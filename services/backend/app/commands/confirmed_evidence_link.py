"""Confirming evidence, replacing it, and revoking it. `05_API_Specification.md` §19.7-19.9.

M9 slice 2. Three commands, and the properties worth stating are the ones the database enforces
rather than these functions.

**Cardinality is a partial unique index, not a check in this file.**
`command_catalog.yaml` asks for `lock_attempt_and_segment_enforce_primary_cardinality`, and both
halves are here: the rows are locked in the global order, *and* the two indexes
`20260830_0029` creates are what actually refuse a second active primary. A read-then-insert under
a lock would be correct too — but only for callers that take the same lock, and the index is
correct for every caller including a future worker and a psql session. `CON-EVIDENCE-001` runs two
connections at it.

**Replacement never deletes.** §12.6 at `:1306` and §22.3: the old row becomes `replaced` and the
new one is inserted in the same transaction, carrying `replaces_link_id` and the reason. The order
matters and is the opposite of the obvious one — the old row is retired *first*, because the
partial index refuses two active primaries and inserting before retiring would fail against the
constraint that exists to protect the invariant.

**Revoking a primary link is refused, and that is document 05's rule rather than caution.**
`:1857`'s heading is "Void **supplementary** link" and its body says primary links use the
replacement workflow "unless the entire result is formally revoked" — which is the correction
command M9's last slice builds, not this one. So a primary revocation here would be a path around
a workflow the specification routes elsewhere.

**The status stored is `revoked`; the route path is `/void`.** `status_catalog.yaml` makes
`revoked` canonical and `voided` a provisional alias, and `command_catalog.yaml`'s revoke row is
marked `blocked_by_voided_vs_revoked_status_conflict`. `20260830_0029`'s docstring records the
decision and what documents 04 and 05 are owed.

Covers: SVC-EVIDENCE-001, SVC-EVIDENCE-002, AUD-EVIDENCE-001.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.outbox import OutboxMessage, OutboxWriter
from app.audit.redaction import RedactionPolicy
from app.audit.registry import (
    CONFIRM_EVIDENCE_LINK,
    REPLACE_EVIDENCE_LINK,
    REVOKE_EVIDENCE_LINK,
)
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.core.errors import BusinessRuleViolationError, ConflictError, NotFoundError
from app.db.locking import LockScope, LockTarget, lock_rows
from app.db.models.confirmed_evidence_link import (
    LINK_ACTIVE,
    LINK_PRIMARY,
    LINK_REPLACED,
    LINK_REVOKED,
    LINK_SUPPLEMENTARY,
    LINK_TYPES,
    PERMITTED_TRANSITIONS,
    ConfirmedEvidenceLink,
)
from app.db.models.payment_batch import PaymentAttempt
from app.db.models.receipt_segment import ReceiptSegment
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.idempotency import IdempotencyResolver

METADATA_SCHEMA = "audit.confirmed_evidence_link"
METADATA_VERSION = 1

CONFIRM_OPERATION = "evidence_link.confirm"
REPLACE_OPERATION = "evidence_link.replace"
REVOKE_OPERATION = "evidence_link.revoke"

# `06_Workflows_and_State_Machines.md:1065`: `candidate_found --> confirmed_linked: candidate used
# in confirmation command`, and `:1063-1064` give the same arrow from `created` and `unmatched`.
# A segment already `confirmed_linked` or beyond keeps its status.
SEGMENT_BECOMES_LINKED_FROM: tuple[str, ...] = ("created", "unmatched", "candidate_found")
SEGMENT_CONFIRMED_LINKED = "confirmed_linked"


@dataclass(frozen=True, slots=True)
class ConfirmEvidenceLink:
    """§19.7's body."""

    payment_attempt_id: uuid.UUID
    receipt_segment_id: uuid.UUID
    link_type: str
    confirmed_by_admin_user_id: uuid.UUID
    confirmation_note: str | None = None


@dataclass(frozen=True, slots=True)
class ReplaceEvidenceLink:
    """§19.8's body. The reason is required by `command_catalog.yaml`'s `reason_required`."""

    link_id: uuid.UUID
    new_receipt_segment_id: uuid.UUID
    replacement_reason: str
    confirmed_by_admin_user_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class RevokeEvidenceLink:
    """§19.9's body. Reason required, and only a supplementary link may take it."""

    link_id: uuid.UUID
    reason: str


