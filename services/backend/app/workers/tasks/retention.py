"""The scheduler's entry point for the retention dry run.

M11 slice 6B. The work is in `app/retention/dry_run.py`; this module exists so the beat schedule
has a zero-argument callable to name, and so the logging of an unresolvable policy happens on a
schedule rather than only when somebody calls the function.

**This task deletes nothing and there is no sibling that does.** §19.5 asks for "retention dry run
and approved execution only"; the execution half is blocked by ADR-005 and by the owner's decision
of 2026-09-05, and `tests/backend/test_no_deletion_machinery.py` refuses a scheduled task that
removes rows. A reader looking for the deletion job should find this sentence rather than an empty
module.
"""

from __future__ import annotations

import logging

from app.core.logging import get_logger, log_event
from app.retention.dry_run import plan_retention

logger = get_logger("workers.retention")


def retention_dry_run_task() -> dict[str, int]:
    """One pass, reported as counts and logged where it cannot answer.

    **An unresolvable policy is logged at WARNING every run.** A policy naming a resource type
    nothing can query is a decision somebody has not finished making, and the report's totals look
    calm while it stands — so the job says so on every pass rather than once. That is the same
    reasoning `verify_recent_checksums` uses for logging an incomplete coverage pass repeatedly.
    """

    from app.core.time import utc_now
    from app.workers.runtime import worker_runtime

    runtime = worker_runtime()
    with runtime.uow_factory() as uow:
        report = plan_retention(uow.session, now=utc_now())
        uow.rollback()

    if report.unresolved:
        log_event(
            logger,
            logging.WARNING,
            "retention_policy_unresolvable",
            resource_types=list(report.unresolved),
            detail=(
                "an activated policy names a resource type nothing can query; its impact is "
                "unknown rather than zero"
            ),
        )

    return {
        "policies": len(report.impacts),
        "eligible": report.total_eligible,
        "unresolvable": len(report.unresolved),
    }
