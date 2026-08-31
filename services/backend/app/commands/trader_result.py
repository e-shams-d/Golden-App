"""What a trader may do about a published result: agree with it, or say it is wrong. §20.5-20.6.

M9 slice 6. `05_API_Specification.md:1921` (acknowledge) and `:1942` (dispute),
`15_Agent_Implementation_Plan.md:1165` (the four trader actions),
`06_Workflows_and_State_Machines.md:602-604` (the three arrows).

**A dispute moves no money, and that is the whole slice.** Doc 05 `:1942` in its own words: "A
dispute creates a visible manual review task and does not automatically reverse bank facts." This
is slice 1's property at the far end of the milestone — there, accepting a candidate must not mark
an attempt paid; here, the customer saying "I did not receive this" must not unwind a bank
transfer. Both are cases where the human action looks as though it should move the money and must
not, and both are tested by reading the financial rows back and requiring them byte-identical.

The enforcement is not a branch. This module imports no attempt model, no publication write and no
recalculation, and `SVC-DISPUTE-001` asserts the financial rows are unchanged rather than trusting
that. A dispute writes exactly three things: two timestamps on the request, its status, and a row
in the review queue.

**The publication version is recorded on the task, not just mentioned.** §17 `:1185` requires that
"a dispute references the exact publication version". `manual_review_tasks.entity_record_version`
is where it goes — M8 slice 7 added that column for the privacy check and its comment already
anticipated other uses. `20260901_0032` adds `payment_result_publication` to the entity types so
the reference can name the publication rather than an attempt.

**A trader disputes what they were shown, which may not be current.** The version is read from the
*active* publication at the moment of the dispute, and `If-Match` on the request is what stops a
trader disputing a result that a correction replaced while they were reading it: publishing N+1
moves the request, so a dispute carrying the old version is refused.

**`reason_code` is required and not enumerated.** Doc 05 shows one value,
`beneficiary_did_not_receive`, and no catalogue names a set. A closed list invented here would
refuse a trader whose complaint does not fit one of the options somebody guessed — and this is the
only surface in the system whose user is a customer rather than staff, so the cost of that is a
phone call instead of a record. Required, bounded, stored on the task, and recorded in the M9 plan
as a list M0 owes. The same reversible middle as G-3.

Covers: SVC-DISPUTE-001, SVC-ACKNOWLEDGE-001, AUD-PUBLICATION-001.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import ACKNOWLEDGE_PUBLICATION, DISPUTE_PUBLICATION
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.commands.manual_review_task import OpenTask, open_task
from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.db.concurrency import compare_and_swap
from app.db.locking import LockScope, LockTarget, lock_rows
from app.db.models.manual_review_task import (
    ENTITY_PAYMENT_PUBLICATION,
    TASK_TYPE_RESULT_DISCREPANCY,
)
from app.db.models.payment_request import PaymentRequest
from app.db.models.payment_result_publication import (
    PUBLICATION_ACTIVE,
    PaymentResultPublication,
)
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.idempotency import IdempotencyResolver

METADATA_SCHEMA = "audit.trader_result"
METADATA_VERSION = 1

ACKNOWLEDGE_OPERATION = "payment_publication.acknowledge_own"
DISPUTE_OPERATION = "payment_publication.dispute_own"

# `06_Workflows_and_State_Machines.md:602-604`. Both arrows leave `result_published`, and the third
# — `trader_disputed --> result_published` — belongs to slice 7's correction, not to the trader.
RESPONDABLE_FROM: tuple[str, ...] = ("result_published",)

REQUEST_ACKNOWLEDGED = "trader_acknowledged"
REQUEST_DISPUTED = "trader_disputed"

# Between M8's failed crop at 3 and M9's overpayment at 4. A trader saying the money did not arrive
# is more urgent than an image that can be re-rendered and less urgent than a sum that does not
# reconcile — the latter is money the centre already knows is wrong, this is money it believes is
# right. `20260824_0025` constrains the column to 1..5.
DISPUTE_PRIORITY = 4


@dataclass(frozen=True, slots=True)
class AcknowledgeResult:
    """§20.5's body. It has none — agreeing needs no fields."""

    payment_request_id: uuid.UUID
    expected_record_version: int


@dataclass(frozen=True, slots=True)
class DisputeResult:
    """§20.6's body.

    `attachment_file_ids` is **absent**. Document 05 shows it, and accepting a file id here would
    let a trader attach a file this command never checks the ownership of — the IDOR case
    `14_Testing_QA_Acceptance.md:1274` names, arriving through a field that looks helpful. M4's
    upload path is where a trader's file gets an owner, and a later slice can link one through it.
    Recorded in the M9 plan rather than half-built.
    """

    payment_request_id: uuid.UUID
    expected_record_version: int
    reason_code: str
    description: str


