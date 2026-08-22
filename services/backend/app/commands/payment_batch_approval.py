"""The manager's decision on one exact version.

M7 slice 1. Two commands — `approve_version` and `reject_version` — and between them the
first place in this system where somebody authorises money to leave.

**The separation rule is enforced twice, and that is not belt-and-braces.**
`FINANCIAL_INTEGRITY_BASELINE.md` §5 requires `finalizer != approver` "at the command layer
**and** by a database-enforceable guard or transactional constraint/trigger whose race behavior
is tested". The two do different jobs. The check here refuses a caller with a sentence they can
act on. The CHECK constraint in `20260822_0020` refuses a row no matter what any transaction
read a moment earlier — which is the half a service check cannot do, because two requests can
both read "the finalizer is somebody else" and both be right at the moment they read it.

Delete the constraint and this module still refuses the obvious case; delete this module's check
and the database still refuses every case, less helpfully. `SEC-APPROVAL-001`'s negative control
removes the constraint and requires the concurrent test to fail, so neither half can be quietly
dropped.

**Two comparisons, not one.** `12_Security_RBAC_Audit.md:1111` names the disqualified actor as
"the version finalizer/**preparer**". `payment_batch_version.create` and `.finalize` are separate
permissions both defaulting to `accountant`, so one accountant can prepare a version and another
finalize it — and under the one-comparison reading the preparer, who chose every row in the file,
could then approve it. G-2 and DOC-CONFLICT-055 record that the owner may mean the finalizer
alone. This implements the stricter reading, because a guard that is too strict refuses a
legitimate approval and says so, while one that is too loose permits a self-approval nobody sees.

**The hash is the whole point of "exact".** `05_API_Specification.md:1443` — "The command is
blocked when the content hash differs." A manager approves what they were shown, and the way this
system knows what they were shown is that they send its digest back. `SVC-APPROVAL-001`.

**This is the second caller of `LockScope.BATCH_VERSION_APPROVAL`** — no, the first. The scope was
defined in M2 with the rest of the lock order and has had no caller since, the same shape as
`lock_rows` itself before M6 slice 3 used it. Nothing was wrong with defining it early; what was
wrong was that nothing said it was unused.

Covers: SEC-APPROVAL-001, SEC-APPROVAL-002, SEC-APPROVAL-003, CON-APPROVAL-001,
SVC-APPROVAL-001, AUD-APPROVAL-001, TRACE-APPROVAL-001.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.outbox import OutboxMessage, OutboxWriter
from app.audit.redaction import RedactionPolicy
from app.audit.registry import (
    APPROVE_PAYMENT_BATCH_VERSION,
    REJECT_PAYMENT_BATCH_VERSION,
)
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.core.errors import BusinessRuleViolationError, ConflictError, NotFoundError
from app.db.concurrency import compare_and_swap
from app.db.locking import LockScope, LockTarget, lock_rows
from app.db.models.payment_batch import BatchApproval, PaymentBatch, PaymentBatchVersion
from app.db.models.session_and_security import AuthEvent, RecentAuthContext
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.idempotency import IdempotencyResolver
from app.security import step_up
from app.security.actor import ActorContext
from app.security.events import OUTCOME_DENIED, SecurityEvent
from app.security.step_up import StepUpRefused, StepUpRejection, StepUpRequest

METADATA_SCHEMA = "payment_batch_command"
METADATA_VERSION = 1
PAYLOAD_VERSION = 1

APPROVE_OPERATION = "payment_batch_version.approve"
REJECT_OPERATION = "payment_batch_version.reject"

# The only state a decision may be taken from. `06_Workflows_and_State_Machines.md:770-903`:
# a draft has not been finalized, and an already-decided version has left this state.
VERSION_READY = "ready_for_approval"

VERSION_APPROVED = "approved"
VERSION_REJECTED = "rejected"
BATCH_APPROVED = "approved"
BATCH_REJECTED = "rejected"

DECISION_APPROVED = "approved"
DECISION_REJECTED = "rejected"

# What a caller must have re-authenticated *for*. The resource is the **version**, not the
# batch: `FINANCIAL_INTEGRITY_BASELINE.md` §3 binds a context to one resource, and
# `app/security/step_up.py` names this exact case in its own docstring — "otherwise a step-up
# for batch version 7 authorises version 8, which is the case the whole approval model exists
# to prevent". Two purposes rather than one, so a step-up obtained to reject cannot be spent
# approving.
STEP_UP_RESOURCE_TYPE = "payment_batch_version"
APPROVE_PURPOSE = "payment_batch_version.approve"
REJECT_PURPOSE = "payment_batch_version.reject"


@dataclass(frozen=True, slots=True)
class ApproveVersion:
    """`05_API_Specification.md:1415-1447`.

    No `expected_batch_record_version`. `:1443` says so in terms — "No `If-Match` is needed for
    the immutable version itself, but the server verifies it remains the batch's current
    version" — and `command_catalog.yaml:150` agrees:
    `immutable_version_id_and_hash_plus_current_version_lock`. The hash is the concurrency token
    here, which is a stronger one than a record version: it names the content, not the revision.
    """

    payment_batch_id: uuid.UUID
    payment_batch_version_id: uuid.UUID
    expected_content_hash: str
    recent_auth_reference: str
    approval_note: str | None = None


@dataclass(frozen=True, slots=True)
class RejectVersion:
    """`05_API_Specification.md:1449-1463`, where "Rejection reason is mandatory"."""

    payment_batch_id: uuid.UUID
    payment_batch_version_id: uuid.UUID
    expected_content_hash: str
    recent_auth_reference: str
    reason_code: str
    reason: str


@dataclass(frozen=True, slots=True)
class DecisionResult:
    batch: PaymentBatch
    version: PaymentBatchVersion
    approval: BatchApproval
    replayed: bool = False


class AlreadyDecided(ConflictError):
    """Some other decision reached this version first.

    Its own type because the route must be able to tell it from every other 409: the loser of a
    concurrent approval is told *which* decision won, and `CON-APPROVAL-001` requires that. A
    manager who refreshes and sees "already approved by Sara" understands what happened; a bare
    CONFLICT sends them to ask somebody.
    """

    def __init__(self, decision: str) -> None:
        super().__init__(f"this version has already been {decision}")
        self.decision = decision


def approve_version(
    command: ApproveVersion,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: ActorContext,
    audit_actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> DecisionResult:
    """`ready_for_approval -> approved`, for the exact content the manager was shown."""

    return _decide(
        DECISION_APPROVED,
        payment_batch_id=command.payment_batch_id,
        payment_batch_version_id=command.payment_batch_version_id,
        expected_content_hash=command.expected_content_hash,
        recent_auth_reference=command.recent_auth_reference,
        reason=command.approval_note,
        reason_code=None,
        operation=APPROVE_OPERATION,
        purpose=APPROVE_PURPOSE,
        uow=uow,
        policy=policy,
        actor=actor,
        audit_actor=audit_actor,
        context=context,
        idempotency_key=idempotency_key,
        now=now,
    )


def reject_version(
    command: RejectVersion,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: ActorContext,
    audit_actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> DecisionResult:
    """`ready_for_approval -> rejected`, with the reason document 05 makes mandatory.

    The rejected version is not edited. `status_catalog.yaml` marks `rejected` terminal for a
    version and its note says why: "replacement is a new version". That replacement is slice 5's.
    """

    if not command.reason.strip():
        raise BusinessRuleViolationError(
            "a rejection requires a reason; 05_API_Specification.md:1461 makes it mandatory"
        )
    if not command.reason_code.strip():
        raise BusinessRuleViolationError(
            "a rejection requires a reason code; 05_API_Specification.md:1456 sends one"
        )

    return _decide(
        DECISION_REJECTED,
        payment_batch_id=command.payment_batch_id,
        payment_batch_version_id=command.payment_batch_version_id,
        expected_content_hash=command.expected_content_hash,
        recent_auth_reference=command.recent_auth_reference,
        reason=command.reason,
        reason_code=command.reason_code,
        operation=REJECT_OPERATION,
        purpose=REJECT_PURPOSE,
        uow=uow,
        policy=policy,
        actor=actor,
        audit_actor=audit_actor,
        context=context,
        idempotency_key=idempotency_key,
        now=now,
    )


def _decide(
    decision: str,
    *,
    payment_batch_id: uuid.UUID,
    payment_batch_version_id: uuid.UUID,
    expected_content_hash: str,
    recent_auth_reference: str,
    reason: str | None,
    reason_code: str | None,
    operation: str,
    purpose: str,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: ActorContext,
    audit_actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> DecisionResult:
    """Both decisions, because every guard before the write is the same guard.

    Shared rather than duplicated: an approval and a rejection differ in what they record and in
    what the version becomes, and in nothing else. Two copies of the eight checks below would be
    two places for the separation rule to be relaxed, and only one of them would be reviewed.
    """

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=audit_actor.actor_type,
        actor_id=audit_actor.idempotency_scope_id,
        operation=operation,
        idempotency_key=idempotency_key,
        # The target and the decision's own content. The step-up reference is deliberately
        # absent: a retry after a timeout is the same request, and a caller who obtained a
        # fresh context to retry would otherwise look like a different one.
        payload={
            "payment_batch_id": str(payment_batch_id),
            "payment_batch_version_id": str(payment_batch_version_id),
            "expected_content_hash": expected_content_hash,
            "reason": reason,
            "reason_code": reason_code,
        },
    )

    session = uow.session

    if claim.is_replay:
        return _replayed(session, claim.record.response_body or {})

    # Locks first, in the global order, before anything is read. `LockScope.BATCH_VERSION_APPROVAL`
    # has existed since M2 and this is its first caller.
    lock_rows(
        session,
        [
            LockTarget.of(LockScope.BATCH_VERSION_APPROVAL, PaymentBatch, payment_batch_id),
            LockTarget.of(
                LockScope.BATCH_VERSION_APPROVAL, PaymentBatchVersion, payment_batch_version_id
            ),
        ],
        models={
            PaymentBatch.__tablename__: PaymentBatch,
            PaymentBatchVersion.__tablename__: PaymentBatchVersion,
        },
    )

    batch = session.get(PaymentBatch, payment_batch_id)
    if batch is None:
        raise NotFoundError()

    version = session.get(PaymentBatchVersion, payment_batch_version_id)
    if version is None or version.payment_batch_id != batch.id:
        # Indistinguishable from a missing version on purpose, the same as finalization: whether
        # a version id exists under some other batch is not something this route should teach.
        raise NotFoundError()

    if batch.current_version_id != version.id:
        # `:1443`: "the server verifies it remains the batch's current version". This is the
        # stale-screen case §15.3 describes — a replacement was made while the manager was
        # reading, and the version in front of them is no longer the one that would be exported.
        raise ConflictError(
            f"version {version.version_number} is no longer the current version of batch "
            f"{batch.batch_number}; a replacement was made and must be decided instead"
        )

    # **Before the status guard, and the order is the answer a person gets.** A decided version
    # is also a version whose status is no longer `ready_for_approval`, so the guard below would
    # fire first and say "a version in 'approved' cannot be decided" — true, and useless. What a
    # manager needs to know is that a colleague already approved it. The status guard then covers
    # what is left: a draft, and a version superseded without a decision.
    existing = session.scalar(
        select(BatchApproval).where(BatchApproval.payment_batch_version_id == version.id)
    )
    if existing is not None:
        raise AlreadyDecided(existing.decision)

    if version.status != VERSION_READY:
        raise BusinessRuleViolationError(
            f"a version in {version.status!r} cannot be decided; only a finalized version "
            f"awaiting approval can be"
        )

    # `SVC-APPROVAL-001`. Before the separation checks, because a manager holding a stale screen
    # should be told the content moved rather than told who they are.
    if expected_content_hash.strip().lower() != version.content_hash:
        raise ConflictError(
            "the expected content hash does not match this version; the screen it was read "
            "from is stale and the decision would not be about what was displayed"
        )

    decider = _decider(audit_actor)
    _refuse_if_the_decider_made_this_version(version, decider)

    # The step-up is consumed **after** every refusal above and before any write, for the reason
    # `role_permissions` gives: spending a caller's single-use assurance on a request that was
    # going to be refused anyway makes them re-authenticate to learn they made a mistake.
    consumed = _consume_context(session, recent_auth_reference, actor, version.id, purpose, now)
    if isinstance(consumed, StepUpRejection):
        session.add(
            AuthEvent(
                **SecurityEvent(
                    actor_type=actor.actor_type.value,
                    actor_id=actor.actor_id,
                    session_id=actor.session_id,
                    event_type="step_up.rejected",
                    event_class="authorization",
                    outcome=OUTCOME_DENIED,
                    metadata_payload={
                        "rejection_reason": consumed.value,
                        "payment_batch_version_id": str(version.id),
                        "operation": operation,
                    },
                ).as_row()
            )
        )
        raise StepUpRefused(consumed)

    approval = BatchApproval(
        payment_batch_version_id=version.id,
        decision=decision,
        decided_by_admin_user_id=decider,
        decided_at=now,
        reason=reason if decision == DECISION_REJECTED else (reason or None),
        # TRACE-APPROVAL-001: the version's own hash, not the caller's copy of it. They were
        # compared above and are equal; storing the version's makes "what did the manager
        # approve" answerable without trusting a request body that is no longer in scope.
        approved_content_hash=version.content_hash if decision == DECISION_APPROVED else None,
        # §11.7: "Session ID/auth level/recent-auth metadata; no secret". The context is named
        # by id. Its reference is not here and never will be — `12_Security_RBAC_Audit.md:536`
        # requires the link without the replayable value.
        authentication_context={
            "session_id": str(actor.session_id),
            "authentication_assurance": audit_actor.authentication_assurance,
            "recent_auth_context_id": str(consumed.id),
            "assurance_factor": consumed.assurance_factor,
            "purpose": purpose,
        },
        request_id=_request_uuid(context),
        version_finalized_by_admin_user_id=_finalizer(version),
        version_created_by_admin_user_id=version.created_by_admin_user_id,
    )
    session.add(approval)

    version.status = VERSION_APPROVED if decision == DECISION_APPROVED else VERSION_REJECTED

    # The container's status is a projection of its current version's — nine of eleven container
    # states are `derived: true` — so moving one without the other would make `CON-BATCH-004`
    # false the instant this commits.
    #
    # Compare-and-swap with the version read under the lock above, rather than a plain
    # assignment. There is no `If-Match` on this route, so this is not optimistic concurrency:
    # it is how `record_version` and `updated_at` move at all. A direct assignment would leave a
    # batch whose status changed and whose record version says nothing happened, and every
    # reader that caches on that token would serve the old status.
    swap = compare_and_swap(
        session,
        PaymentBatch,
        entity_id=batch.id,
        expected_version=batch.record_version,
        values={"status": BATCH_APPROVED if decision == DECISION_APPROVED else BATCH_REJECTED},
    )

    try:
        uow.flush()
    except IntegrityError as error:
        # CON-APPROVAL-001. The `SELECT` above cannot decide this: two transactions can both find
        # no existing decision and both proceed. `uq_batch_approvals_one_per_version` is what
        # actually decides, and this is where the loser learns it lost — translated to the same
        # 409 the early read produces, so a caller cannot tell which path refused them and no
        # timing difference says whether they were first.
        if not _is_one_decision_per_version(error):
            raise
        uow.rollback()
        raise AlreadyDecided(_decision_now_recorded(uow, version.id)) from None

    session.refresh(batch)

    _audit_decision(
        session,
        policy,
        decision=decision,
        batch=batch,
        version=version,
        approval=approval,
        reason=reason,
        reason_code=reason_code,
        actor=audit_actor,
        context=context,
        now=now,
    )
    if decision == DECISION_APPROVED:
        _publish_approved(session, policy, batch, version, approval, context, swap.new_version)

    resolver.complete(
        claim,
        response_code=200,
        response_body={
            "batch_id": str(batch.id),
            "version_id": str(version.id),
            "approval_id": str(approval.id),
        },
        resource_type="batch_approval",
        resource_id=approval.id,
        now=now,
    )

    return DecisionResult(batch=batch, version=version, approval=approval)


def _refuse_if_the_decider_made_this_version(
    version: PaymentBatchVersion, decider: uuid.UUID
) -> None:
    """`SEC-APPROVAL-001` and `SEC-APPROVAL-002`, the half a person can act on.

    **400 rather than 403.** The catalogue's `FORBIDDEN` means "Permission denied", and this
    caller's permission is not the problem — they hold `payment_batch_version.approve` and may
    decide any number of other versions. Telling them their permission was denied would send
    them to an administrator to fix something that is not broken. `BUSINESS_RULE_VIOLATION` is
    what this is: a domain rule about *this* version and *this* actor.

    The message names which role disqualified them, because the remedy differs — a preparer
    hands the file to a colleague, a finalizer asks a different manager to decide.
    """

    if version.finalized_by_admin_user_id == decider:
        raise BusinessRuleViolationError(
            "the actor who finalized this version cannot decide it; "
            "FINANCIAL_INTEGRITY_BASELINE.md §5 requires the approver to differ from the "
            "recorded finalizer"
        )
    if version.created_by_admin_user_id == decider:
        raise BusinessRuleViolationError(
            "the actor who prepared this version cannot decide it; "
            "12_Security_RBAC_Audit.md:1111 disqualifies the version finalizer/preparer"
        )


def _decider(audit_actor: AuditActor) -> uuid.UUID:
    """The deciding administrator, narrowed from `uuid.UUID | None`.

    `AuditActor.actor_id` is optional because the two system actor types carry none. A decision
    is a human act — `permission_catalog.yaml:480` gives `payment_batch_version.approve` to
    `manager` and to nothing automated — so a system actor reaching here is a routing defect,
    and recording the approval with a null decider would defeat the separation rule by removing
    the thing it compares.
    """

    if audit_actor.actor_id is None:
        raise BusinessRuleViolationError(
            "a batch version decision must be taken by an administrator; a system actor has "
            "no identity to compare against the version's finalizer"
        )
    return audit_actor.actor_id


def _finalizer(version: PaymentBatchVersion) -> uuid.UUID:
    """The recorded finalizer, narrowed from `str | None`.

    Nullable on the version because a draft has none. A version in `ready_for_approval` was
    finalized, and finalization writes this column from the session actor — so reaching here
    with `None` would mean a version left `draft` without one, which is a defect in
    `finalize_version` rather than a case to handle politely.
    """

    if version.finalized_by_admin_user_id is None:  # pragma: no cover - status guard precedes it
        raise RuntimeError(
            f"version {version.id} is {version.status!r} and has no recorded finalizer; "
            "the separation guard has nothing to compare against"
        )
    return version.finalized_by_admin_user_id


def _consume_context(
    session: Session,
    reference: str,
    actor: ActorContext,
    version_id: uuid.UUID,
    purpose: str,
    now: datetime,
) -> RecentAuthContext | StepUpRejection:
    """Find the presented context, decide whether it authorises *this*, and spend it.

    `SEC-APPROVAL-003`. Consumption happens inside the caller's transaction, which is what
    `recent_auth_contexts.consumed_at` exists for: marking it spent separately would let a
    timeout-and-retry approve twice on one step-up.

    **This is the second copy of this shape** — `app/commands/role_permissions.py` has the
    first. It is not extracted yet on purpose: the two differ in purpose, resource type and the
    command name recorded on the row, so a shared helper is three parameters and one indirection
    for two callers. The third caller is where that stops being true, and slice 4's mark-sent is
    the likely one. The policy itself is *already* shared — `step_up.rejection_for` holds every
    comparison — so what is duplicated here is lookup and assignment, and both are covered by
    tests on either side.
    """

    stored = session.scalar(
        select(RecentAuthContext).where(
            RecentAuthContext.challenge_hash == step_up.digest_reference(reference)
        )
    )

    presented = (
        None
        if stored is None
        else step_up.PresentedContext(
            actor_id=stored.actor_id,
            session_id=stored.session_id,
            purpose=stored.purpose,
            resource_type=stored.resource_type,
            resource_id=stored.resource_id,
            assurance_factor=stored.assurance_factor,
            expires_at=stored.expires_at,
            consumed_at=stored.consumed_at,
            revoked_at=stored.revoked_at,
        )
    )

    rejection = step_up.rejection_for(
        presented,
        actor=actor,
        request=StepUpRequest(
            purpose=purpose,
            resource_type=STEP_UP_RESOURCE_TYPE,
            resource_id=version_id,
        ),
        now=now,
    )
    if rejection is not None:
        return rejection

    assert stored is not None  # `rejection_for` returns UNKNOWN_REFERENCE for None
    stored.consumed_at = now
    stored.consumed_by_command = purpose
    return stored


def _is_one_decision_per_version(error: IntegrityError) -> bool:
    """Whether this integrity failure is the one-decision-per-version race and not another.

    By constraint name, not by message text: the message is PostgreSQL's and localised, and a
    substring match on it would silently start catching a different violation the day somebody
    adds one. Every other constraint on this table is a programming error and must keep raising.

    **Read from `diag.constraint_name`, which is a correction.** The first version tested
    `"uq_..." in str(error.orig.diag)`, and a diagnostic renders as its repr — the constraint name
    is nowhere in it, so the branch could never match and every concurrent loser would have got a
    500 instead of a 409. Nothing here caught it: the early `SELECT` above returns `AlreadyDecided`
    first in every test, so this path has no coverage of its own and would only have fired under
    a genuine race in production. M7 slice 3 met the same mistake in its own new code, where a
    test *did* reach the branch, and fixed both.
    """

    diagnostic = getattr(error.orig, "diag", None)
    name = getattr(diagnostic, "constraint_name", None)
    return str(name) == "uq_batch_approvals_one_per_version" if name else False


def _decision_now_recorded(uow: SqlAlchemyUnitOfWork, version_id: uuid.UUID) -> str:
    """What the winner decided, read after the rollback so the row is visible.

    The loser is told which decision won rather than a bare conflict — `CON-APPROVAL-001` asks
    for exactly that, and a manager who is told "already approved" knows not to chase it.
    """

    winner = uow.session.scalar(
        select(BatchApproval).where(BatchApproval.payment_batch_version_id == version_id)
    )
    return winner.decision if winner is not None else DECISION_APPROVED


def _replayed(session: Session, stored: dict[str, Any]) -> DecisionResult:
    batch = session.get(PaymentBatch, uuid.UUID(str(stored["batch_id"])))
    version = session.get(PaymentBatchVersion, uuid.UUID(str(stored["version_id"])))
    approval = session.get(BatchApproval, uuid.UUID(str(stored["approval_id"])))
    if batch is None or version is None or approval is None:  # pragma: no cover - it made them
        raise NotFoundError()
    return DecisionResult(batch=batch, version=version, approval=approval, replayed=True)


def _request_uuid(context: AuditContext) -> uuid.UUID | None:
    """§11.7's `request_id`, stored only when the request id is really a UUID.

    The header is caller-supplied and the column is typed. A request id that is not a UUID is
    recorded in the audit row, which is text, and dropped here rather than made up.
    """

    try:
        return uuid.UUID(str(context.request_id))
    except (TypeError, ValueError):
        return None


def _audit_decision(
    session: Session,
    policy: RedactionPolicy,
    *,
    decision: str,
    batch: PaymentBatch,
    version: PaymentBatchVersion,
    approval: BatchApproval,
    reason: str | None,
    reason_code: str | None,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> None:
    """`AUD-APPROVAL-001`. The catalogued action, in this transaction, naming the exact hash.

    `entity_type` is the version, not the approval row: the thing that changed state is the
    version, and "what happened to version 3" is the question an investigator asks.
    """

    names = (
        APPROVE_PAYMENT_BATCH_VERSION
        if decision == DECISION_APPROVED
        else REJECT_PAYMENT_BATCH_VERSION
    )

    AuditWriter(session, policy).record(
        AuditEntry(
            action=names.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="payment_batch_version",
            entity_id=version.id,
            entity_record_version=batch.record_version,
            previous_values={"status": VERSION_READY},
            new_values={
                "status": version.status,
                "batch_status": batch.status,
                # TRACE-APPROVAL-001's other half. The audit row names the hash too, so the
                # chain from "the manager decided" to "this content" survives even if somebody
                # is reading the log rather than the table.
                "content_hash": version.content_hash,
                "approval_id": str(approval.id),
                "decision": decision,
                "decided_by_admin_user_id": str(approval.decided_by_admin_user_id),
                "reason_code": reason_code,
            },
            reason=reason,
            occurred_at=now,
            metadata={"operation": names.audit_action},
        ),
        actor=actor,
        context=context,
    )


def _publish_approved(
    session: Session,
    policy: RedactionPolicy,
    batch: PaymentBatch,
    version: PaymentBatchVersion,
    approval: BatchApproval,
    context: AuditContext,
    aggregate_version: int,
) -> None:
    """`PaymentBatchVersionApproved`, and nothing for a rejection.

    `command_catalog.yaml:153` names this event and `:166` gives rejection `null`. That is the
    catalogue's answer rather than an omission: an approval releases the version to the export
    side and something downstream must hear it, while a rejection returns the batch to the
    accountant who is already looking at it. Inventing `PaymentBatchVersionRejected` would put
    an event type on the queue that no consumer contract names.

    **Identifiers, counts and the hash.** No beneficiary, no IBAN, no row. The hash is included
    because a consumer generating the final export must be able to prove it rendered the
    approved content, which is `FINANCIAL_INTEGRITY_BASELINE.md` §1's requirement of slice 3.
    """

    event = APPROVE_PAYMENT_BATCH_VERSION.outbox_event_type
    if event is None:  # pragma: no cover - the registry entry names one
        raise RuntimeError(
            "APPROVE_PAYMENT_BATCH_VERSION has no outbox event type, and "
            "command_catalog.yaml:153 requires PaymentBatchVersionApproved"
        )

    OutboxWriter(session, policy).enqueue(
        OutboxMessage(
            aggregate_type="payment_batch_version",
            aggregate_id=version.id,
            aggregate_version=aggregate_version,
            event_type=event,
            payload={
                "payment_batch_id": str(batch.id),
                "payment_batch_version_id": str(version.id),
                "batch_approval_id": str(approval.id),
                "batch_number": batch.batch_number,
                "version_number": version.version_number,
                "row_count": version.row_count,
                "total_amount_irr": str(version.total_amount_irr),
                "approved_content_hash": version.content_hash,
            },
            payload_version=PAYLOAD_VERSION,
            correlation_id=context.correlation_id,
            causation_id=context.causation_id,
        )
    )
