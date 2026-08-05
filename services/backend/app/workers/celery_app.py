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
