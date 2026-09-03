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
        # M8 slice 5. `05_API_Specification.md:1042`'s second preview endpoint, which M4 could not
        # build without a renderer. Its sibling above stops serving the original bytes in the same
        # slice, and the test that proves it names the obligation — an id written here would make
        # this file the thing claiming it.
        "previewFilePage",
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
        # M6 slice 3. `05_API_Specification.md:1369`. The first M6 operation that
        # publishes an outbox event, because it is the first that gives a manager
        # something to decide about.
        "finalizePaymentBatchVersion",
        # M6 slice 4. `05_API_Specification.md:1361` and `:1539`. The replacement is
        # the only way a finalized version leaves the lifecycle in M6; the
        # cancellation is draft-only, because §29.2's second origin has no permission.
        "createReplacementPaymentBatchVersion",
        "cancelPaymentBatch",
        # M7 slice 1. `05_API_Specification.md:1398`, `:1415` and `:1449`. Three operations
        # rather than two: the view is separately permissioned, because an auditor must be
        # able to see what was decided without being able to decide it.
        "getPaymentBatchApprovalView",
        "approvePaymentBatchVersion",
        "rejectPaymentBatchVersion",
        # M7 slice 2. `05_API_Specification.md:1466`. The final export is slice 3's and is
        # deliberately absent here — the two are separate operations because §1 forbids one
        # becoming the other.
        "generateBankExportPreview",
        # M7 slice 3. `05_API_Specification.md:1475`. A separate operation from the preview, and
        # it stays separate because §1 forbids one becoming the other.
        "generateBankExportFinal",
        # M7 slice 4. `05_API_Specification.md:1500`, `:1508` and `:1516`. Under `/bank-exports`
        # rather than the batch, because mark-sent acts on an exact export.
        "getBankExport",
        "downloadBankExport",
        "markBankExportSent",
        # M8 slice 1. `05_API_Specification.md:1642`, `:1676`, `:1685` and `:1700`.
        #
        # **Two operations that document 05 defines are absent, and the absence is the record.**
        # `:1693`'s `start-review` has no permission in `permission_catalog.yaml` at all, so
        # deny-by-default would answer 403 to every caller; the transition it performs happens at
        # upload instead, per `06_Workflows_and_State_Machines.md:995`. `:1721`'s `ai-extraction`
        # is Phase 1B+ and slice 7 asserts no AI path is reachable. This set is where somebody
        # comparing the contract to document 05 will notice both.
        "uploadBankResultBundle",
        "listBankResultBundles",
        "getBankResultBundle",
        "linkBankResultBundleToBatch",
        "closeBankResultBundle",
        # M8 slice 2. `05_API_Specification.md:1733` and `:1791`.
        #
        # **`patchReceiptSegment` is absent and that is the record.** `:1792` defines it;
        # `permission_catalog.yaml` resolves `receipt_segment.update` as deny-until-approved with
        # `canonical_targets: []`, and `m0_open_items` carries the same decision. This set is where
        # somebody comparing the contract against document 05 will notice it.
        "attachExternalEvidence",
        # M8 slice 4. `:1753`'s crop, now that the renderer question is answered — and it answers
        # `202` rather than `201`, because `:1786` says the crop "may return `202` with a processing
        # job" and the image does not exist when the response is written.
        "createReceiptCrop",
        "getReceiptSegment",
        # M8 slice 3. `05_API_Specification.md:2058`'s six, all of them — the first M8 surface where
        # the document's route list and the contract agree exactly: for once no permission is
        # missing and no approved rule forbids one of them.
        "listManualReviewTasks",
        "getManualReviewTask",
        "assignManualReviewTask",
        "startManualReviewTask",
        "resolveManualReviewTask",
        "cancelManualReviewTask",
        # M9 slice 1. Document 05's three at `:1798`, `:1806` and `:1816`, plus a list the
        # document does not define — added because both decision routes take a candidate id and
        # without a read there is no way to obtain one tomorrow. A decision route with no list is
        # a mechanism with no caller, which is this repository's most-repeated defect.
        "proposeMatchingCandidate",
        "listMatchingCandidates",
        "acceptMatchingCandidate",
        "rejectMatchingCandidate",
        # M9 slice 2. Document 05's three at `:1824`, `:1844` and `:1860`. The last keeps its
        # `/void` path while storing the canonical `revoked` — renaming a path is a breaking
        # change the oasdiff gate refuses, and the conflict is recorded in `20260830_0029`.
        "confirmEvidenceLink",
        "replaceEvidenceLink",
        "voidEvidenceLink",
        # M9 slices 3 and 4. Document 05's two at `:1564` and `:1594` — the first operations in
        # this contract that record money as having moved. Neither request body carries an amount,
        # which is how §17 `:1131`'s "amount is exact" is enforced.
        "confirmAttemptPaid",
        "confirmAttemptFailed",
        # M9 slice 3B — the two §17 `:1121` commands the plan forgot. Document 05 defines them at
        # `:1608` and `:1616`; neither request body carries a beneficiary field, which is how
        # "the server rejects free-form beneficiary/IBAN changes" is enforced.
        "markAttemptRetryRequired",
        "createRetryAttempt",
        # M9 slice 5. Document 05 at `:1874` and `:1879`. Neither body carries a financial value —
        # "the client cannot submit arbitrary financial summary values" — and neither offers a
        # share file, which slice 5B builds. `publishPaymentResult` is `201`: nothing here is
        # asynchronous because nothing here renders a file, and the `202` document 05 permits
        # would be a promise this route does not keep.
        "previewPaymentResultPublication",
        "publishPaymentResult",
        # M9 slice 6. The two internal reads (`:1905`) and the three trader operations
        # (`:1913`, `:1921`, `:1942`). §20.4's share-file download is absent on purpose — slice 5B
        # builds the renderer, and an operation that can only ever 404 is one a client would write
        # code against.
        "listPaymentResultPublications",
        "getCurrentPaymentResultPublication",
        "getOwnPaymentResultPublication",
        "acknowledgeOwnPaymentResult",
        "disputeOwnPaymentResult",
        # M9 slice 7B. **The one operation in this contract whose path this implementation chose.**
        # `command_catalog.yaml` gives `payment_publication.correct_paid_result`
        # `method: TBD, path: TBD` and document 05 defines no correction endpoint; §20's own
        # pattern — publication operations under the request — is what settled it, and the M9 plan
        # records it as a path M0 owes.
        "correctPaymentResultPublication",
        # M9 slice 5B. §20.4's second route, which slice 6 left out because `share_file_id` was
        # null on every row and a route that can only 404 is a promise a client writes code
        # against. It renders now, so it exists now.
        "downloadOwnPaymentResultShareFile",
        # M10 slice 1. Document 05 at `:1948` and `:1971`. Four of §21.1's eight — request-payment,
        # cancel and close belong to slices that have states to guard.
        "createGoldSaleOrder",
        "listGoldSaleOrders",
        "getGoldSaleOrder",
        "submitGoldSaleOrder",
        "createGoldSalePricingVersion",
        # M10 slice 2. Document 05 at `:1983`. No `If-Match`: a receipt is a new row, not an edit,
        # and a trader may legitimately pay in instalments.
        "submitIncomingPaymentReceipt",
        # M10 slice 3. Document 05 at `:1990`, four of its five — the fifth reads an import run's
        # rows, and rows are slice 4's. `listStatementImportRuns` is **not** in §21.4 and is here
        # because `SVC-IMPORT-001` is a claim about the *set* of runs: an operator with no way to
        # see run 1 beside run 2 has to take "a reparse does not overwrite it" on trust.
        #
        # No `If-Match` on either write. `command_catalog.yaml` gives the import-run command
        # `concurrency: immutable_new_import_run_per_parse`; a record version guards an edit, and
        # both of these create a row.
        "createBankStatement",
        "listBankStatements",
        "getBankStatement",
        "createStatementImportRun",
        "listStatementImportRuns",
        # M10 slice 5. Document 05 at `:2002`, which spells one route. The reject and the list are
        # not in it and are here for the same reason `listStatementImportRuns` is: `:2009` — the
        # sentence the whole slice exists for — describes *two* decisions, and a surface offering
        # only the first leaves an accountant no way to record a judgement that a suggestion is
        # wrong. The list is what makes a rejected candidate history rather than a deletion.
        #
        # `If-Match` on the reject and not on the propose: one edits a row and the other creates
        # one, and §10.7's unique on the pair is what makes two simultaneous proposals safe.
        "proposeIncomingPaymentMatch",
        "rejectIncomingPaymentMatch",
        "listIncomingPaymentMatches",
        # M10 slice 6. Document 05 at `:2011`, spelled exactly — including the nullable
        # `incoming_payment_match_id`, which §8.9's "evidence before statement availability" is
        # the reason for.
        "confirmIncomingPayment",
        # M10 slice 7. Document 05 at `:2029`. Guarded by `gold_sale.dispatch` alone; the override
        # permission is checked inside the command and only on the path where the payment guard
        # fails, because a `requires(...)` for it would deny every ordinary dispatch.
        "recordGoldDispatch",
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
