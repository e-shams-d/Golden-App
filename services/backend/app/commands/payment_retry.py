"""Deciding a retry is needed, and creating one. `05_API_Specification.md` §17.4-17.5.

M9 slice 3B — **the slice the plan forgot**. §17 `:1121` names five payment-result commands; the
plan assigned two to slice 3 and one to slice 7 and never mentioned these, while
`permission_catalog.yaml` seeds `payment_attempt.create_retry` and
`audit_outbox_catalog.yaml:45` names `payment_attempt.retry_created`. An approved permission and a
catalogued action with no slice that builds them, found by re-reading the command list rather than
by any gate.

**Two commands, and the first must not do the second's work.** §17.4 in its own words: "Reason
required. This does not itself create or send a retry." That is the third time in this milestone
that the interesting property is what a command does *not* do — after acceptance not paying, and a
dispute not reversing. Marking retry-required records a decision; creating the attempt is a
separate act with a separate permission requirement and a separate audit row.

**They are a chain, which is why they are one slice.** `06_Workflows_and_State_Machines.md:682-684`
draws `bank_result_pending --> retry_required`, `failed --> retry_required`, and then
`retry_required --> superseded: replacement retry attempt created`. So the original must be marked
before it can be retried, and creating the retry retires the original in the same transaction.

**The beneficiary comes from the referenced revision, never from the request body.** §17.5: "The
server rejects free-form beneficiary/IBAN changes. Material beneficiary changes must exist in the
referenced request revision." Enforced the way slice 3 enforces "amount is exact" — there are no
beneficiary fields in the body to reject, so a caller cannot supply one. `SVC-RETRY-002` asserts
that absence over the request model.

**No overpayment check here, deliberately.** A retry attempt is created `unbatched` and unpaid, so
it moves no paid sum; the overpayment rule lives in `confirm_paid`, which is where money is
actually claimed. Adding a second check here would be a rule no document states and a branch that
duplicates one that already works.

Covers: SVC-RETRY-001, SVC-RETRY-002, AUD-RETRY-001.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import CREATE_RETRY_ATTEMPT, MARK_RETRY_REQUIRED
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.db.concurrency import compare_and_swap
from app.db.locking import LockScope, LockTarget, lock_rows
from app.db.models.payment_batch import PaymentAttempt
from app.db.models.payment_request import PaymentRequest, PaymentRequestRevision
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.idempotency import IdempotencyResolver

METADATA_SCHEMA = "audit.payment_retry"
METADATA_VERSION = 1

MARK_RETRY_OPERATION = "payment_attempt.mark_retry_required"
CREATE_RETRY_OPERATION = "payment_attempt.create_retry"

ATTEMPT_CREATED = "created"
ATTEMPT_RETRY_REQUIRED = "retry_required"
ATTEMPT_SUPERSEDED = "superseded"

# `06_Workflows_and_State_Machines.md:682-683`, both arrows into `retry_required` and no others.
# `paid` is deliberately absent: money that moved is not retried, it is corrected — which is
# slice 7's command.
RETRY_REQUIRABLE_FROM: tuple[str, ...] = ("failed", "bank_result_pending")

ATTEMPT_TYPE_RETRY = "retry"


@dataclass(frozen=True, slots=True)
class MarkRetryRequired:
    """§17.4's body. A reason, and nothing that could create anything."""

    payment_attempt_id: uuid.UUID
    expected_record_version: int
    reason: str


@dataclass(frozen=True, slots=True)
class CreateRetryAttempt:
    """§17.5's body. **No beneficiary fields** — see the module docstring."""

    payment_attempt_id: uuid.UUID
    expected_record_version: int
    payment_request_revision_id: uuid.UUID
    amount_irr: int
    reason: str


@dataclass(frozen=True, slots=True)
class RetryResult:
    attempt: PaymentAttempt
    replayed: bool = False


