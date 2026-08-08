"""Argon2id password hashing, with the parameters as configuration.

`12_Security_RBAC_Audit.md:381` prefers Argon2id with reviewed parameters, `:382`
forbids storing or logging a password or recovery secret in plaintext, `:383`
forbids returning a hash from an API, and `:384` requires comparison through an
approved library. All four are mechanical here rather than matters of care:
nothing in this module accepts a hash to return, and verification never branches
on anything but the library's own answer.

**Why the parameters are settings and not constants.** They have to change over
time as hardware does, and a hash records the parameters it was made with, so
raising them must not invalidate existing hashes. `needs_rehash` is how that is
detected; `verify_password` returns it alongside the verdict so the caller can
upgrade a hash during a successful login, which is the only moment the plaintext
is available.

**The measured cost, so capacity planning is not guesswork.** At the defaults
(t=3, m=64 MiB, p=4) a verification takes about 80-110 ms on an 8-core host.
`parallelism` is a property of the hash rather than a runtime knob, so the same
hash on a single-core container costs the full serial time — about 350 ms. Plan
against the second number. Memory multiplies by concurrent logins, which makes
authentication rate limiting part of the security design rather than a
refinement.

**What this module deliberately does not do.** It has no minimum length, no
character-class rule and no compromised-password check.
`12_Security_RBAC_Audit.md:390-397` assigns those to the production policy, and
the compromised-password rule in particular has an Iran-specific constraint: the
usual implementation calls an external breach API, which does not resolve from
the deployment country, and a blocked call that times out would read as "this
password is fine". When that rule arrives it must use a bundled local list or be
recorded as unmet.

Covers: SEC-PWD-001, SEC-PWD-002, SEC-PWD-003, SEC-PWD-004.
"""

from __future__ import annotations

from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2 import exceptions as argon2_exceptions

from app.core.config import Settings

# Argon2id's own defaults for these two are fine and are not worth a setting:
# 32 bytes of output is beyond any collision concern, and a 16-byte salt is the
# RFC 9106 recommendation. Both are recorded in the encoded hash, so changing
# them later is a `needs_rehash` upgrade like any other.
HASH_LENGTH = 32
SALT_LENGTH = 16

# `admin_users.password_hash` and `trader_users.password_hash` are VARCHAR(255).
# An Argon2id encoding at these parameters is 97 characters and grows slowly with
# memory cost, so the column has room — but a truncated hash fails to verify and
# presents as a wrong password, which is the hardest possible bug to diagnose.
# This turns it into a loud failure at the moment of hashing instead.
MAX_ENCODED_HASH_LENGTH = 255


class PasswordTooLong(ValueError):
    """Raised before hashing, never after.

    `12_Security_RBAC_Audit.md:394` requires a maximum length so a very long
    input cannot be a denial-of-service vector. Rejecting before the Argon2 call
    is the point: rejecting after it would have already paid the cost the limit
    exists to avoid.
    """


@dataclass(frozen=True, slots=True)
class Argon2Parameters:
    """The cost parameters, passed in rather than read from the environment.

    `load_settings()` re-reads the environment and re-parses `.env` on every call
    — it is deliberately not cached — so a module that called it per hash would
    turn every login into a file read.
    """

    time_cost: int
    memory_cost_kib: int
    parallelism: int

    @classmethod
    def from_settings(cls, settings: Settings) -> Argon2Parameters:
        return cls(
            time_cost=settings.argon2_time_cost,
            memory_cost_kib=settings.argon2_memory_cost_kib,
            parallelism=settings.argon2_parallelism,
        )


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """The verdict, plus whether the stored hash is now below policy.

    Two fields rather than two calls because the second question can only be
    answered while the first is being asked, and only a successful login has the
    plaintext needed to act on it.
    """

    is_valid: bool
    needs_rehash: bool


def _hasher(parameters: Argon2Parameters) -> PasswordHasher:
    return PasswordHasher(
        time_cost=parameters.time_cost,
        memory_cost=parameters.memory_cost_kib,
        parallelism=parameters.parallelism,
        hash_len=HASH_LENGTH,
        salt_len=SALT_LENGTH,
    )


def hash_password(password: str, parameters: Argon2Parameters, *, max_length: int) -> str:
    """Return the Argon2id encoding of `password`.

    The encoding carries the algorithm, version, parameters and salt, so nothing
    else needs storing and a later parameter change is detectable per row.
    """

    _reject_if_too_long(password, max_length)

    encoded = _hasher(parameters).hash(password)

    if len(encoded) > MAX_ENCODED_HASH_LENGTH:
        raise ValueError(
            f"the Argon2id encoding is {len(encoded)} characters and password_hash holds "
            f"{MAX_ENCODED_HASH_LENGTH}. A truncated hash never verifies and presents as a "
            "wrong password. Lower memory_cost or widen the column deliberately."
        )
    return encoded


def verify_password(
    encoded_hash: str, password: str, parameters: Argon2Parameters, *, max_length: int
) -> VerificationResult:
    """Check `password` against `encoded_hash`, and report whether to upgrade it.

    Never raises on a wrong password: a mismatch is an ordinary outcome and
    raising would push control flow for the commonest case into an exception
    handler, where a bare `except Exception` turns a rejection into an
    acceptance. It does raise `PasswordTooLong`, because that is a caller error
    rather than an authentication outcome.

    An unparseable or corrupted hash returns invalid rather than raising, for the
    same reason: a damaged row must fail the login, not the process. The library
    is what compares — `12_Security_RBAC_Audit.md:384` — so there is no
    hand-written equality anywhere in this module to get wrong.
    """

    _reject_if_too_long(password, max_length)

    hasher = _hasher(parameters)
    try:
        hasher.verify(encoded_hash, password)
    except argon2_exceptions.VerifyMismatchError:
        return VerificationResult(is_valid=False, needs_rehash=False)
    except argon2_exceptions.InvalidHashError:
        # Not a wrong password: the stored value is not an Argon2 encoding at
        # all. Still a failed login, and the caller records the distinction in
        # `auth_events` rather than telling the client.
        return VerificationResult(is_valid=False, needs_rehash=False)
    except argon2_exceptions.VerificationError:
        return VerificationResult(is_valid=False, needs_rehash=False)

    return VerificationResult(is_valid=True, needs_rehash=hasher.check_needs_rehash(encoded_hash))


def _reject_if_too_long(password: str, max_length: int) -> None:
    if len(password) > max_length:
        # The message names neither the password nor its length beyond the bound
        # already known to the caller.
        raise PasswordTooLong(f"password exceeds the configured maximum of {max_length} characters")
