"""Creating a draft payment request, and cancelling one.

M5 slice 3. Two routes, both serving a trader by ownership and internal staff by
permission — the same shape slice 2 established for beneficiaries, and for the same
reason: a trader actor carries no permissions at all, so a route-level `requires(...)`
would deny every trader, while an in-handler check would be invisible to
`tests/backend/test_permission_guards.py`, which reads the dependency graph.

**Cancel exists because `CON-REQ-001` was unprovable without it.** The obligation is
that `record_version` supports `If-Match` and a stale value returns `412`; a slice
whose only route creates a resource has nothing for `If-Match` to be stale against.
Cancellation is the smallest command that gives it a target, is already in the
milestone (`15_Agent_Implementation_Plan.md:766`), and needs optimistic concurrency on
its own account — two people cancelling the same draft from two screens is ordinary.

Covers: SEC-REQ-001, CON-REQ-001.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor, requires
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.commands import payment_request as commands
from app.core.errors import (
    ErrorEnvelope,
    ForbiddenError,
    NotFoundError,
    PreconditionRequiredError,
    VersionConflictError,
)
from app.core.money import (
    AmountUnitMismatchError,
    Money,
    MoneyUnit,
    parse_integer_string,
)
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.payment_request import PaymentRequest, PaymentRequestRevision
from app.security.actor import ActorContext
from app.security.ownership import require_owned
from app.security.permissions import declare

router = APIRouter(prefix="/payment-requests", tags=["payment-requests"])

# POL-003 is open and `RedactionPolicy` has no default, so the choice is made here and
# visibly. `True`: a revision carries an IBAN snapshot, and the audit rows this route
# writes describe a payment destination. `mask_iban_value` keeps the country prefix and
# last four digits — enough to reconcile against a statement, not enough to originate a
# transfer from the audit trail, which is the right trade for an append-only table no
# runtime role may ever UPDATE.
REQUEST_REDACTION = RedactionPolicy(mask_iban=True)

COMMON_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "Internal caller lacks the permission."},
    404: {"model": ErrorEnvelope, "description": "Missing, or not the caller's."},
    **VALIDATION_ERROR_RESPONSE,
}

WRITE_RESPONSES: dict[int | str, dict[str, object]] = {
    **COMMON_RESPONSES,
    400: {"model": ErrorEnvelope, "description": "A domain rule refused the command."},
    412: {"model": ErrorEnvelope, "description": "The If-Match value is stale."},
    428: {"model": ErrorEnvelope, "description": "If-Match is required."},
}


def owned_or_permitted(trader_permission: str, internal_permission: str) -> Any:
    """Authorise both audiences and hand back the scope to filter by.

    Two permission names rather than one, because the catalogue splits them:
    `payment_request.create_own` is the trader's and `payment_request.create_internal`
    is staff acting for a trader. Both are declared at import so a typo fails the start
    rather than denying everyone silently, and both end up in the closure where
    `test_permission_guards.py` can see them — the trader one is declared and not
    checked, because no trader session can hold it (see the module docstring).
    """

    declared_trader = declare(trader_permission)
    declared_internal = declare(internal_permission)

    def guard(
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> uuid.UUID | None:
        # Both names are read here, and that is deliberate rather than tidy. The gate
        # in `test_permission_guards.py` finds a route's permissions by walking this
        # closure for strings that are approved permission codes, so a name the
        # closure does not carry is a name the gate cannot see. An earlier version
        # wrote `del declared_trader` to mark it unused — which made it a *local* of
        # this function instead of a closure variable, so every call raised
        # `UnboundLocalError` and the name never reached the closure at all.
        required = declared_trader if actor.is_trader else declared_internal

        if actor.is_trader:
            # And the trader's own permission is still not checked: no trader session
            # can hold one (`app/security/actor.py:113-118`), so `required` here names
            # the intent the catalogue records while ownership does the work.
            return actor.trader_id
        if required not in actor.permissions:
            raise ForbiddenError()
        return None

    return Depends(guard)


class EnteredAmountResponse(BaseModel):
    """What the trader typed, nested as document 05 shows it (`:1113`).

    Kept beside `amount_irr` rather than replaced by it. `500 TOMAN` and `5000 IRR`
    are the same money and different intents, and a dispute six months later is about
    the second.
    """

    model_config = ConfigDict(extra="forbid")

    value: str
    unit: str


class DraftRevisionResponse(BaseModel):
    """The nested shape document 05 specifies, **plus** the flat fields slice 3 emitted.

    The flat pair is redundant and deliberately kept. Removing a required response
    property is a breaking change, the oasdiff gate refuses one, and its waiver process
    is an unresolved `TODO(governance)` in `.github/workflows/m1-verify.yml:182` — left
    open through M2 and M3. The M2 plan records the strategy that follows: while no
    waiver exists, changes stay **additive**.

    So slice 4 adds `entered_amount` and keeps `entered_amount_value` and
    `entered_amount_unit` carrying the same values. Inventing a waiver would decide a
    governance question the owner has twice left open; carrying two spellings of one
    fact until they can be removed in a deliberate contract-version bump is the cost of
    not deciding it here.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    revision_number: int
    beneficiary_name_snapshot: str
    beneficiary_iban_snapshot: str
    amount_irr: str
    entered_amount: EnteredAmountResponse | None
    # Deprecated in favour of `entered_amount`. Same values, kept so the change is
    # additive; remove both in the release that bumps the contract version.
    entered_amount_value: str | None
    entered_amount_unit: str | None
    description: str | None
    content_hash: str