def mark_retry_required(
    command: MarkRetryRequired,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> RetryResult:
    """§17.4. "This does not itself create or send a retry."

    `SVC-RETRY-001` asserts it by counting the request's attempts before and after: the status
    moves and the count does not. A test of the status alone would pass against an implementation
    that helpfully created the retry too — which is the shortcut this command exists to refuse.
    """

    if not command.reason.strip():
        raise BusinessRuleViolationError(
            "marking an attempt as needing a retry requires a reason. "
            "`05_API_Specification.md:1612` says so, and the reason is what slice 7's correction "
            "and any later retry are decided from."
        )

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=MARK_RETRY_OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "payment_attempt_id": str(command.payment_attempt_id),
            "reason": command.reason,
        },
    )

    session = uow.session

    if claim.is_replay:
        return RetryResult(attempt=_replayed(session, claim), replayed=True)

    attempt = _locked_attempt(session, command.payment_attempt_id)

    if attempt.status not in RETRY_REQUIRABLE_FROM:
        raise BusinessRuleViolationError(
            f"attempt {attempt.attempt_number} is {attempt.status}; only "
            f"{', '.join(RETRY_REQUIRABLE_FROM)} may be marked as needing a retry. "
            "`06_Workflows_and_State_Machines.md:682-683` draws no other arrow into "
            "`retry_required` — money that moved is corrected rather than retried."
        )

    previous_status = attempt.status
    compare_and_swap(
        session,
        PaymentAttempt,
        entity_id=attempt.id,
        expected_version=command.expected_record_version,
        values={"status": ATTEMPT_RETRY_REQUIRED},
    )
    uow.flush()
    session.refresh(attempt)

    _audit(
        session,
        policy,
        names=MARK_RETRY_REQUIRED,
        attempt=attempt,
        previous_status=previous_status,
        reason=command.reason,
        actor=actor,
        context=context,
        now=now,
        extra={},
    )

    resolver.complete(
        claim,
        response_code=200,
        response_body={"attempt_id": str(attempt.id)},
        resource_type="payment_attempt",
        resource_id=attempt.id,
        now=now,
    )
    return RetryResult(attempt=attempt)


def create_retry_attempt(
    command: CreateRetryAttempt,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> RetryResult:
    """§17.5. A new attempt, its lineage recorded, and the original retired in one transaction.

    **The original becomes `superseded`**, which is `06_Workflows_and_State_Machines.md:684`:
    "retry_required --> superseded: replacement retry attempt created". Doing it in the same
    transaction is what stops two retries of one failure existing at once — the second would find
    the original already superseded and be refused by the status check.

    **The retry is `created`, not batched.** §17.5: "The retry attempt remains unbatched until
    included in a future batch version." M6's allocation is what moves it, and this command
    deliberately holds no batching privilege at all.
    """

    if not command.reason.strip():
        raise BusinessRuleViolationError(
            "creating a retry requires a reason; `05_API_Specification.md:1628` shows it in the "
            "body and `command_catalog.yaml` gives this command `new_attempt_preserves_retry_"
            "lineage` as a precondition, which a reasonless retry cannot evidence"
        )

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=CREATE_RETRY_OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "payment_attempt_id": str(command.payment_attempt_id),
            "payment_request_revision_id": str(command.payment_request_revision_id),
            "amount_irr": str(command.amount_irr),
        },
    )

    session = uow.session

    if claim.is_replay:
        return RetryResult(attempt=_replayed(session, claim), replayed=True)

    original = _locked_attempt(session, command.payment_attempt_id)
    request = _locked_request(session, original.payment_request_id)

    if original.status != ATTEMPT_RETRY_REQUIRED:
        raise BusinessRuleViolationError(
            f"attempt {original.attempt_number} is {original.status}; only a "
            f"{ATTEMPT_RETRY_REQUIRED} attempt may be retried. §17.4's decision comes first, and "
            "it is a separate command because deciding a retry is needed and creating one are "
            "different acts."
        )

    revision = session.get(PaymentRequestRevision, command.payment_request_revision_id)
    if revision is None:
        raise NotFoundError()
    if revision.payment_request_id != request.id:
        raise BusinessRuleViolationError(
            "the referenced revision belongs to a different payment request. §17.5 requires the "
            "retry's beneficiary to come from *this* request's revision, which is what makes "
            "'material beneficiary changes must exist in the referenced revision' checkable."
        )

    # `uq_attempt_number_per_request`. Computed rather than counted, because a superseded or
    # cancelled attempt still occupies its number and counting rows would reuse one.
    highest = session.scalar(
        select(func.coalesce(func.max(PaymentAttempt.attempt_number), 0)).where(
            PaymentAttempt.payment_request_id == request.id
        )
    )

    retry = PaymentAttempt(
        payment_request_id=request.id,
        payment_request_revision_id=revision.id,
        attempt_number=int(highest or 0) + 1,
        attempt_type=ATTEMPT_TYPE_RETRY,
        amount_irr=command.amount_irr,
        # **From the revision, never from the body.** §17.5 rejects free-form beneficiary changes,
        # and the strongest way to reject them is to have nowhere for one to arrive.
        beneficiary_name_snapshot=revision.beneficiary_name_snapshot,
        beneficiary_iban_snapshot=revision.beneficiary_iban_snapshot,
        beneficiary_national_id_snapshot=revision.beneficiary_national_id_snapshot,
        bank_profile_version_id=original.bank_profile_version_id,
        bank_account_id=original.bank_account_id,
        split_rule_snapshot={},
        status=ATTEMPT_CREATED,
        retry_of_attempt_id=original.id,
        record_version=1,
    )
    session.add(retry)

    compare_and_swap(
        session,
        PaymentAttempt,
        entity_id=original.id,
        expected_version=command.expected_record_version,
        values={"status": ATTEMPT_SUPERSEDED},
    )
    uow.flush()
    session.refresh(retry)

    _audit(
        session,
        policy,
        names=CREATE_RETRY_ATTEMPT,
        attempt=retry,
        previous_status=None,
        reason=command.reason,
        actor=actor,
        context=context,
        now=now,
        extra={
            "retry_of_attempt_id": str(original.id),
            "retry_of_attempt_number": original.attempt_number,
            "payment_request_revision_id": str(revision.id),
        },
    )

    resolver.complete(
        claim,
        response_code=201,
        response_body={"attempt_id": str(retry.id)},
        resource_type="payment_attempt",
        resource_id=retry.id,
        now=now,
    )
    return RetryResult(attempt=retry)


