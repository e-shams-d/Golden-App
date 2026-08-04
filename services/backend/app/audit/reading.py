"""The audit read path, as the first user of the list conventions.

`audit_logs` is the table those conventions were written for. It only grows, it
is the widest table in the schema, and every one of its seven indexes exists for
a specific access path — so a filter on an unlisted column is the difference
between an index scan and reading the whole history.

The sort defaults to `sequence_number`, which is why that column exists.
`occurred_at` is not unique: two rows written in the same transaction share it,
so paginating on it alone lets a page boundary fall between them and repeat or
drop one. The sequence number terminates every sort here.

Reads never mutate. There is no "mark as seen", no lazy backfill, no counter
increment — `audit_logs` grants the runtime role no UPDATE, so anything of that
kind would fail at the database, but the rule is worth stating where the read
lives rather than discovering it from a privilege error.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.db.models.audit_log import AuditLog
from app.db.pagination import ListSpec, Page, SortField, apply_pagination, build_page

AUDIT_LIST_SPEC = ListSpec(
    sorts=(
        # Unique, monotonic, and indexed: the only column here that can terminate
        # a sort on its own.
        SortField("sequence_number", AuditLog.sequence_number, unique=True),
        SortField("occurred_at", AuditLog.occurred_at),
    ),
    # Exactly the columns the seven documented indexes cover. Adding one here
    # without an index turns a page request into a sequential scan.
    filters=frozenset(
        {
            "action",
            "actor_type",
            "actor_id",
            "entity_type",
            "entity_id",
            "request_id",
            "correlation_id",
        }
    ),
    default_sort="sequence_number",
)


@dataclass(frozen=True)
class AuditQuery:
    """A read request, already reduced to allowlisted fields."""

    action: str | None = None
    actor_type: str | None = None
    actor_id: uuid.UUID | None = None
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    request_id: str | None = None
    correlation_id: str | None = None

    def applied_filters(self) -> dict[str, object]:
        return {
            name: value
            for name, value in {
                "action": self.action,
                "actor_type": self.actor_type,
                "actor_id": self.actor_id,
                "entity_type": self.entity_type,
                "entity_id": self.entity_id,
                "request_id": self.request_id,
                "correlation_id": self.correlation_id,
            }.items()
            if value is not None
        }


def _filtered(query: AuditQuery) -> Select[tuple[AuditLog]]:
    statement = select(AuditLog)
    for name, value in query.applied_filters().items():
        # Checked even though the dataclass already limits the names: the spec is
        # the single place that decides what is filterable, and a field added to
        # the dataclass without an index must fail here rather than run.
        AUDIT_LIST_SPEC.require_filterable(name)
        statement = statement.where(getattr(AuditLog, name) == value)
    return statement


def read_audit_page(
    session: Session,
    query: AuditQuery | None = None,
    *,
    sort: str | None = None,
    descending: bool = True,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[AuditLog]:
    """One bounded, totally ordered page of audit history."""

    statement, effective = apply_pagination(
        _filtered(query or AuditQuery()),
        AUDIT_LIST_SPEC,
        sort=sort,
        descending=descending,
        limit=limit,
        cursor=cursor,
    )
    rows: Sequence[AuditLog] = session.execute(statement).scalars().all()
    return build_page(rows, effective, AUDIT_LIST_SPEC, sort=sort)
