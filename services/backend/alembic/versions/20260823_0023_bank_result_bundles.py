"""The bundle the bank returned, its files, and the batches it may point at.
`04_Database_Schema.md` §12.1-12.3.

M8 slice 1. Three tables, and the one worth reading is the third.

**A batch link proves nothing.** §12.3 at `:1199`: "This association does not prove payment
completion. Attempt/segment confirmation remains authoritative." So this migration deliberately
does **not** give the link table anything that could be mistaken for a result: no amount, no
`confirmed_at`, no attempt reference. It records that somebody thought a bundle relates to a batch,
with `link_method` saying how they decided and `replaced_at` so a wrong guess leaves evidence
instead of vanishing. `tests/integration/test_bundle_links.py` asserts the absence, because a
column added later would make the sentence above false without any test noticing.

**The counts are cached and the grants say so.** §12.1 at `:1179`: they "must be
recomputed/validated transactionally from segments/tasks; they are not independent financial
truth". The runtime therefore gets UPDATE on the three count columns and on `status`,
`record_version`, `closed_at` and `closed_by_admin_user_id` — and on nothing else. `bundle_number`,
`source_type`, `uploaded_by_admin_user_id` and `uploaded_at` are not writable after insert, so the
question "which bundle is this and who brought it in" has one answer for the row's whole life.
The column-level discipline is M7 slice 2's, for the reason that slice gives: a table-level grant
would also permit rewriting the identity.

**`bank_result_bundle_files` gets no UPDATE at all.** A row here says "this file is part of this
bundle, at this position, in this role". None of those can change: a file that turns out to belong
elsewhere is a row to remove, not a row to edit, and `page_count` is measured once from the file.

**Two uniqueness constraints on the file table, and they are not redundant.**
`UNIQUE(bundle, file)` stops one file being attached twice; `UNIQUE(bundle, sequence_number,
file_role)` stops two files claiming the same position *in the same role* while leaving a source
and its preview free to share a sequence number. §12.2 states both at `:1186`.

Revision ID: 20260823_0023
Revises: 20260822_0022
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260823_0023"
down_revision: str | Sequence[str] | None = "20260822_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `status_catalog.yaml`'s `bank_result_bundle` aggregate, all eight, in its order. The catalogue
# also records `files_stored`, `normalized`, `under_manual_review`, `needs_attention` and
# `archived` as unresolved aliases; none is canonical and none is admitted here.
BUNDLE_STATUSES = (
    "uploaded",
    "processing",
    "ready_for_manual_review",
    "partially_matched",
    "matched",
    "closed",
    "failed",
    "voided",
)

# §12.2 at `:1191`, verbatim.
FILE_ROLES = ("source", "normalized", "preview", "structured_result")

# The link's own lifecycle. `active` and `replaced` only: §12.3's `replaced_at` and
# `06_Workflows_and_State_Machines.md`'s rule that a replacement never deletes the old row.
LINK_STATUSES = ("active", "replaced")

# How somebody decided a bundle relates to a batch. Not a score and not a match: `link_method`
# records the *route to the belief*, so a later reader can weigh it.
LINK_METHODS = ("manual_selection", "export_reference", "bundle_note")


# The UPDATE surface, named column by column. Everything absent is frozen after insert.
#
# A bundle's number, source type, uploader and upload time are what it *is*; the runtime can move
# it through its lifecycle and recount its segments, and cannot rewrite its identity. A table-level
# grant would permit both, which is why M7 slice 2 established this discipline and why it is
# followed here rather than reinvented.
BUNDLE_GRANTED_COLUMNS = (
    "status",
    "segment_count",
    "resolved_segment_count",
    "unresolved_segment_count",
    "record_version",
    "closed_at",
    "closed_by_admin_user_id",
    "notes",
    "bank_profile_id",
    "updated_at",
)

# The link's only mutation is being replaced. `bank_result_bundle_files` gets no UPDATE at all:
# which file, at which position, in which role are three facts that do not change.
LINK_GRANTED_COLUMNS = ("status", "replaced_at")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _runtime_roles() -> tuple[str, ...]:
    """The roles to grant to, read from settings rather than written here.

    Hardcoding a role name was the first version of this migration and it failed the
    fresh-database test with `role "gold_app_runtime" does not exist` — the test provisions its own
    roles and takes their names from the same settings. `20260822_0022` established this helper for
    exactly that reason; this is a copy of it, because a migration importing another migration is
    worse than nine lines repeated.
    """

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
        "bank_result_bundles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # §12.1. Human-readable and unique. The calendar is Gregorian per DOC-CONFLICT-054's
        # interim rule, which is why this is `BRB-YYYYMMDD-NNNNNN` and not the Jalali form
        # `07_UI_UX_Specification.md:630` shows.
        sa.Column("bundle_number", sa.String(64), nullable=False),
        # Nullable, and Q-5 records why it is not always knowable: a bundle may arrive before
        # anybody has worked out which bank sent it.
        sa.Column(
            "bank_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bank_profiles.id", name="fk_bundles_bank_profile"),
            nullable=True,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "uploaded_by_admin_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", name="fk_bundles_uploaded_by"),
            nullable=False,
        ),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        # The three cached counts. `:1179` calls them read values, not financial truth.
        #
        # **No server default, deliberately.** `DEFAULT 0` would let an INSERT that forgot to count
        # succeed, and the first version of this migration had it — which the schema/model gate
        # caught as a mismatch and is worth keeping fixed for the stronger reason: a writer must
        # state these, because `recount` is the only thing entitled to decide them.
        sa.Column("segment_count", sa.Integer(), nullable=False),
        sa.Column("resolved_segment_count", sa.Integer(), nullable=False),
        sa.Column("unresolved_segment_count", sa.Integer(), nullable=False),
        sa.Column("record_version", sa.BigInteger(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "closed_by_admin_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", name="fk_bundles_closed_by"),
            nullable=True,
        ),
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
        sa.UniqueConstraint("bundle_number", name="uq_bundles_bundle_number"),
        sa.CheckConstraint(
            f"status IN ({_quoted(BUNDLE_STATUSES)})", name="status_value"
        ),
        # §12.1's three CHECKs, verbatim.
        sa.CheckConstraint("segment_count >= 0", name="segment_count_non_negative"),
        sa.CheckConstraint(
            "resolved_segment_count >= 0", name="resolved_count_non_negative"
        ),
        sa.CheckConstraint(
            "unresolved_segment_count >= 0", name="unresolved_count_non_negative"
        ),
        # Not in §12.1, and added for the reason `:1179` gives: the two parts must sum to the
        # whole, or the cached values are three independent numbers rather than one fact counted
        # three ways. A CHECK is where this belongs, because it holds for every writer including
        # a future one that forgets.
        sa.CheckConstraint(
            "resolved_segment_count + unresolved_segment_count = segment_count",
            name="counts_reconcile",
        ),
        # `closed` needs both closing facts and nothing else may have them. The same separation
        # shape M7 slice 1 used for `batch_approvals`.
        sa.CheckConstraint(
            "(status = 'closed' AND closed_at IS NOT NULL AND closed_by_admin_user_id IS NOT NULL)"
            " OR "
            "(status <> 'closed' AND closed_at IS NULL AND closed_by_admin_user_id IS NULL)",
            name="closed_requires_closer",
        ),
    )

    # §12.1's own index, at `:1659`.
    op.create_index(
        "idx_bundle_review_queue",
        "bank_result_bundles",
        ["status", "uploaded_at"],
        postgresql_where=sa.text(
            "status IN ('ready_for_manual_review','partially_matched','failed')"
        ),
    )

    op.create_table(
        "bank_result_bundle_files",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "bank_result_bundle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bank_result_bundles.id", name="fk_bundle_files_bundle"),
            nullable=False,
        ),
        sa.Column(
            "file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("file_objects.id", name="fk_bundle_files_file"),
            nullable=False,
        ),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("file_role", sa.String(32), nullable=False),
        # Nullable: a page count is meaningful for a PDF and not for a spreadsheet, and slice 5 is
        # what can measure it. `:1183` makes it optional and this does not improve on that.
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("bank_result_bundle_id", "file_id", name="uq_bundle_files_file"),
        sa.UniqueConstraint(
            "bank_result_bundle_id",
            "sequence_number",
            "file_role",
            name="uq_bundle_files_sequence_in_role",
        ),
        sa.CheckConstraint("sequence_number > 0", name="sequence_positive"),
        sa.CheckConstraint(
            f"file_role IN ({_quoted(FILE_ROLES)})", name="role_value"
        ),
        sa.CheckConstraint(
            "page_count IS NULL OR page_count > 0", name="page_count_positive"
        ),
    )

    op.create_table(
        "bank_result_bundle_batch_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "bank_result_bundle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bank_result_bundles.id", name="fk_bundle_links_bundle"),
            nullable=False,
        ),
        sa.Column(
            "payment_batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_batches.id", name="fk_bundle_links_batch"),
            nullable=False,
        ),
        # Nullable per §12.3: a link may name the batch without committing to which version, which
        # is honest when somebody recognises a batch number on a bank statement.
        sa.Column(
            "payment_batch_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_batch_versions.id", name="fk_bundle_links_version"),
            nullable=True,
        ),
        sa.Column("link_method", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "created_by_admin_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", name="fk_bundle_links_created_by"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("replaced_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"link_method IN ({_quoted(LINK_METHODS)})", name="method_value"
        ),
        sa.CheckConstraint(
            f"status IN ({_quoted(LINK_STATUSES)})", name="status_value"
        ),
        # `replaced` needs its timestamp and `active` must not have one. Without this a row could
        # claim to be current while carrying the moment it stopped being.
        sa.CheckConstraint(
            "(status = 'replaced' AND replaced_at IS NOT NULL)"
            " OR "
            "(status = 'active' AND replaced_at IS NULL)",
            name="replaced_requires_timestamp",
        ),
    )

    # One *active* link per (bundle, batch). A replaced row stays and is outside the predicate, so
    # correcting a link leaves both the old belief and the new one — §12.3's `replaced_at` is only
    # useful if the old row survives to carry it.
    op.create_index(
        "uq_bundle_links_active_pair",
        "bank_result_bundle_batch_links",
        ["bank_result_bundle_id", "payment_batch_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "idx_bundle_links_by_batch",
        "bank_result_bundle_batch_links",
        ["payment_batch_id", "status"],
    )

    # The grants. `infra/postgres/bootstrap/020-runtime-roles.sql` gives new tables SELECT and
    # INSERT; these two statements are the whole UPDATE surface.
    bind = op.get_bind()
    bundle_columns = ", ".join(BUNDLE_GRANTED_COLUMNS)
    link_columns = ", ".join(LINK_GRANTED_COLUMNS)
    for role in _runtime_roles():
        bind.execute(
            sa.text(
                f'GRANT UPDATE ({bundle_columns}) ON public."bank_result_bundles" TO "{role}"'
            )
        )
        bind.execute(
            sa.text(
                f'GRANT UPDATE ({link_columns}) '
                f'ON public."bank_result_bundle_batch_links" TO "{role}"'
            )
        )


def downgrade() -> None:
    op.drop_index("idx_bundle_links_by_batch", table_name="bank_result_bundle_batch_links")
    op.drop_index("uq_bundle_links_active_pair", table_name="bank_result_bundle_batch_links")
    op.drop_table("bank_result_bundle_batch_links")
    op.drop_table("bank_result_bundle_files")
    op.drop_index("idx_bundle_review_queue", table_name="bank_result_bundles")
    op.drop_table("bank_result_bundles")
