"""Sessions, security events and recent-auth contexts, against the real database.

Three properties carry the weight here, and each is a constraint rather than a
convention — a convention is what the code does today, and M3 has to be able to
rely on what the database refuses.

Covers: DB-IDENTITY-002, SEC-RECENTAUTH-001, SEC-SOD-001, SEC-STAMP-001.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from bootstrap_replay import RuntimeIdentities

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

pytestmark = pytest.mark.integration


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def connection(migrated_database: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(_psycopg(migrated_database), autocommit=True) as conn:
        try:
            yield conn
        finally:
            for table in (
                "audit_logs",
                "recent_auth_contexts",
                "auth_sessions",
                "auth_events",
                "admin_users",
                "trader_users",
            ):
                conn.execute(f"DELETE FROM {table}")


def make_admin(connection: psycopg.Connection, username: str = "admin-one") -> uuid.UUID:
    row = connection.execute(
        "INSERT INTO admin_users (username, full_name, password_hash, status) "
        "VALUES (%s, 'Admin One', 'argon2id$dummy', 'active') RETURNING id",
        (username,),
    ).fetchone()
    assert row is not None
    return row[0]


def make_trader(connection: psycopg.Connection, phone: str = "09120000001") -> uuid.UUID:
    row = connection.execute(
        "INSERT INTO trader_users (phone_number, full_name, password_hash, status) "
        "VALUES (%s, 'Trader One', 'argon2id$dummy', 'active') RETURNING id",
        (phone,),
    ).fetchone()
    assert row is not None
    return row[0]


SESSION_INSERT = (
    "INSERT INTO auth_sessions "
    "(admin_user_id, trader_user_id, secret_hash, auth_level, expires_at) "
    "VALUES (%(admin)s, %(trader)s, %(hash)s, 'password', now() + interval '1 hour') "
    "RETURNING id"
)


class TestExactlyOneActor:
    """The constraint M3's cross-surface rejection test depends on."""

    def test_an_admin_session_is_accepted(self, connection: psycopg.Connection) -> None:
        admin = make_admin(connection)

        row = connection.execute(
            SESSION_INSERT, {"admin": admin, "trader": None, "hash": "h1"}
        ).fetchone()

        assert row is not None

    def test_a_trader_session_is_accepted(self, connection: psycopg.Connection) -> None:
        trader = make_trader(connection)

        row = connection.execute(
            SESSION_INSERT, {"admin": None, "trader": trader, "hash": "h2"}
        ).fetchone()

        assert row is not None

    def test_a_session_with_both_actors_is_refused(
        self, connection: psycopg.Connection
    ) -> None:
        """The row that would satisfy an admin authorisation query and a trader one.

        Without this constraint, M3's proof that admin sessions are rejected on
        trader surfaces is unfalsifiable — one row would pass both checks.
        """

        admin = make_admin(connection)
        trader = make_trader(connection)

        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            connection.execute(
                SESSION_INSERT, {"admin": admin, "trader": trader, "hash": "h3"}
            )

        assert "exactly_one_actor" in str(raised.value)

    def test_a_session_with_no_actor_is_refused(
        self, connection: psycopg.Connection
    ) -> None:
        """An unattributed session is authority belonging to nobody."""

        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                SESSION_INSERT, {"admin": None, "trader": None, "hash": "h4"}
            )


class TestSessionIntegrity:
    def test_the_secret_hash_is_unique(self, connection: psycopg.Connection) -> None:
        """Two sessions sharing a hash would let one secret present as either."""

        admin = make_admin(connection)
        connection.execute(SESSION_INSERT, {"admin": admin, "trader": None, "hash": "same"})

        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(
                SESSION_INSERT, {"admin": admin, "trader": None, "hash": "same"}
            )

    def test_a_revoked_session_must_say_why(
        self, connection: psycopg.Connection
    ) -> None:
        """Revoked with no reason is the state that stalls an incident review."""

        admin = make_admin(connection)
        connection.execute(SESSION_INSERT, {"admin": admin, "trader": None, "hash": "h5"})

        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            connection.execute("UPDATE auth_sessions SET revoked_at = now()")

        assert "revocation_fields_move_together" in str(raised.value)

    def test_revoking_with_a_reason_is_accepted(
        self, connection: psycopg.Connection
    ) -> None:
        admin = make_admin(connection)
        connection.execute(SESSION_INSERT, {"admin": admin, "trader": None, "hash": "h6"})

        connection.execute(
            "UPDATE auth_sessions SET revoked_at = now(), revocation_reason = 'password_changed'"
        )

    def test_a_session_cannot_expire_before_it_begins(
        self, connection: psycopg.Connection
    ) -> None:
        admin = make_admin(connection)

        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO auth_sessions "
                "(admin_user_id, secret_hash, auth_level, authenticated_at, expires_at) "
                "VALUES (%s, 'h7', 'password', now(), now() - interval '1 hour')",
                (admin,),
            )

    def test_a_session_cannot_replace_itself(
        self, connection: psycopg.Connection
    ) -> None:
        """A self-referencing rotation chain has no end, so revoking one never
        reaches the rest."""

        admin = make_admin(connection)
        row = connection.execute(
            SESSION_INSERT, {"admin": admin, "trader": None, "hash": "h8"}
        ).fetchone()
        assert row is not None

        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE auth_sessions SET replaced_session_id = id WHERE id = %s", (row[0],)
            )


