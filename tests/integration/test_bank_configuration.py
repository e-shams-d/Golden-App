"""Bank configuration against the real database: scopes, cycles, and immutability.

Four properties, and each one is a trap the plan names explicitly:

**The uniqueness scopes.** A globally scoped mapping unique forbids having an import
mapping and an export mapping at `template_version` 1, and the failure arrives during
the first export rather than here. Dropping `UNIQUE(bank_profile_id, config_hash)`
lets an operator recreate an identical configuration as a "new" version and lose the
audit link between a batch and the configuration that produced it. Both directions
are asserted.

**The pointer cycle.** A profile and its first version must be insertable in one
transaction, which requires the foreign key to be deferred — and the pointer must be
constrained to a version *of this profile*, which requires it to be composite and
correctly ordered. The reversed-order case is asserted too, because without it the
first assertion only proves *an* FK exists.

**Immutability by column-level grant.** `bank_profile_versions` and `bank_mappings`
are snapshots: superseded by a new row, never edited, except for a controlled status
transition. Enforced with `GRANT UPDATE (status)`, so the test connects as the app
role — as owner every one of these passes on a database with no grants at all.

**Nothing is seeded.** SEED-001: no profile, no limit, no cutoff time, no mapping. A
seeded transfer limit would drive real splitting the first time a batch was built.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from alembic_runner import run_alembic
from app.core.hashing import unversioned_digest
from bank_fixtures import (
    MAPPINGS_BY_NAME,
    PROFILES_BY_NAME,
    synthetic_iban,
)
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

PROFILE_A = PROFILES_BY_NAME["BANK_A_PROFILE_V1"]
MAPPING_EXPORT = MAPPINGS_BY_NAME["BANK_A_MAPPING_V1"]
MAPPING_IMPORT = MAPPINGS_BY_NAME["BANK_A_MAPPING_V2"]


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def connection(migrated_database: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(_psycopg(migrated_database), autocommit=True) as conn:
        try:
            yield conn
        finally:
            # Mappings reference versions; the pointer references versions; so the
            # pointer is cleared before the versions go.
            conn.execute("UPDATE bank_profiles SET current_version_id = NULL")
            for table in ("bank_mappings", "bank_accounts", "bank_profile_versions"):
                conn.execute(f"DELETE FROM {table}")
            conn.execute("DELETE FROM bank_profiles")


def make_profile(connection: psycopg.Connection, *, code: str | None = None) -> uuid.UUID:
    row = connection.execute(
        "INSERT INTO bank_profiles (code, name, status) VALUES (%s, %s, 'active') RETURNING id",
        (code or f"synthetic_{uuid.uuid4().hex[:10]}", PROFILE_A.display_name),
    ).fetchone()
    assert row is not None
    return row[0]


def make_version(
    connection: psycopg.Connection,
    profile_id: uuid.UUID,
    *,
    version_number: int = 1,
    config: dict[str, object] | None = None,
    **overrides: object,
) -> uuid.UUID:
    columns: dict[str, object] = {
        "bank_profile_id": profile_id,
        "version_number": version_number,
        "status": "active",
        "config_hash": unversioned_digest(config or {"version": version_number}),
    }
    columns.update(overrides)
    names = ", ".join(columns)
    placeholders = ", ".join(f"%({name})s" for name in columns)
    row = connection.execute(
        f"INSERT INTO bank_profile_versions ({names}) VALUES ({placeholders}) RETURNING id",
        columns,
    ).fetchone()
    assert row is not None
    return row[0]


def make_mapping(
    connection: psycopg.Connection,
    version_id: uuid.UUID,
    *,
    file_type: str = "outgoing_export",
    template_version: int = 1,
    config: dict[str, object] | None = None,
) -> uuid.UUID:
    row = connection.execute(
        "INSERT INTO bank_mappings (bank_profile_version_id, file_type, template_version, "
        "status, mapping, config_hash) VALUES (%s, %s, %s, 'active', %s, %s) RETURNING id",
        (
            version_id,
            file_type,
            template_version,
            psycopg.types.json.Json(MAPPING_EXPORT.mapping),
            unversioned_digest(config or {"file_type": file_type, "v": template_version}),
        ),
    ).fetchone()
    assert row is not None
    return row[0]


class TestVersionNumberingIsPerBank:
    """DB-BANK-001."""

    def test_a_duplicate_version_number_within_one_bank_is_refused(
        self, connection: psycopg.Connection
    ) -> None:
        profile = make_profile(connection)
        make_version(connection, profile, version_number=1, config={"a": 1})

        with pytest.raises(psycopg.errors.UniqueViolation) as raised:
            make_version(connection, profile, version_number=1, config={"a": 2})

        assert "uq_bank_profile_versions_number" in str(raised.value)

    def test_two_banks_may_both_have_version_one(self, connection: psycopg.Connection) -> None:
        """Per bank, not global. A global sequence would number bank B's first
        version 7 because bank A had six, and an operator reading "version 7" would
        look for six predecessors that never existed."""

        first = make_profile(connection, code="synthetic_bank_one")
        second = make_profile(connection, code="synthetic_bank_two")

        make_version(connection, first, version_number=1, config={"bank": "one"})

        assert make_version(connection, second, version_number=1, config={"bank": "two"})


class TestMappingUniquesAreScopedByFileType:
    """DB-BANK-002. The scope is the whole point."""

    def test_an_import_and_an_export_mapping_may_share_template_version_one(
        self, connection: psycopg.Connection
    ) -> None:
        """The case a globally scoped unique would forbid, and the failure would
        arrive during the first export rather than in this test."""

        profile = make_profile(connection)
        version = make_version(connection, profile)

        make_mapping(connection, version, file_type=MAPPING_EXPORT.file_type, template_version=1)

        assert make_mapping(
            connection, version, file_type=MAPPING_IMPORT.file_type, template_version=1
        )

    def test_a_duplicate_template_version_within_one_file_type_is_refused(
        self, connection: psycopg.Connection
    ) -> None:
        profile = make_profile(connection)
        version = make_version(connection, profile)

        make_mapping(connection, version, template_version=1, config={"x": 1})

        with pytest.raises(psycopg.errors.UniqueViolation) as raised:
            make_mapping(connection, version, template_version=1, config={"x": 2})

        assert "uq_bank_mappings_template_version" in str(raised.value)

    def test_a_duplicate_mapping_config_within_one_file_type_is_refused(
        self, connection: psycopg.Connection
    ) -> None:
        profile = make_profile(connection)
        version = make_version(connection, profile)
        config = {"columns": ["iban"]}

        make_mapping(connection, version, template_version=1, config=config)

        with pytest.raises(psycopg.errors.UniqueViolation) as raised:
            make_mapping(connection, version, template_version=2, config=config)

        assert "uq_bank_mappings_config_hash" in str(raised.value)

    def test_the_same_config_under_another_file_type_is_accepted(
        self, connection: psycopg.Connection
    ) -> None:
        """Guard the guard: the config unique must be scoped too, or an import
        mapping that happens to match an export mapping is refused."""

        profile = make_profile(connection)
        version = make_version(connection, profile)
        config = {"columns": ["iban"]}

        make_mapping(connection, version, file_type="outgoing_export", config=config)

        assert make_mapping(connection, version, file_type="incoming_result", config=config)


class TestIdenticalConfigurationCannotBecomeANewVersion:
    """DB-BANK-003. Without this the audit link is breakable through the UI."""

    def test_a_second_version_with_the_same_config_hash_is_refused(
        self, connection: psycopg.Connection
    ) -> None:
        profile = make_profile(connection)
        config = {"limit": 1_000_000_000, "cutoff": "16:00"}

        make_version(connection, profile, version_number=1, config=config)

        with pytest.raises(psycopg.errors.UniqueViolation) as raised:
            make_version(connection, profile, version_number=2, config=config)

        assert "uq_bank_profile_versions_config_hash" in str(raised.value)

    def test_another_bank_may_hold_the_same_configuration(
        self, connection: psycopg.Connection
    ) -> None:
        """Scoped per bank. Two banks with identical rules is ordinary, and a global
        unique would refuse the second one."""

        config = {"limit": 1_000_000_000}
        first = make_profile(connection, code="synthetic_same_one")
        second = make_profile(connection, code="synthetic_same_two")

        make_version(connection, first, config=config)

        assert make_version(connection, second, config=config)

    def test_the_config_hash_column_refuses_a_versioned_digest(
        self, connection: psycopg.Connection
    ) -> None:
        """`CHAR(64)` holds the bare form. Storing `v1:…` would silently truncate or
        fail, so the constraint says which form is expected."""

        profile = make_profile(connection)

        with pytest.raises(psycopg.errors.CheckViolation) as raised:
            make_version(connection, profile, config_hash=f"v1:{'a' * 61}")

        assert "config_hash_is_lowercase_hex" in str(raised.value)


class TestTheProfileAndItsFirstVersionAreOneTransaction:
    """DB-BANK-004. The deferrable composite pointer, exercised as intended."""

    def test_both_rows_commit_together(self, migrated_database: str) -> None:
        """Not autocommit: the whole point is that the pointer is unsatisfied in the
        middle of the transaction and satisfied at commit."""

        profile_id = uuid.uuid4()
        version_id = uuid.uuid4()

        with psycopg.connect(_psycopg(migrated_database)) as conn:
            conn.execute(
                "INSERT INTO bank_profiles (id, code, name, status, current_version_id) "
                "VALUES (%s, 'synthetic_atomic', 'اتمیک', 'active', %s)",
                (profile_id, version_id),
            )
            conn.execute(
                "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, "
                "status, config_hash) VALUES (%s, %s, 1, 'active', %s)",
                (version_id, profile_id, unversioned_digest({"atomic": True})),
            )
            conn.commit()

            row = conn.execute(
                "SELECT current_version_id FROM bank_profiles WHERE id = %s", (profile_id,)
            ).fetchone()
            assert row is not None and row[0] == version_id

            conn.execute("UPDATE bank_profiles SET current_version_id = NULL")
            conn.execute("DELETE FROM bank_profile_versions")
            conn.execute("DELETE FROM bank_profiles")
            conn.commit()

    def test_a_pointer_to_a_version_that_never_arrives_fails_at_commit(
        self, migrated_database: str
    ) -> None:
        """Deferred, not disabled. The check still happens — just at commit."""

        with psycopg.connect(_psycopg(migrated_database)) as conn:
            conn.execute(
                "INSERT INTO bank_profiles (id, code, name, status, current_version_id) "
                "VALUES (%s, 'synthetic_dangling', 'آویزان', 'active', %s)",
                (uuid.uuid4(), uuid.uuid4()),
            )

            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                conn.commit()

    def test_a_profile_cannot_point_at_another_banks_version(
        self, connection: psycopg.Connection
    ) -> None:
        """The invariant the composite form exists for.

        A single-column foreign key would accept this: the target *is* a version. It
        is not a version of this profile, and a profile exporting under another
        bank's configuration is the failure that would follow.
        """

        mine = make_profile(connection, code="synthetic_mine")
        theirs = make_profile(connection, code="synthetic_theirs")
        their_version = make_version(connection, theirs)

        with pytest.raises(psycopg.errors.ForeignKeyViolation) as raised:
            connection.execute(
                "UPDATE bank_profiles SET current_version_id = %s WHERE id = %s",
                (their_version, mine),
            )

        assert "current_version_within_profile" in str(raised.value)

    def test_the_constraint_is_composite_ordered_and_deferred(
        self, connection: psycopg.Connection
    ) -> None:
        """Read from the catalogue, because the column order is load-bearing and
        invisible in behaviour until the cross-bank case above is tried."""

        row = connection.execute(
            "SELECT condeferrable, condeferred, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'fk_bank_profiles_current_version_within_profile'"
        ).fetchone()

        assert row is not None
        deferrable, deferred, definition = row
        assert deferrable is True and deferred is True
        assert "(current_version_id, id)" in definition
        assert "bank_profile_versions(id, bank_profile_id)" in definition


class TestTheIbanConstraintIsNullTolerant:
    """DB-BANK-005."""

    def account(
        self, connection: psycopg.Connection, profile: uuid.UUID, iban: str | None
    ) -> uuid.UUID:
        row = connection.execute(
            "INSERT INTO bank_accounts (bank_profile_id, display_name, normalized_iban, "
            "account_role, status) VALUES (%s, 'حساب', %s, 'outgoing_source', 'active') "
            "RETURNING id",
            (profile, iban),
        ).fetchone()
        assert row is not None
        return row[0]

    def test_a_null_iban_is_accepted(self, connection: psycopg.Connection) -> None:
        """A centre account may be registered before its IBAN is known.

        A negative control corrected the reasoning behind this test. Removing the
        `IS NULL OR` from the check left it green, because **a SQL CHECK passes when
        it evaluates to UNKNOWN, not only when it evaluates to TRUE** — so
        `normalized_iban ~ '^IR…'` already tolerates NULL on its own. Confirmed
        directly against PostgreSQL.

        So the `IS NULL OR` clause is explicitness, not the mechanism: it makes the
        intent legible to a reader who does not have that SQL rule in mind. The thing
        that actually decides whether this row is insertable is the column being
        **nullable**, which is what the next test asserts and what the plan warns
        against copying the beneficiaries' NOT NULL form onto.
        """

        profile = make_profile(connection)

        assert self.account(connection, profile, None) is not None

    def test_the_column_is_nullable_which_is_what_makes_that_possible(
        self, connection: psycopg.Connection
    ) -> None:
        """The real invariant, asked of the catalogue.

        `NOT NULL` here is the mistake the plan names: it would refuse a centre
        account registered before its IBAN is known, and it is exactly what copying
        the beneficiaries' column definition produces.
        """

        row = connection.execute(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'bank_accounts' "
            "AND column_name = 'normalized_iban'"
        ).fetchone()

        assert row is not None and row[0] == "YES"

    def test_the_check_still_states_its_null_tolerance_explicitly(
        self, connection: psycopg.Connection
    ) -> None:
        """Redundant to PostgreSQL and not redundant to a reader.

        Pinned so nobody deletes it as dead weight — the next person to read
        `normalized_iban ~ '^IR…'` alone has to know the UNKNOWN rule to see that
        NULL is permitted, and the plan specifies the explicit form.
        """

        row = connection.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_bank_accounts_normalized_iban_shape'"
        ).fetchone()

        assert row is not None
        assert "IS NULL" in row[0]

    def test_a_valid_iban_is_accepted(self, connection: psycopg.Connection) -> None:
        profile = make_profile(connection)

        assert self.account(connection, profile, synthetic_iban("11")) is not None

    @pytest.mark.parametrize(
        "iban",
        [
            "IR12345",
            "GB99000000000000000000000",
            "ir990000000000000000000001",
            "IR9900000000000000000000012",
            "IR99000000000000000000000A",
        ],
    )
    def test_a_malformed_iban_is_refused(self, connection: psycopg.Connection, iban: str) -> None:
        profile = make_profile(connection)

        with pytest.raises(
            (psycopg.errors.CheckViolation, psycopg.errors.StringDataRightTruncation)
        ):
            self.account(connection, profile, iban)

    def test_two_accounts_may_both_have_no_iban(self, connection: psycopg.Connection) -> None:
        """The unique is on `normalized_iban`, and PostgreSQL treats NULLs as
        distinct — so two accounts awaiting their IBAN do not collide. Asserted
        because a `NULLS NOT DISTINCT` unique would break registration."""

        profile = make_profile(connection)
        self.account(connection, profile, None)

        assert self.account(connection, profile, None) is not None

    def test_a_duplicate_iban_is_refused(self, connection: psycopg.Connection) -> None:
        """Centre accounts only. Two rows for one centre IBAN is a duplicate of the
        centre's own record — unlike a beneficiary, where duplicates are legitimate."""

        profile = make_profile(connection)
        iban = synthetic_iban("22")
        self.account(connection, profile, iban)

        with pytest.raises(psycopg.errors.UniqueViolation):
            self.account(connection, profile, iban)

    def test_no_unique_makes_an_iban_one_per_row_outside_bank_accounts(
        self, connection: psycopg.Connection
    ) -> None:
        """Asked of the database rather than the models, so a unique index added by a
        migration that never touched a model is caught too."""

        rows = connection.execute(
            "SELECT t.relname, i.relname FROM pg_index x "
            "JOIN pg_class i ON i.oid = x.indexrelid "
            "JOIN pg_class t ON t.oid = x.indrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(x.indkey) "
            "WHERE n.nspname = 'public' AND x.indisunique "
            "AND a.attname IN ('iban', 'normalized_iban') AND t.relname <> 'bank_accounts'"
        ).fetchall()

        assert rows == [], f"a unique makes an IBAN one-per-row: {rows}"


