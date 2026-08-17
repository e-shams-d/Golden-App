"""Add the request aggregate and its immutable revisions.

`04_Database_Schema.md:822-906`, with the composite integrity at `:1536-1547`.

**The two tables reference each other, so the order matters and the composite key
arrives last.** `payment_requests` is created without its `current_revision_id`
foreign key; `payment_request_revisions` is created with its own key back to the
request; then the composite key is added by `ALTER`, which is how document 04 writes
it too. Doing it any other way means one `CREATE TABLE` naming a table that does not
exist yet.

**`DEFERRABLE INITIALLY DEFERRED` is not a convenience.** A request and its first
revision are inserted in one transaction and each points at the other. Whichever row
went first would violate an immediately-checked constraint, so a non-deferrable key
would make the ordinary path impossible — the failure `bank_profiles` met in M2 and
solved the same way.

**`payment_request_revisions` receives no UPDATE grant at all.** Not column-level,
not on one column: none. The bootstrap default is `SELECT, INSERT`
(`infra/postgres/bootstrap/020-runtime-roles.sql:95-96`), so immutability here is the
absence of a grant rather than the presence of a rule, and
`tests/integration/test_request_revision_immutability.py` proves it through the
runtime role with one case per column.

This is stricter than `bank_profile_versions`, which has a column-level UPDATE on
`status` because a version is activated. A revision has no status. The request does.

**`superseded_at` exists and nothing may write it.** Document 04 defines the column
so it is created; M5 identifies the current revision through
`payment_requests.current_revision_id` instead. A milestone that needs to set it must
widen the grant deliberately, which is a reviewable act rather than an accident.

`UNIQUE(payment_request_id, content_hash)` is document 04's, at `:901`, and it means
a correction that changes nothing is refused by the database. The M5 plan originally
claimed identical content must be permitted; slice 3 corrected the plan after reading
the constraints under the table it had cited only by line range.

Downgrade drops both tables, the composite key first. Honest only while they are
empty, on the terms `20260801_0012:44-46` records.

Revision ID: 20260817_0016
Revises: 20260816_0015
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260817_0016"
down_revision: str | Sequence[str] | None = "20260816_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# `status_catalog.yaml`'s `payment_request` aggregate, all seventeen. Kept as SQL text
# here and as a tuple in `app/db/models/payment_request.py`; the drift gate compares
# the model against the catalogue and `test_schema_matches_models.py` compares the
# model against the database.
STATUSES_SQL = (
    "'draft', 'submitted_to_center', 'under_accountant_review', "
    "'needs_trader_correction', 'eligible_for_batching', 'batched', "
    "'sent_to_bank', 'partially_paid', 'paid', 'failed', 'retry_required', "
    "'result_ready_for_trader', 'result_published', 'trader_acknowledged', "
    "'trader_disputed', 'cancelled', 'closed'"
)

QUEUE_STATUSES_SQL = (
    "'submitted_to_center','under_accountant_review','needs_trader_correction',"
    "'eligible_for_batching','retry_required','trader_disputed'"
)

IBAN_PATTERN_SQL = "^IR[0-9]{24}$"

# `payment_requests` only. Its status, review columns and `record_version` move.
# `payment_request_revisions` is deliberately absent — see the module docstring.
UPDATE_ONLY_TABLES: tuple[str, ...] = ("payment_requests",)


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
            f"Migration {revision} grants on mutable tables and these roles are "
            f"not set: {', '.join(missing)}."
        )
    return tuple(str(value) for value in configured.values())


def upgrade() -> None:
    op.create_table(
        "payment_requests",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("trader_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("beneficiary_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_number", sa.String(length=64), nullable=False),
        # No foreign key yet: the table it points at does not exist.
        sa.Column("current_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=48), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_admin_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_reason", sa.Text(), nullable=True),
        sa.Column("result_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trader_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trader_disputed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trader_result_note", sa.Text(), nullable=True),
        sa.Column("record_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_by_trader_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_admin_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"status IN ({STATUSES_SQL})",
            name=op.f("ck_payment_requests_status_value"),
        ),
        sa.ForeignKeyConstraint(
            ["beneficiary_id"],
            ["beneficiaries.id"],
            name=op.f("fk_payment_requests_beneficiary_id_beneficiaries"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_admin_user_id"],
            ["admin_users.id"],
            name=op.f("fk_payment_requests_created_by_admin_user_id_admin_users"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_trader_user_id"],
            ["trader_users.id"],
            name=op.f("fk_payment_requests_created_by_trader_user_id_trader_users"),
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_admin_user_id"],
            ["admin_users.id"],
            name=op.f("fk_payment_requests_reviewed_by_admin_user_id_admin_users"),
        ),
        sa.ForeignKeyConstraint(
            ["trader_id"],
            ["traders.id"],
            name=op.f("fk_payment_requests_trader_id_traders"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_requests")),
        sa.UniqueConstraint("request_number", name=op.f("uq_payment_requests_request_number")),
    )

    op.create_table(
        "payment_request_revisions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("payment_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("beneficiary_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("beneficiary_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("beneficiary_iban_snapshot", sa.String(length=26), nullable=False),
        sa.Column("beneficiary_national_id_snapshot", sa.String(length=16), nullable=True),
        sa.Column("amount_irr", sa.BigInteger(), nullable=False),
        sa.Column("entered_amount_value", sa.BigInteger(), nullable=True),
        sa.Column("entered_amount_unit", sa.String(length=8), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_attachment_file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revision_reason", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by_actor_type", sa.String(length=24), nullable=False),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "amount_irr > 0", name=op.f("ck_payment_request_revisions_amount_irr_positive")
        ),
        sa.CheckConstraint(
            f"beneficiary_iban_snapshot ~ '{IBAN_PATTERN_SQL}'",
            name=op.f("ck_payment_request_revisions_iban_snapshot_shape"),
        ),
        sa.CheckConstraint(
            "revision_number > 0",
            name=op.f("ck_payment_request_revisions_revision_number_positive"),
        ),
        sa.CheckConstraint(
            "(entered_amount_value IS NULL) = (entered_amount_unit IS NULL)",
            name=op.f("ck_payment_request_revisions_entered_amount_pair_complete"),
        ),
        sa.CheckConstraint(
            "entered_amount_unit IS NULL OR entered_amount_unit IN ('IRR', 'TOMAN')",
            name=op.f("ck_payment_request_revisions_entered_amount_unit_value"),
        ),
        sa.ForeignKeyConstraint(
            ["beneficiary_id"],
            ["beneficiaries.id"],
            name=op.f("fk_payment_request_revisions_beneficiary_id_beneficiaries"),
        ),
        sa.ForeignKeyConstraint(
            ["payment_request_id"],
            ["payment_requests.id"],
            name="fk_request_revisions_request",
        ),
        sa.ForeignKeyConstraint(
            ["source_attachment_file_id"],
            ["file_objects.id"],
            name="fk_request_revisions_attachment",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_request_revisions")),
        sa.UniqueConstraint(
            "payment_request_id",
            "revision_number",
            name=op.f("uq_revision_number_per_request"),
        ),
        sa.UniqueConstraint(
            "payment_request_id", "content_hash", name=op.f("uq_revision_content_per_request")
        ),
        # The pair the composite foreign key below needs. Document 04 names it.
        sa.UniqueConstraint("id", "payment_request_id", name=op.f("uq_request_revision_pair")),
    )

    # Now both tables exist, so the pointer can be constrained. `(current_revision_id,
    # id)` against `(id, payment_request_id)`: the second column of each side is what
    # ties the revision to *this* request.
    op.create_foreign_key(
        op.f("fk_request_current_revision"),
        "payment_requests",
        "payment_request_revisions",
        ["current_revision_id", "id"],
        ["id", "payment_request_id"],
        deferrable=True,
        initially="DEFERRED",
    )

    op.create_index(
        "idx_payment_requests_trader_status",
        "payment_requests",
        ["trader_id", "status", "created_at"],
    )
    op.create_index(
        "idx_payment_requests_queue",
        "payment_requests",
        ["status", "submitted_at"],
        postgresql_where=sa.text(f"status IN ({QUEUE_STATUSES_SQL})"),
    )

    bind = op.get_bind()
    for role in _runtime_roles():
        for table in UPDATE_ONLY_TABLES:
            bind.execute(sa.text(f'GRANT UPDATE ON public."{table}" TO "{role}"'))


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_request_current_revision"), "payment_requests", type_="foreignkey"
    )
    op.drop_index("idx_payment_requests_queue", table_name="payment_requests")
    op.drop_index("idx_payment_requests_trader_status", table_name="payment_requests")
    op.drop_table("payment_request_revisions")
    op.drop_table("payment_requests")
