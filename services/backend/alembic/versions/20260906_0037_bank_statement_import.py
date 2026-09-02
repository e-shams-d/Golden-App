"""The centre's own copy of what the bank says happened. `04_Database_Schema.md` §10.4, §10.5.

M10 slice 3. Two tables: the immutable statement file, and one run per parse of it.

**`UNIQUE(bank_statement_file_id, run_number)` is the whole design in one constraint.** §10.5's
first line is "Every parse/reparse is a separate run", and §10.5 `:774` spells out the consequence:
"A reparse does not update old rows; it creates a new run and row set." So a reparse cannot be an
UPDATE of run 1 — the unique makes run 2 a different row, and the grants below make run 1's
provenance unwritable.

**The statuses are document 06's five, not document 08's nine, and that is a governance decision
rather than a preference.** `status_catalog.yaml`'s `bank_statement_import_run` aggregate says it
outright: "Document 06 models technical execution states. Document 08 defines a richer
preview/confirmation lifecycle and is intentionally not silently collapsed." Document 08's
`draft`, `preview_ready`, `partial_preview`, `confirmed`, `rejected` and `superseded` sit in that
aggregate's `unresolved_aliases` with `canonical: null` and the note "M0 must choose a two-axis
model or extend the canonical lifecycle". Enforcing one of those six here would enforce a value M0
has not approved, and `test_status_catalogue_drift.py` would say so.

`parsing` and `parse_failed` are *aliases* in the same aggregate, of `running` and `failed`. The
CHECK carries canonical spellings only, as every other status CHECK in this schema does.

**No review column.** The human confirmation `15_Agent_Implementation_Plan.md:1232` requires is
real and is not in this revision, because this revision has nothing to review: rows are slice 4.
A `review_status` written by nothing would be the defect this repository has shipped five times —
complete machinery with no caller — and it would also pre-empt the two-axis decision above.

**Grants: the run's lifecycle and its results, and nothing that says which parse produced them.**
`bank_statement_import_runs` grants `status`, `row_count`, `started_at`, `finished_at` and
`error_summary`. It does **not** grant `run_number`, `parser_version`, `source_hash`,
`bank_mapping_id` or `bank_statement_file_id`. That is `TRACE-IMPORT-001` enforced by absence: a
run whose `parser_version` could be rewritten afterwards could not be told apart from one produced
by a different parser, which is the entire reason §10.5 asks for the column.

`bank_statement_files` grants `status` and `record_version` only. The file is the immutable
original — §10.4's own first line — so its bank version, its account, its file id and its operator
range are not writable after the upload that recorded them.

Revision ID: 20260906_0037
Revises: 20260905_0036
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260906_0037"
down_revision: str | Sequence[str] | None = "20260905_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `status_catalog.yaml`'s `bank_statement_file` aggregate, all five, in its order.
# Document 06 §10.1 is its source and §10.3 draws the transitions, including `parse_failed` ->
# `parsed` when a later run succeeds — which is why `parse_failed` is not terminal here.
FILE_STATUSES = (
    "uploaded",
    "parsed",
    "parse_failed",
    "ready_for_matching",
    "archived",
)

# `status_catalog.yaml`'s `bank_statement_import_run` aggregate: the five canonical states.
# `parsing` and `parse_failed` are aliases of `running` and `failed` and are deliberately absent.
RUN_STATUSES = (
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
)

# The run's execution result. Not its provenance — see the module docstring.
RUN_GRANTED_COLUMNS = (
    "status",
    "row_count",
    "started_at",
    "finished_at",
    "error_summary",
)

# The file's lifecycle. Everything else about a statement file is the original.
FILE_GRANTED_COLUMNS = (
    "status",
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
        "bank_statement_files",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # §8.2: a parse happens "with exact BankProfileVersion and BankMapping". The version is
        # fixed at upload so that the mapping chosen at import time can be checked against it —
        # a mapping belonging to a different bank's version is the mismatch `BANK-VER-005` names.
        sa.Column(
            "bank_profile_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bank_profile_versions.id", name="fk_statement_files_profile_version"),
            nullable=False,
        ),
        # §8.1's "selected destination center account". The command refuses an account whose
        # `account_role` is not an incoming one; the column itself only says which account.
        sa.Column(
            "bank_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bank_accounts.id", name="fk_statement_files_account"),
            nullable=False,
        ),
        # §8.1's "original file preservation", and §22.2's first requirement on failure. NOT NULL:
        # a statement file with no file is a record of nothing.
        sa.Column(
            "original_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("file_objects.id", name="fk_statement_files_original"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        # §8.1's "optional operator-supplied statement range". Optional, and both or neither:
        # a range with one end is not a range.
        sa.Column("date_range_start", sa.Date(), nullable=True),
        sa.Column("date_range_end", sa.Date(), nullable=True),
        sa.Column(
            "uploaded_by_admin_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", name="fk_statement_files_uploaded_by"),
            nullable=False,
        ),
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
        sa.CheckConstraint(f"status IN ({_quoted(FILE_STATUSES)})", name="status_value"),
        sa.CheckConstraint(
            "(date_range_start IS NULL AND date_range_end IS NULL)"
            " OR "
            "(date_range_start IS NOT NULL AND date_range_end IS NOT NULL"
            " AND date_range_start <= date_range_end)",
            name="date_range_is_whole_and_ordered",
        ),
    )

    op.create_index(
        "idx_bank_statement_files_account_status",
        "bank_statement_files",
        ["bank_account_id", "status", "created_at"],
    )

    op.create_table(
        "bank_statement_import_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "bank_statement_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bank_statement_files.id", name="fk_import_runs_file"),
            nullable=False,
        ),
        # Doc 06 §10.3: "Mapping/template version is fixed for each run." Fixed literally — the
        # column is not in `RUN_GRANTED_COLUMNS`, so the runtime cannot repoint a finished run at
        # a different mapping and make its rows unexplainable.
        sa.Column(
            "bank_mapping_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bank_mappings.id", name="fk_import_runs_mapping"),
            nullable=False,
        ),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        # Null until the run finishes. Zero is a real answer — an empty statement parses to no
        # rows — so null and zero are different facts and the column allows both.
        sa.Column("row_count", sa.Integer(), nullable=True),
        # §10.5, and M8's `renderer_version` precedent. Recorded at creation and never granted.
        sa.Column("parser_version", sa.String(64), nullable=False),
        # The sha256 of the file as it was when this run read it. §26.2's "duplicate file
        # checksum" case and §8.7's first duplicate signal both need it, and it is what makes
        # `original_statement_unchanged` — the catalogued precondition — checkable at all.
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        # §22.2: "preserve import-run errors". JSONB rather than text so a mapping mismatch can
        # name the columns it could not find without the report becoming prose.
        sa.Column("error_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_by_admin_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", name="fk_import_runs_created_by"),
            nullable=False,
        ),
        # The job that will do the parsing. Nullable: the run exists before the job is enqueued,
        # and a run created by a path with no job is still a run.
        sa.Column(
            "created_by_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("processing_jobs.id", name="fk_import_runs_job"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # §10.5's constraint verbatim, and the reason the table exists in this shape.
        sa.UniqueConstraint(
            "bank_statement_file_id", "run_number", name="uq_import_runs_file_run_number"
        ),
        sa.CheckConstraint(f"status IN ({_quoted(RUN_STATUSES)})", name="status_value"),
        sa.CheckConstraint("run_number >= 1", name="run_number_is_positive"),
        sa.CheckConstraint("row_count IS NULL OR row_count >= 0", name="row_count_not_negative"),
        # A run that says it finished must say when it started. Not in §10.5; it closes the same
        # shape as slice 2's `confirmation_needs_an_actor` — a timestamp pair where one half
        # without the other describes an event that cannot have happened.
        sa.CheckConstraint(
            "finished_at IS NULL OR started_at IS NOT NULL",
            name="finished_needs_a_start",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="finished_after_started",
        ),
    )

    op.create_index(
        "idx_import_runs_file_status",
        "bank_statement_import_runs",
        ["bank_statement_file_id", "status", "created_at"],
    )

    bind = op.get_bind()
    roles = _runtime_roles()
    for table, columns in (
        ("bank_statement_files", FILE_GRANTED_COLUMNS),
        ("bank_statement_import_runs", RUN_GRANTED_COLUMNS),
    ):
        granted = ", ".join(columns)
        for role in roles:
            bind.execute(
                sa.text(f'GRANT UPDATE ({granted}) ON public."{table}" TO "{role}"')
            )


def downgrade() -> None:
    op.drop_index("idx_import_runs_file_status", table_name="bank_statement_import_runs")
    op.drop_table("bank_statement_import_runs")
    op.drop_index("idx_bank_statement_files_account_status", table_name="bank_statement_files")
    op.drop_table("bank_statement_files")
