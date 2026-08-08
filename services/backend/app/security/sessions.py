"""Server-side sessions: issue, validate, revoke, rotate.

ADR-001, Approved 2026-08-08: session records live on the server and a secure,
HTTP-only, `SameSite` cookie carries the credential. This module owns the record
half. The cookie half is slice 4 and is deliberately not importable from here.

**Why the session secret is hashed with SHA-256 and a password is not.** The
secret is 256 bits of CSPRNG output, so there is no dictionary to slow an
attacker down — there is nothing to guess. A slow hash would add its work factor
to every authenticated request while buying nothing, which is a denial-of-service
lever we would have built ourselves. A password is the opposite case: low entropy,
drawn from a guessable distribution, so the work factor is the entire defence.
The rule that unifies them is "make guessing expensive relative to the entropy of
what is guessed", and it produces different answers here.

**What is stored is a digest, never the secret.** `04_Database_Schema.md:416`
says never store the raw session or refresh secret, and the model docstring gives
the reason: otherwise every database backup is a set of live credentials.

**Validation re-reads the identity every time.** `12_Security_RBAC_Audit.md:438`
requires account status to be revalidated on protected requests and forbids
relying on a stale claim, and `:461` requires that a session cannot outlive
account deactivation or a security-stamp change. A cached answer would mean a
suspension takes effect at next login rather than at the next request, and "we
revoked their access" would be false for as long as the cache lived.

**The lookup does not filter.** `WHERE secret_hash = :digest` and nothing else.
Adding `AND revoked_at IS NULL` would collapse "unknown secret" into "a session
revoked three days ago", and the second is the strongest stolen-cookie signal the
system has. The cost of not filtering is zero — it is the same unique-index probe
— and the client sees no difference either way, because every rejection returns
the same thing.

Covers: SEC-SESS-001, SEC-SESS-002, SEC-SESS-003, SEC-STAMP-001.
"""

from __future__ import annotations

import hashlib
import secrets
import string
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.security.actor import ActorContext, ActorType, Audience

# A version prefix on the stored digest, following the convention
# `app.core.hashing` established. Bumping it to `s2` makes every live session
# fail to match, which logs everyone out — the safe direction for a credential.
SESSION_HASH_VERSION = "s1"
_DIGEST_ALGORITHM = "sha256"

# The full range `SESSION_SECRET_BYTES` permits, not today's value. A pre-filter
# keyed on the current setting would reject every session issued under the
# previous one the moment the setting is raised — a fleet-wide logout at deploy
# time, which would be reported as "sessions broke after the release".
_SECRET_MIN_CHARS = 43  # 32 bytes, base64url, padding stripped
_SECRET_MAX_CHARS = 86  # 64 bytes, likewise
_SECRET_ALPHABET = frozenset(string.ascii_letters + string.digits + "-_")

# One value. Naming others would answer ADR-009 from a constant.
AUTH_LEVELS: tuple[str, ...] = ("password",)


class SessionRejection(StrEnum):
    """Why a presented secret was refused.

    Recorded in `auth_events` and never told to the client, which receives one
    indistinguishable response for all of them. The distinction exists for the
    person investigating an incident, and it is the reason the lookup does not
    filter: `REVOKED` and `UNKNOWN` are different facts about an attacker.
    """

    MALFORMED = "malformed"
    UNKNOWN = "unknown"
    REVOKED = "revoked"
    EXPIRED = "expired"
    AUDIENCE_MISMATCH = "audience_mismatch"
    IDENTITY_NOT_ACTIVE = "identity_not_active"
    IDENTITY_LOCKED = "identity_locked"
    STAMP_BEHIND = "stamp_behind"
    STAMP_AHEAD = "stamp_ahead"


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """The one moment the raw secret exists outside the browser.

    `repr=False` on the secret so a logged dataclass, an exception rendering its
    arguments, or a debugger session does not print a live credential.
    """

    session_id: uuid.UUID
    expires_at: datetime
    secret: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    """Either an actor or a reason, never both and never neither."""

    actor: ActorContext | None = None
    rejection: SessionRejection | None = None

    def __post_init__(self) -> None:
        if (self.actor is None) == (self.rejection is None):
            raise ValueError(
                "a validation outcome is exactly one of an actor or a rejection; "
                "both or neither means a caller can read authority off a failure"
            )

    @property
    def is_valid(self) -> bool:
        return self.actor is not None