class PaymentRequestResponse(BaseModel):
    """Deliberately not the whole row.

    `review_note` and the trader-result columns are absent because nothing in M5 sets
    them, and listing fields explicitly is what keeps a column added later from
    becoming visible by default.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    trader_id: uuid.UUID
    beneficiary_id: uuid.UUID
    request_number: str
    status: str
    current_revision_id: uuid.UUID | None
    record_version: int


class DraftCreated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: PaymentRequestResponse
    revision: DraftRevisionResponse


class AmountRequest(BaseModel):
    """What was typed, and optionally what the client thinks it is worth.

    The nested shape is document 05's (`05_API_Specification.md:1085-1091`). The
    **string** encoding is the approved money contract's — rule 8, "API monetary
    values are base-10 integer strings", and rule 9 forbids JavaScript Number for
    financial amounts. Document 05's example writes them as JSON numbers, which is
    DOC-CONFLICT-050; the contract wins because a JSON number is a float in most
    clients and loses precision above 2^53.

    `amount_irr` is **optional, and verified when present**. Requiring it would push
    the conversion into the client, which `15_Agent_Implementation_Plan.md:802`
    forbids in as many words. Refusing it outright would waste M2's three-way check
    and would reject the exact payload document 05 documents. So the server always
    computes, and a client that offers a figure has it compared rather than trusted.
    """

    model_config = ConfigDict(extra="forbid")

    value: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    unit: str = Field(pattern=r"^(IRR|TOMAN)$")
    amount_irr: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,18}$")


class CreateDraftRequest(BaseModel):
    """Either the nested `amount` object or slice 3's flat fields. Exactly one.

    `amount` is **optional** for the same reason the response keeps its flat pair:
    making it required is a breaking request change, the oasdiff gate refuses one, and
    its waiver is an unresolved `TODO(governance)`. So the nested shape is added rather
    than substituted.

    "Exactly one" is enforced in `_draft_amount` rather than left to precedence. Two
    ways to state the amount is already one more than the money contract wants; two ways
    that could *disagree*, with a rule about which wins, is how a request comes to mean
    two things. A caller that sends both is refused.
    """

    model_config = ConfigDict(extra="forbid")

    beneficiary_id: uuid.UUID
    amount: AmountRequest | None = None
    # Deprecated, and accepted only so slice 3's shape keeps working. Same validation as
    # the nested form: string integers, and the server computes IRR.
    amount_irr: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,18}$")
    entered_amount_value: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,18}$")
    entered_amount_unit: str | None = Field(default=None, pattern=r"^(IRR|TOMAN)$")
    description: str | None = None
    source_attachment_file_id: uuid.UUID | None = None
    # Read only for an internal actor, as on the beneficiary create. For a trader the
    # session's scope wins and this is never consulted.
    trader_id: uuid.UUID | None = None


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


@router.post(
    "",
    response_model=DraftCreated,
    status_code=201,
    operation_id="createPaymentRequestDraft",
    summary="Open a draft payment request and its first immutable revision.",
    responses=WRITE_RESPONSES,
)
def create_draft(
    payload: CreateDraftRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    scope: Annotated[
        uuid.UUID | None,
        owned_or_permitted("payment_request.create_own", "payment_request.create_internal"),
    ],
) -> DraftCreated:
    owner = scope if scope is not None else payload.trader_id
    if owner is None:
        raise NotFoundError()

    now = utc_now()
    with runtime.uow_factory() as uow:
        result = commands.create_draft(
            commands.CreateDraft(
                trader_id=owner,
                beneficiary_id=payload.beneficiary_id,
                amount=_draft_amount(payload),
                description=payload.description,
                source_attachment_file_id=payload.source_attachment_file_id,
            ),
            session=uow.session,
            policy=REQUEST_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            now=now,
        )
        rendered = DraftCreated(
            request=_render(result.request),
            revision=_render_revision(result.revision),
        )
        uow.commit()
    return rendered


@router.post(
    "/{payment_request_id}/cancel",
    response_model=PaymentRequestResponse,
    operation_id="cancelPaymentRequest",
    summary="Cancel a draft. Nothing is deleted; the status moves.",
    responses=WRITE_RESPONSES,
)
def cancel(
    payment_request_id: uuid.UUID,
    payload: CancelRequest,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    scope: Annotated[
        uuid.UUID | None,
        owned_or_permitted("payment_request.cancel", "payment_request.cancel"),
    ],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> PaymentRequestResponse:
    """`If-Match` is required, not optional.

    The stale-tab case: two people acting on the same draft from two screens, where a
    blind write silently discards whichever decision arrived first. `428` when it is
    absent and `412` when it does not match — different answers because the remedies
    differ, and answering `412` to a caller who sent nothing would send them looking
    for a value they never had.
    """

    if if_match is None:
        raise PreconditionRequiredError("If-Match")
    expected = _parse_record_version(if_match)

    now = utc_now()
    with runtime.uow_factory() as uow:
        record = uow.session.get(PaymentRequest, payment_request_id)
        if scope is None:
            if record is None:
                raise NotFoundError()
        else:
            owner = record.trader_id if record is not None else None
            require_owned(record, owner, actor)

        updated = commands.cancel_request(
            commands.CancelPaymentRequest(
                payment_request_id=payment_request_id,
                expected_record_version=expected,
                # Which column of §29.1 applies. `is_trader` is the same fact the
                # ownership branch above turns on, so the authority the command checks and
                # the authority the route checked cannot disagree about who is asking.
                by_trader=actor.is_trader,
                reason=payload.reason,
            ),
            session=uow.session,
            policy=REQUEST_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            now=now,
        )
        rendered = _render(updated)
        uow.commit()

    response.headers["ETag"] = f'"rv-{rendered.record_version}"'
    return rendered


class CreateRevisionRequest(BaseModel):
    """A complete statement of what is being submitted, not a patch.

    Every content field is required. A partial shape would make revision 3's content
    "revision 2 plus a diff", so reading what was submitted the third time would mean
    replaying the first two — and the whole point of an immutable revision is that it
    answers that question on its own.
    """

    model_config = ConfigDict(extra="forbid")

    beneficiary_id: uuid.UUID
    amount: AmountRequest
    description: str | None = None
    source_attachment_file_id: uuid.UUID | None = None
    revision_reason: str | None = Field(default=None, max_length=500)


class RevisionCreated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: PaymentRequestResponse
    revision: DraftRevisionResponse
    # True when an `Idempotency-Key` was replayed. Surfaced rather than hidden: a client
    # retrying after a timeout needs to know it did not create a second revision, and a
    # response identical to the first would leave it guessing.
    replayed: bool


class RevisionHistory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DraftRevisionResponse]
    current_revision_id: uuid.UUID | None


@router.post(
    "/{payment_request_id}/submit",
    response_model=PaymentRequestResponse,
    operation_id="submitPaymentRequest",
    summary="Hand a draft to the centre.",
    responses=WRITE_RESPONSES,
)
def submit(
    payment_request_id: uuid.UUID,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    scope: Annotated[
        uuid.UUID | None,
        owned_or_permitted("payment_request.submit", "payment_request.create_internal"),
    ],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> PaymentRequestResponse:
    """`draft -> submitted_to_center`, under `If-Match`.

    No request body: submission states nothing new. What is being submitted is already
    on the current revision, and a body here would invite a caller to send content that
    the revision does not carry — which is how a request comes to say two things.
    """

    if if_match is None:
        raise PreconditionRequiredError("If-Match")
    expected = _parse_record_version(if_match)

    now = utc_now()
    with runtime.uow_factory() as uow:
        record = uow.session.get(PaymentRequest, payment_request_id)
        if scope is None:
            if record is None:
                raise NotFoundError()
        else:
            owner = record.trader_id if record is not None else None
            require_owned(record, owner, actor)

        updated = commands.submit(
            commands.SubmitRequest(
                payment_request_id=payment_request_id,
                expected_record_version=expected,
            ),
            session=uow.session,
            policy=REQUEST_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            now=now,
        )
        rendered = _render(updated)
        uow.commit()

    response.headers["ETag"] = f'"rv-{rendered.record_version}"'
    return rendered


class ReturnForCorrectionRequest(BaseModel):
    """`05_API_Specification.md:1203-1211`.

    `reason_code` and `message_to_trader` are required because the document says "Reason
    and trader notification are required" — so they are required in the schema, where a
    caller finds out before the command runs, rather than checked in the handler.
    """

    model_config = ConfigDict(extra="forbid")

    reason_code: str = Field(min_length=1, max_length=64)
    message_to_trader: str = Field(min_length=1, max_length=1000)
    internal_note: str | None = Field(default=None, max_length=1000)


class MarkEligibleRequest(BaseModel):
    """`05_API_Specification.md:1223-1227`."""

    model_config = ConfigDict(extra="forbid")

    expected_revision_id: uuid.UUID
    review_note: str | None = Field(default=None, max_length=1000)


# The three accountant routes. Their bodies are near-identical and deliberately written
# out rather than shared through a helper that takes the command as a callable. The first
# draft did share one, and `test_no_io_under_lock.py` caught it: that gate reads the source
# for calls made inside an open write transaction, and a bare `run()` is opaque to it, so
# the abstraction bought three fewer repetitions by making a real guarantee unenforceable
# on all three. The rest of this module is written out longhand for the same reason.
#
# Internal-only, so `requires(declare(...))` rather than
# `owned_or_permitted`: there is no trader audience for any of them, and a trader session
# carries no permissions at all, so routing them through the dual-audience helper would
# declare an authority no trader can hold and read as though one might.
@router.post(
    "/{payment_request_id}/start-review",
    response_model=PaymentRequestResponse,
    operation_id="startPaymentRequestReview",
    summary="Take a submitted request into accountant review.",
    responses=WRITE_RESPONSES,
    dependencies=[requires(declare("payment_request.review"))],
)
def start_review(
    payment_request_id: uuid.UUID,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> PaymentRequestResponse:
    """`submitted_to_center -> under_accountant_review`, under `If-Match`.

    No body, and `If-Match` for the reason document 06 `:642` gives it: two accountants
    opening the same queue is the ordinary race, and the second one should be told the
    request already moved rather than quietly take it over.
    """

    if if_match is None:
        raise PreconditionRequiredError("If-Match")
    expected = _parse_record_version(if_match)

    now = utc_now()
    with runtime.uow_factory() as uow:
        updated = commands.begin_review(
            commands.BeginReview(
                payment_request_id=payment_request_id,
                expected_record_version=expected,
            ),
            session=uow.session,
            policy=REQUEST_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            now=now,
        )
        rendered = _render(updated)
        uow.commit()

    response.headers["ETag"] = f'"rv-{rendered.record_version}"'
    return rendered


@router.post(
    "/{payment_request_id}/request-correction",
    response_model=PaymentRequestResponse,
    operation_id="requestPaymentRequestCorrection",
    summary="Hand a request back to its trader, with a reason.",
    responses=WRITE_RESPONSES,
    dependencies=[requires(declare("payment_request.request_correction"))],
)
def request_correction(
    payment_request_id: uuid.UUID,
    payload: ReturnForCorrectionRequest,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> PaymentRequestResponse:
    """`submitted_to_center | under_accountant_review -> needs_trader_correction`."""

    if if_match is None:
        raise PreconditionRequiredError("If-Match")
    expected = _parse_record_version(if_match)

    now = utc_now()
    with runtime.uow_factory() as uow:
        updated = commands.return_for_correction(
            commands.ReturnForCorrection(
                payment_request_id=payment_request_id,
                expected_record_version=expected,
                reason_code=payload.reason_code,
                message_to_trader=payload.message_to_trader,
                internal_note=payload.internal_note,
            ),
            session=uow.session,
            policy=REQUEST_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            now=now,
        )
        rendered = _render(updated)
        uow.commit()

    response.headers["ETag"] = f'"rv-{rendered.record_version}"'
    return rendered


@router.post(
    "/{payment_request_id}/mark-eligible-for-batching",
    response_model=PaymentRequestResponse,
    operation_id="markPaymentRequestEligibleForBatching",
    summary="Complete accountant review. This is not manager approval.",
    responses=WRITE_RESPONSES,
    dependencies=[requires(declare("payment_request.mark_eligible"))],
)
def mark_eligible_for_batching(
    payment_request_id: uuid.UUID,
    payload: MarkEligibleRequest,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> PaymentRequestResponse:
    """`under_accountant_review -> eligible_for_batching`. Where M5 stops.

    `12_Security_RBAC_Audit.md:904`: "Accountant eligibility is not manager approval." The
    permission is the accountant's, and no manager-only permission is consulted here —
    slice 9 gates that over the whole route table rather than trusting this sentence.
    """

    if if_match is None:
        raise PreconditionRequiredError("If-Match")
    expected = _parse_record_version(if_match)

    now = utc_now()
    with runtime.uow_factory() as uow:
        updated = commands.mark_eligible_for_batching(
            commands.MarkEligibleForBatching(
                payment_request_id=payment_request_id,
                expected_record_version=expected,
                expected_revision_id=payload.expected_revision_id,
                review_note=payload.review_note,
            ),
            session=uow.session,
            policy=REQUEST_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            now=now,
        )
        rendered = _render(updated)
        uow.commit()

    response.headers["ETag"] = f'"rv-{rendered.record_version}"'
    return rendered


@router.post(
    "/{payment_request_id}/revisions",
    response_model=RevisionCreated,
    status_code=201,
    operation_id="createPaymentRequestRevision",
    summary="Correct a request by adding an immutable revision.",
    responses={
        **WRITE_RESPONSES,
        409: {"model": ErrorEnvelope, "description": "The Idempotency-Key was reused."},
    },
)
def create_revision(
    payment_request_id: uuid.UUID,
    payload: CreateRevisionRequest,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    scope: Annotated[
        uuid.UUID | None,
        owned_or_permitted(
            "payment_request.create_revision_own",
            "payment_request.create_revision_internal",
        ),
    ],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RevisionCreated:
    """`If-Match` and `Idempotency-Key` are both required, and they answer different
    questions.

    `If-Match` is "is the request still in the state you read", which is `CON-REQ-002`.
    `Idempotency-Key` is "have I already sent this exact correction", which is
    `SVC-REV-004`. A retry after a network timeout needs the second: the first attempt
    may have committed, and without a key the retry would create revision 3 identical
    to revision 2 — except that `UNIQUE(payment_request_id, content_hash)` would refuse
    it, so the trader would be told their correction was a duplicate of their own
    correction.
    """

    if if_match is None:
        raise PreconditionRequiredError("If-Match")
    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")
    expected = _parse_record_version(if_match)

    now = utc_now()
    with runtime.uow_factory() as uow:
        record = uow.session.get(PaymentRequest, payment_request_id)
        if scope is None:
            if record is None:
                raise NotFoundError()
        else:
            owner = record.trader_id if record is not None else None
            require_owned(record, owner, actor)

        result = commands.create_revision(
            commands.CreateRevision(
                payment_request_id=payment_request_id,
                expected_record_version=expected,
                beneficiary_id=payload.beneficiary_id,
                amount=_money(payload.amount),
                description=payload.description,
                source_attachment_file_id=payload.source_attachment_file_id,
                revision_reason=payload.revision_reason,
            ),
            uow=uow,
            policy=REQUEST_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=idempotency_key,
            now=now,
        )
        rendered = RevisionCreated(
            request=_render(result.request),
            revision=_render_revision(result.revision),
            replayed=result.replayed,
        )
        uow.commit()

    response.headers["ETag"] = f'"rv-{rendered.request.record_version}"'
    return rendered


@router.get(
    "/{payment_request_id}/revisions",
    response_model=RevisionHistory,
    operation_id="listPaymentRequestRevisions",
    summary="Every revision of a request, oldest first.",
    responses=COMMON_RESPONSES,
)
def list_revisions(
    payment_request_id: uuid.UUID,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    scope: Annotated[
        uuid.UUID | None,
        owned_or_permitted("payment_request.read_own", "payment_request.read"),
    ],
) -> RevisionHistory:
    """`SVC-REV-002`: readable in order, and every revision reachable.

    Ordered by `revision_number` rather than `created_at`. Two revisions written in the
    same transaction would share a timestamp to the microsecond, and the number is the
    thing that is guaranteed unique per request.
    """

    with runtime.uow_factory() as uow:
        record = uow.session.get(PaymentRequest, payment_request_id)
        if scope is None:
            if record is None:
                raise NotFoundError()
        else:
            owner = record.trader_id if record is not None else None
            require_owned(record, owner, actor)
        assert record is not None

        rows = list(
            uow.session.scalars(
                select(PaymentRequestRevision)
                .where(PaymentRequestRevision.payment_request_id == payment_request_id)
                .order_by(PaymentRequestRevision.revision_number)
            )
        )
        rendered = RevisionHistory(
            items=[_render_revision(row) for row in rows],
            current_revision_id=record.current_revision_id,
        )
        uow.rollback()
    return rendered


def _draft_amount(payload: CreateDraftRequest) -> Money:
    """One `Money` from whichever shape the caller used, and never from both.

    The flat trio is slice 3's, kept accepted because removing it would be a breaking
    request change and the oasdiff waiver is an unresolved `TODO(governance)`. Both paths
    end in the same `_money`, so the server computes IRR either way and a client-supplied
    figure is verified rather than trusted in both. A compatibility path that skipped the
    checks would be the shape an attacker uses.

    Sending both is refused rather than resolved by precedence. A rule about which wins
    is a rule somebody has to know, and a caller who sends `amount` and a contradicting
    `entered_amount_value` has already lost track of what they are asking for.
    """

    flat = (payload.entered_amount_value, payload.entered_amount_unit, payload.amount_irr)
    sent_flat = any(field is not None for field in flat)

    if payload.amount is not None and sent_flat:
        raise AmountUnitMismatchError(
            "send either `amount` or the deprecated `entered_amount_value`/"
            "`entered_amount_unit`/`amount_irr` fields, not both. The flat fields are "
            "kept only for compatibility and will be removed."
        )

    if payload.amount is not None:
        return _money(payload.amount)

    if payload.entered_amount_value is None or payload.entered_amount_unit is None:
        raise AmountUnitMismatchError(
            "an amount is required: send `amount` as {value, unit}, both as base-10 "
            "integer strings."
        )

    return _money(
        AmountRequest(
            value=payload.entered_amount_value,
            unit=payload.entered_amount_unit,
            amount_irr=payload.amount_irr,
        )
    )


def _money(amount: AmountRequest) -> Money:
    """Turn the wire shape into one checked `Money`.

    Both paths converge on the same three-way check. When the client sent an
    `amount_irr`, `Money.from_wire` compares all three parts and refuses a
    disagreement rather than picking one to believe; when it did not,
    `Money.entered` converts once and the value it derives is by construction
    consistent. Either way the route hands the command a value that has already
    been verified, so nothing downstream re-derives it or has to.

    `AmountUnitMismatchError` is an `AppError` carrying its own 400 and code, so it
    reaches the client as `AMOUNT_UNIT_MISMATCH` rather than as a generic refusal —
    a client that converted wrongly needs to know which of its three numbers the
    server disagreed with.
    """

    try:
        unit = MoneyUnit(amount.unit)
    except ValueError as error:  # pragma: no cover - the pattern already refuses it
        raise AmountUnitMismatchError(
            f"unit must be one of {[member.value for member in MoneyUnit]}"
        ) from error

    if amount.amount_irr is None:
        return Money.entered(parse_integer_string(amount.value, field="value"), unit)

    return Money.from_wire(
        {
            "amount_irr": amount.amount_irr,
            "entered_amount": amount.value,
            "entered_unit": amount.unit,
        }
    )


def _render_revision(revision: PaymentRequestRevision) -> DraftRevisionResponse:
    """Every monetary field as a string, per the money contract's rule 8."""

    entered = None
    if revision.entered_amount_value is not None and revision.entered_amount_unit is not None:
        entered = EnteredAmountResponse(
            value=str(revision.entered_amount_value),
            unit=revision.entered_amount_unit,
        )

    return DraftRevisionResponse(
        id=revision.id,
        revision_number=revision.revision_number,
        beneficiary_name_snapshot=revision.beneficiary_name_snapshot,
        beneficiary_iban_snapshot=revision.beneficiary_iban_snapshot,
        amount_irr=str(revision.amount_irr),
        entered_amount=entered,
        # The deprecated flat pair, from the same source as the nested object so the two
        # cannot disagree. Rendered from `entered` rather than re-read, for that reason.
        entered_amount_value=entered.value if entered else None,
        entered_amount_unit=entered.unit if entered else None,
        description=revision.description,
        content_hash=revision.content_hash,
    )


def _audit_actor(actor: ActorContext) -> AuditActor:
    return AuditActor(
        actor_type=actor.actor_type.value,
        actor_id=actor.actor_id,
        role_snapshot=tuple(sorted(actor.roles)),
        session_id=actor.session_id,
        authentication_assurance=actor.auth_level,
    )


def _render(record: PaymentRequest) -> PaymentRequestResponse:
    return PaymentRequestResponse(
        id=record.id,
        trader_id=record.trader_id,
        beneficiary_id=record.beneficiary_id,
        request_number=record.request_number,
        status=record.status,
        current_revision_id=record.current_revision_id,
        record_version=record.record_version,
    )


def _parse_record_version(value: str) -> int:
    cleaned = value.strip().strip('"')
    if not cleaned.startswith("rv-") or not cleaned[3:].isdigit():
        raise VersionConflictError()
    return int(cleaned[3:])