@dataclass(frozen=True, slots=True)
class LinkResult:
    link: ConfirmedEvidenceLink
    replayed: bool = False


def confirm_evidence_link(
    command: ConfirmEvidenceLink,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> LinkResult:
    """§19.7. A human decides that this segment is evidence for this attempt.

    **It does not mark the attempt paid.** Slice 1's negative applies here too and for the same
    reason: `20260829_0028` granted the runtime nothing on `payment_attempts`, and this slice adds
    no grant either. §17 `:1122`'s confirmation command is slice 3's, and it is the one that takes
    a bank tracking number and a result timestamp.

    **`link_type` is validated here rather than left to the CHECK**, because a bad value should be
    a 400 naming the two permitted kinds, not a 500 from a constraint the client cannot see.
    """

    if command.link_type not in LINK_TYPES:
        raise BusinessRuleViolationError(
            f"link_type must be one of {', '.join(LINK_TYPES)}; got {command.link_type!r}"
        )

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=CONFIRM_OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "payment_attempt_id": str(command.payment_attempt_id),
            "receipt_segment_id": str(command.receipt_segment_id),
            "link_type": command.link_type,
        },
    )

    session = uow.session

    if claim.is_replay:
        return LinkResult(link=_replayed(session, claim), replayed=True)

    _lock_attempt_and_segment(
        session, command.payment_attempt_id, command.receipt_segment_id
    )

    attempt = session.get(PaymentAttempt, command.payment_attempt_id)
    if attempt is None:
        raise NotFoundError()
    segment = session.get(ReceiptSegment, command.receipt_segment_id)
    if segment is None:
        raise NotFoundError()

    link = ConfirmedEvidenceLink(
        payment_attempt_id=command.payment_attempt_id,
        receipt_segment_id=command.receipt_segment_id,
        link_type=command.link_type,
        status=LINK_ACTIVE,
        confirmed_by_admin_user_id=command.confirmed_by_admin_user_id,
        confirmed_at=now,
        replaces_link_id=None,
        replacement_reason=None,
    )
    session.add(link)
    _flush_or_conflict(uow, command.link_type)

    if command.link_type == LINK_PRIMARY and segment.status in SEGMENT_BECOMES_LINKED_FROM:
        segment.status = SEGMENT_CONFIRMED_LINKED

    _audit(
        session,
        policy,
        names=CONFIRM_EVIDENCE_LINK,
        link=link,
        previous_status=None,
        reason=command.confirmation_note,
        actor=actor,
        context=context,
        now=now,
    )

    resolver.complete(
        claim,
        response_code=201,
        response_body={"link_id": str(link.id)},
        resource_type="confirmed_evidence_link",
        resource_id=link.id,
        now=now,
    )
    return LinkResult(link=link)


