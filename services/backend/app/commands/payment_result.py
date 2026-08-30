"""Confirming a payment result, and the seven things that must be true first.

M9 slices 3 and 4, together. `05_API_Specification.md` §17.2-17.3,
`15_Agent_Implementation_Plan.md` §17.4-17.5, `04_Database_Schema.md` §11.3.

**The two slices ship as one command because the catalogue says they are one command.**
`command_catalog.yaml`'s `payment_attempt.confirm_paid` row gives it
`concurrency: if_match_attempt_and_lock_request_aggregate` and lists `no_overpayment` among its
preconditions. The M9 plan put the aggregate recalculation in a later slice; building this one
without it would ship a command that knowingly fails its own approved contract — the request would
stay `sent_to_bank` after every attempt was paid, and an overpayment would be accepted. The plan's
slice boundary was wrong about where a command ends, and the catalogue row is the evidence.

**Both rows are marked blocked, and both blockers are resolved here rather than ignored.**
`confirm_paid` carries `status: blocked_by_result_persistence_and_evidence_policy` and
`confirm_failed` `blocked_by_result_persistence_contract`. *Result persistence* was M6 creating
`bank_tracking_number`, `bank_result_at`, `failure_code`, `failure_reason`,
`confirmed_by_admin_user_id` and `confirmed_at` and granting the runtime nothing on them —
`20260830_0030` is that half. *Evidence policy* is the plan's G-3: doc 05 `:1580` says a reason
"may be required by policy" when no evidence exists and no approved document states the policy, so
a reason is **required** whenever no link is supplied. Strictly weaker than requiring approval,
strictly stronger than requiring nothing, and reversible in one edit. The owner still owes the
decision on whether an evidence-free confirmation needs a second person.

**§17 `:1131`'s seven validations, each with its own provocation.** They are not interchangeable
checks and a single test of "it refused" would leave six unproved:

    attempt was sent                    -> a `created` attempt is refused
    not cancelled or superseded         -> each refused separately
    amount is exact                     -> there is no amount field to disagree with
    evidence or approved exception      -> a link must be active and point here
    no duplicate conflict remains       -> one tracking number, one attempt
    paid sum does not exceed requested  -> a task is opened and the confirmation refused
    permission, version, idempotency    -> If-Match, the key, and the guard

**"Amount is exact" is enforced by an absence.** Neither request body carries an amount, so there
is no number a client could supply that disagrees with the attempt's own `amount_irr`. That is
stronger than validating one, and `SVC-CONFIRM-003` asserts the absence over the request models
rather than testing a value.

Covers: SVC-CONFIRM-001, SVC-CONFIRM-002, SVC-CONFIRM-003, SVC-CONFIRM-004, SVC-CONFIRM-005,
SVC-CONFIRM-006, SVC-AGGREGATE-001, SVC-AGGREGATE-002, AUD-CONFIRM-001.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.outbox import OutboxMessage, OutboxWriter
from app.audit.redaction import RedactionPolicy
from app.audit.registry import CONFIRM_ATTEMPT_FAILED, CONFIRM_ATTEMPT_PAID
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.commands.manual_review_task import OpenTask, open_task
from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.db.concurrency import compare_and_swap
from app.db.locking import LockScope, LockTarget, lock_rows
from app.db.models.confirmed_evidence_link import LINK_ACTIVE, ConfirmedEvidenceLink
from app.db.models.manual_review_task import (
    ENTITY_PAYMENT_ATTEMPT,
    TASK_TYPE_RESULT_DISCREPANCY,
)
from app.db.models.payment_batch import PaymentAttempt
from app.db.models.payment_request import PaymentRequest
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.idempotency import IdempotencyResolver

METADATA_SCHEMA = "audit.payment_result"
METADATA_VERSION = 1

CONFIRM_PAID_OPERATION = "payment_attempt.confirm_paid"
CONFIRM_FAILED_OPERATION = "payment_attempt.confirm_failed"

ATTEMPT_PAID = "paid"
ATTEMPT_FAILED = "failed"

# `attempt_was_sent`, the precondition both catalogue rows name. `bank_result_pending` is included
# because §11.3's status list puts it *after* `sent_to_bank`: a bank has been told, and a result is
# what is being waited for. Confirming from either is confirming a result for something that left.
CONFIRMABLE_FROM: tuple[str, ...] = ("sent_to_bank", "bank_result_pending")

# The two §17 `:1131` names explicitly, separated from the rest so each gets its own refusal and
# its own test. A superseded attempt was retired by a replacement; a cancelled one never went.
RETIRED_STATUSES: tuple[str, ...] = ("superseded", "cancelled")

REQUEST_PAID = "paid"
REQUEST_PARTIALLY_PAID = "partially_paid"


class OverpaymentRefused(BusinessRuleViolationError):
    """Raised when confirming would take the paid sum above the requested amount.

    **Its own type so the route can commit the reconciliation task before re-raising.** The task
    is the whole point of the refusal — `04_Database_Schema.md:1606` requires it — and a refusal
    that rolls back its own record leaves nobody asked to look at the discrepancy.

    The first version of this command raised a plain `BusinessRuleViolationError` and the task was
    discarded with the failed request, which the overpayment test caught. M7's download route
    learned the same lesson about quarantine and its comment says it in one line: on a failure
    path whose whole point is the record, the record commits.
    """


@dataclass(frozen=True, slots=True)
class ConfirmPaid:
    """§17.2's body. **No amount field**, and that is the enforcement of "amount is exact"."""

    payment_attempt_id: uuid.UUID
    expected_record_version: int
    bank_tracking_number: str
    bank_result_at: datetime
    confirmed_by_admin_user_id: uuid.UUID
    primary_evidence_link_id: uuid.UUID | None = None
    evidence_unavailable_reason: str | None = None
    confirmation_note: str | None = None


