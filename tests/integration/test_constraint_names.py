"""Constraint names in the database must match the ones the models declare.

This exists because `test_schema_matches_models.py` cannot cover it. Alembic's
autogenerate comparison does not inspect CHECK constraints, so a migration can
create a check under a different name, or a mangled one, and that comparison
still reports no differences. The first version of these migrations did exactly
that: passing the full `ck_<table>_<name>` while `op.create_table` also applied
the `ck_%(table_name)s_%(constraint_name)s` convention produced a doubled prefix,
and PostgreSQL truncated the longest results at 63 bytes with a hash suffix.

Names are not cosmetic here. A typed error handler that maps a unique or check
violation to an HTTP status matches on the constraint name, so a mangled name
routes a violation to the generic 500 path instead. A truncated name is worse
than a wrong one: it is stable enough to look deliberate.

The expected names come from compiling each model's CREATE TABLE, so this is a
comparison between two independent renderings and not against a hand-kept list.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import psycopg
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

import app.db.models  # noqa: E402, F401  # registers every table on Base.metadata
from app.db.base import MAX_IDENTIFIER_BYTES, Base  # noqa: E402

pytestmark = pytest.mark.integration

CONSTRAINT_IN_DDL = re.compile(r"CONSTRAINT\s+(\S+)\s+(CHECK|PRIMARY KEY|UNIQUE|FOREIGN KEY)")


def declared_constraint_names(table_name: str) -> set[str]:
    """Render the model's CREATE TABLE and read the names back out of it."""

    table = Base.metadata.tables[table_name]
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    return {match.group(1) for match in CONSTRAINT_IN_DDL.finditer(ddl)}


def actual_constraint_names(connection: psycopg.Connection, table_name: str) -> set[str]:
    rows = connection.execute(
        "SELECT conname FROM pg_constraint c "
        "JOIN pg_class t ON t.oid = c.conrelid "
        "JOIN pg_namespace n ON n.oid = t.relnamespace "
        "WHERE n.nspname = 'public' AND t.relname = %s AND c.contype IN ('c', 'p', 'u', 'f')",
        (table_name,),
    ).fetchall()
    # PostgreSQL synthesises a NOT NULL check on identity columns in some versions;
    # only named constraints the model could have declared are compared.
    return {row[0] for row in rows}


@pytest.mark.parametrize(
    "table_name", ["audit_logs", "outbox_events", "idempotency_records", "center_profile"]
)
def test_declared_constraints_all_exist_under_their_declared_names(
    migrated_connection: psycopg.Connection, table_name: str
) -> None:
    declared = declared_constraint_names(table_name)
    actual = actual_constraint_names(migrated_connection, table_name)

    assert declared, f"{table_name} declares no named constraints; the check would be vacuous"
    missing = declared - actual
    assert not missing, (
        f"{table_name} declares these constraints but the migrated database has no "
        f"such names: {sorted(missing)}.\nThe database has: {sorted(actual)}"
    )


@pytest.mark.parametrize(
    "table_name", ["audit_logs", "outbox_events", "idempotency_records", "center_profile"]
)
def test_no_constraint_name_was_truncated(
    migrated_connection: psycopg.Connection, table_name: str
) -> None:
    """A name at exactly the limit is the signature of silent truncation.

    PostgreSQL does not warn. Two long names on a wide table can collapse into
    one, and the second CREATE then fails with a duplicate-name error that points
    at neither constraint.
    """

    actual = actual_constraint_names(migrated_connection, table_name)
    at_the_limit = [
        name for name in actual if len(name.encode("utf-8")) >= MAX_IDENTIFIER_BYTES
    ]

    assert at_the_limit == [], (
        f"{table_name} has constraint names at or over PostgreSQL's {MAX_IDENTIFIER_BYTES}-byte "
        f"limit, so they have been truncated: {sorted(at_the_limit)}"
    )


def test_index_names_match_the_models(migrated_connection: psycopg.Connection) -> None:
    """Doc-04 index names are kept verbatim, so a rename would break a citation."""

    declared = {
        index.name
        for table in Base.metadata.tables.values()
        for index in table.indexes
        if index.name is not None
    }
    rows = migrated_connection.execute(
        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
    ).fetchall()
    actual = {row[0] for row in rows}

    assert declared, "no indexes are declared; the check would be vacuous"
    assert declared <= actual, f"declared but absent: {sorted(declared - actual)}"
