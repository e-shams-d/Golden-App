"""The review queue's table and its transitions, checked without a database.

M8 slice 3. The structural half of `DB-TASK-001` and the whole of `SVC-TASK-001` and
`SVC-TASK-002` — the last two are claims about what the code cannot express, so they are asserted
against the transition table and the query surface rather than by driving PostgreSQL.

Covers: DB-TASK-001, SVC-TASK-001, SVC-TASK-002.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE = REPOSITORY_ROOT / "docs" / "governance"
BACKEND = REPOSITORY_ROOT / "services" / "backend"
SCHEMA = (
    REPOSITORY_ROOT
    / "Implementation Docs"
    / "02_Architecture_and_Contracts"
    / "04_Database_Schema.md"
)


def documented_fields() -> set[str]:
    """§13.1's `Fields:` sentence, parsed. `:1314`."""

    text = SCHEMA.read_text(encoding="utf-8")
    start = text.index("## 13.1 `manual_review_tasks`")
    body = text[start:]
    sentence = body[: body.index("\n\n", body.index("Fields:"))]
    import re

    return set(re.findall(r"`([a-z_]+)`", sentence[sentence.index("Fields:") :]))


def test_the_document_still_lists_this_table() -> None:
    """The control. An empty parse makes the comparison below vacuous."""

    assert len(documented_fields()) > 12


def test_the_table_carries_every_documented_field() -> None:
    """`DB-TASK-001`. §13.1's list, minus its two shorthand words.

    `timestamps` is document 04's abbreviation for the created/updated pair throughout, and it is
    named here rather than filtered by a pattern so a real new column cannot hide behind the filter.
    """

    from app.db.models.manual_review_task import ManualReviewTask

    columns = {column.name for column in ManualReviewTask.__table__.columns}
    missing = sorted(documented_fields() - {"timestamps"} - columns)

    assert missing == [], f"§13.1 names these and the model has none of them: {missing}"


def test_the_statuses_are_the_catalogues() -> None:
    """`DB-TASK-001`. Four canonical states, from `status_catalog.yaml`.

    The only M8 aggregate the catalogue settles completely — no unresolved aliases at all, which
    after `bank_result_bundle`'s five and `receipt_segment`'s two is worth asserting rather than
    assuming.
    """

    from app.db.models.manual_review_task import OPEN_STATUSES, TASK_STATUSES

    catalogue = yaml.safe_load((GOVERNANCE / "status_catalog.yaml").read_text(encoding="utf-8"))
    aggregates = catalogue.get("aggregates", catalogue)
    block = aggregates["manual_review_task"]

    assert list(TASK_STATUSES) == [state["canonical"] for state in block["states"]]
    assert not block.get("unresolved_aliases"), "this aggregate gained an unresolved alias"
    # The queue is exactly the two states where work is outstanding, which is also the partial
    # index's predicate. If these diverged the index would cover rows the queue does not read.
    assert set(OPEN_STATUSES) == {"open", "in_progress"}


def test_the_partial_index_covers_exactly_the_open_states() -> None:
    """`DB-TASK-001`. §13.1's index at `:1317`, and its predicate is the queue's definition.

    Read off the model rather than transcribed: the predicate and `OPEN_STATUSES` have to agree, and
    a test that restated the predicate would agree with itself.
    """

    from app.db.models.manual_review_task import OPEN_STATUSES, ManualReviewTask

    predicates = [
        str(index.dialect_options["postgresql"].get("where"))
        for index in ManualReviewTask.__table__.indexes
        if index.name == "idx_manual_review_open_queue"
    ]

    assert predicates, "§13.1's queue index is missing"
    for status in OPEN_STATUSES:
        assert f"'{status}'" in predicates[0]
    for status in ("resolved", "cancelled"):
        assert f"'{status}'" not in predicates[0], (
            f"the queue index covers {status}, so a queue read touches finished work"
        )


@pytest.mark.parametrize(
    "constraint",
    [
        "resolved_requires_a_disposition",
        "unresolved_requires_a_reason",
        "in_progress_requires_an_assignee",
        "priority_in_range",
    ],
)
def test_each_added_constraint_exists(constraint: str) -> None:
    """The four §13.1 does not state, one test each so a failure names the missing one.

    `05_API_Specification.md:2065` requires an explicit disposition to resolve, and requires prose
    when the underlying item is still unresolved. Both live in the table rather than only in the
    command, because two commands can forget a rule differently.
    """

    from app.db.models.manual_review_task import ManualReviewTask

    names = {
        check.name
        for check in ManualReviewTask.__table__.constraints
        if check.__class__.__name__ == "CheckConstraint" and check.name
    }

    assert any(name.endswith(constraint) for name in names), sorted(names)


