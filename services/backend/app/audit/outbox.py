"""Outbox writing, on the command's own session.

The point of the pattern is that the event and the state change share a fate. So
this writer, like the audit writer, only ever stages a row: it does not commit,
does not open its own session, and does not publish anything. A dispatcher reads
committed rows later.

That is also what lets a financial command succeed while Redis is down, which the
interim rule under DOC-CONFLICT-030 requires. Nothing here touches a broker, so
there is nothing here to be unavailable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy, redact
from app.db.models.outbox_event import OutboxEvent


@dataclass(frozen=True)
class OutboxMessage:
    """One event to be published after the transaction commits."""

    aggregate_type: str
    aggregate_id: uuid.UUID
    # Captured by the caller inside the transaction. Read afterwards it would be
    # whatever a later writer left behind, and a consumer ordering on it would be
    # misled about which change this event describes.
    aggregate_version: int
    event_type: str
    payload: dict[str, Any]
    payload_version: int
    headers: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None
    causation_id: str | None = None
    available_at: datetime | None = None


class OutboxWriter:
    """Adds outbox rows to the command's session. Never commits, never publishes."""

    def __init__(self, session: Session, policy: RedactionPolicy) -> None:
        self._session = session
        self._policy = policy

    def enqueue(self, message: OutboxMessage) -> OutboxEvent:
        """Stage one event. It becomes claimable when the command commits.

        The payload is redacted on the same terms as an audit row. An outbox row
        is readable by anything that can see operational state and is copied into
        whatever the dispatcher delivers, so a secret placed here travels further
        than one placed in the audit table, not less far.
        """

        redacted_payload = redact(message.payload, self._policy)
        assert isinstance(redacted_payload, dict)
        redacted_headers = redact(message.headers, self._policy)
        assert isinstance(redacted_headers, dict)

        row = OutboxEvent(
            aggregate_type=message.aggregate_type,
            aggregate_id=message.aggregate_id,
            aggregate_version=message.aggregate_version,
            event_type=message.event_type,
            payload=redacted_payload,
            payload_version=message.payload_version,
            headers=redacted_headers,
            correlation_id=message.correlation_id,
            causation_id=message.causation_id,
            # status, available_at and attempt_count take their server defaults;
            # a row is born pending and immediately claimable.
            **({"available_at": message.available_at} if message.available_at else {}),
        )
        self._session.add(row)
        return row
