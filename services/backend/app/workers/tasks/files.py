"""Tasks routed to the `files` queue.

Empty by design. The module exists because `app/workers/celery_app.py` routes on
the dotted path `app.workers.tasks.files.*`; a task defined elsewhere matches no
glob and lands silently on `task_default_queue`, which is `maintenance`.

Creating the module now means the first task added here routes correctly instead
of being discovered on the wrong queue later.
"""

from __future__ import annotations

QUEUE_NAME = "files"