def test_the_permitted_transitions_are_exactly_five() -> None:
    """`SVC-TASK-001`. The transition table, asserted as data.

    Written as a set in the command module so the four functions cannot disagree about what is
    allowed, and asserted here so the set itself is a decision rather than an accident.

    **Nothing leaves `resolved` or `cancelled`.** A resolved task is the record of a decision, and
    reopening one would erase the disposition `:2065` requires it to carry — so something that needs
    looking at again is a new task, which is also what keeps the one-open-task-per-entity index
    meaningful.
    """

    from app.commands.manual_review_task import PERMITTED_TRANSITIONS

    assert frozenset(
        {
            ("open", "in_progress"),
            ("open", "resolved"),
            ("in_progress", "resolved"),
            ("open", "cancelled"),
            ("in_progress", "cancelled"),
        }
    ) == PERMITTED_TRANSITIONS

    terminal = [pair for pair in PERMITTED_TRANSITIONS if pair[0] in {"resolved", "cancelled"}]
    assert terminal == [], f"a finished task can be moved: {terminal}"


def test_no_command_writes_a_status_outside_the_transition_table() -> None:
    """`SVC-TASK-001`'s enforcement half.

    Every status write in the command module goes through `_require_transition` first. Asserted by
    walking the AST for assignments to `task.status`: a fifth command added later that set the
    status directly would pass every other test in this file.
    """

    module = BACKEND / "app" / "commands" / "manual_review_task.py"
    tree = ast.parse(module.read_text(encoding="utf-8"))

    functions_assigning_status: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Assign):
                continue
            for target in inner.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr == "status"
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "task"
                ):
                    functions_assigning_status.add(node.name)

    assert functions_assigning_status, "found no status writes; the assertion would be vacuous"

    guarded = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and any(
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Name)
            and inner.func.id == "_require_transition"
            for inner in ast.walk(node)
        ):
            guarded.add(node.name)

    # `open_task` writes the initial status and has no transition to check — a task is born `open`.
    unguarded = sorted(functions_assigning_status - guarded - {"open_task"})

    assert unguarded == [], (
        f"these write task.status without checking the transition table first: {unguarded}"
    )


def test_no_read_joins_through_the_generic_entity_reference() -> None:
    """`SVC-TASK-002`. §13.1 at `:1324`: the reference is for queue navigation only.

    "Financial relationship truth remains in explicit tables." So no query anywhere may join a
    financial table to `manual_review_tasks` through `entity_id` — a generic pointer has no foreign
    key and cannot be trusted to name a row that still exists, let alone one of the right kind.

    Scoped to modules that actually touch `ManualReviewTask`. The first version of this test flagged
    any module mentioning `entity_id` alongside any join, and reported eleven files — `entity_id` is
    a column on `audit_logs` and `processing_jobs` too, so the scan condemned correct code. A rule
    that flags correct code is one people learn to ignore, which is the money guard's own lesson
    applied to this one.
    """

    surface = []
    for directory in ("app/commands", "app/api", "app/db"):
        for path in (BACKEND / directory).rglob("*.py"):
            surface.append((path, path.read_text(encoding="utf-8")))

    touching = [
        (path, text)
        for path, text in surface
        if "ManualReviewTask" in text or "manual_review" in text
    ]

    assert touching, "found no module touching the review queue; the assertion would be vacuous"

    offending = [
        str(path.relative_to(REPOSITORY_ROOT))
        for path, text in touching
        if "ManualReviewTask.entity_id" in text and (".join(" in text or "outerjoin(" in text)
    ]

    assert offending == [], (
        "these modules join through the review queue's generic reference, which §13.1 forbids: "
        f"{offending}"
    )


def test_the_table_has_no_typed_reference_to_a_financial_row() -> None:
    """The same rule from the schema side, and the sharper half.

    Slice 3's own caller — M7's quarantine path — would find a `bank_excel_export_id` convenient.
    That column is exactly the "financial relationship truth" §13.1 puts in explicit tables: whether
    an export is quarantined is `bank_excel_exports.status`, and a task is a note that somebody
    should look at it.

    Listed as forbidden names rather than as an allow-list, because the claim that survives somebody
    adding a column for a good reason is the one about what must never appear.
    """

    from app.db.models.manual_review_task import ManualReviewTask

    columns = {column.name for column in ManualReviewTask.__table__.columns}
    forbidden = {
        "bank_excel_export_id",
        "bank_result_bundle_id",
        "receipt_segment_id",
        "payment_attempt_id",
        "payment_batch_id",
    }
    present = sorted(forbidden & columns)

    assert present == [], (
        f"these typed references make the task a financial relationship: {present}. §13.1 keeps "
        "that truth in explicit tables and limits this table to queue navigation."
    )

    # And the generic pair carries no foreign key, which is both deliberate and unavoidable.
    keyed = [
        key.column.name
        for key in ManualReviewTask.__table__.foreign_keys
        for _ in [None]
        if "entity" in str(key.parent.name)
    ]
    assert keyed == [], f"entity_id has a foreign key: {keyed}"
