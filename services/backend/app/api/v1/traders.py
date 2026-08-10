"""Registration, and the center's decisions about a trader.

One public route and four guarded ones. The public one is the only unauthenticated
write surface in the platform, which is why it carries the most reasoning:

**It is rate-limited on the network axis alone**, because there is no account
identifier to limit against until the account exists. Under CGNAT that ceiling has
to stay loose (see `app/security/rate_limit.py`), so it is a weak control — which
is exactly why the endpoint reveals nothing and creates nothing an attacker can
use. A flood of registrations produces pending businesses that no staff member
approves, not access.

**It answers identically whether or not the phone number is already registered.**
A public endpoint that distinguished the two would be a membership oracle for the
platform's customer list.

The four decisions each require `If-Match` and an `Idempotency-Key`. Both, not
either: `If-Match` stops a decision landing on a business somebody else changed
meanwhile, and the idempotency key stops a retried approval approving twice. They
answer different questions and neither substitutes for the other.

Covers: API-REG-001, API-REG-002, API-REG-003, API-APPROVE-001, API-APPROVE-002.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime, get_settings
from app.api.v1.auth import authenticated_actor, requires
from app.audit.redaction import RedactionPolicy
from app.audit.registry import (
    APPROVE_TRADER,
    REACTIVATE_TRADER,
    REJECT_TRADER,
    SUSPEND_TRADER,
    CommandNames,
)
from app.audit.writer import AuditActor, AuditContext
from app.commands import trader_lifecycle
from app.core.config import Settings
from app.core.errors import ErrorEnvelope, PreconditionRequiredError, VersionConflictError
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.security.actor import ActorContext
from app.security.identifiers import InvalidIdentifier
from app.security.passwords import Argon2Parameters
from app.security.permissions import declare
from app.security.rate_limit import AuthenticationRateLimiter, RateLimitPolicy, RateLimitScope

router = APIRouter(prefix="/traders", tags=["traders"])

# Explicit because POL-003 has not settled which roles see a full IBAN, and
# `RedactionPolicy` deliberately has no default so the open decision stays visible
# at each call site. `True` here: nothing in the trader lifecycle carries an IBAN
# today — `trader_bank_accounts` arrives in M4 — so masking costs nothing and is
# the direction that stays correct when it does.
TRADER_REDACTION = RedactionPolicy(mask_iban=True)

REGISTER_RESPONSES: dict[int | str, dict[str, object]] = {
    429: {"model": ErrorEnvelope, "description": "Too many registration attempts."},
    **VALIDATION_ERROR_RESPONSE,
}

DECISION_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "Permission denied."},
    404: {"model": ErrorEnvelope, "description": "No such trader."},
    400: {"model": ErrorEnvelope, "description": "The transition is not allowed."},
    412: {"model": ErrorEnvelope, "description": "The If-Match value is stale."},
    428: {"model": ErrorEnvelope, "description": "If-Match or Idempotency-Key is missing."},
    **VALIDATION_ERROR_RESPONSE,
}


class RegisterTraderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=255)
    primary_phone: str = Field(min_length=1, max_length=32)
    contact_full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1024)
    legal_name: str | None = Field(default=None, max_length=255)


class RegisterTraderResponse(BaseModel):
    """No identifiers, deliberately.

    Returning the new `trader_id` would let a caller tell a real registration from
    the no-op a duplicate produces, which is the membership oracle the command
    exists to avoid. The message is what a pending trader sees; it is the same
    message either way.
    """

    model_config = ConfigDict(extra="forbid")

    accepted: bool
    pending_approval: bool


class TraderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    display_name: str
    legal_name: str | None
    primary_phone: str
    operational_status: str
    approval_status: str
    approved_at: datetime | None
    record_version: int


class DecisionRequest(BaseModel):
    """`reason` is required for reject and suspend, per `05_API_Specification.md:894-895`.

    Optional in the model and enforced per route, because the same shape serves
    four commands and two of them do not require it — a required field on all four
    would make approval carry a reason nobody has.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=1000)


def _registration_limiter(
    runtime: RuntimeServices, settings: Settings
) -> AuthenticationRateLimiter | None:
    secret = settings.auth_rate_limit_key_secret
    if secret is None:
        return None
    return AuthenticationRateLimiter(
        runtime.redis,
        RateLimitPolicy(
            identifier_max_attempts=settings.auth_rate_limit_identifier_max,
            network_max_attempts=settings.auth_rate_limit_network_max,
            window_seconds=settings.auth_rate_limit_window_seconds,
        ),
        secret.get_secret_value().encode("utf-8"),
    )


def _audit_pair(actor: ActorContext | None) -> tuple[AuditActor, AuditContext]:
    """Who acted, and how to correlate it.

    A public registration has no authenticated actor, so it is attributed to the
    `system_maintenance` type rather than to an invented identity — doc 12:344
    reserves a controlled system actor for exactly the case where no human session
    exists, and inventing a UUID would put a fictional person in an append-only
    table.
    """

    if actor is None:
        return (
            AuditActor(actor_type="system_maintenance"),
            AuditContext(request_id=get_request_id()),
        )
    return (
        AuditActor(
            actor_type=actor.actor_type.value,
            actor_id=actor.actor_id,
            role_snapshot=tuple(sorted(actor.roles)),
            session_id=actor.session_id,
            authentication_assurance=actor.auth_level,
        ),
        AuditContext(request_id=get_request_id()),
    )


