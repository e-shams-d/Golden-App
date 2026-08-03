"""Transactional outbox: the event is committed with the business change.

Nothing here talks to a broker. The row is inserted in the same transaction as the
state change it describes, so either both are durable or neither is, and a
dispatcher publishes afterwards. That is what lets a financial command commit
while Redis is unavailable, which the interim rule under DOC-CONFLICT-030
requires.

The status set is the five canonical values from `status_catalog.yaml`. `retry` is
absent deliberately: the catalogue records it as an unresolved alias, and doc 04's
dispatch predicate `WHERE status IN ('pending','retry')` is not copied, because
against the approved set it would index rows no legal row can satisfy while
omitting claimed-but-stalled `processing` rows — an index that is simultaneously
dead and incomplete.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, named_check, uuid_primary_key

STATUSES: tuple[str, ...] = (
    "pending",
    "processing",
    "published",
    "failed",
    "dead_lettered",
)

CLAIMABLE_STATUSES: tuple[str, ...] = ("pending", "processing", "failed")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    # Captured inside the transaction that produced it. Read afterwards it would
    # be the version some later writer left behind, and consumers relying on it to
    # order or deduplicate would be misled.
    aggregate_version: Mapped[int] = mapped_column(BigInteger, nullable=False)

    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_version: Mapped[int] = mapped_column(Integer, nullable=False)
    headers: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'pending'")
    )

    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Redacted before it is written. A driver error string routinely carries the
    # parameters of the failing statement, and this table is readable by anyone
    # who can see operational state.
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        named_check(f"status IN ({_quoted(STATUSES)})", name="status"),
        named_check("attempt_count >= 0", name="attempt_count_not_negative"),
        named_check("aggregate_version > 0", name="aggregate_version_positive"),
        named_check("payload_version > 0", name="payload_version_positive"),
        # A published row must say when, and an unpublished row must not claim to
        # have been. Without this, `published_at IS NULL` stops being a usable
        # filter and every consumer has to check both columns.
        named_check(
            "(status = 'published' AND published_at IS NOT NULL) "
            "OR (status <> 'published' AND published_at IS NULL)",
            name="published_at_matches_status",
        ),
        # Claim bookkeeping moves as a pair, so a crashed dispatcher leaves a row
        # that can be identified by age rather than one holding half a lock.
        named_check(
            "(locked_at IS NULL AND locked_by IS NULL) "
            "OR (locked_at IS NOT NULL AND locked_by IS NOT NULL)",
            name="lock_fields_move_together",
        ),
        # The dispatch index covers exactly the claimable set: rows waiting, rows
        # whose claim may have stalled, and rows awaiting another attempt.
        # Terminal rows are excluded, so the index does not grow with history.
        Index(
            "idx_outbox_dispatch",
            "available_at",
            "created_at",
            postgresql_where=text(f"status IN ({_quoted(CLAIMABLE_STATUSES)})"),
        ),
        Index("idx_outbox_aggregate", "aggregate_type", "aggregate_id", "aggregate_version"),
        Index("idx_outbox_correlation_id", "correlation_id"),
    )
