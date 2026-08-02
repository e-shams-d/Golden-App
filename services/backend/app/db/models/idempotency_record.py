"""Durable idempotency, keyed per actor and operation rather than globally.

The unique key is four columns, not one. A global key would let one caller's
choice of `Idempotency-Key` collide with another's, which is both a correctness
bug and a disclosure: the second caller would receive the first caller's stored
response.

`status` carries no value CHECK. `status_catalog.yaml` records this aggregate with
`canonical: null` and three uncatalogued doc-04 states, so the table is approved
and the enum is not. The application enforces the values fail-closed, and a named
CHECK is added by expand/contract once the catalogue settles — see the plan's
§2.3 discipline on deciding an open enum by writing it into a migration.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, named_check, uuid_primary_key

# Same vocabulary as the audit actor, and for the same reason: the two must agree
# or a record cannot be attributed to the actor who created it.
ACTOR_TYPES: tuple[str, ...] = (
    "trader_user",
    "admin_user",
    "system_worker",
    "system_maintenance",
)

REQUEST_HASH_LENGTH = 64


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # NOT NULL here, unlike the audit table. An anonymous caller has no way to
    # scope a key, so there is no legitimate row without an actor.
    actor_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)

    operation: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    # Over a canonically serialised payload, so the same request hashes the same
    # regardless of key order or whitespace. Fixed width because it is always a
    # SHA-256 digest; a varying length would mean something upstream changed.
    request_hash: Mapped[str] = mapped_column(CHAR(REQUEST_HASH_LENGTH), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False)

    resource_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(PostgresUUID(as_uuid=True), nullable=True)

    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Sanitised before storage. Replaying a stored response hands back whatever was
    # captured, so anything sensitive in it is disclosed once per replay.
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Nothing acts on this in M2. Every expiry sweeper, purge job and deletion
    # path is blocked by the open ADR-005, so the column is recorded and left
    # inert rather than wired to an executor that has no approved policy.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = created_at_column()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "actor_type",
            "actor_id",
            "operation",
            "idempotency_key",
            name="uq_idempotency_records_actor_operation_key",
        ),
        named_check(
            f"actor_type IN ({', '.join(repr(value) for value in ACTOR_TYPES)})",
            name="actor_type",
        ),
        named_check(f"length(request_hash) = {REQUEST_HASH_LENGTH}", name="request_hash_length"),
        named_check("request_hash = lower(request_hash)", name="request_hash_lowercase"),
        named_check("length(btrim(idempotency_key)) > 0", name="idempotency_key_not_blank"),
        named_check(
            "response_code IS NULL OR response_code BETWEEN 100 AND 599",
            name="response_code_range",
        ),
        named_check("expires_at > created_at", name="expires_after_creation"),
        # Doc 04's name, used verbatim.
        Index("idx_idempotency_expiry", "expires_at"),
    )
