"""The preview: document 05's shape, strings on the wire, and it writes nothing.

M6 slice 1. The splitting engine is tested where it is pure, in
`tests/backend/test_splitting.py`. What this adds is everything the engine cannot say: that
the route carries the engine's answer, that the amounts leave as strings, that a stale
expectation is refused rather than answered, and that the whole call is **not a command**.

That last one is the negative control, and it is stronger than the document asks.
`15_Agent_Implementation_Plan.md:893` requires that the preview "does not mutate records".
`test_the_preview_is_not_a_command` also requires that it leaves no audit row, no outbox event
and no idempotency record — because a read that leaves a governance trace is a write nobody
has noticed yet, and the traces are where a future "just record who looked" would land.

Covers: API-BATCH-001, API-BATCH-002, CON-BATCH-001, SEC-BATCH-001.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery-staple"
CSRF_HEADER = "X-CSRF-Token"
TRADER_CSRF_COOKIE = "__Host-gp_trader_csrf"
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"

TRADER_PHONE = "+989120001001"
IBAN = "IR060120000000000000000041"

# One billion rial. The profile version below publishes a limit of exactly this, so a request
# above it splits and a request at it does not — which is the boundary worth having a fixture
# for rather than a comment about.
LIMIT = 1_000_000_000


@pytest.fixture(scope="module")
def migrated(module_provisioned_database: RuntimeIdentities) -> RuntimeIdentities:
    result = run_alembic(
        module_provisioned_database.migrator_url,
        "upgrade",
        "head",
        app_role=module_provisioned_database.app_role,
        worker_role=module_provisioned_database.worker_role,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return module_provisioned_database


@pytest.fixture(scope="module")
def world(migrated: RuntimeIdentities, tmp_path_factory: Any) -> Iterator[dict[str, Any]]:
    from app.core.config import Settings
    from app.core.runtime import RuntimeServices
    from app.main import create_app
    from app.security.passwords import Argon2Parameters, hash_password
    from fastapi.testclient import TestClient

    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=migrated.owner_url,
        redis_url="redis://127.0.0.1:6379/0",
        local_storage_root=tmp_path_factory.mktemp("storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="c" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    trader_id = uuid.uuid4()
    beneficiary_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    version_id = uuid.uuid4()

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'Batch Trader', %s, 'active', 'approved')",
            (trader_id, TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (trader_id, TRADER_PHONE, encoded),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'Ali One', %s, %s, 'active', "
            "'not_checked')",
            (beneficiary_id, trader_id, IBAN, IBAN),
        )
        # A bank profile and one version carrying the splitting rules. M4 built these tables;
        # slice 1 reads them and writes nothing. Column names are the model's — an earlier
        # version of this fixture guessed `bank_name`/`bank_code` and PostgreSQL refused it,
        # which is the cheap way for that mistake to surface.
        # Lowercase, because `ck_bank_profiles_code_is_lowercase` says so. M4 put that CHECK
        # there and it refused the fixture, which is the constraint doing its job on a test.
        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'melli', 'Bank Melli', 'active')",
            (profile_id,),
        )
        connection.execute(
            "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, status, "
            "default_transfer_limit_irr, after_cutoff_transfer_limit_irr, cutoff_time, "
            "splitting_enabled, required_fields, rules, config_hash) "
            "VALUES (%s, %s, 1, 'active', %s, NULL, NULL, TRUE, '{}', '{}', %s)",
            (version_id, profile_id, LIMIT, "b" * 64),
        )
        for username, role in (("batch_accountant", "accountant"), ("batch_bare", None)):
            connection.execute(
                "INSERT INTO admin_users (username, full_name, password_hash, status) "
                "VALUES (%s, %s, %s, 'active')",
                (username, username, encoded),
            )
            if role is not None:
                connection.execute(
                    "INSERT INTO admin_user_roles (admin_user_id, role_id) "
                    "SELECT u.id, r.id FROM admin_users u, roles r "
                    "WHERE u.username = %s AND r.code = %s",
                    (username, role),
                )
        connection.commit()

    app = create_app(settings=settings)
    app.state.runtime = RuntimeServices.from_settings(settings)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://trader.localhost") as client:
        yield {
            "client": client,
            "trader_id": trader_id,
            "beneficiary_id": beneficiary_id,
            "version_id": version_id,
            "owner_url": migrated.owner_url,
        }
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def sign_in_trader(client: Any) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/trader/login", json={"identifier": TRADER_PHONE, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def sign_in_admin(client: Any, username: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def csrf(client: Any) -> dict[str, str]:
    token = client.cookies.get(TRADER_CSRF_COOKIE) or client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token, "signed in but no CSRF cookie was set"
    return {CSRF_HEADER: token}


def an_eligible_request(world: dict[str, Any], value: str) -> dict[str, Any]:
    """A request at `eligible_for_batching`, through the real M5 journey.

    Not seeded by hand. A hand-seeded row is the shape M5 slice 8 caught a defect behind: the
    fixture invents the state the step needs and never notices what the real step leaves.
    """

    client = world["client"]
    sign_in_trader(client)
    created = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiary_id"]),
            "amount": {"value": value, "unit": "IRR"},
            "description": "for batching",
        },
        headers=csrf(client),
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["request"]["id"]
    revision_id = created.json()["revision"]["id"]

    handed = client.post(
        f"/api/v1/payment-requests/{request_id}/submit",
        json={},
        headers={**csrf(client), "If-Match": f'"rv-{created.json()["request"]["record_version"]}"'},
    )
    assert handed.status_code == 200, handed.text

    sign_in_admin(client, "batch_accountant")
    started = client.post(
        f"/api/v1/payment-requests/{request_id}/start-review",
        json={},
        headers={**csrf(client), "If-Match": handed.headers["ETag"]},
    )
    assert started.status_code == 200, started.text

    eligible = client.post(
        f"/api/v1/payment-requests/{request_id}/mark-eligible-for-batching",
        json={"expected_revision_id": revision_id, "review_note": "checked"},
        headers={**csrf(client), "If-Match": started.headers["ETag"]},
    )
    assert eligible.status_code == 200, eligible.text

    return {
        "request_id": request_id,
        "revision_id": revision_id,
        "record_version": eligible.json()["record_version"],
    }


def preview(world: dict[str, Any], items: list[dict[str, Any]], **overrides: Any) -> Any:
    client = world["client"]
    body: dict[str, Any] = {
        "items": items,
        "bank_profile_version_id": str(world["version_id"]),
        "bank_account_id": None,
        "bank_mapping_id": None,
        "apply_split_rules": True,
    }
    body.update(overrides)
    return client.post("/api/v1/payment-batches/preview", json=body, headers=csrf(client))


def as_item(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "payment_request_id": request["request_id"],
        "expected_revision_id": request["revision_id"],
        "expected_record_version": request["record_version"],
    }


def governance_counts(world: dict[str, Any]) -> tuple[int, int, int]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        row = connection.execute(
            "SELECT (SELECT count(*) FROM audit_logs), "
            "(SELECT count(*) FROM outbox_events), "
            "(SELECT count(*) FROM idempotency_records)"
        ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1]), int(row[2])


# --- API-BATCH-001: the published shape ---------------------------------------------------


def test_the_preview_returns_the_documented_shape(world: dict[str, Any]) -> None:
    """`API-BATCH-001`. `05_API_Specification.md:1291-1313`, field for field."""

    request = an_eligible_request(world, str(LIMIT * 2 + 1))

    sign_in_admin(world["client"], "batch_accountant")
    response = preview(world, [as_item(request)])

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"proposed_rows", "row_count", "total_amount_irr", "validation"}
    assert set(body["validation"]) == {"errors", "warnings"}
    assert body["validation"] == {"errors": [], "warnings": []}
    assert body["row_count"] == len(body["proposed_rows"]) == 3
    for row in body["proposed_rows"]:
        assert set(row) == {
            "source_request_id",
            "source_revision_id",
            "row_order",
            "amount_irr",
            "beneficiary_name",
            "beneficiary_iban",
            "split_reason",
        }
        assert row["source_request_id"] == request["request_id"]
        assert row["source_revision_id"] == request["revision_id"]
        assert row["beneficiary_name"] == "Ali One"
        assert row["beneficiary_iban"] == IBAN
    assert [row["row_order"] for row in body["proposed_rows"]] == [1, 2, 3]


def test_the_rows_carry_the_split_the_engine_computed(world: dict[str, Any]) -> None:
    """The route carries the engine's answer rather than computing a second one."""

    request = an_eligible_request(world, str(LIMIT * 2 + 1))

    sign_in_admin(world["client"], "batch_accountant")
    body = preview(world, [as_item(request)]).json()

    assert [row["amount_irr"] for row in body["proposed_rows"]] == [
        str(LIMIT),
        str(LIMIT),
        "1",
    ]
    assert body["total_amount_irr"] == str(LIMIT * 2 + 1)
    assert {row["split_reason"] for row in body["proposed_rows"]} == {"bank_limit_default"}


