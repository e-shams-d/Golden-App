"""Matching a receipt to a statement row. `05_API_Specification.md` §21.5.

M10 slice 5. Propose, reject, and read — and the reject route is the reason the prefix is
`/incoming-payment-receipts`: §21.5 puts creation under the receipt, and a decision about one
candidate needs the candidate's own address.

**Internal only.** `permission_catalog.yaml` gives `incoming_payment.match` to the accountant, with
the manager conditional on `exception_policy_only`, and gives a trader nothing. A trader may claim
they paid — slice 2 — and may not say which bank row proves it; that is the centre's judgement and
the whole reason the two are separate tables.

**Rejecting takes `If-Match`; proposing does not.** A proposal creates a row and a rejection edits
one, and that is the whole rule: `20260909_0040`'s unique on the pair is what makes two
simultaneous proposals safe, while two simultaneous rejections are two people deciding the same
thing and the second must be told.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor, requires
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.commands import incoming_confirmation as confirmation_commands
from app.commands import incoming_match as match_commands
from app.core.errors import (
    ErrorEnvelope,
    ForbiddenError,
    NotFoundError,
    PreconditionRequiredError,
)
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.incoming_match import IncomingPaymentMatch
from app.db.models.incoming_payment import IncomingPaymentReceipt
from app.security.actor import ActorContext
from app.security.permissions import declare

router = APIRouter(prefix="/incoming-payment-receipts", tags=["incoming-payment-matches"])

# A match names a receipt and a statement row and carries no IBAN of its own; the row it points at
# does. Passed explicitly for the reason every call site passes one: POL-003 is open.
MATCH_REDACTION = RedactionPolicy(mask_iban=True)

RESPONSES: dict[int | str, dict[str, object]] = {
    400: {
        "model": ErrorEnvelope,
        "description": "The receipt is closed, the run did not succeed, or the match is not a "
        "proposal.",
    },
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "The caller lacks the permission."},
    404: {"model": ErrorEnvelope, "description": "No such receipt, row or match."},
    409: {
        "model": ErrorEnvelope,
        "description": "This pair is already matched, or the match moved under the caller.",
    },
    428: {"model": ErrorEnvelope, "description": "Idempotency-Key or If-Match is required."},
    **VALIDATION_ERROR_RESPONSE,
}


class ProposeMatchRequest(BaseModel):
    """§21.5's body.

    **No `status` and no `confirmed_amount_irr`.** §21.5: "Candidate acceptance and financial
    confirmation remain separate." A field for either would be a value the command then had to
    refuse, and the strongest refusal is having nowhere for one to arrive.

    **No `match_method` either**, and that one is different: Phase 1A has exactly one method,
    document 08 §8.8's manual search. A field would invite a caller to claim a machine found it.
    """

    model_config = ConfigDict(extra="forbid")

    bank_statement_row_id: uuid.UUID
    # Optional, and null is the honest value for a human who searched. §10.7's CHECK bounds it.
    match_score: Decimal | None = Field(default=None, ge=0, le=1)
    match_reasons: list[str] = Field(default_factory=list)


class RejectMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Required and non-blank. §8.8 requires a match decision to record actor, time and reason.
    rejection_reason: str = Field(min_length=1, max_length=2000)


class MatchResponse(BaseModel):
    """What comes back. The confirmation columns are included **and will be null**.

    Present rather than omitted so a client can see that nobody has agreed with the suggestion yet
    — a response that left them out would read as though the question had not been asked.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    incoming_payment_receipt_id: uuid.UUID
    bank_statement_row_id: uuid.UUID
    status: str
    match_method: str
    match_score: Decimal | None
    match_reasons: list[str]
    confirmed_amount_irr: int | None
    confirmed_at: datetime | None
    rejected_at: datetime | None
    rejection_reason: str | None
    replaces_match_id: uuid.UUID | None
    receipt_status: str
    record_version: int
    created_at: datetime


def _audit_actor(actor: ActorContext) -> AuditActor:
    return AuditActor(
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        role_snapshot=tuple(actor.roles),
        session_id=actor.session_id,
    )


def _require_key(idempotency_key: str | None) -> str:
    if not idempotency_key:
        raise PreconditionRequiredError(
            "Idempotency-Key is required; a retried proposal must not become a second candidate"
        )
    return idempotency_key


def _parse_record_version(if_match: str | None) -> int:
    if not if_match:
        raise PreconditionRequiredError(
            "If-Match is required to reject a match; without it a second accountant's decision "
            "would overwrite the first without either knowing"
        )
    token = if_match.strip().strip('"')
    if token.startswith("rv-"):
        token = token[3:]
    try:
        return int(token)
    except ValueError as error:
        raise PreconditionRequiredError(
            f"If-Match {if_match!r} is not a record version"
        ) from error


