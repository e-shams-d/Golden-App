"""Downloading the file, and a human saying they sent it.

M7 slice 4, against a real PostgreSQL and real storage.

**`15_Agent_Implementation_Plan.md:989`: "Downloading does not mean sent."** That sentence is the
milestone's central human-factors risk and it shapes this whole file. An accountant who downloads
a bank file, uploads it to a portal and forgets to come back leaves the system believing the
payment was never made — and the next reconciliation cycle chases a payment that already
happened. Nothing here can prevent that; what it can do is make the gap visible, which is
`SVC-SENT-002`.

**Revalidation is asserted by corrupting the file between two downloads**, because that is the
only way to tell "validated once at generation" from "revalidated before every download". The
first download succeeds, the bytes are edited on disk, and the second must refuse and quarantine.

Covers: SEC-DOWNLOAD-001, SVC-INTEGRITY-003, SVC-SENT-001, SVC-SENT-002, CON-SENT-001,
AUD-SENT-001.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
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

TRADER_PHONE = "+989120004801"
IBAN = "IR060120000000000000000048"
LIMIT = 1_000_000_000
ONE_ROW = "900000000"

APPROVE_PURPOSE = "payment_batch_version.approve"
STEP_UP_RESOURCE_TYPE = "payment_batch_version"

CHANNEL = "bank_portal_manual_upload"


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

    storage_root = tmp_path_factory.mktemp("sent-storage")
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=migrated.owner_url,
        redis_url="redis://127.0.0.1:6379/0",
        local_storage_root=storage_root,
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
            "approval_status) VALUES (%s, 'Sent Trader', %s, 'active', 'approved')",
            (ids["trader"], TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (ids["trader"], TRADER_PHONE, encoded),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'علی رضایی', %s, %s, 'active', "
            "'not_checked')",
            (ids["beneficiary"], ids["trader"], IBAN, IBAN),
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
            ("sent_accountant", "accountant"),
            # Holds `bank_export.read` and neither `download` nor `mark_sent`
            # (`permission_catalog.yaml:495-505`), which is what makes the two permission
            # negatives prove the routes want *those* grants rather than merely some export grant.
            ("sent_manager", "manager"),
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
            "app_role": migrated.app_role,
            "owner_url": migrated.owner_url,
            "storage_root": storage_root,
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


def a_final_export(world: dict[str, Any]) -> dict[str, Any]:
    """One request, batched, finalized, approved, exported. The whole chain, through the routes."""

    client = world["client"]
    sign_in_trader(client)
    created = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiary_id"]),
            "amount": {"value": ONE_ROW, "unit": "IRR"},
            "description": "برای ارسال",
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

    sign_in_admin(client, "sent_accountant")
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

    batch = client.post(
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
    assert batch.status_code == 201, batch.text
    batch_id = batch.json()["batch"]["id"]
    version_id = batch.json()["current_version"]["id"]

    frozen = client.post(
        f"/api/v1/payment-batches/{batch_id}/versions/{version_id}/finalize",
        json={"note": "validated"},
        headers={
            **csrf(client),
            "If-Match": batch.headers["ETag"],
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert frozen.status_code == 200, frozen.text

    sign_in_admin(client, "sent_manager")
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
    approved = client.post(
        f"/api/v1/payment-batches/{batch_id}/versions/{version_id}/approve",
        json={
            "expected_content_hash": frozen.json()["version"]["content_hash"],
            "approval_note": "ok",
        },
        headers={
            **csrf(client),
            "Idempotency-Key": str(uuid.uuid4()),
            "X-Recent-Auth": str(reference.json()["recent_auth_reference"]),
        },
    )
    assert approved.status_code == 200, approved.text

    sign_in_admin(client, "sent_accountant")
    exported = client.post(
        f"/api/v1/payment-batches/{batch_id}/versions/{version_id}/exports/final",
        json=None,
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert exported.status_code == 201, exported.text

    return {
        "batch_id": batch_id,
        "version_id": version_id,
        "export_id": exported.json()["id"],
        "file_id": exported.json()["file_id"],
    }


def download(world: dict[str, Any], export_id: str) -> Any:
    return world["client"].get(f"/api/v1/bank-exports/{export_id}/download")


def mark_sent(world: dict[str, Any], export_id: str, *, key: str | None = None) -> Any:
    client = world["client"]
    return client.post(
        f"/api/v1/bank-exports/{export_id}/mark-sent-to-bank",
        json={
            "sent_at": datetime.now(UTC).isoformat(),
            "submission_channel": CHANNEL,
            "note": "Uploaded manually to the bank portal.",
        },
        headers={**csrf(client), "Idempotency-Key": key or str(uuid.uuid4())},
    )


def stored_path(world: dict[str, Any], file_id: str) -> Path:
    key = rows(world, "SELECT storage_key FROM file_objects WHERE id = %s", file_id)[0][0]
    return Path(world["storage_root"]) / str(key)


def test_a_download_streams_the_file_and_records_that_it_happened(
    world: dict[str, Any],
) -> None:
    """`SEC-DOWNLOAD-001`'s happy half, and the timestamp `SVC-SENT-002` needs.

    `downloaded_at` is not a lifecycle step for its own sake — it exists so that "who has a copy
    of this and has not told us they sent it" is answerable at all.
    """

    target = a_final_export(world)
    sign_in_admin(world["client"], "sent_accountant")

    response = download(world, target["export_id"])
    assert response.status_code == 200, response.text
    assert response.content[:2] == b"PK", "an xlsx is a zip; this is not one"
    assert "attachment" in response.headers["content-disposition"]

    state = rows(
        world,
        "SELECT status, downloaded_at IS NOT NULL, sent_to_bank_marked_at "
        "FROM bank_excel_exports WHERE id = %s",
        target["export_id"],
    )
    assert state == [("downloaded", True, None)], state


def test_a_downloaded_but_unsent_export_says_so(world: dict[str, Any]) -> None:
    """`SVC-SENT-002`. The gap between downloading and sending is visible, not inferred.

    §2.5 of the M7 plan: an export that is downloaded and unsent must be *visibly* unsent in the
    read model rather than merely lacking a timestamp. A screen cannot show what the response does
    not say, and asking a UI to interpret `sent_to_bank_marked_at === null` is how the reminder
    gets left out.
    """

    target = a_final_export(world)
    client = world["client"]
    sign_in_admin(client, "sent_accountant")

    before = client.get(f"/api/v1/bank-exports/{target['export_id']}")
    assert before.status_code == 200, before.text
    assert before.json()["awaiting_send_confirmation"] is False, (
        "nothing to confirm before anybody has a copy"
    )

    assert download(world, target["export_id"]).status_code == 200

    after = client.get(f"/api/v1/bank-exports/{target['export_id']}")
    assert after.status_code == 200, after.text
    assert after.json()["awaiting_send_confirmation"] is True
    assert after.json()["sent_to_bank_marked_at"] is None

    assert mark_sent(world, target["export_id"]).status_code == 200

    settled = client.get(f"/api/v1/bank-exports/{target['export_id']}")
    assert settled.json()["awaiting_send_confirmation"] is False
    assert settled.json()["sent_to_bank_marked_at"] is not None


def test_integrity_is_revalidated_before_every_download(world: dict[str, Any]) -> None:
    """`SVC-INTEGRITY-003`. The word in `:1514` is "every".

    The first download succeeds. The bytes on disk are then edited — which is exactly the failure
    a checksum exists to detect and the only one that generation-time validation cannot — and the
    second download must refuse and quarantine.

    Validating once at generation would pass this test's first half and fail its second, which is
    why the second half is here.
    """

    target = a_final_export(world)
    sign_in_admin(world["client"], "sent_accountant")

    assert download(world, target["export_id"]).status_code == 200

    path = stored_path(world, target["file_id"])
    path.write_bytes(path.read_bytes() + b"tampered")

    second = download(world, target["export_id"])
    assert second.status_code == 409, second.text
    assert "file_checksum_matches_stored_checksum" in second.json()["error"]["message"]

    assert rows(
        world, "SELECT status FROM bank_excel_exports WHERE id = %s", target["export_id"]
    ) == [("quarantined",)]


def test_a_quarantined_export_cannot_be_downloaded_or_marked_sent(
    world: dict[str, Any],
) -> None:
    """`SEC-DOWNLOAD-001`. A quarantined export is evidence, not a deliverable.

    Whatever is wrong with it must not reach a bank while somebody works out what happened — and
    it must not be recordable as sent either, because that would assert a payment was made from a
    file the system does not trust.
    """

    target = a_final_export(world)
    sign_in_admin(world["client"], "sent_accountant")
    assert download(world, target["export_id"]).status_code == 200

    path = stored_path(world, target["file_id"])
    path.write_bytes(b"not a spreadsheet at all")
    assert download(world, target["export_id"]).status_code == 409

    assert download(world, target["export_id"]).status_code == 409
    assert mark_sent(world, target["export_id"]).status_code in (400, 409)


def test_marking_sent_records_all_seven_things_the_document_lists(
    world: dict[str, Any],
) -> None:
    """`SVC-SENT-001` and `AUD-SENT-001`. `15_Agent_Implementation_Plan.md:978-987`.

    Export id, batch and version, actor, sent timestamp, submission channel, note, and the
    integrity state. **Two of them have no column** — §11.8 gives the table neither
    `submission_channel` nor `note` — so they are in the audit row, which is append-only and
    which the runtime cannot rewrite. Inventing two columns document 04 does not define would be
    schema drift in the one milestone where the schema is the evidence.
    """

    target = a_final_export(world)
    sign_in_admin(world["client"], "sent_accountant")
    assert download(world, target["export_id"]).status_code == 200

    response = mark_sent(world, target["export_id"])
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "sent_to_bank_marked"

    stored = rows(
        world,
        "SELECT status, sent_to_bank_marked_at IS NOT NULL, "
        "sent_to_bank_marked_by_admin_user_id IS NOT NULL "
        "FROM bank_excel_exports WHERE id = %s",
        target["export_id"],
    )
    assert stored == [("sent_to_bank_marked", True, True)], stored

    audited = rows(
        world,
        "SELECT new_values->>'payment_batch_id', new_values->>'payment_batch_version_id', "
        "new_values->>'submission_channel', new_values->>'file_sha256_hash', reason "
        "FROM audit_logs WHERE action = 'bank_export.sent_marked' AND entity_id = %s",
        target["export_id"],
    )
    assert len(audited) == 1, audited
    batch_id, version_id, channel, checksum, note = audited[0]
    assert batch_id == target["batch_id"]
    assert version_id == target["version_id"]
    assert channel == CHANNEL
    assert checksum, "the integrity state is part of what mark-sent records"
    assert note == "Uploaded manually to the bank portal."

    published = rows(
        world,
        "SELECT event_type FROM outbox_events WHERE aggregate_id = %s",
        target["export_id"],
    )
    assert published == [("BankExportSent",)], published


def test_a_preview_cannot_be_marked_sent(world: dict[str, Any]) -> None:
    """`SVC-SENT-001`'s negative control, and the service half of a database property.

    The runtime cannot write `export_type`, so a preview can never *become* final. This is the
    other direction: it cannot be *treated* as final either.
    """

    target = a_final_export(world)
    client = world["client"]
    sign_in_admin(client, "sent_accountant")

    preview = client.post(
        f"/api/v1/payment-batches/{target['batch_id']}"
        f"/versions/{target['version_id']}/exports/preview",
        json=None,
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert preview.status_code == 201, preview.text

    response = mark_sent(world, preview.json()["id"])

    assert response.status_code == 400, response.text
    assert "preview" in response.json()["error"]["message"]
    assert rows(
        world,
        "SELECT sent_to_bank_marked_at FROM bank_excel_exports WHERE id = %s",
        preview.json()["id"],
    ) == [(None,)]


def test_marking_sent_twice_does_not_move_the_timestamp(world: dict[str, Any]) -> None:
    """`CON-SENT-001`. Idempotent under its key, and refused without one.

    Two claims, and the second is the one that matters operationally: a retry under the same key
    returns the first answer, and a *different* request to mark an already-sent export is
    refused rather than silently re-stamping it. An accountant who clicks twice must not move the
    moment a payment is recorded as having left.
    """

    target = a_final_export(world)
    sign_in_admin(world["client"], "sent_accountant")
    assert download(world, target["export_id"]).status_code == 200

    key = str(uuid.uuid4())
    first = mark_sent(world, target["export_id"], key=key)
    assert first.status_code == 200, first.text
    stamped = first.json()["sent_to_bank_marked_at"]

    replay = mark_sent(world, target["export_id"], key=key)
    assert replay.status_code == 200, replay.text
    assert replay.json()["sent_to_bank_marked_at"] == stamped

    fresh = mark_sent(world, target["export_id"])
    assert fresh.status_code == 409, fresh.text

    assert rows(
        world,
        "SELECT count(*) FROM audit_logs WHERE action = 'bank_export.sent_marked' "
        "AND entity_id = %s",
        target["export_id"],
    )[0][0] == 1, "a second audit row was written for one sending"


def test_reading_an_export_needs_the_read_permission(world: dict[str, Any]) -> None:
    """`bank_export.read` goes to accountant, manager and auditor. A trader gets nothing."""

    target = a_final_export(world)
    client = world["client"]

    sign_in_trader(client)
    assert client.get(f"/api/v1/bank-exports/{target['export_id']}").status_code == 403

    sign_in_admin(client, "sent_manager")
    assert client.get(f"/api/v1/bank-exports/{target['export_id']}").status_code == 200


def test_downloading_needs_the_download_permission_and_is_refused_to_a_trader(
    world: dict[str, Any],
) -> None:
    """`SEC-DOWNLOAD-001`. The file is a list of every payment the centre is making.

    Two negatives, and they fail for different reasons worth keeping apart: the manager holds
    `bank_export.read` and not `download`, so the route wants *this* grant rather than some
    export grant; the trader holds nothing on this surface at all, and a batch has no trader, so
    there is no ownership scope that could ever make the file theirs.
    """

    target = a_final_export(world)
    client = world["client"]

    sign_in_admin(client, "sent_manager")
    assert download(world, target["export_id"]).status_code == 403

    sign_in_trader(client)
    assert download(world, target["export_id"]).status_code == 403


def test_marking_sent_needs_the_mark_sent_permission(world: dict[str, Any]) -> None:
    """`permission_catalog.yaml:504` gives it to `accountant` only."""

    target = a_final_export(world)
    sign_in_admin(world["client"], "sent_manager")

    assert mark_sent(world, target["export_id"]).status_code == 403


def test_marking_sent_requires_an_idempotency_key(world: dict[str, Any]) -> None:
    """`command_catalog.yaml:202`: `"idempotency": "required"`.

    428 and not 400: the caller did not supply a precondition the command needs, which is a
    different thing from supplying a bad one.

    **No `If-Match` is required, and that is recorded rather than overlooked.**
    `05_API_Specification.md:1519` shows one; §11.8 gives this table no `record_version`; and
    `command_catalog.yaml:203` says `open_conflict_if_match_target_not_defined` — the catalogue
    describing an unresolved contract. G-13 in the M7 plan carries the question.
    """

    target = a_final_export(world)
    client = world["client"]
    sign_in_admin(client, "sent_accountant")

    response = client.post(
        f"/api/v1/bank-exports/{target['export_id']}/mark-sent-to-bank",
        json={
            "sent_at": datetime.now(UTC).isoformat(),
            "submission_channel": CHANNEL,
            "note": None,
        },
        headers=csrf(client),
    )

    assert response.status_code == 428, response.text
