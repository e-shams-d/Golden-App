"""Audit writing, on the command's own session.

Everything about the placement is deliberate. No second session, no
`after_commit` hook, no logging handler, no trigger on another connection: each
of those would let the business change commit while the audit row did not, which
is precisely the state the table exists to make impossible. The row is inserted
through the same session as the change it describes, so one commit covers both
and one rollback discards both.

The writer takes the values it is given and applies redaction before the insert;
it does not decide what an action is called. Names come from the registry so a
provisional name can be renamed at the M0 freeze without a migration.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy, redact
from app.core.time import utc_now
from app.db.models.audit_log import ACTOR_TYPES, CURRENT_AUDIT_SCHEMA_VERSION, AuditLog

SYSTEM_ACTOR_TYPES = frozenset({"system_worker", "system_maintenance"})


@dataclass(frozen=True)
class AuditActor:
    """Who acted. The two system types carry no ID, and must not invent one."""

    actor_type: str
    actor_id: uuid.UUID | None = None
    role_snapshot: tuple[str, ...] = ()
    session_id: uuid.UUID | None = None
    recent_auth_context_id: uuid.UUID | None = None
    authentication_assurance: str | None = None

    def __post_init__(self) -> None:
        if self.actor_type not in ACTOR_TYPES:
            raise ValueError(
                f"unknown actor_type {self.actor_type!r}; the database CHECK would "
                f"reject this row at commit. Known types: {', '.join(ACTOR_TYPES)}"
            )
        is_system = self.actor_type in SYSTEM_ACTOR_TYPES
        if is_system and self.actor_id is not None:
            raise ValueError(f"{self.actor_type} must not carry an actor_id")
        if not is_system and self.actor_id is None:
            raise ValueError(
                f"{self.actor_type} must carry an actor_id; an unattributed human "
                "action is indistinguishable from a scheduled one"
            )


@dataclass(frozen=True)
class AuditContext:
    """The request-scoped identifiers a row is correlated by.

    Three separate values, not one. `request_id` identifies this HTTP request,
    `correlation_id` the whole flow it belongs to, and `causation_id` the event
    that directly caused it. Collapsing them loses the edge that makes a chain
    reconstructable.
    """

    request_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True)
class AuditEntry:
    """One recorded event, before redaction."""

    action: str
    outcome: str
    metadata_schema: str
    metadata_version: int
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    parent_entity_type: str | None = None
    parent_entity_id: uuid.UUID | None = None
    entity_record_version: int | None = None
    immutable_snapshot_hash: str | None = None
    previous_values: dict[str, Any] | None = None
    new_values: dict[str, Any] | None = None
    reason: str | None = None
    reason_code: str | None = None
    idempotency_record_id: uuid.UUID | None = None
    idempotency_key_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime | None = None


class AuditWriter:
    """Adds audit rows to the command's session. Never commits."""

    def __init__(self, session: Session, policy: RedactionPolicy) -> None:
        self._session = session
        self._policy = policy

    def record(
        self, entry: AuditEntry, *, actor: AuditActor, context: AuditContext
    ) -> AuditLog:
        """Stage one audit row. It becomes durable when the command commits."""

        row = AuditLog(
            occurred_at=entry.occurred_at or utc_now(),
            action=entry.action,
            outcome=entry.outcome,
            audit_schema_version=CURRENT_AUDIT_SCHEMA_VERSION,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            actor_role_snapshot=list(actor.role_snapshot),
            session_id=actor.session_id,
            recent_auth_context_id=actor.recent_auth_context_id,
            authentication_assurance=actor.authentication_assurance,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            parent_entity_type=entry.parent_entity_type,
            parent_entity_id=entry.parent_entity_id,
            entity_record_version=entry.entity_record_version,
            immutable_snapshot_hash=entry.immutable_snapshot_hash,
            previous_values=self._redacted(entry.previous_values),
            new_values=self._redacted(entry.new_values),
            reason=self._redacted_text(entry.reason),
            reason_code=entry.reason_code,
            request_id=context.request_id,
            correlation_id=context.correlation_id,
            causation_id=context.causation_id,
            idempotency_record_id=entry.idempotency_record_id,
            # The hash, never the key. Passing a raw key here would put a bearer
            # value into a table nobody can edit afterwards.
            idempotency_key_hash=entry.idempotency_key_hash,
            ip_address=context.ip_address,
            user_agent=context.user_agent,
            metadata_payload=self._redacted(entry.metadata) or {},
            metadata_schema=entry.metadata_schema,
            metadata_version=entry.metadata_version,
        )
        self._session.add(row)
        return row

    def _redacted(self, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        redacted = redact(value, self._policy)
        assert isinstance(redacted, dict)
        return redacted

    def _redacted_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        return self._policy.apply_to_text(value)
