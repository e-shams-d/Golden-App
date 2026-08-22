"""The bank file's record. `04_Database_Schema.md` §11.8.

M7 slice 2. Nineteen columns, four of §11.8's own SQL statements, and **no grants at all** — the
last of which is the part worth reading.

**A preview cannot become a final export, and the enforcement is an absence.**
`FINANCIAL_INTEGRITY_BASELINE.md` §1: "Preview output cannot be promoted by mutating it into a
final artifact." A rule in a command would be a rule somebody can forget, refactor around, or
route past. `infra/postgres/bootstrap/020-runtime-roles.sql:95-96` gives new tables
`SELECT, INSERT` and nothing else, so as this migration leaves it the runtime role cannot write
`export_type` at all. Promotion is not refused; it is unavailable.

Slices 3 and 4 will need `status`, `downloaded_at`, `sent_to_bank_marked_at` and
`sent_to_bank_marked_by_admin_user_id`, and will grant those columns and no others — the same
column-level discipline `20260821_0019` used for the allocation's release pair, and for the same
reason: a table-level grant would also permit rewriting `export_type`, `batch_approval_id`,
`content_hash` and `file_sha256_hash`, which is to say rewriting *which file this is* and *what it
claims to contain*.

`tests/integration/test_export_table_privileges.py` asserts that against a live database rather
than trusting this paragraph, because a bootstrap file is something somebody can edit.

**The composite key §11.8 names is created here and its target already exists.** M7 slice 1 gave
`batch_approvals` a `UNIQUE(id, payment_batch_version_id)` — document 04 states that pair in
§11.7 — so the reference below needs nothing added to a table this slice does not own.

**The partial unique index is where `preview` and `final` stop being symmetric.** One *active*
final export per version; previews are outside the predicate entirely, and so are `voided`,
`quarantined` and `generation_failed` finals. A voided export must not block the replacement that
voided it, and a failed generation must not stop the next attempt.

Revision ID: 20260822_0021
Revises: 20260822_0020
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260822_0021"
down_revision: str | Sequence[str] | None = "20260822_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `status_catalog.yaml`'s `bank_export` aggregate, all eight. Document 05 lists a different five
# (DOC-CONFLICT-016); the catalogue wins, and the status drift gate is what enforces that rather
# than this comment.
STATUSES_SQL = (
    "'generating', 'generated', 'validated', 'downloaded', "
    "'sent_to_bank_marked', 'voided', 'quarantined', 'generation_failed'"
)

TYPES_SQL = "'preview', 'final'"

# The four states in which a final export still occupies its version.
ACTIVE_FINAL_SQL = "'generated', 'validated', 'downloaded', 'sent_to_bank_marked'"

# §11.8 verbatim.
APPROVAL_MATCHES_TYPE_SQL = """
(export_type = 'preview' AND batch_approval_id IS NULL)
OR
(export_type = 'final' AND batch_approval_id IS NOT NULL)
"""


def upgrade() -> None:
    op.create_table(
        "bank_excel_exports",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("payment_batch_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_approval_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("bank_profile_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bank_mapping_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("export_number", sa.String(length=64), nullable=False),
        sa.Column("export_type", sa.String(length=16), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("total_amount_irr", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("file_sha256_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("generated_by_admin_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_to_bank_marked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "sent_to_bank_marked_by_admin_user_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"export_type IN ({TYPES_SQL})", name=op.f("ck_bank_excel_exports_export_type_value")
        ),
        sa.CheckConstraint(
            f"status IN ({STATUSES_SQL})", name=op.f("ck_bank_excel_exports_status_value")
        ),
        sa.CheckConstraint("row_count > 0", name=op.f("ck_bank_excel_exports_row_count_positive")),
        sa.CheckConstraint(
            "total_amount_irr > 0", name=op.f("ck_bank_excel_exports_total_positive")
        ),
        sa.CheckConstraint(
            APPROVAL_MATCHES_TYPE_SQL, name=op.f("ck_bank_excel_exports_approval_matches_type")
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_bank_excel_exports_content_hash_is_lowercase_hex"),
        ),
        sa.CheckConstraint(
            "file_sha256_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_bank_excel_exports_file_hash_is_lowercase_hex"),
        ),
        sa.ForeignKeyConstraint(
            ["payment_batch_version_id"],
            ["payment_batch_versions.id"],
            name="fk_bank_exports_version",
        ),
        sa.ForeignKeyConstraint(
            ["bank_profile_version_id"],
            ["bank_profile_versions.id"],
            name="fk_bank_exports_profile_version",
        ),
        sa.ForeignKeyConstraint(
            ["bank_mapping_id"], ["bank_mappings.id"], name="fk_bank_exports_mapping"
        ),
        sa.ForeignKeyConstraint(["file_id"], ["file_objects.id"], name="fk_bank_exports_file"),
        sa.ForeignKeyConstraint(
            ["generated_by_admin_user_id"],
            ["admin_users.id"],
            name="fk_bank_exports_generated_by",
        ),
        sa.ForeignKeyConstraint(
            ["sent_to_bank_marked_by_admin_user_id"],
            ["admin_users.id"],
            name="fk_bank_exports_sent_by",
        ),
        # §11.8's "Composite same-version integrity". Slice 1 created the pair this references.
        sa.ForeignKeyConstraint(
            ["batch_approval_id", "payment_batch_version_id"],
            ["batch_approvals.id", "batch_approvals.payment_batch_version_id"],
            name="fk_export_approval_same_version",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bank_excel_exports")),
        sa.UniqueConstraint("export_number", name=op.f("uq_bank_exports_export_number")),
    )

    op.create_index(
        "uq_active_final_export_per_version",
        "bank_excel_exports",
        ["payment_batch_version_id"],
        unique=True,
        postgresql_where=sa.text(f"export_type = 'final' AND status IN ({ACTIVE_FINAL_SQL})"),
    )
    op.create_index(
        "idx_bank_exports_by_version",
        "bank_excel_exports",
        ["payment_batch_version_id", "export_type"],
    )


def downgrade() -> None:
    op.drop_index("idx_bank_exports_by_version", table_name="bank_excel_exports")
    op.drop_index("uq_active_final_export_per_version", table_name="bank_excel_exports")
    op.drop_table("bank_excel_exports")
