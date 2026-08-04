"""Process-wide resources for the worker, which had none.

`RuntimeServices.from_settings` is called by the FastAPI lifespan and nowhere
else. A Celery task therefore has no engine, no session factory and no Unit of
Work — it can import them, but nothing constructs them, so the first task that
touches the database would build its own engine per call and leak a connection
pool every time.

The engine is built once per worker process and reused, deliberately **after**
the fork rather than at import. A pool created before Celery forks is inherited
by every child, and the children then share sockets they each believe they own —
the resulting errors look like random corruption and are extremely hard to trace
back here.

Nothing in this module runs at import time. `configure_worker` is wired to
Celery's `worker_process_init` signal by the entrypoint, and tests call
`reset_worker_runtime` to get a clean process-local state.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.core.config import Settings, load_settings
from app.core.logging import get_logger, log_event
from app.core.runtime import RuntimeServices

logger = get_logger("workers.runtime")

_runtime: RuntimeServices | None = None


def configure_worker(settings: Settings | None = None, **_signal_kwargs: Any) -> RuntimeServices:
    """Build this process's resources. Called once, after the fork.

    Accepts and ignores Celery's signal keyword arguments so it can be connected
    directly to `worker_process_init` without a wrapper that would be one more
    place for the wiring to be wrong.
    """

    global _runtime

    if _runtime is not None:
        return _runtime

    _runtime = RuntimeServices.from_settings(settings or load_settings())
    log_event(
        logger,
        logging.INFO,
        "worker_runtime_ready",
        pid=os.getpid(),
    )
    return _runtime


def worker_runtime() -> RuntimeServices:
    """The resources for this process.

    Raises rather than lazily constructing. A task that reaches this before the
    process is configured has a wiring problem, and building an engine here to
    paper over it would create one pool per fork with nothing owning it.
    """

    if _runtime is None:
        raise RuntimeError(
            "the worker runtime is not configured in this process. "
            "app.workers.entrypoint connects configure_worker to Celery's "
            "worker_process_init signal; a task running outside that path must "
            "configure it explicitly."
        )
    return _runtime


def shutdown_worker(**_signal_kwargs: Any) -> None:
    """Release the pool on process shutdown, so a restart does not leak it."""

    global _runtime

    if _runtime is None:
        return
    _runtime.close()
    _runtime = None
    log_event(logger, logging.INFO, "worker_runtime_closed", pid=os.getpid())


def reset_worker_runtime() -> None:
    """Drop the process-local runtime without closing it.

    For tests that install a fake. Closing here would dispose an engine the test
    still owns, which produces a failure in whichever test happens to run next.
    """

    global _runtime

    _runtime = None