@dataclass(frozen=True, slots=True)
class ConfirmFailed:
    """§17.3's body."""

    payment_attempt_id: uuid.UUID
    expected_record_version: int
    failure_code: str
    failure_reason: str
    confirmed_by_admin_user_id: uuid.UUID
    receipt_segment_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class ResultConfirmation:
    attempt: PaymentAttempt
    request_status: str
    replayed: bool = False


def confirm_paid(
    command: ConfirmPaid,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> ResultConfirmation:
    """The first command in this project that records money as having moved."""

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=CONFIRM_PAID_OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "payment_attempt_id": str(command.payment_attempt_id),
            "bank_tracking_number": command.bank_tracking_number,
        },
    )

    session = uow.session

    if claim.is_replay:
        attempt, request = _replayed(session, claim)
        return ResultConfirmation(
            attempt=attempt, request_status=request.status, replayed=True
        )

    attempt = _locked_attempt(session, command.payment_attempt_id)
    request = _locked_request(session, attempt.payment_request_id)

    _refuse_unless_sent(attempt)
    _refuse_evidence_that_does_not_point_here(session, command, attempt)
    _refuse_a_duplicate_tracking_number(session, command, attempt)

    # `no_overpayment`, the third catalogue precondition. Computed under the request lock taken
    # above, which is what `if_match_attempt_and_lock_request_aggregate` asks for — two
    # confirmations racing must not both read a pre-payment sum.
    already_paid = _paid_sum(session, request.id)
    requested = _requested_amount(session, request)
    if already_paid + attempt.amount_irr > requested:
        _open_a_reconciliation_task(
            session,
            policy,
            request=request,
            attempt=attempt,
            already_paid=already_paid,
            requested=requested,
            actor=actor,
            context=context,
            now=now,
        )
        raise OverpaymentRefused(
            f"confirming {attempt.amount_irr} would bring the paid total for request "
            f"{request.request_number} to {already_paid + attempt.amount_irr}, above the "
            f"requested {requested}. `04_Database_Schema.md:961` calls this a reconciliation "
            "error and never a normal paid; a review task has been opened."
        )

    compare_and_swap(
        session,
        PaymentAttempt,
        entity_id=attempt.id,
        expected_version=command.expected_record_version,
        values={
            "status": ATTEMPT_PAID,
            "bank_tracking_number": command.bank_tracking_number,
            "bank_result_at": command.bank_result_at,
            "confirmed_by_admin_user_id": command.confirmed_by_admin_user_id,
            "confirmed_at": now,
        },
    )
    uow.flush()
    session.refresh(attempt)

    request_status = _recalculate(session, request, requested=requested)

    _audit(
        session,
        policy,
        names=CONFIRM_ATTEMPT_PAID,
        attempt=attempt,
        request=request,
        previous_status=CONFIRMABLE_FROM[0],
        reason=command.confirmation_note or command.evidence_unavailable_reason,
        actor=actor,
        context=context,
        now=now,
        extra={
            "bank_tracking_number": command.bank_tracking_number,
            "primary_evidence_link_id": (
                str(command.primary_evidence_link_id)
                if command.primary_evidence_link_id
                else None
            ),
            "evidence_unavailable_reason": command.evidence_unavailable_reason,
            "request_status": request_status,
        },
    )

    OutboxWriter(session, policy).enqueue(
        OutboxMessage(
            aggregate_type="payment_attempt",
            aggregate_id=attempt.id,
            aggregate_version=attempt.record_version,
            event_type=str(CONFIRM_ATTEMPT_PAID.outbox_event_type),
            payload={
                "payment_attempt_id": str(attempt.id),
                "payment_request_id": str(request.id),
                "amount_irr": str(attempt.amount_irr),
                "bank_tracking_number": command.bank_tracking_number,
                "request_status": request_status,
            },
            payload_version=1,
            headers={},
        )
    )

    resolver.complete(
        claim,
        response_code=200,
        response_body={"attempt_id": str(attempt.id), "request_id": str(request.id)},
        resource_type="payment_attempt",
        resource_id=attempt.id,
        now=now,
    )
    return ResultConfirmation(attempt=attempt, request_status=request_status)


