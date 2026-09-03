"""Gold moves, and only when it may. `04_Database_Schema.md` §10.8.

M10 slice 7. One table, three override columns, and one seeded permission the owner chose.

**The guard is §18 `:1236` in one sentence:** "Gold cannot be dispatched unless the approved
payment/settlement condition is satisfied or an explicitly authorized override is recorded with
reason and audit." §10.8 says it again from the schema's side: "No dispatch/settlement row may be
marked completed unless the payment guard or an audited authorized override is satisfied by the
service transaction."

**The override is recorded on the row, not only in the audit log.** §10.8's field list does not
name these three columns and §18 `:1236` is what authorises them: "recorded with reason **and**
audit" is two things, and a dispatch row that could not say whether it passed the guard or bypassed
it would make the audit log the only place the difference exists. Reading the row is how an
operator answers "was this gold released against confirmed money", and that question must not
require a log search.

**`dispatch_type` gets no UPDATE grant, and that is document 06 §12.3's second rule enforced by
absence:** "A physical dispatch cannot be converted silently into offset settlement; create a
replacement/superseding settlement record." The word is *silently*, and a column the runtime cannot
write is the strongest form of not-silently there is — a conversion has to become a new row with
the old one `superseded`, which is what the rule asks for.

**The override permission is seeded and granted to `manager`, on the owner's decision of
2026-09-03.** `20260828_0027` is the precedent exactly: that migration seeded
`payment_batch.cancel_approved` for the manager alone on the owner's 2026-08-25 decision, and its
comment explains why a grant belongs in the migration once the owner has chosen — "leaving it
ungranted would repeat DOC-CONFLICT-056 one level further in — a permission that exists and
authorises nobody."

**Not the warehouse operator, and that is the catalogue's rule rather than a preference.**
`permission_catalog.yaml`'s `dispatch_control` constraint reads `separation_of_duties: warehouse
cannot override financial verification`, and `gold_sale.dispatch` is granted to
`warehouse_operator` alone. So the two authorities are held by different roles by construction, and
`SEC-DISPATCH-001` is a property of the seed rather than of a branch somebody could delete.

**Still owed by M0**: a `permission_catalog.yaml` entry for `gold_sale.dispatch_override` approved
rather than added here, a `command_catalog.yaml` row for the dispatch command, and a catalogued
audit action — `audit_outbox_catalog.yaml` names `gold_sale.dispatched` and nothing for an
override.

Revision ID: 20260911_0042
Revises: 20260910_0041
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260911_0042"
down_revision: str | Sequence[str] | None = "20260910_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# §10.8's four, and document 06 §12.1 lists the same four in the same order.
DISPATCH_TYPES = (
    "physical_dispatch",
    "physical_receipt",
    "offset_settlement",
    "manual_settlement",
)

# `status_catalog.yaml`'s `gold_dispatch` aggregate, all six, in its order. Document 06 §12.2.
DISPATCH_STATUSES = (
    "pending",
    "dispatched",
    "delivered",
    "settled",
    "cancelled",
    "superseded",
)

# M1's weight units, shared with `gold_sale_orders`. Doc 04 §4.5.
WEIGHT_UNITS = ("GRAM", "MITHQAL")

# The lifecycle, the trader's acknowledgement, and nothing else.
#
# **Not `dispatch_type`** — document 06 §12.3's second rule, above. **Not `weight`, `weight_unit` or
# `gold_purity`**: what left the building is a fact recorded once, and a dispatch whose weight could
# be edited afterwards would let a discrepancy be tidied away rather than corrected. **Not the three
# override columns**: an override that could be added after the fact would let a dispatch made under
# the guard be relabelled as authorised, or the reverse.
GRANTED_COLUMNS = (
    "status",
    "confirmed_by_trader_user_id",
    "confirmed_at",
    "record_version",
    "updated_at",
)

# The owner's decision of 2026-09-03: the manager holds the override, and the grant is manageable
# afterwards through `updateRolePermissions` like every other grant in this system.
#
# The domain is read from `20260801_0008`'s own list rather than invented: `gold_sale.dispatch` sits
# in `gold_sale`, and an override of that command's guard belongs in the same domain.
OVERRIDE_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("gold_sale.dispatch_override", "gold_sale"),
)

OVERRIDE_GRANTS: tuple[tuple[str, str], ...] = (
    ("manager", "gold_sale.dispatch_override"),
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
        "gold_dispatches",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "gold_sale_order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("gold_sale_orders.id", name="fk_gold_dispatches_order"),
            nullable=False,
        ),
        sa.Column("dispatch_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        # NUMERIC(20, 6) and the unit beside it, exactly as `gold_sale_orders` carries them. A mass
        # is not money and cannot be an integer of rials; `test_money_and_time_guards.py` records
        # the exception per column.
        sa.Column("weight", sa.Numeric(20, 6), nullable=True),
        sa.Column("weight_unit", sa.String(16), nullable=True),
        sa.Column("gold_purity", sa.String(16), nullable=True),
        sa.Column("receiver_name", sa.String(255), nullable=True),
        sa.Column("tracking_or_delivery_note", sa.Text(), nullable=True),
        sa.Column(
            "evidence_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("file_objects.id", name="fk_gold_dispatches_evidence"),
            nullable=True,
        ),
        sa.Column(
            "created_by_admin_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", name="fk_gold_dispatches_created_by"),
            nullable=False,
        ),
        # The trader's acknowledgement. Document 06 §12.3's fourth rule: "Trader acknowledgment is
        # not required to prove that dispatch occurred" — so nullable, and the dispatch is real
        # without it.
        sa.Column(
            "confirmed_by_trader_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("trader_users.id", name="fk_gold_dispatches_confirmed_by"),
            nullable=True,
        ),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        # §18 `:1236`'s "recorded with reason and audit". Three columns, because the sentence names
        # three facts: that it happened, who authorised it, and why.
        sa.Column(
            "guard_override_by_admin_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", name="fk_gold_dispatches_override_by"),
            nullable=True,
        ),
        sa.Column("guard_override_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("guard_override_reason", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            f"dispatch_type IN ({_quoted(DISPATCH_TYPES)})", name="dispatch_type_value"
        ),
        sa.CheckConstraint(f"status IN ({_quoted(DISPATCH_STATUSES)})", name="status_value"),
        sa.CheckConstraint(
            f"weight_unit IS NULL OR weight_unit IN ({_quoted(WEIGHT_UNITS)})",
            name="weight_unit_value",
        ),
        sa.CheckConstraint("weight IS NULL OR weight > 0", name="weight_positive"),
        # An override that says it happened must say who and why, and one that did not must say
        # none of the three. The same shape slice 2's `confirmation_needs_an_actor` uses, and here
        # it is what stops a half-recorded override reading as a full one.
        sa.CheckConstraint(
            "(guard_override_at IS NULL AND guard_override_by_admin_user_id IS NULL"
            " AND guard_override_reason IS NULL)"
            " OR "
            "(guard_override_at IS NOT NULL AND guard_override_by_admin_user_id IS NOT NULL"
            " AND guard_override_reason IS NOT NULL"
            " AND length(btrim(guard_override_reason)) > 0)",
            name="override_needs_an_actor_and_a_reason",
        ),
        # A trader acknowledgement, likewise: both halves or neither.
        sa.CheckConstraint(
            "(confirmed_at IS NULL AND confirmed_by_trader_user_id IS NULL)"
            " OR "
            "(confirmed_at IS NOT NULL AND confirmed_by_trader_user_id IS NOT NULL)",
            name="acknowledgement_needs_an_actor",
        ),
    )

    op.create_index(
        "idx_gold_dispatches_order_status",
        "gold_dispatches",
        ["gold_sale_order_id", "status", "created_at"],
    )
    # Every dispatch released without the payment guard, cheaply. An override nobody can list is
    # one nobody reviews, and §18 `:1236` requires it to be auditable rather than merely recorded.
    op.create_index(
        "idx_gold_dispatches_overridden",
        "gold_dispatches",
        ["guard_override_at"],
        postgresql_where=sa.text("guard_override_at IS NOT NULL"),
    )

    bind = op.get_bind()
    columns = ", ".join(GRANTED_COLUMNS)
    for role in _runtime_roles():
        bind.execute(
            sa.text(f'GRANT UPDATE ({columns}) ON public."gold_dispatches" TO "{role}"')
        )

    for code, domain in OVERRIDE_PERMISSIONS:
        bind.execute(
            sa.text(
                "INSERT INTO permissions (code, domain) VALUES (:code, :domain) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "domain": domain},
        )
    for role, code in OVERRIDE_GRANTS:
        # Joined through the codes rather than the ids, because the ids differ per database and
        # this migration runs against every one of them.
        bind.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT r.id, p.id FROM roles r, permissions p "
                "WHERE r.code = :role AND p.code = :code "
                "ON CONFLICT DO NOTHING"
            ),
            {"role": role, "code": code},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for _role, code in OVERRIDE_GRANTS:
        # The grant first: dropping the permission while a `role_permissions` row referenced it
        # would fail on the foreign key.
        bind.execute(
            sa.text(
                "DELETE FROM role_permissions WHERE permission_id IN "
                "(SELECT id FROM permissions WHERE code = :code)"
            ),
            {"code": code},
        )
    for code, _domain in OVERRIDE_PERMISSIONS:
        bind.execute(sa.text("DELETE FROM permissions WHERE code = :code"), {"code": code})

    op.drop_index("idx_gold_dispatches_overridden", table_name="gold_dispatches")
    op.drop_index("idx_gold_dispatches_order_status", table_name="gold_dispatches")
    op.drop_table("gold_dispatches")
