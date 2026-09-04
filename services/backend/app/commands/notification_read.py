"""Marking a notification read. `05_API_Specification.md:2077`.

M11 slice 1. Two commands over the table M9 built and nothing has been able to reach.

**Neither command writes anything a person was told.** `20260913_0044` grants `status` and
`read_at` alone, so the title, the body and the entity a notification points at are unwritable by
the runtime. A message whose text could change after it was sent is not a record of what somebody
was told.

**"Read" is not workflow truth**, and document 05 `:2085` says so in the same breath as the routes:
"Notifications are deduplicated from outbox events and are not workflow truth." So neither command
touches the thing the notification is about — no publication is acknowledged, no task is resolved,
no order moves. Reading a message is a fact about the reader.

**No audit entry, and that is a decision rather than an omission.** `audit_outbox_catalog.yaml`
names no action for reading a notification, and `04_Database_Schema.md`'s audit table is for
business changes — `10_Backend_Implementation_Guide.md` scopes it to "critical financial, evidence,
publication, and dispatch mutations". Writing an uncatalogued action for every list a trader opens
would put thousands of rows a year into the table an auditor reads, and would be the eighth
declared name of a milestone that has not started. Recorded in the plan as G-5 rather than
invented.

Covers: SVC-NOTIFY-001.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.models.notification import (
    NOTIFICATION_READ,
    NOTIFICATION_UNREAD,
    Notification,
)
from app.db.unit_of_work import SqlAlchemyUnitOfWork


@dataclass(frozen=True, slots=True)
class MarkNotificationRead:
    notification_id: uuid.UUID
    recipient_actor_type: str
    recipient_actor_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class MarkAllNotificationsRead:
    recipient_actor_type: str
    recipient_actor_id: uuid.UUID


def mark_read(
    command: MarkNotificationRead, *, uow: SqlAlchemyUnitOfWork, now: datetime
) -> Notification:
    """One notification, and only if it is the caller's own.

    **404 rather than 403 for somebody else's**, on `app/security/ownership.py`'s rule: an
    authorisation error over a guessable identifier tells the caller the row exists.

    Idempotent without an idempotency key. Marking a read notification read again returns it
    unchanged rather than moving `read_at` — the moment somebody first read it is the fact worth
    keeping, and a second call is a client retrying rather than a person reading twice.
    """

    session = uow.session
    notification = session.get(Notification, command.notification_id)
    if notification is None:
        raise NotFoundError()
    if (
        notification.recipient_actor_type != command.recipient_actor_type
        or notification.recipient_actor_id != command.recipient_actor_id
    ):
        raise NotFoundError()

    if notification.status == NOTIFICATION_UNREAD:
        notification.status = NOTIFICATION_READ
        notification.read_at = now
        uow.flush()
    return notification


def mark_all_read(
    command: MarkAllNotificationsRead, *, uow: SqlAlchemyUnitOfWork, now: datetime
) -> int:
    """Every unread notification of **this** recipient. Returns how many moved.

    **The recipient predicate is in the same statement as the update**, not a filter applied to a
    list read beforehand. A read-then-update would mark rows that arrived between the two, and —
    worse — a refactor that dropped the recipient clause from the read would be invisible here
    while marking everybody's.

    `dismissed` is left alone. `status_catalog.yaml` gives the notification three states and
    dismissing is a different act from reading; sweeping it into `read` would erase which one a
    person performed.
    """

    # `Session.execute` is typed as returning `Result`, and `rowcount` belongs to the
    # `CursorResult` a DML statement actually produces. Cast rather than ignore, so the narrowing
    # says which type it is instead of only that mypy was wrong — the same call
    # `app/commands/change_own_password.py` makes for the same reason.
    result = cast(
        "CursorResult[Any]",
        uow.session.execute(
            update(Notification)
            .where(
                Notification.recipient_actor_type == command.recipient_actor_type,
                Notification.recipient_actor_id == command.recipient_actor_id,
                Notification.status == NOTIFICATION_UNREAD,
            )
            .values(status=NOTIFICATION_READ, read_at=now)
        ),
    )
    uow.flush()
    return int(result.rowcount or 0)


def unread_count(
    session: Session, *, recipient_actor_type: str, recipient_actor_id: uuid.UUID
) -> int:
    """How many the recipient has not read.

    §19 `:1298` asks for "permission-aware counts". This one is scope-aware in the only way this
    table has: a count over somebody else's rows is a disclosure of how much is happening to them.
    """

    total = session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.recipient_actor_type == recipient_actor_type,
            Notification.recipient_actor_id == recipient_actor_id,
            Notification.status == NOTIFICATION_UNREAD,
        )
    )
    return int(total or 0)
