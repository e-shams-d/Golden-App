"""Celery factory with named queues and non-authoritative result handling."""

from __future__ import annotations

from celery import Celery
from kombu import Queue

from app.core.config import Settings


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
    )
    return app