class TestSnapshotsAreImmutableExceptForStatus:
    """DB-BANK-006, connected as the app role.

    Run as owner these all pass on a database with no grants at all, so the role is
    the test.
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

    def seed_one_version(self, url: str) -> tuple[uuid.UUID, uuid.UUID]:
        with psycopg.connect(url, autocommit=True) as conn:
            profile = make_profile(conn, code="synthetic_immutable")
            version = make_version(conn, profile, config={"immutable": True})
            make_mapping(conn, version)
        return profile, version

    def test_the_status_of_a_version_may_still_move(
        self, migrated_as_migrator: RuntimeIdentities
    ) -> None:
        """The controlled transition. Withholding it entirely would make a version
        impossible to retire."""

        _profile, version = self.seed_one_version(migrated_as_migrator.owner_url)

        with psycopg.connect(migrated_as_migrator.app_url, autocommit=True) as conn:
            conn.execute(
                "UPDATE bank_profile_versions SET status = 'retired' WHERE id = %s", (version,)
            )
            row = conn.execute(
                "SELECT status FROM bank_profile_versions WHERE id = %s", (version,)
            ).fetchone()

        assert row is not None and row[0] == "retired"

    @pytest.mark.parametrize(
        ("column", "value"),
        [
            ("default_transfer_limit_irr", 999_000_000),
            ("cutoff_time", "12:00"),
            ("config_hash", "f" * 64),
            ("version_number", 99),
            ("splitting_enabled", True),
        ],
    )
    def test_no_other_column_of_a_version_may_be_updated(
        self, migrated_as_migrator: RuntimeIdentities, column: str, value: object
    ) -> None:
        """The reason the grant is column-level.

        A table-level `GRANT UPDATE` would permit rewriting a transfer limit under an
        already-approved batch, and the batch's audit trail would still point at a
        version whose numbers had changed.
        """

        _profile, version = self.seed_one_version(migrated_as_migrator.owner_url)

        with (
            psycopg.connect(migrated_as_migrator.app_url, autocommit=True) as conn,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            conn.execute(
                f"UPDATE bank_profile_versions SET {column} = %s WHERE id = %s",
                (value, version),
            )

    def test_a_mapping_is_immutable_except_for_status(
        self, migrated_as_migrator: RuntimeIdentities
    ) -> None:
        self.seed_one_version(migrated_as_migrator.owner_url)

        with psycopg.connect(migrated_as_migrator.app_url, autocommit=True) as conn:
            conn.execute("UPDATE bank_mappings SET status = 'retired'")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("UPDATE bank_mappings SET template_version = 9")

    def test_neither_snapshot_may_be_deleted(self, migrated_as_migrator: RuntimeIdentities) -> None:
        """A bank configuration a batch was built against is evidence of how that
        batch was built."""

        self.seed_one_version(migrated_as_migrator.owner_url)

        with psycopg.connect(migrated_as_migrator.app_url, autocommit=True) as conn:
            for table in ("bank_profile_versions", "bank_mappings"):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    conn.execute(f"DELETE FROM {table}")

    def test_the_mutable_tables_are_still_updatable(
        self, migrated_as_migrator: RuntimeIdentities
    ) -> None:
        """Guard the guard: the column-level grants must not have narrowed the
        ordinary current-state tables into uselessness."""

        with psycopg.connect(migrated_as_migrator.app_url) as conn:
            row = conn.execute(
                "SELECT has_table_privilege('bank_profiles', 'UPDATE'), "
                "has_table_privilege('bank_accounts', 'UPDATE'), "
                "has_table_privilege('bank_profiles', 'DELETE')"
            ).fetchone()

        assert row is not None
        assert row == (True, True, False)


class TestNothingIsSeeded:
    """SEED-001. A seeded transfer limit would drive real splitting decisions."""

    @pytest.mark.parametrize(
        "table", ["bank_profiles", "bank_profile_versions", "bank_accounts", "bank_mappings"]
    )
    def test_the_migration_inserts_no_rows(self, migrated_database: str, table: str) -> None:
        """Read from a freshly migrated database before any test has written to it.

        Module-scoped, so this runs against whatever earlier tests left behind — the
        cleanup fixture removes their rows, and these four tables have no other
        source.
        """

        with psycopg.connect(_psycopg(migrated_database), autocommit=True) as conn:
            row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()

        assert row is not None and row[0] == 0, (
            f"{table} contains seeded rows. ADR-007 permits synthetic fixtures only, "
            "and a seeded limit becomes production truth."
        )

    def test_no_migration_file_inserts_bank_configuration(self) -> None:
        """The source-level half, so a future revision cannot add a seed quietly."""

        from pathlib import Path

        versions = (
            Path(__file__).resolve().parents[2] / "services" / "backend" / "alembic" / "versions"
        )
        offenders: list[str] = []
        for path in sorted(versions.glob("*.py")):
            lowered = path.read_text(encoding="utf-8").lower()
            for table in ("bank_profiles", "bank_profile_versions", "bank_mappings"):
                if f"insert into {table}" in lowered:
                    offenders.append(f"{path.name}: {table}")

        assert offenders == [], "a migration seeds bank configuration:\n" + "\n".join(offenders)
