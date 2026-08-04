"""Durable job state, owned by PostgreSQL rather than by the broker.

Celery's queue is transport. It knows a message was delivered; it does not know
whether the work succeeded, how many times it has been attempted, or what it
produced. Losing Redis therefore must not lose job truth — DOC-CONFLICT-030's
interim rule requires exactly that — so the authoritative record is a row here
and the broker only carries the wake-up.

The status CHECK is written, unlike `idempotency_records`. `processing_job` is an
approved aggregate with eight canonical values in `status_catalog.yaml:602-614`,
so enumerating them decides nothing that is still open.

Two indexes exist that doc 04 never writes down, because the worker pattern it
specifies cannot run without them: a claim index over `(queue_name, status,
available_at)` and a reclaim index over `heartbeat_at`. Adding a lease column
afterwards means migrating a live queue while workers hold rows in it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, named_check, updated_at_column, uuid_primary_key

STATUSES: tuple[str, ...] = (
    "queued",
    "running",
    "succeeded",
    "failed",
    "retry_scheduled",
    "cancelled",
    "dead_lettered",
    "fallback_to_manual",
)

# What a worker may pick up. `running` is included because a claimant can die
# holding a row: the lease, not the status, is what says whether it is still
# being worked on. Excluding it would strand every crashed job forever.
CLAIMABLE_STATUSES: tuple[str, ...] = ("queued", "retry_scheduled", "running")

TERMINAL_STATUSES: tuple[str, ...] = (
    "succeeded",
    "cancelled",
    "dead_lettered",
    "fallback_to_manual",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    job_type: Mapped[str] = mapped_column(String(120), nullable=False)
    # One of the six frozen queue prefixes. Not a foreign key to anything: the
    # queue set lives in configuration, and DOC-CONFLICT-032 leaves the concrete
    # worker topology open.
    queue_name: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'queued'")
    )

    input_entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    input_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True
    )

    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_version: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Retained even on failure. A dead-lettered job that discarded its input
    # cannot be reviewed and cannot be retried by an authorised operator, which
    # turns a recoverable failure into a lost one.
    input_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Nullable, and unique only where present — see the partial index below.
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"))

    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The lease. A claimant refreshes it while working; a stale one means the
    # claimant is gone and the row may be taken by somebody else.
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)

    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Redacted before it is written. A driver error string routinely carries the
    # parameters of the failing statement.
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    record_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("1")
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        named_check(f"status IN ({_quoted(STATUSES)})", name="status"),
        named_check("attempt_count >= 0", name="attempt_count_not_negative"),
        named_check("max_attempts >= 1", name="max_attempts_positive"),
        named_check("attempt_count <= max_attempts", name="attempts_within_maximum"),
        # A finished job must say when, and an unfinished one must not claim to
        # have. Otherwise `finished_at IS NULL` stops being a usable filter.
        named_check(
            f"(status IN ({_quoted(TERMINAL_STATUSES)}) AND finished_at IS NOT NULL) "
            f"OR (status NOT IN ({_quoted(TERMINAL_STATUSES)}) AND finished_at IS NULL)",
            name="finished_at_matches_status",
        ),
        # Lease bookkeeping moves together, so a crashed claimant leaves a row
        # identifiable by age rather than one holding half a lease.
        named_check(
            "(locked_by IS NULL AND heartbeat_at IS NULL) "
            "OR (locked_by IS NOT NULL AND heartbeat_at IS NOT NULL)",
            name="lease_fields_move_together",
        ),
        # Partial and unique, exactly as 04:1373-1376 instructs. A plain unique
        # constraint would allow only one job per type with a NULL key in some
        # databases and many in others; partial says what is meant.
        Index(
            "uq_processing_jobs_type_idempotency_key",
            "job_type",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        # The claim path. Doc 04 does not write this down and the worker pattern
        # it specifies cannot run without it: every poll filters on exactly these
        # three columns in this order.
        Index(
            "idx_processing_jobs_claim",
            "queue_name",
            "status",
            "available_at",
            postgresql_where=text(f"status IN ({_quoted(CLAIMABLE_STATUSES)})"),
        ),
        # The reclaim path: find rows whose claimant stopped heartbeating.
        Index(
            "idx_processing_jobs_stale_lease",
            "heartbeat_at",
            postgresql_where=text("heartbeat_at IS NOT NULL"),
        ),
        Index("idx_processing_jobs_input_entity", "input_entity_type", "input_entity_id"),
    )
