"""Constraint *names* in the database match the models, which `compare_metadata` never checks.

Written because M6 slice 2 shipped five tables whose model-declared foreign-key names differed
from the names its own migration created, and `tests/integration/test_schema_matches_models.py`
passed. That test uses Alembic's `compare_metadata`, which compares structure — columns, types,
nullability, the existence of a constraint — and **not** the name a constraint carries. So a
migration saying `fk_allocation_attempt` and a model saying
`fk_payment_attempt_allocations_payment_attempt_id_payment_attempts` were both accepted, and the
schema gate reported agreement.

Only `over_length_identifiers()` noticed, and only for the five names that happened to exceed
PostgreSQL's 63-byte limit. Every shorter divergence was invisible.

**Why a name is not cosmetic.** Three consequences, in increasing order of how long they take to
find:

1. A migration that later does `op.drop_constraint(<model's name>)` fails at deploy time, because
   the database holds the other name.
2. Code that turns an `IntegrityError` into a specific HTTP answer has to match on
   `exception.diag.constraint_name`. Nothing does that today, but `create_batch` deliberately
   relies on the allocation's unique violation being the refusal — and the moment somebody needs
   to tell "this attempt is already allocated" from "that batch number is taken", they will match
   on a name. Matching on a name the model declares and the database does not produces a 500
   where a 409 was intended, for the one input that matters.
3. PostgreSQL truncates at 63 bytes silently, so two long names can collapse into one and the
   second `CREATE` either fails or, worse, succeeds against the wrong object.

Compared by set difference rather than pairwise, so the failure message names exactly which
constraints exist on one side only.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities
from sqlalchemy import create_engine, inspect

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

import app.db.models  # noqa: E402, F401  # registers every table on Base.metadata
from app.db.base import Base  # noqa: E402

pytestmark = pytest.mark.integration

# Primary keys are excluded: the convention generates `pk_<table>` and PostgreSQL reports the
# same, so they cannot diverge without the table name diverging first — which
# `test_schema_matches_models.py` already catches.
KINDS = ("foreign_key", "unique", "check", "index")


def _model_names(table_name: str) -> dict[str, set[str]]:
    table = Base.metadata.tables[table_name]
    return {
        "foreign_key": {
            constraint.name
            for constraint in table.constraints
            if type(constraint).__name__ == "ForeignKeyConstraint" and constraint.name
        },
        "unique": {
            constraint.name
            for constraint in table.constraints
            if type(constraint).__name__ == "UniqueConstraint" and constraint.name
        },
        "check": {
            constraint.name
            for constraint in table.constraints
            if type(constraint).__name__ == "CheckConstraint" and constraint.name
        },
        "index": {index.name for index in table.indexes if index.name},
    }


def _sqlalchemy_url(database_url: str) -> str:
    if database_url.startswith("postgresql+psycopg://"):
        return database_url
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


def _database_names(inspector: object, table_name: str) -> dict[str, set[str]]:
    unique = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(table_name)
        if constraint.get("name")
    }
    indexes = {
        index["name"] for index in inspector.get_indexes(table_name) if index.get("name")
    }
    return {
        "foreign_key": {
            key["name"] for key in inspector.get_foreign_keys(table_name) if key.get("name")
        },
        # A `UniqueConstraint` in the model becomes a unique *constraint* in PostgreSQL, which
        # also has a backing index of the same name. Subtracted from the index set so a
        # unique constraint is not counted twice and reported as a missing index.
        "unique": unique,
        "check": {
            constraint["name"]
            for constraint in inspector.get_check_constraints(table_name)
            if constraint.get("name")
        },
        "index": indexes - unique,
    }


def test_every_constraint_name_matches_between_the_model_and_the_database(
    provisioned_database: RuntimeIdentities,
) -> None:
    """Every table, not only M6's: the gap this closes was never specific to one slice.

    One test over every table rather than a parametrised one per table, because the database has
    to be migrated once and a parametrised fixture would either re-migrate or need a wider scope
    than the isolation rules allow. Every mismatch is collected before asserting, so a run
    reports all of them instead of the alphabetically first.
    """

    result = run_alembic(
        provisioned_database.migrator_url,
        "upgrade",
        "head",
        app_role=provisioned_database.app_role,
        worker_role=provisioned_database.worker_role,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    engine = create_engine(_sqlalchemy_url(provisioned_database.owner_url))
    problems: list[str] = []
    try:
        inspector = inspect(engine)
        present = set(inspector.get_table_names())

        for table_name in sorted(Base.metadata.tables):
            if table_name not in present:
                problems.append(f"{table_name}: mapped but not in the migrated database")
                continue

            model = _model_names(table_name)
            database = _database_names(inspector, table_name)

            for kind in KINDS:
                only_in_model = model[kind] - database[kind]
                only_in_database = database[kind] - model[kind]

                if only_in_model:
                    problems.append(
                        f"{table_name}: the model declares {kind} {sorted(only_in_model)} and "
                        f"the database has no such name (database: {sorted(database[kind])}). "
                        "A migration that later drops one of these by name fails at deploy time."
                    )
                if only_in_database:
                    problems.append(
                        f"{table_name}: the database has {kind} {sorted(only_in_database)} and "
                        f"the model declares no such name (model: {sorted(model[kind])})."
                    )
    finally:
        engine.dispose()

    assert problems == [], (
        "constraint names disagree between the models and the migrated database. Autogenerate "
        "compares structure and not names, so nothing else reports this:\n"
        + "\n".join(f"  {problem}" for problem in problems)
    )


def test_this_gate_would_have_caught_the_defect_that_prompted_it() -> None:
    """The convention that produced the divergence, asserted so the shape stays visible.

    `NAMING_CONVENTION["fk"]` is `fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s`,
    which on a table named `payment_attempt_allocations` produces names well over the limit. An
    unnamed `ForeignKey` on a long table therefore *always* diverges from any migration that
    named it by hand — so this is a property of the convention, not an accident of one slice.

    Kept as a unit assertion with no database, so it cannot become a skip.
    """

    from app.db.base import MAX_IDENTIFIER_BYTES, NAMING_CONVENTION

    generated = NAMING_CONVENTION["fk"] % {
        "table_name": "payment_attempt_allocations",
        "column_0_N_name": "allocated_by_admin_user_id",
        "referred_table_name": "admin_users",
    }
    assert len(generated.encode("utf-8")) > MAX_IDENTIFIER_BYTES, (
        f"{generated!r} now fits in {MAX_IDENTIFIER_BYTES} bytes. Either the convention or the "
        "limit changed; re-read whether unnamed foreign keys on wide tables are still a hazard "
        "before relaxing anything."
    )
