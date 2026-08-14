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
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime, get_settings
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.commands.authenticate import (
    AuthenticationPolicy,
    LoginAttempt,
    SuccessfulAuthentication,
    authenticate,
)
from app.commands.change_own_password import change_own_password
from app.commands.recover_admin_password import RecoveryAttempt, recover_admin_password
from app.core.config import Settings
from app.core.errors import AppError, ErrorEnvelope, ForbiddenError
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.identity import AdminUser, TraderUser
from app.db.models.session_and_security import AuthEvent, AuthSession, RecentAuthContext
from app.security import cookies, passwords, sessions, step_up
from app.security.actor import ActorContext, Audience
from app.security.events import OUTCOME_FAILURE, OUTCOME_SUCCESS, SecurityEvent
from app.security.lockout import LockoutPolicy
from app.security.passwords import Argon2Parameters
from app.security.permissions import declare, resolve
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


class RecentAuthRequiredError(AppError):
    """The catalogue's own 401 for a critical action lacking assurance.

    One code for every rejection reason, exactly as login has one: telling a
    caller whether their reference was expired, spent, or issued for a different
    batch version would let them probe the context store. The nine reasons
    `step_up.StepUpRejection` distinguishes go to `auth_events`.
    """

    def __init__(self) -> None:
        super().__init__(
            "RECENT_AUTH_REQUIRED",
            "This action requires recent authentication.",
            401,
        )


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

        # Resolved on every protected request rather than carried in the
        # session: a role revoked a minute ago must stop granting now, and a
        # cached set would keep granting until the session expired.
        roles, permissions = resolve(session, row_audience, identity.id)

        actor = ActorContext(
            actor_type=sessions.actor_type_for(row_audience),
            actor_id=identity.id,
            audience=row_audience,
            session_id=record.id,
            security_stamp_version=record.security_stamp_version,
            trader_id=getattr(identity, "trader_id", None),
            roles=roles,
            permissions=permissions,
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


def authenticated_actor(
    request: Request,
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ActorContext:
    """The dependency every protected route outside this module uses.

    Exported here rather than in `app/api/dependencies.py` because it needs the
    session machinery this module already owns, and a second copy of the
    validation order is the thing most likely to drift into accepting something
    the first copy refuses.
    """

    actor, _ = _authenticate_request(request, runtime, settings)
    return actor


def requires(permission: str) -> Any:
    """Route-level guard for one approved permission.

    The permission is checked against the approved catalogue **now**, at import,
    so a typo is a failed start rather than a route that silently denies everyone
    (`12_Security_RBAC_Audit.md:629`).
    """

    declared = declare(permission)

    def guard(
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> None:
        if declared not in actor.permissions:
            raise ForbiddenError()

    return Depends(guard)


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


class RecoverPasswordRequest(BaseModel):
    """The temporary credential an administrator set, and the one its owner chooses."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class RecoverPasswordResponse(BaseModel):
    """`recovered: true`, and nothing else — not a session, not a token.

    No session is issued deliberately. The account could not act a moment ago, and handing
    it one here would turn a credential its owner was given by somebody else into access
    without them ever having chosen anything. Recovery ends with a normal sign-in: one
    extra step, and the only shape in which the administrator's temporary password never
    becomes access on its own.
    """

    model_config = ConfigDict(extra="forbid")

    recovered: bool


@router.post(
    "/admin/recover-password",
    response_model=RecoverPasswordResponse,
    operation_id="recoverAdminPassword",
    summary="Complete a recovery after an administrative reset. Unauthenticated.",
    responses={
        401: {"model": ErrorEnvelope, "description": "The recovery could not be completed."},
        429: {"model": ErrorEnvelope, "description": "Too many attempts."},
        **VALIDATION_ERROR_RESPONSE,
    },
)
def recover_admin_password_route(
    request: Request,
    payload: RecoverPasswordRequest,
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RecoverPasswordResponse:
    """The way out of `recovery_required`, which had none until this route.

    `app/security/account_state.py` has described this flow since M2 —
    `AccountAction.RECOVER` is one of its three intents, and the only combination it
    permits is a `recovery_required` account that is not locked. **Nothing ever passed
    that intent.** The branch that makes the state escapable was reachable only from a
    unit test, which is why slice 8B declined to provision accounts into it: it would have
    produced a correctly-built account nobody could sign in to.

    **One answer for every failure.** An unknown username, a wrong temporary password and
    an account that is not awaiting recovery are all `UNAUTHENTICATED`, exactly as login
    is (`12_Security_RBAC_Audit.md:403`). Distinguishing them would be worse here than at
    login: this route would become a status oracle for the centre's own staff, telling an
    attacker which accounts an administrator has just reset — the moment those accounts
    are most exposed, because their credential is one somebody typed and communicated.

    **Rate-limited on both axes.** Unlike registration there *is* an account identifier to
    limit against, so one username cannot be ground through at network speed.
    """

    now = utc_now()
    # Read before the transaction opens, like `_login`: a header lookup is not database
    # work and `test_no_io_under_lock` enforces the shape.
    client_host = _client_address(request)
    user_agent = request.headers.get("user-agent")
    limiter = _limiter(runtime, settings)

    if limiter is not None and client_host is not None:
        decision = limiter.check(f"recover:{payload.username}", client_host)
        if not decision.allowed:
            raise AppError("RATE_LIMITED", "Too many attempts. Try again later.", 429)

    with runtime.uow_factory() as uow:
        outcome = recover_admin_password(
            RecoveryAttempt(
                username=payload.username,
                current_password=payload.current_password,
                new_password=payload.new_password,
            ),
            session=uow.session,
            policy=CREDENTIAL_REDACTION,
            parameters=Argon2Parameters.from_settings(settings),
            password_max_length=settings.password_max_length,
            # No session exists, so there is no actor to attribute this to. The
            # `system_maintenance` type is what doc 12:344 reserves for exactly that, and
            # inventing the target's own id would put a claim in an append-only table that
            # the platform cannot support — it does not yet know the caller is that person.
            actor=AuditActor(actor_type="system_maintenance"),
            context=AuditContext(request_id=get_request_id()),
            now=now,
        )

        if not outcome.succeeded:
            # The identity writes are discarded and the event is not. `rollback` on the
            # session drops the failed attempt's changes; the row below is added
            # afterwards so it survives the commit.
            uow.session.rollback()
            uow.session.add(
                AuthEvent(
                    **SecurityEvent(
                        actor_type="system_maintenance",
                        event_type="credential.recovery_failed",
                        event_class="credential",
                        outcome=OUTCOME_FAILURE,
                        ip_address=client_host,
                        user_agent=user_agent,
                        # The reason the server decided, never the one the client is told.
                        metadata_payload={"rejection_reason": outcome.refusal or "unknown"},
                    ).as_row()
                )
            )
            # Committed for the same reason a failed login is: the row explaining the
            # refusal is the whole record of an attempt, and rolling it back would erase
            # exactly the evidence this route exists to leave.
            uow.commit()
            raise UnauthenticatedError()

        uow.commit()

    return RecoverPasswordResponse(recovered=True)


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


class ReauthenticateRequest(BaseModel):
    """Carries the resource, which document 05's example omits.

    `05_API_Specification.md:825-828` shows `password` and `purpose` only.
    `FINANCIAL_INTEGRITY_BASELINE.md` §3 binds the context to a resource as well,
    and `recent_auth_contexts.resource_id` is NOT NULL. The approved baseline wins
    under the precedence order — a context naming only a purpose would authorise
    the same action against any resource, which is the batch-version-7-approves-8
    case the approval model exists to prevent.
    """

    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=1024)
    purpose: str = Field(min_length=1, max_length=120)
    resource_type: str = Field(min_length=1, max_length=80)
    resource_id: uuid.UUID


class ReauthenticateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recent_auth_reference: str
    expires_at: datetime
    authentication_level: str


@router.post(
    "/reauthenticate",
    response_model=ReauthenticateResponse,
    operation_id="reauthenticate",
    summary="Prove recent presence for one exact critical action.",
    responses=AUTH_RESPONSES,
)
def reauthenticate(
    request: Request,
    payload: ReauthenticateRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ReauthenticateResponse:
    """Reauthentication raises assurance. It approves nothing (`doc 12:550`).

    A wrong password here is `RECENT_AUTH_REQUIRED` rather than
    `UNAUTHENTICATED`: the session is still valid and the caller is still signed
    in, so answering 401-unauthenticated would tell a client to sign in again for
    a problem that has nothing to do with its session.
    """

    now = utc_now()
    client_host = _client_address(request)
    parameters = Argon2Parameters.from_settings(settings)

    with runtime.uow_factory() as uow:
        session = uow.session
        identity: AdminUser | TraderUser | None = (
            session.get(AdminUser, actor.actor_id)
            if actor.audience is Audience.ADMIN
            else session.get(TraderUser, actor.actor_id)
        )
        if identity is None:  # pragma: no cover - the session just resolved it
            uow.rollback()
            raise RecentAuthRequiredError()

        verification = passwords.verify_password(
            identity.password_hash,
            payload.password,
            parameters,
            max_length=settings.password_max_length,
        )

        reference = step_up.generate_reference()
        expires_at = step_up.expiry_for(
            now, step_up.StepUpPolicy(lifetime_seconds=settings.step_up_lifetime_seconds)
        )

        if not verification.is_valid:
            # Recorded, and counted by nothing: a failed step-up is not a login
            # attempt, and letting it drive the lockout would let anyone with a
            # session lock their own account out of a command they are entitled to.
            session.add(
                _security_event(
                    actor,
                    "step_up.failed",
                    "wrong_password",
                    client_host,
                )
            )
            uow.commit()
            raise RecentAuthRequiredError()

        context = RecentAuthContext(
            session_id=actor.session_id,
            actor_type=actor.actor_type.value,
            actor_id=actor.actor_id,
            purpose=payload.purpose,
            resource_type=payload.resource_type,
            resource_id=payload.resource_id,
            assurance_factor=step_up.require_registered_factor(step_up.PASSWORD_FACTOR),
            challenge_hash=step_up.digest_reference(reference),
            issued_at=now,
            expires_at=expires_at,
        )
        session.add(context)
        session.flush()

        session.add(_security_event(actor, "step_up.succeeded", None, client_host, OUTCOME_SUCCESS))
        uow.commit()

    return ReauthenticateResponse(
        recent_auth_reference=reference,
        expires_at=expires_at,
        authentication_level=sessions.AUTH_LEVELS[-1],
    )


# Masking on, like every other command's policy. Nothing in a credential change carries
# an IBAN, but `RedactionPolicy` has no default so that the open decision stays visible
# at each call site rather than being inherited silently.
CREDENTIAL_REDACTION = RedactionPolicy(mask_iban=True)


class ChangePasswordRequest(BaseModel):
    """The current password is required, and that is the presence check.

    `12_Security_RBAC_Audit.md` treats a credential change as critical, and the formal
    recent-auth binding — a `recent_auth_contexts` row consumed by `step_up.rejection_for`
    — has no production caller anywhere yet. Rather than half-build that here, this
    proves presence the way the neighbouring reauthenticate route does: by asking for the
    password again. Wiring the context store is M3 slice 8D's, together with the role
    change that needs it.

    Bounds match `LoginRequest` deliberately. A stronger minimum would be this file
    inventing a password policy while ADR-SEC-002's numbers are open, and a test asserting
    it would be enforcing an unapproved decision.
    """

    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class ChangePasswordResponse(BaseModel):
    """Deliberately says nothing but that it happened.

    Not the new stamp, not how many sessions ended: the first is an internal counter and
    the second is a number an attacker who guessed a password would like to know.
    """

    model_config = ConfigDict(extra="forbid")

    changed: bool


@router.post(
    "/change-password",
    response_model=ChangePasswordResponse,
    operation_id="changeOwnPassword",
    summary="Change your own password and end your other sessions.",
    responses=SESSION_RESPONSES,
)
def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChangePasswordResponse:
    """API-PWD-001. Both audiences: an admin and a trader change their own the same way.

    A wrong current password answers `RECENT_AUTH_REQUIRED` rather than
    `UNAUTHENTICATED`. The session is valid and the caller is still signed in, so telling
    a client to sign in again would send it to fix something that is not broken — the
    same reasoning the reauthenticate route above records.
    """

    now = utc_now()
    client_host = _client_address(request)
    parameters = Argon2Parameters.from_settings(settings)

    with runtime.uow_factory() as uow:
        session = uow.session
        identity: AdminUser | TraderUser | None = (
            session.get(AdminUser, actor.actor_id)
            if actor.audience is Audience.ADMIN
            else session.get(TraderUser, actor.actor_id)
        )
        if identity is None:  # pragma: no cover - the session just resolved it
            uow.rollback()
            raise RecentAuthRequiredError()

        verification = passwords.verify_password(
            identity.password_hash,
            payload.current_password,
            parameters,
            max_length=settings.password_max_length,
        )
        if not verification.is_valid:
            # Recorded and deliberately not counted towards the lockout: a signed-in
            # caller guessing their own current password is not a login attempt, and
            # letting it drive the lockout would let anyone holding a session lock the
            # account they are entitled to use.
            session.add(
                _security_event(actor, "password.change_refused", "wrong_password", client_host)
            )
            uow.commit()
            raise RecentAuthRequiredError()

        change_own_password(
            identity,
            session=session,
            audience=actor.audience,
            current_session_id=actor.session_id,
            new_password=payload.new_password,
            policy=CREDENTIAL_REDACTION,
            parameters=parameters,
            password_max_length=settings.password_max_length,
            actor=AuditActor(
                actor_type=actor.actor_type.value,
                actor_id=actor.actor_id,
                role_snapshot=tuple(sorted(actor.roles)),
            ),
            context=AuditContext(request_id=get_request_id()),
            now=now,
        )
        session.add(
            _security_event(
                actor,
                "password.changed",
                None,
                client_host,
                outcome=OUTCOME_SUCCESS,
            )
        )
        uow.commit()

    return ChangePasswordResponse(changed=True)


def _security_event(
    actor: ActorContext,
    event_type: str,
    reason: str | None,
    ip_address: str | None,
    outcome: str = OUTCOME_FAILURE,
) -> AuthEvent:
    """A step-up event, with the address the attempt came from."""

    payload: dict[str, object] = {"audience": actor.audience.value}
    if reason is not None:
        payload["rejection_reason"] = reason
    validated = SecurityEvent(
        actor_type=actor.actor_type.value,
        actor_id=actor.actor_id,
        event_type=event_type,
        event_class="authentication",
        outcome=outcome,
        session_id=actor.session_id,
        ip_address=ip_address,
        metadata_payload=payload,
    )
    return AuthEvent(**validated.as_row())


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
