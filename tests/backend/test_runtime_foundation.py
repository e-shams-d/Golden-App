from __future__ import annotations

import app.db.models  # noqa: F401  # registers every mapped table on Base.metadata
from app.db.base import Base, over_length_identifiers
from app.workers.celery_app import create_celery_app
from fastapi.testclient import TestClient

EXPECTED_TABLES = frozenset(
    {
        "audit_logs",
        "center_profile",
        "idempotency_records",
        "outbox_events",
    }
)


def test_exactly_the_slice_one_tables_are_mapped() -> None:
    """Pin the mapped set, so a table cannot arrive without a decision.

    Every table here is a permanent migration and a governance commitment. An
    accidental import bringing a half-finished model into `Base.metadata` would
    otherwise reach autogenerate, and from there a migration, with nothing having
    said so out loud.
    """

    assert frozenset(Base.metadata.tables) == EXPECTED_TABLES


def test_no_identifier_would_be_silently_truncated() -> None:
    """PostgreSQL truncates at 63 bytes without warning.

    Two constraints on a wide table can collapse into the same name, and the
    second CREATE then fails — or worse, succeeds against the wrong object.
    `audit_logs` is wide enough for this to be a live risk rather than a
    theoretical one.
    """

    assert over_length_identifiers() == []


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
