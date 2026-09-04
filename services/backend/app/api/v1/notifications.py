"""What the system has told you. `05_API_Specification.md:2077`.

M11 slice 1, and the milestone starts here for one reason: **M9 built this table, wrote rows into
it for two milestones, and gave it no way to be read.** M9's own G-5 decided a failed payment
reaches its trader *as a notification rather than as a publication*; that decision has been
unhonoured since it was made, because nothing could fetch one.

**Guarded by recipiency, not by permission.** `permission_catalog.yaml` has no notification
permission — not for a trader and not for an accountant — and inventing one would be a governance
act rather than an implementation. What decides who sees a row is
`notifications.recipient_actor_id`, and `app/notifications/reading.py` takes it as a keyword
argument so a caller cannot build a page request that omits it.

**Both audiences, one router.** `recipient_actor_type` admits `trader_user` and `admin_user`, and
the session says which the caller is. Two routers split by audience would need the caller's type in
the URL, which is the opposite of what M3's login split decided: the audience is a property of the
*session* here, because the row already names its owner.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor
from app.commands import notification_read as notification_commands
from app.core.errors import ErrorEnvelope, ForbiddenError
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.notification import Notification
from app.notifications.reading import NotificationQuery, read_notification_page
from app.security.actor import ActorContext

router = APIRouter(prefix="/notifications", tags=["notifications"])

RESPONSES: dict[int | str, dict[str, object]] = {
    400: {"model": ErrorEnvelope, "description": "The cursor, sort or filter is not allowlisted."},
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "The session carries no actor."},
    404: {
        "model": ErrorEnvelope,
        "description": "No such notification, or it belongs to somebody else. The two are "
        "deliberately indistinguishable.",
    },
    **VALIDATION_ERROR_RESPONSE,
}


class NotificationResponse(BaseModel):
    """One message, as it was sent.

    **No recipient field.** Every row in a response is the caller's own by construction, and a
    recipient id in the body would be a value a client could compare against somebody else's.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    notification_type: str
    title: str
    body: str
    entity_type: str
    entity_id: uuid.UUID
    status: str
    read_at: datetime | None
    created_at: datetime


class NotificationPageResponse(BaseModel):
    """A page, its cursor, and the count §19 `:1298` asks to be permission-aware.

    `unread_count` is over the caller's own rows only. A count is a disclosure: how much is
    happening to a business is information about that business.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[NotificationResponse]
    next_cursor: str | None
    unread_count: int


class MarkAllReadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marked: int
    unread_count: int


def _rendered(notification: Notification) -> NotificationResponse:
    return NotificationResponse(
        id=notification.id,
        notification_type=notification.notification_type,
        title=notification.title,
        body=notification.body,
        entity_type=notification.entity_type,
        entity_id=notification.entity_id,
        status=notification.status,
        read_at=notification.read_at,
        created_at=notification.created_at,
    )


def _recipient(actor: ActorContext) -> tuple[str, uuid.UUID]:
    """Who the caller is, as the table spells it.

    `ForbiddenError` when the session carries no actor id: the two system actor types
    (`system_worker`, `system_maintenance`) have none by design, and a notification addressed to
    nobody is not something to return an empty list for — it is a request that should not have
    been made.
    """

    if actor.actor_id is None:
        raise ForbiddenError()
    return actor.actor_type.value, actor.actor_id


@router.get(
    "",
    response_model=NotificationPageResponse,
    operation_id="listNotifications",
    summary="Your own notifications, newest first.",
    responses=RESPONSES,
)
def list_notifications(
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    status: Annotated[str | None, Query()] = None,
    notification_type: Annotated[str | None, Query()] = None,
    entity_type: Annotated[str | None, Query()] = None,
    sort: Annotated[str | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    cursor: Annotated[str | None, Query()] = None,
) -> NotificationPageResponse:
    """`GET /api/v1/notifications`, per `:2079`.

    §19 `:1298`'s rules come from `app/db/pagination.py`, which has expressed them since M9's audit
    read: a cursor, a total order, an allowlisted sort and an allowlisted filter. An unknown sort
    or filter is **refused**, not ignored — ignoring one returns a different page than the caller
    asked for and says nothing about it.
    """

    recipient_type, recipient_id = _recipient(actor)

    with runtime.uow_factory() as uow:
        page = read_notification_page(
            uow.session,
            recipient_actor_type=recipient_type,
            recipient_actor_id=recipient_id,
            query=NotificationQuery(
                status=status,
                notification_type=notification_type,
                entity_type=entity_type,
            ),
            sort=sort,
            limit=limit,
            cursor=cursor,
        )
        response = NotificationPageResponse(
            items=[_rendered(row) for row in page.rows],
            next_cursor=page.next_cursor,
            unread_count=notification_commands.unread_count(
                uow.session,
                recipient_actor_type=recipient_type,
                recipient_actor_id=recipient_id,
            ),
        )
        uow.rollback()

    return response


@router.post(
    "/{notification_id}/mark-read",
    response_model=NotificationResponse,
    operation_id="markNotificationRead",
    summary="Mark one of your notifications read.",
    responses=RESPONSES,
)
def mark_notification_read(
    notification_id: uuid.UUID,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> NotificationResponse:
    """`POST /api/v1/notifications/{notification_id}/mark-read`, per `:2080`.

    **No `If-Match` and no `Idempotency-Key`.** `command_catalog.yaml` carries no row for this —
    its scope is "critical financial, evidence, publication, and dispatch mutations" — and reading
    a message is none of those. The command is idempotent by construction: a second call returns
    the row unchanged rather than moving `read_at`, because when somebody first read it is the fact
    worth keeping.
    """

    recipient_type, recipient_id = _recipient(actor)

    with runtime.uow_factory() as uow:
        notification = notification_commands.mark_read(
            notification_commands.MarkNotificationRead(
                notification_id=notification_id,
                recipient_actor_type=recipient_type,
                recipient_actor_id=recipient_id,
            ),
            uow=uow,
            now=utc_now(),
        )
        response = _rendered(notification)
        uow.commit()

    return response


@router.post(
    "/mark-all-read",
    response_model=MarkAllReadResponse,
    operation_id="markAllNotificationsRead",
    summary="Mark every unread notification of yours read.",
    responses=RESPONSES,
)
def mark_all_notifications_read(
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> MarkAllReadResponse:
    """`POST /api/v1/notifications/mark-all-read`, per `:2081`.

    Returns how many moved, which is the only way a client can tell "nothing was unread" from
    "the request did not reach the right rows".
    """

    recipient_type, recipient_id = _recipient(actor)

    with runtime.uow_factory() as uow:
        marked = notification_commands.mark_all_read(
            notification_commands.MarkAllNotificationsRead(
                recipient_actor_type=recipient_type,
                recipient_actor_id=recipient_id,
            ),
            uow=uow,
            now=utc_now(),
        )
        remaining = notification_commands.unread_count(
            uow.session,
            recipient_actor_type=recipient_type,
            recipient_actor_id=recipient_id,
        )
        uow.commit()

    return MarkAllReadResponse(marked=marked, unread_count=remaining)
