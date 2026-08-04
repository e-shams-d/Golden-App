"""The transaction boundary a task runs inside, owned in one place.

Every task needs the same shape: take the process runtime, open one Unit of Work,
do the work, commit once. Written per task it is written differently per task,
and the difference that matters — whether the commit happens before or after the
side effect — is invisible in review.

**Dispatch is never called next to a commit.** `celery_task_always_eager` is a
real setting used by tests, and under it `.delay()` executes the task *inline*,
immediately, inside the caller's transaction. A task that opens its own session
then cannot see the caller's uncommitted rows, so it fails or, worse, acts on the
state from before the command ran. Enqueueing therefore goes through the
after-commit hook registry, which runs strictly after the commit and on a
separate session.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.core.logging import get_logger, log_event
from app.core.runtime import RuntimeServices
from app.db.unit_of_work import SqlAlchemyUnitOfWork

logger = get_logger("workers.base")


def run_in_transaction[ResultT](
    runtime: RuntimeServices,
    operation: Callable[[SqlAlchemyUnitOfWork], ResultT],
    *,
    task_name: str,
) -> ResultT:
    """One task, one Unit of Work, one commit.

    The commit is here rather than in the operation so a task cannot commit
    halfway and leave the rest of its work in a second transaction — which is how
    a job gets marked succeeded beside an effect that then rolls back.
    """

    with runtime.uow_factory() as uow:
        result = operation(uow)
        uow.commit()

    log_event(logger, logging.INFO, "task_completed", task=task_name)
    return result


def enqueue_after_commit(
    uow: SqlAlchemyUnitOfWork,
    send: Callable[[], Any],
    *,
    task_name: str,
) -> None:
    """Register a dispatch to happen only if this transaction commits.

    Calling `.delay()` directly beside a commit is wrong in both directions.
    Before the commit, an eager task runs inline and cannot see the rows the
    command has not committed yet. After the commit but outside the hook, a
    crash in between loses the dispatch entirely with the business change already
    durable — and nothing records that it was owed.

    The hook receives a session it does not need; the signature is the registry's,
    and ignoring the argument is cheaper than a second registry for hooks that
    take none.
    """

    def dispatch(_session: object) -> None:
        send()
        log_event(logger, logging.INFO, "task_enqueued_after_commit", task=task_name)

    uow.after_commit(dispatch)
