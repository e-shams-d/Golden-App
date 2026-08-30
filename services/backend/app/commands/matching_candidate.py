"""Proposing a link, accepting it, and refusing it — none of which decides anything financial.

M9 slice 1. `05_API_Specification.md` §19.4-19.6, `04_Database_Schema.md` §12.5,
`06_Workflows_and_State_Machines.md` §21.

**The negative property is the whole slice.** §12.5 at `:1274`: "Accepting a candidate does not
itself set an attempt to paid; a human confirmation command creates/activates the confirmed link
and updates the attempt in one transaction." `15_Agent_Implementation_Plan.md:1102` says it again.
`command_catalog.yaml:296` says it a third time, as two preconditions on the acceptance row —
`does_not_confirm_evidence` and `does_not_confirm_payment`.

Three documents guarding one rule means the rule is easy to break by accident, and it is: the
reviewer accepting a candidate has just decided the receipt *is* the payment, so marking the
attempt paid there feels like finishing the job. It is not, because a candidate carries no bank
tracking number, no result timestamp and no confirming actor — the three things a paid attempt
must record. Acceptance opens the context; slice 3's command closes it.

**Nothing in this module can write a `payment_attempts` row even if it tried.** `20260829_0028`
grants the runtime no privilege on that table, so the property is enforced by PostgreSQL rather
than by this docstring. That is what `SEC-CANDIDATE-001` reads back.

**Two places this module was stricter than the documents, and both were corrected.**

`accepted_for_confirmation` is not terminal: `05_API_Specification.md:1816` requires a reason when
"overriding a previously accepted candidate", which only means something if acceptance can be
undone. And §21.2's staleness rules are not scoped to `proposed`.

**A rejection always requires a reason, and that one is deliberately stricter.** `:1816` names two
cases — a high-confidence candidate, and an override. The second is exactly definable; the first
is not, because **no approved document gives a confidence threshold**. Implementing "sometimes"
would mean inventing the boundary and letting a number nobody approved decide whether a refusal is
accepted. Requiring the reason always needs no invented value, costs the reviewer a sentence, and
narrows in one edit once the owner sets a threshold. Recorded as a deviation toward strictness
rather than presented as the document's rule.

Covers: SVC-CANDIDATE-001, SVC-CANDIDATE-002, AUD-CANDIDATE-001.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import (
    ACCEPT_MATCHING_CANDIDATE,
    CREATE_MATCHING_CANDIDATE,
    REJECT_MATCHING_CANDIDATE,
)
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.core.errors import BusinessRuleViolationError, ConflictError, NotFoundError
from app.db.locking import LockScope, LockTarget, lock_rows
from app.db.models.matching_candidate import (
    CANDIDATE_ACCEPTED,
    CANDIDATE_PROPOSED,
    CANDIDATE_REJECTED,
    PERMITTED_TRANSITIONS,
    MatchingCandidate,
)
from app.db.models.payment_batch import PaymentAttempt
from app.db.models.receipt_segment import (
    SEGMENT_CREATED,
    SEGMENT_UNMATCHED,
    ReceiptSegment,
)
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.idempotency import IdempotencyResolver

METADATA_SCHEMA = "audit.matching_candidate"
METADATA_VERSION = 1

PROPOSE_OPERATION = "matching_candidate.create"
ACCEPT_OPERATION = "matching_candidate.accept_for_confirmation"
REJECT_OPERATION = "matching_candidate.reject"

# `06_Workflows_and_State_Machines.md:1061-1062` draws both arrows into `candidate_found`:
# `created --> candidate_found: candidate(s) exist` and
# `unmatched --> candidate_found: candidate later found`. No other segment status gains one, so a
# segment already `confirmed_linked` or `voided` keeps its status when a candidate is proposed
# against it — the suggestion is recorded and the segment's summary is not rewritten.
SEGMENT_GAINS_A_CANDIDATE_FROM: tuple[str, ...] = (SEGMENT_CREATED, SEGMENT_UNMATCHED)
SEGMENT_CANDIDATE_FOUND = "candidate_found"


@dataclass(frozen=True, slots=True)
class ProposeCandidate:
    """§19.4. A suggestion that this segment might be evidence for this attempt."""

    receipt_segment_id: uuid.UUID
    payment_attempt_id: uuid.UUID
    method: str
    score: Decimal | None = None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DecideCandidate:
    """§19.5 and §19.6. One shape for both decisions, because they differ only in the target."""

    matching_candidate_id: uuid.UUID
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateResult:
    candidate: MatchingCandidate
    replayed: bool = False


def propose_candidate(
    command: ProposeCandidate,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> CandidateResult:
    """`SVC-CANDIDATE-001`'s subject: a row that suggests, and changes no financial fact.

    **Both sides are read, and neither is written.** The segment and the attempt are loaded to
    prove they exist — a foreign key would catch a missing one, but as a 500 rather than a 404 —
    and the attempt is then used for nothing else. It is not locked, not updated, and not read for
    its status: a suggestion about an attempt in any state is still a suggestion.

    **The segment's status may move, and that is documented rather than convenient.**
    `06_Workflows_and_State_Machines.md:1061-1062` draws `created --> candidate_found` and
    `unmatched --> candidate_found`. Any other status is left exactly as it is.

    **Idempotency is required although no catalogue row asks for it.** `command_catalog.yaml` has
    no row for this command at all — see `_CANDIDATE_DECISION_REASON` in the audit registry — so
    the contract is inferred from its neighbours, every one of which carries
    `idempotency: required`. Without it a retried proposal is refused by
    `uq_candidate_segment_attempt_method` as a conflict, which tells a client that somebody else
    proposed this when in fact they did it themselves.
    """

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=PROPOSE_OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "receipt_segment_id": str(command.receipt_segment_id),
            "payment_attempt_id": str(command.payment_attempt_id),
            "method": command.method,
        },
    )

    session = uow.session

    if claim.is_replay:
        stored = claim.record.response_body or {}
        candidate = session.get(MatchingCandidate, uuid.UUID(str(stored["candidate_id"])))
        if candidate is None:  # pragma: no cover - the record made it
            raise NotFoundError()
        return CandidateResult(candidate=candidate, replayed=True)

    segment = session.get(ReceiptSegment, command.receipt_segment_id)
    if segment is None:
        raise NotFoundError()

    attempt = session.get(PaymentAttempt, command.payment_attempt_id)
    if attempt is None:
        raise NotFoundError()

    existing = session.scalar(
        select(MatchingCandidate).where(
            MatchingCandidate.receipt_segment_id == command.receipt_segment_id,
            MatchingCandidate.payment_attempt_id == command.payment_attempt_id,
            MatchingCandidate.method == command.method,
        )
    )
    if existing is not None:
        raise ConflictError(
            f"a {command.method} candidate already links this segment and attempt; "
            "§12.5's unique is on the pair and the method together"
        )

    candidate = MatchingCandidate(
        receipt_segment_id=command.receipt_segment_id,
        payment_attempt_id=command.payment_attempt_id,
        method=command.method,
        score=command.score,
        reasons=list(command.reasons),
        status=CANDIDATE_PROPOSED,
        created_by_actor_type=actor.actor_type,
        created_by_actor_id=actor.actor_id,
        resolved_at=None,
    )
    session.add(candidate)
    uow.flush()

    if segment.status in SEGMENT_GAINS_A_CANDIDATE_FROM:
        segment.status = SEGMENT_CANDIDATE_FOUND

    _audit(
        session,
        policy,
        names=CREATE_MATCHING_CANDIDATE,
        candidate=candidate,
        previous_status=None,
        reason=None,
        actor=actor,
        context=context,
        now=now,
    )

    resolver.complete(
        claim,
        response_code=201,
        response_body={"candidate_id": str(candidate.id)},
        resource_type="matching_candidate",
        resource_id=candidate.id,
        now=now,
    )

    return CandidateResult(candidate=candidate)


def accept_candidate(
    command: DecideCandidate,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> CandidateResult:
    """§19.5, and the one line the whole milestone rests on: "This does not mark an attempt paid".

    **What this function does not do is the point.** It does not load the attempt, does not read
    its status, and writes nothing to it — and it could not if it tried, because the migration
    grants the runtime nothing on that table. `SVC-CANDIDATE-001` reads the attempt's entire row
    through `row_to_json` before and after and asserts byte equality, which is the only assertion
    that covers `status`, `confirmed_at` and `confirmed_by_admin_user_id` at once.

    It also creates no evidence link. `command_catalog.yaml:296` names both prohibitions —
    `does_not_confirm_evidence` and `does_not_confirm_payment` — and slice 2's table does not
    exist yet, which makes the first one structural for now and a real assertion afterwards.
    """

    return _decide(
        command,
        target=CANDIDATE_ACCEPTED,
        operation=ACCEPT_OPERATION,
        names=ACCEPT_MATCHING_CANDIDATE,
        reason_required=False,
        uow=uow,
        policy=policy,
        actor=actor,
        context=context,
        idempotency_key=idempotency_key,
        now=now,
    )


def reject_candidate(
    command: DecideCandidate,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> CandidateResult:
    """§19.6. A refusal, with a reason, retained.

    §21.2 requires that "candidate reasons, score, algorithm/provider version, and input snapshot
    are retained" — so a rejected candidate is never deleted. The row stays, its status moves, and
    the reason lives on the audit entry rather than on the table: §12.5 gives the table no reason
    column, and adding one would be inventing a field two catalogues do not describe.
    """

    return _decide(
        command,
        target=CANDIDATE_REJECTED,
        operation=REJECT_OPERATION,
        names=REJECT_MATCHING_CANDIDATE,
        reason_required=True,
        uow=uow,
        policy=policy,
        actor=actor,
        context=context,
        idempotency_key=idempotency_key,
        now=now,
    )


def _decide(
    command: DecideCandidate,
    *,
    target: str,
    operation: str,
    names: Any,
    reason_required: bool,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> CandidateResult:
    """Both decisions, because they differ only in the target status and the reason rule.

    **`candidate_version_revalidated` without a version column.** `command_catalog.yaml:295`
    requires it and §12.5 gives the table no `record_version`. The row is locked and its status
    re-read inside the transaction instead — for a row whose only mutable field is that status,
    that is the same guarantee, and it is the mechanism M2's `lock_rows` exists to provide.
    Adding a version column would be inventing one document 04 does not list.
    """

    if reason_required and not (command.reason or "").strip():
        raise BusinessRuleViolationError(
            "a rejection requires a reason. `05_API_Specification.md:1816` requires one for a "
            "high-confidence candidate or when overriding an acceptance, and no approved document "
            "gives a confidence threshold — so the reason is required for every rejection rather "
            "than for a boundary this implementation would have had to invent."
        )

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=operation,
        idempotency_key=idempotency_key,
        payload={
            "matching_candidate_id": str(command.matching_candidate_id),
            "reason": command.reason,
        },
    )

    session = uow.session

    if claim.is_replay:
        stored = claim.record.response_body or {}
        candidate = session.get(MatchingCandidate, uuid.UUID(str(stored["candidate_id"])))
        if candidate is None:  # pragma: no cover - the record made it
            raise NotFoundError()
        return CandidateResult(candidate=candidate, replayed=True)

    lock_rows(
        session,
        [
            LockTarget.of(
                LockScope.MATCHING_CANDIDATE_DECIDE,
                MatchingCandidate,
                command.matching_candidate_id,
            )
        ],
        models={MatchingCandidate.__tablename__: MatchingCandidate},
    )

    candidate = session.get(MatchingCandidate, command.matching_candidate_id)
    if candidate is None:
        raise NotFoundError()

    permitted = PERMITTED_TRANSITIONS.get(candidate.status, frozenset())
    if target not in permitted:
        raise BusinessRuleViolationError(
            f"a {candidate.status} candidate cannot become {target}; "
            f"{candidate.status} permits {', '.join(sorted(permitted)) or 'no transition'}"
        )

    previous_status = candidate.status
    candidate.status = target
    candidate.resolved_at = now
    uow.flush()

    _audit(
        session,
        policy,
        names=names,
        candidate=candidate,
        previous_status=previous_status,
        reason=command.reason,
        actor=actor,
        context=context,
        now=now,
    )

    resolver.complete(
        claim,
        response_code=200,
        response_body={"candidate_id": str(candidate.id)},
        resource_type="matching_candidate",
        resource_id=candidate.id,
        now=now,
    )

    return CandidateResult(candidate=candidate)


def _audit(
    session: Session,
    policy: RedactionPolicy,
    *,
    names: Any,
    candidate: MatchingCandidate,
    previous_status: str | None,
    reason: str | None,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> None:
    """`AUD-CANDIDATE-001`. One row per decision, naming both sides of the suggestion.

    **`entity_record_version` is absent, and that is not an oversight.** §12.5 gives this table no
    version column, so there is no number to record. Every other field the audit contract requires
    is present; inventing a version to fill a slot would make the row look like it tracked
    something it does not.
    """

    new_values: dict[str, Any] = {
        "status": candidate.status,
        "receipt_segment_id": str(candidate.receipt_segment_id),
        "payment_attempt_id": str(candidate.payment_attempt_id),
        "method": candidate.method,
    }
    if candidate.score is not None:
        # As text: `parameters_hash` refuses floats and an audit reader comparing two rows should
        # see the stored precision rather than a repr that depends on the JSON encoder.
        new_values["score"] = str(candidate.score)

    AuditWriter(session, policy).record(
        AuditEntry(
            action=names.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="matching_candidate",
            entity_id=candidate.id,
            previous_values=({"status": previous_status} if previous_status else {}),
            new_values=new_values,
            reason=reason,
            occurred_at=now,
            metadata={"operation": names.audit_action},
        ),
        actor=actor,
        context=context,
    )
