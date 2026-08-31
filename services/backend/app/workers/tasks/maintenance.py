"""Scheduler-driven maintenance: outbox dispatch and stale-lease recovery.

Two sweeps, and both are recovery rather than routine. The outbox poll exists
because a dispatch registered after commit can still be lost — the process can
die between the commit and the hook — so the table is the source of truth and the
poll is what eventually notices. Lease recovery exists because a worker that dies
mid-job leaves a row nobody is working on.

**Deliberately not here: any expiry cleanup or purge.** `idempotency_records`
carries `expires_at` with an index and nothing acts on it, and nothing here
deletes an outbox event, a dead-lettered job or an audit row. Every deletion path
is blocked by the open ADR-005, and a sweep that quietly removed rows would be
the hardest kind of change to notice after the fact.
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta

from sqlalchemy import func, select

from app.core.logging import get_logger, log_event
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.claiming import DEFAULT_LEASE
from app.db.models.processing_job import ProcessingJob
from app.workers.dispatcher import DispatchReport, dispatch_once

logger = get_logger("workers.maintenance")


def poll_outbox_task() -> dict[str, int]:
    """The beat entry point. Named separately from `poll_outbox` on purpose.

    Celery resolves a scheduled task by its dotted name, so the schedule and the
    function are coupled by a string. Keeping the task a thin wrapper means the
    logic can be called directly from a test without a broker, and the wrapper is
    the only thing that needs the process runtime.

    **Delivery stopped being a no-op in M9 slice 7.** This docstring used to say "nothing consumes
    these events in Phase 1A, and a dispatcher that invented a destination would publish somewhere
    no consumer agreed to" — which was correct, and which `notifications`
    (`04_Database_Schema.md` §13.3) ends. The destination is one document 04 specifies rather than
    one a dispatcher guessed, and the plan's G-2 assigned it to this slice.

    The projection reads three of the eleven event types and ignores the rest, which is not a gap:
    a notification is for a person, and most of these events are about work the centre does to
    itself.
    """

    from app.notifications.projection import notification_deliverer
    from app.workers.runtime import worker_runtime

    runtime = worker_runtime()
    report = poll_outbox(runtime, notification_deliverer(runtime.uow_factory))
    return {
        "published": report.published,
        "failed": report.failed,
        "dead_lettered": report.dead_lettered,
    }


def recover_stale_leases_task() -> int:
    """The beat entry point for the lease sweep."""

    from app.workers.runtime import worker_runtime

    return recover_stale_leases(worker_runtime())


def worker_identity() -> str:
    """Who holds a claim, as it appears in the row and in pg_stat_activity."""

    return f"{os.uname().nodename}:{os.getpid()}"


def poll_outbox(
    runtime: RuntimeServices,
    deliver: object,
    *,
    limit: int = 20,
) -> DispatchReport:
    """One dispatch pass. Scheduling the interval belongs to the scheduler.

    A module that started its own loop on import would run one in every process
    that imported it, including the API.
    """

    assert callable(deliver)
    report = dispatch_once(
        runtime.uow_factory, deliver, worker_id=worker_identity(), limit=limit
    )
    if report.dead_lettered or report.failed:
        log_event(
            logger,
            logging.WARNING,
            "outbox_dispatch_incomplete",
            published=report.published,
            failed=report.failed,
            dead_lettered=report.dead_lettered,
        )
    return report


def recover_stale_leases(
    runtime: RuntimeServices, *, lease: timedelta = DEFAULT_LEASE
) -> int:
    """Count jobs whose claimant stopped heartbeating. Reports, does not reset.

    The claim query already treats a stale lease as claimable, so a worker picks
    these up on its next poll. Resetting them here would race that: two writers
    deciding the same row is free, which is the problem the lease exists to
    prevent.

    Returned as a number because it is an operational signal — a count that keeps
    climbing means workers are dying, not that jobs are slow.
    """

    deadline = utc_now() - lease
    with runtime.uow_factory() as uow:
        stale = uow.session.execute(
            select(func.count())
            .select_from(ProcessingJob)
            .where(
                ProcessingJob.status == "running",
                ProcessingJob.heartbeat_at < deadline,
            )
        ).scalar_one()
        uow.rollback()

    if stale:
        log_event(logger, logging.WARNING, "stale_job_leases_detected", count=stale)
    return int(stale)