def confirm_failed(
    command: ConfirmFailed,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> ResultConfirmation:
    """§17.3. A failure is recorded with its reason, and no money is claimed to have moved.

    **`failure_reason_recorded` is the catalogue's precondition** and it is required rather than
    optional: a failed attempt whose reason is empty is one nobody can act on, and the retry
    decision slice 3B builds is made from exactly this field.

    The request aggregate is recalculated here too — a failure changes no paid sum, but it can
    move a request that was `partially_paid` nowhere and must not silently leave a stale status
    behind. The recalculation is the same function, which is why it cannot drift between the two.
    """

    if not command.failure_reason.strip():
        raise BusinessRuleViolationError(
            "a failed confirmation requires a reason; `command_catalog.yaml` gives this command "
            "`failure_reason_recorded` and `05_API_Specification.md:1600` shows it in the body"
        )

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=CONFIRM_FAILED_OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "payment_attempt_id": str(command.payment_attempt_id),
            "failure_code": command.failure_code,
        },
    )

    session = uow.session

    if claim.is_replay:
        attempt, request = _replayed(session, claim)
        return ResultConfirmation(
            attempt=attempt, request_status=request.status, replayed=True
        )

    attempt = _locked_attempt(session, command.payment_attempt_id)
    request = _locked_request(session, attempt.payment_request_id)

    _refuse_unless_sent(attempt)

    compare_and_swap(
        session,
        PaymentAttempt,
        entity_id=attempt.id,
        expected_version=command.expected_record_version,
        values={
            "status": ATTEMPT_FAILED,
            "failure_code": command.failure_code,
            "failure_reason": command.failure_reason,
            "confirmed_by_admin_user_id": command.confirmed_by_admin_user_id,
            "confirmed_at": now,
        },
    )
    uow.flush()
    session.refresh(attempt)

    request_status = _recalculate(
        session, request, requested=_requested_amount(session, request)
    )

    _audit(
        session,
        policy,
        names=CONFIRM_ATTEMPT_FAILED,
        attempt=attempt,
        request=request,
        previous_status=CONFIRMABLE_FROM[0],
        reason=command.failure_reason,
        actor=actor,
        context=context,
        now=now,
        extra={"failure_code": command.failure_code, "request_status": request_status},
    )

    OutboxWriter(session, policy).enqueue(
        OutboxMessage(
            aggregate_type="payment_attempt",
            aggregate_id=attempt.id,
            aggregate_version=attempt.record_version,
            event_type=str(CONFIRM_ATTEMPT_FAILED.outbox_event_type),
            payload={
                "payment_attempt_id": str(attempt.id),
                "payment_request_id": str(request.id),
                "failure_code": command.failure_code,
                "request_status": request_status,
            },
            payload_version=1,
            headers={},
        )
    )

    resolver.complete(
        claim,
        response_code=200,
        response_body={"attempt_id": str(attempt.id), "request_id": str(request.id)},
        resource_type="payment_attempt",
        resource_id=attempt.id,
        now=now,
    )
    return ResultConfirmation(attempt=attempt, request_status=request_status)


