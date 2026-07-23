from __future__ import annotations

from app.db.base import Base
from app.db.migrations import EXPECTED_MIGRATION_HEADS
from app.workers.celery_app import create_celery_app
from fastapi.testclient import TestClient


def test_m1_has_no_business_tables() -> None:
    assert list(Base.metadata.tables) == []
    assert frozenset({"20260720_0001"}) == EXPECTED_MIGRATION_HEADS


def test_celery_uses_named_utc_queues_and_no_authoritative_result_backend(
    settings_factory,
) -> None:
    settings = settings_factory(celery_task_always_eager=True)
    celery = create_celery_app(settings)

    assert celery.conf.enable_utc is True
    assert celery.conf.timezone == "UTC"
    assert celery.conf.result_backend is None
    assert celery.conf.task_ignore_result is True
    assert tuple(queue.name for queue in celery.conf.task_queues) == settings.queue_names
    assert celery.conf.task_acks_late is True
    assert celery.conf.worker_prefetch_multiplier == 1


def test_runtime_is_created_on_startup_and_closed_on_shutdown(app_factory) -> None:
    app, runtime, _settings = app_factory()

    assert not hasattr(app.state, "runtime")
    assert runtime.closed is False
    with TestClient(app) as client:
        assert client.get("/api/v1/health/live").status_code == 200
        assert app.state.accepting_traffic is True
        assert runtime.closed is False

    assert app.state.accepting_traffic is False
    assert runtime.closed is True
