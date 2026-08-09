"""Authentication rate limiting, keyed for a country where CGNAT is the norm.

`12_Security_RBAC_Audit.md:483` requires limiting by normalized account
identifier **and** network source, using privacy-conscious keys. Both halves are
here, but they are deliberately not symmetric, and the asymmetry is the important
design decision in this module.

**Why the network limit is loose.** This platform is deployed only in Iran, where
carrier-grade NAT is the norm on mobile networks: hundreds or thousands of
unrelated subscribers share one public address. A network limit tight enough to
stop one attacker would lock out every other customer of that carrier, and the
attacker — who can rotate through mobile data, a VPN, or simply wait — is the
least inconvenienced party. So the identifier limit is the control, and the
network limit is a coarse backstop with a much higher ceiling: it exists to catch
a single source spraying thousands of *different* usernames, which is the one
attack the identifier limit cannot see.

**Why the keys are hashed.** Storing a raw phone number or IP address in Redis
would put a directory of who uses the platform, and from where, in a datastore
with no persistence, no encryption and a wider blast radius than the database.
The HMAC makes a key unusable for lookup by anyone who does not hold the secret,
while still being stable enough to count against.

**Why this fails open.** If Redis is unreachable the limiter allows the attempt.
That is not laziness: the durable defences — the failed-login counter and the
lock, both in PostgreSQL — are unaffected by a Redis outage, so failing open
degrades from two controls to one. Failing closed would convert a cache outage
into a total authentication outage, locking out every legitimate user of a
settlement platform to slow an attacker who is already being counted and locked
by the durable half. The trade is stated here so a future reader can disagree
with the reasoning rather than discover the behaviour.

Covers: SEC-RATE-001.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from enum import StrEnum

from redis import Redis, RedisError

# Key namespace. Versioned so a change in what a key means can be rolled out by
# changing the prefix rather than by reasoning about what the old keys counted.
_KEY_PREFIX = "authrate:v1"


class RateLimitScope(StrEnum):
    """The two axes, which carry different limits for different reasons."""

    IDENTIFIER = "identifier"
    """The normalized account identifier. The real control."""

    NETWORK = "network"
    """The network source. A coarse backstop; see the module docstring on CGNAT."""


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """Ceilings and the window, injected rather than read from the environment."""

    identifier_max_attempts: int
    network_max_attempts: int
    window_seconds: int

    def __post_init__(self) -> None:
        if self.identifier_max_attempts < 1 or self.network_max_attempts < 1:
            raise ValueError("a ceiling below 1 would refuse the first attempt")
        if self.window_seconds < 1:
            raise ValueError("a window shorter than a second counts nothing")
        if self.network_max_attempts < self.identifier_max_attempts:
            raise ValueError(
                "the network ceiling is below the identifier ceiling, which inverts the "
                "design: under CGNAT one address carries many unrelated users, so the "
                "network axis must be the looser of the two or it locks out a carrier"
            )


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    scope: RateLimitScope | None = None
    degraded: bool = False
    """True when Redis was unreachable and the attempt was allowed without counting."""


def key_for(scope: RateLimitScope, value: str, secret: bytes) -> str:
    """A stable, non-reversible key.

    HMAC rather than a bare hash: a plain SHA-256 of a phone number is trivially
    reversed by enumerating the number space, which for Iranian mobile numbers is
    about 10^9 candidates — seconds of work. The secret is what makes the mapping
    unrecoverable to anyone holding only the Redis contents.
    """

    if not secret:
        raise ValueError(
            "the rate-limit key secret is empty, so keys would be a plain hash of a "
            "phone number or address — reversible by enumeration"
        )
    digest = hmac.new(secret, f"{scope.value}:{value}".encode(), hashlib.sha256).hexdigest()
    return f"{_KEY_PREFIX}:{scope.value}:{digest}"


class AuthenticationRateLimiter:
    """A fixed-window counter over Redis.

    A fixed window rather than a sliding log: the log is more accurate at the
    boundary and costs a sorted set per identifier, and the accuracy buys nothing
    here because the ceiling is already a blunt number. The boundary artefact —
    up to twice the ceiling across two adjacent windows — is bounded and
    acceptable for a control whose job is to make guessing slow rather than to
    make it impossible.
    """

    def __init__(self, client: Redis, policy: RateLimitPolicy, key_secret: bytes) -> None:
        self._client = client
        self._policy = policy
        self._key_secret = key_secret

    def _ceiling(self, scope: RateLimitScope) -> int:
        if scope is RateLimitScope.IDENTIFIER:
            return self._policy.identifier_max_attempts
        return self._policy.network_max_attempts

    def _count(self, scope: RateLimitScope, value: str) -> int | None:
        """Increment and return the new count, or `None` if Redis is unreachable."""

        key = key_for(scope, value, self._key_secret)
        try:
            pipeline = self._client.pipeline()
            pipeline.incr(key)
            # Refreshed on every attempt rather than set once on creation. A TTL
            # set only when the counter is created leaves a key with no
            # expiry if the process dies between INCR and EXPIRE, and that key
            # then blocks the identifier forever.
            pipeline.expire(key, self._policy.window_seconds)
            # redis-py's pipeline is untyped, so the result is narrowed here
            # rather than trusted. INCR answers with an integer; anything else
            # means the key holds something this module did not put there, and
            # treating that as a count would silently stop limiting.
            results: list[object] = pipeline.execute()  # type: ignore[no-untyped-call]
        except RedisError:
            return None

        count = results[0] if results else None
        if not isinstance(count, int):
            return None
        return count

    def check(self, identifier: str, network_source: str | None) -> RateLimitDecision:
        """Count this attempt and say whether it may proceed.

        Both axes are counted even when the first already refuses, so a refusal
        on one does not hide the other's signal from an investigator.
        """

        identifier_count = self._count(RateLimitScope.IDENTIFIER, identifier)
        network_count = (
            self._count(RateLimitScope.NETWORK, network_source)
            if network_source is not None
            else None
        )

        if identifier_count is None and network_count is None:
            # Redis is gone. The durable counter and lock in PostgreSQL still
            # apply; see the module docstring for why this is the safer failure.
            return RateLimitDecision(allowed=True, degraded=True)

        if identifier_count is not None and identifier_count > self._ceiling(
            RateLimitScope.IDENTIFIER
        ):
            return RateLimitDecision(allowed=False, scope=RateLimitScope.IDENTIFIER)

        if network_count is not None and network_count > self._ceiling(RateLimitScope.NETWORK):
            return RateLimitDecision(allowed=False, scope=RateLimitScope.NETWORK)

        return RateLimitDecision(allowed=True)
