"""Recent authentication: proving presence again, for one exact action.

`12_Security_RBAC_Audit.md:512` states the premise — a valid base session is not
sufficient assurance for selected high-impact actions. What that buys is narrow
and worth naming: it does not prove the actor is entitled, and it does not approve
anything (`:550`). It proves that whoever is holding the session was present a
moment ago.

**Four bindings, and every one of them is a refusal somebody would otherwise
want.** `FINANCIAL_INTEGRITY_BASELINE.md` §3 requires a context bound to actor,
active session, action/purpose and resource:

- **actor** — otherwise one person's step-up authorises another's command;
- **session** — otherwise a context obtained on a laptop authorises a command
  from a stolen phone (`:556` prohibits cross-session reuse in terms);
- **purpose** — otherwise a step-up for "change my password" authorises
  "approve a payment batch";
- **resource** — otherwise a step-up for batch version 7 authorises version 8,
  which is the case the whole approval model exists to prevent.

**The reference is opaque and stored as a hash.** `:535` requires an opaque value
and `:536` requires it audit-linked without logging the secret in plaintext. So
the caller receives a high-entropy string, the row keeps only its digest, and an
audit row can name the context by id without ever holding something replayable.

**One factor is registered, and that is ADR-009's decision to make.** `password`
is the only entry. `:554` says the timeout "must be short enough for high-risk
financial use" and leaves the number to an ADR; the factor set is the same. What
M3 owes is the interface, so adding SMS or TOTP later is a registration rather
than a rewrite — and the deployment facts that decide it (SMS deliverability in
Iran, whether the people holding manager authority carry smartphones) are the
owner's knowledge, not a technical judgement.

Covers: SEC-STEP-001, SEC-STEP-002, SEC-STEP-003, SEC-STEP-004, SEC-STEP-005,
SEC-STEP-006.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app.security.actor import ActorContext

# The registry. One entry, because ADR-009 is Open and inventing a second would
# decide it. `assurance_factor` on the row records which was used, so a later
# addition is distinguishable in history rather than retroactively ambiguous.
PASSWORD_FACTOR = "password"
REGISTERED_FACTORS: frozenset[str] = frozenset({PASSWORD_FACTOR})

# 32 bytes, same reasoning as the session secret: the reference is uniform
# randomness, so there is no dictionary to slow down and a fast digest is correct.
REFERENCE_BYTES = 32


class StepUpRejection(StrEnum):
    """Why a presented context does not authorise this command.

    Recorded in `auth_events`; the client is told only `RECENT_AUTH_REQUIRED`, so
    a caller cannot learn whether their reference was expired, spent, or issued
    for a different batch.
    """

    UNKNOWN_REFERENCE = "unknown_reference"
    WRONG_ACTOR = "wrong_actor"
    WRONG_SESSION = "wrong_session"
    WRONG_PURPOSE = "wrong_purpose"
    WRONG_RESOURCE = "wrong_resource"
    EXPIRED = "expired"
    ALREADY_CONSUMED = "already_consumed"
    REVOKED = "revoked"
    UNREGISTERED_FACTOR = "unregistered_factor"


@dataclass(frozen=True, slots=True)
class StepUpRequest:
    """What a caller must name to obtain a context.

    `05_API_Specification.md:825-828` shows only `password` and `purpose`. The
    resource is required here as well, because `FINANCIAL_INTEGRITY_BASELINE.md`
    §3 binds the context to one and `recent_auth_contexts.resource_id` is
    `NOT NULL`. Document 05's example is narrower than the approved baseline; the
    baseline wins under the precedence order, and a context that named only a
    purpose would authorise the same action against any resource.
    """

    purpose: str
    resource_type: str
    resource_id: uuid.UUID
    factor: str = PASSWORD_FACTOR


@dataclass(frozen=True, slots=True)
class IssuedStepUp:
    context_id: uuid.UUID
    reference: str
    """Returned once, never stored. The row keeps only its digest."""
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class StepUpPolicy:
    lifetime_seconds: int

    def __post_init__(self) -> None:
        if self.lifetime_seconds < 1:
            raise ValueError("a context that expires immediately cannot be presented")


def generate_reference() -> str:
    return secrets.token_urlsafe(REFERENCE_BYTES)


def digest_reference(reference: str) -> str:
    """SHA-256 of the reference. A dump of the table yields nothing presentable."""

    return hashlib.sha256(reference.encode("ascii")).hexdigest()


def require_registered_factor(factor: str) -> str:
    if factor not in REGISTERED_FACTORS:
        raise ValueError(
            f"{factor!r} is not a registered assurance factor. ADR-009 decides which "
            f"factors exist and is Open; registered today: {sorted(REGISTERED_FACTORS)}."
        )
    return factor


def expiry_for(now: datetime, policy: StepUpPolicy) -> datetime:
    return now + timedelta(seconds=policy.lifetime_seconds)


@dataclass(frozen=True, slots=True)
class PresentedContext:
    """The stored row's fields, as the validator needs them.

    A plain value object rather than the ORM row so the comparison logic has no
    database in it and every rejection branch is reachable in a unit test.
    """

    actor_id: uuid.UUID
    session_id: uuid.UUID
    purpose: str
    resource_type: str
    resource_id: uuid.UUID
    assurance_factor: str
    expires_at: datetime
    consumed_at: datetime | None
    revoked_at: datetime | None


def rejection_for(
    stored: PresentedContext | None,
    *,
    actor: ActorContext,
    request: StepUpRequest,
    now: datetime,
) -> StepUpRejection | None:
    """`None` when the context authorises exactly this command, else why not.

    The order is deliberate: identity mismatches are checked before expiry, so a
    caller replaying somebody else's reference is recorded as the wrong actor
    rather than as a stale one. The client cannot tell the difference either way,
    but an investigator can.
    """

    if stored is None:
        return StepUpRejection.UNKNOWN_REFERENCE
    if stored.actor_id != actor.actor_id:
        return StepUpRejection.WRONG_ACTOR
    if stored.session_id != actor.session_id:
        return StepUpRejection.WRONG_SESSION
    if stored.purpose != request.purpose:
        return StepUpRejection.WRONG_PURPOSE
    if stored.resource_type != request.resource_type or stored.resource_id != request.resource_id:
        return StepUpRejection.WRONG_RESOURCE
    if stored.assurance_factor not in REGISTERED_FACTORS:
        # A factor that was registered when the row was written and is not now.
        # Refusing is the fail-closed direction: the assurance it recorded is no
        # longer one this deployment accepts.
        return StepUpRejection.UNREGISTERED_FACTOR
    if stored.revoked_at is not None:
        return StepUpRejection.REVOKED
    if stored.consumed_at is not None:
        return StepUpRejection.ALREADY_CONSUMED
    if stored.expires_at <= now:
        return StepUpRejection.EXPIRED
    return None
