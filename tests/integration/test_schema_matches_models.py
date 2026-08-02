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
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic_runner import run_alembic
from sqlalchemy import create_engine

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


def test_migrated_database_matches_the_models_exactly(disposable_database: str) -> None:
    assert run_alembic(disposable_database, "upgrade", "head").returncode == 0

    differences = schema_differences(disposable_database)

    assert differences == [], (
        "Alembic autogenerate found differences between the migrated database and "
        "the models, which means a hand-written revision does not create what the "
        "model declares. Each entry below is a change autogenerate would emit:\n"
        + "\n".join(f"  {difference}" for difference in differences)
    )


def test_every_expected_table_exists_after_upgrade(disposable_database: str) -> None:
    """Guard the guard: an empty comparison proves nothing if nothing is mapped.

    If `app.db.models` stopped registering its tables, the comparison above would
    compare an empty model set against an empty database and pass.
    """

    assert run_alembic(disposable_database, "upgrade", "head").returncode == 0

    with psycopg.connect(
        disposable_database.replace("postgresql+psycopg://", "postgresql://", 1)
    ) as connection:
        rows = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()

    present = {row[0] for row in rows}
    expected = set(Base.metadata.tables)

    assert expected, "no tables are mapped, so the comparison above cannot mean anything"
    assert expected <= present, f"missing after upgrade: {sorted(expected - present)}"
