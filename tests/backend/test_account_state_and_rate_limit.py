"""Account states, lockout arithmetic, and the CGNAT-shaped rate limiter.

No database and no Redis server: the account and lockout modules are pure policy
by design, and the limiter is exercised against a fake client so the failure
cases — an outage, a key holding the wrong type — can be produced on demand
rather than waited for.

Covers: SEC-ACCT-001, SEC-ACCT-002, SEC-ACCT-003, SEC-LOCK-001, SEC-LOCK-002,
SEC-LOCK-003, SEC-RATE-001.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.security import account_state
from app.security.account_state import AccountAction, AccountRefusal, refusal_for
from app.security.lockout import LockoutPolicy, after_failure, after_success
from app.security.rate_limit import (
    AuthenticationRateLimiter,
    RateLimitPolicy,
    RateLimitScope,
    key_for,
)
from app.security.sessions import SessionRejection, classify_identity
from redis import RedisError

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
FUTURE = NOW + timedelta(minutes=10)
PAST = NOW - timedelta(minutes=10)

SECRET = b"a" * 32


class FakeRedis:
    """Just enough Redis to count, and to fail when asked to.

    A fake rather than a real server because the interesting cases here are the
    ones a healthy server never produces: an outage mid-attempt, and a key
    holding a value this module did not write.
    """

    def __init__(self, *, fail: bool = False, value: Any = None) -> None:
        self.counts: dict[str, int] = {}
        self.expiries: list[tuple[str, int, bool]] = []
        self._fail = fail
        self._value = value
        # A clock the test moves by hand. Without one this fake can record that EXPIRE
        # was called but never that it did anything, so the property that matters —
        # whether a counter is still there a window later — cannot be asserted. The
        # absence of this clock is why the unbounded lockout survived a suite that
        # already had a test about the expiry.
        self.now: float = 0.0
        self._expires_at: dict[str, float] = {}

    def advance(self, seconds: float) -> None:
        """Move the clock and drop whatever has fallen due, as a real server would."""

        self.now += seconds
        self._collect()

    def _collect(self) -> None:
        for key, due in list(self._expires_at.items()):
            if due <= self.now:
                del self._expires_at[key]
                self.counts.pop(key, None)

    def pipeline(self) -> FakeRedis:
        self._queued: list[tuple[str, Any]] = []
        return self

    def incr(self, key: str) -> None:
        self._queued.append(("incr", key))

    def expire(self, key: str, seconds: int, nx: bool = False) -> None:
        self._queued.append(("expire", (key, seconds, nx)))

    def execute(self) -> list[Any]:
        if self._fail:
            raise RedisError("connection refused")
        self._collect()
        results: list[Any] = []
        for operation, argument in self._queued:
            if operation == "incr":
                self.counts[argument] = self.counts.get(argument, 0) + 1
                results.append(self._value if self._value is not None else self.counts[argument])
            else:
                key, seconds, nx = argument
                self.expiries.append((key, seconds, nx))
                # NX is the whole point: an EXPIRE that arrives while a TTL is already
                # running must not move it. Modelled rather than ignored, or the fake
                # would report success for the behaviour that caused the defect.
                if nx and key in self._expires_at:
                    results.append(False)
                else:
                    self._expires_at[key] = self.now + seconds
                    results.append(True)
        return results


def limiter(client: Any, *, identifier_max: int = 3, network_max: int = 10) -> Any:
    policy = RateLimitPolicy(
        identifier_max_attempts=identifier_max,
        network_max_attempts=network_max,
        window_seconds=300,
    )
    return AuthenticationRateLimiter(client, policy, SECRET)


# --- account state ---------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (account_state.ACTIVE, None),
        (account_state.SUSPENDED, AccountRefusal.SUSPENDED),
        (account_state.RECOVERY_REQUIRED, AccountRefusal.RECOVERY_REQUIRED),
        (account_state.DEACTIVATED, AccountRefusal.DEACTIVATED),
    ],
)
def test_only_an_active_account_may_authenticate(status: str, expected: object) -> None:
    """SEC-ACCT-001."""

    assert refusal_for(status, None, NOW, AccountAction.AUTHENTICATE) is expected


def test_an_unknown_status_refuses_everything() -> None:
    """Fail closed on a value nobody has defined, per doc 12:629's reasoning."""

    for action in AccountAction:
        assert refusal_for("some_new_state", None, NOW, action) is AccountRefusal.UNKNOWN_STATUS


def test_recovery_required_permits_only_the_recovery_flow() -> None:
    """SEC-ACCT-003. And an administrative reset outlives an already-open tab."""

    assert refusal_for(account_state.RECOVERY_REQUIRED, None, NOW, AccountAction.RECOVER) is None
    assert (
        refusal_for(account_state.RECOVERY_REQUIRED, None, NOW, AccountAction.AUTHENTICATE)
        is AccountRefusal.RECOVERY_REQUIRED
    )
    assert (
        refusal_for(account_state.RECOVERY_REQUIRED, None, NOW, AccountAction.ACT)
        is AccountRefusal.RECOVERY_REQUIRED
    )


