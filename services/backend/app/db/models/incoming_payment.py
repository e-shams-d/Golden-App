"""A trader's claim to have paid for gold. `04_Database_Schema.md` §10.3.

M10 slice 2. §10.3 opens by calling it "a claim/evidence submitted for a gold sale", and doc 05
§21.3 closes the same thought: **"Uploading evidence never confirms payment."**

**Two amount columns, because they are two facts.** `amount_irr` is what the trader says they
sent; `confirmed_amount_irr` is what the centre verified against a bank statement it imported
itself. Slice 6 writes the second. Collapsing them into one would make a claim indistinguishable
from a verification — which is the whole reason this milestone imports statements at all.

**`trader_id` is denormalised from the order on purpose.** `app/security/ownership.py` scopes a
query by a trader column on the row, so a receipt whose owner could only be reached through a join
is one `scoped()` cannot constrain. The composite foreign key is what keeps the copy honest: a
receipt cannot name one order and a different order's trader.

**`raw_payment_date` beside `payment_at_normalized`**, per §10.3 and ADR-006. A trader's receipt
shows a Jalali date and the platform stores an instant; discarding the raw string would make a
later mismatch unexaminable.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    created_at_column,
    named_check,
    record_version_column,
    updated_at_column,
    uuid_primary_key,
)

# `status_catalog.yaml`'s `incoming_payment_receipt` aggregate, all nine, in its order.
RECEIPT_STATUSES: tuple[str, ...] = (
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

RECEIPT_SUBMITTED = "submitted"
RECEIPT_WAITING_FOR_STATEMENT = "waiting_for_bank_statement"
RECEIPT_CONFIRMED = "confirmed"

# What slice 2 can reach. A receipt is submitted and then waits for the centre to import the
# statement that would confirm it; every other value belongs to matching or confirmation. Kept
# beside the full set so the difference is visible rather than discovered.
SLICE_TWO_REACHABLE: tuple[str, ...] = (RECEIPT_SUBMITTED, RECEIPT_WAITING_FOR_STATEMENT)

AMOUNT_UNITS: tuple[str, ...] = ("IRR", "TOMAN")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class IncomingPaymentReceipt(Base):
    """One claim, with its evidence. §10.3."""

    __tablename__ = "incoming_payment_receipts"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    gold_sale_order_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("gold_sale_orders.id", name="fk_incoming_receipts_order"),
        nullable=False,
    )
    # See the module docstring: denormalised so `scoped()` has a column to constrain, and kept
    # honest by the composite foreign key below.
    trader_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)

    amount_irr: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entered_amount_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    entered_amount_unit: Mapped[str | None] = mapped_column(String(8), nullable=True)

    tracking_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_payment_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payment_at_normalized: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    source_bank_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # A hint, not an account number. §10.3's own word, and the distinction is deliberate.
    source_account_hint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    destination_bank_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bank_accounts.id", name="fk_incoming_receipts_destination"),
        nullable=True,
    )
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    evidence_file_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("file_objects.id", name="fk_incoming_receipts_evidence"),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(String(32), nullable=False)

    confirmed_amount_irr: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    confirmed_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_incoming_receipts_confirmed_by"),
        nullable=True,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    record_version: Mapped[int] = record_version_column()
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        named_check("amount_irr > 0", name="amount_positive"),
        # Zero is permitted, and that is not an oversight: a confirmation may find that nothing
        # arrived, which is a different fact from not having looked. A *claim* of nothing is not
        # a claim, so `amount_irr` has no such allowance.
        named_check(
            "confirmed_amount_irr IS NULL OR confirmed_amount_irr >= 0",
            name="confirmed_amount_not_negative",
        ),
        named_check(f"status IN ({_quoted(RECEIPT_STATUSES)})", name="status_value"),
        named_check(
            f"entered_amount_unit IS NULL OR entered_amount_unit IN ({_quoted(AMOUNT_UNITS)})",
            name="entered_amount_unit_value",
        ),
        named_check(
            "(confirmed_at IS NULL AND confirmed_by_admin_user_id IS NULL)"
            " OR "
            "(confirmed_at IS NOT NULL AND confirmed_by_admin_user_id IS NOT NULL)",
            name="confirmation_needs_an_actor",
        ),
        ForeignKeyConstraint(
            ["gold_sale_order_id", "trader_id"],
            ["gold_sale_orders.id", "gold_sale_orders.trader_id"],
            name="fk_incoming_receipts_order_trader",
        ),
        Index(
            "idx_incoming_receipts_order_status",
            "gold_sale_order_id",
            "status",
            "created_at",
        ),
        Index(
            "idx_incoming_receipts_tracking",
            "tracking_number",
            postgresql_where="tracking_number IS NOT NULL",
        ),
    )