def _rendered(match: IncomingPaymentMatch, receipt_status: str) -> MatchResponse:
    return MatchResponse(
        id=match.id,
        incoming_payment_receipt_id=match.incoming_payment_receipt_id,
        bank_statement_row_id=match.bank_statement_row_id,
        status=match.status,
        match_method=match.match_method,
        match_score=match.match_score,
        match_reasons=list(match.match_reasons or []),
        confirmed_amount_irr=match.confirmed_amount_irr,
        confirmed_at=match.confirmed_at,
        rejected_at=match.rejected_at,
        rejection_reason=match.rejection_reason,
        replaces_match_id=match.replaces_match_id,
        receipt_status=receipt_status,
        record_version=match.record_version,
        created_at=match.created_at,
    )


@router.post(
    "/{receipt_id}/matches",
    response_model=MatchResponse,
    status_code=201,
    operation_id="proposeIncomingPaymentMatch",
    summary="Suggest which statement row proves this claim.",
    responses=RESPONSES,
    dependencies=[requires(declare("incoming_payment.match"))],
)
def propose_incoming_match(
    receipt_id: uuid.UUID,
    payload: ProposeMatchRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> MatchResponse:
    """`POST /api/v1/incoming-payment-receipts/{receipt_id}/matches`, per `:2002`.

    **No `If-Match`.** A proposal creates a row rather than editing one, and what makes two
    simultaneous proposals safe is §10.7's unique on the pair — a record version could not have
    expressed that, because there is no prior version of a row that does not exist yet.

    201: a suggestion exists. Nothing has been confirmed, and the response says so by carrying a
    null `confirmed_amount_irr` rather than omitting the field.
    """

    key = _require_key(idempotency_key)
    now = utc_now()

    if actor.actor_id is None:
        raise ForbiddenError()

    with runtime.uow_factory() as uow:
        result = match_commands.propose_match(
            match_commands.ProposeMatch(
                incoming_payment_receipt_id=receipt_id,
                bank_statement_row_id=payload.bank_statement_row_id,
                match_reasons=list(payload.match_reasons),
                match_score=payload.match_score,
            ),
            uow=uow,
            policy=MATCH_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=key,
            now=now,
        )
        response = _rendered(result.match, result.receipt_status)
        uow.commit()

    return response


@router.post(
    "/{receipt_id}/matches/{match_id}/reject",
    response_model=MatchResponse,
    operation_id="rejectIncomingPaymentMatch",
    summary="Refuse a suggested match, with a reason.",
    responses=RESPONSES,
    dependencies=[requires(declare("incoming_payment.match"))],
)
def reject_incoming_match(
    receipt_id: uuid.UUID,
    match_id: uuid.UUID,
    payload: RejectMatchRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> MatchResponse:
    """Not a path §21.5 spells out, and the reason it exists is `:2002`'s own sentence.

    "Candidate acceptance and financial confirmation remain separate" describes two decisions, and
    a surface offering only the first would leave an accountant no way to record the second half of
    a judgement — a wrong suggestion would have to be left sitting or silently ignored. The address
    follows §21.5's own shape: the candidate under the receipt it belongs to.

    **`If-Match` is required here and not on the proposal**, because this edits a row that already
    exists and two accountants deciding the same candidate must not overwrite each other.
    """

    expected = _parse_record_version(if_match)
    key = _require_key(idempotency_key)
    now = utc_now()

    if actor.actor_id is None:
        raise ForbiddenError()

    with runtime.uow_factory() as uow:
        stored = uow.session.get(IncomingPaymentMatch, match_id)
        if stored is None or stored.incoming_payment_receipt_id != receipt_id:
            # A match id that belongs to another receipt is 404 rather than 400: the path asserts a
            # relationship, and answering "wrong receipt" would confirm the match exists.
            uow.rollback()
            raise NotFoundError()

        result = match_commands.reject_match(
            match_commands.RejectMatch(
                incoming_payment_match_id=match_id,
                expected_record_version=expected,
                rejection_reason=payload.rejection_reason,
            ),
            uow=uow,
            policy=MATCH_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=key,
            now=now,
        )
        response = _rendered(result.match, result.receipt_status)
        uow.commit()

    return response


class ConfirmRequest(BaseModel):
    """§21.6's body, field for field.

    `incoming_payment_match_id` is **nullable in the specification itself**, and the reason is
    document 08 §8.9's first edge case: evidence can arrive before the statement does. A
    confirmation with no match is a person taking responsibility without a bank row to point at,
    which is a different act from one with a row — and the audit entry records which.
    """

    model_config = ConfigDict(extra="forbid")

    confirmed_amount_irr: int = Field(gt=0)
    incoming_payment_match_id: uuid.UUID | None = None
    confirmation_note: str | None = Field(default=None, max_length=2000)


class ConfirmationResponse(BaseModel):
    """What the order now believes, not only what this receipt did.

    `confirmed_total_irr` beside `expected_amount_irr` is the whole point of §21.6's "not silently
    treated as fully paid": a client that saw only this receipt's figure could not tell a partial
    payment from a complete one.
    """

    model_config = ConfigDict(extra="forbid")

    receipt_id: uuid.UUID
    receipt_status: str
    confirmed_amount_irr: int | None
    order_status: str
    confirmed_total_irr: int
    expected_amount_irr: int | None
    record_version: int


@router.post(
    "/{receipt_id}/confirm",
    response_model=ConfirmationResponse,
    operation_id="confirmIncomingPayment",
    summary="Record that the money arrived, and what the order now totals.",
    responses=RESPONSES,
    dependencies=[requires(declare("incoming_payment.confirm"))],
)
def confirm_incoming_payment(
    receipt_id: uuid.UUID,
    payload: ConfirmRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ConfirmationResponse:
    """`POST /api/v1/incoming-payment-receipts/{receipt_id}/confirm`, per `:2011`.

    **A different permission from the matching routes above.** `incoming_payment.match` proposes;
    `incoming_payment.confirm` decides. `permission_catalog.yaml` separates them and gives the
    manager a different conditional on each — `exception_policy_only` against
    `exception_or_policy_approval_only` — which is M0 saying the two acts are not one.

    **The overpayment refusal commits its own review task.** `OverpaymentRefused` is caught here
    rather than in the command so the transaction carrying the task can commit before the error
    becomes a 400. M9's first version raised a plain business error and lost the task with the
    rolled-back transaction; §21.6 requires both the refusal and the task, and a refusal nobody
    follows up is the outcome that rule exists to prevent.
    """

    expected = _parse_record_version(if_match)
    key = _require_key(idempotency_key)
    now = utc_now()

    if actor.actor_id is None:
        raise ForbiddenError()

    with runtime.uow_factory() as uow:
        try:
            result = confirmation_commands.confirm_incoming_payment(
                confirmation_commands.ConfirmIncomingPayment(
                    incoming_payment_receipt_id=receipt_id,
                    expected_record_version=expected,
                    confirmed_amount_irr=payload.confirmed_amount_irr,
                    incoming_payment_match_id=payload.incoming_payment_match_id,
                    confirmation_note=payload.confirmation_note,
                ),
                uow=uow,
                policy=MATCH_REDACTION,
                actor=_audit_actor(actor),
                context=AuditContext(request_id=get_request_id()),
                idempotency_key=key,
                now=now,
            )
        except confirmation_commands.OverpaymentRefused:
            # The task is the point of the refusal. Commit it, then let the error become a 400.
            uow.commit()
            raise

        response = ConfirmationResponse(
            receipt_id=result.receipt.id,
            receipt_status=result.receipt.status,
            confirmed_amount_irr=result.receipt.confirmed_amount_irr,
            order_status=result.order_status,
            confirmed_total_irr=result.confirmed_total_irr,
            expected_amount_irr=result.expected_amount_irr,
            record_version=result.receipt.record_version,
        )
        uow.commit()

    return response


@router.get(
    "/{receipt_id}/matches",
    response_model=list[MatchResponse],
    operation_id="listIncomingPaymentMatches",
    summary="Every candidate proposed for this claim.",
    responses=RESPONSES,
    dependencies=[requires(declare("incoming_receipt.read"))],
)
def list_incoming_matches(
    receipt_id: uuid.UUID,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> list[MatchResponse]:
    """Not in §21.5's one line, and it is what makes the other two reviewable.

    A rejected candidate is history rather than a deletion — §10.7's whole shape is "Multiple
    records support partial/combined scenarios and corrections" — and history nobody can read is
    indistinguishable from a row that was removed. Ordered oldest first, so the sequence of
    judgements reads forwards.

    `incoming_receipt.read` rather than `incoming_payment.match`: reading who suggested what is a
    manager's and an auditor's question as much as an accountant's, and the catalogue gives the
    read permission to all three.
    """

    with runtime.uow_factory() as uow:
        receipt = uow.session.get(IncomingPaymentReceipt, receipt_id)
        if receipt is None:
            uow.rollback()
            raise NotFoundError()
        rows = list(
            uow.session.scalars(
                select(IncomingPaymentMatch)
                .where(IncomingPaymentMatch.incoming_payment_receipt_id == receipt_id)
                .order_by(IncomingPaymentMatch.created_at.asc())
            )
        )
        response = [_rendered(row, receipt.status) for row in rows]
        uow.rollback()

    return response
