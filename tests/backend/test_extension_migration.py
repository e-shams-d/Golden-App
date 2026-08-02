"""Cover the extension revision's failure branches, which no gate can reach.

The revision creates the extensions only where the connected role is permitted
to, and otherwise raises a message naming the exact statement an operator must
run. Every environment the pipeline actually exercises has the extensions
provisioned by `db-bootstrap` before the migration runs, so the create attempt
succeeds and none of the failure branches execute anywhere. Without these tests a
typo in the remediation text is undetectable until it is needed, which is the one
moment nobody can afford it to be wrong.

The exception classes matter as much as the messages. Verified against the pinned
psycopg 3.2.12: `InsufficientPrivilege` is a `ProgrammingError` (42501), but
`UndefinedFile` is an `OperationalError` (58P01) and `FeatureNotSupported` is a
`NotSupportedError` (0A000). Catching `ProgrammingError` alone would let both
managed-PostgreSQL conditions escape as a bare traceback, which is precisely the
case the tolerant shape exists to handle.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import psycopg
import pytest
from sqlalchemy.exc import NotSupportedError, OperationalError, ProgrammingError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.db.migrations import EXPECTED_MIGRATION_HEADS  # noqa: E402

REVISION_PATH = BACKEND_ROOT / "alembic" / "versions" / "20260801_0002_extensions.py"


def load_revision() -> ModuleType:
    """Import the revision by path; alembic/versions is not an importable package."""

    spec = importlib.util.spec_from_file_location("m2_extensions_revision", REVISION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingBind:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def exec_driver_sql(self, statement: str) -> None:
        self.statements.append(statement)


class RaisingBind:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def exec_driver_sql(self, statement: str) -> None:
        raise self.error


def runnable_statements(message: str) -> list[str]:
    """Lines an operator could paste. Exactly one is intended."""

    return [line.strip() for line in message.splitlines() if line.strip().endswith(";")]


def test_create_extension_issues_the_schema_qualified_statement() -> None:
    revision = load_revision()
    bind = RecordingBind()

    revision.create_extension(bind, "citext", "gold_platform", "gold_migrator")

    assert bind.statements == ['CREATE EXTENSION IF NOT EXISTS "citext" WITH SCHEMA public;']


def test_insufficient_privilege_reports_one_runnable_remedy() -> None:
    revision = load_revision()
    original = psycopg.errors.InsufficientPrivilege(
        'permission denied to create extension "citext"'
    )
    bind = RaisingBind(ProgrammingError("CREATE EXTENSION", None, original))

    with pytest.raises(RuntimeError) as raised:
        revision.create_extension(bind, "citext", "gold_platform", "gold_migrator")

    message = str(raised.value)
    assert "gold_platform" in message
    assert "gold_migrator" in message
    assert "42501" in message
    assert runnable_statements(message) == [
        'CREATE EXTENSION IF NOT EXISTS "citext" WITH SCHEMA public;'
    ]
    # The remedy must never be copy-pasteable privilege widening: CREATE on a
    # database also confers CREATE SCHEMA, permanently, on the role owning all DDL.
    assert "Do not grant CREATE ON DATABASE" in message
    assert runnable_statements(message) == [
        line for line in runnable_statements(message) if "GRANT" not in line
    ]


def test_missing_control_file_is_caught_although_it_is_an_operational_error() -> None:
    revision = load_revision()
    original = psycopg.errors.UndefinedFile("could not open extension control file")
    bind = RaisingBind(OperationalError("CREATE EXTENSION", None, original))

    with pytest.raises(RuntimeError) as raised:
        revision.create_extension(bind, "citext", "gold_platform", "gold_migrator")

    message = str(raised.value)
    assert "58P01" in message
    assert "allow-listed" in message
    assert runnable_statements(message) == [
        'CREATE EXTENSION IF NOT EXISTS "citext" WITH SCHEMA public;'
    ]


def test_feature_not_supported_is_caught_although_it_is_a_not_supported_error() -> None:
    revision = load_revision()
    original = psycopg.errors.FeatureNotSupported("extension is not allow-listed")
    bind = RaisingBind(NotSupportedError("CREATE EXTENSION", None, original))

    with pytest.raises(RuntimeError) as raised:
        revision.create_extension(bind, "citext", "gold_platform", "gold_migrator")

    assert "0A000" in str(raised.value)


def test_unknown_sqlstate_still_raises_the_curated_error() -> None:
    revision = load_revision()

    class UnknownDriverError(Exception):
        sqlstate = "XX000"

    bind = RaisingBind(ProgrammingError("CREATE EXTENSION", None, UnknownDriverError("boom")))

    with pytest.raises(RuntimeError) as raised:
        revision.create_extension(bind, "citext", "gold_platform", "gold_migrator")

    message = str(raised.value)
    assert "XX000" in message
    assert runnable_statements(message) == [
        'CREATE EXTENSION IF NOT EXISTS "citext" WITH SCHEMA public;'
    ]


def test_driver_error_without_a_sqlstate_does_not_crash_the_handler() -> None:
    """A driver that reports no SQLSTATE must still produce the curated message."""

    revision = load_revision()
    bind = RaisingBind(ProgrammingError("CREATE EXTENSION", None, Exception("no sqlstate")))

    with pytest.raises(RuntimeError) as raised:
        revision.create_extension(bind, "citext", "gold_platform", "gold_migrator")

    assert "unknown" in str(raised.value)


def test_the_three_handled_sqlstates_are_what_the_driver_actually_raises() -> None:
    """Guards the premise the whole tolerant shape rests on.

    If a driver upgrade moved any of these, the revision would keep catching
    DBAPIError but would classify the failure into the wrong branch and print
    the wrong remedy.
    """

    revision = load_revision()

    assert psycopg.errors.InsufficientPrivilege("x").sqlstate == revision.PRIVILEGE_SQLSTATE
    assert psycopg.errors.UndefinedFile("x").sqlstate in revision.UNAVAILABLE_SQLSTATES
    assert psycopg.errors.FeatureNotSupported("x").sqlstate in revision.UNAVAILABLE_SQLSTATES


def test_the_extension_revision_still_precedes_every_table() -> None:
    """The extensions must be installed before anything can depend on them.

    This revision was the head when it was written. It is not any more, so
    asserting that would only pin how many revisions exist. What has to stay true
    is its position: `gen_random_uuid()` is the primary-key default on every table
    that follows, so a chain that reordered this revision would fail at the first
    CREATE TABLE rather than anywhere near the cause.

    `test_migration_heads.py` owns the head assertion, resolving it from Alembic
    rather than from a literal repeated here.
    """

    revision = load_revision()

    assert revision.down_revision == "20260720_0001"
    assert revision.revision not in EXPECTED_MIGRATION_HEADS, (
        "this revision creates extensions and no tables; if it is the head again, "
        "the table revisions have been lost rather than this test being wrong"
    )
