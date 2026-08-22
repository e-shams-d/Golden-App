"""The whole milestone, from an eligible request to a file somebody says they sent.

M7 slices 5B and 6B — the close-out.

**`TRACE-DOD-013` is a claim about queryable evidence, so it is asserted by querying.** The
Definition of Done asks that the system "prove exactly which approved immutable version produced
the exact checksummed file that an authorized accountant marked as sent to the bank". The test
therefore starts from **the sent export alone** — one id, nothing else remembered — and walks
backwards to the approval, the version, the items, and the request a trader filed. Every link is
recovered from the database rather than from a variable the test happened to keep.

**And the ambiguity that makes it worth testing:** the batch here has *two* approved versions and
two approvals, because one was replaced after being approved. Only one of them produced the file
that was sent. A chain that could not tell them apart would satisfy a single-version test and fail
the only question that matters after something goes wrong.

Covers: SVC-INVALIDATE-003, TRACE-INVALIDATE-001, TRACE-DOD-013.
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

TRADER_PHONE = "+989120004901"
IBAN = "IR060120000000000000000049"
LIMIT = 1_000_000_000
ONE_ROW = "900000000"
BENEFICIARY_NAME = "علی رضایی"

APPROVE_PURPOSE = "payment_batch_version.approve"
STEP_UP_RESOURCE_TYPE = "payment_batch_version"


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
        local_storage_root=tmp_path_factory.mktemp("journey-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="c" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    ids = {
        name: uuid.uuid4()
        for name in ("trader", "beneficiary", "profile", "version", "account", "mapping")
    }

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'Journey Trader', %s, 'active', 'approved')",
            (ids["trader"], TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (ids["trader"], TRADER_PHONE, encoded),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, %s, %s, %s, 'active', 'not_checked')",
            (ids["beneficiary"], ids["trader"], BENEFICIARY_NAME, IBAN, IBAN),
        )
        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'ayandeh', 'Bank Ayandeh', 'active')",
            (ids["profile"],),
        )
        connection.execute(
            "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, status, "
            "default_transfer_limit_irr, after_cutoff_transfer_limit_irr, cutoff_time, "
            "splitting_enabled, required_fields, rules, config_hash) "
            "VALUES (%s, %s, 1, 'active', %s, NULL, NULL, TRUE, '{}', '{}', %s)",
            (ids["version"], ids["profile"], LIMIT, "1" * 64),
        )
        connection.execute(
            "INSERT INTO bank_accounts (id, bank_profile_id, display_name, iban, "
            "normalized_iban, account_role, status) "
            "VALUES (%s, %s, 'Centre Account', %s, %s, 'outgoing_source', 'active')",
            (ids["account"], ids["profile"], IBAN, IBAN),
        )
        connection.execute(
            "INSERT INTO bank_mappings (id, bank_profile_version_id, file_type, "
            "template_version, status, mapping, config_hash) "
            "VALUES (%s, %s, 'outgoing_excel', 1, 'active', '{}', %s)",
            (ids["mapping"], ids["version"], "2" * 64),
        )
        for username, role in (
            ("journey_accountant", "accountant"),
            ("journey_manager", "manager"),
        ):
            connection.execute(
                "INSERT INTO admin_users (username, full_name, password_hash, status) "
                "VALUES (%s, %s, %s, 'active')",
                (username, username, encoded),
            )
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
            "owner_url": migrated.owner_url,
            **{f"{name}_id": value for name, value in ids.items()},
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


def rows(world: dict[str, Any], sql: str, *parameters: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        return connection.execute(sql, parameters).fetchall()


def an_eligible_request(world: dict[str, Any]) -> dict[str, Any]:
    client = world["client"]
    sign_in_trader(client)
    created = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiary_id"]),
            "amount": {"value": ONE_ROW, "unit": "IRR"},
            "description": "سفر کامل",
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

    sign_in_admin(client, "journey_accountant")
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
        "payment_request_id": request_id,
        "expected_revision_id": revision_id,
        "expected_record_version": eligible.json()["record_version"],
    }


def a_batch(world: dict[str, Any], selection: dict[str, Any]) -> Any:
    client = world["client"]
    return client.post(
        "/api/v1/payment-batches",
        json={
            "items": [selection],
            "bank_profile_version_id": str(world["version_id"]),
            "bank_account_id": str(world["account_id"]),
            "bank_mapping_id": str(world["mapping_id"]),
        },
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )


def finalize(world: dict[str, Any], batch_id: str, version_id: str, etag: str) -> Any:
    client = world["client"]
    return client.post(
        f"/api/v1/payment-batches/{batch_id}/versions/{version_id}/finalize",
        json={"note": "validated"},
        headers={**csrf(client), "If-Match": etag, "Idempotency-Key": str(uuid.uuid4())},
    )


def approve(world: dict[str, Any], batch_id: str, version_id: str, content_hash: str) -> Any:
    client = world["client"]
    sign_in_admin(client, "journey_manager")
    reference = client.post(
        "/api/v1/auth/reauthenticate",
        json={
            "password": PASSWORD,
            "purpose": APPROVE_PURPOSE,
            "resource_type": STEP_UP_RESOURCE_TYPE,
            "resource_id": version_id,
        },
        headers=csrf(client),
    )
    assert reference.status_code == 200, reference.text
    response = client.post(
        f"/api/v1/payment-batches/{batch_id}/versions/{version_id}/approve",
        json={"expected_content_hash": content_hash, "approval_note": "ok"},
        headers={
            **csrf(client),
            "Idempotency-Key": str(uuid.uuid4()),
            "X-Recent-Auth": str(reference.json()["recent_auth_reference"]),
        },
    )
    sign_in_admin(client, "journey_accountant")
    return response


def final_export(world: dict[str, Any], batch_id: str, version_id: str) -> Any:
    client = world["client"]
    return client.post(
        f"/api/v1/payment-batches/{batch_id}/versions/{version_id}/exports/final",
        json=None,
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )


def replace(world: dict[str, Any], batch_id: str, etag: str, selection: dict[str, Any]) -> Any:
    client = world["client"]
    return client.post(
        f"/api/v1/payment-batches/{batch_id}/versions",
        json={
            "items": [selection],
            "bank_profile_version_id": str(world["version_id"]),
            "bank_account_id": str(world["account_id"]),
            "bank_mapping_id": str(world["mapping_id"]),
            "reason": "the first version had to be redone",
        },
        headers={**csrf(client), "If-Match": etag, "Idempotency-Key": str(uuid.uuid4())},
    )


def current_selection(world: dict[str, Any], request_id: str) -> dict[str, Any]:
    """Re-read the request, because batching moved its record version."""

    found = rows(
        world,
        "SELECT current_revision_id, record_version FROM payment_requests WHERE id = %s",
        request_id,
    )
    return {
        "payment_request_id": request_id,
        "expected_revision_id": str(found[0][0]),
        "expected_record_version": found[0][1],
    }


def test_a_replacement_voids_the_final_export_of_the_version_it_replaces(
    world: dict[str, Any],
) -> None:
    """`SVC-INVALIDATE-003`. Voided, not deleted.

    The export row is the evidence that a particular file was produced. Deleting it would erase
    the answer to "what did we generate" at the exact moment the question becomes hardest — after
    somebody replaced the version it came from.

    `voided` is outside `uq_active_final_export_per_version`'s predicate, so the version is free
    for a later export without any row being removed. That predicate was written in slice 2 with
    this case in it, and this is the first thing to use it.
    """

    selection = an_eligible_request(world)
    batch = a_batch(world, selection)
    assert batch.status_code == 201, batch.text
    batch_id = batch.json()["batch"]["id"]
    first_version = batch.json()["current_version"]["id"]

    frozen = finalize(world, batch_id, first_version, batch.headers["ETag"])
    assert frozen.status_code == 200, frozen.text
    approved = approve(
        world, batch_id, first_version, frozen.json()["version"]["content_hash"]
    )
    assert approved.status_code == 200, approved.text

    exported = final_export(world, batch_id, first_version)
    assert exported.status_code == 201, exported.text
    export_id = exported.json()["id"]

    replaced = replace(
        world,
        batch_id,
        f'"rv-{approved.json()["batch"]["record_version"]}"',
        current_selection(world, selection["payment_request_id"]),
    )
    assert replaced.status_code == 201, replaced.text

    assert rows(
        world, "SELECT status FROM bank_excel_exports WHERE id = %s", export_id
    ) == [("voided",)], "the export of the replaced version is not voided"

    # And the row is still there, with its file and its digests intact.
    survived = rows(
        world,
        "SELECT file_id IS NOT NULL, file_sha256_hash IS NOT NULL, batch_approval_id IS NOT NULL "
        "FROM bank_excel_exports WHERE id = %s",
        export_id,
    )
    assert survived == [(True, True, True)], survived

    audited = rows(
        world,
        "SELECT previous_values->>'voided_exports' FROM audit_logs "
        "WHERE action = 'payment_batch_version.created' ORDER BY occurred_at DESC LIMIT 1",
    )
    assert audited and exported.json()["export_number"] in str(audited[0][0]), audited


def test_a_superseded_versions_approval_cannot_produce_a_final_export(
    world: dict[str, Any],
) -> None:
    """`SVC-INVALIDATE-003`'s other half, and the negative control the plan names.

    The approval row is untouched — §11.7 forbids updating it and no grant permits it — so an
    implementation that asked only "is there an approval?" would happily generate a second file
    for a version nobody may pay from. What refuses it is the version's own status.
    """

    selection = an_eligible_request(world)
    batch = a_batch(world, selection)
    assert batch.status_code == 201, batch.text
    batch_id = batch.json()["batch"]["id"]
    first_version = batch.json()["current_version"]["id"]

    frozen = finalize(world, batch_id, first_version, batch.headers["ETag"])
    approved = approve(
        world, batch_id, first_version, frozen.json()["version"]["content_hash"]
    )
    assert approved.status_code == 200, approved.text

    replaced = replace(
        world,
        batch_id,
        f'"rv-{approved.json()["batch"]["record_version"]}"',
        current_selection(world, selection["payment_request_id"]),
    )
    assert replaced.status_code == 201, replaced.text

    # The approval is still there, exactly as the manager left it.
    assert rows(
        world,
        "SELECT decision FROM batch_approvals WHERE payment_batch_version_id = %s",
        first_version,
    ) == [("approved",)]

    refused = final_export(world, batch_id, first_version)
    assert refused.status_code == 400, refused.text
    assert "no longer operational" in refused.json()["error"]["message"]


def test_the_whole_chain_is_recoverable_from_the_sent_export_alone(
    world: dict[str, Any],
) -> None:
    """`TRACE-DOD-013` and `TRACE-INVALIDATE-001`. The milestone's Definition of Done.

    The batch reaches a sent file the hard way: approved, exported, **replaced**, approved again,
    exported again, sent. Two versions, two approvals, two exports, and only one of each produced
    the file that went to the bank.

    Then everything is forgotten except one export id, and the chain is walked backwards in a
    single query. That is what "the system can prove exactly which approved immutable version
    produced the exact checksummed file" means: not that the values match — they matched at every
    step — but that a reader starting from the file can *find* them.
    """

    selection = an_eligible_request(world)
    batch = a_batch(world, selection)
    assert batch.status_code == 201, batch.text
    batch_id = batch.json()["batch"]["id"]
    first_version = batch.json()["current_version"]["id"]

    frozen = finalize(world, batch_id, first_version, batch.headers["ETag"])
    approved_once = approve(
        world, batch_id, first_version, frozen.json()["version"]["content_hash"]
    )
    assert approved_once.status_code == 200, approved_once.text
    first_export = final_export(world, batch_id, first_version)
    assert first_export.status_code == 201, first_export.text

    replaced = replace(
        world,
        batch_id,
        f'"rv-{approved_once.json()["batch"]["record_version"]}"',
        current_selection(world, selection["payment_request_id"]),
    )
    assert replaced.status_code == 201, replaced.text
    second_version = replaced.json()["current_version"]["id"]

    refrozen = finalize(world, batch_id, second_version, replaced.headers["ETag"])
    assert refrozen.status_code == 200, refrozen.text
    approved_twice = approve(
        world, batch_id, second_version, refrozen.json()["version"]["content_hash"]
    )
    assert approved_twice.status_code == 200, approved_twice.text

    second_export = final_export(world, batch_id, second_version)
    assert second_export.status_code == 201, second_export.text

    client = world["client"]
    downloaded = client.get(f"/api/v1/bank-exports/{second_export.json()['id']}/download")
    assert downloaded.status_code == 200, downloaded.text
    sent = client.post(
        f"/api/v1/bank-exports/{second_export.json()['id']}/mark-sent-to-bank",
        json={
            "sent_at": datetime.now(UTC).isoformat(),
            "submission_channel": "bank_portal_manual_upload",
            "note": "Uploaded to the portal.",
        },
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert sent.status_code == 200, sent.text

    # Everything above is now forgotten. This is the only thing carried forward.
    sent_export_id = second_export.json()["id"]

    chain = rows(
        world,
        "SELECT e.export_number, e.file_sha256_hash, e.content_hash, "
        "       a.id, a.decision, a.approved_content_hash, a.decided_by_admin_user_id, "
        "       v.id, v.version_number, v.content_hash, v.status, "
        "       f.id, f.sha256_hash, "
        "       e.sent_to_bank_marked_by_admin_user_id, e.sent_to_bank_marked_at "
        "FROM bank_excel_exports e "
        "JOIN batch_approvals a ON a.id = e.batch_approval_id "
        "JOIN payment_batch_versions v ON v.id = e.payment_batch_version_id "
        "JOIN file_objects f ON f.id = e.file_id "
        "WHERE e.id = %s",
        sent_export_id,
    )
    assert len(chain) == 1, "the chain does not resolve from the sent export"
    (
        _number, file_hash, export_hash,
        approval_id, decision, approved_hash, decided_by,
        version_id, version_number, version_hash, version_status,
        _file_id, stored_hash,
        sent_by, sent_at,
    ) = chain[0]

    # version -> approval: the manager approved this exact content.
    assert decision == "approved"
    assert approved_hash == version_hash
    # approval -> file: the file renders that content, and the bytes are what was recorded.
    assert export_hash == version_hash
    assert file_hash == stored_hash
    # the accountant who said they sent it, and when.
    assert sent_by is not None and sent_at is not None
    assert sent_by != decided_by, "the approver and the sender must be distinguishable"

    # `TRACE-INVALIDATE-001`: two approvals exist for this batch and only one produced this file.
    approvals = rows(
        world,
        "SELECT a.id FROM batch_approvals a JOIN payment_batch_versions v "
        "ON v.id = a.payment_batch_version_id WHERE v.payment_batch_id = %s",
        batch_id,
    )
    assert len(approvals) == 2, f"the journey should have produced two approvals: {approvals}"
    assert str(approval_id) in {str(found[0]) for found in approvals}
    assert version_id is not None and str(version_id) == second_version
    assert version_number == 2
    assert version_status == "approved"

    # And the first export is voided, so nothing could confuse the two files.
    assert rows(
        world, "SELECT status FROM bank_excel_exports WHERE id = %s", first_export.json()["id"]
    ) == [("voided",)]

    # The trader's original request is reachable from the same file, through the items.
    origin = rows(
        world,
        "SELECT DISTINCT r.id FROM bank_excel_exports e "
        "JOIN payment_batch_items i ON i.payment_batch_version_id = e.payment_batch_version_id "
        "JOIN payment_attempts t ON t.id = i.payment_attempt_id "
        "JOIN payment_requests r ON r.id = t.payment_request_id "
        "WHERE e.id = %s",
        sent_export_id,
    )
    assert [str(found[0]) for found in origin] == [selection["payment_request_id"]]
