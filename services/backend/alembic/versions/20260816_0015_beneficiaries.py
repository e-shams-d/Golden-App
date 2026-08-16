"""Add `beneficiaries`, the trader-owned payment destination.

`04_Database_Schema.md:491-528`. Hand-written like every revision in this tree, so
the reasons live next to the SQL rather than in a commit message.

**No unique constraint on IBAN or on name.** Document 04 states the prohibition and
gives the reason: duplicates may be legitimate or incomplete, and the service warns
rather than auto-merging. This is the one thing about this table most likely to be
"fixed" by a later migration that reads a duplicate-warning bug report and reaches
for the obvious constraint, so `tests/backend/test_beneficiary_schema.py` asserts
the absence against `IBAN_UNIQUE_IS_PERMITTED_ONLY_ON` — the allowlist M2 wrote in
`app/db/models/bank.py` before this table existed.

**`normalized_iban` is `NOT NULL` with a null-intolerant regex.** M2 recorded the
asymmetry with `bank_accounts` and predicted this form: a centre account may be
registered before its IBAN is known; a payment destination without an IBAN cannot
be paid.

**`status` gets a value CHECK and `verification_status` does not.** The
`beneficiary` aggregate is approved in `status_catalog.yaml` with exactly these
four values. No approved aggregate covers the verification outcome — document 04
names four values in a Notes cell — so enumerating them in a migration would put an
unapproved vocabulary into the database permanently, which is the one thing a
migration must never do. Raised as DOC-CONFLICT-048 and pinned in
`test_status_catalogue_drift.py`'s `DELIBERATELY_UNCONSTRAINED`.

**The trader status CHECKs are not here.** M5 owes them (DOC-CONFLICT-024's values,
plan §2.4) and the owner decision has not arrived. `docs/handoff/M5_IMPLEMENTATION_PLAN.md`
says what to do in that case in terms: the columns stay unconstrained and the slice
ships the rest. A milestone must not invent a status vocabulary to unblock itself,
least of all from a migration.

`beneficiaries` receives `GRANT UPDATE` and not `DELETE`: status changes and
`record_version` are updates, and a beneficiary is never deleted — the requests
that reference it would lose their subject, and their snapshots exist precisely so
that never matters.

Downgrade drops the table. Honest only while it is empty, on the same terms
`20260801_0012:44-46` records.

Revision ID: 20260816_0015
Revises: 20260816_0014
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_0015"
down_revision: str | Sequence[str] | None = "20260816_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# The approved `beneficiary` aggregate. Kept as SQL text here and as a tuple in
# `app/db/models/beneficiary.py`; the drift gate compares the model against the
# catalogue and `test_schema_matches_models.py` compares the model against the
# database, so all three must agree.
BENEFICIARY_STATUSES_SQL = "'active', 'inactive', 'blocked', 'superseded'"

# Iranian IBAN: `IR` then 24 digits. Duplicated as text rather than imported so the
# revision stays readable as SQL; `test_beneficiary_schema.py` asserts it equals
# `app.db.models.bank.IBAN_PATTERN`.
IBAN_PATTERN_SQL = "^IR[0-9]{24}$"

# Mutable, so the runtime needs more than the fail-closed SELECT+INSERT default
# that `infra/postgres/bootstrap/020-runtime-roles.sql:95-96` grants.
UPDATE_ONLY_TABLES: tuple[str, ...] = ("beneficiaries",)


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
        "beneficiaries",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("trader_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=True),
        sa.Column("iban", sa.String(length=34), nullable=False),
        sa.Column("normalized_iban", sa.String(length=26), nullable=False),
        sa.Column("bank_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("national_id", sa.String(length=16), nullable=True),
        sa.Column("phone_number", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("notes_internal", sa.Text(), nullable=True),
        sa.Column("verification_status", sa.String(length=24), nullable=False),
        sa.Column(
            "verification_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("record_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
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
            "length(btrim(full_name)) > 0",
            name=op.f("ck_beneficiaries_full_name_not_blank"),
        ),
        sa.CheckConstraint(
            f"normalized_iban ~ '{IBAN_PATTERN_SQL}'",
            name=op.f("ck_beneficiaries_normalized_iban_shape"),
        ),
        sa.CheckConstraint(
            f"status IN ({BENEFICIARY_STATUSES_SQL})",
            name=op.f("ck_beneficiaries_status_value"),
        ),
        sa.ForeignKeyConstraint(
            ["bank_profile_id"],
            ["bank_profiles.id"],
            name=op.f("fk_beneficiaries_bank_profile_id_bank_profiles"),
        ),
        sa.ForeignKeyConstraint(
            ["trader_id"],
            ["traders.id"],
            name=op.f("fk_beneficiaries_trader_id_traders"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_beneficiaries")),
    )
    # Both names come from doc 04:521-525. Trader-scoped, including the IBAN one:
    # a duplicate lookup that could see another trader's row is one a bug could
    # return.
    op.create_index("idx_beneficiaries_trader_status", "beneficiaries", ["trader_id", "status"])
    op.create_index(
        "idx_beneficiaries_normalized_iban", "beneficiaries", ["trader_id", "normalized_iban"]
    )

    bind = op.get_bind()
    for role in _runtime_roles():
        for table in UPDATE_ONLY_TABLES:
            bind.execute(sa.text(f'GRANT UPDATE ON public."{table}" TO "{role}"'))


def downgrade() -> None:
    op.drop_index("idx_beneficiaries_normalized_iban", table_name="beneficiaries")
    op.drop_index("idx_beneficiaries_trader_status", table_name="beneficiaries")
    op.drop_table("beneficiaries")