class TestSecurityEvents:
    def test_a_failed_login_for_an_unknown_identity_is_recordable(
        self, connection: psycopg.Connection
    ) -> None:
        """The case that matters most, and the reason auth_events has no
        human-actor-is-identified check.

        Somebody tried a username that does not exist. Requiring an actor id
        would mean either discarding the event or inventing an identity.
        """

        connection.execute(
            "INSERT INTO auth_events "
            "(actor_type, actor_id, event_type, event_class, outcome, "
            "metadata_schema, metadata_version) "
            "VALUES ('admin_user', NULL, 'login_failed', 'authentication', 'failure', "
            "'security.v1', 1)"
        )

        count = connection.execute("SELECT count(*) FROM auth_events").fetchone()
        assert count is not None and count[0] == 1

    def test_an_unknown_event_class_is_refused(
        self, connection: psycopg.Connection
    ) -> None:
        """The class drives alerting and retention, so an unrecognised one would
        route a security event nowhere."""

        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            connection.execute(
                "INSERT INTO auth_events "
                "(actor_type, event_type, event_class, outcome, metadata_schema, "
                "metadata_version) VALUES "
                "('admin_user', 'x', 'not_a_class', 'failure', 'security.v1', 1)"
            )

        assert "event_class" in str(raised.value)

    def test_the_runtime_role_cannot_rewrite_a_security_event(
        self, provisioned_database: RuntimeIdentities
    ) -> None:
        """Append-only, by the same fail-closed default as audit_logs.

        A record of a failed login that the failing process can erase is not a
        record. `auth_events` receives no UPDATE grant, so this is the default
        rather than a revoke.
        """

        from alembic_runner import run_alembic

        result = run_alembic(
            provisioned_database.migrator_url,
            "upgrade",
            "head",
            app_role=provisioned_database.app_role,
            worker_role=provisioned_database.worker_role,
        )
        assert result.returncode == 0, result.stderr

        with psycopg.connect(_psycopg(provisioned_database.app_url)) as app:
            row = app.execute(
                "SELECT has_table_privilege('auth_events', 'INSERT'), "
                "has_table_privilege('auth_events', 'UPDATE'), "
                "has_table_privilege('auth_events', 'DELETE')"
            ).fetchone()

        assert row is not None
        can_insert, can_update, can_delete = row
        assert can_insert is True, "the runtime must still be able to record events"
        assert can_update is False
        assert can_delete is False

    def test_sessions_stay_mutable_for_the_runtime_role(
        self, provisioned_database: RuntimeIdentities
    ) -> None:
        """The contrast that proves the split is deliberate rather than blanket.

        A session must be revocable; if the append-only treatment had been
        applied to everything, revocation would fail at the database.
        """

        from alembic_runner import run_alembic

        assert (
            run_alembic(
                provisioned_database.migrator_url,
                "upgrade",
                "head",
                app_role=provisioned_database.app_role,
                worker_role=provisioned_database.worker_role,
            ).returncode
            == 0
        )

        with psycopg.connect(_psycopg(provisioned_database.app_url)) as app:
            row = app.execute(
                "SELECT has_table_privilege('auth_sessions', 'UPDATE'), "
                "has_table_privilege('recent_auth_contexts', 'UPDATE')"
            ).fetchone()

        assert row == (True, True)