def _locked_attempt(session: Session, attempt_id: uuid.UUID) -> PaymentAttempt:
    lock_rows(
        session,
        [LockTarget.of(LockScope.PAYMENT_ATTEMPT_CONFIRM, PaymentAttempt, attempt_id)],
        models={PaymentAttempt.__tablename__: PaymentAttempt},
    )
    attempt = session.get(PaymentAttempt, attempt_id)
    if attempt is None:
        raise NotFoundError()
    return attempt


def _locked_request(session: Session, request_id: uuid.UUID) -> PaymentRequest:
    """`REQUEST_PAID_TOTAL` is M2's scope for exactly this, and it sorts *before* the attempt.

    `lock_rows` orders by scope, so taking them in two calls is safe only because the request's
    scope number is lower — 250 against 550 — which is the ordering M2 chose when it wrote
    "request, then batch, then export, then payment". Two calls rather than one because the
    attempt has to be read before its request id is known.
    """

    lock_rows(
        session,
        [LockTarget.of(LockScope.REQUEST_PAID_TOTAL, PaymentRequest, request_id)],
        models={PaymentRequest.__tablename__: PaymentRequest},
    )
    request = session.get(PaymentRequest, request_id)
    if request is None:  # pragma: no cover - the foreign key guarantees it
        raise NotFoundError()
    return request


def _refuse_unless_sent(attempt: PaymentAttempt) -> None:
    """`SVC-CONFIRM-001` and `SVC-CONFIRM-002`.

    **One refusal and two messages, which is not what this docstring first claimed.** It said
    "two checks rather than one", and a negative control disproved it: removing the retired branch
    changed nothing, because `cancelled` and `superseded` are not in `CONFIRMABLE_FROM` either and
    the second branch catches them anyway.

    So the first branch exists for the *message*, and that is worth keeping rather than deleting.
    A reader told "only sent_to_bank may be confirmed" about a superseded attempt will go looking
    for a way to send it; told that a replacement already decided what happens to this money, they
    go and look at the replacement. `SVC-CONFIRM-002` asserts the distinctive wording, which is
    what makes the branch provable rather than decorative.
    """

    if attempt.status in RETIRED_STATUSES:
        raise BusinessRuleViolationError(
            f"attempt {attempt.attempt_number} is {attempt.status} and cannot be confirmed. "
            "§17 `:1131` refuses a retired attempt: a replacement or a cancellation already "
            "decided what happens to this money."
        )
    if attempt.status not in CONFIRMABLE_FROM:
        raise BusinessRuleViolationError(
            f"attempt {attempt.attempt_number} is {attempt.status}; only "
            f"{', '.join(CONFIRMABLE_FROM)} may be confirmed. §17 `:1131` requires that the "
            "attempt was sent, because confirming one that never left claims a bank did "
            "something it was never asked to do."
        )


