"""Atomic claiming with `FOR UPDATE SKIP LOCKED`, and leases for claimants that die.

Two consumers, one race. The outbox dispatcher and the job runner both need to
take work nobody else is taking, and both get it wrong the same way if written
naively: SELECT a candidate, then UPDATE it. Between those two statements another
worker selects the same row, and the event is delivered twice or the job runs
twice. Under READ COMMITTED neither transaction sees anything wrong.

`FOR UPDATE SKIP LOCKED` makes the selection itself the claim. A row already
locked by another claimant is skipped rather than waited for, so workers scale by
adding processes instead of queueing behind each other.

"Run a single scheduler instance" is a real operational rule and not a substitute
for this. It survives exactly until the first rolling deploy runs two replicas for
thirty seconds, and the failure it produces — one duplicate delivery — is the kind
nobody notices until reconciliation.

**The lease is separate from the status.** A claimant that dies mid-work leaves a
row marked `running` that no living process is working on. Excluding `running`
from the claimable set would strand it forever; including it without a lease would
let two workers run the same job. So a claimed row carries `locked_by` and a
`heartbeat_at` it refreshes, and a row whose heartbeat has gone stale is
claimable again.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.db.models.outbox_event import OutboxEvent
from app.db.models.processing_job import ProcessingJob

# How long a claim survives without a heartbeat before another worker may take
# it. Long enough that an ordinary slow task is not stolen mid-flight, short
# enough that a crashed worker's queue drains without an operator.
DEFAULT_LEASE = timedelta(minutes=5)


def claimable_jobs(
    *, queue_name: str, now: object = None, lease: timedelta = DEFAULT_LEASE
) -> Select[tuple[ProcessingJob]]:
    """Rows this worker may take: due, and not currently leased by anyone alive."""

    moment = now or utc_now()
    lease_deadline = moment - lease  # type: ignore[operator]

    return (
        select(ProcessingJob)
        .where(
            ProcessingJob.queue_name == queue_name,
            ProcessingJob.available_at <= moment,
            or_(
                ProcessingJob.status.in_(("queued", "retry_scheduled")),
                # A running row whose claimant stopped heartbeating. This is the
                # only path by which a crashed worker's job is ever picked up
                # again.
                (ProcessingJob.status == "running")
                & (ProcessingJob.heartbeat_at < lease_deadline),
            ),
        )
        .order_by(ProcessingJob.available_at, ProcessingJob.created_at)
    )


def claim_jobs(
    session: Session,
    *,
    queue_name: str,
    worker_id: str,
    limit: int = 1,
    lease: timedelta = DEFAULT_LEASE,
) -> Sequence[ProcessingJob]:
    """Take up to `limit` jobs, atomically.

    `with_for_update(skip_locked=True)` is what makes the select a claim. The
    statement runs inside the caller's transaction and the rows stay locked until
    it commits, so a second worker executing the identical statement at the same
    instant sees none of them.
    """

    moment = utc_now()
    statement = (
        claimable_jobs(queue_name=queue_name, now=moment, lease=lease)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    claimed = list(session.execute(statement).scalars().all())

    for job in claimed:
        job.status = "running"
        job.locked_by = worker_id
        job.heartbeat_at = moment
        if job.started_at is None:
            job.started_at = moment
        # Counted at claim time, not at completion. A worker that crashes mid-run
        # must still have consumed an attempt, or a poison job is retried forever.
        job.attempt_count += 1

    return claimed


def claim_outbox_events(
    session: Session,
    *,
    worker_id: str,
    limit: int = 20,
    lease: timedelta = DEFAULT_LEASE,
) -> Sequence[OutboxEvent]:
    """The same claim, for the dispatch side.

    Deliberately the same shape rather than a shared generic: the two tables have
    different status vocabularies and different lease columns, and a helper
    abstract enough to cover both would hide which column is the lease — the one
    thing a reader needs to see.
    """

    moment = utc_now()
    lease_deadline = moment - lease

    statement = (
        select(OutboxEvent)
        .where(
            OutboxEvent.available_at <= moment,
            or_(
                OutboxEvent.status.in_(("pending", "failed")),
                (OutboxEvent.status == "processing") & (OutboxEvent.locked_at < lease_deadline),
            ),
        )
        .order_by(OutboxEvent.available_at, OutboxEvent.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    claimed = list(session.execute(statement).scalars().all())

    for event in claimed:
        event.status = "processing"
        event.locked_by = worker_id
        event.locked_at = moment
        event.attempt_count += 1

    return claimed


def release_job(
    job: ProcessingJob,
    *,
    status: str,
    error_code: str | None = None,
    error_message: str | None = None,
    output: dict[str, object] | None = None,
    retry_delay: timedelta | None = None,
) -> None:
    """Finish or reschedule a claimed job, clearing the lease either way.

    Leaving `locked_by` set on a finished row makes the reclaim query treat a
    completed job as a stale claim forever.
    """

    moment = utc_now()
    job.status = status
    job.locked_by = None
    job.heartbeat_at = None
    job.last_error_code = error_code
    job.last_error_message = error_message
    if output is not None:
        job.output_payload = output

    if status in {"succeeded", "cancelled", "dead_lettered", "fallback_to_manual", "failed"}:
        job.finished_at = moment if status != "failed" else None
    if status == "retry_scheduled":
        job.finished_at = None
        job.available_at = moment + (retry_delay or timedelta(seconds=30))


def heartbeat(job: ProcessingJob, worker_id: str) -> None:
    """Refresh the lease. Refused if the row was reclaimed by somebody else.

    A worker that lost its lease and keeps writing would finish a job another
    worker is already running, and the second completion would overwrite the
    first.
    """

    if job.locked_by != worker_id:
        raise RuntimeError(
            f"job {job.id} is held by {job.locked_by!r}, not {worker_id!r}; the lease "
            "was reclaimed and this worker must stop rather than finish it"
        )
    job.heartbeat_at = utc_now()


def new_job(
    *,
    job_type: str,
    queue_name: str,
    input_payload: dict[str, object] | None = None,
    idempotency_key: str | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    max_attempts: int = 5,
) -> ProcessingJob:
    return ProcessingJob(
        job_type=job_type,
        queue_name=queue_name,
        status="queued",
        input_payload=input_payload or {},
        idempotency_key=idempotency_key,
        input_entity_type=entity_type,
        input_entity_id=entity_id,
        max_attempts=max_attempts,
    )
