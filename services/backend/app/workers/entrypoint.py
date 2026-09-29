"""Environment-loaded Celery CLI entrypoint.

**This module is also where the worker's process-wide resources are wired**, which is what
`app/workers/runtime.py` has always said about it: "configure_worker is wired to Celery's
`worker_process_init` signal by the entrypoint". It was not. The entrypoint built the app
and connected nothing, so every task that touched the database raised

    RuntimeError: the worker runtime is not configured in this process.

— an error whose own text names this file as the place that prevents it. Nobody saw it
because until the tasks were registered at all (F-22) no task ever ran.

`worker_process_init` rather than `worker_init`: the engine must be built **after** the
fork. A pool created in the parent is inherited by every child, and children sharing
sockets they each believe they own produce errors that look like random corruption.
`runtime.py`'s module docstring is explicit about this, and connecting to the wrong signal
would satisfy this file's purpose while reintroducing exactly what it warns against.
"""

from celery.signals import worker_process_init

from app.core.config import load_settings
from app.workers.celery_app import create_celery_app
from app.workers.runtime import configure_worker

celery_app = create_celery_app(load_settings())

# `configure_worker` takes Celery's signal keyword arguments and ignores them, so it is
# connected directly — `runtime.py` built it that way to avoid a wrapper that would be one
# more place for this wiring to be wrong.
worker_process_init.connect(configure_worker)
