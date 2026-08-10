from __future__ import annotations

from app.api.contract import API_CONTRACT_VERSION
from app.api.dependencies import OPERATIONS_SECURITY_SCHEME, OPERATIONS_TOKEN_HEADER
from fastapi.testclient import TestClient
from scripts.export_openapi import build_schema, render_schema, render_schema_bytes


def test_openapi_export_is_deterministic_and_stays_inside_v1() -> None:
    first = render_schema()
    second = render_schema()
    first_bytes = render_schema_bytes()
    second_bytes = render_schema_bytes()
    schema = build_schema()

    assert first == second
    assert first_bytes == second_bytes == first.encode("utf-8")
    assert first_bytes.endswith(b"\n")
    assert b"\r\n" not in first_bytes
    assert schema["openapi"].startswith("3.1.")
    assert schema["info"]["version"] == API_CONTRACT_VERSION
    assert all(path.startswith("/api/v1/") for path in schema["paths"])


def test_openapi_operations_are_stable_and_error_schema_matches_runtime() -> None:
    schema = build_schema()
    operation_ids = [
        operation["operationId"]
        for path_item in schema["paths"].values()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete", "options", "head"}
    ]
    schemas = schema["components"]["schemas"]

    assert len(operation_ids) == len(set(operation_ids))
    # Every published operation is a contract other people generate clients from,
    # so the set is pinned rather than counted. Adding one here is a deliberate
    # act; `renameCenterProfile` is M2's exemplar command.
    assert set(operation_ids) == {
        "getHealthDependencies",
        "getHealthLiveness",
        "getHealthReadiness",
        "getHealthWorkers",
        "getReleaseMetadata",
        "renameCenterProfile",
        "getBackgroundProcessingHealth",
        # Additive path. The evidence emitter reads the applied Alembic revision from
        # the running instance rather than from `alembic/versions/`, and this is how
        # it asks. Folding these fields into an existing response would change a
        # published schema and trip the oasdiff breaking-change gate, whose waiver
        # process is still an unresolved TODO(governance).
        "getReleaseEvidence",
        # M3 slice 4. Two login operations rather than one taking a `user_type`,
        # which is DOC-CONFLICT-023's approved direction made visible in the
        # published contract: the audience is a property of the URL, so a client
        # generated from this document cannot ask to be evaluated as the other one.
        "loginAdmin",
        "loginTrader",
        "getCurrentSession",
        "logout",
        "listOwnSessions",
        "revokeOwnSession",
        # M3 slice 6. Ownership-scoped rather than permission-scoped: a trader
        # holds no grants, so the guard is the session's own trader_id.
        # M3 slice 7. Raises assurance for one exact action; it approves
        # nothing (doc 12:550).
        "reauthenticate",
        "getOwnTraderProfile",
        "updateOwnTraderProfile",
        # M3 slice 8. `registerTrader` is the only unauthenticated write
        # surface on the platform; the four decisions are the center's and each
        # carries its own canonical permission.
        "registerTrader",
        "approveTrader",
        "rejectTrader",
        "suspendTrader",
        "reactivateTrader",
    }
    assert "ErrorEnvelope" in schemas
    assert "HTTPValidationError" not in schemas
    assert "ValidationError" not in schemas


def test_no_login_operation_accepts_an_audience_selector() -> None:
    """SEC-AUD-002, asserted against the contract rather than against source.

    DOC-CONFLICT-023's resolution is that the audience is derived and enforced
    server-side, never taken from a client-supplied field. A `user_type` in a
    login body would not grant authority by itself — the credential still has to
    be valid — but it would decide *which* authority is evaluated, and that puts
    the separation inside a handler branch nothing outside can observe.

    Checked here because the OpenAPI document is what other people generate
    clients from: a field that never appears in it cannot be sent by a generated
    client, and a source-level review is not something CI repeats.
    """

    schema = build_schema()
    login_paths = [path for path in schema["paths"] if path.endswith("/login")]

    assert len(login_paths) == 2, (
        f"expected exactly two login operations, one per audience; found {login_paths}"
    )

    for path in login_paths:
        body = schema["paths"][path]["post"]["requestBody"]
        reference = body["content"]["application/json"]["schema"]["$ref"]
        model = schema["components"]["schemas"][reference.rsplit("/", 1)[-1]]
        fields = set(model["properties"])

        assert fields == {"identifier", "password"}, (
            f"{path} accepts {sorted(fields)}. An audience selector in the body is "
            "exactly what DOC-CONFLICT-023 refuses; the route is the selector."
        )


def test_restricted_operations_use_explicit_api_key_security_scheme() -> None:
    schema = build_schema()
    security_schemes = schema["components"]["securitySchemes"]
    expected = {
        "type": "apiKey",
        "description": "Operations-only health access token.",
        "in": "header",
        "name": OPERATIONS_TOKEN_HEADER,
    }

    assert security_schemes[OPERATIONS_SECURITY_SCHEME] == expected
    for path in (
        "/api/v1/health/dependencies",
        "/api/v1/health/workers",
    ):
        operation = schema["paths"][path]["get"]
        assert operation["security"] == [{OPERATIONS_SECURITY_SCHEME: []}]
        assert all(
            parameter.get("name") != OPERATIONS_TOKEN_HEADER
            for parameter in operation.get("parameters", ())
        )

    for path in (
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/meta/release",
    ):
        assert "security" not in schema["paths"][path]["get"]


def test_export_ignores_host_environment(monkeypatch) -> None:
    baseline = render_schema_bytes()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_DEBUG", "definitely-not-a-boolean")
    monkeypatch.setenv("DATABASE_URL", "not-a-database-url")
    monkeypatch.setenv("REDIS_URL", "not-a-redis-url")
    monkeypatch.setenv("OPERATIONS_HEALTH_TOKEN", "host-secret-must-not-be-read")

    assert render_schema_bytes() == baseline


def test_production_does_not_publish_openapi_or_interactive_docs(
    app_factory,
) -> None:
    app, _runtime, _settings = app_factory(settings_overrides={"app_env": "production"})

    with TestClient(app) as client:
        assert client.get("/api/v1/openapi.json").status_code == 404
        assert client.get("/api/v1/docs").status_code == 404


def test_openapi_contains_no_runtime_credentials_or_local_paths() -> None:
    rendered = render_schema()

    for forbidden in (
        "contract:contract",
        "redis://",
        "postgresql",
        "contract-storage",
        "OPERATIONS_HEALTH_TOKEN",
    ):
        assert forbidden not in rendered
