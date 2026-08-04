"""Running a claimed job: backoff, dead-lettering, and what retry must never imply.

**A retry is a new attempt, never a re-assertion of success.** The rule sounds
obvious and is the one that gets broken: a handler that retried and eventually
returned must not cause anything to be marked paid, sent or confirmed unless that
attempt itself did the work. So this module moves job *state* and nothing else —
the business effect belongs to the handler, inside its own transaction, and a
handler that cannot be safely repeated says so rather than being trusted.

**Retry safety is declared per handler, not assumed.** A globally applied retry
decorator is how a non-idempotent operation gets run twice: the decorator has no
idea whether the handler it wraps sends money. `JobHandler.retry_safe` is
mandatory, and a handler that is not retry-safe fails straight to
`fallback_to_manual` — a human decides, which is the correct answer for work that
cannot be repeated blindly.

**Backoff is exponential with jitter.** Without jitter a batch of jobs that
failed together retries together, re-creating the pile-up that failed them; the
spread is proportional so it stays useful at every delay.

**Exhaustion keeps the input.** A dead-lettered job that discarded its payload
cannot be reviewed and cannot be replayed by an authorised operator, which turns
a recoverable failure into a lost one.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

from app.core.logging import get_logger, log_event
from app.db.claiming import release_job
from app.db.models.processing_job import ProcessingJob

logger = get_logger("workers.execution")

BASE_DELAY = timedelta(seconds=15)
MAX_DELAY = timedelta(hours=1)
JITTER_FRACTION = 0.25


class JobHandler(Protocol):
    """What a task must provide to be run by this module."""

    job_type: str

    # Not optional and not defaulted. A default would be applied to handlers
    # nobody assessed, and the safe default (False) would send every legitimate
    # transient failure to manual review while the unsafe one (True) would retry
    # a payment.
    retry_safe: bool

    def __call__(self, job: ProcessingJob) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class Outcome:
    status: str
    error_code: str | None = None
    retry_in: timedelta | None = None


def backoff_delay(
    attempt: int, *, rand: Callable[[], float] = random.random
) -> timedelta:
    """Exponential, capped, with proportional jitter.

    Jitter is a fraction of the delay rather than a fixed window: at fifteen
    seconds a one-minute spread would dominate, and at one hour it would do
    nothing. `rand` is injectable so tests assert the shape rather than sampling
    a distribution.
    """

    exponential = BASE_DELAY * (2 ** max(0, attempt - 1))
    capped: timedelta = min(exponential, MAX_DELAY)
    # Computed in seconds rather than by scaling a timedelta twice: the double
    # multiplication is where the type is lost, and a silently-Any delay is one
    # nothing would check again.
    jitter_seconds = capped.total_seconds() * JITTER_FRACTION * (rand() * 2 - 1)
    return max(timedelta(seconds=1), capped + timedelta(seconds=jitter_seconds))


def decide_outcome(
    job: ProcessingJob,
    *,
    handler_retry_safe: bool,
    rand: Callable[[], float] = random.random,
) -> Outcome:
    """What happens to a job whose attempt just failed.

    Pure, so the policy can be asserted without running a worker or a database.
    """

    if not handler_retry_safe:
        # Not retried at all. Whether repeating the work is safe is a property of
        # the operation, and this is the one case where a human must look.
        return Outcome(status="fallback_to_manual", error_code="NOT_RETRY_SAFE")

    if job.attempt_count >= job.max_attempts:
        return Outcome(status="dead_lettered", error_code="ATTEMPTS_EXHAUSTED")

    return Outcome(
        status="retry_scheduled",
        error_code="TRANSIENT",
        retry_in=backoff_delay(job.attempt_count, rand=rand),
    )


def run_job(
    job: ProcessingJob,
    handler: JobHandler,
    *,
    redact: Callable[[str], str] = lambda message: message,
    rand: Callable[[], float] = random.random,
) -> Outcome:
    """Execute a claimed job and move its state. Never commits.

    The caller owns the transaction, because the job-state change and whatever
    the handler wrote must land together or not at all — a job marked succeeded
    beside a rolled-back effect is the worst outcome available.
    """

    try:
        output = handler(job)
    except Exception as error:
        outcome = decide_outcome(job, handler_retry_safe=handler.retry_safe, rand=rand)
        log_event(
            logger,
            logging.WARNING,
            "job_attempt_failed",
            job_type=job.job_type,
            attempt=job.attempt_count,
            max_attempts=job.max_attempts,
            next_status=outcome.status,
            exception_type=type(error).__name__,
        )
        release_job(
            job,
            status=outcome.status,
            error_code=outcome.error_code,
            # Redacted before storage. A driver or client error routinely carries
            # the parameters of the failing call, and this column is readable by
            # anyone who can see operational state.
            error_message=redact(str(error))[:2000],
            retry_delay=outcome.retry_in,
        )
        return outcome

    release_job(job, status="succeeded", output=output or {})
    return Outcome(status="succeeded")