def replace_evidence_link(
    command: ReplaceEvidenceLink,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> LinkResult:
    """§19.8. The old link is retired and a new one takes its place, in one transaction.

    **Retire first, then insert — and the order is not stylistic.** The partial unique index
    permits one active primary per attempt, so inserting the replacement while the original is
    still `active` fails against the very constraint the invariant depends on. Doing it the other
    way round means the window in which neither is active exists only inside this transaction,
    which no other session can observe.

    **`SVC-EVIDENCE-001` is a failure injection**, not a happy path: force the insert to fail and
    the original must still be `active`. A replacement that retired the old row and then failed
    would leave an attempt with no primary evidence at all, and a passing happy-path test cannot
    see that ordering.
    """

    if not command.replacement_reason.strip():
        raise BusinessRuleViolationError(
            "a replacement requires a reason; `command_catalog.yaml` gives this command "
            "`reason_required` and §12.6 stores it on the new row"
        )

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=REPLACE_OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "link_id": str(command.link_id),
            "new_receipt_segment_id": str(command.new_receipt_segment_id),
            "replacement_reason": command.replacement_reason,
        },
    )

    session = uow.session

    if claim.is_replay:
        return LinkResult(link=_replayed(session, claim), replayed=True)

    original = session.get(ConfirmedEvidenceLink, command.link_id)
    if original is None:
        raise NotFoundError()

    # Locked after the first read, because the attempt id is on the row and the lock order needs
    # it. The status is re-read below, under the lock, before anything is written.
    _lock_attempt_and_segment(
        session,
        original.payment_attempt_id,
        command.new_receipt_segment_id,
        link_id=original.id,
    )
    session.refresh(original)

    _refuse_unless_transition_permitted(original, LINK_REPLACED)

    if session.get(ReceiptSegment, command.new_receipt_segment_id) is None:
        raise NotFoundError()

    original.status = LINK_REPLACED
    uow.flush()

    replacement = ConfirmedEvidenceLink(
        payment_attempt_id=original.payment_attempt_id,
        receipt_segment_id=command.new_receipt_segment_id,
        link_type=original.link_type,
        status=LINK_ACTIVE,
        confirmed_by_admin_user_id=command.confirmed_by_admin_user_id,
        confirmed_at=now,
        replaces_link_id=original.id,
        replacement_reason=command.replacement_reason,
    )
    session.add(replacement)
    _flush_or_conflict(uow, original.link_type)

    _audit(
        session,
        policy,
        names=REPLACE_EVIDENCE_LINK,
        link=replacement,
        previous_status=LINK_ACTIVE,
        reason=command.replacement_reason,
        actor=actor,
        context=context,
        now=now,
        replaces=original,
    )

    # `audit_outbox_catalog.yaml:76`. The only event in this slice, because replacement is where
    # evidence stops agreeing with whatever a trader was shown — `:1854` requires a corrected
    # publication and a notification when that happens, and both consume this.
    OutboxWriter(session, policy).enqueue(
        OutboxMessage(
            aggregate_type="confirmed_evidence_link",
            aggregate_id=replacement.id,
            aggregate_version=1,
            event_type=str(REPLACE_EVIDENCE_LINK.outbox_event_type),
            payload={
                "confirmed_evidence_link_id": str(replacement.id),
                "replaces_link_id": str(original.id),
                "payment_attempt_id": str(replacement.payment_attempt_id),
                "previous_receipt_segment_id": str(original.receipt_segment_id),
                "receipt_segment_id": str(replacement.receipt_segment_id),
                "link_type": replacement.link_type,
                "replacement_reason": command.replacement_reason,
            },
            payload_version=1,
            headers={},
        )
    )

    resolver.complete(
        claim,
        response_code=201,
        response_body={"link_id": str(replacement.id)},
        resource_type="confirmed_evidence_link",
        resource_id=replacement.id,
        now=now,
    )
    return LinkResult(link=replacement)


def revoke_evidence_link(
    command: RevokeEvidenceLink,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> LinkResult:
    """§19.9. A supplementary link is withdrawn, with a reason, and the row stays.

    **A primary link cannot be revoked here.** `:1857`: "Primary links use the
    replacement/correction workflow unless the entire result is formally revoked." That exception
    is the correction command M9's last slice builds; letting it through here would be a path
    around a workflow document 05 routes elsewhere, and it would leave an attempt with no primary
    evidence and no replacement — the state `SVC-EVIDENCE-001` exists to prevent.

    §22.3: "Revocation requires reason and cannot silently erase a previously published result."
    The reason is required below; the second half is slice 5's, and there is no publication table
    yet for a revocation to contradict.
    """

    if not command.reason.strip():
        raise BusinessRuleViolationError(
            "a revocation requires a reason; §22.3 says so and `command_catalog.yaml` gives this "
            "command `reason_required`"
        )

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=REVOKE_OPERATION,
        idempotency_key=idempotency_key,
        payload={"link_id": str(command.link_id), "reason": command.reason},
    )

    session = uow.session

    if claim.is_replay:
        return LinkResult(link=_replayed(session, claim), replayed=True)

    link = session.get(ConfirmedEvidenceLink, command.link_id)
    if link is None:
        raise NotFoundError()

    lock_rows(
        session,
        [LockTarget.of(LockScope.EVIDENCE_LINK_REPLACE, ConfirmedEvidenceLink, link.id)],
        models={ConfirmedEvidenceLink.__tablename__: ConfirmedEvidenceLink},
    )
    session.refresh(link)

    if link.link_type != LINK_SUPPLEMENTARY:
        raise BusinessRuleViolationError(
            f"a {link.link_type} link cannot be voided. `05_API_Specification.md:1857` routes "
            "primary evidence through the replacement workflow, and formal revocation of a whole "
            "result is the correction command rather than this one."
        )

    _refuse_unless_transition_permitted(link, LINK_REVOKED)

    previous_status = link.status
    link.status = LINK_REVOKED
    uow.flush()

    _audit(
        session,
        policy,
        names=REVOKE_EVIDENCE_LINK,
        link=link,
        previous_status=previous_status,
        reason=command.reason,
        actor=actor,
        context=context,
        now=now,
    )

    resolver.complete(
        claim,
        response_code=200,
        response_body={"link_id": str(link.id)},
        resource_type="confirmed_evidence_link",
        resource_id=link.id,
        now=now,
    )
    return LinkResult(link=link)


