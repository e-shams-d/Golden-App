"""Sessions, security events, and recent-auth contexts. Schema only.

Three tables that together answer "who is acting, under what authority, and what
was refused". Authentication behaviour is M3; what M2 owns is a shape M3 cannot
get wrong.

`auth_sessions` stores a **hash** of the session secret and never the secret.
A stolen database dump then yields nothing usable: the hash cannot be presented
as a session. Storing the secret would make every backup a set of live
credentials.

The XOR check is the load-bearing constraint. A session belongs to exactly one
actor — an admin or a trader, never both and never neither. Written as a sum
rather than as a pair of nullable foreign keys with a comment, because a comment
does not stop a row where both are set, and such a row would satisfy an admin
authorisation query *and* a trader one.

`auth_events` records what was **denied and failed**, which is the opposite of
`audit_logs`. Audit explains authorised change; a security event explains a
refusal. Keeping them apart matters because their retention, their read
permissions and their alerting differ — and because a failed login is not a
change to anything, so it has no entity to attach to.

`recent_auth_contexts` is the one with consumption columns, and they are the
point. An assurance obtained for "approve batch version 7" must not be reusable
for "approve batch version 8", and without recording consumption inside the
command transaction, a timeout-and-retry or an idempotency replay would let one
step-up authorise two different effects.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, named_check, updated_at_column, uuid_primary_key

# Doc 12's twenty security event types group into these classes. The column is a
# discriminator rather than an enum of all twenty: the class is what alerting and
# retention are decided by, and the exact type is recorded beside it.
EVENT_CLASSES: tuple[str, ...] = (
    "authentication",
    "authorization",
    "session",
    "credential",
    "account_state",
    "administrative",
)

ACTOR_TYPES: tuple[str, ...] = (
    "trader_user",
    "admin_user",
    "system_worker",
    "system_maintenance",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    # Exactly one is set; the CHECK below enforces it rather than trusting the
    # code that inserts.
    admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=True
    )
    trader_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trader_users.id"), nullable=True
    )

    # The hash, never the secret. A database dump must not yield usable sessions.
    secret_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    # No value CHECK: ADR-001 (session transport) and ADR-009 (assurance factors)
    # are both open, and enumerating levels here would decide them.
    auth_level: Mapped[str] = mapped_column(String(32), nullable=False)

    authenticated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    step_up_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)

    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # The other half of the security stamp pair. A session whose stored version
    # is behind the identity's has had its authority changed since sign-in.
    security_stamp_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("1")
    )

    # Set when a session is rotated: the new row points at the one it replaced,
    # so a chain can be revoked together after a credential compromise.
    replaced_session_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("auth_sessions.id"), nullable=True
    )

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        # Exactly one actor. A row with both set would satisfy an admin
        # authorisation query and a trader one, which is the failure M3 must be
        # able to prove impossible.
        named_check(
            "((admin_user_id IS NOT NULL)::int + (trader_user_id IS NOT NULL)::int) = 1",
            name="exactly_one_actor",
        ),
        named_check("expires_at > authenticated_at", name="expires_after_authentication"),
        named_check("security_stamp_version > 0", name="security_stamp_version_positive"),
        # A revoked session must say why. "Revoked" with no reason is the state
        # that makes an incident review impossible to complete.
        named_check(
            "(revoked_at IS NULL AND revocation_reason IS NULL) "
            "OR (revoked_at IS NOT NULL AND revocation_reason IS NOT NULL)",
            name="revocation_fields_move_together",
        ),
        named_check(
            "replaced_session_id IS NULL OR replaced_session_id <> id",
            name="replacement_is_not_self",
        ),
        # Two symmetric partial indexes rather than one over both columns: a
        # lookup only ever knows one actor kind, and a combined index would be
        # half dead weight on every query.
        Index(
            "idx_auth_sessions_active_admin",
            "admin_user_id",
            "expires_at",
            postgresql_where=text("revoked_at IS NULL AND admin_user_id IS NOT NULL"),
        ),
        Index(
            "idx_auth_sessions_active_trader",
            "trader_user_id",
            "expires_at",
            postgresql_where=text("revoked_at IS NULL AND trader_user_id IS NOT NULL"),
        ),
    )


class AuthEvent(Base):
    """Append-only security events: what was denied, failed or attempted.

    Receives the same append-only grant treatment as `audit_logs` — the runtime
    role may insert and read, never update or delete. A record of a failed login
    that the failing process can erase is not a record.
    """

    __tablename__ = "auth_events"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    # Polymorphic and unconstrained by a foreign key, like audit: the actor may
    # be an admin, a trader, a worker — or, for a failed login, an identity that
    # does not exist at all.
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(PostgresUUID(as_uuid=True), nullable=True)

    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    event_class: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)

    session_id: Mapped[uuid.UUID | None] = mapped_column(PostgresUUID(as_uuid=True), nullable=True)

    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    metadata_payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    metadata_schema: Mapped[str] = mapped_column(String(120), nullable=False)
    metadata_version: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        named_check(f"actor_type IN ({_quoted(ACTOR_TYPES)})", name="actor_type"),
        named_check(f"event_class IN ({_quoted(EVENT_CLASSES)})", name="event_class"),
        named_check("length(btrim(event_type)) > 0", name="event_type_not_blank"),
        named_check("metadata_version > 0", name="metadata_version_positive"),
        # Deliberately no human-actor-is-identified check, unlike audit_logs. A
        # failed login for an unknown username has no actor id to record, and
        # requiring one would mean either discarding the event or inventing an
        # identity — the two worst options for the case that matters most.
        Index("idx_auth_events_actor_time", "actor_type", "actor_id", "created_at"),
        Index("idx_auth_events_class_time", "event_class", "created_at"),
        Index("idx_auth_events_correlation_id", "correlation_id"),
        Index(
            "idx_auth_events_failures",
            "created_at",
            postgresql_where=text("outcome <> 'success'"),
        ),
    )


class RecentAuthContext(Base):
    """A step-up authentication, bound to one purpose and consumable once.

    The binding is the whole value. An assurance obtained for approving batch
    version 7 must not authorise approving version 8, so the context names the
    action and the exact resource, and consumption is recorded inside the
    command transaction. Without that, a timeout-and-retry or an idempotency
    replay would let one step-up authorise two different effects.
    """

    __tablename__ = "recent_auth_contexts"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    session_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("auth_sessions.id"), nullable=False
    )
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)

    # What this assurance is for. Both required: an assurance with no resource is
    # a general-purpose one, which is the thing step-up exists to avoid.
    purpose: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)

    # No CHECK on the factor: ADR-009 governs the vocabulary and is open.
    assurance_factor: Mapped[str] = mapped_column(String(48), nullable=False)

    # A hash, never a replayable token — same reason as the session secret.
    challenge_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # No NOT NULL DEFAULT interval: a validity duration is exactly what ADR-009
    # leaves open, and a default here would decide it silently.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_by_command: Mapped[str | None] = mapped_column(String(120), nullable=True)

    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        named_check(f"actor_type IN ({_quoted(ACTOR_TYPES)})", name="actor_type"),
        named_check("expires_at > issued_at", name="expires_after_issue"),
        # Consumption records what used it, not merely that something did. An
        # incident review needs to know which command consumed the assurance.
        named_check(
            "(consumed_at IS NULL AND consumed_by_command IS NULL) "
            "OR (consumed_at IS NOT NULL AND consumed_by_command IS NOT NULL)",
            name="consumption_fields_move_together",
        ),
        named_check("length(btrim(purpose)) > 0", name="purpose_not_blank"),
        # The lookup a command performs: this actor, this purpose, this exact
        # resource, still live. Partial so consumed and revoked rows leave the
        # index rather than growing it forever.
        Index(
            "idx_recent_auth_live",
            "actor_id",
            "purpose",
            "resource_id",
            "expires_at",
            postgresql_where=text("consumed_at IS NULL AND revoked_at IS NULL"),
        ),
        Index("idx_recent_auth_session", "session_id"),
    )
