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

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration


@pytest.fixture
def migrated_as_migrator(provisioned_database: RuntimeIdentities) -> RuntimeIdentities:
    result = run_alembic(provisioned_database.migrator_url, "upgrade", "head")
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
