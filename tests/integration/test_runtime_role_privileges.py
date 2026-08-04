"""What each runtime identity can actually do, connected as that identity.

Run through the owner connection every one of these passes trivially: the owner
may do anything, so "must be refused" is never refused and the test reports
success for a database with no protection at all. So each test opens a real
login as the role under test.

The chain is the production one end to end. The bootstrap SQL the Compose stack
runs is replayed against a disposable database, then Alembic runs **as the
migration role** — not as the owner — because `ALTER DEFAULT PRIVILEGES FOR ROLE
<migrator>` only applies to tables that role creates. Migrating as the owner
would produce tables no default privilege touched, and the grant assertions
below would be measuring an empty ACL.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration


@pytest.fixture
def migrated_as_migrator(provisioned_database: RuntimeIdentities) -> RuntimeIdentities:
    result = run_alembic(
        provisioned_database.migrator_url,
        "upgrade",
        "head",
        app_role=provisioned_database.app_role,
        worker_role=provisioned_database.worker_role,
    )
    assert result.returncode == 0, (
        "the migration role could not migrate the database it is provisioned to "
        f"migrate.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return provisioned_database


def privileges(url: str, table: str) -> dict[str, bool]:
    """Ask the database what the *connected* role holds, not what we assume."""

    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT has_table_privilege(%(t)s, 'SELECT'), has_table_privilege(%(t)s, 'INSERT'), "
            "has_table_privilege(%(t)s, 'UPDATE'), has_table_privilege(%(t)s, 'DELETE')",
            {"t": table},
        ).fetchone()
    assert row is not None
    return dict(zip(("SELECT", "INSERT", "UPDATE", "DELETE"), row, strict=True))


AUDIT_INSERT = (
    "INSERT INTO audit_logs (action, outcome, actor_type, actor_id, metadata_schema, "
    "metadata_version) VALUES ('center_profile.renamed', 'success', 'admin_user', "
    "gen_random_uuid(), 'audit.test', 1)"
)


class TestTheFixtureItselfIsHonest:
    """If provisioning silently did nothing, every test below would pass vacuously."""

    def test_the_three_roles_exist_and_can_connect(
        self, provisioned_database: RuntimeIdentities
    ) -> None:
        for url, expected in (
            (provisioned_database.migrator_url, provisioned_database.migrator_role),
            (provisioned_database.app_url, provisioned_database.app_role),
            (provisioned_database.worker_url, provisioned_database.worker_role),
        ):
            with psycopg.connect(url) as connection:
                current = connection.execute("SELECT current_user").fetchone()
            assert current is not None and current[0] == expected

    def test_the_roles_are_not_superusers(
        self, provisioned_database: RuntimeIdentities
    ) -> None:
        """A superuser bypasses every grant, so the whole suite would be theatre."""

        with psycopg.connect(provisioned_database.owner_url) as connection:
            rows = connection.execute(
                "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles "
                "WHERE rolname = ANY(%s)",
                (
                    [
                        provisioned_database.migrator_role,
                        provisioned_database.app_role,
                        provisioned_database.worker_role,
                    ],
                ),
            ).fetchall()

        assert len(rows) == 3
        for name, is_super, can_create_db, can_create_role in rows:
            assert not is_super, f"{name} is a superuser"
            assert not can_create_db, f"{name} may create databases"
            assert not can_create_role, f"{name} may create roles"

    def test_default_privileges_were_actually_recorded(
        self, provisioned_database: RuntimeIdentities
    ) -> None:
        """`020-runtime-roles.sql` warns about this exact vacuous pass.

        pg_default_acl rows live in the database the ALTER ran in, so a database
        that never replayed the file has none — and the append-only assertions
        would then be measuring a grant that was never made.
        """

        with psycopg.connect(provisioned_database.owner_url) as connection:
            count = connection.execute("SELECT count(*) FROM pg_default_acl").fetchone()

        assert count is not None and count[0] > 0, (
            "no default ACLs exist, so the bootstrap replay did nothing and the "
            "privilege tests below would prove nothing"
        )


class TestMigrationRole:
    def test_it_can_create_the_schema(self, migrated_as_migrator: RuntimeIdentities) -> None:
        with psycopg.connect(migrated_as_migrator.migrator_url) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                )
            }
        assert {"audit_logs", "outbox_events", "idempotency_records", "center_profile"} <= tables

    def test_it_cannot_create_a_database(
        self, migrated_as_migrator: RuntimeIdentities
    ) -> None:
        """NOCREATEDB, so a compromised migrator cannot provision itself an escape."""

        with psycopg.connect(
            migrated_as_migrator.migrator_url, autocommit=True
        ) as connection, pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("CREATE DATABASE escape_hatch")


class TestAppRoleOnAuditLogs:
    """SEC-ROLE-001 / 002: the writer must not be able to edit what it wrote."""

    def test_it_may_insert(self, migrated_as_migrator: RuntimeIdentities) -> None:
        with psycopg.connect(migrated_as_migrator.app_url, autocommit=True) as connection:
            connection.execute(AUDIT_INSERT)
            count = connection.execute("SELECT count(*) FROM audit_logs").fetchone()
        assert count is not None and count[0] == 1

    def test_it_may_not_update(self, migrated_as_migrator: RuntimeIdentities) -> None:
        with psycopg.connect(migrated_as_migrator.app_url, autocommit=True) as connection:
            connection.execute(AUDIT_INSERT)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("UPDATE audit_logs SET outcome = 'tampered'")

    def test_it_may_not_delete(self, migrated_as_migrator: RuntimeIdentities) -> None:
        with psycopg.connect(migrated_as_migrator.app_url, autocommit=True) as connection:
            connection.execute(AUDIT_INSERT)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("DELETE FROM audit_logs")

    def test_the_privilege_bits_agree_with_the_behaviour(
        self, migrated_as_migrator: RuntimeIdentities
    ) -> None:
        held = privileges(migrated_as_migrator.app_url, "audit_logs")

        assert held == {"SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False}


class TestWorkerRoleOnAuditLogs:
    """SEC-ROLE-003: least privilege must not break worker-side atomicity."""

    def test_it_may_insert(self, migrated_as_migrator: RuntimeIdentities) -> None:
        """A worker writes audit in the same transaction as its own work.

        Revoking INSERT here would force the worker to either skip audit or
        commit its change without one, which is the failure the whole design
        exists to prevent.
        """

        with psycopg.connect(migrated_as_migrator.worker_url, autocommit=True) as connection:
            connection.execute(AUDIT_INSERT)
            count = connection.execute("SELECT count(*) FROM audit_logs").fetchone()
        assert count is not None and count[0] == 1

    def test_it_may_not_update_or_delete(
        self, migrated_as_migrator: RuntimeIdentities
    ) -> None:
        with psycopg.connect(migrated_as_migrator.worker_url, autocommit=True) as connection:
            connection.execute(AUDIT_INSERT)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("UPDATE audit_logs SET outcome = 'tampered'")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("DELETE FROM audit_logs")


class TestTheRevokeIsTargeted:
    """Only audit_logs is append-only. Locking everything down would break the app."""

    @pytest.mark.parametrize("table", ["outbox_events", "idempotency_records", "center_profile"])
    def test_mutable_tables_stay_mutable_for_the_app(
        self, migrated_as_migrator: RuntimeIdentities, table: str
    ) -> None:
        held = privileges(migrated_as_migrator.app_url, table)

        assert held["UPDATE"] is True, (
            f"{table} is not append-only; a dispatcher must move an outbox event "
            "through its lifecycle and an idempotency record must be completable"
        )

    def test_the_worker_can_advance_an_outbox_event(
        self, migrated_as_migrator: RuntimeIdentities
    ) -> None:
        """The dispatcher is worker-side, so this is the privilege it lives on."""

        with psycopg.connect(migrated_as_migrator.worker_url, autocommit=True) as connection:
            connection.execute(
                "INSERT INTO outbox_events (aggregate_type, aggregate_id, aggregate_version, "
                "event_type, payload, payload_version) VALUES "
                "('center_profile', gen_random_uuid(), 1, 'CenterProfileRenamed', '{}', 1)"
            )
            connection.execute(
                "UPDATE outbox_events SET status = 'published', published_at = now()"
            )
            status = connection.execute("SELECT status FROM outbox_events").fetchone()

        assert status is not None and status[0] == "published"


class TestGrantsNameTheIdentityThatConnects:
    """SEC-ROLE-000. Without this, every assertion in this file can pass vacuously.

    A migration that granted to a literal `platform_app` would constrain a role
    nothing connects as. Every "must be refused" test would still pass — because
    the real role was never granted anything — and the evidence would be false in
    the most convincing possible way.
    """

    def test_the_granted_role_is_the_one_in_the_connection_string(
        self, migrated_as_migrator: RuntimeIdentities
    ) -> None:
        granted = urlsplit(migrated_as_migrator.app_url).username

        assert granted == migrated_as_migrator.app_role, (
            "the role the migration granted to is not the username the application "
            "connects as, so the grant constrains a different identity"
        )

        with psycopg.connect(migrated_as_migrator.app_url) as connection:
            connected = connection.execute("SELECT current_user").fetchone()
        assert connected is not None and connected[0] == granted

    def test_the_grant_actually_reached_that_role(
        self, migrated_as_migrator: RuntimeIdentities
    ) -> None:
        """Read the ACL back by name, rather than trusting the statement ran."""

        with psycopg.connect(migrated_as_migrator.owner_url) as connection:
            grantees = {
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT grantee FROM information_schema.role_table_grants "
                    "WHERE table_schema = 'public' AND table_name = 'center_profile' "
                    "AND privilege_type = 'UPDATE'"
                )
            }

        assert migrated_as_migrator.app_role in grantees
        assert migrated_as_migrator.worker_role in grantees


class TestReadOnlyRole:
    """SEC-ROLE-005, first half."""

    def test_it_can_read(self, migrated_as_migrator: RuntimeIdentities) -> None:
        with psycopg.connect(migrated_as_migrator.readonly_url) as connection:
            count = connection.execute("SELECT count(*) FROM center_profile").fetchone()
        assert count is not None

    @pytest.mark.parametrize(
        "statement",
        [
            "INSERT INTO center_profile (name, status) VALUES ('x', 'active')",
            "UPDATE center_profile SET name = 'x'",
            "DELETE FROM center_profile",
        ],
    )
    def test_it_cannot_write(
        self, migrated_as_migrator: RuntimeIdentities, statement: str
    ) -> None:
        with psycopg.connect(
            migrated_as_migrator.readonly_url, autocommit=True
        ) as connection, pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(statement)

    def test_it_cannot_write_to_audit_either(
        self, migrated_as_migrator: RuntimeIdentities
    ) -> None:
        """Not covered by the append-only revoke: this role never had INSERT."""

        with psycopg.connect(
            migrated_as_migrator.readonly_url, autocommit=True
        ) as connection, pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(AUDIT_INSERT)


class TestBackupRole:
    """SEC-ROLE-005, second half. The role exists; no backup claim rides on it."""

    @pytest.mark.parametrize(
        "table", ["audit_logs", "outbox_events", "idempotency_records", "center_profile"]
    )
    def test_it_can_read_audit_and_business_data(
        self, migrated_as_migrator: RuntimeIdentities, table: str
    ) -> None:
        """A dump that silently omits audit history is not a usable backup."""

        with psycopg.connect(migrated_as_migrator.backup_url) as connection:
            count = connection.execute(f"SELECT count(*) FROM {table}").fetchone()
        assert count is not None

    @pytest.mark.parametrize(
        "statement",
        [
            "INSERT INTO center_profile (name, status) VALUES ('x', 'active')",
            "UPDATE center_profile SET name = 'x'",
            "DELETE FROM center_profile",
        ],
    )
    def test_it_cannot_write(
        self, migrated_as_migrator: RuntimeIdentities, statement: str
    ) -> None:
        with psycopg.connect(
            migrated_as_migrator.backup_url, autocommit=True
        ) as connection, pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(statement)


class TestTheDefaultIsFailClosed:
    """A table nobody grants on must be immutable, not writable.

    This is the property the narrowed `ALTER DEFAULT PRIVILEGES` buys. It matters
    for tables that do not exist yet: `auth_events` in slice 6 and the approval
    tables in M7 are append-only, and under the old default each would have
    inherited UPDATE and DELETE simply by being created.
    """

    def test_a_newly_created_table_is_not_writable_by_the_runtime_roles(
        self, migrated_as_migrator: RuntimeIdentities
    ) -> None:
        with psycopg.connect(migrated_as_migrator.migrator_url, autocommit=True) as connection:
            connection.execute("CREATE TABLE future_append_only (id integer)")

        for url in (migrated_as_migrator.app_url, migrated_as_migrator.worker_url):
            with psycopg.connect(url) as connection:
                row = connection.execute(
                    "SELECT has_table_privilege('future_append_only', 'INSERT'), "
                    "has_table_privilege('future_append_only', 'UPDATE'), "
                    "has_table_privilege('future_append_only', 'DELETE')"
                ).fetchone()
            assert row is not None
            can_insert, can_update, can_delete = row
            assert can_insert is True, "a new table should still be writable-once"
            assert can_update is False, (
                "a table nobody granted UPDATE on inherited it, so the default is "
                "still open and the next append-only table will be mutable"
            )
            assert can_delete is False

    def test_the_sequence_default_does_not_include_update(
        self, migrated_as_migrator: RuntimeIdentities
    ) -> None:
        """UPDATE on a sequence is setval.

        On `audit_logs.sequence_number` that would let a writer rewind the
        ordering key and reissue values it had already used, which breaks cursor
        pagination in a way no row-level constraint can catch.
        """

        with psycopg.connect(migrated_as_migrator.app_url) as connection:
            row = connection.execute(
                "SELECT has_sequence_privilege('audit_logs_sequence_number_seq', 'USAGE'), "
                "has_sequence_privilege('audit_logs_sequence_number_seq', 'UPDATE')"
            ).fetchone()

        assert row is not None
        can_use, can_setval = row
        assert can_use is True, "the app must be able to consume the sequence"
        assert can_setval is False


class TestSchemaOwnership:
    def test_neither_runtime_role_may_create_tables(
        self, migrated_as_migrator: RuntimeIdentities
    ) -> None:
        """DDL belongs to migrations. A runtime role that can CREATE can also
        create a table the migration harness does not know about, and autogenerate
        would later propose dropping it."""

        for url in (migrated_as_migrator.app_url, migrated_as_migrator.worker_url):
            with psycopg.connect(url, autocommit=True) as connection, pytest.raises(
                psycopg.errors.InsufficientPrivilege
            ):
                connection.execute("CREATE TABLE smuggled (id integer)")

    def test_neither_runtime_role_may_drop_an_audit_row_by_truncation(
        self, migrated_as_migrator: RuntimeIdentities
    ) -> None:
        """TRUNCATE is not DELETE and is not covered by revoking DELETE.

        It is owner-only by default, but asserting it keeps a future grant from
        quietly reopening the path that revoking DELETE was meant to close.
        """

        for url in (migrated_as_migrator.app_url, migrated_as_migrator.worker_url):
            with psycopg.connect(url, autocommit=True) as connection, pytest.raises(
                psycopg.errors.InsufficientPrivilege
            ):
                connection.execute("TRUNCATE audit_logs")
