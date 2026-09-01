"""The gold sale order and its immutable pricing versions. `04_Database_Schema.md` §10.1-10.2.

M10 slice 1. Two tables in one module because neither is meaningful alone: an order without a
pricing version has no amount, and a pricing version without an order has no subject — the same
sentence `payment_request.py` opens with, and the same split.

**The split is the milestone's first decision.** `gold_sale_orders` is mutable and carries no
price; every figure a trader is asked to pay lives on `gold_sale_pricing_versions`, which nothing
may update. §10.2 at `:731`: "Updating price creates a new row and updates
`gold_sale_orders.current_pricing_version_id` transactionally."

So a pricing version has **no `record_version` and no `updated_at`**, deliberately. Both would be
machinery for changing a row that nothing may change. `superseded_at` is the single exception and
the migration grants that column alone.

**`current_pricing_version_id` is a composite foreign key, and it must be.** A single-column key
would let order A point at order B's pricing — the pointer would be valid, the row would look
correct, and the trader would be quoted somebody else's price. `payment_requests` proved the
pattern in M5 and `bank_profiles` in M2. Deferrable, because the order and its first version
reference each other and whichever is written first would violate an immediately-checked
constraint.

**`gold_weight` is `Numeric`, never a float.** The plan's G-1, and document 05 §21.1 reached the
same spelling independently: "gold weight uses a string decimal and explicit unit". A float here
would reach `app/core/hashing.py`, which refuses one outright because two masses a human calls
equal would otherwise produce different digests.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
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

# `status_catalog.yaml`'s `gold_sale_order` aggregate, which is §10.1's list verbatim — eighteen
# canonical states, no aliases, nothing unresolved. `tests/backend/test_status_catalogue_drift.py`
# compares this set against the catalogue, so a value added here that the catalogue does not carry
# fails rather than ships.
ORDER_STATUSES: tuple[str, ...] = (
    "draft",
    "submitted",
    "under_center_review",
    "priced",
    "waiting_for_incoming_payment",
    "payment_evidence_submitted",
    "waiting_for_bank_statement",
    "needs_review",
    "incoming_payment_partially_confirmed",
    "incoming_payment_confirmed",
    "manager_approval_required",
    "ready_for_dispatch",
    "dispatched",
    "received_by_trader",
    "settled_or_offset",
    "closed",
    "rejected",
    "cancelled",
)

ORDER_DRAFT = "draft"
ORDER_SUBMITTED = "submitted"
ORDER_UNDER_REVIEW = "under_center_review"
ORDER_PRICED = "priced"
ORDER_CANCELLED = "cancelled"

# What slice 1 can actually reach. The rest of `ORDER_STATUSES` exists because the catalogue and
# §10.1 define eighteen and the CHECK must admit what later slices write; the commands here move an
# order through these five and refuse the others. Kept beside the full set so the difference is
# visible rather than discovered — M5's `M5_REACHABLE_STATUSES` established the habit.
SLICE_ONE_REACHABLE: tuple[str, ...] = (
    ORDER_DRAFT,
    ORDER_SUBMITTED,
    ORDER_UNDER_REVIEW,
    ORDER_PRICED,
    ORDER_CANCELLED,
)

# **Document 04 §4.5**: "The unit must be explicit (`GRAM`, `MITHQAL`, or an approved code)."
# `MITHQAL` is the traditional Iranian measure gold is quoted in; the first draft of this list
# invented `KILOGRAM` and left it out. See the migration for how that was found.
WEIGHT_UNITS: tuple[str, ...] = ("GRAM", "MITHQAL")

# §18's goal excludes automatic pricing in as many words, so `manual` is the only Phase 1A value.
# The column exists so that a later method is a value rather than a schema change.
PRICING_METHODS: tuple[str, ...] = ("manual",)

# M5's `AMOUNT_UNITS`, reused rather than redefined: what an accountant typed is the same question
# here as it was for a payment request.
AMOUNT_UNITS: tuple[str, ...] = ("IRR", "TOMAN")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class GoldSaleOrder(Base):
    """The mutable order aggregate. §10.1."""

    __tablename__ = "gold_sale_orders"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    trader_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("traders.id", name="fk_gold_sale_orders_trader"),
        nullable=False,
    )
    # `unique=True` is **not** set here: the named `UniqueConstraint` below carries it, and
    # declaring both makes autogenerate see a second, unnamed constraint the migration never
    # created. The schema-match gate caught exactly that.
    order_number: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(48), nullable=False)

    gold_type: Mapped[str] = mapped_column(String(64), nullable=False)
    gold_weight: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    weight_unit: Mapped[str] = mapped_column(String(16), nullable=False)
    gold_purity: Mapped[str] = mapped_column(String(16), nullable=False)

    current_pricing_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True
    )

    expected_amount_irr: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    final_amount_irr: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_by_actor_type: Mapped[str] = mapped_column(String(24), nullable=False)
    created_by_actor_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    record_version: Mapped[int] = record_version_column()
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        named_check(f"status IN ({_quoted(ORDER_STATUSES)})", name="status_value"),
        named_check(f"weight_unit IN ({_quoted(WEIGHT_UNITS)})", name="weight_unit_value"),
        named_check(
            "expected_amount_irr IS NULL OR expected_amount_irr > 0",
            name="expected_amount_positive",
        ),
        named_check(
            "final_amount_irr IS NULL OR final_amount_irr > 0", name="final_amount_positive"
        ),
        named_check(
            "(cancelled_at IS NULL AND cancelled_reason IS NULL)"
            " OR "
            "(cancelled_at IS NOT NULL AND cancelled_reason IS NOT NULL)",
            name="cancellation_needs_a_reason",
        ),
        named_check("gold_weight > 0", name="gold_weight_positive"),
        UniqueConstraint("order_number", name="uq_gold_sale_order_number"),
        UniqueConstraint("id", "trader_id", name="uq_gold_sale_order_identity"),
        # See the module docstring. Deferrable because the two tables reference each other.
        ForeignKeyConstraint(
            ["current_pricing_version_id", "id"],
            ["gold_sale_pricing_versions.id", "gold_sale_pricing_versions.gold_sale_order_id"],
            name="fk_gold_sale_orders_current_pricing",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("idx_gold_sale_orders_trader_status", "trader_id", "status", "created_at"),
    )


class GoldSalePricingVersion(Base):
    """One immutable price snapshot. §10.2.

    `UNIQUE(gold_sale_order_id, content_hash)` means re-pricing at the same figures is refused by
    the database — M5's rule for revisions, and the same argument: an accountant who re-prices
    without changing anything has not re-priced, and a second identical row would reach a reviewer
    looking like new work.
    """

    __tablename__ = "gold_sale_pricing_versions"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    gold_sale_order_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("gold_sale_orders.id", name="fk_pricing_versions_order"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    pricing_method: Mapped[str] = mapped_column(String(32), nullable=False)

    gold_weight: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    weight_unit: Mapped[str] = mapped_column(String(16), nullable=False)
    gold_purity: Mapped[str] = mapped_column(String(16), nullable=False)

    unit_price_irr: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expected_amount_irr: Mapped[int] = mapped_column(BigInteger, nullable=False)

    entered_amount_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    entered_amount_unit: Mapped[str | None] = mapped_column(String(8), nullable=True)
    pricing_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)

    created_by_admin_user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_pricing_versions_created_by"),
        nullable=False,
    )
    created_at: Mapped[datetime] = created_at_column()
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        named_check("expected_amount_irr > 0", name="expected_amount_positive"),
        named_check("unit_price_irr > 0", name="unit_price_positive"),
        named_check("version_number > 0", name="version_number_positive"),
        named_check("gold_weight > 0", name="gold_weight_positive"),
        named_check(
            f"pricing_method IN ({_quoted(PRICING_METHODS)})", name="pricing_method_value"
        ),
        named_check(f"weight_unit IN ({_quoted(WEIGHT_UNITS)})", name="weight_unit_value"),
        UniqueConstraint(
            "gold_sale_order_id", "version_number", name="uq_pricing_version_per_order"
        ),
        UniqueConstraint(
            "gold_sale_order_id", "content_hash", name="uq_pricing_content_per_order"
        ),
        # What the order's composite foreign key references. See the migration.
        UniqueConstraint("id", "gold_sale_order_id", name="uq_pricing_version_pair"),
    )
