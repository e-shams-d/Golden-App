from __future__ import annotations

from uuid import UUID, uuid4

from app.api.contract import API_CONTRACT_VERSION
from app.core.time import utc_now
from app.observability.health import WorkerProbeResult, WorkerSnapshot
from fastapi.testclient import TestClient


def test_liveness_is_minimal_and_does_not_probe_dependencies(app_factory) -> None:
    app, runtime, _settings = app_factory()

    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "alive",
        "service": "backend-api",
        "version": "0.1.0-test",
    }
    assert all(probe.calls == 0 for probe in runtime.probes.values())
    UUID(response.headers["X-Request-ID"])
    assert response.headers["X-Correlation-ID"] == response.headers["X-Request-ID"]


def test_readiness_uses_canonical_minimal_contract(app_factory) -> None:
    app, _runtime, _settings = app_factory()

    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "redis": "ok", "storage": "ok"},
    }


def test_readiness_fails_closed_when_required_dependency_is_down(app_factory) -> None:
    app, _runtime, _settings = app_factory(
        dependency_statuses={"database": "ok", "redis": "unavailable", "storage": "ok"},
        dependency_errors={"redis": "REDIS_UNAVAILABLE"},
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "ok", "redis": "unavailable", "storage": "ok"},
    }
    assert "database-secret" not in response.text
    assert "redis-secret" not in response.text


def test_dependency_details_are_restricted_and_safe(app_factory) -> None:
    app, _runtime, settings = app_factory(
        dependency_statuses={"database": "unavailable", "redis": "ok", "storage": "ok"},
        dependency_errors={"database": "DATABASE_SCHEMA_INCOMPATIBLE"},
    )

    with TestClient(app) as client:
        denied = client.get("/api/v1/health/dependencies")
        allowed = client.get(
            "/api/v1/health/dependencies",
            headers={"X-Operations-Token": settings.operations_health_token.get_secret_value()},
        )

    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "FORBIDDEN"
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "degraded"
    assert allowed.json()["dependencies"]["database"]["error_code"] == (
        "DATABASE_SCHEMA_INCOMPATIBLE"
    )
    assert "database-secret" not in allowed.text
    assert "127.0.0.1" not in allowed.text


def test_worker_details_are_restricted_and_report_live_control_reply(app_factory) -> None:
    worker = WorkerSnapshot(
        name="worker-1",
        status="running",
        queues=("exports", "files"),
        last_heartbeat_at=utc_now(),
        release_version="0.1.0-test",
        active_job_count=2,
    )
    app, _runtime, settings = app_factory(worker_result=WorkerProbeResult(True, (worker,)))

    with TestClient(app) as client:
        denied = client.get("/api/v1/health/workers")
        allowed = client.get(
            "/api/v1/health/workers",
            headers={"X-Operations-Token": settings.operations_health_token.get_secret_value()},
        )

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["workers"][0]["queues"] == ["exports", "files"]
    assert allowed.json()["workers"][0]["active_job_count"] == 2


def test_worker_unavailability_uses_standard_error_envelope(app_factory) -> None:
    app, _runtime, settings = app_factory(
        worker_result=WorkerProbeResult(False, (), "WORKER_PROBE_TIMEOUT")
    )
    request_id = str(uuid4())

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/health/workers",
            headers={
                "X-Operations-Token": settings.operations_health_token.get_secret_value(),
                "X-Request-ID": request_id,
            },
        )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "BACKGROUND_PROCESSING_UNAVAILABLE",
            "message": "Background processing is unavailable.",
            "details": [],
            "request_id": request_id,
        }
    }


def test_release_metadata_and_openapi_are_versioned(app_factory) -> None:
    app, runtime, _settings = app_factory()

    with TestClient(app) as client:
        release = client.get("/api/v1/meta/release")
        schema = client.get("/api/v1/openapi.json")

    assert release.status_code == 200
    assert release.json()["commit"] == "abcdef1234567"
    assert release.json()["built_at"] == "2026-07-20T12:00:00Z"
    assert schema.status_code == 200
    assert schema.json()["info"]["version"] == API_CONTRACT_VERSION
    paths = schema.json()["paths"]
    assert {
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/health/dependencies",
        "/api/v1/health/workers",
        "/api/v1/meta/release",
    }.issubset(paths)
    assert runtime.closed is True
