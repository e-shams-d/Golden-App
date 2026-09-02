"""The statement the centre imports, and one run per parse of it. `04_Database_Schema.md` §10.4,
§10.5.

M10 slice 3. The outgoing half of this platform sends money and reads the bank's answer back as a
result bundle (M8). This is the incoming half: the bank's own record of what arrived, imported by
the centre rather than asserted by a trader.

**One run per parse, and a reparse never edits the old one.** §10.5 `:774`: "A reparse does not
update old rows; it creates a new run and row set." `UNIQUE(bank_statement_file_id, run_number)`
is how the schema says it, and the migration's column grants are how the runtime is prevented from
saying otherwise — `run_number`, `parser_version`, `source_hash` and `bank_mapping_id` are not
grantable, so a finished run's provenance cannot be rewritten to look like a different parse.

**The statuses are document 06's, and `status_catalog.yaml` is why.** Its
`bank_statement_import_run` aggregate carries five canonical states and records document 08 §8.3's
six review states as `unresolved_aliases` with `canonical: null`: "M0 must choose a two-axis model
or extend the canonical lifecycle." Until that choice is made, `status` is the execution axis and
there is no review axis — not an omission, a deferral with an owner.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
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

# `status_catalog.yaml`'s `bank_statement_file` aggregate, all five, in its order. Document 06
# §10.3 draws the transitions; `parse_failed` is not terminal, because a later run may succeed.
FILE_STATUSES: tuple[str, ...] = (
    "uploaded",
    "parsed",
    "parse_failed",
    "ready_for_matching",
    "archived",
)

FILE_UPLOADED = "uploaded"
FILE_ARCHIVED = "archived"

# `status_catalog.yaml`'s `bank_statement_import_run` aggregate: the five canonical states.
# `parsing` and `parse_failed` are aliases of `running` and `failed` in that aggregate and are
# deliberately absent — a CHECK enforcing an alias would let two spellings of one state coexist.
RUN_STATUSES: tuple[str, ...] = (
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
)

RUN_QUEUED = "queued"
RUN_RUNNING = "running"

# A run in either of these is doing, or about to do, the work. A second run started alongside one
# of them would produce a second row set for the same file with nothing to say which is
# authoritative — see `app/commands/bank_statement.py`, where the guard lives and is argued.
RUN_IN_FLIGHT: tuple[str, ...] = (RUN_QUEUED, RUN_RUNNING)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class BankStatementFile(Base):
    """The immutable original statement, and the import context chosen for it. §10.4."""

    __tablename__ = "bank_statement_files"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    # Doc 08 §8.2 parses "with exact BankProfileVersion and BankMapping". The version is fixed
    # here, at upload, so that a mapping offered later can be checked against it.
    bank_profile_version_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bank_profile_versions.id", name="fk_statement_files_profile_version"),
        nullable=False,
    )
    # §8.1's "selected destination center account".
    bank_account_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bank_accounts.id", name="fk_statement_files_account"),
        nullable=False,
    )
    # §8.1's "original file preservation". Unique: two statement records pointing at one upload
    # would each claim to be the original of it.
    original_file_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("file_objects.id", name="fk_statement_files_original"),
        nullable=False,
        unique=True,
    )

    status: Mapped[str] = mapped_column(String(32), nullable=False)

    # §8.1's "optional operator-supplied statement range".
    date_range_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_range_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    uploaded_by_admin_user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_statement_files_uploaded_by"),
        nullable=False,
    )

    record_version: Mapped[int] = record_version_column()
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        named_check(f"status IN ({_quoted(FILE_STATUSES)})", name="status_value"),
        # Both ends or neither, and in order. A range with one end is not a range, and a range
        # that ends before it starts describes no statement.
        named_check(
            "(date_range_start IS NULL AND date_range_end IS NULL)"
            " OR "
            "(date_range_start IS NOT NULL AND date_range_end IS NOT NULL"
            " AND date_range_start <= date_range_end)",
            name="date_range_is_whole_and_ordered",
        ),
        Index(
            "idx_bank_statement_files_account_status",
            "bank_account_id",
            "status",
            "created_at",
        ),
    )


class BankStatementImportRun(Base):
    """One parse of one statement file. §10.5.

    No `record_version` and no `updated_at`: a run is an execution record, not an entity an
    operator edits, and the only writes it takes are its own progress. `bank_profile_versions`
    and `bank_mappings` are shaped the same way for the same reason.
    """

    __tablename__ = "bank_statement_import_runs"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    bank_statement_file_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bank_statement_files.id", name="fk_import_runs_file"),
        nullable=False,
    )
    # Doc 06 §10.3: "Mapping/template version is fixed for each run."
    bank_mapping_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bank_mappings.id", name="fk_import_runs_mapping"),
        nullable=False,
    )

    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    # Null until the run finishes. Zero is a real answer — an empty statement parses to no rows —
    # so null and zero are different facts.
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # §10.5, and M8's `renderer_version` precedent: a row must be tellable apart from one a later
    # parser produced against the same file.
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # The file's sha256 as this run read it. `command_catalog.yaml` makes
    # `original_statement_unchanged` a precondition of creating a run; this column is what makes
    # that checkable afterwards rather than only at the moment of the check.
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Doc 08 §22.2: "preserve import-run errors". JSONB so a mapping mismatch can name the columns
    # it could not find.
    error_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_by_admin_user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_import_runs_created_by"),
        nullable=False,
    )
    created_by_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("processing_jobs.id", name="fk_import_runs_job"),
        nullable=True,
    )

    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        # §10.5's constraint verbatim, and the reason this table is shaped as it is.
        UniqueConstraint(
            "bank_statement_file_id", "run_number", name="uq_import_runs_file_run_number"
        ),
        named_check(f"status IN ({_quoted(RUN_STATUSES)})", name="status_value"),
        named_check("run_number >= 1", name="run_number_is_positive"),
        named_check("row_count IS NULL OR row_count >= 0", name="row_count_not_negative"),
        named_check(
            "finished_at IS NULL OR started_at IS NOT NULL", name="finished_needs_a_start"
        ),
        named_check(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="finished_after_started",
        ),
        Index(
            "idx_import_runs_file_status",
            "bank_statement_file_id",
            "status",
            "created_at",
        ),
    )


__all__ = [
    "FILE_ARCHIVED",
    "FILE_STATUSES",
    "FILE_UPLOADED",
    "RUN_IN_FLIGHT",
    "RUN_QUEUED",
    "RUN_RUNNING",
    "RUN_STATUSES",
    "BankStatementFile",
    "BankStatementImportRun",
]
