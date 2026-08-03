"""The exemplar command: rename the center profile.

Named, not generic. `PATCH /center-profile` with an arbitrary body would let any
field change through one code path, and audit could then only record "something
was patched". A command says what was intended, which is what makes the audit row
worth keeping.

Everything the slice built meets here, and all of it in one commit: the
compare-and-swap on `record_version`, the audit row, the outbox event and the
idempotency completion. Either all four are durable or none of them are.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import CursorResult, update

from app.audit import AuditActor, AuditContext, AuditEntry, AuditWriter, OutboxMessage, OutboxWriter
from app.audit.redaction import RedactionPolicy
from app.audit.registry import RENAME_CENTER_PROFILE
from app.core.errors import BusinessRuleViolationError, NotFoundError, VersionConflictError
from app.core.time import utc_now
from app.db.models.center_profile import CenterProfile
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.idempotency import IdempotencyResolver, key_hash

OPERATION = "center_profile.rename"

METADATA_SCHEMA = "audit.center_profile.rename"
METADATA_VERSION = 1
PAYLOAD_VERSION = 1

MAX_NAME_LENGTH = 200


@dataclass(frozen=True)
class RenameCenterProfile:
    """What the caller asked for, already parsed and bounded."""

    profile_id: uuid.UUID
    new_name: str
    expected_record_version: int
    reason: str | None = None


@dataclass(frozen=True)
class RenameResult:
    profile_id: uuid.UUID
    name: str
    record_version: int
    replayed: bool


def _validate(command: RenameCenterProfile) -> str:
    name = command.new_name.strip()
    if not name:
        raise BusinessRuleViolationError("The center profile name cannot be blank.")
    if len(name) > MAX_NAME_LENGTH:
        raise BusinessRuleViolationError(
            f"The center profile name cannot exceed {MAX_NAME_LENGTH} characters."
        )
    return name


def execute(
    command: RenameCenterProfile,
    *,
    uow: SqlAlchemyUnitOfWork,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    policy: RedactionPolicy,
) -> RenameResult:
    """Run the command, or return what the first identical request produced."""

    name = _validate(command)
    assert actor.actor_id is not None  # AuditActor rejects a human actor without one

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        operation=OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "profile_id": str(command.profile_id),
            "new_name": name,
            "expected_record_version": command.expected_record_version,
        },
    )

    if claim.is_replay:
        stored = claim.record.response_body or {}
        return RenameResult(
            profile_id=command.profile_id,
            name=str(stored.get("name", name)),
            record_version=int(stored.get("record_version", command.expected_record_version)),
            replayed=True,
        )

    previous = uow.session.get(CenterProfile, command.profile_id)
    if previous is None:
        raise NotFoundError()
    previous_name = previous.name

    # Compare-and-swap in the statement, never read-then-compare in Python. Under
    # READ COMMITTED the row can change between the read above and a write, so a
    # Python-side check would pass while writing over somebody else's update. The
    # predicate and the affected-row count are what actually enforce the version.
    # Cast because Session.execute is typed as returning Result, while a DML
    # statement always yields a CursorResult. The row count is the enforcement
    # here, so it must be read rather than assumed.
    result = cast(
        "CursorResult[Any]",
        uow.session.execute(
            update(CenterProfile)
            .where(
                CenterProfile.id == command.profile_id,
                CenterProfile.record_version == command.expected_record_version,
            )
            .values(
                name=name,
                record_version=CenterProfile.record_version + 1,
                updated_at=utc_now(),
            )
        ),
    )

    if result.rowcount != 1:
        # Zero rows means the version did not match. The row exists — it was read
        # a moment ago — so this is staleness, not absence.
        raise VersionConflictError()

    new_version = command.expected_record_version + 1

    AuditWriter(uow.session, policy).record(
        AuditEntry(
            action=RENAME_CENTER_PROFILE.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="center_profile",
            entity_id=command.profile_id,
            entity_record_version=new_version,
            previous_values={"name": previous_name},
            new_values={"name": name},
            reason=command.reason,
            idempotency_record_id=claim.record.id,
            # The hash, never the key itself.
            idempotency_key_hash=key_hash(idempotency_key),
            metadata={"operation": OPERATION},
        ),
        actor=actor,
        context=context,
    )

    assert RENAME_CENTER_PROFILE.outbox_event_type is not None
    OutboxWriter(uow.session, policy).enqueue(
        OutboxMessage(
            aggregate_type="center_profile",
            aggregate_id=command.profile_id,
            # Captured here, inside the transaction. Read after the commit it
            # would be whatever a later writer left behind.
            aggregate_version=new_version,
            event_type=RENAME_CENTER_PROFILE.outbox_event_type,
            payload={"profile_id": str(command.profile_id), "name": name},
            payload_version=PAYLOAD_VERSION,
            correlation_id=context.correlation_id,
            causation_id=context.causation_id,
        )
    )

    response: dict[str, Any] = {
        "profile_id": str(command.profile_id),
        "name": name,
        "record_version": new_version,
    }
    resolver.complete(
        claim,
        response_code=200,
        response_body=response,
        resource_type="center_profile",
        resource_id=command.profile_id,
    )

    return RenameResult(
        profile_id=command.profile_id, name=name, record_version=new_version, replayed=False
    )
