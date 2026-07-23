from __future__ import annotations

from uuid import UUID, uuid4

from app.core.errors import AppError, ErrorDetail
from fastapi import Body
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field


class ExamplePayload(BaseModel):
    count: int = Field(ge=1)


def test_client_request_and_correlation_ids_are_validated_and_echoed(app_factory) -> None:
    app, _runtime, _settings = app_factory()
    request_id = str(uuid4())
    correlation_id = str(uuid4())

    with TestClient(app) as client:
        valid = client.get(
            "/api/v1/health/live",
            headers={"X-Request-ID": request_id, "X-Correlation-ID": correlation_id},
        )
        invalid = client.get(
            "/api/v1/health/live",
            headers={"X-Request-ID": "not-a-valid-id", "X-Correlation-ID": "also-invalid"},
        )

    assert valid.headers["X-Request-ID"] == request_id
    assert valid.headers["X-Correlation-ID"] == correlation_id
    replacement = invalid.headers["X-Request-ID"]
    UUID(replacement)
    assert replacement != "not-a-valid-id"
    assert invalid.headers["X-Correlation-ID"] == replacement


def test_typed_error_uses_canonical_envelope(app_factory) -> None:
    app, _runtime, _settings = app_factory()

    @app.get("/api/v1/example-conflict")
    def conflict() -> None:
        raise AppError(
            "VERSION_CONFLICT",
            "The record changed after it was loaded.",
            412,
            (ErrorDetail(field=None, reason="expected rv-7 but current version is rv-8"),),
        )

    request_id = str(uuid4())
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/example-conflict",
            headers={"X-Request-ID": request_id},
        )

    assert response.status_code == 412
    assert response.json() == {
        "error": {
            "code": "VERSION_CONFLICT",
            "message": "The record changed after it was loaded.",
            "details": [
                {"field": None, "reason": "expected rv-7 but current version is rv-8"}
            ],
            "request_id": request_id,
        }
    }


def test_validation_errors_use_canonical_envelope_without_input_echo(app_factory) -> None:
    app, _runtime, _settings = app_factory()

    @app.post("/api/v1/example-validation")
    def validate(payload: ExamplePayload = Body()) -> ExamplePayload:
        return payload

    with TestClient(app) as client:
        response = client.post("/api/v1/example-validation", json={"count": 0, "secret": "raw"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"][0]["field"] == "count"
    assert "raw" not in response.text
    UUID(error["request_id"])


def test_framework_404_uses_error_contract(app_factory) -> None:
    app, _runtime, _settings = app_factory()

    with TestClient(app) as client:
        response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert "detail" not in response.json()


def test_unexpected_errors_do_not_expose_exception_or_secret(app_factory) -> None:
    app, _runtime, _settings = app_factory()

    @app.get("/api/v1/example-failure")
    def fail() -> None:
        raise RuntimeError("database-secret should never escape")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/example-failure")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "database-secret" not in response.text
    assert "RuntimeError" not in response.text
