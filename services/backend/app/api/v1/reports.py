"""Reports. `15_Agent_Implementation_Plan.md:1331`.

M11 slice 7. One report, and it is the one whose content needed no judgement — see
`app/reports/queue_summary.py` for why that mattered.

**`report.read` had no route until now.** The permission has been in the catalogue since M0,
granted to four roles, and nothing declared it. This is its first caller.

**There is no export route, deliberately.** `permission_catalog.yaml:700` gives `report.export`
`default_roles: []`: no role holds it, pending an explicit grant. A route behind it would refuse
every caller — the `bank_profile.activate_version` shape this project already carries once — and
guarding an export by a different permission would invent an authority the catalogue withholds on
purpose.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor, requires
from app.core.errors import ErrorEnvelope
from app.core.runtime import RuntimeServices
from app.reports.queue_summary import summarise_queues
from app.security.actor import ActorContext

router = APIRouter(prefix="/reports", tags=["reports"])


class QueueCountResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queue: str
    waiting: int


class QueueSummaryResponse(BaseModel):
    """What is waiting for the caller, per queue and in total.

    **A queue the caller may not read is absent rather than zero.** A zero would say "this queue
    exists and is empty", which is information about a part of the business that is not theirs.
    """

    model_config = ConfigDict(extra="forbid")

    counts: list[QueueCountResponse]
    total: int


@router.get(
    "/queue-summary",
    response_model=QueueSummaryResponse,
    operation_id="getQueueSummaryReport",
    summary="How much work is waiting in each queue the caller may read.",
    dependencies=[requires("report.read")],
    responses={
        401: {"model": ErrorEnvelope, "description": "No valid session."},
        403: {"model": ErrorEnvelope, "description": "The session does not hold `report.read`."},
        **VALIDATION_ERROR_RESPONSE,
    },
)
def queue_summary(
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> QueueSummaryResponse:
    """`GET /api/v1/reports/queue-summary`.

    **Two permissions are consulted, and that is the design rather than an oversight.**
    `report.read` decides whether a person may ask this question at all; each queue's own grant
    decides whether they may be told about that queue. Someone holding `report.read` and nothing
    else receives an empty summary and a total of zero — which is true, and is the correct answer
    for a person with no queues.
    """

    with runtime.uow_factory() as uow:
        summary = summarise_queues(uow.session, actor=actor)
        response = QueueSummaryResponse(
            counts=[
                QueueCountResponse(queue=count.queue, waiting=count.waiting)
                for count in summary.counts
            ],
            total=summary.total,
        )
        uow.rollback()

    return response
