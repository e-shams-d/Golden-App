"""Sign in: verify a credential, and record what happened, in one transaction.

Every outcome writes an `auth_events` row, and the successful one additionally
inserts a session and clears the failure counters. All of it commits together or
none of it does — a login that issued a session but lost the event, or counted a
failure but lost the lock, is a login whose record disagrees with its effect.

**Every failure returns the same thing.** `12_Security_RBAC_Audit.md:403` requires
login to return a generic error that does not reveal whether an account exists,
and this module honours that by construction: the caller gets a
`FailedAuthentication` carrying only the reason *for the log*, and the route
renders one response for all of them. An unknown identifier, a wrong password, a
suspended account and a locked account are indistinguishable to the client and
fully distinguished in `auth_events`.

**A wrong password and an unknown user cost the same time.** Skipping the hash
when no row is found would make an unknown identifier measurably faster, which is
an account-enumeration oracle that no amount of identical response bodies hides.
So a miss verifies the presented password against a dummy hash and discards the
result.

**The rate limiter is consulted before the database, and the lockout after.** The
limiter is the cheap check that stops a flood before it costs a query or an
Argon2 verification; the durable counter is the one that survives a Redis
restart. Both exist because either alone has a failure mode the other covers.

Covers: SEC-ENUM-001, AUD-EVENT-001, API-AUTH-001.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.identity import AdminUser, TraderUser
from app.db.models.session_and_security import AuthEvent, AuthSession
from app.security import account_state, cookies, passwords, sessions
from app.security.account_state import AccountAction, AccountRefusal
from app.security.actor import ActorContext, Audience
from app.security.events import (
    OUTCOME_FAILURE,
    OUTCOME_SUCCESS,
    SecurityEvent,
)
from app.security.identifiers import InvalidIdentifier, normalize_mobile, normalize_username
from app.security.lockout import LockoutPolicy, after_failure, after_success
from app.security.passwords import Argon2Parameters
from app.security.rate_limit import AuthenticationRateLimiter

# Verified against when no identity matches, so the timing of a miss matches the
# timing of a wrong password. Generated once at import with the cheapest
# parameters the floor permits — its only job is to consume comparable time, and
# it never protects anything.
_DUMMY_HASH: str | None = None


def _dummy_hash(parameters: Argon2Parameters, max_length: int) -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = passwords.hash_password(
            "not-a-real-password", parameters, max_length=max_length
        )
    return _DUMMY_HASH


@dataclass(frozen=True, slots=True)
class AuthenticationPolicy:
    """Everything the command needs that is configuration rather than input."""

    argon2: Argon2Parameters
    password_max_length: int
    lockout: LockoutPolicy
    session_secret_bytes: int
    session_lifetime_seconds: int
    csrf_key: bytes


@dataclass(frozen=True, slots=True)
class LoginAttempt:
    identifier: str
    password: str
    audience: Audience
    ip_address: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True, slots=True)
class SuccessfulAuthentication:
    actor: ActorContext
    issued: sessions.IssuedSession
    csrf_token: str


@dataclass(frozen=True, slots=True)
class FailedAuthentication:
    """The reason is for `auth_events`, never for the client."""

    reason: str


def authenticate(
    attempt: LoginAttempt,
    *,
    session: Session,
    policy: AuthenticationPolicy,
    limiter: AuthenticationRateLimiter | None,
    now: datetime,
) -> SuccessfulAuthentication | FailedAuthentication:
    """Verify a credential and, on success, issue a session.

    Does not commit. The route owns the transaction boundary, as every other
    command in this codebase does, so a login can be composed into a larger unit
    of work without this module deciding when it ends.
    """

    try:
        identifier = (
            normalize_username(attempt.identifier)
            if attempt.audience is Audience.ADMIN
            else normalize_mobile(attempt.identifier)
        )
    except InvalidIdentifier:
        # Never told to the client: "that is not a valid number" answers a
        # question the generic-error rule exists to refuse.
        session.add(_event(attempt.audience, "login.rejected", "malformed_identifier", None))
        return FailedAuthentication(reason="malformed_identifier")

    if limiter is not None:
        decision = limiter.check(identifier, attempt.ip_address)
        if not decision.allowed:
            scope = decision.scope.value if decision.scope else "unknown"
            session.add(_event(attempt.audience, "login.rate_limited", f"rate_{scope}", None))
            return FailedAuthentication(reason=f"rate_limited_{scope}")

    identity = _load_identity(session, identifier, attempt.audience)

    if identity is None:
        # Spend the same time as a real verification. Without this, an unknown
        # identifier returns measurably faster and the identical response body
        # stops mattering.
        passwords.verify_password(
            _dummy_hash(policy.argon2, policy.password_max_length),
            attempt.password,
            policy.argon2,
            max_length=policy.password_max_length,
        )
        session.add(_event(attempt.audience, "login.failed", "unknown_identifier", None))
        return FailedAuthentication(reason="unknown_identifier")

    refusal = account_state.refusal_for(
        identity.status, identity.locked_until, now, AccountAction.AUTHENTICATE
    )
    if refusal is not None:
        # Still counted: an attacker must not learn that an account is suspended
        # by observing that their guesses stopped accumulating against it.
        _record_failure(session, identity, now, policy)
        session.add(_event(attempt.audience, "login.refused", refusal.value, identity.id))
        return FailedAuthentication(reason=refusal.value)

    verification = passwords.verify_password(
        identity.password_hash,
        attempt.password,
        policy.argon2,
        max_length=policy.password_max_length,
    )
    if not verification.is_valid:
        _record_failure(session, identity, now, policy)
        session.add(_event(attempt.audience, "login.failed", "wrong_password", identity.id))
        return FailedAuthentication(reason="wrong_password")

    if verification.needs_rehash:
        # The only moment the plaintext exists to upgrade with.
        identity.password_hash = passwords.hash_password(
            attempt.password, policy.argon2, max_length=policy.password_max_length
        )

    cleared = after_success(now)
    identity.failed_login_count = cleared.failed_login_count
    identity.locked_until = cleared.locked_until
    identity.last_login_at = now

    secret = sessions.generate_secret(policy.session_secret_bytes)
    digest = sessions.digest_secret(secret)
    record = AuthSession(
        admin_user_id=identity.id if attempt.audience is Audience.ADMIN else None,
        trader_user_id=identity.id if attempt.audience is Audience.TRADER else None,
        secret_hash=digest,
        auth_level=sessions.AUTH_LEVELS[0],
        authenticated_at=now,
        expires_at=now + timedelta(seconds=policy.session_lifetime_seconds),
        security_stamp_version=identity.security_stamp_version,
        ip_address=attempt.ip_address,
        user_agent=attempt.user_agent,
    )
    session.add(record)
    # Needed now because the actor context and the event both name the session,
    # and `autoflush=False` means nothing has assigned an id yet.
    session.flush()

    session.add(
        _event(attempt.audience, "login.succeeded", None, identity.id, record.id, OUTCOME_SUCCESS)
    )

    actor = ActorContext(
        actor_type=sessions.actor_type_for(attempt.audience),
        actor_id=identity.id,
        audience=attempt.audience,
        session_id=record.id,
        security_stamp_version=identity.security_stamp_version,
        trader_id=getattr(identity, "trader_id", None),
    )

    return SuccessfulAuthentication(
        actor=actor,
        issued=sessions.IssuedSession(
            session_id=record.id, expires_at=record.expires_at, secret=secret
        ),
        csrf_token=cookies.csrf_token(digest, policy.csrf_key),
    )


def _load_identity(
    session: Session, identifier: str, audience: Audience
) -> AdminUser | TraderUser | None:
    if audience is Audience.ADMIN:
        return session.scalar(select(AdminUser).where(AdminUser.username == identifier))
    return session.scalar(select(TraderUser).where(TraderUser.phone_number == identifier))


def _record_failure(
    session: Session,
    identity: AdminUser | TraderUser,
    now: datetime,
    policy: AuthenticationPolicy,
) -> None:
    del session  # the identity is already attached; mutating it is the write
    counted = after_failure(identity.failed_login_count, identity.locked_until, now, policy.lockout)
    identity.failed_login_count = counted.failed_login_count
    identity.locked_until = counted.locked_until


def _event(
    audience: Audience,
    event_type: str,
    reason: str | None,
    actor_id: uuid.UUID | None,
    session_id: uuid.UUID | None = None,
    outcome: str = OUTCOME_FAILURE,
) -> AuthEvent:
    """Build the row through `SecurityEvent`, so the metadata allowlist applies.

    Constructing an `AuthEvent` directly would bypass the check that keeps
    credential material out of an append-only table the runtime cannot delete
    from.
    """

    payload: dict[str, object] = {"audience": audience.value}
    if reason is not None:
        payload["rejection_reason"] = reason

    validated = SecurityEvent(
        actor_type=sessions.actor_type_for(audience).value,
        actor_id=actor_id,
        event_type=event_type,
        event_class="authentication",
        outcome=outcome,
        session_id=session_id,
        metadata_payload=payload,
    )
    return AuthEvent(**validated.as_row())


__all__ = [
    "AccountRefusal",
    "AuthenticationPolicy",
    "FailedAuthentication",
    "LoginAttempt",
    "SuccessfulAuthentication",
    "authenticate",
]
