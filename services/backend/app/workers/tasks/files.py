"""Tasks routed to the `files` queue.

The module was created empty in M2 so that the first task added here would route correctly instead
of being discovered on the wrong queue later: `app/workers/celery_app.py` routes on the dotted path
`app.workers.tasks.files.*`, and a task defined elsewhere matches no glob and lands silently on
`task_default_queue`, which is `maintenance`. M8 slice 4 is the first task, and it routes.

**Rendering a crop is the first work in this system that is genuinely asynchronous**, and the
reason is worth stating: a page render is CPU-bound and unbounded in time, so doing it inside the
request would hold a web worker for as long as PDFium takes on a large scan. §16.4's fifth
requirement — "process asynchronously when appropriate" — is that.

**A failed render must leave no evidence.** The whole point of the lifecycle in
`08_Bank_File_and_Result_Processing.md:1031` is that the segment row exists first with
`segment_file_id` NULL, so a crash between claim and commit leaves a request nobody mistakes for a
receipt. That is why this task rolls the transaction back on failure and records the error on the
*job* rather than on the segment: the segment's honest state is "asked for, not produced".

**Retries are bounded by `max_attempts`, and exhaustion is not silence.** A crop that can never be
rendered becomes a manual review task, because the alternative — a job quietly dead-lettered and a
segment forever without a file — is the shape this milestone exists to prevent. Slice 3 built the
queue; this is its second caller.

**M10 slice 4 added a second task to this module**, and the two share one queue. Each hands back
what it does not recognise rather than failing it — see `_render_one` — because a worker that
failed an unfamiliar job type would exhaust another task's attempts without ever trying it.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.commands.bank_statement import IMPORT_JOB_TYPE
from app.commands.manual_review_task import OpenTask, open_task
from app.commands.receipt_crop import CROP_JOB_TYPE, render_pending_crop
from app.commands.statement_rows import parse_pending_run
from app.core.logging import get_logger, log_event
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.claiming import claim_jobs, release_job
from app.db.models.manual_review_task import ENTITY_RECEIPT_SEGMENT, TASK_TYPE_UNRESOLVED_SEGMENT
from app.workers.tasks.maintenance import worker_identity

QUEUE_NAME = "files"

logger = get_logger("workers.files")

# `system_worker`, not `system_maintenance`. `app/audit/writer.py:28` recognises both and derives a
# stable id for each, and the distinction is worth keeping: this row was written by a worker doing
# the job it was asked to do, not by a sweep.
RENDER_ACTOR = AuditActor(actor_type="system_worker")
RENDER_REDACTION = RedactionPolicy(mask_iban=True)


@dataclass(frozen=True, slots=True)
class RenderReport:
    """What one pass did. Counted rather than logged only, so a test can assert it."""

    rendered: int
    failed: int
    escalated: int


def render_crops_task() -> dict[str, int]:
    """The Celery entry point. A thin wrapper, on `maintenance.py`'s precedent.

    Celery resolves a task by its dotted name, so the schedule and the function are coupled by a
    string. Keeping the wrapper thin means the logic below can be called directly from a test
    without a broker.
    """

    from app.workers.runtime import worker_runtime

    report = render_crops(worker_runtime())
    return {
        "rendered": report.rendered,
        "failed": report.failed,
        "escalated": report.escalated,
    }


def render_crops(runtime: RuntimeServices, *, limit: int = 1) -> RenderReport:
    """Claim up to `limit` crop jobs and render each in its own transaction.

    **One transaction per job, not one per pass.** A pass that rendered three crops in one
    transaction would lose two finished crops because the third failed — and a crop is evidence
    somebody is waiting to look at.

    **The claim and the render share a transaction.** `claim_jobs` holds the row locked until
    commit, so a second worker running this identical function at the same instant sees none of the
    rows this one took. Committing the claim separately would open the window the lock exists to
    close.
    """

    rendered = 0
    failed = 0
    escalated = 0
    worker_id = worker_identity()

    for _ in range(limit):
        pass_report = _render_one(runtime, worker_id)
        if pass_report is None:
            break
        rendered += pass_report.rendered
        failed += pass_report.failed
        escalated += pass_report.escalated

    return RenderReport(rendered=rendered, failed=failed, escalated=escalated)


def _render_one(runtime: RuntimeServices, worker_id: str) -> RenderReport | None:
    """One job, one transaction. `None` when the queue had nothing due."""

    with runtime.uow_factory() as uow:
        claimed = claim_jobs(
            uow.session, queue_name=QUEUE_NAME, worker_id=worker_id, limit=1
        )
        jobs = [job for job in claimed if job.job_type == CROP_JOB_TYPE]
        if not claimed:
            uow.rollback()
            return None
        if not jobs:
            # Claimed something this task does not know how to run. Released back rather than
            # failed: another task type on this queue is a future slice's job, not an error, and
            # marking it failed would consume its attempts on a worker that never tried.
            #
            # **M10 slice 4 is what made that sentence load-bearing.** `parse_statements` below
            # handles `bank_statement.parse_import_run` on this same queue, and the two hand each
            # other's jobs back rather than failing them. A worker that failed what it did not
            # recognise would exhaust a parse's attempts in three claims and dead-letter a run
            # nothing had attempted.
            for job in claimed:
                release_job(job, status="retry_scheduled")
            uow.commit()
            return RenderReport(rendered=0, failed=0, escalated=0)

        job = jobs[0]
        segment_id = uuid.UUID(str(job.input_payload["receipt_segment_id"]))

        try:
            derived_file_id = render_pending_crop(
                segment_id,
                uow=uow,
                storage=runtime.storage,
                now=utc_now(),
                job_id=job.id,
            )
        except Exception as error:
            # **Broad on purpose.** A render can fail in ways this module cannot enumerate: a
            # malformed PDF, a storage read, a native crash surfaced as an exception. What matters
            # is that every one of them leaves the segment without a file rather than leaving the
            # job claimed forever — and a narrower clause would let an unlisted failure escape,
            # abandon the lease, and require the stale-lease sweep to notice.
            uow.rollback()
            return _record_failure(runtime, job.id, segment_id, error, worker_id)

        release_job(
            job,
            status="succeeded",
            output={"derived_file_id": str(derived_file_id)},
        )
        uow.commit()
        log_event(
            logger,
            logging.INFO,
            "receipt_crop_rendered",
            receipt_segment_id=str(segment_id),
            processing_job_id=str(job.id),
        )
        return RenderReport(rendered=1, failed=0, escalated=0)


def _record_failure(
    runtime: RuntimeServices,
    job_id: uuid.UUID,
    segment_id: uuid.UUID,
    error: Exception,
    worker_id: str,
) -> RenderReport:
    """Record the failure on the job, in a transaction of its own.

    **A separate transaction because the first one was rolled back.** Writing the error into the
    session that just failed would either be discarded with the rollback or, worse, commit
    alongside a partially-written derivation — and a `file_derivations` row for a file that was
    never finished is exactly the orphan M4's atomicity rule forbids.
    """

    with runtime.uow_factory() as uow:
        from app.db.models.processing_job import ProcessingJob

        job = uow.session.get(ProcessingJob, job_id)
        if job is None:
            uow.rollback()
            return RenderReport(rendered=0, failed=1, escalated=0)

        exhausted = job.attempt_count >= job.max_attempts
        release_job(
            job,
            status="dead_lettered" if exhausted else "retry_scheduled",
            error_code=type(error).__name__,
            # The message, not the traceback. A traceback in a column is read by nobody and can
            # carry a storage key, which is the boundary `app/files/download.py` protects.
            error_message=str(error)[:500],
        )

        escalated = 0
        if exhausted:
            # Slice 3's queue, second caller. A crop that has exhausted its attempts is work for a
            # person: the operator drew a rectangle and is owed either a picture or a reason.
            open_task(
                OpenTask(
                    task_type=TASK_TYPE_UNRESOLVED_SEGMENT,
                    entity_type=ENTITY_RECEIPT_SEGMENT,
                    entity_id=segment_id,
                    title="A crop could not be rendered",
                    description=(
                        f"the render failed {job.attempt_count} times, most recently with "
                        f"{type(error).__name__}; the operator's rectangle is stored and has no "
                        "image"
                    ),
                    priority=5,
                ),
                session=uow.session,
                policy=RENDER_REDACTION,
                actor=RENDER_ACTOR,
                context=AuditContext(causation_id=str(job_id)),
                now=utc_now(),
            )
            escalated = 1

        uow.commit()

    log_event(
        logger,
        logging.WARNING if escalated else logging.INFO,
        "receipt_crop_render_failed",
        receipt_segment_id=str(segment_id),
        processing_job_id=str(job_id),
        error_code=type(error).__name__,
        escalated=bool(escalated),
        worker_id=worker_id,
    )
    return RenderReport(rendered=0, failed=1, escalated=escalated)


# --- M10 slice 4: parsing a bank statement -----------------------------------
#
# The second task on this queue, and the one that closes what slice 3 opened. Slice 3 created the
# import run and enqueued `bank_statement.parse_import_run`; nothing handled that job type, which
# is the mechanism-with-no-caller shape this repository has shipped five times. Building the
# handler one slice later rather than in the same one was deliberate — rows had nowhere to go
# until `20260907_0038` — and this is the slice at which that stops being true.
#
# A parse belongs on a queue for the same reason a crop does: it opens an uploaded file and reads
# it end to end, and a statement is thousands of rows.


@dataclass(frozen=True, slots=True)
class StatementParseReport:
    parsed: int
    failed: int


def parse_statements_task() -> dict[str, int]:
    """The Celery entry point. Thin, on `render_crops_task`'s precedent."""

    from app.workers.runtime import worker_runtime

    report = parse_statements(worker_runtime())
    return {"parsed": report.parsed, "failed": report.failed}