class TestRecentAuthContexts:
    def make_context(
        self,
        connection: psycopg.Connection,
        *,
        purpose: str = "payment_batch_version.approve",
        resource: uuid.UUID | None = None,
        challenge: str = "c1",
    ) -> tuple[uuid.UUID, uuid.UUID]:
        admin = make_admin(connection, username=f"admin-{uuid.uuid4().hex[:8]}")
        session_row = connection.execute(
            SESSION_INSERT,
            {"admin": admin, "trader": None, "hash": f"h-{uuid.uuid4().hex[:8]}"},
        ).fetchone()
        assert session_row is not None

        row = connection.execute(
            "INSERT INTO recent_auth_contexts "
            "(session_id, actor_type, actor_id, purpose, resource_type, resource_id, "
            "assurance_factor, challenge_hash, expires_at) VALUES "
            "(%s, 'admin_user', %s, %s, 'payment_batch_version', %s, 'otp', %s, "
            "now() + interval '5 minutes') RETURNING id",
            (
                session_row[0],
                admin,
                purpose,
                resource or uuid.uuid4(),
                challenge,
            ),
        ).fetchone()
        assert row is not None
        return row[0], admin

    def test_a_context_is_bound_to_one_resource(
        self, connection: psycopg.Connection
    ) -> None:
        """An assurance for approving version 7 must not authorise version 8.

        Both resource columns are NOT NULL, so a general-purpose assurance —
        the thing step-up exists to avoid — cannot be stored.
        """

        with pytest.raises(psycopg.errors.NotNullViolation):
            admin = make_admin(connection, username="admin-unbound")
            session_row = connection.execute(
                SESSION_INSERT, {"admin": admin, "trader": None, "hash": "hb"}
            ).fetchone()
            assert session_row is not None
            connection.execute(
                "INSERT INTO recent_auth_contexts "
                "(session_id, actor_type, actor_id, purpose, resource_type, "
                "assurance_factor, challenge_hash, expires_at) VALUES "
                "(%s, 'admin_user', %s, 'approve', 'batch', 'otp', 'hb2', "
                "now() + interval '5 minutes')",
                (session_row[0], admin),
            )

    def test_consumption_records_which_command_used_it(
        self, connection: psycopg.Connection
    ) -> None:
        """"Consumed" without naming the consumer cannot answer an incident review."""

        context_id, _admin = self.make_context(connection)

        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            connection.execute(
                "UPDATE recent_auth_contexts SET consumed_at = now() WHERE id = %s",
                (context_id,),
            )

        assert "consumption_fields_move_together" in str(raised.value)

    def test_a_fully_recorded_consumption_is_accepted(
        self, connection: psycopg.Connection
    ) -> None:
        context_id, _admin = self.make_context(connection)

        connection.execute(
            "UPDATE recent_auth_contexts SET consumed_at = now(), "
            "consumed_by_command = 'payment_batch_version.approve' WHERE id = %s",
            (context_id,),
        )

    def test_the_challenge_hash_is_unique(self, connection: psycopg.Connection) -> None:
        """Two contexts sharing a challenge would let one proof consume either."""

        self.make_context(connection, challenge="shared")

        with pytest.raises(psycopg.errors.UniqueViolation):
            self.make_context(connection, challenge="shared")

    def test_a_context_cannot_expire_before_issue(
        self, connection: psycopg.Connection
    ) -> None:
        admin = make_admin(connection, username="admin-expiry")
        session_row = connection.execute(
            SESSION_INSERT, {"admin": admin, "trader": None, "hash": "he"}
        ).fetchone()
        assert session_row is not None

        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO recent_auth_contexts "
                "(session_id, actor_type, actor_id, purpose, resource_type, resource_id, "
                "assurance_factor, challenge_hash, issued_at, expires_at) VALUES "
                "(%s, 'admin_user', %s, 'approve', 'batch', gen_random_uuid(), 'otp', "
                "'he2', now(), now() - interval '1 minute')",
                (session_row[0], admin),
            )


class TestTheDeferredAuditForeignKey:
    """Slice 1 declared the column without its FK. This attaches it."""

    def test_an_audit_row_can_reference_a_real_context(
        self, connection: psycopg.Connection
    ) -> None:
        helper = TestRecentAuthContexts()
        context_id, admin = helper.make_context(connection)

        connection.execute(
            "INSERT INTO audit_logs "
            "(action, outcome, actor_type, actor_id, recent_auth_context_id, "
            "metadata_schema, metadata_version) VALUES "
            "('payment_batch_version.approved', 'success', 'admin_user', %s, %s, "
            "'audit.v1', 1)",
            (admin, context_id),
        )

        count = connection.execute("SELECT count(*) FROM audit_logs").fetchone()
        assert count is not None and count[0] == 1

    def test_an_audit_row_cannot_invent_a_context(
        self, connection: psycopg.Connection
    ) -> None:
        """Before this revision the column accepted any UUID, so an audit row
        could claim an assurance that never existed."""

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                "INSERT INTO audit_logs "
                "(action, outcome, actor_type, actor_id, recent_auth_context_id, "
                "metadata_schema, metadata_version) VALUES "
                "('x.y', 'success', 'admin_user', gen_random_uuid(), gen_random_uuid(), "
                "'audit.v1', 1)"
            )

    def test_a_referenced_context_cannot_be_deleted(
        self, connection: psycopg.Connection
    ) -> None:
        """No ON DELETE CASCADE: removing the context would erase the evidence of
        which assurance authorised the change."""

        helper = TestRecentAuthContexts()
        context_id, admin = helper.make_context(connection)
        connection.execute(
            "INSERT INTO audit_logs "
            "(action, outcome, actor_type, actor_id, recent_auth_context_id, "
            "metadata_schema, metadata_version) VALUES "
            "('x.y', 'success', 'admin_user', %s, %s, 'audit.v1', 1)",
            (admin, context_id),
        )

        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                "DELETE FROM recent_auth_contexts WHERE id = %s", (context_id,)
            )

    def test_an_audit_row_without_a_context_is_still_valid(
        self, connection: psycopg.Connection
    ) -> None:
        """Most commands need no step-up, so the column stays nullable."""

        connection.execute(
            "INSERT INTO audit_logs "
            "(action, outcome, actor_type, actor_id, metadata_schema, metadata_version) "
            "VALUES ('center_profile.renamed', 'success', 'admin_user', "
            "gen_random_uuid(), 'audit.v1', 1)"
        )
