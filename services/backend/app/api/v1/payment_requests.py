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

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor
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
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    revision_number: int
    beneficiary_name_snapshot: str
    beneficiary_iban_snapshot: str
    amount_irr: str
    entered_amount: EnteredAmountResponse | None
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
    model_config = ConfigDict(extra="forbid")

    beneficiary_id: uuid.UUID
    amount: AmountRequest
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
                amount=_money(payload.amount),
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

        updated = commands.cancel_draft(
            commands.CancelDraft(
                payment_request_id=payment_request_id,
                expected_record_version=expected,
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