def parse_statements(runtime: RuntimeServices, *, limit: int = 1) -> StatementParseReport:
    """Claim up to `limit` parse jobs and run each in its own transaction."""

    parsed = 0
    failed = 0
    worker_id = worker_identity()

    for _ in range(limit):
        outcome = _parse_one(runtime, worker_id)
        if outcome is None:
            break
        parsed += outcome.parsed
        failed += outcome.failed

    return StatementParseReport(parsed=parsed, failed=failed)


def _parse_one(runtime: RuntimeServices, worker_id: str) -> StatementParseReport | None:
    """One run, one transaction. `None` when the queue had nothing due.

    **The rows, the run's status and the file's status commit together.** A partial commit would
    leave a `succeeded` run holding half a statement, and nothing downstream could tell that apart
    from a statement that was half as long.
    """

    with runtime.uow_factory() as uow:
        claimed = claim_jobs(uow.session, queue_name=QUEUE_NAME, worker_id=worker_id, limit=1)
        if not claimed:
            uow.rollback()
            return None
        jobs = [job for job in claimed if job.job_type == IMPORT_JOB_TYPE]
        if not jobs:
            # Somebody else's job type — a crop, today. Handed back for the reason spelled out in
            # `_render_one`: failing what this task does not recognise would consume the attempts
            # of a job it never tried.
            for job in claimed:
                release_job(job, status="retry_scheduled")
            uow.commit()
            return StatementParseReport(parsed=0, failed=0)

        job = jobs[0]
        run_id = uuid.UUID(str(job.input_payload["bank_statement_import_run_id"]))

        try:
            report = parse_pending_run(run_id, uow=uow, storage=runtime.storage, now=utc_now())
        except Exception as error:
            # Broad for the same reason `_render_one` is broad: a statement can fail to open in
            # ways this module cannot enumerate, and every one of them must leave the job
            # released rather than claimed forever.
            uow.rollback()
            return _record_parse_failure(runtime, job.id, run_id, error, worker_id)

        release_job(
            job,
            status="succeeded",
            output={"import_run_status": report.status, "row_count": report.row_count},
        )
        uow.commit()
        log_event(
            logger,
            logging.INFO,
            "bank_statement_parsed",
            bank_statement_import_run_id=str(run_id),
            processing_job_id=str(job.id),
            import_run_status=report.status,
            row_count=report.row_count,
            rows_invalid=report.invalid,
        )
        # **A run that failed on its mapping is not a worker failure.** The job did exactly what it
        # was asked and the answer was "this mapping does not fit this file", which is recorded on
        # the run's `error_summary`. Counting it as a worker failure would put a configuration
        # problem into the retry machinery, and retrying it would produce the same answer four
        # more times. §22.2's remedy is a new run after the mapping is corrected.
        return StatementParseReport(parsed=1, failed=0)


