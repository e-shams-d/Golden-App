"""Authentication endpoints: two login routes, and the session surface.

**Two routes, not one with a `user_type` field.** DOC-CONFLICT-023's approved
direction is that authentication derives and enforces the audience server-side
and never trusts a client-supplied selector. A body field cannot carry authority
on its own, but it decides *which* authority is evaluated, and that puts the
separation document 12 requires inside a handler branch no external test can
observe. Two routes make the audience a property of the URL and of the session
row, so `SEC-AUD-002` can assert against the published contract rather than
against source.

**The response is identical for every failure.** `12_Security_RBAC_Audit.md:403`
requires a generic error that does not reveal whether an account exists. The
command distinguishes nine reasons for `auth_events`; this module renders one.

**Cookies are `__Host-` prefixed and host-only.** See `app/security/cookies.py`
for why the isolation axis is the host rather than the path in this deployment.

Covers: API-AUTH-001, API-AUTH-002, API-AUTH-003, API-AUTH-004, SEC-AUD-001,
SEC-CSRF-001, SEC-LEAK-001.
"""

from __future__ import annotations

import ipaddress
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime, get_settings
from app.commands.authenticate import (
    AuthenticationPolicy,
    LoginAttempt,
    SuccessfulAuthentication,
    authenticate,
)
from app.core.config import Settings
from app.core.errors import AppError, ErrorEnvelope
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.identity import AdminUser, TraderUser
from app.db.models.session_and_security import AuthSession
from app.security import cookies, sessions
from app.security.actor import ActorContext, Audience
from app.security.lockout import LockoutPolicy
from app.security.passwords import Argon2Parameters
from app.security.rate_limit import AuthenticationRateLimiter, RateLimitPolicy

router = APIRouter(prefix="/auth", tags=["auth"])


class UnauthenticatedError(AppError):
    """The one answer every authentication failure produces.

    `UNAUTHENTICATED` rather than doc 12's example spelling `INVALID_CREDENTIALS`:
    the approved-shape error catalogue carries no such code, and inventing an
    identifier that no catalogue records is the thing DOC-CONFLICT-013 exists to
    stop. The divergence is a name, not a behaviour — the message is the generic
    one `:403` requires either way.
    """

    def __init__(self) -> None:
        super().__init__("UNAUTHENTICATED", "The login information is not valid.", 401)


class CsrfRequiredError(AppError):
    """A missing or wrong CSRF token.

    `FORBIDDEN` because the catalogue has no CSRF code and 403 is what it means:
    the request is understood and refused. A distinct code would also tell an
    attacker which control stopped them.
    """

    def __init__(self) -> None:
        super().__init__("FORBIDDEN", "Permission denied.", 403)


AUTH_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope, "description": "The login information is not valid."},
    **VALIDATION_ERROR_RESPONSE,
}

SESSION_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "Permission denied."},
    **VALIDATION_ERROR_RESPONSE,
}


class LoginRequest(BaseModel):
    """Note what is absent: there is no `user_type`.

    `SEC-AUD-002` asserts that against the generated OpenAPI document, so adding
    one here fails the contract test rather than only a source review.
    """

    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class SessionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    expires_at: datetime
    authentication_level: str


class ActorSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    audience: str
    status: str
    trader_id: uuid.UUID | None
    roles: list[str]
    permissions: list[str]


class LoginResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: SessionSummary
    user: ActorSummary


class SessionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessions: list[SessionSummary]


class RevocationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revoked: bool


def _policy(settings: Settings, audience: Audience) -> AuthenticationPolicy:
    """Per-audience because doc 12:460 wants internal sessions held to a stricter
    policy. The values themselves are provisional under ADR-SEC-002 and no test
    asserts them."""

    csrf_secret = settings.auth_csrf_key_secret
    lifetime = (
        settings.admin_session_lifetime_seconds
        if audience is Audience.ADMIN
        else settings.trader_session_lifetime_seconds
    )
    return AuthenticationPolicy(
        argon2=Argon2Parameters.from_settings(settings),
        password_max_length=settings.password_max_length,
        lockout=LockoutPolicy(
            threshold=settings.auth_lockout_threshold,
            lock_duration_seconds=settings.auth_lockout_seconds,
        ),
        session_secret_bytes=settings.session_secret_bytes,
        session_lifetime_seconds=lifetime,
        csrf_key=(csrf_secret.get_secret_value() if csrf_secret else "").encode("utf-8"),
    )