def _lock_attempt_and_segment(
    session: Session,
    attempt_id: uuid.UUID,
    segment_id: uuid.UUID,
    *,
    link_id: uuid.UUID | None = None,
) -> None:
    """`lock_attempt_and_segment_enforce_primary_cardinality`, the lock half.

    `lock_rows` sorts by `(scope, table, primary key)`, so two commands naming the same rows take
    them in the same order however the caller listed them — which is the whole reason the ordering
    lives there and not here.
    """

    targets = [
        LockTarget.of(LockScope.PAYMENT_ATTEMPT_CONFIRM, PaymentAttempt, attempt_id),
        LockTarget.of(LockScope.EVIDENCE_LINK_REPLACE, ReceiptSegment, segment_id),
    ]
    if link_id is not None:
        targets.append(
            LockTarget.of(LockScope.EVIDENCE_LINK_REPLACE, ConfirmedEvidenceLink, link_id)
        )

    lock_rows(
        session,
        targets,
        models={
            PaymentAttempt.__tablename__: PaymentAttempt,
            ReceiptSegment.__tablename__: ReceiptSegment,
            ConfirmedEvidenceLink.__tablename__: ConfirmedEvidenceLink,
        },
    )


def _flush_or_conflict(uow: SqlAlchemyUnitOfWork, link_type: str) -> None:
    """Turn the partial index's refusal into a sentence a caller can act on.

    Without this the response is a 500 from an `IntegrityError`, which tells an accountant nothing
    and tells an operator to look in the wrong place. The index is doing exactly its job; the
    message is what was missing.
    """

    try:
        uow.flush()
    except IntegrityError as exc:  # pragma: no cover - exercised by the live conflict tests
        raise ConflictError(
            f"an active {link_type} evidence link already exists for this attempt or segment. "
            "§12.6 permits one active primary per attempt and one active primary target per "
            "segment; replace the existing link rather than adding a second."
        ) from exc


def _refuse_unless_transition_permitted(link: ConfirmedEvidenceLink, target: str) -> None:
    permitted = PERMITTED_TRANSITIONS.get(link.status, frozenset())
    if target not in permitted:
        raise BusinessRuleViolationError(
            f"a {link.status} evidence link cannot become {target}; "
            f"{link.status} permits {', '.join(sorted(permitted)) or 'no transition'}"
        )


def _replayed(session: Session, claim: Any) -> ConfirmedEvidenceLink:
    stored = claim.record.response_body or {}
    link = session.get(ConfirmedEvidenceLink, uuid.UUID(str(stored["link_id"])))
    if link is None:  # pragma: no cover - the record made it
        raise NotFoundError()
    return link


def _audit(
    session: Session,
    policy: RedactionPolicy,
    *,
    names: Any,
    link: ConfirmedEvidenceLink,
    previous_status: str | None,
    reason: str | None,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
    replaces: ConfirmedEvidenceLink | None = None,
) -> None:
    """`AUD-EVIDENCE-001`. One row per decision, naming both sides and the chain.

    **The revocation reason lives here and nowhere else.** §22.3 requires one and §12.6 gives the
    table no column for it — slice 1 put a rejection's reason in the same place for the same
    reason. Inventing a column two catalogues do not describe is the drift this milestone opened
    by promising not to do.
    """

    new_values: dict[str, Any] = {
        "status": link.status,
        "link_type": link.link_type,
        "payment_attempt_id": str(link.payment_attempt_id),
        "receipt_segment_id": str(link.receipt_segment_id),
    }
    if replaces is not None:
        new_values["replaces_link_id"] = str(replaces.id)
        new_values["previous_receipt_segment_id"] = str(replaces.receipt_segment_id)

    AuditWriter(session, policy).record(
        AuditEntry(
            action=names.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="confirmed_evidence_link",
            entity_id=link.id,
            previous_values=({"status": previous_status} if previous_status else {}),
            new_values=new_values,
            reason=reason,
            occurred_at=now,
            metadata={"operation": names.audit_action},
        ),
        actor=actor,
        context=context,
    )
