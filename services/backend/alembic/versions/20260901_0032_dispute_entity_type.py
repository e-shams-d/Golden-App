"""A review task may be about a publication. `05_API_Specification.md` §20.6.

M9 slice 6. One CHECK widened by one value, and nothing else.

**Why the list needed a fifth value rather than a reused fourth.** §20.6: "A dispute creates a
visible manual review task", and §17 `:1185` requires that "a dispute references the exact
publication version". `manual_review_tasks` already carries `entity_record_version` — M8 slice 7
added it for the privacy check, and its comment says the pattern is `audit_logs`' — so the version
half is free. What was missing is a way to say the task is *about a publication*.

The four existing entity types are `bank_excel_export`, `bank_result_bundle`, `receipt_segment` and
`payment_attempt`. Attaching a dispute to the attempt was the tempting reuse: M9 slice 3 did
exactly that for an overpayment, because §13.1's list had no better fit. It is wrong here. A
publication covers a whole request and may span several attempts, so a dispute pointed at one
attempt would name a part of what the trader is complaining about — and `entity_record_version`
would then carry the *attempt's* version rather than the publication version §17 requires.

**This is an extension, not a conflict.** `04_Database_Schema.md` §13.1 lists the columns and does
not enumerate the values; the tuple is M8's own, and its comment states the rule it was chosen by:
"Enumerated rather than free text... each of these is a table that exists."
`payment_result_publications` is now a table that exists. Following that rule is what adds the
value; DOC-CONFLICT-052 does not apply, because no document says otherwise.

**No new grant.** `20260824_0025` already grants `status` and the assignment columns, and a dispute
inserts a task rather than changing one.

Revision ID: 20260901_0032
Revises: 20260831_0031
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260901_0032"
down_revision: str | Sequence[str] | None = "20260831_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `20260824_0025`'s four, plus the one this revision adds. Written out rather than imported from
# the model so that the migration says what it enforces without executing application code — the
# rule every value CHECK in this project follows.
ENTITY_TYPES = (
    "bank_excel_export",
    "bank_result_bundle",
    "receipt_segment",
    "payment_attempt",
    "payment_result_publication",
)

PREVIOUS_ENTITY_TYPES = ENTITY_TYPES[:-1]

# The **bare** name, not the stored one. The naming convention expands a `ck_` template around
# whatever it is given, so `drop_constraint` prefixes the name a second time: passing the full
# stored name produced `ck_manual_review_tasks_ck_manual_review_tasks_entity_type_value` and a
# migration that could not run. The convention applies on the way out as well as on the way in.
CONSTRAINT = "entity_type_value"


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, "manual_review_tasks", type_="check")
    op.create_check_constraint(
        "entity_type_value",
        "manual_review_tasks",
        f"entity_type IN ({_quoted(ENTITY_TYPES)})",
    )


def downgrade() -> None:
    # Narrowing back would fail against any dispute already recorded, which is correct: the rows
    # are the evidence that the value was needed. `04_Database_Schema.md`'s forward-fix policy
    # means this path exists for a database that never took the widened value.
    op.drop_constraint(CONSTRAINT, "manual_review_tasks", type_="check")
    op.create_check_constraint(
        "entity_type_value",
        "manual_review_tasks",
        f"entity_type IN ({_quoted(PREVIOUS_ENTITY_TYPES)})",
    )