@router.post(
    "/register",
    response_model=RegisterTraderResponse,
    operation_id="registerTrader",
    summary="Apply to become a trader. Public and rate-limited.",
    responses=REGISTER_RESPONSES,
)
def register(
    request: Request,
    payload: RegisterTraderRequest,
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RegisterTraderResponse:
    """The only unauthenticated write surface on the platform.

    Limited on the network axis alone, because there is no account identifier to
    limit against until the account exists.
    """

    from app.api.v1.auth import _client_address

    now = utc_now()
    client_host = _client_address(request)

    limiter = _registration_limiter(runtime, settings)
    if limiter is not None and client_host is not None:
        decision = limiter.check(f"register:{client_host}", client_host)
        if not decision.allowed and decision.scope is RateLimitScope.NETWORK:
            from app.core.errors import AppError

            raise AppError("RATE_LIMITED", "Too many attempts. Try again later.", 429)

    actor, context = _audit_pair(None)

    with runtime.uow_factory() as uow:
        try:
            trader_lifecycle.register_trader(
                trader_lifecycle.RegisterTrader(
                    display_name=payload.display_name,
                    primary_phone=payload.primary_phone,
                    contact_full_name=payload.contact_full_name,
                    password=payload.password,
                    legal_name=payload.legal_name,
                ),
                session=uow.session,
                policy=TRADER_REDACTION,
                parameters=Argon2Parameters.from_settings(settings),
                password_max_length=settings.password_max_length,
                actor=actor,
                context=context,
                now=now,
            )
        except InvalidIdentifier:
            uow.rollback()
            # Answered as an acceptance, like a duplicate: a public endpoint that
            # distinguished "not a valid Iranian mobile" from "already registered"
            # would still be an oracle, just a coarser one.
            return RegisterTraderResponse(accepted=True, pending_approval=True)
        uow.commit()

    return RegisterTraderResponse(accepted=True, pending_approval=True)


def _decide(
    names: CommandNames,
    trader_id: uuid.UUID,
    payload: DecisionRequest,
    response: Response,
    actor: ActorContext,
    runtime: RuntimeServices,
    if_match: str | None,
    idempotency_key: str | None,
    *,
    reason_required: bool,
) -> TraderResponse:
    if if_match is None:
        raise PreconditionRequiredError("If-Match")
    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")
    if reason_required and not (payload.reason or "").strip():
        from app.core.errors import BusinessRuleViolationError

        raise BusinessRuleViolationError(
            "this decision requires a reason; 05_API_Specification.md:894-895 makes it "
            "mandatory, and a rejection nobody explained cannot be reviewed later"
        )

    expected = _parse_record_version(if_match)
    audit_actor, context = _audit_pair(actor)

    with runtime.uow_factory() as uow:
        trader = trader_lifecycle.decide(
            trader_lifecycle.TraderDecision(
                trader_id=trader_id,
                expected_record_version=expected,
                reason=payload.reason,
            ),
            names,
            session=uow.session,
            policy=TRADER_REDACTION,
            actor=audit_actor,
            context=context,
            now=utc_now(),
        )
        rendered = TraderResponse(
            id=trader.id,
            display_name=trader.display_name,
            legal_name=trader.legal_name,
            primary_phone=trader.primary_phone,
            operational_status=trader.operational_status,
            approval_status=trader.approval_status,
            approved_at=trader.approved_at,
            record_version=trader.record_version,
        )
        uow.commit()

    response.headers["ETag"] = f'"rv-{rendered.record_version}"'
    return rendered


def _parse_record_version(value: str) -> int:
    cleaned = value.strip().strip('"')
    if not cleaned.startswith("rv-") or not cleaned[3:].isdigit():
        raise VersionConflictError()
    return int(cleaned[3:])


@router.post(
    "/{trader_id}/approve",
    response_model=TraderResponse,
    operation_id="approveTrader",
    summary="Accept a trader as a counterparty.",
    responses=DECISION_RESPONSES,
    dependencies=[requires(declare("trader.approve"))],
)
def approve(
    trader_id: uuid.UUID,
    payload: DecisionRequest,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TraderResponse:
    return _decide(
        APPROVE_TRADER,
        trader_id,
        payload,
        response,
        actor,
        runtime,
        if_match,
        idempotency_key,
        reason_required=False,
    )


@router.post(
    "/{trader_id}/reject",
    response_model=TraderResponse,
    operation_id="rejectTrader",
    summary="Decline a trader application. Reason required.",
    responses=DECISION_RESPONSES,
    dependencies=[requires(declare("trader.reject"))],
)
def reject(
    trader_id: uuid.UUID,
    payload: DecisionRequest,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TraderResponse:
    return _decide(
        REJECT_TRADER,
        trader_id,
        payload,
        response,
        actor,
        runtime,
        if_match,
        idempotency_key,
        reason_required=True,
    )


@router.post(
    "/{trader_id}/suspend",
    response_model=TraderResponse,
    operation_id="suspendTrader",
    summary="Bar an approved trader from transacting. Reason required.",
    responses=DECISION_RESPONSES,
    dependencies=[requires(declare("trader.suspend"))],
)
def suspend(
    trader_id: uuid.UUID,
    payload: DecisionRequest,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TraderResponse:
    return _decide(
        SUSPEND_TRADER,
        trader_id,
        payload,
        response,
        actor,
        runtime,
        if_match,
        idempotency_key,
        reason_required=True,
    )


@router.post(
    "/{trader_id}/reactivate",
    response_model=TraderResponse,
    operation_id="reactivateTrader",
    summary="Return a suspended trader to active.",
    responses=DECISION_RESPONSES,
    dependencies=[requires(declare("trader.reactivate"))],
)
def reactivate(
    trader_id: uuid.UUID,
    payload: DecisionRequest,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TraderResponse:
    return _decide(
        REACTIVATE_TRADER,
        trader_id,
        payload,
        response,
        actor,
        runtime,
        if_match,
        idempotency_key,
        reason_required=False,
    )
