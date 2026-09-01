"""The gold sale order and its immutable pricing versions. `04_Database_Schema.md` §10.1-10.2.

M10 slice 1, and the first table in this project that is about money coming **in**.

**The split is M5's, deliberately reused.** `gold_sale_orders` is the mutable aggregate and
`gold_sale_pricing_versions` is an immutable snapshot with a monotonic `version_number`, a
`content_hash`, and a pointer on the aggregate updated in the same transaction — exactly the shape
`payment_requests` and `payment_request_revisions` have carried since M5. §10.2 at `:731` states
the transactional half: "Updating price creates a new row and updates
`gold_sale_orders.current_pricing_version_id` transactionally."

A pricing version therefore has **no `record_version` and no `updated_at`**, for the reason M5's
revisions have neither: both are machinery for changing a row that nothing may change. Optimistic
concurrency belongs to the order, which does move.

**`gold_weight` is the first non-integer quantity this system stores**, and the plan's G-1 decided
its spelling before any code: `NUMERIC` in the column, `Decimal` in Python, and a **string** in
every hash input. Document 05 §21.1 arrived at the same answer independently — "gold weight uses a
string decimal and explicit unit", with `"125.500000"` as its example — which is the strongest kind
of agreement, two documents reaching one spelling without citing each other.

The reason is `app/core/hashing.py`, which refuses a float outright: "0.1 + 0.2 does not equal 0.3,
so two amounts a human calls equal produce different digests". Every amount M1 through M9 stores
is `BigInteger` rials and never met this; a mass cannot be.

**Eighteen statuses, and they are the catalogue's.** `status_catalog.yaml`'s `gold_sale_order`
aggregate carries all eighteen canonical with no aliases and no unresolved entries — checked
against §10.1's list value by value before this CHECK was written, because
`test_status_catalogue_drift.py` holds every enforced CHECK to its aggregate **exactly**.

**Grants: `status`, the pricing pointer, the two amounts, and the cancellation and closure
columns.** Not `order_number`, not `trader_id`, not the gold description — those are what the order
*is*, and an order whose weight or owner could be rewritten after submission would make every
pricing version below it a snapshot of something that no longer exists.

Revision ID: 20260904_0035
Revises: 20260903_0034
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260904_0035"
down_revision: str | Sequence[str] | None = "20260903_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `status_catalog.yaml`'s `gold_sale_order` aggregate, which is §10.1's list verbatim. Eighteen,
# all canonical, no aliases — the drift gate compares this set to the catalogue exactly.
ORDER_STATUSES = (
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

# **Document 04 §4.5 names these two**: "The unit must be explicit (`GRAM`, `MITHQAL`, or an
# approved code)." The first draft here read `("GRAM", "KILOGRAM")` — an invented unit, and worse,
# it omitted **mithqal**, which is the traditional Iranian measure gold is actually quoted in. Found
# by reading §4.5 while chasing the NUMERIC exemption gate, not by any test.
#
# "or an approved code" is left unimplemented rather than guessed: a third unit is a governance
# addition and the CHECK is what makes that deliberate.
WEIGHT_UNITS = ("GRAM", "MITHQAL")

# §10.2's `pricing_method`. Not catalogued either. `manual` is the only Phase 1A value — §18's goal
# says "without automatic pricing or bank APIs" in as many words — and the column exists so that a
# later automatic method is a value rather than a schema change.
PRICING_METHODS = ("manual",)

# What a command may write on the order after it exists. Everything absent is what the order *is*.
GRANTED_COLUMNS = (
    "status",
    "current_pricing_version_id",
    "expected_amount_irr",
    "final_amount_irr",
    "cancelled_at",
    "cancelled_reason",
    "closed_at",
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
        "gold_sale_orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "trader_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("traders.id", name="fk_gold_sale_orders_trader"),
            nullable=False,
        ),
        sa.Column("order_number", sa.String(64), nullable=False),
        sa.Column("status", sa.String(48), nullable=False),
        sa.Column("gold_type", sa.String(64), nullable=False),
        # NUMERIC, never a float. See the module docstring and the plan's G-1.
        sa.Column("gold_weight", sa.Numeric(20, 6), nullable=False),
        sa.Column("weight_unit", sa.String(16), nullable=False),
        sa.Column("gold_purity", sa.String(16), nullable=False),
        # Set when the first pricing version is created, in that version's own transaction. The
        # composite foreign key below is what stops it pointing at another order's pricing.
        sa.Column("current_pricing_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expected_amount_irr", sa.BigInteger(), nullable=True),
        sa.Column("final_amount_irr", sa.BigInteger(), nullable=True),
        sa.Column("created_by_actor_type", sa.String(24), nullable=False),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_reason", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("order_number", name="uq_gold_sale_order_number"),
        sa.CheckConstraint(f"status IN ({_quoted(ORDER_STATUSES)})", name="status_value"),
        sa.CheckConstraint(
            f"weight_unit IN ({_quoted(WEIGHT_UNITS)})", name="weight_unit_value"
        ),
        # §10.1's two CHECKs verbatim. Both nullable-tolerant: an order has no amount until it is
        # priced, and forcing one would make a draft impossible to save.
        sa.CheckConstraint(
            "expected_amount_irr IS NULL OR expected_amount_irr > 0",
            name="expected_amount_positive",
        ),
        sa.CheckConstraint(
            "final_amount_irr IS NULL OR final_amount_irr > 0", name="final_amount_positive"
        ),
        # Not in §10.1, and it closes the same shape M9 closed twice: a row that says it was
        # cancelled must say why, and a row that was not cancelled must not carry a reason.
        sa.CheckConstraint(
            "(cancelled_at IS NULL AND cancelled_reason IS NULL)"
            " OR "
            "(cancelled_at IS NOT NULL AND cancelled_reason IS NOT NULL)",
            name="cancellation_needs_a_reason",
        ),
        sa.CheckConstraint("gold_weight > 0", name="gold_weight_positive"),
        # A unique on `(id, ...)` so the pricing table can carry a composite foreign key back.
        sa.UniqueConstraint("id", "trader_id", name="uq_gold_sale_order_identity"),
    )

    op.create_index(
        "idx_gold_sale_orders_trader_status",
        "gold_sale_orders",
        ["trader_id", "status", "created_at"],
    )

    op.create_table(
        "gold_sale_pricing_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "gold_sale_order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("gold_sale_orders.id", name="fk_pricing_versions_order"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("pricing_method", sa.String(32), nullable=False),
        # The weight as priced. Snapshotted rather than read through the order, for M5's reason:
        # a version records what was true when the price was set, and the order is mutable.
        sa.Column("gold_weight", sa.Numeric(20, 6), nullable=False),
        sa.Column("weight_unit", sa.String(16), nullable=False),
        sa.Column("gold_purity", sa.String(16), nullable=False),
        sa.Column("unit_price_irr", sa.BigInteger(), nullable=False),
        sa.Column("expected_amount_irr", sa.BigInteger(), nullable=False),
        # What the accountant typed, beside what it became. M5's `entered_amount_*` pair and its
        # argument: `500 TOMAN` and `5000 IRR` are the same money and different intents, and a
        # dispute six months later is about the second.
        sa.Column("entered_amount_value", sa.BigInteger(), nullable=True),
        sa.Column("entered_amount_unit", sa.String(8), nullable=True),
        sa.Column("pricing_note", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column(
            "created_by_admin_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", name="fk_pricing_versions_created_by"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "gold_sale_order_id", "version_number", name="uq_pricing_version_per_order"
        ),
        sa.CheckConstraint("expected_amount_irr > 0", name="expected_amount_positive"),
        sa.CheckConstraint("unit_price_irr > 0", name="unit_price_positive"),
        sa.CheckConstraint("version_number > 0", name="version_number_positive"),
        sa.CheckConstraint("gold_weight > 0", name="gold_weight_positive"),
        sa.CheckConstraint(
            f"pricing_method IN ({_quoted(PRICING_METHODS)})", name="pricing_method_value"
        ),
        sa.CheckConstraint(
            f"weight_unit IN ({_quoted(WEIGHT_UNITS)})", name="weight_unit_value"
        ),
        # A pricing version that changed nothing is refused by the database, which is M5's
        # `UNIQUE(payment_request_id, content_hash)` one aggregate along and for the same reason:
        # re-pricing at the same figures has not re-priced anything, and a second identical row
        # would reach a reviewer looking like new work.
        sa.UniqueConstraint(
            "gold_sale_order_id", "content_hash", name="uq_pricing_content_per_order"
        ),
        # **The composite foreign key below has nothing to reference without this.** PostgreSQL
        # requires a unique constraint on exactly the referenced pair, and the primary key on `id`
        # alone does not satisfy `(id, gold_sale_order_id)`. M5's `uq_request_revision_pair` is the
        # same constraint for the same reason; leaving it out failed the migration outright, which
        # is the honest failure — the alternative is a single-column key that lets one order point
        # at another's pricing.
        sa.UniqueConstraint(
            "id", "gold_sale_order_id", name="uq_pricing_version_pair"
        ),
    )

    # **Deferrable, and it must be.** The order and its first pricing version reference each other:
    # the version names the order, and the order's `current_pricing_version_id` names the version.
    # Whichever is written first would violate an immediately-checked constraint. `payment_requests`
    # carries the identical arrangement (`04_Database_Schema.md:1536-1547`) for the identical
    # reason, and a single-column key would let one order point at another's pricing.
    op.create_foreign_key(
        "fk_gold_sale_orders_current_pricing",
        "gold_sale_orders",
        "gold_sale_pricing_versions",
        ["current_pricing_version_id", "id"],
        ["id", "gold_sale_order_id"],
        deferrable=True,
        initially="DEFERRED",
    )

    bind = op.get_bind()
    columns = ", ".join(GRANTED_COLUMNS)
    for role in _runtime_roles():
        bind.execute(
            sa.text(f'GRANT UPDATE ({columns}) ON public."gold_sale_orders" TO "{role}"')
        )
        # `superseded_at` alone on the pricing table. A version is otherwise immutable; being
        # superseded is the one thing that may happen to it, exactly as a publication may only
        # become `superseded` (`20260903_0034`).
        bind.execute(
            sa.text(
                'GRANT UPDATE (superseded_at) ON public."gold_sale_pricing_versions" '
                f'TO "{role}"'
            )
        )


def downgrade() -> None:
    op.drop_constraint(
        "fk_gold_sale_orders_current_pricing", "gold_sale_orders", type_="foreignkey"
    )
    op.drop_table("gold_sale_pricing_versions")
    op.drop_index("idx_gold_sale_orders_trader_status", table_name="gold_sale_orders")
    op.drop_table("gold_sale_orders")