def generate_secret(secret_bytes: int) -> str:
    """A URL-safe, high-entropy session secret.

    `secrets.token_urlsafe` rather than `random`: the module distinction is the
    difference between a CSPRNG and a Mersenne Twister whose state is recoverable
    from its output.
    """

    if secret_bytes < 32:
        raise ValueError(
            f"session secrets need at least 32 bytes of entropy, not {secret_bytes}. "
            "The stored digest is a fast unsalted hash, which is only sound because "
            "the input is uniform and large."
        )
    return secrets.token_urlsafe(secret_bytes)


def digest_secret(secret: str) -> str:
    """`s1:<sha256 hex>` — 67 characters into a VARCHAR(128) column.

    Deliberately not `app.core.hashing.content_hash`. That function normalises
    text — Unicode form, zero-width characters, Persian digit folding, whitespace
    — so that two spellings of one name hash alike. For a credential that is
    exactly backwards: two distinct secrets must never collide, and a future
    normalisation rule that made them collide would surface as an integrity error
    on `uq_auth_sessions_secret_hash` at login, long after the change that caused
    it.
    """

    return (
        f"{SESSION_HASH_VERSION}:"
        f"{hashlib.new(_DIGEST_ALGORITHM, secret.encode('ascii')).hexdigest()}"
    )


def is_well_formed(secret: str) -> bool:
    """Cheap shape check, run before the secret is encoded or queried.

    Two jobs. It keeps a malformed cookie from reaching the database at all, and
    it guarantees `.encode("ascii")` in `digest_secret` cannot raise a
    `UnicodeEncodeError` whose message would quote part of the presented
    credential into a stack trace.
    """

    return _SECRET_MIN_CHARS <= len(secret) <= _SECRET_MAX_CHARS and not (
        set(secret) - _SECRET_ALPHABET
    )


def audience_for(admin_user_id: uuid.UUID | None, trader_user_id: uuid.UUID | None) -> Audience:
    """Read the audience off the session row's populated column.

    `auth_sessions` carries a CHECK that exactly one is set, so this cannot be
    ambiguous at the database level. DOC-CONFLICT-023's approved direction is
    that the audience is derived and enforced server-side and never taken from a
    client-supplied field; deriving it from the column is the strongest form of
    that, because a mismatch is a `NULL` rather than an unequal string.
    """

    if (admin_user_id is None) == (trader_user_id is None):
        raise ValueError(
            "auth_sessions row has both or neither actor column set, which "
            "ck_auth_sessions_exactly_one_actor forbids; the row is corrupt"
        )
    return Audience.ADMIN if admin_user_id is not None else Audience.TRADER


def actor_type_for(audience: Audience) -> ActorType:
    return ActorType.ADMIN_USER if audience is Audience.ADMIN else ActorType.TRADER_USER


def classify_stamp(session_version: int, identity_version: int) -> SessionRejection | None:
    """Compare the session's security stamp against the identity's.

    Equality, not `>=`. A session whose stamp is *ahead* of the identity's cannot
    happen through any code path here — it means a partial restore, a replayed
    backup, or manual editing — and treating it as acceptable would make a
    rolled-back identity table silently re-authorise old sessions. It is a
    separate rejection so it can be alerted on rather than counted as ordinary.
    """

    if session_version == identity_version:
        return None
    if session_version < identity_version:
        return SessionRejection.STAMP_BEHIND
    return SessionRejection.STAMP_AHEAD


def classify_identity(
    status: str, locked_until: datetime | None, now: datetime
) -> SessionRejection | None:
    """Whether the identity may act right now.

    `locked_until` is compared rather than a status value being read, because
    DOC-CONFLICT-037 decided that a lock is a timestamp that expires by itself
    and `locked` is not one of the four account statuses.
    """

    if status != "active":
        return SessionRejection.IDENTITY_NOT_ACTIVE
    if locked_until is not None and locked_until > now:
        return SessionRejection.IDENTITY_LOCKED
    return None
