"""The published contract, and what may never change in it silently.

Covers: CI-OPENAPI-001, SEC-AUD-002.
"""

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
        # M3 slice 8C. Both audiences change their own the same way, so there is one
        # operation and no `user_type` — the same reasoning as the two login routes,
        # from the other direction: the caller is already established, so the audience
        # is a property of the session rather than of the URL.
        "changeOwnPassword",
        # M3 slice 8D. Four operations rather than two, because the approved catalogue
        # resolves doc 05's `admin_user.manage` to three action-specific canonical
        # permissions and the endpoints have to follow the permissions.
        "listAdminUsers",
        "getAdminUser",
        "createAdminUser",
        "updateAdminUser",
        # The centre's read surface. Brought forward from M5 deliberately — see the
        # plan's slice D1 — because without it an operator cannot learn the id of a
        # business to approve, and registration returns none by design.
        "listTraders",
        "getTrader",
        # M3 slice 8E. The three acts on somebody else, each guarded separately: the
        # catalogue's four canonical codes have no `user.suspend`, so suspension takes
        # `user.deactivate` and the other two take `user.update`, which keeps "can remove
        # access" and "can restore it" expressible as different authorities.
        "suspendAdminUser",
        "reactivateAdminUser",
        "resetAdminUserPassword",
        # The far side of that reset, and unauthenticated by necessity: an account in
        # `recovery_required` is refused every action except recovery, so it can hold no
        # session to present. Published so a client can be generated for it — the flow is
        # otherwise reachable only by somebody who read this file.
        "recoverAdminPassword",
        # Roles. `updateRolePermissions` is the first operation in the contract to require
        # `X-Recent-Auth`: the step-up machinery has existed since slice 7 with no
        # consumer at all, so six obligations were green against a mechanism no route
        # exercised.
        "listRoles",
        "getRole",
        "updateRolePermissions",
        # M4 slice 2. The first operation in this contract whose request body is not
        # JSON, and the first that writes a byte to storage. Its response is pinned
        # elsewhere by `API-FILE-001`, which reads the response model's field names so
        # that a storage address added later cannot reach a client.
        "uploadFile",
        # M4 slice 5. The first operations that stream bytes rather than JSON, and the
        # first whose refusal is deliberately indistinguishable from "not found".
        "getFileMetadata",
        "downloadFile",
        "previewFile",
        # M4 slice 8. Creation only: activation needs two permissions that do not exist
        # yet (DOC-CONFLICT-045), and a route guarded by an unapproved identifier denies
        # everyone — shipping it before the guard is reviewable ships a decision as an
        # accident.
        "listBankProfiles",
        "createBankProfile",
        "listBankAccounts",
        "createBankAccount",
        # M4 slice 9. Present in the contract and denied to every role: the permission
        # exists and is granted to nobody (DOC-CONFLICT-045).
        "activateBankProfileVersion",
        # M5 slice 2. Five of the seven document 05 lists for beneficiaries.
        # `blockBeneficiary` and `reactivateBeneficiary` are absent because no
        # permission in the approved catalogue covers them, and a route guarded by
        # an unapproved identifier denies everyone — the same reasoning that kept
        # activation out of M4 slice 8. `deactivateBeneficiary` is here and not in
        # document 05's table, because it is the one lifecycle move that has both a
        # catalogued permission and a document 06 transition. DOC-CONFLICT-049.
        "listBeneficiaries",
        "createBeneficiary",
        "getBeneficiary",
        "updateBeneficiary",
        "deactivateBeneficiary",
        # M5 slice 3. Draft creation, and cancellation — which the plan did not
        # list for this slice and which `CON-REQ-001` needs: a slice whose only
        # route creates a resource has nothing for `If-Match` to be stale
        # against, so the obligation was unprovable as scoped.
        "createPaymentRequestDraft",
        "cancelPaymentRequest",
        # M5 slice 5. The correction path and the history that makes it
        # answerable. `05_API_Specification.md:1136` and `:1142`.
        "createPaymentRequestRevision",
        "listPaymentRequestRevisions",
        # M5 slice 6.
        "submitPaymentRequest",
        # M5 slice 7. The centre's half of the journey.
        # `05_API_Specification.md:1189`, `:1197`, `:1213`.
        "startPaymentRequestReview",
        "requestPaymentRequestCorrection",
        "markPaymentRequestEligibleForBatching",
        # M5 slice 8. The two reads the screens need. `05_API_Specification.md:1061` and
        # `:1125`. Until this slice the aggregate had eleven operations and one of them
        # read — a trader could not list their own requests and an accountant had no queue.
        "listPaymentRequests",
        "getPaymentRequest",
        # M6 slice 1. `05_API_Specification.md:1268`. Advisory and non-mutating: the first
        # batching operation, and the only one that writes nothing.
        "previewPaymentBatch",
        # M6 slice 2. `:1318`, `:1347`. The create and the two reads, shipped together
        # because a container nothing can read is a container nobody can act on — the shape
        # of the five mechanisms-with-no-caller M3 shipped and M5 shipped once more.
        "createPaymentBatch",
        "listPaymentBatches",
        "getPaymentBatch",
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
