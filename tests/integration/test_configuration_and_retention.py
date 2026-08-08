"""Configuration and the inert retention structures, against the real database.

Four properties carry the weight, and all four are enforced by the database rather
than by the code that writes to it. That distinction is the whole point of putting
them here: application-level validation protects against the call sites that exist
today, and every one of these tables will still be here when the call sites are
written by someone who never read this file.

The secret prohibition and the break-glass prohibition are CHECK constraints, so
they hold against a psql session, a migration, an admin screen and a mistake.
`activation_requires_approval` is a CHECK, so a retention policy cannot become
active without a recorded approver. And the seeded flag set is asserted as a whole
— exactly five rows, exact keys, exact values — because "the flags we expect are
present" would pass on a database that also had `ocr.enabled = true`.

The non-delivery is checked here too, and against the live catalogue rather than
the source: no trigger and no rule on any table. A trigger is the one deletion
path a reader of the application code could never find.

Covers: OPS-FLAG-002, OPS-FLAG-003.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

CONFIGURATION_TABLES = (
    "system_settings",
    "feature_flags",
    "retention_policies",
    "legal_holds",
)

# 04:1502-1506. Stated here rather than imported, so this test fails if the seed
# and the approved list diverge — importing the migration's own constant would
# make the assertion "the seed matches the seed".
APPROVED_PHASE_1A_FLAGS = {
    "manual_crop.enabled": True,
    "auto_segmentation.enabled": False,
    "ocr.enabled": False,
    "ai_matching.enabled": False,
    "bank_api.enabled": False,
}


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def connection(migrated_database: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(_psycopg(migrated_database), autocommit=True) as conn:
        try:
            yield conn
        finally:
            # `feature_flags` is deliberately absent: the five seeded rows belong
            # to the migrated database, and a test that cleared them would leave
            # the next one asserting against an empty table.
            for table in (
                "retention_policies",
                "legal_holds",
                "system_settings",
                "admin_users",
            ):
                conn.execute(f"DELETE FROM {table}")


def make_admin(connection: psycopg.Connection, username: str = "config-admin") -> uuid.UUID:
    row = connection.execute(
        "INSERT INTO admin_users (username, full_name, password_hash, status) "
        "VALUES (%s, 'Config Admin', 'argon2id$dummy', 'active') RETURNING id",
        (username,),
    ).fetchone()
    assert row is not None
    return row[0]


SETTING_INSERT = (
    "INSERT INTO system_settings (key, value, value_type, category, status) "
    "VALUES (%(key)s, %(value)s, %(type)s, 'general', 'active') RETURNING id"
)


class TestSecretsCannotBeStoredAsSettings:
    """SEC-SETTINGS-001. `04:1486` prohibits it; this is the enforcement.

    The table is readable by every holder of `system_setting.read`, writable from
    an admin screen, and present in every backup. Those are the right properties
    for a cutoff time and the wrong ones for a credential.
    """

    def test_an_ordinary_setting_is_accepted(self, connection: psycopg.Connection) -> None:
        """Guard the guard: an over-broad pattern would refuse everything."""

        row = connection.execute(
            SETTING_INSERT,
            {"key": "payment.cutoff_hour", "value": "16", "type": "integer"},
        ).fetchone()

        assert row is not None

    @pytest.mark.parametrize(
        "key",
        [
            "bank_api_token",
            "storage_secret_key",
            "smtp_password",
            "sms_provider_credential",
            "jwt_private_key",
            "s3_access_key",
            "field_encryption_key",
            "internal_api_key",
        ],
    )
    def test_a_key_naming_a_credential_is_refused(
        self, connection: psycopg.Connection, key: str
    ) -> None:
        """Substring matching, because the risk is `bank_api_token`, not `secret`."""

        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            connection.execute(SETTING_INSERT, {"key": key, "value": "x", "type": "string"})

        assert "key_is_not_a_secret" in str(raised.value)

    def test_an_uppercase_key_is_refused_so_the_pattern_cannot_be_evaded(
        self, connection: psycopg.Connection
    ) -> None:
        """`LIKE` is case-sensitive, so `BANK_API_TOKEN` would slip past the
        prohibition on its own. The lowercase constraint is what closes that,
        which is why it is not merely a tidiness rule."""

        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            connection.execute(
                SETTING_INSERT,
                {"key": "BANK_API_TOKEN", "value": "x", "type": "string"},
            )

        assert "key_is_lowercase" in str(raised.value)

    def test_an_unknown_value_type_is_refused(self, connection: psycopg.Connection) -> None:
        """Typed rather than parsed: "true"/"True"/"1" disagreements between two
        call sites are decided here instead of by whichever one guessed."""

        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                SETTING_INSERT, {"key": "some.flagish", "value": "yes", "type": "yesno"}
            )


class TestTheSeededFlags:
    """OPS-FLAG-001, asserted against the migrated database."""

    def test_exactly_the_five_approved_rows_exist(self, connection: psycopg.Connection) -> None:
        rows = connection.execute("SELECT flag_key, is_enabled FROM feature_flags").fetchall()

        assert dict(rows) == APPROVED_PHASE_1A_FLAGS

    def test_every_automated_path_is_off(self, connection: psycopg.Connection) -> None:
        """Phase 1A is manual. OCR, segmentation, matching and the bank API all
        ship disabled, and a deployment that enabled one would be the moment an
        unreviewed path started touching financial data."""

        rows = connection.execute(
            "SELECT flag_key FROM feature_flags WHERE is_enabled ORDER BY flag_key"
        ).fetchall()

        assert [row[0] for row in rows] == ["manual_crop.enabled"]

    def test_no_break_glass_flag_exists(self, connection: psycopg.Connection) -> None:
        """SEC-BREAKGLASS-001 at the data level."""

        rows = connection.execute(
            "SELECT flag_key FROM feature_flags WHERE flag_key LIKE '%break%glass%'"
        ).fetchall()

        assert rows == []

    def test_a_break_glass_flag_cannot_be_created_at_runtime(
        self, connection: psycopg.Connection
    ) -> None:
        """The reason the prohibition is a constraint rather than an omission.

        `feature_flag.update` is granted by default to `technical_admin` — the one
        role that must hold no financial authority. Without this CHECK, that role
        could create the bypass through the ordinary configuration screen and
        nothing would have refused it.
        """

        for key in (
            "break_glass_enabled",
            "feature.break_glass",
            "emergency.break_glass.on",
        ):
            with pytest.raises(psycopg.errors.CheckViolation) as raised:
                connection.execute(
                    "INSERT INTO feature_flags (flag_key, is_enabled) VALUES (%s, false)",
                    (key,),
                )
            assert "break_glass_flag_is_prohibited" in str(raised.value)

    def test_re_running_the_seed_neither_fails_nor_duplicates(
        self, connection: psycopg.Connection
    ) -> None:
        """The migrate container runs on every stack start.

        `ON CONFLICT DO NOTHING` rather than an upsert: re-asserting the seeded
        value would silently undo an operator's deliberate change on the next
        deploy, and a configuration that reverts is one nobody can trust.
        """

        connection.execute(
            "UPDATE feature_flags SET is_enabled = true WHERE flag_key = 'ocr.enabled'"
        )
        for key, enabled in APPROVED_PHASE_1A_FLAGS.items():
            connection.execute(
                "INSERT INTO feature_flags (flag_key, is_enabled) VALUES (%s, %s) "
                "ON CONFLICT (flag_key) DO NOTHING",
                (key, enabled),
            )

        total = connection.execute("SELECT count(*) FROM feature_flags").fetchone()
        operator_value = connection.execute(
            "SELECT is_enabled FROM feature_flags WHERE flag_key = 'ocr.enabled'"
        ).fetchone()

        assert total is not None and total[0] == len(APPROVED_PHASE_1A_FLAGS)
        assert operator_value is not None and operator_value[0] is True

        connection.execute(
            "UPDATE feature_flags SET is_enabled = false WHERE flag_key = 'ocr.enabled'"
        )


class TestRetentionPolicyOrdering:
    """The separation of proposer from approver is the control, so it is a CHECK."""

    def propose(
        self, connection: psycopg.Connection, admin: uuid.UUID, **overrides: object
    ) -> uuid.UUID:
        columns = {
            "resource_type": "audit_logs",
            "retention_class": "financial_record",
            "retention_seconds": 220752000,
            "status": "proposed",
            "proposed_by_admin_user_id": admin,
        }
        columns.update(overrides)
        names = ", ".join(columns)
        placeholders = ", ".join(f"%({name})s" for name in columns)
        row = connection.execute(
            f"INSERT INTO retention_policies ({names}) VALUES ({placeholders}) RETURNING id",
            columns,
        ).fetchone()
        assert row is not None
        return row[0]

    def test_a_proposal_is_accepted(self, connection: psycopg.Connection) -> None:
        assert self.propose(connection, make_admin(connection)) is not None

    def test_activation_without_approval_is_refused(self, connection: psycopg.Connection) -> None:
        """The whole workflow in one constraint: nothing becomes active until
        somebody other than the proposer has recorded an approval."""

        admin = make_admin(connection)

        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            self.propose(
                connection,
                admin,
                status="active",
                activated_by_admin_user_id=admin,
                activated_at="2026-08-06 10:00:00+00",
            )

        assert "activation_requires_approval" in str(raised.value)

    def test_an_approval_without_an_approver_is_refused(
        self, connection: psycopg.Connection
    ) -> None:
        """An approval that does not say who approved it cannot be audited."""

        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            self.propose(connection, make_admin(connection), approved_at="2026-08-06 10:00:00+00")

        assert "approval_fields_move_together" in str(raised.value)

    def test_an_approved_policy_may_then_be_activated(self, connection: psycopg.Connection) -> None:
        """Guard the guard: the ordering constraint must permit the legitimate path."""

        admin = make_admin(connection)
        approver = make_admin(connection, username="config-approver")
        policy = self.propose(
            connection,
            admin,
            approved_by_admin_user_id=approver,
            approved_at="2026-08-06 10:00:00+00",
        )

        connection.execute(
            "UPDATE retention_policies SET status = 'active', "
            "activated_by_admin_user_id = %s, activated_at = now() WHERE id = %s",
            (approver, policy),
        )

        row = connection.execute(
            "SELECT status FROM retention_policies WHERE id = %s", (policy,)
        ).fetchone()
        assert row is not None and row[0] == "active"

    def test_reducing_a_retention_duration_deletes_nothing(
        self, connection: psycopg.Connection
    ) -> None:
        """OPS-RETENTION-001, asserted by row counts either side of the change.

        `04:1517`: a reduction creates a new policy version and deletes nothing.
        Editing the duration in place would make the shorter period appear always
        to have applied, and — if anything acted on policies — would put existing
        records past their retention the instant the row was saved.
        """

        admin = make_admin(connection)
        original = self.propose(connection, admin, retention_seconds=220752000)

        before = connection.execute("SELECT count(*) FROM audit_logs").fetchone()
        assert before is not None

        reduced = self.propose(
            connection,
            admin,
            retention_seconds=86400,
            version=2,
            supersedes_id=original,
        )

        after = connection.execute("SELECT count(*) FROM audit_logs").fetchone()
        surviving = connection.execute("SELECT count(*) FROM retention_policies").fetchone()

        assert after is not None and after[0] == before[0]
        # Both versions survive: the chain is the record of what applied when.
        assert surviving is not None and surviving[0] == 2
        assert reduced != original


class TestLegalHolds:
    """CON-010-shape: a hold is placed, and nothing in the system can act past it."""

    def place(self, connection: psycopg.Connection, admin: uuid.UUID) -> uuid.UUID:
        row = connection.execute(
            "INSERT INTO legal_holds (resource_type, resource_id, reason, "
            "placed_by_admin_user_id) VALUES ('audit_logs', %s, 'court order 1404/۳۲۱', %s) "
            "RETURNING id",
            (uuid.uuid4(), admin),
        ).fetchone()
        assert row is not None
        return row[0]

    def test_a_hold_can_be_placed(self, connection: psycopg.Connection) -> None:
        assert self.place(connection, make_admin(connection)) is not None

    def test_a_blank_reason_is_refused(self, connection: psycopg.Connection) -> None:
        """A hold nobody can explain is a hold nobody can defend releasing."""

        admin = make_admin(connection)

        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO legal_holds (resource_type, reason, placed_by_admin_user_id) "
                "VALUES ('audit_logs', '   ', %s)",
                (admin,),
            )

    def test_releasing_without_a_reason_or_an_actor_is_refused(
        self, connection: psycopg.Connection
    ) -> None:
        """Releasing is the act that would allow a deletion, so it records who and
        why, or it does not happen."""

        admin = make_admin(connection)
        hold = self.place(connection, admin)

        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            connection.execute("UPDATE legal_holds SET released_at = now() WHERE id = %s", (hold,))

        assert "release_fields_move_together" in str(raised.value)

    def test_a_complete_release_is_accepted(self, connection: psycopg.Connection) -> None:
        admin = make_admin(connection)
        hold = self.place(connection, admin)

        connection.execute(
            "UPDATE legal_holds SET released_at = now(), released_by_admin_user_id = %s, "
            "release_reason = 'matter closed' WHERE id = %s",
            (admin, hold),
        )

        row = connection.execute(
            "SELECT released_at IS NOT NULL FROM legal_holds WHERE id = %s", (hold,)
        ).fetchone()
        assert row is not None and row[0] is True

    def test_the_active_index_excludes_released_holds(self, connection: psycopg.Connection) -> None:
        """The lookup a deletion path would perform, if one existed. Partial, so a
        released hold leaves the index rather than being filtered out of it."""

        row = connection.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_legal_holds_active'"
        ).fetchone()

        assert row is not None
        assert "released_at IS NULL" in row[0]


class TestNothingActsOnAnyOfThis:
    """OPS-RETENTION-002, asserted against the live catalogue.

    The source-level half of this lives in
    `tests/backend/test_no_deletion_machinery.py`. This half asks the database
    what it will do on its own, which is the part no amount of reading the
    application code can answer.
    """

    def test_no_table_carries_a_trigger(self, connection: psycopg.Connection) -> None:
        """Excludes the internal triggers PostgreSQL creates for foreign keys.

        A trigger is the worst deletion path there is: no call site, so nothing to
        find by reading, and it fires for psql exactly as it fires for the
        application.
        """

        rows = connection.execute(
            "SELECT c.relname, t.tgname FROM pg_trigger t "
            "JOIN pg_class c ON c.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND NOT t.tgisinternal"
        ).fetchall()

        assert rows == [], f"triggers exist: {rows}"

    def test_no_table_carries_a_rewrite_rule(self, connection: psycopg.Connection) -> None:
        """A rule can turn an ordinary UPDATE into a DELETE with nothing at the
        call site to suggest it. `_RETURN` is the view rule and is not one."""

        rows = connection.execute(
            "SELECT tablename, rulename FROM pg_rules WHERE schemaname = 'public'"
        ).fetchall()

        assert rows == [], f"rewrite rules exist: {rows}"

    def test_nothing_has_expired_the_idempotency_records(
        self, connection: psycopg.Connection
    ) -> None:
        """`expires_at` exists with an index and nothing acts on it, deliberately.

        Sweeping it would destroy precisely the rows that prove no duplicate
        financial command was accepted, and would do it silently. Inserting one
        already past its expiry and finding it still present is the assertion.
        """

        # `created_at` is set explicitly and further back than `expires_at`: the
        # table's own `expires_after_creation` CHECK would otherwise refuse a row
        # that expired before it was written.
        connection.execute(
            "INSERT INTO idempotency_records (idempotency_key, actor_type, actor_id, "
            "operation, request_hash, status, created_at, expires_at) VALUES "
            "('expired-key', 'admin_user', gen_random_uuid(), 'center_profile.rename', "
            f"'{'a' * 64}', 'completed', now() - interval '60 days', "
            "now() - interval '30 days')"
        )
        try:
            row = connection.execute(
                "SELECT count(*) FROM idempotency_records WHERE idempotency_key = 'expired-key'"
            ).fetchone()

            assert row is not None and row[0] == 1
        finally:
            connection.execute(
                "DELETE FROM idempotency_records WHERE idempotency_key = 'expired-key'"
            )


class TestTheConfigurationTablesAreWritableByTheRuntime:
    """All four are current state, so all four are mutable — unlike `audit_logs`.

    Connected as the app role rather than the owner: run as owner every one of
    these passes on a database with no grants at all.
    """

    @pytest.fixture
    def migrated_as_migrator(self, provisioned_database: RuntimeIdentities) -> RuntimeIdentities:
        result = run_alembic(
            provisioned_database.migrator_url,
            "upgrade",
            "head",
            app_role=provisioned_database.app_role,
            worker_role=provisioned_database.worker_role,
        )
        assert result.returncode == 0, (
            f"migration failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        return provisioned_database

    @pytest.mark.parametrize("table", CONFIGURATION_TABLES)
    def test_the_app_role_may_update_and_delete(
        self, migrated_as_migrator: RuntimeIdentities, table: str
    ) -> None:
        with psycopg.connect(migrated_as_migrator.app_url) as connection:
            row = connection.execute(
                "SELECT has_table_privilege(%(t)s, 'UPDATE'), has_table_privilege(%(t)s, 'DELETE')",
                {"t": table},
            ).fetchone()

        assert row is not None
        assert row[0] is True, f"{table} holds current state and must be correctable"
        assert row[1] is True, f"{table} holds current state and must be correctable"

    def test_the_app_role_still_may_not_touch_the_audit_log(
        self, migrated_as_migrator: RuntimeIdentities
    ) -> None:
        """Guard the guard: the grants above must not have widened anything else.

        Granting per table is what keeps this true — a blanket grant across the
        schema would have taken `audit_logs` and `auth_events` with it.
        """

        with psycopg.connect(migrated_as_migrator.app_url) as connection:
            row = connection.execute(
                "SELECT has_table_privilege('audit_logs', 'UPDATE'), "
                "has_table_privilege('audit_logs', 'DELETE'), "
                "has_table_privilege('auth_events', 'UPDATE'), "
                "has_table_privilege('auth_events', 'DELETE')"
            ).fetchone()

        assert row is not None
        assert row == (False, False, False, False)

    def test_the_seeded_flags_are_visible_to_the_runtime(
        self, migrated_as_migrator: RuntimeIdentities
    ) -> None:
        """A seed the application cannot read is a seed that does not exist."""

        with psycopg.connect(migrated_as_migrator.app_url) as connection:
            rows = connection.execute("SELECT flag_key, is_enabled FROM feature_flags").fetchall()

        assert dict(rows) == APPROVED_PHASE_1A_FLAGS
