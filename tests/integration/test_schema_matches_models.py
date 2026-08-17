"""The migrations and the models must describe the same database.

Every revision is hand-written, so a column type, a server default, a constraint
name or a partial-index predicate can drift from the model it is supposed to
create. Nothing else in the suite would notice: the ORM would keep working
against the drifted column right up until the difference mattered, and by then
the migration is in production and the fix is another migration.

So the check is not a transcription review, which would have to be repeated by
hand on every revision. It runs Alembic's own autogenerate comparison against a
freshly migrated database and requires it to find nothing. That is the same
machinery that would generate the correcting revision, so an empty result means
Alembic would propose no change.

It has one blind spot worth stating plainly, because relying on it unaware would
be worse than not having it: **autogenerate does not compare CHECK constraints**.
A migration can create a check under a mangled name, or omit one entirely, and
this comparison still reports no differences. `test_constraint_names.py` and
`test_integrity_constraints.py` cover that gap — the first on names, the second
on whether each check actually rejects what it claims to.

Since 20260801_0012 the comparison also emits a warning that reads like a second
blind spot and is not one:

    Cannot correctly sort tables; there are unresolvable cycles between tables
    "bank_profile_versions, bank_profiles" ... Foreign key constraints involving
    these tables will not be considered

`bank_profiles` points at its current version and every version points back at its
profile, so the two cannot be topologically ordered. The sentence about foreign keys
concerns that **ordering** — which constraints Alembic can place when it renders DDL
— not which constraints it compares. `test_the_table_cycle_does_not_hide_a_missing_foreign_key`
below proves the difference by dropping each foreign key on the cycle and requiring
the comparison to notice, so the distinction is pinned rather than assumed. It also
guards the future: the warning says it may become an error in a later SQLAlchemy, and
if that release changes the comparison too, that test fails rather than the drift
check going quiet.

Covers: DB-TYPE-001.
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities
from sqlalchemy import create_engine, text

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

import app.db.models  # noqa: E402, F401  # registers every table on Base.metadata
from app.db.base import Base  # noqa: E402

pytestmark = pytest.mark.integration

# Owned by the verifier, not by this application: `infra/scripts/verify-docker.sh`
# creates it to prove data survives a container recreation. `alembic/env.py`
# excludes it from autogenerate, and the comparison here must agree or the
# exclusion would be untested.
UNMANAGED_SCHEMAS = frozenset({"m1_verification"})


def _sqlalchemy_url(database_url: str) -> str:
    if database_url.startswith("postgresql+psycopg://"):
        return database_url
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


def _include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object | None
) -> bool:
    return getattr(obj, "schema", None) not in UNMANAGED_SCHEMAS


def schema_differences(database_url: str) -> list[object]:
    engine = create_engine(_sqlalchemy_url(database_url))
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={
                    "compare_type": True,
                    "compare_server_default": True,
                    "include_object": _include_object,
                },
            )
            return list(compare_metadata(context, Base.metadata))
    finally:
        engine.dispose()


def _migrate_full_head(identities: RuntimeIdentities) -> None:
    """Migrate to the real head, as a provisioned deployment does.

    Stopping at a schema-only revision used to be enough. It is not any more:
    20260801_0006 both creates a table and grants on it, so a comparison run
    against an earlier revision would report the new table as missing from the
    database and pass or fail for reasons unrelated to model drift.
    """

    result = run_alembic(
        identities.migrator_url,
        "upgrade",
        "head",
        app_role=identities.app_role,
        worker_role=identities.worker_role,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_migrated_database_matches_the_models_exactly(
    provisioned_database: RuntimeIdentities,
) -> None:
    _migrate_full_head(provisioned_database)

    differences = schema_differences(provisioned_database.owner_url)

    assert differences == [], (
        "Alembic autogenerate found differences between the migrated database and "
        "the models, which means a hand-written revision does not create what the "
        "model declares. Each entry below is a change autogenerate would emit:\n"
        + "\n".join(f"  {difference}" for difference in differences)
    )


# Every foreign key on the two tables that form the cycle, plus one that points into
# the cycle from outside it, plus a control far away from it. The control is what says
# the test itself works: if the drop-and-compare mechanism were broken, everything
# would read as "not detected" and the test would look like it had found a disaster.
CYCLE_FOREIGN_KEYS: tuple[tuple[str, str], ...] = (
    ("bank_profiles", "fk_bank_profiles_current_version_within_profile"),
    ("bank_profile_versions", "fk_bank_profile_versions_bank_profile_id_bank_profiles"),
    (
        "bank_profile_versions",
        "fk_bank_profile_versions_created_by_admin_user_id_admin_users",
    ),
    ("bank_mappings", "fk_bank_mappings_bank_profile_version_id_bank_profile_versions"),
    ("file_links", "fk_file_links_file_id_file_objects"),
    # M5 slice 3 creates a **second** cycle on the same pattern: a request points at
    # its current revision and every revision points back at its request. Listed
    # because the property this test proves is per-cycle — covering M2's and not this
    # one would leave the newer composite pointer unchecked, and that pointer is what
    # stops a request from showing another request's beneficiary and amount.
    ("payment_requests", "fk_request_current_revision"),
    (
        "payment_request_revisions",
        "fk_request_revisions_request",
    ),
)


def test_the_table_cycle_does_not_hide_a_missing_foreign_key(
    provisioned_database: RuntimeIdentities,
) -> None:
    """The cycle warning is about sort order, not about what gets compared.

    Proved rather than reasoned about: each foreign key is dropped inside a
    transaction, the comparison is run on that same connection so it sees the
    uncommitted change, and the transaction is rolled back. A drop the comparison
    does not report would be a change a hand-written revision could make with the
    drift check above staying green.

    The `file_links` entry is the control. Without it, a broken drop-and-compare
    would report every constraint as undetected and this test would read as a
    catastrophic finding rather than as its own failure.
    """

    _migrate_full_head(provisioned_database)

    engine = create_engine(_sqlalchemy_url(provisioned_database.owner_url))
    undetected: list[str] = []
    try:
        for table, constraint in CYCLE_FOREIGN_KEYS:
            with engine.connect() as connection:
                transaction = connection.begin()
                try:
                    connection.execute(
                        text(f'ALTER TABLE public."{table}" DROP CONSTRAINT "{constraint}"')
                    )
                    context = MigrationContext.configure(
                        connection,
                        opts={
                            "compare_type": True,
                            "compare_server_default": True,
                            "include_object": _include_object,
                        },
                    )
                    reported = [
                        difference
                        for difference in compare_metadata(context, Base.metadata)
                        if "foreign" in str(difference).lower()
                    ]
                    if not reported:
                        undetected.append(f"{table}.{constraint}")
                finally:
                    transaction.rollback()
    finally:
        engine.dispose()

    assert undetected == [], (
        "the comparison did not notice these foreign keys going missing, so a "
        "revision could drop them with the drift check staying green:\n"
        + "\n".join(f"  {entry}" for entry in undetected)
    )


def test_every_expected_table_exists_after_upgrade(
    provisioned_database: RuntimeIdentities,
) -> None:
    """Guard the guard: an empty comparison proves nothing if nothing is mapped.

    If `app.db.models` stopped registering its tables, the comparison above would
    compare an empty model set against an empty database and pass.
    """

    _migrate_full_head(provisioned_database)

    with psycopg.connect(
        provisioned_database.owner_url.replace("postgresql+psycopg://", "postgresql://", 1)
    ) as connection:
        rows = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()

    present = {row[0] for row in rows}
    expected = set(Base.metadata.tables)

    assert expected, "no tables are mapped, so the comparison above cannot mean anything"
    assert expected <= present, f"missing after upgrade: {sorted(expected - present)}"
