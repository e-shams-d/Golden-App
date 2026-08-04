"""Task modules, one per frozen queue prefix.

The routing globs in `app/workers/celery_app.py` match on the dotted module path:
`app.workers.tasks.files.*` goes to the `files` queue and so on. A task defined
anywhere else matches no glob and lands on `task_default_queue`, which is
`maintenance` — silently, with no error, on a queue sized for sweeps.

So the package layout is not organisational. Each module below exists because its
name is the routing key, and the six names are frozen by
`app/core/config.py`'s `celery_queues` default. `ai` has no Phase 1A producer and
exists so a task added later routes correctly rather than falling through.
"""

from __future__ import annotations

QUEUE_MODULES: tuple[str, ...] = (
    "files",
    "exports",
    "notifications",
    "reports",
    "maintenance",
    "ai",
)