def _record_parse_failure(
    runtime: RuntimeServices,
    job_id: uuid.UUID,
    run_id: uuid.UUID,
    error: Exception,
    worker_id: str,
) -> StatementParseReport:
    """Record the failure on the job, in a transaction of its own.

    **The run is left `running`, and that is deliberate rather than a leak.** A crash between the
    claim and the commit means nobody knows what the parse read; writing `failed` here would
    assert a conclusion this code never reached, and `failed` is what a mapping mismatch means.
    The job carries the error and its remaining attempts, and slice 3's in-flight guard stops a
    second parse of the same statement starting meanwhile — which is the state that guard exists
    for.
    """

    with runtime.uow_factory() as uow:
        from app.db.models.processing_job import ProcessingJob

        job = uow.session.get(ProcessingJob, job_id)
        if job is None:
            uow.rollback()
            return StatementParseReport(parsed=0, failed=1)

        exhausted = job.attempt_count >= job.max_attempts
        release_job(
            job,
            status="dead_lettered" if exhausted else "retry_scheduled",
            error_code=type(error).__name__,
            # The message, not the traceback: a traceback can carry a storage key, which is the
            # boundary `app/files/download.py` exists to protect.
            error_message=str(error)[:500],
        )
        uow.commit()

    log_event(
        logger,
        logging.WARNING if exhausted else logging.INFO,
        "bank_statement_parse_failed",
        bank_statement_import_run_id=str(run_id),
        processing_job_id=str(job_id),
        error_code=type(error).__name__,
        exhausted=exhausted,
        worker_id=worker_id,
    )
    return StatementParseReport(parsed=0, failed=1)