@dataclass(frozen=True, slots=True)
class TraderResponse:
    request: PaymentRequest
    publication: PaymentResultPublication
    task_id: uuid.UUID | None = None
    replayed: bool = False


def acknowledge_result(
    command: AcknowledgeResult,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> TraderResponse:
    """§20.5. The trader agrees, and nothing about the money changes."""

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=ACKNOWLEDGE_OPERATION,
        idempotency_key=idempotency_key,
        payload={"payment_request_id": str(command.payment_request_id)},
    )

    session = uow.session
    if claim.is_replay:
        request, publication = _replayed(session, claim)
        return TraderResponse(request=request, publication=publication, replayed=True)

    request = _locked_request(session, command.payment_request_id)
    _refuse_unless_published(request)
    publication = _active_publication(session, request)

    compare_and_swap(
        session,
        PaymentRequest,
        entity_id=request.id,
        expected_version=command.expected_record_version,
        values={"status": REQUEST_ACKNOWLEDGED, "trader_acknowledged_at": now},
    )
    uow.flush()
    session.refresh(request)

    _audit(
        session,
        policy,
        names=ACKNOWLEDGE_PUBLICATION,
        request=request,
        publication=publication,
        reason=None,
        actor=actor,
        context=context,
        now=now,
        extra={},
    )

    resolver.complete(
        claim,
        response_code=200,
        response_body={
            "request_id": str(request.id),
            "publication_id": str(publication.id),
        },
        resource_type="payment_request",
        resource_id=request.id,
        now=now,
    )
    return TraderResponse(request=request, publication=publication)


def dispute_result(
    command: DisputeResult,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> TraderResponse:
    """§20.6. A queue item and a status, and **no bank fact touched**."""

    if not command.reason_code.strip():
        raise BusinessRuleViolationError(
            "a dispute requires a reason code; `05_API_Specification.md:1949` shows one in the "
            "body and a dispute nobody can categorise cannot be triaged"
        )
    if not command.description.strip():
        raise BusinessRuleViolationError(
            "a dispute requires a description. The person who picks this task up has only what "
            "the trader wrote to work from, and `manual_review_tasks.description` is where it goes."
        )

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=DISPUTE_OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "payment_request_id": str(command.payment_request_id),
            "reason_code": command.reason_code,
        },
    )

    session = uow.session
    if claim.is_replay:
        request, publication = _replayed(session, claim)
        return TraderResponse(request=request, publication=publication, replayed=True)

    request = _locked_request(session, command.payment_request_id)
    _refuse_unless_published(request)
    publication = _active_publication(session, request)

    compare_and_swap(
        session,
        PaymentRequest,
        entity_id=request.id,
        expected_version=command.expected_record_version,
        values={
            "status": REQUEST_DISPUTED,
            "trader_disputed_at": now,
            "trader_result_note": command.description,
        },
    )
    uow.flush()
    session.refresh(request)

    task = _open_a_dispute_task(
        session,
        policy,
        request=request,
        publication=publication,
        command=command,
        actor=actor,
        context=context,
        now=now,
    )

    _audit(
        session,
        policy,
        names=DISPUTE_PUBLICATION,
        request=request,
        publication=publication,
        reason=command.description,
        actor=actor,
        context=context,
        now=now,
        extra={"reason_code": command.reason_code, "review_task_id": str(task.id)},
    )

    resolver.complete(
        claim,
        response_code=200,
        response_body={
            "request_id": str(request.id),
            "publication_id": str(publication.id),
            "task_id": str(task.id),
        },
        resource_type="payment_request",
        resource_id=request.id,
        now=now,
    )
    return TraderResponse(request=request, publication=publication, task_id=task.id)


def _locked_request(session: Session, request_id: uuid.UUID) -> PaymentRequest:
    """`current_publication_identity_revalidated`, which is the catalogue's own concurrency note.

    The lock is on the request rather than on the publication because the publication is immutable
    — there is nothing to serialise against on that row. What can move underneath a trader is
    *which* publication is active, and that changes by the request's status, which this holds.
    """

    lock_rows(
        session,
        [LockTarget.of(LockScope.REQUEST_PAID_TOTAL, PaymentRequest, request_id)],
        models={PaymentRequest.__tablename__: PaymentRequest},
    )
    request = session.get(PaymentRequest, request_id)
    if request is None:
        raise NotFoundError()
    return request