def _locked_attempt(session: Session, attempt_id: uuid.UUID) -> PaymentAttempt:
    lock_rows(
        session,
        [LockTarget.of(LockScope.PAYMENT_ATTEMPT_CREATE, PaymentAttempt, attempt_id)],
        models={PaymentAttempt.__tablename__: PaymentAttempt},
    )
    attempt = session.get(PaymentAttempt, attempt_id)
    if attempt is None:
        raise NotFoundError()
    return attempt


def _locked_request(session: Session, request_id: uuid.UUID) -> PaymentRequest:
    """`lock_original_attempt_and_request`, which the catalogue row asks for by name.

    The request's scope sorts before the attempt's, so `lock_rows` takes them in the order M2
    chose however this function calls them.
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


def _replayed(session: Session, claim: Any) -> PaymentAttempt:
    stored = claim.record.response_body or {}
    attempt = session.get(PaymentAttempt, uuid.UUID(str(stored["attempt_id"])))
    if attempt is None:  # pragma: no cover - the record made it
        raise NotFoundError()
    return attempt


def _audit(
    session: Session,
    policy: RedactionPolicy,
    *,
    names: Any,
    attempt: PaymentAttempt,
    previous_status: str | None,
    reason: str | None,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
    extra: dict[str, Any],
) -> None:
    """`AUD-RETRY-001`. The retry's row names what it retries.

    Without `retry_of_attempt_id` on the audit row, an investigator asking why a second attempt
    exists would have to join the attempts table — and the whole point of the lineage is that the
    answer is in the record of the decision.
    """

    new_values: dict[str, Any] = {
        "status": attempt.status,
        "payment_request_id": str(attempt.payment_request_id),
        "attempt_number": attempt.attempt_number,
        "amount_irr": str(attempt.amount_irr),
    }
    new_values.update(extra)

    AuditWriter(session, policy).record(
        AuditEntry(
            action=names.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="payment_attempt",
            entity_id=attempt.id,
            entity_record_version=attempt.record_version,
            previous_values=({"status": previous_status} if previous_status else {}),
            new_values=new_values,
            reason=reason,
            occurred_at=now,
            metadata={"operation": names.audit_action},
        ),
        actor=actor,
        context=context,
    )
