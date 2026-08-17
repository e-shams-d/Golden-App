"""Creating a draft request, and cancelling one.

M5 slice 3. Two commands, one transaction each, neither committing — the route owns
the boundary.

**A draft is a request and its first revision, or neither.** They are inserted in one
transaction and each references the other, which is why the composite pointer is
`DEFERRABLE INITIALLY DEFERRED`. A request with no revision has no content and would
sit in a queue as an empty row nobody can act on.

**Why `cancel_draft` is here when the plan listed only `create_draft`.** `CON-REQ-001`
is "`payment_requests.record_version` supports `If-Match`, and a stale value returns
`412` rather than overwriting" — and a slice whose only route creates a resource has
nothing for `If-Match` to be stale *against*. The obligation was unprovable as the
plan scoped it. Cancellation is the smallest command that fixes that and is already
in the milestone (`15_Agent_Implementation_Plan.md:766`), reaches an M5 status, and
needs optimistic concurrency for its own sake: two people cancelling the same draft
from two screens is the ordinary race.

**Money is not computed here.** `amount_irr` is taken as given and the entered pair is
stored as passed. Slice 4 owns the conversion and its refusals; this slice stores what
it is handed so the table and its constraints exist to be built against. The CHECKs
that `amount_irr > 0` and that the entered pair is complete-or-absent are already in
the database, so a caller cannot write a row slice 4 would have to repair.

Covers: SEC-REQ-001, CON-REQ-001.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import (
    CANCEL_PAYMENT_REQUEST,
    CREATE_PAYMENT_REQUEST,
    CREATE_REVISION,
    CommandNames,
)
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.core.hashing import unversioned_digest
from app.core.money import Money
from app.db.concurrency import compare_and_swap
from app.db.models.beneficiary import Beneficiary
from app.db.models.payment_request import PaymentRequest, PaymentRequestRevision
from app.db.models.trader import Trader
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.idempotency import IdempotencyResolver

METADATA_SCHEMA = "audit.payment_request.lifecycle"
METADATA_VERSION = 1

DRAFT = "draft"
CANCELLED = "cancelled"
SUBMITTED = "submitted_to_center"
NEEDS_CORRECTION = "needs_trader_correction"

# The operation name the idempotency record carries. Distinct from draft creation, so a
# key reused across the two is a conflict rather than a replay of the wrong command.
CREATE_REVISION_OPERATION = "payment_request.create_revision"

# Which statuses accept a correction. `draft` because a trader may fix their own work
# before submitting, and `needs_trader_correction` because that is what the accountant
# asked for. Deliberately not `submitted_to_center` or `under_accountant_review`:
# correcting a request while somebody is reading it would move the content under them,
# and document 06 routes that through the review workflow instead.
CORRECTABLE = (DRAFT, NEEDS_CORRECTION)

# `traders`, per DOC-CONFLICT-024's two axes. Both must be right, and that is the
# point of `SEC-REQ-001`: a business awaiting approval and a business barred today are
# different facts, and either one is a reason to refuse. Checking only one would let a
# suspended-but-approved trader keep creating requests.
OPERATIONAL_OK = "active"
APPROVAL_OK = "approved"

# Which statuses may still be cancelled. `draft` only, in this slice: document 06
# permits cancellation from later states through the review workflow, and slice 7 is
# where those transitions and their authority live. Narrow here rather than permissive,
# because a cancel that reached a batched request would invalidate work downstream.
CANCELLABLE = (DRAFT,)


@dataclass(frozen=True, slots=True)
class CreateDraft:
    trader_id: uuid.UUID
    beneficiary_id: uuid.UUID
    # One `Money`, not three loose numbers. Slice 3 took `amount_irr` as an int and
    # the entered pair as optional extras, which meant the command could be handed a
    # canonical value that did not follow from what was typed — and M2's `Money`,
    # built for exactly this, had no caller anywhere in the system.
    #
    # `Money.__post_init__` re-derives the conversion and refuses a disagreement, so
    # by the time a `CreateDraft` exists the three parts have already been checked
    # against each other. The command cannot construct an inconsistent revision
    # because it is not given the parts separately.
    amount: Money
    description: str | None = None
    source_attachment_file_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class CancelDraft:
    payment_request_id: uuid.UUID
    expected_record_version: int
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class CreateRevision:
    """A correction. Every content field is required, not patched.

    Deliberately not a partial update. A revision is a complete statement of what is
    being submitted — that is what makes it answerable later — and a patch shape would
    mean the new revision's content is the old revision's plus a diff, so reading what
    revision 3 said would require replaying revisions 1 and 2. The client sends the
    whole intent and the server hashes it.
    """

    payment_request_id: uuid.UUID
    expected_record_version: int
    beneficiary_id: uuid.UUID
    amount: Money
    description: str | None = None
    source_attachment_file_id: uuid.UUID | None = None
    revision_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RevisionResult:
    request: PaymentRequest
    revision: PaymentRequestRevision
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class DraftResult:
    request: PaymentRequest
    revision: PaymentRequestRevision


def create_draft(
    command: CreateDraft,
    *,
    session: Session,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> DraftResult:
    """Create the request and revision 1, or nothing at all."""

    trader = session.get(Trader, command.trader_id)
    if trader is None:
        raise NotFoundError()
    _require_operable(trader)

    beneficiary = session.get(Beneficiary, command.beneficiary_id)
    if beneficiary is None or beneficiary.trader_id != command.trader_id:
        # Indistinguishable on purpose: a beneficiary belonging to another trader
        # answers exactly as a missing one, so the endpoint cannot be used to learn
        # that an id is real.
        raise NotFoundError()
    if beneficiary.status != "active":
        raise BusinessRuleViolationError(
            f"a {beneficiary.status} beneficiary cannot receive a new request; "
            "06_Workflows_and_State_Machines.md:299 permits only active ones"
        )

    request = PaymentRequest(
        trader_id=command.trader_id,
        beneficiary_id=command.beneficiary_id,
        request_number=_next_request_number(session, now),
        status=DRAFT,
        created_by_trader_user_id=actor.actor_id if actor.actor_type == "trader_user" else None,
        created_by_admin_user_id=actor.actor_id if actor.actor_type == "admin_user" else None,
    )
    session.add(request)
    session.flush()

    revision = PaymentRequestRevision(
        payment_request_id=request.id,
        revision_number=1,
        beneficiary_id=beneficiary.id,
        # Snapshotted now, from the beneficiary as it stands. Slice 6 proves that
        # editing the beneficiary afterwards leaves this untouched; taking the values
        # here rather than by reference is what makes that true.
        beneficiary_name_snapshot=beneficiary.full_name,
        beneficiary_iban_snapshot=beneficiary.normalized_iban,
        beneficiary_national_id_snapshot=beneficiary.national_id,
        # All three from the one checked value. `entered_amount_*` are NOT NULL in
        # practice from here on, even though document 04 marks them nullable: the
        # column pair is what a dispute six months later is read against, and a
        # revision that recorded only the canonical figure could not answer "what did
        # they type". The CHECK that the pair is complete-or-absent still permits a
        # future importer to write a row without provenance.
        amount_irr=command.amount.amount_irr,
        entered_amount_value=command.amount.entered_amount,
        entered_amount_unit=command.amount.entered_unit.value,
        description=command.description,
        source_attachment_file_id=command.source_attachment_file_id,
        created_by_actor_type=actor.actor_type,
        created_by_actor_id=actor.actor_id,
    )
    revision.content_hash = revision_content_hash(revision)
    session.add(revision)
    session.flush()

    # The pointer, set after the revision exists. Deferred checking is what permits
    # this order inside one transaction.
    request.current_revision_id = revision.id
    session.flush()

    _audit(
        session,
        policy,
        CREATE_PAYMENT_REQUEST,
        outcome="success",
        request_id=request.id,
        record_version=request.record_version,
        reason=None,
        actor=actor,
        context=context,
        now=now,
        new_values={"status": DRAFT, "revision_number": 1},
    )

    return DraftResult(request=request, revision=revision)


def cancel_draft(
    command: CancelDraft,
    *,
    session: Session,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> PaymentRequest:
    """Cancel a draft, under optimistic concurrency.

    Through `compare_and_swap` rather than a read-then-write: the comparison belongs
    in the statement that writes, because a check in Python loses the race under READ
    COMMITTED and loses it silently.

    Nothing is deleted. The request and every revision stay; only the status moves,
    because a cancelled request is part of the trader's history and the reason it was
    cancelled is something a dispute may turn on.
    """

    request = session.get(PaymentRequest, command.payment_request_id)
    if request is None:
        raise NotFoundError()

    if request.status not in CANCELLABLE:
        raise BusinessRuleViolationError(
            f"a {request.status} request is not cancelled here; only {', '.join(CANCELLABLE)} "
            "is, and later states are cancelled through the review workflow"
        )

    previous = {"status": request.status}
    outcome = compare_and_swap(
        session,
        PaymentRequest,
        entity_id=command.payment_request_id,
        expected_version=command.expected_record_version,
        values={
            "status": CANCELLED,
            "cancelled_at": now,
            "cancelled_reason": command.reason,
        },
    )
    session.expire(request)

    _audit(
        session,
        policy,
        CANCEL_PAYMENT_REQUEST,
        outcome="success",
        request_id=command.payment_request_id,
        record_version=outcome.new_version,
        reason=command.reason,
        actor=actor,
        context=context,
        now=now,
        previous_values=previous,
        new_values={"status": CANCELLED},
    )

    return request


def create_revision(
    command: CreateRevision,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> RevisionResult:
    """Add revision *n+1* and move the pointer. Revision *n* is not touched.

    Takes the unit of work rather than a session, because the idempotency resolver
    needs a savepoint: it inserts the claim, flushes to force the unique violation
    while it can still be turned into a replay, and rolls back to the savepoint if it
    was already claimed.

    **Nothing here updates a revision.** The pointer that moves is on the request. The
    previous revision keeps its row, its `content_hash` and its `created_at` — the
    migration grants no UPDATE on that table at all, so this is enforced by the absence
    of a privilege rather than by the care of this function.

    `superseded_at` is deliberately left NULL on the replaced revision. Document 04
    defines the column and M5 does not write it: setting it would be an update to an
    immutable row, and "which revision is current" is already answered by
    `payment_requests.current_revision_id`. Recording the same fact twice, where one
    copy requires widening a grant, is how the immutability guarantee gets traded away
    for a denormalised convenience.
    """

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=CREATE_REVISION_OPERATION,
        idempotency_key=idempotency_key,
        # The content, not the record version. Two retries of the same correction are
        # the same request even if the first one moved `record_version` — including it
        # would make an honest retry look like a different body and raise a conflict
        # where a replay is correct.
        payload={
            "payment_request_id": str(command.payment_request_id),
            "beneficiary_id": str(command.beneficiary_id),
            "amount_irr": command.amount.amount_irr,
            "entered_amount": command.amount.entered_amount,
            "entered_unit": command.amount.entered_unit.value,
            "description": command.description,
            "source_attachment_file_id": (
                str(command.source_attachment_file_id)
                if command.source_attachment_file_id
                else None
            ),
        },
    )

    session = uow.session

    if claim.is_replay:
        stored = claim.record.response_body or {}
        request = session.get(PaymentRequest, command.payment_request_id)
        revision = session.get(PaymentRequestRevision, uuid.UUID(str(stored["revision_id"])))
        if request is None or revision is None:  # pragma: no cover - the record made them
            raise NotFoundError()
        return RevisionResult(request=request, revision=revision, replayed=True)

    request = session.get(PaymentRequest, command.payment_request_id)
    if request is None:
        raise NotFoundError()

    if request.status not in CORRECTABLE:
        raise BusinessRuleViolationError(
            f"a {request.status} request does not take a correction; only "
            f"{', '.join(CORRECTABLE)} does"
        )

    trader = session.get(Trader, request.trader_id)
    if trader is None:  # pragma: no cover - the request's FK guarantees it
        raise NotFoundError()
    _require_operable(trader)

    beneficiary = session.get(Beneficiary, command.beneficiary_id)
    if beneficiary is None or beneficiary.trader_id != request.trader_id:
        raise NotFoundError()
    if beneficiary.status != "active":
        raise BusinessRuleViolationError(
            f"a {beneficiary.status} beneficiary cannot receive a corrected request"
        )

    previous = session.get(PaymentRequestRevision, request.current_revision_id)
    if previous is None:  # pragma: no cover - a request always has revision 1
        raise NotFoundError()

    revision = PaymentRequestRevision(
        payment_request_id=request.id,
        revision_number=previous.revision_number + 1,
        beneficiary_id=beneficiary.id,
        # Re-snapshotted from the beneficiary as it stands *now*, not copied from the
        # previous revision. A correction that changed the beneficiary must carry that
        # beneficiary's details, and one that did not must still record today's values
        # — the revision is a statement about this submission, not a delta.
        beneficiary_name_snapshot=beneficiary.full_name,
        beneficiary_iban_snapshot=beneficiary.normalized_iban,
        beneficiary_national_id_snapshot=beneficiary.national_id,
        amount_irr=command.amount.amount_irr,
        entered_amount_value=command.amount.entered_amount,
        entered_amount_unit=command.amount.entered_unit.value,
        description=command.description,
        source_attachment_file_id=command.source_attachment_file_id,
        revision_reason=command.revision_reason,
        created_by_actor_type=actor.actor_type,
        created_by_actor_id=actor.actor_id,
    )
    revision.content_hash = revision_content_hash(revision)

    if revision.content_hash == previous.content_hash:
        # Refused here as well as by `UNIQUE(payment_request_id, content_hash)`, and
        # the duplication is the point: the constraint is what makes the rule
        # unbypassable, and this is what makes the refusal explicable. A caller who
        # hits the constraint gets an integrity error naming an index; a caller who
        # hits this gets told they changed nothing.
        raise BusinessRuleViolationError(
            "this correction is identical to the current revision, so there is nothing "
            "to correct. Change what you are submitting, or leave the request as it is."
        )

    session.add(revision)
    session.flush()

    outcome = compare_and_swap(
        session,
        PaymentRequest,
        entity_id=request.id,
        expected_version=command.expected_record_version,
        values={
            "current_revision_id": revision.id,
            # Back to the centre's queue. A correction the accountant asked for is not
            # finished until it is resubmitted, and leaving it in
            # `needs_trader_correction` would mean the trader corrected it and nobody
            # was told.
            "status": SUBMITTED,
            "submitted_at": now,
        },
    )
    session.expire(request)

    _audit(
        session,
        policy,
        CREATE_REVISION,
        outcome="success",
        request_id=request.id,
        record_version=outcome.new_version,
        reason=command.revision_reason,
        actor=actor,
        context=context,
        now=now,
        previous_values={
            "current_revision_id": str(previous.id),
            "revision_number": previous.revision_number,
        },
        new_values={
            "current_revision_id": str(revision.id),
            "revision_number": revision.revision_number,
            "status": SUBMITTED,
        },
    )

    resolver.complete(
        claim,
        response_code=201,
        response_body={"revision_id": str(revision.id), "request_id": str(request.id)},
        resource_type="payment_request",
        resource_id=request.id,
        now=now,
    )

    return RevisionResult(request=request, revision=revision)


def revision_content_hash(revision: PaymentRequestRevision) -> str:
    """The digest `UNIQUE(payment_request_id, content_hash)` compares.

    Over the fields that make a revision *different submitted intent*, and
    deliberately not over `revision_number`, `created_at` or the actor — including any
    of those would make every revision unique and the uniqueness constraint would
    stop refusing anything, which is the quietest possible way to lose it.

    `description` is included. A description-only edit is a real correction: the
    reviewer read that text, and changing it changes what was submitted even though no
    money moved.

    `unversioned_digest` because the column is 64 characters and the versioned form is
    67; that function's docstring records what the missing version prefix costs.
    """

    return unversioned_digest(
        {
            "beneficiary_id": str(revision.beneficiary_id),
            "beneficiary_name_snapshot": revision.beneficiary_name_snapshot,
            "beneficiary_iban_snapshot": revision.beneficiary_iban_snapshot,
            "beneficiary_national_id_snapshot": revision.beneficiary_national_id_snapshot,
            "amount_irr": revision.amount_irr,
            "entered_amount_value": revision.entered_amount_value,
            "entered_amount_unit": revision.entered_amount_unit,
            "description": revision.description,
            "source_attachment_file_id": (
                str(revision.source_attachment_file_id)
                if revision.source_attachment_file_id
                else None
            ),
        }
    )


def _require_operable(trader: Trader) -> None:
    """Both axes, because they are different facts.

    `15_Agent_Implementation_Plan.md:806`: a pending or suspended trader cannot create
    or submit. DOC-CONFLICT-024 keeps those on separate columns, so checking one would
    let a suspended-but-approved business keep creating requests — which is precisely
    what suspension is supposed to stop.
    """

    if trader.approval_status != APPROVAL_OK or trader.operational_status != OPERATIONAL_OK:
        raise BusinessRuleViolationError(
            "this business cannot create payment requests: it is "
            f"{trader.approval_status} and {trader.operational_status}"
        )


def _next_request_number(session: Session, now: datetime) -> str:
    """A human-readable unique number, per `04_Database_Schema.md:833`.

    `GP-YYYYMM-NNNN`, counted within the month. Not a global sequence: an operator
    reading a number should be able to tell roughly when it was raised, and a number
    that encodes nothing is one nobody can use on the phone.

    The count is taken inside the same transaction, so two concurrent creations can
    compute the same number — and `UNIQUE(request_number)` is what refuses the second.
    That is the correct division: the database owns uniqueness, and the caller retries.
    A `SELECT max()+1` that pretended to be safe would be the version that silently
    collides.
    """

    prefix = f"GP-{now.strftime('%Y%m')}-"
    used = session.scalar(
        select(func.count())
        .select_from(PaymentRequest)
        .where(PaymentRequest.request_number.startswith(prefix))
    )
    return f"{prefix}{(used or 0) + 1:04d}"


def _audit(
    session: Session,
    policy: RedactionPolicy,
    names: CommandNames,
    *,
    outcome: str,
    request_id: uuid.UUID,
    record_version: int,
    reason: str | None,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
    previous_values: dict[str, Any] | None = None,
    new_values: dict[str, Any] | None = None,
) -> None:
    AuditWriter(session, policy).record(
        AuditEntry(
            action=names.audit_action,
            outcome=outcome,
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="payment_request",
            entity_id=request_id,
            entity_record_version=record_version,
            previous_values=previous_values,
            new_values=new_values,
            reason=reason,
            occurred_at=now,
            metadata={"operation": names.audit_action},
        ),
        actor=actor,
        context=context,
    )
