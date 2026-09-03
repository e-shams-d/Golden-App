"""The second axis, and the column a confirmation writes.
`06_Workflows_and_State_Machines.md` §11.2.

M10 slice 6. One column on `incoming_payment_matches`, and it is the answer to a question two
slices have now recorded as open.

**The two-axis choice, taken and argued.** `status_catalog.yaml` carries two aggregates for this
one table: `incoming_match_candidate` (document 06 §11.1's `proposed / accepted_for_review /
rejected / superseded / expired`) and `incoming_confirmed_match` (§11.2's `active / replaced /
revoked`). Slice 5 enforced the first on `status` and left the second unplaced, because it wrote no
confirmations. This slice writes them, so the question can no longer be deferred.

**A second column, not a wider CHECK.** Three reasons, and the third is the one that decides it:

- The candidate lifecycle has no state meaning "confirmed" — §11.3's first rule is that even
  `accepted_for_review` "is not financial confirmation" — so extending `status` would mean either
  inventing a sixth candidate state or overwriting the candidate's own history with a confirmation.
- `status_catalog.yaml` names the two aggregates separately and describes them as separate
  lifecycles. Collapsing them here would make the catalogue's own distinction unreadable from the
  schema.
- **The two axes move independently and both matter afterwards.** A match that was `proposed` and
  then confirmed is a different record from one that was `accepted_for_review` first; slice 8's
  correction sets `confirmation_status` to `replaced` while the candidate's own history stays put.
  One column cannot hold both without losing one.

Nullable, and null means "not confirmed" — the same shape `confirmed_at` already has beside it.
There is no `CHECK` tying the two together beyond the pair rule the table already carries, because
`confirmation_status` is set in the same statement as `confirmed_at` and the existing
`confirmation_needs_an_actor` CHECK already refuses half a confirmation.

**The catalogue still owes the reconciliation.** This is an implementation choosing the shape the
catalogue's own note suggested — "a two-axis model or extend the canonical lifecycle" — for the
table it could no longer avoid. M0 may prefer the other reading, and the plan records it.

**Grants: `confirmation_status` on the match, and nothing new anywhere else.** `20260909_0040`
already grants the match's confirmation columns and `20260905_0036` the receipt's; the order's
`status` has been grantable since `20260904_0035`. A confirmation writes only columns some earlier
revision already opened, which is what makes this revision one column wide.

Revision ID: 20260910_0041
Revises: 20260909_0040
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260910_0041"
down_revision: str | Sequence[str] | None = "20260909_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `status_catalog.yaml`'s `incoming_confirmed_match` aggregate, all three, in its order.
# Document 06 §11.2 is its source.
CONFIRMATION_STATUSES = ("active", "replaced", "revoked")

# `20260908_0039`'s seven, plus the one this revision adds by the list's own stated rule — it is a
# table that exists. An overpayment task must point at the **receipt** whose confirmation was
# refused; the first draft of this slice pointed it at `bank_statement_import_run` while passing a
# receipt id, which is a reference nothing can navigate and exactly what `20260824_0025`'s comment
# says the enumeration exists to prevent.
ENTITY_TYPES = (
    "bank_excel_export",
    "bank_result_bundle",
    "receipt_segment",
    "payment_attempt",
    "payment_result_publication",
    "bank_statement_file",
    "bank_statement_import_run",
    "incoming_payment_receipt",
)

PREVIOUS_ENTITY_TYPES = ENTITY_TYPES[:-1]

# `20260908_0039`'s five, plus the one this revision declares. The nearest existing value is
# `payment_result_discrepancy` and it is about an **outgoing** payment's result — a different
# direction of money and a different person's queue — and 4B's `statement_duplicate_review` is
# about a statement row rather than a claim. Using either would file this in a queue an accountant
# filters for something else, which is the one thing `TASK_TYPES` exists to prevent.
TASK_TYPES = (
    "bank_export_integrity",
    "bundle_unresolved_segment",
    "segment_privacy_review",
    "payment_result_discrepancy",
    "statement_duplicate_review",
    "incoming_payment_discrepancy",
)

PREVIOUS_TASK_TYPES = TASK_TYPES[:-1]

ENTITY_CONSTRAINT = "entity_type_value"
TASK_TYPE_CONSTRAINT = "task_type_value"


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _runtime_roles() -> tuple[str, ...]:
    from app.core.config import load_settings

    settings = load_settings()
    configured = {
        "APP_DB_ROLE": settings.app_db_role,
        "WORKER_DB_ROLE": settings.worker_db_role,
    }
    missing = sorted(name for name, value in configured.items() if not value)
    if missing:
        raise RuntimeError(
            f"Migration {revision} grants on a mutable column and these roles are "
            f"not set: {', '.join(missing)}."
        )
    return tuple(str(value) for value in configured.values())


def upgrade() -> None:
    op.add_column(
        "incoming_payment_matches",
        sa.Column("confirmation_status", sa.String(32), nullable=True),
    )
    op.create_check_constraint(
        "confirmation_status_value",
        "incoming_payment_matches",
        f"confirmation_status IS NULL OR confirmation_status IN "
        f"({_quoted(CONFIRMATION_STATUSES)})",
    )
    # A confirmed match must say when, and a match that says when must say what it is now. The
    # existing `confirmation_needs_an_actor` covers the actor; this covers the axis.
    op.create_check_constraint(
        "confirmation_status_needs_a_time",
        "incoming_payment_matches",
        "(confirmation_status IS NULL AND confirmed_at IS NULL)"
        " OR "
        "(confirmation_status IS NOT NULL AND confirmed_at IS NOT NULL)",
    )
    # **No partial unique on `(bank_statement_row_id) WHERE confirmation_status = 'active'`, and
    # writing one was the first thing this revision did.**
    #
    # Document 06 §11.3's third rule wants the protection: "A row already used in an active match
    # causes a duplicate/conflict guard unless an explicit combined-payment model is used." But it
    # says *guard*, and §10.7 `:809` says a partial unique is only for when "the business confirms
    # strict one-row/one-receipt matching" — which is the plan's G-2, still the owner's. The
    # exception clause in §11.3 names the same open question from the other side.
    #
    # So the guard lives in `app/commands/incoming_confirmation.py`, where it can be lifted by a
    # business decision without a migration, and slice 5's
    # `test_no_partial_unique_constrains_the_pair` stays true. An index would have answered G-2 in
    # `alembic/` — which is the thing slice 5's test exists to prevent, and it would have been this
    # slice that tripped it.
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

    bind = op.get_bind()
    for role in _runtime_roles():
        bind.execute(
            sa.text(
                'GRANT UPDATE (confirmation_status) ON public."incoming_payment_matches" '
                f'TO "{role}"'
            )
        )


def downgrade() -> None:
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
    op.drop_constraint(
        "confirmation_status_needs_a_time", "incoming_payment_matches", type_="check"
    )
    op.drop_constraint("confirmation_status_value", "incoming_payment_matches", type_="check")
    op.drop_column("incoming_payment_matches", "confirmation_status")
