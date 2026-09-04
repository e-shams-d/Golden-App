"""A recipient's own notifications, bounded and stably ordered.
`05_API_Specification.md:2077`, `15_Agent_Implementation_Plan.md:1298`.

M11 slice 1. **`app/db/pagination.py` is reused, not re-decided.** It was written for the audit read
and has had one caller since; it already expresses cursor pagination, a sort allowlist, a filter
allowlist and a limit. §19 `:1298`'s six query rules are five-sixths of that helper, and writing a
second one would have been the easy path and the wrong one — M8's rule: look for the helper before
writing one.

**The scope is the recipient, not a permission.** `permission_catalog.yaml` has no notification
permission at all, and inventing one would be a governance act rather than an implementation. What
constrains this query is `recipient_actor_id` — the row's own owner — which is what
`app/security/ownership.py` exists for.

`created_at` is not unique, so it cannot terminate a sort on its own: two notifications written by
one dispatcher pass share a transaction and can share a timestamp. `id` is the unique tiebreak, and
without it the second page silently repeats or drops rows.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.db.models.notification import Notification
from app.db.pagination import (
    ListSpec,
    Page,
    SortField,
    apply_pagination,
    build_page,
)

# The index `20260902_0033` built is `(recipient_actor_type, recipient_actor_id, created_at)`, and
# the spec is written next to it deliberately: `ListSpec`'s own docstring says it is "constructed
# once per read path, next to the indexes that support it, rather than assembled from request
# parameters — which is how an unindexed column becomes filterable by accident."
NOTIFICATION_LIST_SPEC = ListSpec(
    sorts=(
        SortField("created_at", Notification.created_at),
        # Unique, and the only column here that can terminate a sort on its own — `ListSpec`
        # refuses a spec without one. `created_at` cannot: two notifications written by one
        # dispatcher pass share a transaction and can share a timestamp, and a sort that ends
        # there repeats or drops rows at the page boundary.
        SortField("id", Notification.id, unique=True),
    ),
    # Three, and each is either the index's own column or a low-cardinality value the recipient
    # scope has already narrowed. `entity_id` is deliberately absent: filtering by it would be a
    # lookup rather than a list, and it has no index of its own.
    filters=frozenset({"status", "notification_type", "entity_type"}),
    default_sort="created_at",
)


@dataclass(frozen=True, slots=True)
class NotificationQuery:
    """What a caller may narrow the list by.

    **No recipient field.** The recipient is not a filter — it is the scope, applied from the
    session in `read_notification_page` below. A recipient parameter would be a filter somebody
    could omit, and omitting it would return everybody's notifications.
    """

    status: str | None = None
    notification_type: str | None = None
    entity_type: str | None = None

    def applied_filters(self) -> dict[str, object]:
        return {
            name: value
            for name, value in {
                "status": self.status,
                "notification_type": self.notification_type,
                "entity_type": self.entity_type,
            }.items()
            if value is not None
        }


def _for_recipient(
    recipient_actor_type: str, recipient_actor_id: uuid.UUID, query: NotificationQuery
) -> Select[tuple[Notification]]:
    statement = select(Notification).where(
        Notification.recipient_actor_type == recipient_actor_type,
        Notification.recipient_actor_id == recipient_actor_id,
    )
    for name, value in query.applied_filters().items():
        # Checked even though the dataclass already limits the names, on
        # `app/audit/reading.py`'s reasoning: the spec is the single place that decides what is
        # filterable, and a field added to the dataclass without an index must fail here rather
        # than run.
        NOTIFICATION_LIST_SPEC.require_filterable(name)
        statement = statement.where(getattr(Notification, name) == value)
    return statement


def read_notification_page(
    session: Session,
    *,
    recipient_actor_type: str,
    recipient_actor_id: uuid.UUID,
    query: NotificationQuery | None = None,
    sort: str | None = None,
    descending: bool = True,
    limit: int | None = None,
    cursor: str | None = None,
) -> Page[Notification]:
    """One bounded, totally ordered page of one recipient's own notifications.

    The recipient is a keyword argument rather than part of `query`, so a caller cannot construct
    a page request that omits it. `SEC-NOTIFY-001` is that shape asserted from the outside.
    """

    statement, effective = apply_pagination(
        _for_recipient(recipient_actor_type, recipient_actor_id, query or NotificationQuery()),
        NOTIFICATION_LIST_SPEC,
        sort=sort,
        descending=descending,
        limit=limit,
        cursor=cursor,
    )
    rows: Sequence[Notification] = session.execute(statement).scalars().all()
    return build_page(rows, effective, NOTIFICATION_LIST_SPEC, sort=sort)
