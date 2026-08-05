"""No float touches money, and no timestamp column loses its timezone.

Both rules are from the approved MONEY_TIME_CONTRACT, and both are the kind that
hold until the first person who has not read it adds a column. So they are
checked by parsing the source rather than by review.

The float rule is the sharper one. A `Float` column accepts every test value
anyone writes — 100, 250, 1000 all round-trip perfectly — and starts losing whole
rials at amounts this system reaches routinely. There is no test of *behaviour*
that catches it early; only a check of the declaration does.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPOSITORY_ROOT / "services" / "backend" / "app"
MODELS_ROOT = APP_ROOT / "db" / "models"

# SQLAlchemy and Pydantic spellings of binary floating point.
FORBIDDEN_COLUMN_TYPES = frozenset({"Float", "REAL", "DOUBLE_PRECISION", "Double", "Numeric"})

# A timestamp without a timezone is a wall clock: two servers in different zones
# disagree about what it means, and neither is detectably wrong.
NAIVE_TIMESTAMP_MARKERS = frozenset({"TIMESTAMP", "Date"})


def _model_files() -> list[Path]:
    return sorted(MODELS_ROOT.rglob("*.py"))


def _calls(path: Path) -> list[tuple[int, str, str | None, ast.Call]]:
    """(line, called name, receiver name, node).

    The receiver is what separates `func.now()` — SQLAlchemy's SQL `now()`,
    evaluated by PostgreSQL and entirely correct as a server default — from
    `datetime.now()`, which reads the Python process clock and returns a naive
    value. Without it the guard fires on every correct server default, and a rule
    that flags correct code is one people learn to ignore.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, str, str | None, ast.Call]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            found.append((node.lineno, node.func.id, None, node))
        elif isinstance(node.func, ast.Attribute):
            receiver = (
                node.func.value.id if isinstance(node.func.value, ast.Name) else None
            )
            found.append((node.lineno, node.func.attr, receiver, node))
    return found


# `func` is SQLAlchemy's SQL function namespace: `func.now()` is evaluated by
# PostgreSQL as `now()`, which returns timestamptz. It is the correct way to
# write a server-side default and must not be confused with the Python clock.
SQL_FUNCTION_RECEIVERS = frozenset({"func", "sa", "sqlalchemy"})


def _floating_point_references(paths: list[Path]) -> list[str]:
    """Every mention of a forbidden numeric type, called or not.

    Both spellings matter, and only one is a call. `mapped_column(Float, ...)`
    passes the class itself — which is how SQLAlchemy columns are nearly always
    written — so a scanner that only walked `ast.Call` would report a clean
    package with a Float column sitting in it.
    """

    offenders: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name: str | None = None
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            if name in FORBIDDEN_COLUMN_TYPES:
                offenders.append(f"{path.name}:{node.lineno}: {name}")
    return sorted(set(offenders))


def test_the_scanner_sees_the_models() -> None:
    """Guard the guard: an empty file list passes every check below."""

    files = _model_files()

    assert len(files) >= 4, f"only found {[f.name for f in files]}"


def test_no_model_declares_a_floating_point_column() -> None:
    """`Float` accepts every plausible test value and loses rials at scale.

    NUMERIC is included: the contract permits it only under a recorded schema
    exception, and none exists. Adding one is a governance act, not a column
    choice, so the guard fails until that happens.
    """

    offenders = _floating_point_references(_model_files())

    assert offenders == [], (
        "binary floating point is forbidden for monetary storage, and NUMERIC "
        "requires a recorded approved exception:\n" + "\n".join(offenders)
    )


def test_the_float_scanner_catches_the_bare_class_form(tmp_path: Path) -> None:
    """Guard the guard, on the idiom SQLAlchemy actually uses.

    The first version of this scanner only inspected calls, so it saw `Float()`
    and missed `mapped_column(Float, ...)` — which is how the type is nearly
    always written. It reported a clean package while a Float column sat in it.
    """

    planted = tmp_path / "model.py"
    planted.write_text(
        "from sqlalchemy import Float\n"
        "from sqlalchemy.orm import mapped_column\n"
        "class M:\n"
        "    bare = mapped_column(Float, nullable=True)\n"
        "    called = mapped_column(Float(), nullable=True)\n",
        encoding="utf-8",
    )

    found = _floating_point_references([planted])

    assert len(found) == 2, f"both spellings must be caught, got {found}"