def _refuse_evidence_that_does_not_point_here(
    session: Session, command: ConfirmPaid, attempt: PaymentAttempt
) -> None:
    """`SVC-CONFIRM-004`. `evidence_policy_satisfied`, and the plan's G-3.

    Doc 05 `:1580`: "evidence link must be active and point to the same attempt", and "when no
    evidence exists, a reason may be required by policy". No approved document states the policy,
    so the reason is **required** — the reversible middle, recorded rather than presented as the
    document's rule. The owner owes a decision on whether an evidence-free confirmation needs a
    second person, and this field is what such a flow would attach to.
    """

    if command.primary_evidence_link_id is None:
        if not (command.evidence_unavailable_reason or "").strip():
            raise BusinessRuleViolationError(
                "confirming paid with no evidence link requires a reason. "
                "`05_API_Specification.md:1580` requires one 'by policy' and no approved document "
                "states the policy, so it is required in every evidence-free case rather than in "
                "a subset this implementation would have had to invent."
            )
        return

    link = session.get(ConfirmedEvidenceLink, command.primary_evidence_link_id)
    if link is None:
        raise NotFoundError()
    if link.status != LINK_ACTIVE:
        raise BusinessRuleViolationError(
            f"evidence link {link.id} is {link.status}; `05_API_Specification.md:1580` requires "
            "an active link"
        )
    if link.payment_attempt_id != attempt.id:
        raise BusinessRuleViolationError(
            "the evidence link points at a different attempt. `05_API_Specification.md:1580` "
            "requires it to point at the one being confirmed — otherwise a paid result cites "
            "evidence for somebody else's payment."
        )


def _refuse_a_duplicate_tracking_number(
    session: Session, command: ConfirmPaid, attempt: PaymentAttempt
) -> None:
    """`SVC-CONFIRM-005`. "No duplicate conflict remains" — two attempts, one bank transaction.

    §11.3's `idx_payment_attempts_match` exists for this comparison, and the failure it prevents
    is a real one: a bank result read twice, or a person confirming the same transfer against two
    split rows, doubles the paid sum and the overpayment check would then be the only thing left
    between that and a wrong `paid`.
    """

    clash = session.scalar(
        select(PaymentAttempt.id).where(
            PaymentAttempt.bank_tracking_number == command.bank_tracking_number,
            PaymentAttempt.status == ATTEMPT_PAID,
            PaymentAttempt.id != attempt.id,
        )
    )
    if clash is not None:
        raise BusinessRuleViolationError(
            f"bank tracking number {command.bank_tracking_number} is already confirmed paid "
            f"against attempt {clash}. One bank transaction pays one attempt; §17 `:1131` "
            "requires that no duplicate conflict remains."
        )


def _paid_sum(session: Session, request_id: uuid.UUID) -> int:
    """The authoritative paid total. `04_Database_Schema.md:961`.

    Computed from the attempts rather than cached on the request, because a cached total is a
    second copy of a financial fact and `:469` prohibits exactly that shape for balances.
    """

    total = session.scalar(
        select(func.coalesce(func.sum(PaymentAttempt.amount_irr), 0)).where(
            PaymentAttempt.payment_request_id == request_id,
            PaymentAttempt.status == ATTEMPT_PAID,
        )
    )
    return int(total or 0)


def _requested_amount(session: Session, request: PaymentRequest) -> int:
    """The request's own amount, from its current revision.

    Not from an attempt: an attempt may be a split of the request, so its `amount_irr` is a part
    rather than the whole, and comparing the paid sum against a part is how a partial payment
    reads as complete.
    """

    from app.db.models.payment_request import PaymentRequestRevision

    amount = session.scalar(
        select(PaymentRequestRevision.amount_irr).where(
            PaymentRequestRevision.id == request.current_revision_id
        )
    )
    if amount is None:  # pragma: no cover - the composite key guarantees a current revision
        raise NotFoundError()
    return int(amount)