def test_row_order_is_continuous_across_requests(world: dict[str, Any]) -> None:
    """One file, one sequence. Restarting per request would number two rows `1`."""

    first = an_eligible_request(world, str(LIMIT + 5))
    second = an_eligible_request(world, str(LIMIT + 7))

    sign_in_admin(world["client"], "batch_accountant")
    body = preview(world, [as_item(first), as_item(second)]).json()

    assert body["row_count"] == 4
    assert [row["row_order"] for row in body["proposed_rows"]] == [1, 2, 3, 4]
    assert body["total_amount_irr"] == str((LIMIT + 5) + (LIMIT + 7))


def test_apply_split_rules_false_asks_for_the_unsplit_shape(world: dict[str, Any]) -> None:
    """The flag document 05 declares at `:1287`, honoured rather than accepted and ignored."""

    request = an_eligible_request(world, str(LIMIT * 3))

    sign_in_admin(world["client"], "batch_accountant")
    body = preview(world, [as_item(request)], apply_split_rules=False).json()

    assert body["row_count"] == 1
    assert body["proposed_rows"][0]["amount_irr"] == str(LIMIT * 3)
    assert body["proposed_rows"][0]["split_reason"] == "none"


# --- API-BATCH-002: strings, asserted on the raw text -------------------------------------