def test_the_float_scanner_does_not_flag_unrelated_names(tmp_path: Path) -> None:
    """A rule that fires on correct code is one people learn to ignore."""

    clean = tmp_path / "model.py"
    clean.write_text(
        "from sqlalchemy import BigInteger, String\n"
        "from sqlalchemy.orm import mapped_column\n"
        "class M:\n"
        "    amount_irr = mapped_column(BigInteger, nullable=False)\n"
        "    name = mapped_column(String(80))\n",
        encoding="utf-8",
    )

    assert _floating_point_references([clean]) == []


def test_every_datetime_column_is_timezone_aware() -> None:
    """`DateTime()` without `timezone=True` maps to TIMESTAMP WITHOUT TIME ZONE.

    The default is the wrong one, which is exactly why this is checked: the
    correct declaration is longer than the incorrect one.
    """

    offenders: list[str] = []
    for path in _model_files():
        for line, name, _receiver, call in _calls(path):
            if name != "DateTime":
                continue
            aware = any(
                keyword.arg == "timezone"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in call.keywords
            )
            if not aware:
                offenders.append(f"{path.name}:{line}")

    assert offenders == [], (
        "these DateTime columns are naive, so they store a wall clock that two "
        "servers in different zones read differently:\n" + "\n".join(offenders)
    )


def test_no_module_uses_the_wall_clock_directly() -> None:
    """`datetime.now()` without a zone is naive, and `utcnow()` is naive too.

    `utcnow()` is the more dangerous of the two: it returns the right instant
    with no tzinfo, so it looks correct and compares wrongly against anything
    aware.
    """

    offenders: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        if path.name == "time.py" and path.parent.name == "core":
            # The one module allowed to call the clock; it attaches UTC.
            continue
        for line, name, receiver, call in _calls(path):
            if receiver in SQL_FUNCTION_RECEIVERS:
                # `func.now()` is PostgreSQL's now(), which returns timestamptz.
                continue
            if name == "utcnow":
                offenders.append(f"{path.relative_to(APP_ROOT)}:{line}: utcnow()")
            elif name == "now" and not call.args and not call.keywords:
                offenders.append(f"{path.relative_to(APP_ROOT)}:{line}: now() with no tz")

    assert offenders == [], (
        "these produce naive timestamps; use app.core.time.utc_now():\n"
        + "\n".join(offenders)
    )


def test_the_wall_clock_scanner_finds_a_planted_violation(tmp_path: Path) -> None:
    """Guard the guard, and pin the distinction the fix depends on.

    The first version of this scanner flagged every `func.now()` server default —
    a rule that fires on correct code, which is worse than no rule. This asserts
    both halves: the Python clock is caught, and the SQL function is not.
    """

    planted = tmp_path / "offender.py"
    planted.write_text(
        "from datetime import datetime\n"
        "from sqlalchemy import func\n"
        "def bad():\n"
        "    return datetime.now()\n"
        "def worse():\n"
        "    return datetime.utcnow()\n"
        "def fine():\n"
        "    return func.now()\n",
        encoding="utf-8",
    )

    naive = [
        f"{line}:{name}"
        for line, name, receiver, call in _calls(planted)
        if receiver not in SQL_FUNCTION_RECEIVERS
        and (name == "utcnow" or (name == "now" and not call.args and not call.keywords))
    ]

    assert len(naive) == 2, f"expected both Python clock calls, got {naive}"
    assert not any("func" in entry for entry in naive)


@pytest.mark.parametrize(
    "name", ["audit_log", "center_profile", "idempotency_record", "outbox_event", "processing_job"]
)
def test_each_model_file_is_actually_scanned(name: str) -> None:
    """Names the files, so deleting one does not quietly shrink the guard."""

    assert (MODELS_ROOT / f"{name}.py").exists()
