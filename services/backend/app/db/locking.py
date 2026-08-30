"""One global lock ordering rule, and a closed list of places locks are taken.

Deadlock is not a bug in either participant. Two commands, each locking its rows
in an order that is obviously right on its own, deadlock when their sets overlap.
M6 allocation locking and M9 evidence replacement are exactly that pair, and
neither author would be wrong. The only fix is a rule that predates both, which
is why this lands in M2 rather than when the second command is written.

**The rule.** Before taking any row lock, sort the targets by
`(scope.order, table_name, primary_key)` and lock in that order. Two commands
touching the same rows then queue instead of deadlocking, whatever order the
business logic thought of them in.

`scope.order` comes first because cross-table cycles are the case a per-table
sort cannot fix: locking `payment_requests` then `payment_batches` in one command
and the reverse in another deadlocks even if each sorts its own rows perfectly.

**The list is closed.** `LockScope` enumerates the coordination points
`04_Database_Schema.md:1691-1723` names and nothing else. A general-purpose
`lock_anything()` would be used, and the rule would be back to being discovered
per call site. Adding a scope is a deliberate edit here, reviewable on its own.

The ten `FOR UPDATE` call sites belong to M5 through M9. M2 owns the primitive
and the ordering, not the callers.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import IntEnum

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.concurrency import primary_key_column

# Reserved so an advisory key can never collide with one another subsystem
# invents. PostgreSQL advisory locks share one cluster-wide namespace, so an
# unreserved key is a collision waiting for the first unrelated caller.
ADVISORY_LOCK_NAMESPACE = 0x474F4C44  # "GOLD"


class LockScope(IntEnum):
    """The coordination points that may take a lock, in global lock order.

    The numbers are the ordering. They ascend roughly with the flow of value
    through the system — request, then batch, then export, then payment, then
    evidence — so a command that touches two scopes naturally locks the earlier
    one first, and any command that needs them in the other order is forced by
    this enum to reconsider rather than to deadlock.

    Gaps are intentional: a scope inserted later takes an unused number instead
    of renumbering the others, which would silently change every existing
    command's ordering.
    """

    TRADER_STATUS = 100
    REQUEST_REVISION_FINALISE = 200
    REQUEST_PAID_TOTAL = 250
    BATCH_VERSION_FINALISE = 300
    BATCH_VERSION_APPROVAL = 350
    EXPORT_GENERATE_FINAL = 400
    EXPORT_MARK_SENT = 450
    PAYMENT_ATTEMPT_CREATE = 500
    PAYMENT_ATTEMPT_CONFIRM = 550
    # M9 slice 1. A candidate decision touches `matching_candidates` and the segment's status and
    # **nothing else** — its migration grants no privilege on `payment_attempts` at all — so this
    # scope rarely meets another. It takes an unused number between the attempt and the evidence
    # link because that is where a suggestion sits in the flow of value: after the attempt exists,
    # before anything authoritative is written about it.
    #
    # It exists at all because `command_catalog.yaml:295` requires `candidate_version_revalidated`
    # and §12.5 gives the table no `record_version` to revalidate. Locking the row and re-reading
    # its status is the same guarantee for a row whose only mutable field is that status.
    MATCHING_CANDIDATE_DECIDE = 575
    EVIDENCE_LINK_REPLACE = 600
    RESULT_PUBLISH = 700


@dataclass(frozen=True, order=True)
class LockTarget:
    """One row to lock. Ordering is the global rule, encoded once.

    `order=True` on a frozen dataclass makes the field order the sort order, so
    the rule lives in the field declaration rather than in a comparison function
    someone could write differently elsewhere.
    """

    scope_order: int
    table_name: str
    primary_key: uuid.UUID

    @classmethod
    def of(cls, scope: LockScope, model: type[Base], primary_key: uuid.UUID) -> LockTarget:
        return cls(
            scope_order=int(scope),
            table_name=model.__tablename__,
            primary_key=primary_key,
        )


def ordered(targets: Iterable[LockTarget]) -> list[LockTarget]:
    """Apply the global ordering. Deduplicated: locking a row twice is a no-op
    that still costs a round trip, and a duplicate usually means two code paths
    each thought they owned the lock."""

    return sorted(set(targets))


def lock_rows(
    session: Session,
    targets: Sequence[LockTarget],
    *,
    models: dict[str, type[Base]],
) -> None:
    """Take row locks in the global order.

    Callers pass targets in whatever order the business logic produced. The
    ordering happens here, so a caller cannot get it wrong by being reasonable.
    """

    for target in ordered(targets):
        model = models.get(target.table_name)
        if model is None:
            raise KeyError(
                f"no model supplied for {target.table_name!r}; lock_rows cannot "
                "take a lock on a table it cannot name"
            )
        identifier = primary_key_column(model)
        session.execute(
            select(identifier).where(identifier == target.primary_key).with_for_update()
        )


def advisory_key(scope: LockScope, discriminator: str) -> tuple[int, int]:
    """A stable two-int advisory key inside the reserved namespace.

    Two ints rather than one 64-bit value because the two-argument form keeps the
    namespace visible in `pg_locks`, where a single opaque bigint tells an
    operator nothing about who holds it.
    """

    digest = hashlib.sha256(f"{int(scope)}:{discriminator}".encode()).digest()
    # Signed 32-bit, which is what pg_advisory_lock(int, int) accepts.
    second = int.from_bytes(digest[:4], "big", signed=True)
    return ADVISORY_LOCK_NAMESPACE, second


def acquire_advisory_lock(session: Session, scope: LockScope, discriminator: str) -> None:
    """Serialise work that has no single row to lock.

    Transaction-scoped (`pg_advisory_xact_lock`), so it is released by commit or
    rollback and cannot be leaked by a path that forgets to unlock. A
    session-scoped advisory lock survives a rollback and outlives the work it was
    protecting, which turns one failed command into a queue that never drains.
    """

    namespace, key = advisory_key(scope, discriminator)
    session.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, :key)"),
        {"namespace": namespace, "key": key},
    )