def _recalculate(session: Session, request: PaymentRequest, *, requested: int) -> str:
    """`SVC-AGGREGATE-001`. §17 `:1141` and `04_Database_Schema.md:961`, in three lines.

        paid_sum == requested        -> paid
        0 < paid_sum < requested     -> partially_paid
        paid_sum > requested         -> refused before this point

    The third line never reaches here: `confirm_paid` opens a reconciliation task and raises
    before the attempt is written, so this function has no branch for it. A branch that cannot be
    reached is the defect this repository has found fifteen times, and leaving one here would be
    the sixteenth.
    """

    paid = _paid_sum(session, request.id)
    if paid == 0:
        return request.status
    request.status = REQUEST_PAID if paid == requested else REQUEST_PARTIALLY_PAID
    return request.status


def _open_a_reconciliation_task(
    session: Session,
    policy: RedactionPolicy,
    *,
    request: PaymentRequest,
    attempt: PaymentAttempt,
    already_paid: int,
    requested: int,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> None:
    """`SVC-AGGREGATE-002`. `04_Database_Schema.md:1606`: overpayment creates a task.

    **`payment_result_discrepancy` was already in M0's approved task-type list**, which is the
    plan's G-4 answered without inventing anything — the fourth time an approved list already
    contained what a later milestone needed. A `crop_failed`-shaped invention would have been
    refused by the column's own CHECK.

    **The task hangs off the attempt, not the request**, because `ENTITY_TYPES` has no
    `payment_request`. That is the approved list rather than a preference, and the attempt is the
    accurate subject anyway: it is the row whose confirmation was refused.

    **Priority 4**, between M7's quarantine at 5 and M8's failed crop at 3. An overpayment is
    money that does not reconcile and is more urgent than a re-renderable image, and less urgent
    than a file whose integrity failed on its way to a bank.

    The task is opened **and** the confirmation refused. A block with no task is a silent refusal
    nobody follows up; a task with no block is worse, because the money would be recorded as paid
    while somebody is asked to look into it.
    """

    open_task(
        OpenTask(
            task_type=TASK_TYPE_RESULT_DISCREPANCY,
            entity_type=ENTITY_PAYMENT_ATTEMPT,
            entity_id=attempt.id,
            title=(
                f"Overpayment on {request.request_number}: confirming attempt "
                f"{attempt.attempt_number} would total {already_paid + attempt.amount_irr} "
                f"against {requested} requested"
            ),
            priority=4,
        ),
        session=session,
        policy=policy,
        actor=actor,
        context=context,
        now=now,
    )


def _replayed(session: Session, claim: Any) -> tuple[PaymentAttempt, PaymentRequest]:
    stored = claim.record.response_body or {}
    attempt = session.get(PaymentAttempt, uuid.UUID(str(stored["attempt_id"])))
    request = session.get(PaymentRequest, uuid.UUID(str(stored["request_id"])))
    if attempt is None or request is None:  # pragma: no cover - the record made it
        raise NotFoundError()
    return attempt, request


def _audit(
    session: Session,
    policy: RedactionPolicy,
    *,
    names: Any,
    attempt: PaymentAttempt,
    request: PaymentRequest,
    previous_status: str,
    reason: str | None,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
    extra: dict[str, Any],
) -> None:
    """`AUD-CONFIRM-001`. The row records the attempt *and* what it did to the request.

    Both, because an investigator asking "when did this request become paid" would otherwise have
    to join every attempt's audit row against a status change nothing recorded.
    """

    new_values: dict[str, Any] = {
        "status": attempt.status,
        "payment_request_id": str(request.id),
        "amount_irr": str(attempt.amount_irr),
    }
    new_values.update({key: value for key, value in extra.items() if value is not None})

    AuditWriter(session, policy).record(
        AuditEntry(
            action=names.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="payment_attempt",
            entity_id=attempt.id,
            entity_record_version=attempt.record_version,
            previous_values={"status": previous_status},
            new_values=new_values,
            reason=reason,
            occurred_at=now,
            metadata={"operation": names.audit_action},
        ),
        actor=actor,
        context=context,
    )
