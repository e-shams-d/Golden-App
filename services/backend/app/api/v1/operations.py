"""Background-processing state for operators, on a path of its own.

Deliberately **not** an addition to `ReadinessResponse.checks`. That would change
an existing response schema and trip the oasdiff breaking-change gate, whose
waiver process is still an unresolved `TODO(governance)` in the workflow — so the
choice is between a new path and a governance decision this work does not need to
force. It is also the wrong shape: readiness answers "should this instance
receive traffic", and an outbox backlog does not mean it should not. Wiring lag
into readiness would take a healthy instance out of rotation for a condition
adding instances cannot fix.

Restricted by the same operations token as the health detail paths. Queue depth,
dead-letter counts and failure ages describe internal state precisely enough to
be worth withholding from an anonymous caller.

Ages, not just counts. Ten thousand events published seconds ago is healthy; one
event stuck for six hours is not, and a count cannot tell those apart.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime, require_operations_access
from app.core.errors import ErrorEnvelope
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.claiming import DEFAULT_LEASE
from app.db.models.processing_job import ProcessingJob
from app.workers.dispatcher import outbox_lag

router = APIRouter(prefix="/operations", tags=["operations"])


class OutboxHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pending: int = Field(description="Events awaiting or retrying delivery.")
    dead_lettered: int = Field(description="Events that exhausted delivery attempts.")
    oldest_pending_age_seconds: float | None = Field(
        default=None,
        description="Age of the oldest undelivered event. Null when none are pending.",
    )


class JobHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queued: int
    running: int
    retry_scheduled: int
    dead_lettered: int
    fallback_to_manual: int = Field(
        description="Jobs whose handler is not retry-safe and which need a human decision."
    )
    stale_leases: int = Field(
        description="Running jobs whose claimant stopped heartbeating. A rising number "
        "means workers are dying rather than that jobs are slow."
    )
    oldest_queued_age_seconds: float | None = None


class BackgroundProcessingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outbox: OutboxHealth
    jobs: JobHealth
    needs_attention: bool = Field(
        description="True when anything here requires an operator: a dead letter, a "
        "job awaiting manual handling, or a stale lease."
    )


def _job_health(runtime: RuntimeServices) -> JobHealth:
    lease_deadline = utc_now() - DEFAULT_LEASE

    with runtime.uow_factory() as uow:
        counts: dict[str, int] = {
            str(status): int(count)
            for status, count in uow.session.execute(
                select(ProcessingJob.status, func.count()).group_by(ProcessingJob.status)
            ).all()
        }
        stale = uow.session.execute(
            select(func.count())
            .select_from(ProcessingJob)
            .where(
                ProcessingJob.status == "running",
                ProcessingJob.heartbeat_at < lease_deadline,
            )
        ).scalar_one()
        oldest = uow.session.execute(
            select(func.min(ProcessingJob.created_at)).where(
                ProcessingJob.status.in_(("queued", "retry_scheduled"))
            )
        ).scalar_one()
        # A read path never mutates domain state, and rolling back rather than
        # committing says so in the code as well as in the query.
        uow.rollback()

    return JobHealth(
        queued=int(counts.get("queued", 0)),
        running=int(counts.get("running", 0)),
        retry_scheduled=int(counts.get("retry_scheduled", 0)),
        dead_lettered=int(counts.get("dead_lettered", 0)),
        fallback_to_manual=int(counts.get("fallback_to_manual", 0)),
        stale_leases=int(stale),
        oldest_queued_age_seconds=(
            (utc_now() - oldest).total_seconds() if oldest is not None else None
        ),
    )


@router.get(
    "/background-processing",
    response_model=BackgroundProcessingResponse,
    operation_id="getBackgroundProcessingHealth",
    summary="Outbox lag, dead letters and job queue state",
    dependencies=[Depends(require_operations_access)],
    responses={
        403: {"model": ErrorEnvelope, "description": "The operations token is invalid."},
        **VALIDATION_ERROR_RESPONSE,
    },
)
def background_processing_health(
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> BackgroundProcessingResponse:
    outbox = outbox_lag(runtime.uow_factory)
    jobs = _job_health(runtime)

    return BackgroundProcessingResponse(
        outbox=OutboxHealth(
            pending=outbox.pending,
            dead_lettered=outbox.dead_lettered,
            oldest_pending_age_seconds=outbox.oldest_pending_age_seconds,
        ),
        jobs=jobs,
        # Anything here means somebody has to look. Backlog alone does not:
        # a queue draining normally is not a fault.
        needs_attention=bool(
            outbox.dead_lettered or jobs.dead_lettered or jobs.fallback_to_manual
            or jobs.stale_leases
        ),
    )
