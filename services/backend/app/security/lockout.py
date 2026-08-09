"""Failed-login counting and temporary lock — the arithmetic, with no I/O.

The state lives in PostgreSQL, on `admin_users`/`trader_users.failed_login_count`
and `.locked_until`, and not in Redis. `infra/redis/redis.conf` sets
`appendonly no` and `save ""` — zero persistence — so a Redis-backed counter
resets on every restart and an attacker only has to wait for one, or cause one.
`12_Security_RBAC_Audit.md:488` states the requirement: Redis loss must not
erase account or security state that has to be durable.

This module is the decision, not the write. It computes what the columns should
become; the login command performs the `UPDATE` inside its own transaction, so
the counter moves in the same commit as the `auth_events` row that explains why.
Splitting it this way is what lets the policy be tested exhaustively without a
database, and it keeps the rule in one readable place instead of spread through
an `UPDATE ... SET failed_login_count = failed_login_count + 1` that also decides
policy in its `CASE`.

**The threshold is not exposed to the client.** `12_Security_RBAC_Audit.md:486`
requires that, and it is the reason nothing here returns "3 attempts remaining":
that number tells an attacker exactly how much budget they have and when to pause
to avoid tripping it.

Covers: SEC-LOCK-001, SEC-LOCK-002, SEC-LOCK-003.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class LockoutPolicy:
    """Thresholds, injected rather than read from the environment."""

    threshold: int
    lock_duration_seconds: int

    def __post_init__(self) -> None:
        if self.threshold < 1:
            raise ValueError("a lockout threshold below 1 would lock on the first attempt")
        if self.lock_duration_seconds < 1:
            raise ValueError("a lock that expires immediately is not a lock")


@dataclass(frozen=True, slots=True)
class CounterState:
    """What the two columns should hold after this attempt.

    Both are always returned, even when unchanged, so the caller writes one
    `UPDATE` with both values rather than branching on which to set — a branch
    that forgets to clear `locked_until` leaves an account locked forever.
    """

    failed_login_count: int
    locked_until: datetime | None


def after_failure(
    current_count: int,
    locked_until: datetime | None,
    now: datetime,
    policy: LockoutPolicy,
) -> CounterState:
    """Count the failure, and lock once the threshold is reached.

    An attempt made while already locked still counts. The alternative — freezing
    the counter during a lock — means an attacker can keep guessing through the
    lock window at no cost and resume exactly where they stopped, which turns the
    lock into a pause rather than a penalty.

    The lock window restarts from `now` on each failure past the threshold, so
    continued attacking extends the lock instead of running it down.
    """

    count = current_count + 1
    if count >= policy.threshold:
        return CounterState(
            failed_login_count=count,
            locked_until=now + timedelta(seconds=policy.lock_duration_seconds),
        )
    return CounterState(failed_login_count=count, locked_until=locked_until)


def after_success(now: datetime) -> CounterState:
    """Clear both columns.

    `locked_until` is cleared rather than left to expire because a successful
    authentication proves the credential holder is present, which is the only
    thing the lock was waiting to establish. Leaving a stale future timestamp
    would lock the account again on its next request for a reason that no longer
    applies.

    `now` is unused and still required: a signature that cannot accept the clock
    invites a later change to reach for `datetime.now()` inside, and this module
    is deliberately clock-free so its tests are not time-dependent.
    """

    del now
    return CounterState(failed_login_count=0, locked_until=None)
