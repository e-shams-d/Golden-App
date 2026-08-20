"""The two reads: what a batch looks like to somebody who did not create it.

M6 slice 2. Shipped in the same pull request as the create, because five times in M3 and once in
M5 a complete, tested mechanism arrived with nothing able to read what it wrote — and a container
nothing can read is a container nobody can act on.

Three things worth stating about the shape, all of them omissions:

**No ownership scope.** A batch has no trader. It is a file the centre sends to a bank and its
rows belong to many traders at once, so `owned_or_permitted` would have nothing to scope on and
`scoped()` — which takes the actor precisely so a route cannot invent a filter — has no column to
take. The guard is the permission, and the negative below is a role holding neither batch grant.

**No `exports`, no `approval_summary`, no `result_progress`.** `05_API_Specification.md:1350` asks
the detail read for all three. M6 cannot reach any of them: approval is M7, export is M7, results
are M8. They are absent rather than returned empty, because `exports: []` reads as "this batch has
no exports" when the truth is "this deployment cannot have any", and a screen renders the first as
a fact.

**`active_allocation_count` is not in document 05 and is added deliberately.** It is the only way
a reader can see the invariant holding — it must equal `row_count` while every row owns its
allocation — and slice 3's finalization refuses to proceed when it does not.

Covers: API-BATCH-003, SEC-BATCH-002.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
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

TRADER_PHONE = "+989120003001"
IBAN = "IR060120000000000000000043"

LIMIT = 1_000_000_000
SPLITS_INTO_TWO = "1500000000"


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
    account_id = uuid.uuid4()
    mapping_id = uuid.uuid4()

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'Read Trader', %s, 'active', 'approved')",
            (trader_id, TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (trader_id, TRADER_PHONE, encoded),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'Ali Three', %s, %s, 'active', "
            "'not_checked')",
            (beneficiary_id, trader_id, IBAN, IBAN),
        )
        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'pasargad', 'Bank Pasargad', 'active')",
            (profile_id,),
        )
        connection.execute(
            "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, status, "
            "default_transfer_limit_irr, after_cutoff_transfer_limit_irr, cutoff_time, "
            "splitting_enabled, required_fields, rules, config_hash) "
            "VALUES (%s, %s, 1, 'active', %s, NULL, NULL, TRUE, '{}', '{}', %s)",
            (version_id, profile_id, LIMIT, "e" * 64),
        )
        connection.execute(
            "INSERT INTO bank_accounts (id, bank_profile_id, display_name, iban, "
            "normalized_iban, account_role, status) "
            "VALUES (%s, %s, 'Centre Account', %s, %s, 'outgoing_source', 'active')",
            (account_id, profile_id, IBAN, IBAN),
        )
        connection.execute(
            "INSERT INTO bank_mappings (id, bank_profile_version_id, file_type, "
            "template_version, status, mapping, config_hash) "
            "VALUES (%s, %s, 'outgoing_excel', 1, 'active', '{}', %s)",
            (mapping_id, version_id, "f" * 64),
        )
        for username, role in (
            ("read_accountant", "accountant"),
            # Holds `payment_batch.read` and not `.create`, which is what makes it the right
            # signer for the reads: if the reads had been guarded by the create grant, this role
            # would be refused and the split would be wrong in the direction that hides a batch
            # from somebody entitled to see it.
            ("read_business_admin", "business_admin"),
            ("read_bare", None),
        ):
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
            "beneficiary_id": beneficiary_id,
            "version_id": version_id,
            "account_id": account_id,
            "mapping_id": mapping_id,
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


def a_batch(world: dict[str, Any], value: str = SPLITS_INTO_TWO) -> dict[str, Any]:
    """One batch, made through the real create route."""

    client = world["client"]
    sign_in_trader(client)
    created = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiary_id"]),
            "amount": {"value": value, "unit": "IRR"},
            "description": "to be read",
        },
        headers=csrf(client),
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["request"]["id"]
    revision_id = created.json()["revision"]["id"]

    handed = client.post(
        f"/api/v1/payment-requests/{request_id}/submit",
        json={},
        headers={
            **csrf(client),
            "If-Match": f'"rv-{created.json()["request"]["record_version"]}"',
        },
    )
    assert handed.status_code == 200, handed.text

    sign_in_admin(client, "read_accountant")
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

    response = client.post(
        "/api/v1/payment-batches",
        json={
            "items": [
                {
                    "payment_request_id": request_id,
                    "expected_revision_id": revision_id,
                    "expected_record_version": eligible.json()["record_version"],
                }
            ],
            "bank_profile_version_id": str(world["version_id"]),
            "bank_account_id": str(world["account_id"]),
            "bank_mapping_id": str(world["mapping_id"]),
        },
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_the_detail_read_answers_with_the_version_its_rows_and_the_allocation_count(
    world: dict[str, Any],
) -> None:
    """`API-BATCH-003`. Every monetary field a string, and the invariant visible."""

    created = a_batch(world)
    sign_in_admin(world["client"], "read_business_admin")

    response = world["client"].get(f"/api/v1/payment-batches/{created['batch']['id']}")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["batch"]["batch_number"] == created["batch"]["batch_number"]
    assert body["batch"]["status"] == "draft"
    assert body["current_version"]["id"] == created["current_version"]["id"]
    assert body["current_version"]["row_count"] == 2
    assert body["historical_versions"] == [], (
        "a batch with one version has no history; a non-empty list here would mean the current "
        "version appears twice"
    )

    assert [item["row_order"] for item in body["items"]] == [1, 2]
    assert [item["amount_irr"] for item in body["items"]] == [str(LIMIT), "500000000"]
    assert body["active_allocation_count"] == body["current_version"]["row_count"], (
        "a row does not own its allocation, which is exactly what slice 3's finalization "
        "refuses to proceed on"
    )

    # `MONEY_TIME_CONTRACT.md:17-18` on the raw text, not the parsed body: a parsed assertion
    # cannot tell `"1000000000"` from `1000000000`, which is the whole of the claim.
    assert '"amount_irr":"1000000000"' in response.text.replace(" ", "")
    assert '"total_amount_irr":"1500000000"' in response.text.replace(" ", "")

    # The three fields document 05 asks for and M6 cannot answer. Absent, not empty.
    for absent in ("exports", "approval_summary", "result_progress"):
        assert absent not in body, (
            f"the detail read returns {absent!r}, and M6 can put nothing true in it — an empty "
            "value here reads as a fact about the batch rather than about the milestone"
        )

    assert response.headers["ETag"] == f'"rv-{body["batch"]["record_version"]}"'


def test_the_list_holds_every_batch_newest_first(world: dict[str, Any]) -> None:
    """Enough to choose a batch, and ordered so the newest is the first thing read."""

    first = a_batch(world)
    second = a_batch(world, "700000000")

    sign_in_admin(world["client"], "read_business_admin")
    response = world["client"].get("/api/v1/payment-batches")
    assert response.status_code == 200, response.text

    numbers = [entry["batch_number"] for entry in response.json()["batches"]]
    assert first["batch"]["batch_number"] in numbers
    assert second["batch"]["batch_number"] in numbers
    assert numbers.index(second["batch"]["batch_number"]) < numbers.index(
        first["batch"]["batch_number"]
    ), "the list is not newest-first"

    entry = next(
        item
        for item in response.json()["batches"]
        if item["batch_number"] == second["batch"]["batch_number"]
    )
    assert entry["row_count"] == 1
    assert entry["total_amount_irr"] == "700000000"


def test_reading_one_batch_needs_the_read_permission(world: dict[str, Any]) -> None:
    """`SEC-BATCH-002` on the detail read.

    A trader is refused too, and that is the more interesting half: a trader holds no permission
    at all, and a batch is not theirs to see even though some of its rows came from their
    requests. `permission_catalog.yaml:459` gives `payment_batch.read` to no trader role, so the
    refusal is deny-by-default rather than a rule written here.
    """

    created = a_batch(world)
    path = f"/api/v1/payment-batches/{created['batch']['id']}"

    sign_in_admin(world["client"], "read_bare")
    assert world["client"].get(path).status_code == 403

    sign_in_trader(world["client"])
    assert world["client"].get(path).status_code == 403


def test_listing_batches_needs_the_read_permission(world: dict[str, Any]) -> None:
    """`SEC-BATCH-002` on the list. Same two refusals, because a list leaks more than a detail.

    A detail read refused with 403 tells the caller an id exists. A list refused with 403 tells
    them nothing, which is why the list is the one worth checking separately: an unguarded list
    would hand every batch in the system to any authenticated caller in a single call.
    """

    a_batch(world)

    sign_in_admin(world["client"], "read_bare")
    assert world["client"].get("/api/v1/payment-batches").status_code == 403

    sign_in_trader(world["client"])
    assert world["client"].get("/api/v1/payment-batches").status_code == 403


def test_a_missing_batch_is_a_404_and_not_a_500(world: dict[str, Any]) -> None:
    """An unknown id, from a caller who is allowed to ask."""

    sign_in_admin(world["client"], "read_business_admin")
    response = world["client"].get(f"/api/v1/payment-batches/{uuid.uuid4()}")
    assert response.status_code == 404, response.text
