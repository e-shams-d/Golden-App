"""Tell the trader their order is ready. `audit_outbox_catalog.yaml:79`.

M10 slice 8. Two CHECKs on `notifications` widen by one value each, so M9 slice 7's projection can
consume the one outbox event this milestone has.

**The event existed in the catalogue before any of this was built and nothing published it.**
`GoldOrderReadyForDispatch` is listed in `audit_outbox_catalog.yaml`'s eleven, and
`command_catalog.yaml` names it on `incoming_payment.confirm` — the confirmation slice 6 built.
Slice 6 declared `outbox_event_type=None` in error, and no gate could see it: the registry test
asked whether a declared event was real and never whether a required one was declared. Slice 8 adds
that gate, fixes the declaration, emits the event, and this revision is what lets a notification be
written from it.

**One notification type and one entity type.** `gold_order_ready_for_dispatch` says what happened;
`gold_sale_order` is what it points at. Both lists are enumerated for M8's stated reason — "a type
nothing can navigate is worse than no type" — so both need widening rather than a free-text value.

**No grant.** `20260901_0033` already grants what a notification needs, and this adds a value
rather than a column.

Revision ID: 20260912_0043
Revises: 20260911_0042
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260912_0043"
down_revision: str | Sequence[str] | None = "20260911_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `20260901_0033`'s three, plus the one this revision adds.
NOTIFICATION_TYPES = (
    "payment_result_published",
    "payment_result_corrected",
    "payment_attempt_failed",
    "gold_order_ready_for_dispatch",
)

PREVIOUS_NOTIFICATION_TYPES = NOTIFICATION_TYPES[:-1]

ENTITY_TYPES = (
    "payment_request",
    "payment_result_publication",
    "gold_sale_order",
)

PREVIOUS_ENTITY_TYPES = ENTITY_TYPES[:-1]

# The **bare** names. The naming convention re-prefixes whatever `drop_constraint` is given, which
# is the trap `20260901_0032` documented after producing an unrunnable migration.
TYPE_CONSTRAINT = "notification_type_value"
ENTITY_CONSTRAINT = "entity_type_value"


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.drop_constraint(TYPE_CONSTRAINT, "notifications", type_="check")
    op.create_check_constraint(
        TYPE_CONSTRAINT,
        "notifications",
        f"notification_type IN ({_quoted(NOTIFICATION_TYPES)})",
    )
    op.drop_constraint(ENTITY_CONSTRAINT, "notifications", type_="check")
    op.create_check_constraint(
        ENTITY_CONSTRAINT,
        "notifications",
        f"entity_type IN ({_quoted(ENTITY_TYPES)})",
    )


def downgrade() -> None:
    # Narrowing back fails against any gold-order notification already written, which is correct:
    # those rows are the evidence the values were needed.
    op.drop_constraint(ENTITY_CONSTRAINT, "notifications", type_="check")
    op.create_check_constraint(
        ENTITY_CONSTRAINT,
        "notifications",
        f"entity_type IN ({_quoted(PREVIOUS_ENTITY_TYPES)})",
    )
    op.drop_constraint(TYPE_CONSTRAINT, "notifications", type_="check")
    op.create_check_constraint(
        TYPE_CONSTRAINT,
        "notifications",
        f"notification_type IN ({_quoted(PREVIOUS_NOTIFICATION_TYPES)})",
    )
