"""A trader's claim to have paid, with evidence. `04_Database_Schema.md` §10.3.

M10 slice 2. One table, and §10.3's first line is the whole design: "A claim/evidence submitted for
a gold sale." Not a payment — a claim that one was made.

**Doc 05 §21.3 says the same thing in five words: "Uploading evidence never confirms payment."**
So this table carries `amount_irr` (what the trader says they sent) *and* `confirmed_amount_irr`
(what the centre verified), and they are different columns because they are different facts. Slice
6 writes the second, against a bank statement row the centre imported itself. Until then it is
null, and the migration grants nothing that would let this slice write it.

**Grants: `status` and the two confirmation columns, plus `record_version` and `updated_at`.** Not
`amount_irr`, not `tracking_number`, not `evidence_file_id` — those are what the trader claimed,
and a claim that could be rewritten after submission is not evidence of anything. The confirmation
columns are granted here rather than in slice 6 because they belong to the same lifecycle and
splitting a column-level grant across two revisions makes the second unreadable without the first;
what stops this slice writing them is that no command does.

**Nine statuses, and they are the catalogue's.** `status_catalog.yaml`'s
`incoming_payment_receipt` aggregate carries all nine canonical with no aliases — checked value by
value before this CHECK was written, because `test_status_catalogue_drift.py` holds every enforced
CHECK to its aggregate exactly.

**`raw_payment_date` beside `payment_at_normalized`.** §10.3 asks for both, and ADR-006 is why: a
trader's receipt shows a Jalali date, the platform stores an instant, and throwing the raw string
away means a mismatch can never be re-examined. The same pair `bank_statement_rows` will carry in
slice 4.

Revision ID: 20260905_0036
Revises: 20260904_0035
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260905_0036"
down_revision: str | Sequence[str] | None = "20260904_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `status_catalog.yaml`'s `incoming_payment_receipt` aggregate, all nine, in its order.
RECEIPT_STATUSES = (
    "submitted",
    "waiting_for_bank_statement",
    "candidate_match",
    "needs_review",
    "duplicate_suspected",
    "partially_confirmed",
    "confirmed",
    "rejected",
    "superseded",
)

# M5's `AMOUNT_UNITS`. What the trader typed is provenance; `amount_irr` is canonical.
AMOUNT_UNITS = ("IRR", "TOMAN")

# The lifecycle and the confirmation. Everything else is the claim, and a claim is not editable.
GRANTED_COLUMNS = (
    "status",
    "confirmed_amount_irr",
    "confirmed_by_admin_user_id",
    "confirmed_at",
    "record_version",
    "updated_at",
)


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
            f"Migration {revision} grants on mutable columns and these roles are "
            f"not set: {', '.join(missing)}."
        )
    return tuple(str(value) for value in configured.values())


def upgrade() -> None:
    op.create_table(
        "incoming_payment_receipts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "gold_sale_order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("gold_sale_orders.id", name="fk_incoming_receipts_order"),
            nullable=False,
        ),
        # **Denormalised from the order deliberately.** `app/security/ownership.py` scopes a query
        # by a trader column on the row itself, and a receipt whose owner could only be found
        # through a join is one the ownership helper cannot constrain. The composite foreign key
        # below is what keeps the two consistent: a receipt cannot name one order and another
        # order's trader.
        sa.Column("trader_id", postgresql.UUID(as_uuid=True), nullable=False),
        # What the trader says they sent.
        sa.Column("amount_irr", sa.BigInteger(), nullable=False),
        sa.Column("entered_amount_value", sa.BigInteger(), nullable=True),
        sa.Column("entered_amount_unit", sa.String(8), nullable=True),
        sa.Column("tracking_number", sa.String(128), nullable=True),
        # Both, per §10.3 and ADR-006. See the module docstring.
        sa.Column("raw_payment_date", sa.String(64), nullable=True),
        sa.Column("payment_at_normalized", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_bank_name", sa.String(160), nullable=True),
        # A *hint*, not an account number. §10.3 names it that way and the distinction is the
        # point: a trader's own account identifier is not something this platform needs to hold.
        sa.Column("source_account_hint", sa.String(64), nullable=True),
        sa.Column(
            "destination_bank_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bank_accounts.id", name="fk_incoming_receipts_destination"),
            nullable=True,
        ),
        sa.Column("sender_name", sa.String(255), nullable=True),
        sa.Column(
            "evidence_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("file_objects.id", name="fk_incoming_receipts_evidence"),
            nullable=True,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        # What the centre verified. Null until slice 6 confirms against a statement row.
        sa.Column("confirmed_amount_irr", sa.BigInteger(), nullable=True),
        sa.Column(
            "confirmed_by_admin_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", name="fk_incoming_receipts_confirmed_by"),
            nullable=True,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_version", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # §10.3's two CHECKs verbatim. The second permits **zero**, which is not an oversight: a
        # confirmation may find that nothing arrived, and that is a different fact from not having
        # looked. `amount_irr` has no such allowance — a claim of nothing is not a claim.
        sa.CheckConstraint("amount_irr > 0", name="amount_positive"),
        sa.CheckConstraint(
            "confirmed_amount_irr IS NULL OR confirmed_amount_irr >= 0",
            name="confirmed_amount_not_negative",
        ),
        sa.CheckConstraint(f"status IN ({_quoted(RECEIPT_STATUSES)})", name="status_value"),
        sa.CheckConstraint(
            f"entered_amount_unit IS NULL OR entered_amount_unit IN ({_quoted(AMOUNT_UNITS)})",
            name="entered_amount_unit_value",
        ),
        # Not in §10.3, and it closes the shape M9 closed three times: a row that says it was
        # confirmed must say by whom and when, and a row that was not must carry neither.
        sa.CheckConstraint(
            "(confirmed_at IS NULL AND confirmed_by_admin_user_id IS NULL)"
            " OR "
            "(confirmed_at IS NOT NULL AND confirmed_by_admin_user_id IS NOT NULL)",
            name="confirmation_needs_an_actor",
        ),
        # The trader on the receipt is the trader on the order. Without this the denormalised
        # column above would be a second, unchecked copy of the ownership fact — which is exactly
        # how a trader ends up seeing somebody else's receipt through a scoped query.
        sa.ForeignKeyConstraint(
            ["gold_sale_order_id", "trader_id"],
            ["gold_sale_orders.id", "gold_sale_orders.trader_id"],
            name="fk_incoming_receipts_order_trader",
        ),
    )

    op.create_index(
        "idx_incoming_receipts_order_status",
        "incoming_payment_receipts",
        ["gold_sale_order_id", "status", "created_at"],
    )
    # §10.3's partial index verbatim. Partial because a tracking number is optional — a trader who
    # paid at a counter may not have one — and indexing the nulls would be indexing absence.
    op.create_index(
        "idx_incoming_receipts_tracking",
        "incoming_payment_receipts",
        ["tracking_number"],
        postgresql_where=sa.text("tracking_number IS NOT NULL"),
    )

    bind = op.get_bind()
    columns = ", ".join(GRANTED_COLUMNS)
    for role in _runtime_roles():
        bind.execute(
            sa.text(
                f'GRANT UPDATE ({columns}) ON public."incoming_payment_receipts" TO "{role}"'
            )
        )


def downgrade() -> None:
    op.drop_index("idx_incoming_receipts_tracking", table_name="incoming_payment_receipts")
    op.drop_index("idx_incoming_receipts_order_status", table_name="incoming_payment_receipts")
    op.drop_table("incoming_payment_receipts")
