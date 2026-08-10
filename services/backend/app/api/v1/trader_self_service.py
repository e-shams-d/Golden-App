"""What a trader may see and change about their own business.

The first routes whose scope is ownership rather than a permission. A trader holds
no grants at all — `04_Database_Schema.md:405` makes trader access
ownership-scoped — so the guard here is `ActorContext.trader_id`, and it comes
from the session cookie by way of `trader_users.trader_id`. Nothing the caller
sends reaches it, which is what makes the mandatory IDOR case *"trader A submits
`trader_id` belonging to B"* (`14_Testing_QA_Acceptance.md:1280`) unrepresentable
rather than merely rejected: there is no field to submit it in.

**The patch allowlist is narrow, and two exclusions are load-bearing.**
`05_API_Specification.md:925` requires phone/login changes to use a controlled
identity workflow rather than a profile patch — a trader who could change
`primary_phone` here would be editing an identity the center approved. And the
two status columns are absent because they are the center's decisions about the
trader, not the trader's about themselves; a self-service route that could set
`approval_status` would let a business approve itself.

Covers: API-PROFILE-001, API-PROFILE-002, SEC-IDOR-001.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor
from app.core.errors import (
    ErrorEnvelope,
    NotFoundError,
    PreconditionRequiredError,
    VersionConflictError,
)
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.trader import Trader
from app.security.actor import ActorContext

router = APIRouter(prefix="/me/trader", tags=["trader-self-service"])

OWNED_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    404: {"model": ErrorEnvelope, "description": "Missing, or not the caller's."},
    **VALIDATION_ERROR_RESPONSE,
}

PATCH_RESPONSES: dict[int | str, dict[str, object]] = {
    **OWNED_RESPONSES,
    412: {"model": ErrorEnvelope, "description": "The If-Match value is stale."},
    428: {"model": ErrorEnvelope, "description": "If-Match is required."},
}


class TraderProfileResponse(BaseModel):
    """Deliberately not the whole row.

    `notes_internal` is marked "Never trader-visible" in `04_Database_Schema.md:464`
    and `risk_level` is an internal advisory label; neither appears here. Listing
    fields explicitly rather than serialising the model is what keeps a column
    added later from becoming trader-visible by default.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    display_name: str
    legal_name: str | None
    primary_phone: str
    operational_status: str
    approval_status: str
    approved_at: datetime | None
    credit_limit_irr: int | None
    record_version: int


class TraderProfilePatch(BaseModel):
    """Only what a trader may change about itself.

    Absent on purpose: `primary_phone` (an identity change, `:925`), both status
    columns and `approved_at` (the center's decisions, not the trader's),
    `credit_limit_irr` (a limit the trader would otherwise raise), `risk_level`
    and `notes_internal` (internal).
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    legal_name: str | None = Field(default=None, max_length=255)


@router.get(
    "/profile",
    response_model=TraderProfileResponse,
    operation_id="getOwnTraderProfile",
    summary="The caller's own trader business.",
    responses=OWNED_RESPONSES,
)
def own_profile(
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> TraderProfileResponse:
    with runtime.uow_factory() as uow:
        session = uow.session
        trader = session.get(Trader, actor.trader_id) if actor.is_trader else None
        if trader is None:
            uow.rollback()
            raise NotFoundError()
        response = _render(trader)
        uow.rollback()
    return response


@router.patch(
    "/profile",
    response_model=TraderProfileResponse,
    operation_id="updateOwnTraderProfile",
    summary="Change the non-sensitive fields of the caller's own business.",
    responses=PATCH_RESPONSES,
)
def update_own_profile(
    payload: TraderProfilePatch,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> TraderProfileResponse:
    """`If-Match` is required, not optional.

    `05_API_Specification.md:919` requires it, and the reason is the stale-tab
    case: two people editing the same business from two screens, where a blind
    write silently discards whichever change arrived first.
    """

    if if_match is None:
        raise PreconditionRequiredError("If-Match")

    expected = _parse_record_version(if_match)
    now = utc_now()

    with runtime.uow_factory() as uow:
        session = uow.session
        trader = session.get(Trader, actor.trader_id) if actor.is_trader else None
        if trader is None:
            uow.rollback()
            raise NotFoundError()

        if trader.record_version != expected:
            uow.rollback()
            raise VersionConflictError()

        changes = payload.model_dump(exclude_unset=True)
        for field_name, value in changes.items():
            setattr(trader, field_name, value)

        if changes:
            trader.record_version += 1
            trader.updated_at = now

        rendered = _render(trader)
        uow.commit()

    response.headers["ETag"] = f'"rv-{rendered.record_version}"'
    return rendered


def _render(trader: Trader) -> TraderProfileResponse:
    return TraderProfileResponse(
        id=trader.id,
        display_name=trader.display_name,
        legal_name=trader.legal_name,
        primary_phone=trader.primary_phone,
        operational_status=trader.operational_status,
        approval_status=trader.approval_status,
        approved_at=trader.approved_at,
        credit_limit_irr=trader.credit_limit_irr,
        record_version=trader.record_version,
    )


def _parse_record_version(value: str) -> int:
    """Accept the `"rv-N"` form this API emits, and refuse anything else.

    A malformed `If-Match` is a stale precondition rather than a validation error:
    the caller did supply one, it just cannot match, and answering 412 keeps the
    retry story identical to the ordinary conflict.
    """

    cleaned = value.strip().strip('"')
    if not cleaned.startswith("rv-") or not cleaned[3:].isdigit():
        raise VersionConflictError()
    return int(cleaned[3:])
