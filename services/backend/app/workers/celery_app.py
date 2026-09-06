"""Celery factory with named queues and non-authoritative result handling."""

from __future__ import annotations

from datetime import timedelta

from celery import Celery
from kombu import Queue

from app.core.config import Settings

# Both sweeps are recovery, not routine, and their intervals say so.
#
# The outbox poll is a safety net rather than the delivery path: a dispatch
# registered after commit still runs immediately, and this only picks up what a
# process death lost between the commit and the hook. Polling every few seconds
# would spend a claim query per interval per worker to find nothing almost
# always.
#
# Lease recovery is slower still. It reports rather than resets, and the number
# it reports is only interesting as a trend.
OUTBOX_POLL_INTERVAL = timedelta(seconds=30)
STALE_LEASE_SWEEP_INTERVAL = timedelta(minutes=5)

# M11 slice 6A. Daily, and the interval is part of the design rather than a default.
#
# Every pass reads objects out of storage, so the cost is I/O per row rather than a query. Hourly
# would multiply that by twenty-four to catch a corruption a day sooner, which is not a trade worth
# making for bytes that do not change on their own. Weekly would let a broken write path run for
# six days before anything noticed.
CHECKSUM_VERIFY_INTERVAL = timedelta(days=1)

# M11 slice 6B. Daily, and it costs two counting queries per activated policy — of which
# there are currently none. The interval is about the day the first policy is activated: an
# impact report a day old is fine, and one nobody has seen since last month is not.
RETENTION_DRY_RUN_INTERVAL = timedelta(days=1)

BEAT_SCHEDULE: dict[str, dict[str, object]] = {
    "outbox-dispatch": {
        "task": "app.workers.tasks.maintenance.poll_outbox_task",
        "schedule": OUTBOX_POLL_INTERVAL,
        # Explicit even though the module prefix already routes here: a reader
        # checking which queue a scheduled task lands on should not have to
        # resolve a glob to find out.
        "options": {"queue": "maintenance"},
    },
    "stale-lease-sweep": {
        "task": "app.workers.tasks.maintenance.recover_stale_leases_task",
        "schedule": STALE_LEASE_SWEEP_INTERVAL,
        "options": {"queue": "maintenance"},
    },
    # M11 slice 6A. The third of §19.5's eight, and the first that reads storage rather than the
    # database. Routed to `maintenance` explicitly like the other two, even though
    # `app.workers.tasks.*` would not match this module's prefix rule on its own — the routes map
    # below has no entry for `checksums`, so without this option the task would land on the
    # default queue and nobody would notice until it was starved behind something else.
    # M11 slice 6B. Reports what retention would remove. There is deliberately no companion
    # entry that removes it: ADR-005 is open and the owner decided against automatic
    # deletion, and `test_no_deletion_machinery.py` refuses one on purpose.
    "retention-dry-run": {
        "task": "app.workers.tasks.retention.retention_dry_run_task",
        "schedule": RETENTION_DRY_RUN_INTERVAL,
        "options": {"queue": "maintenance"},
    },
    "checksum-verification": {
        "task": "app.workers.tasks.checksums.verify_checksums_task",
        "schedule": CHECKSUM_VERIFY_INTERVAL,
        "options": {"queue": "maintenance"},
    },
}


def create_celery_app(settings: Settings) -> Celery:
    app = Celery(settings.service_name)
    queues = tuple(Queue(name) for name in settings.queue_names)
    routes = {
        "app.workers.tasks.files.*": {"queue": "files"},
        "app.workers.tasks.exports.*": {"queue": "exports"},
        "app.workers.tasks.notifications.*": {"queue": "notifications"},
        "app.workers.tasks.reports.*": {"queue": "reports"},
        "app.workers.tasks.maintenance.*": {"queue": "maintenance"},
        # M11 slice 6A. Its own entry rather than relying on the beat option above: a task sent by
        # hand — an operator running a verification pass now — must land on the same queue the
        # schedule uses, and `options` only covers the scheduled call.
        "app.workers.tasks.checksums.*": {"queue": "maintenance"},
        "app.workers.tasks.retention.*": {"queue": "maintenance"},
        "app.workers.tasks.ai.*": {"queue": "ai"},
    }
    app.conf.update(
        broker_url=settings.redis_url.get_secret_value(),
        result_backend=None,
        task_ignore_result=True,
        task_store_errors_even_if_ignored=False,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_track_started=True,
        task_always_eager=settings.celery_task_always_eager,
        task_serializer="json",
        result_serializer="json",
        accept_content=("json",),
        enable_utc=True,
        timezone="UTC",
        task_default_queue="maintenance",
        task_queues=queues,
        task_routes=routes,
        worker_prefetch_multiplier=1,
        worker_send_task_events=True,
        task_send_sent_event=True,
        broker_connection_retry_on_startup=True,
        broker_transport_options={"visibility_timeout": 3600},
        beat_schedule=BEAT_SCHEDULE,
    )
    return app
