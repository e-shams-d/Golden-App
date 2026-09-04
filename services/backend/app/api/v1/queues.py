"""The work waiting for a person. `15_Agent_Implementation_Plan.md:1256`.

M11 slice 2 decided the shape; slice 3 built the accountant's eleven against it.

**G-1, answered:** one path per queue, under `/queues/`, named for the queue §19.2 names. The
`?queue=` alternative makes the set of queues a runtime value, and §19 `:1298` asks for allowlisted
filters — a queue reached by a path is enumerated by the route table and refused by
`test_m3_definition_of_done.py` until somebody classifies it.

**The routes are generated from the registry, one per entry.** Slice 2 wrote its single route by
hand; eleven copies of that function would differ only in a permission, an entity and a renderer,
and eleven hand-written copies of one envelope is exactly how twenty-four queues drift apart. So
the body is written once here and `QueueDefinition` carries the three things that vary. Two
properties come free: every queue in `BUILT` has a route, and no route exists for a queue that is
not in `BUILT`.

**Each queue declares its own permission and the loop reads it from the definition**, so a queue
cannot be added without one. `declare()` refuses a name `permission_catalog.yaml` does not hold, so
a queue guarded by an invented permission fails at import rather than at the first request.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor, requires
from app.core.errors import ErrorEnvelope
from app.core.runtime import RuntimeServices
from app.queues.contract import QueueDefinition, read_queue_page
from app.queues.registry import BUILT
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


class QueueRowResponse(BaseModel):
    """One row of any queue. The same five fields for all of them.

    **Deliberately narrower than any aggregate's own response.** A queue row exists to be triaged:
    what it is, whose it is, what state it is in, how long it has waited. The detail route answers
    the rest. One shape for twenty-four queues is also what makes §19 `:1298`'s last rule
    checkable — a single assertion on the key set covers every queue, where per-queue shapes would
    need twenty-four.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    reference: str
    status: str
    created_at: datetime
    trader_id: uuid.UUID | None


class RequestQueueRowResponse(QueueRowResponse):
    """`new-requests` only, and it exists to keep a published contract from breaking.

    Slice 2 shipped this queue with `request_number` (required) and a **non-nullable** `trader_id`.
    Slice 3's unified row renames the first to `reference` and makes the second nullable, because
    six of the eleven queues are about no particular business. `oasdiff breaking --fail-on ERR` —
    CI gate 3 — reports both as errors: `response-required-property-removed` and
    `response-property-list-of-types-widened`.

    The endpoint is one day old and nothing consumes it, so the break would cost nothing in
    practice. It is avoided anyway, because the alternative was to add an ignore rule to the gate,
    and weakening a governance check to fit a change is the move this project refuses everywhere
    else. `.github/workflows/m1-verify.yml:181` carries a `TODO(governance)` for exactly this — a
    waiver needs a contract-version bump and recorded approval, and neither exists.

    So the compatibility fields are *added* rather than the new ones withheld: adding a property to
    a response is not a breaking change. `request_number` duplicates `reference`, and `trader_id`
    is redeclared non-null, which is true for this queue and only this queue.

    **Recorded as the plan's G-8**: when the waiver mechanism exists, this class is deleted and
    `new-requests` joins the others. Until then it is one queue carrying two names for one value.
    """

    model_config = ConfigDict(extra="forbid")

    request_number: str
    trader_id: uuid.UUID


class QueuePageResponse(BaseModel):
    """The envelope every queue returns.

    `total` is §19 `:1298`'s "permission-aware count": how much work is waiting behind the cursor,
    computed from the same statement the rows came from.
    """

    model_config = ConfigDict(extra="forbid")

    queue: str
    items: list[QueueRowResponse]
    next_cursor: str | None
    total: int


class RequestQueuePageResponse(BaseModel):
    """The same envelope carrying the compatibility row. See `RequestQueueRowResponse`.

    Declared alongside `QueuePageResponse` rather than inheriting from it: `list` is invariant, so
    narrowing `items` in a subclass is not a subtype and mypy refuses it. Two flat models say the
    same thing without asking the type system to accept something untrue.
    """

    model_config = ConfigDict(extra="forbid")

    queue: str
    items: list[RequestQueueRowResponse]
    next_cursor: str | None
    total: int