def test_an_active_account_cannot_enter_the_recovery_flow() -> None:
    """Otherwise guessing a username is a way to strand its owner.

    Recovery is for an account an administrator has already reset. Letting it run
    against a healthy account would let anyone who knows a username push it into
    `recovery_required` and invalidate a working credential.
    """

    assert (
        refusal_for(account_state.ACTIVE, None, NOW, AccountAction.RECOVER)
        is AccountRefusal.RECOVERY_NOT_APPLICABLE
    )


def test_a_lock_blocks_signing_in() -> None:
    """SEC-LOCK-001's policy half."""

    assert (
        refusal_for(account_state.ACTIVE, FUTURE, NOW, AccountAction.AUTHENTICATE)
        is AccountRefusal.LOCKED
    )


def test_a_lock_does_not_end_a_session_that_already_exists() -> None:
    """SEC-ACCT-002's counterpart, and the reason this module exists separately.

    If a lock rejected live sessions, failing a handful of logins against a
    manager's username would end that manager's session — an on-demand logout of
    any user, requiring no credential, available to anyone who knows a username.
    The control against guessing would become a denial-of-service tool.

    Immediate administrative cut-off is `suspended`, which is recorded and takes
    effect through the security stamp.
    """

    assert refusal_for(account_state.ACTIVE, FUTURE, NOW, AccountAction.ACT) is None
    assert classify_identity(account_state.ACTIVE, FUTURE, NOW) is None

    # Suspension is the mechanism that does stop a live session.
    assert classify_identity(account_state.SUSPENDED, None, NOW) is (
        SessionRejection.IDENTITY_NOT_ACTIVE
    )


def test_a_lock_expires_without_anything_running() -> None:
    """SEC-LOCK-002. The property that made `locked` unnecessary as a status."""

    assert account_state.is_locked(FUTURE, NOW)
    assert not account_state.is_locked(PAST, NOW)
    assert not account_state.is_locked(None, NOW)
    assert refusal_for(account_state.ACTIVE, PAST, NOW, AccountAction.AUTHENTICATE) is None


# --- lockout arithmetic ----------------------------------------------------


def test_failures_accumulate_and_lock_at_the_threshold() -> None:
    """SEC-LOCK-001."""

    policy = LockoutPolicy(threshold=3, lock_duration_seconds=900)

    first = after_failure(0, None, NOW, policy)
    assert first.failed_login_count == 1 and first.locked_until is None

    second = after_failure(first.failed_login_count, first.locked_until, NOW, policy)
    assert second.failed_login_count == 2 and second.locked_until is None

    third = after_failure(second.failed_login_count, second.locked_until, NOW, policy)
    assert third.failed_login_count == 3
    assert third.locked_until == NOW + timedelta(seconds=900)


def test_attacking_through_a_lock_extends_it_rather_than_running_it_down() -> None:
    """A lock that freezes the counter is a pause, not a penalty."""

    policy = LockoutPolicy(threshold=3, lock_duration_seconds=900)
    later = NOW + timedelta(minutes=5)

    during = after_failure(3, NOW + timedelta(seconds=900), later, policy)

    assert during.failed_login_count == 4
    assert during.locked_until == later + timedelta(seconds=900), (
        "a failure during a lock must restart the window, or an attacker can keep "
        "guessing for free until it lapses"
    )


def test_success_clears_both_columns() -> None:
    """A stale future lock would re-lock the account on its next request."""

    cleared = after_success(NOW)

    assert cleared.failed_login_count == 0
    assert cleared.locked_until is None


def test_a_nonsensical_policy_is_refused() -> None:
    with pytest.raises(ValueError, match="below 1"):
        LockoutPolicy(threshold=0, lock_duration_seconds=900)
    with pytest.raises(ValueError, match="not a lock"):
        LockoutPolicy(threshold=3, lock_duration_seconds=0)


# --- rate limiting ---------------------------------------------------------


def test_the_identifier_axis_refuses_past_its_ceiling() -> None:
    """SEC-RATE-001, the control half."""

    client = FakeRedis()
    limit = limiter(client, identifier_max=3)

    for _ in range(3):
        assert limit.check("09123456789", "10.0.0.1").allowed

    refused = limit.check("09123456789", "10.0.0.1")
    assert not refused.allowed
    assert refused.scope is RateLimitScope.IDENTIFIER


def test_the_two_axes_count_independently() -> None:
    """A different identifier from the same address is not the same bucket."""

    client = FakeRedis()
    limit = limiter(client, identifier_max=2, network_max=10)

    assert limit.check("09120000001", "10.0.0.1").allowed
    assert limit.check("09120000001", "10.0.0.1").allowed
    assert not limit.check("09120000001", "10.0.0.1").allowed

    # A different user behind the same CGNAT address is unaffected.
    assert limit.check("09120000002", "10.0.0.1").allowed