def _refuse_unless_published(request: PaymentRequest) -> None:
    """`06_Workflows_and_State_Machines.md:602-603`. Both arrows leave `result_published`.

    A second acknowledgement is refused here rather than being made idempotent, and the difference
    matters: a replayed request — same `Idempotency-Key` — returns the first answer, while a
    genuinely new one against an already-acknowledged request is a caller who does not know what
    they are looking at.
    """

    if request.status not in RESPONDABLE_FROM:
        raise BusinessRuleViolationError(
            f"request {request.request_number} is {request.status}; a trader may respond only to "
            f"{', '.join(RESPONDABLE_FROM)}. `06_Workflows_and_State_Machines.md:602` draws both "
            "arrows from there — there is nothing to agree with or dispute until a result has "
            "been published."
        )


def _active_publication(
    session: Session, request: PaymentRequest
) -> PaymentResultPublication:
    """The version the trader is responding to.

    Read under the request lock, so the version recorded on a dispute is the one that was active
    when the dispute was accepted. `uq_active_publication_per_request` guarantees there is at most
    one, which is why this returns a row rather than a list.
    """

    publication = session.scalar(
        select(PaymentResultPublication).where(
            PaymentResultPublication.payment_request_id == request.id,
            PaymentResultPublication.status == PUBLICATION_ACTIVE,
        )
    )
    if publication is None:  # pragma: no cover - `result_published` implies one exists
        raise NotFoundError()
    return publication


def _open_a_dispute_task(
    session: Session,
    policy: RedactionPolicy,
    *,
    request: PaymentRequest,
    publication: PaymentResultPublication,
    command: DisputeResult,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> Any:
    """§20.6: "A dispute creates a visible manual review task."

    **`payment_result_discrepancy`, the fifth value named from M0's approved list rather than
    added to it.** A trader saying the beneficiary did not receive the money is a disagreement
    between the recorded result and reality, which is what that type describes — the accurate
    type as well as the permitted one, which is the test M8 slice 4 set for this decision.

    **The entity is the publication and `entity_record_version` is its version.** That is §17
    `:1185`'s "references the exact publication version", stored in a column rather than written
    into prose where nothing could query it.
    """

    return open_task(
        OpenTask(
            task_type=TASK_TYPE_RESULT_DISCREPANCY,
            entity_type=ENTITY_PAYMENT_PUBLICATION,
            entity_id=publication.id,
            entity_record_version=publication.publication_version,
            title=(
                f"Trader dispute on {request.request_number}: {command.reason_code} "
                f"(publication v{publication.publication_version})"
            ),
            description=command.description,
            priority=DISPUTE_PRIORITY,
        ),
        session=session,
        policy=policy,
        actor=actor,
        context=context,
        now=now,
    )


def _replayed(
    session: Session, claim: Any
) -> tuple[PaymentRequest, PaymentResultPublication]:
    stored = claim.record.response_body or {}
    request = session.get(PaymentRequest, uuid.UUID(str(stored["request_id"])))
    publication = session.get(
        PaymentResultPublication, uuid.UUID(str(stored["publication_id"]))
    )
    if request is None or publication is None:  # pragma: no cover - the record made it
        raise NotFoundError()
    return request, publication


def _audit(
    session: Session,
    policy: RedactionPolicy,
    *,
    names: Any,
    request: PaymentRequest,
    publication: PaymentResultPublication,
    reason: str | None,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
    extra: dict[str, Any],
) -> None:
    """`AUD-PUBLICATION-001`. Both actions catalogued, neither with an outbox event.

    `audit_outbox_catalog.yaml:48-49` names `payment_publication.acknowledged` and `.disputed` and
    lists no event for either — correctly: nothing outside the platform acts on a trader's opinion
    of a result. The dispute's consumer is a person, and the review task is how they hear about it.

    The entity is the **request**, because that is the row whose status moved, and the publication
    id and version travel in `new_values` so an investigator can tell which version was disputed
    without joining through the queue.
    """

    new_values: dict[str, Any] = {
        "status": request.status,
        "publication_id": str(publication.id),
        "publication_version": publication.publication_version,
    }
    new_values.update(extra)

    AuditWriter(session, policy).record(
        AuditEntry(
            action=names.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="payment_request",
            entity_id=request.id,
            entity_record_version=request.record_version,
            previous_values={"status": RESPONDABLE_FROM[0]},
            new_values=new_values,
            reason=reason,
            occurred_at=now,
            metadata={"operation": names.audit_action},
        ),
        actor=actor,
        context=context,
    )
