"""Append-only audit evidence, written in the same transaction as the command.

The column set is the union of three authorities, not the intersection: doc 04
§15.3 for the table and index names, `FINANCIAL_INTEGRITY_BASELINE.md` §4 for the
fields that must be first-class rather than buried in metadata, and doc 12 for the
actor vocabulary. Where they disagree the plan's §2.3 rows decide, and the
divergences are recorded there rather than resolved silently here:

* `action` replaces doc 04's `event_type`, so `idx_audit_event_time` becomes
  `idx_audit_action_time`. The other two doc-04 index names are kept verbatim.
* `request_id`, `correlation_id` and `causation_id` are three columns. Doc 04 has
  a single `request_id` described as a correlation ID; the baseline requires all
  three, and collapsing them loses the causation edge entirely.
* `actor_type` carries a named CHECK over doc 12's four values. `outcome` does
  not, because no approved catalogue enumerates it and inventing the set here
  would decide it.

Rows are never updated. That is why redaction happens in the writer, before the
insert: a value written in error cannot be masked later, only exposed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, named_check, uuid_primary_key

ACTOR_TYPES: tuple[str, ...] = (
    "trader_user",
    "admin_user",
    "system_worker",
    "system_maintenance",
)

CURRENT_AUDIT_SCHEMA_VERSION = 1


def _quoted_actor_types() -> str:
    return ", ".join(f"'{value}'" for value in ACTOR_TYPES)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    # Assigned by a sequence so rows have a total order that survives two inserts
    # sharing a timestamp, which a UUIDv4 primary key plus occurred_at cannot.
    #
    # Read cursors must still tolerate gaps rather than assume contiguity: a
    # sequence allocates in request order but rows become visible in commit order,
    # so a reader can pass a value that a slower concurrent transaction has not
    # committed yet. Ordering is stable; contiguity is not, and treating it as
    # contiguous would silently skip rows.
    sequence_number: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False), nullable=False
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    action: Mapped[str] = mapped_column(String(120), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    audit_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text(str(CURRENT_AUDIT_SCHEMA_VERSION))
    )

    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Nullable and deliberately unconstrained by a foreign key: actors span two
    # separate identity domains plus two non-human types, so no single table can
    # be the referent.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(PostgresUUID(as_uuid=True), nullable=True)
    # An array literal, not '{}'. A JSONB object default here would make every
    # consumer branch on the shape before iterating.
    actor_role_snapshot: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    session_id: Mapped[uuid.UUID | None] = mapped_column(PostgresUUID(as_uuid=True), nullable=True)
    # The column was declared in slice 1 without its foreign key, because the
    # referenced table did not exist yet. Attached now by expand/contract, so
    # rows written in between keep whatever they recorded and new ones are
    # checked.
    #
    # No ON DELETE: a recent-auth context is never deleted while an audit row
    # references it. Cascading would erase the evidence of which assurance
    # authorised a change, which is the reason the column exists.
    recent_auth_context_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("recent_auth_contexts.id"),
        nullable=True,
    )
    # No CHECK: the assurance factor vocabulary is governed by the open ADR-009,
    # and enumerating it would decide it.
    authentication_assurance: Mapped[str | None] = mapped_column(String(48), nullable=True)

    entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PostgresUUID(as_uuid=True), nullable=True)
    parent_entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    parent_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True
    )
    entity_record_version: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    immutable_snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    previous_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    new_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)

    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    idempotency_record_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True
    )
    # The hash, never the key. A raw idempotency key is a bearer value: anyone
    # holding it can replay the caller's request against the stored response.
    idempotency_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Doc 04's optional hash chain. The columns exist so a later milestone can
    # populate them without a migration; M2 computes no chain, and a partially
    # populated chain would be worse than none because it looks verified.
    previous_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Metadata may extend an event but may never substitute for a first-class
    # field, so both descriptors are mandatory whenever a payload is present.
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    metadata_schema: Mapped[str] = mapped_column(String(120), nullable=False)
    metadata_version: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        named_check(f"actor_type IN ({_quoted_actor_types()})", name="actor_type"),
        named_check("audit_schema_version > 0", name="audit_schema_version_positive"),
        named_check("metadata_version > 0", name="metadata_version_positive"),
        named_check("length(btrim(action)) > 0", name="action_not_blank"),
        named_check("length(btrim(outcome)) > 0", name="outcome_not_blank"),
        named_check("length(btrim(metadata_schema)) > 0", name="metadata_schema_not_blank"),
        # A human actor must be identifiable; the two system types have no ID to
        # give. Without this, an admin action could be recorded with a null actor
        # and remain indistinguishable from a scheduled task.
        named_check(
            "(actor_type IN ('system_worker', 'system_maintenance') AND actor_id IS NULL) "
            "OR (actor_type IN ('trader_user', 'admin_user') AND actor_id IS NOT NULL)",
            name="human_actor_is_identified",
        ),
        # The seven documented access paths. The first two names are doc 04's
        # verbatim; the third is renamed because the column is `action`.
        Index("idx_audit_entity_time", "entity_type", "entity_id", "occurred_at"),
        Index("idx_audit_actor_time", "actor_type", "actor_id", "occurred_at"),
        Index("idx_audit_action_time", "action", "occurred_at"),
        Index("idx_audit_occurred_at", "occurred_at"),
        Index("idx_audit_request_id", "request_id"),
        Index("idx_audit_correlation_id", "correlation_id"),
        # The security-event class. Partial, because security actions are a small
        # fraction of the table and a full index over `action` would be paid for
        # on every write to serve one read path.
        Index(
            "idx_audit_security_events",
            "occurred_at",
            postgresql_where=text("action LIKE 'security.%'"),
        ),
        Index("uq_audit_logs_sequence_number", "sequence_number", unique=True),
    )
