"""Creating a draft request, and cancelling one.

M5 slice 3. Two commands, one transaction each, neither committing — the route owns
the boundary.

**A draft is a request and its first revision, or neither.** They are inserted in one
transaction and each references the other, which is why the composite pointer is
`DEFERRABLE INITIALLY DEFERRED`. A request with no revision has no content and would
sit in a queue as an empty row nobody can act on.

**Why cancellation is here when the plan listed only `create_draft`.** `CON-REQ-001`
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

from app.audit.outbox import OutboxMessage, OutboxWriter
from app.audit.redaction import RedactionPolicy
from app.audit.registry import (
    BEGIN_REVIEW,
    CANCEL_PAYMENT_REQUEST,
    CREATE_PAYMENT_REQUEST,
    CREATE_REVISION,
    MARK_ELIGIBLE_FOR_BATCHING,
    RETURN_FOR_CORRECTION,
    SUBMIT_PAYMENT_REQUEST,
    CommandNames,
)
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.core.hashing import unversioned_digest
from app.core.money import Money
from app.db.concurrency import compare_and_swap
from app.db.models.beneficiary import Beneficiary
from app.db.models.file_object import FileObject
from app.db.models.payment_request import PaymentRequest, PaymentRequestRevision
from app.db.models.trader import Trader
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.files.states import AVAILABLE
from app.idempotency import IdempotencyResolver

PAYLOAD_VERSION = 1
METADATA_SCHEMA = "audit.payment_request.lifecycle"
METADATA_VERSION = 1

DRAFT = "draft"
CANCELLED = "cancelled"
SUBMITTED = "submitted_to_center"
NEEDS_CORRECTION = "needs_trader_correction"
UNDER_REVIEW = "under_accountant_review"
ELIGIBLE = "eligible_for_batching"

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

@dataclass(frozen=True, slots=True)
class CancelRule:
    trader_may: bool
    reason_required: bool


# `06_Workflows_and_State_Machines.md:1367-1375` — §29.1, "Cancellation and Void Rules",
# which is the authority for this and not the §13.2 diagram. The diagram declares
# `cancelled` as a state and draws no arrow into it, so a rule built from it would prove
# that cancellation is never permitted at all. Slice 3 wrote `CANCELLABLE = (DRAFT,)` and
# deferred the rest to this slice, citing the review workflow for it — the deferral was
# right and the citation was wrong.
#
# Restricted to the states M5 reaches: §29.1 also covers `batched` ("only by
# replacement/removal") and `sent_to_bank` and later ("no normal cancellation"), and M6
# owns both. Absent from this table means refused, which is what makes adding a state to
# the milestone a decision rather than an omission.
#
# The trader column is where the document is specific, and `under_accountant_review` is
# the row that matters: it says "Internal with reason" where its neighbours say
# "Trader/internal", so the exclusion is deliberate — a trader cannot pull a request out
# from under the accountant reading it. `draft` says only "Trader may cancel"; internal is
# permitted here too, because that row names who normally does it rather than forbidding
# anyone, and an internal actor who created a draft under
# `payment_request.create_internal` would otherwise be unable to cancel what they made.
CANCELLABLE: dict[str, CancelRule] = {
    DRAFT: CancelRule(trader_may=True, reason_required=False),
    SUBMITTED: CancelRule(trader_may=True, reason_required=True),
    UNDER_REVIEW: CancelRule(trader_may=False, reason_required=True),
    NEEDS_CORRECTION: CancelRule(trader_may=True, reason_required=True),
    # No reason required, which is not what I wrote first. §29.1's cell reads
    # "Internal/trader if no active allocation" — a guard, and no mention of a reason —
    # while its three predecessors all say "reason". The parser in
    # `tests/backend/test_review_transitions.py` caught the difference.
    #
    # Requiring one anyway would be an unmandated refusal, which is the same error as the
    # unmandated side effect this slice removed from `create_revision`, only pointing the
    # other way. The allocation guard is real and arrives with M6, which is what creates
    # allocations; until then there is never an active one.
    ELIGIBLE: CancelRule(trader_may=True, reason_required=False),
}


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
class CancelPaymentRequest:
    """`by_trader` has no default on purpose.

    It selects between the two actor columns of §29.1, and the internal one is the more
    permissive. A default would mean a caller who forgot to pass it got the wider
    authority, which is the wrong direction for a field that decides an authority.
    """

    payment_request_id: uuid.UUID
    expected_record_version: int
    by_trader: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class SubmitRequest:
    payment_request_id: uuid.UUID
    expected_record_version: int


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


def cancel_request(
    command: CancelPaymentRequest,
    *,
    session: Session,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> PaymentRequest:
    """Cancel a request, under optimistic concurrency.

    Named `cancel_draft` until this slice, when §29.1's other four states arrived and the
    name stopped being true.

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

    rule = CANCELLABLE.get(request.status)
    if rule is None:
        raise BusinessRuleViolationError(
            f"a {request.status} request is not cancelled; §29.1 permits cancellation from "
            f"{', '.join(CANCELLABLE)}, and a request that has reached batching is "
            "withdrawn by replacing the batch version instead"
        )
    if command.by_trader and not rule.trader_may:
        raise BusinessRuleViolationError(
            f"a {request.status} request is cancelled by the centre, not by its trader; "
            "it is with an accountant, and withdrawing it from under them is what a "
            "correction request is for"
        )
    if rule.reason_required and not (command.reason or "").strip():
        raise BusinessRuleViolationError(
            f"cancelling a {request.status} request requires a reason; only a draft, "
            "which nobody else has seen, may be abandoned without one"
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


def submit(
    command: SubmitRequest,
    *,
    session: Session,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> PaymentRequest:
    """Hand a request to the centre. `draft | needs_trader_correction -> submitted_to_center`.

    Both origins, per document 06's transition table at `:641`. The correction case is
    what makes the milestone's Definition of Done read "resubmit": a returned request goes
    back to the centre because its owner says so, in a command that can be refused for the
    same reasons a first submission can, not as a side effect of editing.

    **Submission does not write the snapshot; it verifies one.** The plan originally said
    the columns are filled here, and that is not implementable: a revision cannot be
    updated, so there is nothing for submission to fill, and creating a revision at
    submit would produce a byte-identical second row that
    `UNIQUE(payment_request_id, content_hash)` refuses — a trader could not submit an
    unmodified draft. The snapshot is taken where content is stated, by `create_draft`
    and `create_revision`.

    So what is left here is the check that the thing being handed over is complete, and
    it is worth doing rather than assuming: a request that reaches a reviewer without a
    beneficiary name is one nobody can act on, and the database's NOT NULL constraints
    are the only other thing standing behind it.

    The outbox event is the first in this aggregate. Draft creation and cancellation
    publish nothing — nothing outside the platform acts on a trader opening or abandoning
    a draft — but submission has a real audience: this is the moment the centre's queue
    changes, and `05_API_Specification.md:878` requires an event for it.
    """

    request = session.get(PaymentRequest, command.payment_request_id)
    if request is None:
        raise NotFoundError()

    if request.status not in CORRECTABLE:
        raise BusinessRuleViolationError(
            f"only {' or '.join(CORRECTABLE)} is submitted; this request is "
            f"{request.status}"
        )

    trader = session.get(Trader, request.trader_id)
    if trader is None:  # pragma: no cover - the request's FK guarantees it
        raise NotFoundError()
    _require_operable(trader)

    revision = session.get(PaymentRequestRevision, request.current_revision_id)
    if revision is None:
        raise BusinessRuleViolationError(
            "this request has no current revision, so there is no content to submit"
        )

    _require_complete_snapshot(revision)
    _require_attachment_is_available(session, revision)

    # Read before the swap: the audit row must name the state this actually left, and
    # after the correction origin was added that is no longer always `draft`.
    previous_status = request.status

    outcome = compare_and_swap(
        session,
        PaymentRequest,
        entity_id=request.id,
        expected_version=command.expected_record_version,
        values={"status": SUBMITTED, "submitted_at": now},
    )
    session.expire(request)

    _audit(
        session,
        policy,
        SUBMIT_PAYMENT_REQUEST,
        outcome="success",
        request_id=request.id,
        record_version=outcome.new_version,
        reason=None,
        actor=actor,
        context=context,
        now=now,
        previous_values={"status": previous_status},
        new_values={"status": SUBMITTED, "revision_number": revision.revision_number},
    )
    _publish(session, policy, SUBMIT_PAYMENT_REQUEST, request, context, outcome.new_version)

    return request


@dataclass(frozen=True, slots=True)
class Transition:
    """One row of document 06's transition table, as the code enforces it.

    A declaration the guard itself reads, rather than a description beside a hand-written
    `if`. `SVC-REVIEW-001` enumerates the documented transitions and compares them against
    this tuple, so a row the document gains and the code does not is a failure rather than
    a silence — and a guard that drifts from its own declaration cannot happen, because
    there is only one of them.
    """

    command_id: str
    origins: tuple[str, ...]
    destination: str


# `06_Workflows_and_State_Machines.md:585-589` and its table at `:642-644`. Command ids are
# the catalogued ones from `command_catalog.yaml`, which is what the audit rows and
# idempotency records carry.
START_REVIEW = Transition(
    command_id="payment_request.start_review",
    origins=(SUBMITTED,),
    destination=UNDER_REVIEW,
)
REQUEST_CORRECTION = Transition(
    command_id="payment_request.request_correction",
    # Both origins. `:586` draws the arrow from `submitted_to_center` and `:643` writes the
    # origin as "submitted/review": an accountant who can see at a glance that the IBAN is
    # wrong should not have to open a review first in order to hand it back.
    origins=(SUBMITTED, UNDER_REVIEW),
    destination=NEEDS_CORRECTION,
)
MARK_ELIGIBLE = Transition(
    command_id="payment_request.mark_eligible",
    origins=(UNDER_REVIEW,),
    destination=ELIGIBLE,
)

REVIEW_TRANSITIONS: tuple[Transition, ...] = (START_REVIEW, REQUEST_CORRECTION, MARK_ELIGIBLE)


@dataclass(frozen=True, slots=True)
class BeginReview:
    payment_request_id: uuid.UUID
    expected_record_version: int


@dataclass(frozen=True, slots=True)
class ReturnForCorrection:
    """`05_API_Specification.md:1203-1211`. Reason and trader message are both required.

    Required in the type, not checked in the body: a return with no reason is a request a
    trader cannot act on, and "Reason and trader notification are required" is the
    document's sentence rather than an inference. `internal_note` is the accountant's own
    and is not sent to the trader.
    """

    payment_request_id: uuid.UUID
    expected_record_version: int
    reason_code: str
    message_to_trader: str
    internal_note: str | None = None


@dataclass(frozen=True, slots=True)
class MarkEligibleForBatching:
    """`05_API_Specification.md:1223-1227`.

    `expected_revision_id` is the guard document 06 `:644` calls "current revision valid":
    the accountant states which revision they validated, and a correction that landed
    while they were reading makes the command fail rather than mark a superseded revision
    eligible.
    """

    payment_request_id: uuid.UUID
    expected_record_version: int
    expected_revision_id: uuid.UUID
    review_note: str | None = None


def _require_transition(request: PaymentRequest, transition: Transition) -> None:
    if request.status not in transition.origins:
        raise BusinessRuleViolationError(
            f"{transition.command_id} moves a request to {transition.destination} from "
            f"{' or '.join(transition.origins)}; this request is {request.status}"
        )


def _move(
    *,
    names: CommandNames,
    transition: Transition,
    request_id: uuid.UUID,
    expected_record_version: int,
    session: Session,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
    extra_values: dict[str, Any] | None = None,
    reason: str | None = None,
    extra_audit: dict[str, Any] | None = None,
) -> PaymentRequest:
    """The shared body of the three accountant transitions.

    They differ in their guards, their reason, and whether they publish; they do not
    differ in how they move a status, and writing that three times is how the third one
    ends up without a `compare_and_swap`.
    """

    request = session.get(PaymentRequest, request_id)
    if request is None:
        raise NotFoundError()

    _require_transition(request, transition)

    previous_status = request.status
    outcome = compare_and_swap(
        session,
        PaymentRequest,
        entity_id=request_id,
        expected_version=expected_record_version,
        values={"status": transition.destination, **(extra_values or {})},
    )
    session.expire(request)

    _audit(
        session,
        policy,
        names,
        outcome="success",
        request_id=request_id,
        record_version=outcome.new_version,
        reason=reason,
        actor=actor,
        context=context,
        now=now,
        previous_values={"status": previous_status},
        new_values={"status": transition.destination, **(extra_audit or {})},
    )

    if names.outbox_event_type is not None:
        _publish(session, policy, names, request, context, outcome.new_version)

    return request


def begin_review(
    command: BeginReview,
    *,
    session: Session,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> PaymentRequest:
    """`submitted_to_center -> under_accountant_review`.

    No body and no reason: starting to read something is not a decision about it. The
    request's status is the only thing that changes, and it changes so that a second
    accountant opening the same queue can see somebody already has it.
    """

    return _move(
        names=BEGIN_REVIEW,
        transition=START_REVIEW,
        request_id=command.payment_request_id,
        expected_record_version=command.expected_record_version,
        session=session,
        policy=policy,
        actor=actor,
        context=context,
        now=now,
    )


def return_for_correction(
    command: ReturnForCorrection,
    *,
    session: Session,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> PaymentRequest:
    """`submitted_to_center | under_accountant_review -> needs_trader_correction`.

    The one accountant action with an audience outside the centre, so the one that
    publishes: `PaymentRequestCorrectionRequested` is in the outbox catalogue precisely
    because a trader has to be told their request is waiting on them.

    The reason is audited. A request handed back without a recorded reason is one nobody
    can answer for later, and this is the transition a dispute is most likely to turn on.
    """

    return _move(
        names=RETURN_FOR_CORRECTION,
        transition=REQUEST_CORRECTION,
        request_id=command.payment_request_id,
        expected_record_version=command.expected_record_version,
        session=session,
        policy=policy,
        actor=actor,
        context=context,
        now=now,
        reason=command.reason_code,
        extra_audit={
            "reason_code": command.reason_code,
            # The trader-facing message, recorded so the trail holds what they were
            # actually told. The internal note is deliberately not audited here: it is the
            # accountant's working note, and `12_Security_RBAC_Audit.md` keeps the audit
            # trail to what was decided rather than what was thought.
            "message_to_trader": command.message_to_trader,
        },
    )


def mark_eligible_for_batching(
    command: MarkEligibleForBatching,
    *,
    session: Session,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> PaymentRequest:
    """`under_accountant_review -> eligible_for_batching`. Where M5 stops.

    This is accountant review completion and **not** manager approval —
    `12_Security_RBAC_Audit.md:904` says so in one sentence, and slice 9 gates it. The
    permission is `payment_request.mark_eligible`, which the role matrix gives an
    accountant; nothing manager-only is consulted here.
    """

    request = session.get(PaymentRequest, command.payment_request_id)
    if request is None:
        raise NotFoundError()

    # Before the transition guard, because "you validated a revision that is no longer
    # current" is the more useful refusal of the two when both are true.
    if request.current_revision_id != command.expected_revision_id:
        raise BusinessRuleViolationError(
            "the revision named here is not the current one, so marking it eligible "
            "would send a superseded revision for batching; re-read the request"
        )

    return _move(
        names=MARK_ELIGIBLE_FOR_BATCHING,
        transition=MARK_ELIGIBLE,
        request_id=command.payment_request_id,
        expected_record_version=command.expected_record_version,
        session=session,
        policy=policy,
        actor=actor,
        context=context,
        now=now,
        reason=command.review_note,
        extra_audit={"revision_id": str(command.expected_revision_id)},
    )


def _require_complete_snapshot(revision: PaymentRequestRevision) -> None:
    """SVC-SUB-001. Every column document 04 marks required must be populated.

    `beneficiary_national_id_snapshot` is deliberately absent from this list: document 04
    marks it optional, because not every recipient has one on file, and requiring it here
    would refuse legitimate requests.
    """

    missing = [
        name
        for name in (
            "beneficiary_name_snapshot",
            "beneficiary_iban_snapshot",
            "amount_irr",
            "content_hash",
        )
        if not getattr(revision, name, None)
    ]
    if missing:
        raise BusinessRuleViolationError(
            f"the current revision is missing {', '.join(missing)}, so it cannot be "
            "submitted: a reviewer would receive a request they cannot act on"
        )


def _require_attachment_is_available(session: Session, revision: PaymentRequestRevision) -> None:
    """SVC-SUB-003. M4's file states carry the meaning; this is the first consumer.

    `available` is the only state that means hashed and scanned clean — M4's migration
    encodes that in a CHECK. A `pending` attachment has not finished inspection and a
    `quarantined` one failed it, and submitting either would put a request in front of a
    reviewer whose evidence might be a malicious file nobody has cleared.

    A missing attachment is fine: document 04 marks the column nullable and not every
    request has a receipt.
    """

    if revision.source_attachment_file_id is None:
        return

    attachment = session.get(FileObject, revision.source_attachment_file_id)
    if attachment is None:  # pragma: no cover - the FK guarantees it
        raise NotFoundError()

    if attachment.storage_status != AVAILABLE:
        raise BusinessRuleViolationError(
            f"the attached file is {attachment.storage_status}, not available. Only a "
            "file that has been hashed and scanned clean can be submitted as evidence."
        )


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
        # The pointer moves and the status does not. Document 06's transition table at
        # `:640` says a revision leaves the request in the "same aggregate state", and
        # `:641` gives submit both `draft` and `needs_trader_correction` as origins — so
        # resubmission is a command the trader issues, not a side effect of correcting.
        #
        # This used to set `status: SUBMITTED` unconditionally, reasoning that a
        # correction the accountant asked for is not finished until the centre is told.
        # True, and still the wrong place: the same line also submitted a *draft* the
        # moment its owner edited it, so a trader who fixed a typo had filed the request,
        # and `submit` — which then only accepted `draft` — could never be called on it.
        # Nothing in slice 5's obligations asked for the status to move here.
        values={"current_revision_id": revision.id},
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


def _publish(
    session: Session,
    policy: RedactionPolicy,
    names: CommandNames,
    request: PaymentRequest,
    context: AuditContext,
    version: int,
) -> None:
    """One event, in the same transaction as the audit row and the status change.

    The payload carries identifiers and nothing else. A consumer that needs the amount
    or the beneficiary reads the aggregate; putting them on a queue would widen where a
    payment destination and a sum live, for no gain — the same reasoning
    `trader_lifecycle._publish` applies to a phone number.
    """

    if names.outbox_event_type is None:  # pragma: no cover - only submit publishes
        return

    OutboxWriter(session, policy).enqueue(
        OutboxMessage(
            aggregate_type="payment_request",
            aggregate_id=request.id,
            aggregate_version=version,
            event_type=names.outbox_event_type,
            payload={
                "payment_request_id": str(request.id),
                "trader_id": str(request.trader_id),
                "request_number": request.request_number,
            },
            payload_version=PAYLOAD_VERSION,
            correlation_id=context.correlation_id,
            causation_id=context.causation_id,
        )
    )