def _limiter(runtime: RuntimeServices, settings: Settings) -> AuthenticationRateLimiter | None:
    secret = settings.auth_rate_limit_key_secret
    if secret is None:
        # Outside production the secret is optional, and a limiter keyed on an
        # empty secret would hash identifiers reversibly. Absent is safer than
        # weak: the durable lockout still applies.
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


def _client_address(request: Request) -> str | None:
    """The caller's address, or `None` when it is not one.

    Two problems this solves, both found by an integration test rather than by
    reading the code.

    `auth_sessions.ip_address` and `auth_events.ip_address` are `INET`, so a value
    that is not an address is a `DataError` at insert — and the insert in question
    is the one recording a failed login, which is the row least able to afford
    being lost. Anything unparseable becomes `NULL`, because a missing address is
    a smaller loss than a missing security event.

    And `request.client.host` is the *proxy* here. nginx terminates the connection
    and forwards `X-Forwarded-For`, so recording `client.host` would write the
    same container address for every user on the platform and quietly make the
    network half of the rate limiter meaningless. The left-most entry is the
    original client; it is attacker-controlled, which is exactly why it is only
    ever used for recording and for the coarse network limit, never for
    authorization.
    """

    forwarded = request.headers.get("x-forwarded-for")
    candidate = forwarded.split(",")[0].strip() if forwarded else None
    if not candidate and request.client is not None:
        candidate = request.client.host

    if not candidate:
        return None
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _set_session_cookies(
    response: Response, audience: Audience, result: SuccessfulAuthentication
) -> None:
    names = cookies.names_for(audience)
    max_age = int((result.issued.expires_at - utc_now()).total_seconds())

    response.set_cookie(
        names.session,
        result.issued.secret,
        max_age=max_age,
        path=cookies.COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite=cookies.COOKIE_SAMESITE,
    )
    # Readable by script on purpose: the page must echo it in a header, which is
    # the part a cross-site form cannot set. It carries no authority alone.
    response.set_cookie(
        names.csrf,
        result.csrf_token,
        max_age=max_age,
        path=cookies.COOKIE_PATH,
        secure=True,
        httponly=False,
        samesite=cookies.COOKIE_SAMESITE,
    )


def _clear_session_cookies(response: Response, audience: Audience) -> None:
    names = cookies.names_for(audience)
    for name in (names.session, names.csrf):
        response.delete_cookie(
            name,
            path=cookies.COOKIE_PATH,
            secure=True,
            samesite=cookies.COOKIE_SAMESITE,
        )


def _login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    audience: Audience,
    runtime: RuntimeServices,
    settings: Settings,
) -> LoginResponse:
    now = utc_now()
    # Read before the transaction opens. A header lookup is not database work and
    # must not sit inside a lock; `test_no_io_under_lock` enforces the shape.
    client_host = _client_address(request)
    user_agent = request.headers.get("user-agent")

    with runtime.uow_factory() as uow:
        outcome = authenticate(
            LoginAttempt(
                identifier=payload.identifier,
                password=payload.password,
                audience=audience,
                ip_address=client_host,
                user_agent=user_agent,
            ),
            session=uow.session,
            policy=_policy(settings, audience),
            limiter=_limiter(runtime, settings),
            now=now,
        )
        # Committed on failure too: the `auth_events` row explaining the refusal
        # is the whole record of an attack, and rolling it back would erase
        # exactly the evidence a failed login exists to leave.
        uow.commit()

        if not isinstance(outcome, SuccessfulAuthentication):
            raise UnauthenticatedError()

        _set_session_cookies(response, audience, outcome)
        return LoginResponse(
            session=SessionSummary(
                id=outcome.issued.session_id,
                expires_at=outcome.issued.expires_at,
                authentication_level=outcome.actor.auth_level,
            ),
            user=_actor_summary(outcome.actor, status="active"),
        )