def test_the_network_ceiling_must_exceed_the_identifier_ceiling() -> None:
    """The CGNAT decision, enforced rather than left to a comment.

    Under carrier-grade NAT one address carries many unrelated subscribers, so a
    network ceiling at or below the identifier ceiling locks out a carrier the
    moment a handful of its customers sign in.
    """

    with pytest.raises(ValueError, match="CGNAT"):
        RateLimitPolicy(identifier_max_attempts=10, network_max_attempts=5, window_seconds=300)


def test_keys_are_not_reversible_and_are_scope_separated() -> None:
    """A raw phone number in Redis would be a directory of who uses the platform."""

    number = "09123456789"
    key = key_for(RateLimitScope.IDENTIFIER, number, SECRET)

    assert number not in key
    assert key == key_for(RateLimitScope.IDENTIFIER, number, SECRET), "counting needs stability"
    assert key != key_for(RateLimitScope.NETWORK, number, SECRET), "scopes must not share a bucket"
    assert key != key_for(RateLimitScope.IDENTIFIER, number, b"b" * 32), (
        "the secret must change the key, or it is a plain hash and reversible by "
        "enumerating ~10^9 Iranian mobile numbers"
    )


def test_an_empty_key_secret_is_refused() -> None:
    with pytest.raises(ValueError, match="reversible by enumeration"):
        key_for(RateLimitScope.IDENTIFIER, "09123456789", b"")


def test_expire_accompanies_every_attempt_but_never_extends_the_window() -> None:
    """Both halves, because each without the other is a way to lock an account forever.

    EXPIRE on every INCR: a TTL set only on creation is lost if the process dies between
    the two, and the key left behind blocks the identifier permanently.

    `nx=True` on every one of them: without it the expiry moves on each attempt, refused
    attempts included, and since the counter is never reset a caller who keeps retrying
    keeps their own lockout alive. The original asserted only the first half, which is
    why the second could be wrong for as long as it was.
    """

    client = FakeRedis()
    limit = limiter(client)

    limit.check("09123456789", None)
    limit.check("09123456789", None)

    identifier_expiries = [entry for entry in client.expiries if "identifier" in entry[0]]
    assert len(identifier_expiries) == 2, "EXPIRE must accompany every INCR, not just the first"
    assert all(seconds == 300 for _, seconds, _nx in identifier_expiries)
    assert all(nx for *_rest, nx in identifier_expiries), (
        "an EXPIRE without NX extends a window that is already running, which is how a "
        "300-second limit became an unbounded lockout"
    )


def test_a_caller_who_keeps_retrying_still_recovers_when_the_window_passes() -> None:
    """The property the whole control rests on, and the one nothing asserted.

    A person who mistypes their password past the ceiling and then keeps trying — which
    is what people do — must be let back in one window after their FIRST attempt, not one
    window after their last. Under the old EXPIRE the counter's life was extended by every
    refused attempt, so this test would loop to its end still refused.

    Measured against the running stack on 2026-09-28 before the fix: retrying every 30
    seconds for six minutes never recovered, while 330 seconds of complete silence let the
    very same password through on the first try.
    """

    client = FakeRedis()
    limit = limiter(client)
    phone = "09123456789"

    for _ in range(11):  # ceiling is 10; the eleventh is the first refusal
        decision = limit.check(phone, None)
    assert not decision.allowed, "the ceiling did not refuse"
    assert decision.scope is RateLimitScope.IDENTIFIER

    # The caller keeps trying inside the window. None of this may postpone recovery.
    for _ in range(10):
        client.advance(30)
        decision = limit.check(phone, None)

    assert decision.allowed, (
        "still refused a full window after the first attempt. The expiry is being pushed "
        "out by attempts that are themselves being refused, so anyone who keeps retrying "
        "can never get back in — and an attacker who knows a phone number can hold that "
        "account shut with one request every few minutes"
    )


def test_a_redis_outage_allows_the_attempt_and_says_so() -> None:
    """SEC-RATE-001's failure mode, stated rather than discovered.

    Failing open degrades from two controls to one — the durable counter and lock
    in PostgreSQL are untouched by a Redis outage. Failing closed would turn a
    cache outage into a total authentication outage for a settlement platform.
    """

    decision = limiter(FakeRedis(fail=True)).check("09123456789", "10.0.0.1")

    assert decision.allowed
    assert decision.degraded, "a degraded decision must be visible, not silent"


def test_a_key_holding_the_wrong_type_does_not_read_as_a_count() -> None:
    """Guard the guard: a non-integer reply must not be coerced into a count.

    `int(b"7")` would succeed and silently keep limiting off something this
    module did not write.
    """

    decision = limiter(FakeRedis(value="not-an-integer")).check("09123456789", None)

    assert decision.allowed
    assert decision.degraded
