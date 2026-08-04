"""Optimistic concurrency, in two shapes, because one is not enough.

**Shape A — `record_version` compare-and-swap.** For mutable aggregates. The
predicate goes in the UPDATE and the affected-row count decides the outcome.

**Shape B — exact resource ID plus expected content hash, under a row lock.**
For immutable snapshots, which deliberately have no `record_version`.
`bank_excel_exports` is the case: DOC-CONFLICT-025 records that it has no version
column while the batch around it does. A helper hardwired to shape A cannot
express the M7 mark-sent command at all, so both exist from the start — and
neither is chosen *for* exports here, because that target is the open conflict.

Three things are prohibited as the concurrency token, and the prohibition is
enforced by a test rather than a comment:

* `xmin` — PostgreSQL's transaction ID. Wraps around, is not preserved by a dump
  and restore, and changes on updates that alter nothing the caller cares about.
* `updated_at` — two updates inside the same clock tick are indistinguishable,
  and a clock that steps backwards makes a stale token look fresh.
* a row hash — a value can be rewritten to an identical one, so a lost update
  becomes invisible rather than detected.

What every shape has in common: the comparison happens **in the database, in the
statement that writes**. A read followed by a comparison in Python loses the race
under READ COMMITTED, and loses it silently — the guard looks correct and permits
the lost update anyway.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import Column, CursorResult, select, update
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, VersionConflictError
from app.core.time import utc_now
from app.db.base import Base

# Names that must never be used as a concurrency token. Asserted, not advised.
PROHIBITED_TOKENS: frozenset[str] = frozenset({"xmin", "updated_at", "row_hash", "content_hash"})


def primary_key_column(model: type[Base]) -> Column[Any]:
    """The mapped primary key, asked of the mapper rather than assumed to be `id`.

    Every table here uses `id`, and hardcoding it would still work today. Asking
    the mapper means a table that ever differs fails at the mapper rather than
    silently building a predicate against a column that is not the key.
    """

    keys = model.__mapper__.primary_key
    if len(keys) != 1:
        raise ValueError(
            f"{model.__tablename__} has a composite primary key; these helpers "
            "address a single row by a single key"
        )
    return cast("Column[Any]", keys[0])


@dataclass(frozen=True)
class SwapOutcome:
    """What a compare-and-swap did, for the caller's audit and outbox rows."""

    new_version: int
    rows_affected: int


def compare_and_swap[ModelT: Base](
    session: Session,
    model: type[ModelT],
    *,
    entity_id: uuid.UUID,
    expected_version: int,
    values: dict[str, Any],
    version_column: str = "record_version",
) -> SwapOutcome:
    """Update a mutable aggregate only if its version still matches.

    The predicate is part of the UPDATE, so no window exists between checking and
    writing. Zero affected rows means either the row is gone or the version moved;
    the caller is told which, because "reload and retry" and "it does not exist"
    call for different client behaviour.
    """

    if version_column in PROHIBITED_TOKENS:
        raise ValueError(
            f"{version_column!r} cannot be a concurrency token. See PROHIBITED_TOKENS "
            "for why each is unsafe."
        )

    version_attribute = getattr(model, version_column)
    identifier = primary_key_column(model)

    result = cast(
        "CursorResult[Any]",
        session.execute(
            update(model)
            .where(identifier == entity_id, version_attribute == expected_version)
            .values(**values, **{version_column: version_attribute + 1}, updated_at=utc_now())
        ),
    )

    if result.rowcount == 1:
        return SwapOutcome(new_version=expected_version + 1, rows_affected=1)

    # Distinguish absence from staleness with a second read. It is only reached
    # on the failure path, so the ordinary case still costs one statement.
    exists = session.execute(select(identifier).where(identifier == entity_id)).first()
    if exists is None:
        raise NotFoundError()
    raise VersionConflictError()


def lock_by_content_hash[ModelT: Base](
    session: Session,
    model: type[ModelT],
    *,
    entity_id: uuid.UUID,
    expected_hash: str,
    hash_column: str,
) -> ModelT:
    """Take a row lock on an immutable snapshot, keyed by ID and content hash.

    The shape immutable records need: they carry no version to increment, so the
    precondition is that the content is still exactly what the caller saw. The
    row lock is what makes the check meaningful — without it the row can change
    between the comparison and whatever the caller does next.

    `FOR UPDATE` here waits at most `lock_timeout`, which slice 2 set on every
    connection. Before that, a contended row meant waiting forever.
    """

    if hash_column in {"record_version"}:
        raise ValueError(
            "this is the shape for immutable snapshots; use compare_and_swap for "
            "an aggregate that carries a version"
        )

    identifier = primary_key_column(model)

    locked = session.execute(
        select(model).where(identifier == entity_id).with_for_update()
    ).scalar_one_or_none()

    if locked is None:
        raise NotFoundError()

    # Compared after the lock, never before: a comparison on an unlocked row is
    # only a statement about the past.
    if getattr(locked, hash_column) != expected_hash:
        raise VersionConflictError()

    return locked