# The one queue whose response shape was published before the shape was unified.
COMPATIBILITY_QUEUE = "new-requests"


def _operation_id(name: str) -> str:
    """`new-requests` becomes `listNewRequestsQueue`.

    Derived rather than declared, so a queue's path and operation id cannot disagree.
    `test_openapi_contract.py` still lists every id by hand, which is what keeps a new queue from
    entering the published contract without somebody writing it down.
    """

    return "list" + "".join(part.capitalize() for part in name.split("-")) + "Queue"


def _register(definition: QueueDefinition[Any]) -> None:
    """One route for one queue. The body of every queue endpoint lives here, once."""

    compatibility = definition.name == COMPATIBILITY_QUEUE
    page_model = RequestQueuePageResponse if compatibility else QueuePageResponse

    @router.get(
        f"/{definition.name}",
        response_model=page_model,
        operation_id=_operation_id(definition.name),
        summary=f"Section 19.2's {definition.name.replace('-', ' ')} queue.",
        dependencies=[requires(definition.permission)],
        responses=RESPONSES,
        name=f"queue_{definition.name.replace('-', '_')}",
    )
    def endpoint(
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        runtime: Annotated[RuntimeServices, Depends(get_runtime)],
        trader_id: Annotated[uuid.UUID | None, Query()] = None,
        task_type: Annotated[str | None, Query()] = None,
        sort: Annotated[str | None, Query()] = None,
        limit: Annotated[int | None, Query()] = None,
        cursor: Annotated[str | None, Query()] = None,
    ) -> Any:
        """**Oldest first.** `descending=False`, and this is the one place it is correct.

        An audit log is read from the top because the newest entry is the interesting one; a work
        queue is drained from the bottom because the oldest item is the one somebody has been
        waiting on. A newest-first queue quietly starves its tail.

        `limit` carries no `ge`/`le`: `normalise_limit` refuses an out-of-range value with a 400
        that says what the bounds are, and duplicating the bounds here would let FastAPI answer 422
        first — a different status for the same mistake, decided by which validator ran.

        The two filter parameters are declared for every queue and **allowlisted per queue**. A
        queue whose spec does not hold `task_type` refuses it rather than ignoring it, which is
        `read_queue_page`'s job.
        """

        requested = {"trader_id": trader_id, "task_type": task_type}
        filters = {name: value for name, value in requested.items() if value is not None}

        render = definition.render
        if render is None:  # pragma: no cover - refused at registration below
            raise RuntimeError(f"queue {definition.name!r} has no renderer")

        with runtime.uow_factory() as uow:
            page = read_queue_page(
                uow.session,
                definition,
                select(definition.entity),
                actor=actor,
                filters=filters or None,
                sort=sort,
                descending=False,
                limit=limit,
                cursor=cursor,
            )
            # `asdict`, not `vars`: `QueueRow` is `slots=True`, so it has no `__dict__` and
            # `vars()` raises.
            rendered = [asdict(render(row)) for row in page.rows]
            if compatibility:
                # `request_number` duplicates `reference` and `trader_id` is known non-null on
                # this queue. Both are here only so the shape slice 2 published still validates.
                response: BaseModel = RequestQueuePageResponse(
                    queue=definition.name,
                    items=[
                        RequestQueueRowResponse(**fields, request_number=fields["reference"])
                        for fields in rendered
                    ],
                    next_cursor=page.next_cursor,
                    total=page.total,
                )
            else:
                response = QueuePageResponse(
                    queue=definition.name,
                    items=[QueueRowResponse(**fields) for fields in rendered],
                    next_cursor=page.next_cursor,
                    total=page.total,
                )
            uow.rollback()

        return response


for _definition in BUILT.values():
    if _definition.entity is None or _definition.render is None:
        raise RuntimeError(
            f"queue {_definition.name!r} is in BUILT without an entity or a renderer, so no route "
            "can be generated for it. A registered queue with no route is a queue that looks built."
        )
    _register(_definition)