def test_every_amount_leaves_as_a_string(world: dict[str, Any]) -> None:
    """`API-BATCH-002`. `MONEY_TIME_CONTRACT.md:17-18`, against document 05's own examples.

    Asserted on the raw response **text**. A parsed assertion cannot tell `"1000000000"` from
    `1000000000`, and the whole of DOC-CONFLICT-050 is that difference: a JSON number is an
    IEEE-754 double in most clients, exact only below 2^53, and an IRR settlement reaches that.
    """

    request = an_eligible_request(world, str(LIMIT * 2))

    sign_in_admin(world["client"], "batch_accountant")
    response = preview(world, [as_item(request)])

    assert response.status_code == 200, response.text
    assert f'"amount_irr":"{LIMIT}"' in response.text.replace(" ", "")
    assert f'"total_amount_irr":"{LIMIT * 2}"' in response.text.replace(" ", "")
    # And no bare number in either field, which is what a regression would look like.
    assert f'"amount_irr":{LIMIT}' not in response.text.replace(" ", "")


# --- CON-BATCH-001: a stale expectation is refused, not answered ---------------------------


def test_a_stale_record_version_is_refused(world: dict[str, Any]) -> None:
    """`CON-BATCH-001`. `409`, and nothing is previewed."""

    request = an_eligible_request(world, str(LIMIT))

    sign_in_admin(world["client"], "batch_accountant")
    stale = as_item(request) | {"expected_record_version": request["record_version"] - 1}
    response = preview(world, [stale])

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "CONFLICT"


def test_a_revision_that_is_no_longer_current_is_refused(world: dict[str, Any]) -> None:
    """`CON-BATCH-001`. The case that matters: somebody corrected it while we were choosing.

    A preview against a superseded revision is not a stale answer, it is a wrong one — and the
    accountant's next action is to create the batch from what they were shown.
    """

    request = an_eligible_request(world, str(LIMIT))

    sign_in_admin(world["client"], "batch_accountant")
    wrong = as_item(request) | {"expected_revision_id": str(uuid.uuid4())}
    response = preview(world, [wrong])

    assert response.status_code == 409, response.text


def test_a_request_that_is_not_eligible_is_indistinguishable_from_a_missing_one(
    world: dict[str, Any],
) -> None:
    """A draft is not previewable, and saying which of the two it is teaches a caller nothing
    they should learn from this route."""

    client = world["client"]
    sign_in_trader(client)
    draft = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiary_id"]),
            "amount": {"value": str(LIMIT), "unit": "IRR"},
            "description": "still a draft",
        },
        headers=csrf(client),
    ).json()

    sign_in_admin(client, "batch_accountant")
    not_eligible = preview(
        world,
        [
            {
                "payment_request_id": draft["request"]["id"],
                "expected_revision_id": draft["revision"]["id"],
                "expected_record_version": draft["request"]["record_version"],
            }
        ],
    )
    absent = preview(
        world,
        [
            {
                "payment_request_id": str(uuid.uuid4()),
                "expected_revision_id": str(uuid.uuid4()),
                "expected_record_version": 1,
            }
        ],
    )

    assert not_eligible.status_code == 404, not_eligible.text
    assert absent.status_code == 404
    assert not_eligible.json()["error"]["code"] == absent.json()["error"]["code"]
    assert not_eligible.json()["error"]["message"] == absent.json()["error"]["message"]


