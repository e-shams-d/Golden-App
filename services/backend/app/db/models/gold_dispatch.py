"""Gold leaving, or a settlement that moves none. `04_Database_Schema.md` §10.8.

M10 slice 7. **Four types and two of them move no metal**, which is the distinction
`SVC-SETTLEMENT-001` exists for: an implementation that treated them alike would dispatch gold for
an offset.

**`dispatch_type` has no UPDATE grant.** Document 06 §12.3: "A physical dispatch cannot be
converted silently into offset settlement; create a replacement/superseding settlement record." The
operative word is *silently*, and a column the runtime cannot write is the strongest form of
not-silently available — a conversion has to become a new row with the old one `superseded`.

**The three override columns are on the row on purpose.** §18 `:1236` requires an override to be
"recorded with reason and audit", which is two places rather than one: reading a dispatch is how an
operator answers "was this gold released against confirmed money", and that question must not
require searching a log.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
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

# §10.8's four, and document 06 §12.1's four, in the same order.
DISPATCH_TYPES: tuple[str, ...] = (
    "physical_dispatch",
    "physical_receipt",
    "offset_settlement",
    "manual_settlement",
)

TYPE_PHYSICAL_DISPATCH = "physical_dispatch"
TYPE_PHYSICAL_RECEIPT = "physical_receipt"
TYPE_OFFSET_SETTLEMENT = "offset_settlement"
TYPE_MANUAL_SETTLEMENT = "manual_settlement"

# **The two that move metal, and the two that do not.** Named rather than inferred, because
# `SVC-SETTLEMENT-001` is precisely that an implementation must not treat them alike — and a
# derived split ("anything starting with physical_") would silently reclassify a fifth type
# somebody adds later.
PHYSICAL_TYPES: tuple[str, ...] = (TYPE_PHYSICAL_DISPATCH, TYPE_PHYSICAL_RECEIPT)
SETTLEMENT_TYPES: tuple[str, ...] = (TYPE_OFFSET_SETTLEMENT, TYPE_MANUAL_SETTLEMENT)

# `status_catalog.yaml`'s `gold_dispatch` aggregate, all six, in its order. Document 06 §12.2.
DISPATCH_STATUSES: tuple[str, ...] = (
    "pending",
    "dispatched",
    "delivered",
    "settled",
    "cancelled",
    "superseded",
)

DISPATCH_PENDING = "pending"
DISPATCH_DISPATCHED = "dispatched"
DISPATCH_DELIVERED = "delivered"
DISPATCH_SETTLED = "settled"
DISPATCH_CANCELLED = "cancelled"
DISPATCH_SUPERSEDED = "superseded"

# Where a physical movement has really happened. Document 06 §12.3's third rule turns on this:
# "Cancellation after real physical movement is not normal cancellation; use
# correction/reconciliation and retain evidence."
MOVED_STATUSES: tuple[str, ...] = (DISPATCH_DISPATCHED, DISPATCH_DELIVERED)

WEIGHT_UNITS: tuple[str, ...] = ("GRAM", "MITHQAL")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class GoldDispatch(Base):
    """One dispatch or settlement against one order. §10.8."""

    __tablename__ = "gold_dispatches"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    gold_sale_order_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("gold_sale_orders.id", name="fk_gold_dispatches_order"),
        nullable=False,
    )

    dispatch_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    # Nullable, because a settlement that moves no metal has no weight to record. A NOT NULL column
    # would force an offset to invent one, which is the placeholder
    # `FINANCIAL_INTEGRITY_BASELINE.md` forbids.
    weight: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    weight_unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    gold_purity: Mapped[str | None] = mapped_column(String(16), nullable=True)

    receiver_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tracking_or_delivery_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_file_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("file_objects.id", name="fk_gold_dispatches_evidence"),
        nullable=True,
    )

    created_by_admin_user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_gold_dispatches_created_by"),
        nullable=False,
    )
    # Document 06 §12.3: "Trader acknowledgment is not required to prove that dispatch occurred."
    # So nullable, and the dispatch is real without it.
    confirmed_by_trader_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("trader_users.id", name="fk_gold_dispatches_confirmed_by"),
        nullable=True,
    )

    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # §18 `:1236`'s three facts: that an override happened, who authorised it, and why.
    guard_override_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_gold_dispatches_override_by"),
        nullable=True,
    )
    guard_override_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    guard_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    record_version: Mapped[int] = record_version_column()
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        named_check(f"dispatch_type IN ({_quoted(DISPATCH_TYPES)})", name="dispatch_type_value"),
        named_check(f"status IN ({_quoted(DISPATCH_STATUSES)})", name="status_value"),
        named_check(
            f"weight_unit IS NULL OR weight_unit IN ({_quoted(WEIGHT_UNITS)})",
            name="weight_unit_value",
        ),
        named_check("weight IS NULL OR weight > 0", name="weight_positive"),
        # All three or none, and the reason must not be blank. A half-recorded override reads as a
        # full one, and §18 `:1236` asks for a reason rather than for a field that could hold one.
        named_check(
            "(guard_override_at IS NULL AND guard_override_by_admin_user_id IS NULL"
            " AND guard_override_reason IS NULL)"
            " OR "
            "(guard_override_at IS NOT NULL AND guard_override_by_admin_user_id IS NOT NULL"
            " AND guard_override_reason IS NOT NULL"
            " AND length(btrim(guard_override_reason)) > 0)",
            name="override_needs_an_actor_and_a_reason",
        ),
        named_check(
            "(confirmed_at IS NULL AND confirmed_by_trader_user_id IS NULL)"
            " OR "
            "(confirmed_at IS NOT NULL AND confirmed_by_trader_user_id IS NOT NULL)",
            name="acknowledgement_needs_an_actor",
        ),
        Index(
            "idx_gold_dispatches_order_status",
            "gold_sale_order_id",
            "status",
            "created_at",
        ),
        # Every dispatch released without the payment guard, cheaply. An override nobody can list
        # is one nobody reviews, and §18 `:1236` asks for auditable rather than merely recorded.
        # The predicate is spelled exactly as `20260911_0042` spells it, because
        # `test_schema_matches_models.py` compares the two.
        Index(
            "idx_gold_dispatches_overridden",
            "guard_override_at",
            postgresql_where=text("guard_override_at IS NOT NULL"),
        ),
    )


__all__ = [
    "DISPATCH_CANCELLED",
    "DISPATCH_DELIVERED",
    "DISPATCH_DISPATCHED",
    "DISPATCH_PENDING",
    "DISPATCH_SETTLED",
    "DISPATCH_STATUSES",
    "DISPATCH_SUPERSEDED",
    "DISPATCH_TYPES",
    "MOVED_STATUSES",
    "PHYSICAL_TYPES",
    "SETTLEMENT_TYPES",
    "TYPE_MANUAL_SETTLEMENT",
    "TYPE_OFFSET_SETTLEMENT",
    "TYPE_PHYSICAL_DISPATCH",
    "TYPE_PHYSICAL_RECEIPT",
    "WEIGHT_UNITS",
    "GoldDispatch",
]
