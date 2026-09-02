"""A duplicate is a warning, and a warning is somebody's work.
`08_Bank_File_and_Result_Processing.md` §8.7.

M10 slice 4B. No new table: two values on `manual_review_tasks.entity_type` and one on
`task_type`, so that §8.7's "A warning does not automatically delete or merge data" has somewhere
to put the warning.

**The two entity types are added by the list's own rule, and that rule is M8's.**
`20260824_0025`'s comment says: "Enumerated rather than free text: a generic reference whose type
is unconstrained is one nothing can navigate, and each of these is a table that exists."
`bank_statement_files` and `bank_statement_import_runs` are now tables that exist. M9 slice 6 added
`payment_result_publication` by exactly this argument; DOC-CONFLICT-052 does not apply, because
`04_Database_Schema.md` §13.1 lists the columns and enumerates no values.

**The task type is different, and it is declared rather than derived.** `TASK_TYPES` carries four
values and none of them describes a statement row suspected of being a duplicate. The nearest,
`payment_result_discrepancy`, is about an *outgoing* payment's result — a different direction of
money and a different person's queue. M8 reused `bundle_unresolved_segment` for a failed crop and
its comment explains why that was accurate rather than convenient; the same test fails here.

Reusing an inaccurate type would break the one thing the list exists for. Its own comment:
"the kind of attention needed, which is what lets a queue be filtered by skill rather than only by
age." An accountant reconciling outgoing payment results and one reviewing an incoming statement
import are looking for different things, and collapsing them makes the filter useless in both
directions. So `statement_duplicate_review` is added, spelled to match the existing
`<subject>_<kind>` pattern, and recorded as a name M0 owes.

**No new grant.** `20260824_0025` already grants what a task needs; this inserts tasks rather than
changing them.

Revision ID: 20260908_0039
Revises: 20260907_0038
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260908_0039"
down_revision: str | Sequence[str] | None = "20260907_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `20260901_0032`'s five, plus the two this revision adds. Written out rather than imported from
# the model so the migration says what it enforces without executing application code.
ENTITY_TYPES = (
    "bank_excel_export",
    "bank_result_bundle",
    "receipt_segment",
    "payment_attempt",
    "payment_result_publication",
    "bank_statement_file",
    "bank_statement_import_run",
)

PREVIOUS_ENTITY_TYPES = ENTITY_TYPES[:-2]

# `20260824_0025`'s four, plus the one this revision declares.
TASK_TYPES = (
    "bank_export_integrity",
    "bundle_unresolved_segment",
    "segment_privacy_review",
    "payment_result_discrepancy",
    "statement_duplicate_review",
)

PREVIOUS_TASK_TYPES = TASK_TYPES[:-1]

# The **bare** names. The naming convention expands a `ck_` template around whatever it is given,
# so passing the stored name makes `drop_constraint` prefix it twice — which produced
# `ck_manual_review_tasks_ck_manual_review_tasks_entity_type_value` and an unrunnable migration
# when `20260901_0032` first tried it.
ENTITY_CONSTRAINT = "entity_type_value"
TASK_TYPE_CONSTRAINT = "task_type_value"


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.drop_constraint(ENTITY_CONSTRAINT, "manual_review_tasks", type_="check")
    op.create_check_constraint(
        ENTITY_CONSTRAINT,
        "manual_review_tasks",
        f"entity_type IN ({_quoted(ENTITY_TYPES)})",
    )
    op.drop_constraint(TASK_TYPE_CONSTRAINT, "manual_review_tasks", type_="check")
    op.create_check_constraint(
        TASK_TYPE_CONSTRAINT,
        "manual_review_tasks",
        f"task_type IN ({_quoted(TASK_TYPES)})",
    )


def downgrade() -> None:
    # Narrowing back fails against any duplicate review already recorded, which is correct: those
    # rows are the evidence the values were needed. `04_Database_Schema.md`'s forward-fix policy
    # means this path exists for a database that never took the widened values.
    op.drop_constraint(TASK_TYPE_CONSTRAINT, "manual_review_tasks", type_="check")
    op.create_check_constraint(
        TASK_TYPE_CONSTRAINT,
        "manual_review_tasks",
        f"task_type IN ({_quoted(PREVIOUS_TASK_TYPES)})",
    )
    op.drop_constraint(ENTITY_CONSTRAINT, "manual_review_tasks", type_="check")
    op.create_check_constraint(
        ENTITY_CONSTRAINT,
        "manual_review_tasks",
        f"entity_type IN ({_quoted(PREVIOUS_ENTITY_TYPES)})",
    )