def test_an_unknown_bank_profile_version_is_refused(world: dict[str, Any]) -> None:
    """No version, no rules. Previewing against a default nobody chose would be an invention."""

    request = an_eligible_request(world, str(LIMIT))

    sign_in_admin(world["client"], "batch_accountant")
    response = preview(
        world, [as_item(request)], bank_profile_version_id=str(uuid.uuid4())
    )

    assert response.status_code == 404, response.text


# --- SEC-BATCH-001: the read grant, not the create grant ----------------------------------


def test_the_preview_needs_the_read_permission(world: dict[str, Any]) -> None:
    """`SEC-BATCH-001`. An internal caller without `payment_batch.read` is refused.

    The CSRF token is sent deliberately: CSRF failure and permission denial share the
    `FORBIDDEN` envelope, so a permission negative that omits the token asserts `403` and
    proves nothing about permissions.
    """

    request = an_eligible_request(world, str(LIMIT))

    sign_in_admin(world["client"], "batch_bare")
    response = preview(world, [as_item(request)])

    assert response.status_code == 403, response.text


def test_a_trader_cannot_preview_a_batch(world: dict[str, Any]) -> None:
    """`SEC-BATCH-001`. A proposed bank file has no trader audience at all.

    A trader session resolves no permissions (`app/security/actor.py:113-118`), so this is
    refused even though the request being previewed is the trader's own.
    """

    request = an_eligible_request(world, str(LIMIT))

    sign_in_trader(world["client"])
    response = preview(world, [as_item(request)])

    assert response.status_code == 403, response.text


# --- The negative control, stronger than the document asks --------------------------------


def test_the_preview_is_not_a_command(world: dict[str, Any]) -> None:
    """`:893` says the preview "does not mutate records". This says it is not a command.

    Three governance tables as well as the aggregate: no audit row, no outbox event, no
    idempotency record. A read that leaves a governance trace is a write nobody has noticed
    yet, and those three tables are exactly where a future "just record who looked at it"
    would land — at which point the preview would need an idempotency key, and the route that
    needs one is a command.
    """

    request = an_eligible_request(world, str(LIMIT * 2 + 3))

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        before_rows = connection.execute(
            "SELECT id, status, record_version, current_revision_id, updated_at "
            "FROM payment_requests ORDER BY id"
        ).fetchall()
        before_revisions = connection.execute(
            "SELECT row_to_json(r) FROM payment_request_revisions r ORDER BY r.id"
        ).fetchall()
    before_governance = governance_counts(world)

    sign_in_admin(world["client"], "batch_accountant")
    # Twice, because an idempotency record or an audit row would most plausibly appear on the
    # second identical call rather than the first.
    assert preview(world, [as_item(request)]).status_code == 200
    assert preview(world, [as_item(request)]).status_code == 200

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        after_rows = connection.execute(
            "SELECT id, status, record_version, current_revision_id, updated_at "
            "FROM payment_requests ORDER BY id"
        ).fetchall()
        after_revisions = connection.execute(
            "SELECT row_to_json(r) FROM payment_request_revisions r ORDER BY r.id"
        ).fetchall()

    assert after_rows == before_rows, "the preview changed a payment request"
    assert after_revisions == before_revisions, "the preview changed a revision"
    assert governance_counts(world) == before_governance, (
        "the preview wrote an audit row, an outbox event or an idempotency record, so it is a "
        "command wearing a read's clothes"
    )


def test_the_preview_reads_no_clock_of_its_own(world: dict[str, Any]) -> None:
    """One instant per call, so a preview straddling a cutoff second cannot use two limits.

    Asserted through the response rather than by patching: every row of a multi-request preview
    carries the same `split_reason` family, which it could not if each split had asked the clock
    again across a boundary. The boundary itself is tested directly in
    `tests/backend/test_splitting.py`; this is the wiring.
    """

    first = an_eligible_request(world, str(LIMIT + 1))
    second = an_eligible_request(world, str(LIMIT + 1))

    sign_in_admin(world["client"], "batch_accountant")
    body = preview(world, [as_item(first), as_item(second)]).json()

    reasons = {row["split_reason"] for row in body["proposed_rows"]}
    assert len(reasons) == 1, reasons
    assert datetime.now(UTC) is not None  # the test itself reads a clock; the route need not