def _actor_summary(actor: ActorContext, *, status: str) -> ActorSummary:
    return ActorSummary(
        id=actor.actor_id,
        audience=actor.audience.value,
        status=status,
        trader_id=actor.trader_id,
        roles=sorted(actor.roles),
        permissions=sorted(actor.permissions),
    )


def _authenticate_request(
    request: Request, runtime: RuntimeServices, settings: Settings, audience: Audience | None = None
) -> tuple[ActorContext, str]:
    """Validate the presented cookie and return the actor plus the session digest.

    Every rejection raises the same 401. The reason is recorded by the caller in
    `auth_events`, never returned.
    """

    now = utc_now()
    presented: str | None = None
    resolved: Audience | None = audience

    candidates = [audience] if audience is not None else [Audience.ADMIN, Audience.TRADER]
    for candidate in candidates:
        value = request.cookies.get(cookies.names_for(candidate).session)
        if value:
            presented, resolved = value, candidate
            break

    if presented is None or resolved is None or not sessions.is_well_formed(presented):
        raise UnauthenticatedError()

    digest = sessions.digest_secret(presented)
    with runtime.uow_factory() as uow:
        session = uow.session
        record = session.scalar(select(AuthSession).where(AuthSession.secret_hash == digest))
        if record is None:
            uow.rollback()
            raise UnauthenticatedError()

        row_audience = sessions.audience_for(record.admin_user_id, record.trader_user_id)
        if row_audience is not resolved:
            uow.rollback()
            raise UnauthenticatedError()

        if record.revoked_at is not None or record.expires_at <= now:
            uow.rollback()
            raise UnauthenticatedError()

        identity: AdminUser | TraderUser | None
        if row_audience is Audience.ADMIN:
            identity = session.get(AdminUser, record.admin_user_id)
        else:
            identity = session.get(TraderUser, record.trader_user_id)

        if identity is None:
            uow.rollback()
            raise UnauthenticatedError()

        if sessions.classify_identity(identity.status, identity.locked_until, now) is not None:
            uow.rollback()
            raise UnauthenticatedError()

        if (
            sessions.classify_stamp(record.security_stamp_version, identity.security_stamp_version)
            is not None
        ):
            uow.rollback()
            raise UnauthenticatedError()

        actor = ActorContext(
            actor_type=sessions.actor_type_for(row_audience),
            actor_id=identity.id,
            audience=row_audience,
            session_id=record.id,
            security_stamp_version=record.security_stamp_version,
            trader_id=getattr(identity, "trader_id", None),
        )
        uow.rollback()

    _require_csrf(request, digest, settings)
    return actor, digest


def _require_csrf(request: Request, digest: str, settings: Settings) -> None:
    if not cookies.requires_csrf(request.method):
        return
    key = settings.auth_csrf_key_secret
    presented = request.headers.get(cookies.CSRF_HEADER)
    if not cookies.csrf_token_matches(
        presented, digest, (key.get_secret_value() if key else "").encode("utf-8")
    ):
        raise CsrfRequiredError()


