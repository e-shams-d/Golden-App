"""The work waiting for a person. `15_Agent_Implementation_Plan.md:1256`.

M11 slice 2, and the first route in this project whose *shape* is the deliverable. §19.2 names
twenty-four queues and document 05 defines a route for none of them, so this file is the plan's
**G-1** answered in code: one path per queue, under `/queues/`, named for the queue the document
names.

**One route is registered, not twenty-four**, and that is the point rather than a shortfall. The
contract is decided by a queue that works and is asserted against a real database; slices 3, 4 and
5 add the rest against a shape somebody has already tried. Reversing this decision costs one slice.

**Each queue declares its own permission and the route reads it from the registry**, so a queue
cannot be added without one. `requires(...)` is called with `definition.permission`, which
`declare()` refuses unless `permission_catalog.yaml` holds it — the same fail-closed path that
caught `gold_sale.dispatch_override` in M10.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor, requires
from app.core.errors import ErrorEnvelope
from app.core.runtime import RuntimeServices
from app.db.models.payment_request import PaymentRequest
from app.queues.contract import read_queue_page
from app.queues.payment_requests import NEW_REQUESTS
from app.security.actor import ActorContext

router = APIRouter(prefix="/queues", tags=["queues"])

RESPONSES: dict[int | str, dict[str, object]] = {
    400: {
        "model": ErrorEnvelope,
        "description": "The cursor, sort, filter or limit is not allowlisted. Refused rather "
        "than ignored.",
    },
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "The session does not hold the queue's grant."},
    **VALIDATION_ERROR_RESPONSE,
}


class QueueRequestItem(BaseModel):
    """One row of the new-requests queue.

    **Deliberately narrower than `PaymentRequestResponse`.** A queue row exists to be triaged, not
    read in full: it answers who, when and how much, and the detail route answers the rest. Sending
    the whole aggregate would make every queue a second read surface that has to be kept in step
    with the first — and §19 `:1298`'s last rule says a queue is where over-disclosure happens.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    request_number: str
    trader_id: uuid.UUID
    status: str
    created_at: datetime


class QueuePageResponse(BaseModel):
    """The envelope every queue returns. Named once so twenty-four routes cannot drift.

    `total` is §19 `:1298`'s "permission-aware count": how much work is waiting behind the cursor,
    computed from the same statement the rows came from.
    """

    model_config = ConfigDict(extra="forbid")

    queue: str
    items: list[QueueRequestItem]
    next_cursor: str | None
    total: int


@router.get(
    "/new-requests",
    response_model=QueuePageResponse,
    operation_id="listNewRequestsQueue",
    summary="Requests submitted to the centre that nobody has started reviewing.",
    dependencies=[requires(NEW_REQUESTS.permission)],
    responses=RESPONSES,
)
def list_new_requests(
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    trader_id: Annotated[uuid.UUID | None, Query()] = None,
    sort: Annotated[str | None, Query()] = None,
    limit: Annotated[int | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
) -> QueuePageResponse:
    """`GET /api/v1/queues/new-requests`, per §19 `:1262`.

    **Oldest first.** `descending=False`, which is the opposite of every other list in this project
    and the one place the difference matters: an audit log is read from the top because the newest
    entry is the interesting one, and a work queue is drained from the bottom because the oldest
    item is the one somebody has been waiting on. A newest-first queue quietly starves its tail.

    `limit` carries no `ge`/`le` here on purpose. `normalise_limit` refuses an out-of-range value
    with a 400 that says what the bounds are, and duplicating them in the signature would let
    FastAPI answer 422 first — a different status and a different message for the same mistake,
    decided by which validator happened to run.
    """

    with runtime.uow_factory() as uow:
        page = read_queue_page(
            uow.session,
            NEW_REQUESTS,
            select(PaymentRequest),
            actor=actor,
            filters={"trader_id": trader_id} if trader_id is not None else None,
            sort=sort,
            descending=False,
            limit=limit,
            cursor=cursor,
        )
        response = QueuePageResponse(
            queue=NEW_REQUESTS.name,
            items=[
                QueueRequestItem(
                    id=row.id,
                    request_number=row.request_number,
                    trader_id=row.trader_id,
                    status=row.status,
                    created_at=row.created_at,
                )
                for row in page.rows
            ],
            next_cursor=page.next_cursor,
            total=page.total,
        )
        uow.rollback()

    return response
