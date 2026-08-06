"""`skipped_by_approved_policy` is reserved: recordable, never produced.

ADR-008 is Open and DOC-CONFLICT-029 is Open, and their interim rule is that
unknown or skipped scans fail closed. That leaves an awkward shape to get right,
and it is worth being precise about why it is this shape and not a simpler one.

The value is **not** refused by a database constraint. If a scanner genuinely
skipped a file, that is a fact, and a schema that cannot record it forces the
caller to write something else — which loses the truth and makes the skip harder to
notice, not easier. What must be impossible is the *consequence*: a skipped file
becoming available evidence. `ck_file_objects_available_requires_clean_scan` makes
that impossible for every value except `clean`, so the reserved value needs no
special case there.

What this file adds is the other half: no code path may **set** it. A skip the
application can produce is a skip that happens implicitly, and "implicitly" is
exactly what the interim rule forbids. Until ADR-008 approves a policy under which
skipping is allowed, the only way this value can enter the database is a human
writing it deliberately in a migration or a console.

Enumerating the scan outcomes in a CHECK would decide DOC-CONFLICT-029 from a
migration, which is why the column carries no value constraint at all.
"""

from __future__ import annotations

import ast
from pathlib import Path

import app.db.models  # noqa: F401  # registers every mapped table on Base.metadata
from app.db.base import Base
from app.db.models.file_object import (
    CLEAN_SCAN_STATUS,
    RESERVED_SCAN_STATUS,
    STORAGE_STATUSES,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "services" / "backend"
APP_ROOT = BACKEND_ROOT / "app"


def string_constants(path: Path) -> list[tuple[int, str]]:
    """Every string literal, docstrings included.

    Docstrings are *not* excluded here, unlike the deletion scan. This module's own
    prose names the value because it is explaining it; runtime code under `app/`
    has no such excuse, and a module docstring that mentions the value is a module
    that is thinking about producing it.
    """

    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        (node.lineno, node.value)
        for node in ast.walk(module)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def test_no_runtime_module_mentions_the_reserved_scan_status() -> None:
    """Except the model that declares it as a constant, which is the point of it.

    Declaring the name in one place and refusing it everywhere else means a future
    caller reaching for the value finds a constant with a docstring explaining why
    it may not be used, rather than inventing the string.
    """

    declaring_module = APP_ROOT / "db" / "models" / "file_object.py"
    offenders: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts or path == declaring_module:
            continue
        for line_number, value in string_constants(path):
            if RESERVED_SCAN_STATUS in value:
                offenders.append(f"{path.relative_to(APP_ROOT)}:{line_number}")

    assert offenders == [], (
        f"runtime code names {RESERVED_SCAN_STATUS!r}:\n"
        + "\n".join(offenders)
        + "\nADR-008 is Open. A skip this code can produce is a skip that happens "
        "implicitly."
    )


def test_the_declaring_module_does_not_put_the_reserved_value_in_a_constraint() -> None:
    """A CHECK naming it would either enumerate scan outcomes or refuse the value.

    Enumerating decides DOC-CONFLICT-029 from a migration. Refusing means a real
    skip cannot be recorded at all, which trades a small safety gain for losing the
    evidence that a scan did not happen.
    """

    table = Base.metadata.tables["file_objects"]
    naming_it = [
        constraint.name
        for constraint in table.constraints
        if RESERVED_SCAN_STATUS in str(getattr(constraint, "sqltext", ""))
    ]

    assert naming_it == []


def test_scan_status_carries_no_value_constraint() -> None:
    """The blocked value, asserted as an absence.

    Stated as a test rather than a comment because the tempting fix for any future
    scan-status bug is to add the enum, and the reason not to is two Open decisions
    that a reader of the model will not have in front of them.
    """

    table = Base.metadata.tables["file_objects"]
    constraining_scan_values = [
        constraint.name
        for constraint in table.constraints
        if "scan_status" in str(getattr(constraint, "sqltext", ""))
        and "storage_status" not in str(getattr(constraint, "sqltext", ""))
    ]

    assert constraining_scan_values == [], (
        "scan_status has acquired a value constraint: "
        f"{constraining_scan_values}. DOC-CONFLICT-029 and ADR-008 are both Open."
    )


def test_availability_is_gated_on_exactly_one_scan_value() -> None:
    """A whitelist, not a blacklist.

    A blacklist of bad outcomes lets an outcome nobody thought of through, and the
    outcome nobody thought of is the one a new scanner version introduces.
    """

    table = Base.metadata.tables["file_objects"]
    gate = next(
        constraint
        for constraint in table.constraints
        if constraint.name == "ck_file_objects_available_requires_clean_scan"
    )

    expression = str(gate.sqltext)

    assert f"scan_status = '{CLEAN_SCAN_STATUS}'" in expression
    assert "<>" in expression and "available" in expression


def test_deleted_by_policy_is_not_a_permitted_storage_status() -> None:
    """The recorded reconciliation, asserted.

    `status_catalog.yaml` lists eight spellings and forbids canonicalising `deleted`
    against `deleted_by_policy`. Keeping `deleted` and declining the policy variant
    is not canonicalisation — it refuses a value whose only writer would be the
    policy-driven deletion ADR-005 blocks from existing.
    """

    assert "deleted" in STORAGE_STATUSES
    assert "deleted_by_policy" not in STORAGE_STATUSES
    assert len(STORAGE_STATUSES) == 7