@router.post(
    "/admin/login",
    response_model=LoginResponse,
    operation_id="loginAdmin",
    summary="Authenticate an internal user and open a session.",
    responses=AUTH_RESPONSES,
)
def login_admin(
    request: Request,
    response: Response,
    payload: LoginRequest,
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LoginResponse:
    return _login(request, response, payload, Audience.ADMIN, runtime, settings)


@router.post(
    "/trader/login",
    response_model=LoginResponse,
    operation_id="loginTrader",
    summary="Authenticate a trader contact and open a session.",
    responses=AUTH_RESPONSES,
)
def login_trader(
    request: Request,
    response: Response,
    payload: LoginRequest,
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LoginResponse:
    return _login(request, response, payload, Audience.TRADER, runtime, settings)


@router.get(
    "/me",
    response_model=LoginResponse,
    operation_id="getCurrentSession",
    summary="The current session and the actor it authenticates.",
    responses=SESSION_RESPONSES,
)
def current_session(
    request: Request,
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LoginResponse:
    actor, _ = _authenticate_request(request, runtime, settings)
    with runtime.uow_factory() as uow:
        session = uow.session
        record = session.get(AuthSession, actor.session_id)
        expires_at = record.expires_at if record is not None else utc_now()
        uow.rollback()
    return LoginResponse(
        session=SessionSummary(
            id=actor.session_id,
            expires_at=expires_at,
            authentication_level=actor.auth_level,
        ),
        user=_actor_summary(actor, status="active"),
    )


@router.post(
    "/logout",
    response_model=RevocationResponse,
    operation_id="logout",
    summary="Revoke the current session.",
    responses=SESSION_RESPONSES,
)
def logout(
    request: Request,
    response: Response,
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RevocationResponse:
    """Idempotent by definition (`05_API_Specification.md:802`).

    Revoking an already-revoked session succeeds and revokes nothing further, so
    a client that retries after a timeout is not told it has failed.
    """

    actor, _ = _authenticate_request(request, runtime, settings)
    now = utc_now()
    with runtime.uow_factory() as uow:
        session = uow.session
        record = session.get(AuthSession, actor.session_id)
        if record is not None and record.revoked_at is None:
            record.revoked_at = now
            record.revocation_reason = "logout"
            record.updated_at = now
        uow.commit()

    _clear_session_cookies(response, actor.audience)
    return RevocationResponse(revoked=True)


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    operation_id="listOwnSessions",
    summary="List the caller's own live sessions.",
    responses=SESSION_RESPONSES,
)
def list_sessions(
    request: Request,
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionListResponse:
    actor, _ = _authenticate_request(request, runtime, settings)
    now = utc_now()
    with runtime.uow_factory() as uow:
        session = uow.session
        column = (
            AuthSession.admin_user_id
            if actor.audience is Audience.ADMIN
            else AuthSession.trader_user_id
        )
        rows = list(
            session.scalars(
                select(AuthSession)
                .where(column == actor.actor_id)
                .where(AuthSession.revoked_at.is_(None))
                .where(AuthSession.expires_at > now)
                .order_by(AuthSession.created_at.desc())
            )
        )
        summaries = [
            SessionSummary(
                id=row.id, expires_at=row.expires_at, authentication_level=row.auth_level
            )
            for row in rows
        ]
        uow.rollback()
    return SessionListResponse(sessions=summaries)


@router.post(
    "/sessions/{session_id}/revoke",
    response_model=RevocationResponse,
    operation_id="revokeOwnSession",
    summary="Revoke one of the caller's own sessions.",
    responses=SESSION_RESPONSES,
)
def revoke_session(
    request: Request,
    session_id: uuid.UUID,
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RevocationResponse:
    """Scoped to the caller's own sessions.

    A session belonging to someone else answers exactly as one that does not
    exist: `14_Testing_QA_Acceptance.md:1284` requires refusal without disclosing
    whether the target exists, and a 404-versus-403 difference here would be an
    existence oracle over session identifiers.
    """

    actor, _ = _authenticate_request(request, runtime, settings)
    now = utc_now()
    with runtime.uow_factory() as uow:
        session = uow.session
        record = session.get(AuthSession, session_id)
        owner = (
            (record.admin_user_id if actor.audience is Audience.ADMIN else record.trader_user_id)
            if record is not None
            else None
        )

        if record is None or owner != actor.actor_id:
            uow.rollback()
            return RevocationResponse(revoked=True)

        if record.revoked_at is None:
            record.revoked_at = now
            record.revocation_reason = "revoked_by_owner"
            record.updated_at = now
        uow.commit()
    return RevocationResponse(revoked=True)
