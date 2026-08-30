"""No float touches money, and no timestamp column loses its timezone.

Both rules are from the approved MONEY_TIME_CONTRACT, and both are the kind that
hold until the first person who has not read it adds a column. So they are
checked by parsing the source rather than by review.

The float rule is the sharper one. A `Float` column accepts every test value
anyone writes — 100, 250, 1000 all round-trip perfectly — and starts losing whole
rials at amounts this system reaches routinely. There is no test of *behaviour*
that catches it early; only a check of the declaration does.

Covers: UT-TIME-001.
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


# Columns the schema specification itself declares as `NUMERIC`, and which hold no money.
#
# **This is not a widening of the money rule; it is the boundary the rule always had.** The guard
# below exists because binary floating point loses rials at scale, and its own docstring says
# "forbidden for *monetary* storage". A normalized crop coordinate is not a monetary value: it is a
# fraction of a page, `04_Database_Schema.md:1213-1216` specifies it as `NUMERIC(10,6)` by name, and
# a float would be wrong for the same reason money must not be one — a rectangle that reproduces a
# *different* crop is the exact failure DOC-CONFLICT-057 is about.
#
# Keyed by `(module, column)` rather than by file, so the exemption cannot drift onto a money column
# in the same model. `test_no_exempted_column_looks_monetary` is what keeps that true.
NON_MONETARY_NUMERIC: dict[tuple[str, str], str] = {
    ("receipt_segment.py", "bbox_x"): (
        "Normalized crop coordinate, 0..1. 04_Database_Schema.md:1213 specifies NUMERIC(10,6) and "
        "the value must reproduce a rectangle exactly; a float would store a number the database "
        "never held."
    ),
    ("receipt_segment.py", "bbox_y"): (
        "Normalized crop coordinate, 0..1. 04_Database_Schema.md:1214 specifies NUMERIC(10,6)."
    ),
    ("receipt_segment.py", "bbox_width"): (
        "Normalized crop width, >0..1. 04_Database_Schema.md:1215 specifies NUMERIC(10,6)."
    ),
    ("receipt_segment.py", "bbox_height"): (
        "Normalized crop height, >0..1. 04_Database_Schema.md:1216 specifies NUMERIC(10,6)."
    ),
    ("receipt_segment.py", "extraction_confidence"): (
        "A confidence between 0 and 1 for a later phase that guesses. "
        "04_Database_Schema.md:1228 specifies NUMERIC(5,4). Never money, and never a rial."
    ),
    ("matching_candidate.py", "score"): (
        "A match score between 0 and 1, bounded by 04_Database_Schema.md:1268's own CHECK. It "
        "ranks a suggestion and cannot become a payment: :1274 says accepting a candidate does "
        "not set an attempt to paid, and 20260829_0028 grants the runtime nothing at all on "
        "payment_attempts, so no arithmetic on this column can reach money. NUMERIC rather than "
        "a float because the CHECK's bounds have to hold exactly at 0 and at 1."
    ),
}

# Any column whose name suggests money. Deliberately broad: this decides what the exemption above
# may never contain, so a false positive costs a rename and a false negative costs the rule.
MONETARY_HINTS = ("amount", "irr", "toman", "rial", "total", "price", "fee", "balance")


def _numeric_column_owner(tree: ast.AST, lineno: int) -> str | None:
    """The name of the column a forbidden type appears inside, if any.

    Walks assignments and returns the target whose value spans `lineno`. Needed because the scanner
    reports a type reference and the exemption is per column: exempting a *file* would let a money
    column arrive beside an approved coordinate and inherit its permission.
    """

    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign | ast.Assign):
            continue
        start = node.lineno
        end = getattr(node, "end_lineno", start) or start
        if not (start <= lineno <= end):
            continue
        target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0]
        if isinstance(target, ast.Name):
            return target.id
    return None


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
            if name not in FORBIDDEN_COLUMN_TYPES:
                continue
            # `Float` is never exempt; only `Numeric` can be, and only per column. Binary floating
            # point is wrong for every value this system stores, monetary or not.
            column = _numeric_column_owner(tree, node.lineno)
            if name == "Numeric" and (path.name, column) in NON_MONETARY_NUMERIC:
                continue
            offenders.append(f"{path.name}:{node.lineno}: {name}")
    return sorted(set(offenders))


def test_the_scanner_sees_the_models() -> None:
    """Guard the guard: an empty file list passes every check below."""

    files = _model_files()

    assert len(files) >= 4, f"only found {[f.name for f in files]}"


def test_no_exempted_column_looks_monetary() -> None:
    """The exemption above may never hold a money column, and this is what makes that true.

    `NON_MONETARY_NUMERIC` subtracts from the floating-point guard, so it is where a monetary
    `NUMERIC` would be parked to make a failure go away. Names are checked against a deliberately
    broad list of money words: a false positive costs somebody a rename, and a false negative costs
    the rule the guard exists to enforce.
    """

    assert NON_MONETARY_NUMERIC, "the set is empty; delete it rather than carrying an unused escape"

    suspicious = sorted(
        f"{module}:{column}"
        for module, column in NON_MONETARY_NUMERIC
        for hint in MONETARY_HINTS
        if hint in column.lower()
    )

    assert suspicious == [], (
        "these exempted columns have monetary-sounding names. NUMERIC for money needs a recorded "
        f"governance exception, not an entry here: {suspicious}"
    )


def test_each_numeric_exemption_cites_the_specification() -> None:
    """A bare entry is the thing this mechanism must not become.

    Every reason names the document line that specifies the type, so the exemption records a
    decision the schema already made rather than a preference this test file has.
    """

    for column, reason in NON_MONETARY_NUMERIC.items():
        assert len(reason) > 60, f"{column} is exempted with no real reason"
        assert "04_Database_Schema.md:" in reason, f"{column} cites no specification line"


def test_float_is_never_exempt() -> None:
    """`Float` cannot be waived by the mechanism above, only `Numeric`.

    Binary floating point is wrong for every value this system stores — a coordinate no less than a
    rial — so the exemption is typed narrowly rather than left as "the guard can be silenced".
    """

    import inspect as inspect_module

    source = inspect_module.getsource(_floating_point_references)

    assert 'name == "Numeric"' in source, (
        "the exemption is no longer restricted to Numeric, so a Float column could be waived"
    )


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
