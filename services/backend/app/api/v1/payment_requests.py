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
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.payment_request import PaymentRequest
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


class DraftRevisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    revision_number: int
    beneficiary_name_snapshot: str
    beneficiary_iban_snapshot: str
    amount_irr: str
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


class CreateDraftRequest(BaseModel):
    """Money crosses as a string integer, per `15_Agent_Implementation_Plan.md:800`.

    Slice 4 owns the conversion and the refusals; this accepts what it is given and
    the database's `amount_irr > 0` CHECK is what refuses a nonsense value in the
    meantime.
    """

    model_config = ConfigDict(extra="forbid")

    beneficiary_id: uuid.UUID
    amount_irr: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
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
                amount_irr=int(payload.amount_irr),
                entered_amount_value=(
                    int(payload.entered_amount_value)
                    if payload.entered_amount_value is not None
                    else None
                ),
                entered_amount_unit=payload.entered_amount_unit,
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
            revision=DraftRevisionResponse(
                id=result.revision.id,
                revision_number=result.revision.revision_number,
                beneficiary_name_snapshot=result.revision.beneficiary_name_snapshot,
                beneficiary_iban_snapshot=result.revision.beneficiary_iban_snapshot,
                amount_irr=str(result.revision.amount_irr),
                entered_amount_value=(
                    str(result.revision.entered_amount_value)
                    if result.revision.entered_amount_value is not None
                    else None
                ),
                entered_amount_unit=result.revision.entered_amount_unit,
                description=result.revision.description,
                content_hash=result.revision.content_hash,
            ),
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
