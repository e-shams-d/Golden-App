"""Submitting a draft, and what makes the submitted revision evidence.

M5 slice 6. The test that carries the milestone is
`test_editing_the_beneficiary_afterwards_does_not_change_the_submitted_revision`:
`15_Agent_Implementation_Plan.md:808` says beneficiary history is not mutated by later
edits, and that is the difference between a revision and a view.

**Submission verifies the snapshot rather than filling it**, which corrects what the plan
originally said. Filling it at submit is not implementable: a revision cannot be updated,
and creating one at submit would produce a byte-identical second row that
`UNIQUE(payment_request_id, content_hash)` refuses — so a trader could not submit an
unmodified draft.

Covers: SVC-SUB-001, SVC-SUB-002, SVC-SUB-003, SEC-REQ-002, AUD-REQ-001.
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

TRADERS: dict[str, tuple[str, str, str]] = {
    "ok": ("+989120000401", "active", "approved"),
    "pending": ("+989120000402", "active", "pending_approval"),
    "suspended": ("+989120000403", "suspended", "approved"),
    "other": ("+989120000404", "active", "approved"),
}

IBAN = "IR060120000000000000000001"


@pytest.fixture
def migrated(provisioned_database: RuntimeIdentities) -> RuntimeIdentities:
    result = run_alembic(
        provisioned_database.migrator_url,
        "upgrade",
        "head",
        app_role=provisioned_database.app_role,
        worker_role=provisioned_database.worker_role,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return provisioned_database


@pytest.fixture
def world(migrated: RuntimeIdentities, tmp_path: Any) -> Iterator[dict[str, Any]]:
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
        local_storage_root=tmp_path / "storage",
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="c" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    traders = {name: uuid.uuid4() for name in TRADERS}
    beneficiaries = {name: uuid.uuid4() for name in TRADERS}
    files: dict[str, uuid.UUID] = {}

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        for name, (phone, operational, approval) in TRADERS.items():
            connection.execute(
                "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
                "approval_status) VALUES (%s, %s, %s, %s, %s)",
                (traders[name], f"Trader {name}", phone, operational, approval),
            )
            connection.execute(
                "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
                "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
                (traders[name], phone, encoded),
            )
            connection.execute(
                "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
                "national_id, status, verification_status) VALUES (%s, %s, 'Ali Original', %s, "
                "%s, '1234567890', 'active', 'not_checked')",
                (beneficiaries[name], traders[name], IBAN, IBAN),
            )

        # One attachment per storage state that matters. `available` is the only state
        # that means hashed and scanned clean; the other two are what M4's states exist
        # to distinguish.
        for label, storage_status, scan_status in (
            ("available", "available", "clean"),
            ("pending", "pending", "pending"),
            ("quarantined", "quarantined", "suspicious"),
        ):
            file_id = uuid.uuid4()
            files[label] = file_id
            connection.execute(
                "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
                "original_filename, mime_type_declared, size_bytes, category, "
                "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
                "original_or_derived_relation, sha256_hash) VALUES (%s, 'local', 'private', "
                "%s, 'receipt.pdf', 'application/pdf', 1024, 'payment_request_source', "
                "'trader_private', %s, %s, 'trader_user', 'original', %s)",
                (file_id, f"key/{file_id}", storage_status, scan_status, "a" * 64),
            )

        for username in ("staff_granted", "staff_bare"):
            connection.execute(
                "INSERT INTO admin_users (username, full_name, password_hash, status) "
                "VALUES (%s, %s, %s, 'active')",
                (username, f"{username} User", encoded),
            )
        connection.execute(
            "INSERT INTO admin_user_roles (admin_user_id, role_id) "
            "SELECT u.id, r.id FROM admin_users u, roles r "
            "WHERE u.username = 'staff_granted' AND r.code = 'accountant'"
        )
        connection.commit()

    app = create_app(settings=settings)
    app.state.runtime = RuntimeServices.from_settings(settings)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://trader.localhost") as client:
        yield {
            "client": client,
            "traders": traders,
            "beneficiaries": beneficiaries,
            "files": files,
            "owner_url": migrated.owner_url,
        }
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def sign_in(client: Any, trader: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/trader/login",
        json={"identifier": TRADERS[trader][0], "password": PASSWORD},
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


def open_draft(world: dict[str, Any], trader: str = "ok", attachment: str | None = None) -> Any:
    client = world["client"]
    body: dict[str, Any] = {
        "beneficiary_id": str(world["beneficiaries"][trader]),
        "amount": {"value": "500", "unit": "TOMAN"},
    }
    if attachment is not None:
        body["source_attachment_file_id"] = str(world["files"][attachment])
    created = client.post("/api/v1/payment-requests", json=body, headers=csrf(client))
    assert created.status_code == 201, created.text
    return created.json()


def submit(world: dict[str, Any], request_id: str, version: int) -> Any:
    client = world["client"]
    return client.post(
        f"/api/v1/payment-requests/{request_id}/submit",
        headers={**csrf(client), "If-Match": f'"rv-{version}"'},
    )


def test_a_draft_is_submitted_to_the_centre(world: dict[str, Any]) -> None:
    """The ordinary path, and `submitted_at` is set.

    No request body: submission states nothing new. What is being submitted is already
    on the current revision, and a body would invite a caller to send content the
    revision does not carry.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)

    response = submit(world, created["request"]["id"], created["request"]["record_version"])
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "submitted_to_center"

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        row = connection.execute(
            "SELECT status, submitted_at FROM payment_requests WHERE id = %s",
            (created["request"]["id"],),
        ).fetchone()

    assert row is not None
    assert row[0] == "submitted_to_center"
    assert row[1] is not None, "submitted_at was not recorded"


def test_the_submitted_revision_carries_a_complete_snapshot(world: dict[str, Any]) -> None:
    """SVC-SUB-001.

    Every column document 04 marks required, populated and matching the beneficiary as
    it stood when the revision was written. `beneficiary_national_id_snapshot` is checked
    too here — the fixture's beneficiary has one, so it must have been copied; the
    command does not *require* it, because document 04 marks it optional and not every
    recipient has one on file.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)
    submit(world, created["request"]["id"], created["request"]["record_version"])

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        row = connection.execute(
            "SELECT beneficiary_name_snapshot, beneficiary_iban_snapshot, "
            "beneficiary_national_id_snapshot, amount_irr, content_hash "
            "FROM payment_request_revisions WHERE id = %s",
            (created["revision"]["id"],),
        ).fetchone()

    assert row is not None
    assert row[0] == "Ali Original"
    assert row[1] == IBAN
    assert row[2] == "1234567890"
    assert row[3] == 5000
    assert len(row[4]) == 64


def test_a_revision_with_an_incomplete_snapshot_cannot_be_submitted(
    world: dict[str, Any],
) -> None:
    """SVC-SUB-001, the refusal.

    The snapshot columns are NOT NULL, so this state cannot be reached through the API —
    it is forced with direct SQL through the owner connection. That is the point: the
    check is a second line behind the constraints, and a request that reached a reviewer
    without a beneficiary name would be one nobody can act on.

    Blanking rather than nulling, because NOT NULL refuses NULL and an empty string is
    the shape a careless writer would actually produce.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE payment_request_revisions SET beneficiary_name_snapshot = '' WHERE id = %s",
            (created["revision"]["id"],),
        )
        connection.commit()

    refused = submit(world, created["request"]["id"], created["request"]["record_version"])
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["code"] == "BUSINESS_RULE_VIOLATION"


def test_editing_the_beneficiary_afterwards_does_not_change_the_submitted_revision(
    world: dict[str, Any],
) -> None:
    """SVC-SUB-002, and the test that makes a revision evidence rather than a view.

    `15_Agent_Implementation_Plan.md:808`: beneficiary history is not mutated by later
    edits. The beneficiary is edited **through the API**, not with SQL, so this exercises
    the real path a trader would take — and the submitted revision must still read as it
    did at submission.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)
    submit(world, created["request"]["id"], created["request"]["record_version"])

    beneficiary_id = world["beneficiaries"]["ok"]
    current = client.get(f"/api/v1/beneficiaries/{beneficiary_id}").json()
    edited = client.patch(
        f"/api/v1/beneficiaries/{beneficiary_id}",
        json={"full_name": "Renamed Entirely", "iban": "IR060120000000000000000099"},
        headers={**csrf(client), "If-Match": f'"rv-{current["record_version"]}"'},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["full_name"] == "Renamed Entirely"

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        row = connection.execute(
            "SELECT beneficiary_name_snapshot, beneficiary_iban_snapshot "
            "FROM payment_request_revisions WHERE id = %s",
            (created["revision"]["id"],),
        ).fetchone()

    assert row is not None
    assert row[0] == "Ali Original", "the submitted revision followed the beneficiary edit"
    assert row[1] == IBAN, "the submitted IBAN snapshot followed the beneficiary edit"


def test_a_beneficiary_edited_between_drafting_and_submitting_does_not_reach_the_revision(
    world: dict[str, Any],
) -> None:
    """SVC-SUB-002, and the case the other tests could not see.

    **This test exists because a negative control found it missing.** The plan's stated
    control is "store a beneficiary reference instead of the snapshot: SVC-SUB-002 must
    fail". Making `submit` re-read the live beneficiary — which is exactly what a
    reference would mean — left every test passing, because they all edit the beneficiary
    *after* submitting: the re-read then writes back the values that were already there
    and nothing looks wrong.

    The distinguishing case is an edit **between** drafting and submitting. Under
    snapshot-at-revision-write the submitted revision keeps what the trader stated; under
    snapshot-at-submit it would silently pick up the new name and IBAN, and the reviewer
    would see values the trader never submitted.

    That is also the behavioural half of the plan correction this slice made: the plan
    said the snapshot is filled at submission, and it is not.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)

    beneficiary_id = world["beneficiaries"]["ok"]
    current = client.get(f"/api/v1/beneficiaries/{beneficiary_id}").json()
    edited = client.patch(
        f"/api/v1/beneficiaries/{beneficiary_id}",
        json={"full_name": "Changed Before Submit", "iban": "IR060120000000000000000077"},
        headers={**csrf(client), "If-Match": f'"rv-{current["record_version"]}"'},
    )
    assert edited.status_code == 200, edited.text

    assert submit(
        world, created["request"]["id"], created["request"]["record_version"]
    ).status_code == 200

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        row = connection.execute(
            "SELECT beneficiary_name_snapshot, beneficiary_iban_snapshot "
            "FROM payment_request_revisions WHERE id = %s",
            (created["revision"]["id"],),
        ).fetchone()

    assert row is not None
    assert row[0] == "Ali Original", (
        "the snapshot was re-read at submission, so the reviewer would see a name the "
        "trader never submitted"
    )
    assert row[1] == IBAN, "the IBAN snapshot was re-read at submission"


def test_the_history_still_reads_as_submitted_after_a_beneficiary_edit(
    world: dict[str, Any],
) -> None:
    """SVC-SUB-002, through the API rather than the table.

    The previous test proves the row did not move. This proves the *reader* does not see
    the new values either — a history endpoint that joined to `beneficiaries` instead of
    reading the snapshot columns would pass the previous test and fail this one.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)
    request_id = created["request"]["id"]
    submit(world, request_id, created["request"]["record_version"])

    beneficiary_id = world["beneficiaries"]["ok"]
    current = client.get(f"/api/v1/beneficiaries/{beneficiary_id}").json()
    client.patch(
        f"/api/v1/beneficiaries/{beneficiary_id}",
        json={"full_name": "Renamed Entirely"},
        headers={**csrf(client), "If-Match": f'"rv-{current["record_version"]}"'},
    )

    history = client.get(f"/api/v1/payment-requests/{request_id}/revisions")
    assert history.status_code == 200
    assert history.json()["items"][0]["beneficiary_name_snapshot"] == "Ali Original"
    assert "Renamed Entirely" not in history.text


def test_an_available_attachment_can_be_submitted(world: dict[str, Any]) -> None:
    """SVC-SUB-003, the permissive half.

    Without this, a command that refused every attachment would satisfy the two refusals
    below and look like a working state check.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world, attachment="available")

    response = submit(world, created["request"]["id"], created["request"]["record_version"])
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("state", ["pending", "quarantined"])
def test_an_attachment_that_is_not_available_cannot_be_submitted(
    world: dict[str, Any], state: str
) -> None:
    """SVC-SUB-003. M4's file states carry the meaning; this is the first consumer.

    `available` is the only state that means hashed and scanned clean. A `pending`
    attachment has not finished inspection and a `quarantined` one failed it — submitting
    either would put a request in front of a reviewer whose evidence might be a file
    nobody has cleared.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world, attachment=state)

    refused = submit(world, created["request"]["id"], created["request"]["record_version"])
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["code"] == "BUSINESS_RULE_VIOLATION"

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        row = connection.execute(
            "SELECT status FROM payment_requests WHERE id = %s",
            (created["request"]["id"],),
        ).fetchone()
    assert row is not None and row[0] == "draft", "the refused submission moved the status"


def test_a_request_with_no_attachment_can_be_submitted(world: dict[str, Any]) -> None:
    """SVC-SUB-003. Document 04 marks the column nullable and not every request has a
    receipt, so an absent attachment is not an unavailable one."""

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)

    response = submit(world, created["request"]["id"], created["request"]["record_version"])
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("trader", ["pending", "suspended"])
def test_a_trader_that_is_not_operable_cannot_submit(world: dict[str, Any], trader: str) -> None:
    """SEC-REQ-002. `15_Agent_Implementation_Plan.md:806` covers submit as well as create.

    The draft is created through the API by the operable trader and then reassigned with
    SQL, because a non-operable trader cannot create one in the first place — slice 3
    proved that. Reassigning is what isolates the *submit* guard from the create guard.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE payment_requests SET trader_id = %s WHERE id = %s",
            (world["traders"][trader], created["request"]["id"]),
        )
        connection.commit()

    sign_in(client, trader)
    refused = submit(world, created["request"]["id"], created["request"]["record_version"])
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["code"] == "BUSINESS_RULE_VIOLATION"


def test_a_trader_cannot_submit_another_traders_request(world: dict[str, Any]) -> None:
    """SEC-REQ-002, the ownership half. `404`, so the id is not confirmed."""

    client = world["client"]

    sign_in(client, "other")
    theirs = open_draft(world, trader="other")

    sign_in(client, "ok")
    refused = submit(world, theirs["request"]["id"], theirs["request"]["record_version"])
    assert refused.status_code == 404, refused.text

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        row = connection.execute(
            "SELECT status FROM payment_requests WHERE id = %s", (theirs["request"]["id"],)
        ).fetchone()
    assert row is not None and row[0] == "draft"


def test_an_admin_without_the_submit_permission_is_refused(world: dict[str, Any]) -> None:
    """The permission negative, with the permitted half to prove it is about the grant."""

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)

    sign_in_admin(client, "staff_bare")
    refused = submit(world, created["request"]["id"], created["request"]["record_version"])
    assert refused.status_code == 403, refused.text

    sign_in_admin(client, "staff_granted")
    allowed = submit(world, created["request"]["id"], created["request"]["record_version"])
    assert allowed.status_code != 403, (
        f"the permitted admin was refused too ({allowed.status_code}): {allowed.text}"
    )


def test_submission_requires_a_current_if_match(world: dict[str, Any]) -> None:
    """The stale-tab case on the submit path."""

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)
    path = f"/api/v1/payment-requests/{created['request']['id']}/submit"

    assert client.post(path, headers=csrf(client)).status_code == 428
    assert client.post(
        path, headers={**csrf(client), "If-Match": '"rv-99"'}
    ).status_code == 412

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        row = connection.execute(
            "SELECT status FROM payment_requests WHERE id = %s", (created["request"]["id"],)
        ).fetchone()
    assert row is not None and row[0] == "draft"


def test_only_a_draft_is_submitted(world: dict[str, Any]) -> None:
    """The transition guard. Submitting twice is refused.

    A request returned for correction is resubmitted by filing the correction, which
    moves it back to the centre in one step — so there is no second path into
    `submitted_to_center` that this would need to permit.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)

    first = submit(world, created["request"]["id"], created["request"]["record_version"])
    assert first.status_code == 200
    version = first.json()["record_version"]

    second = submit(world, created["request"]["id"], version)
    assert second.status_code == 400, second.text


def test_submission_audits_and_publishes_in_one_transaction(world: dict[str, Any]) -> None:
    """AUD-REQ-001.

    Both rows read from a separate connection after the response returned, so what is
    asserted is what committed. Submission is the first command in this aggregate that
    publishes: draft creation and cancellation have no audience, and this is the moment
    the centre's queue changes.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)
    submit(world, created["request"]["id"], created["request"]["record_version"])

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        audit = connection.execute(
            "SELECT action, new_values FROM audit_logs "
            "WHERE action = 'payment_request.submitted'"
        ).fetchone()
        outbox = connection.execute(
            "SELECT event_type, aggregate_type, aggregate_id, payload FROM outbox_events "
            "WHERE event_type = 'PaymentRequestSubmitted'"
        ).fetchone()

    assert audit is not None, "submission wrote no audit row"
    assert audit[1]["status"] == "submitted_to_center"

    assert outbox is not None, "submission published no outbox event"
    assert outbox[1] == "payment_request"
    assert str(outbox[2]) == created["request"]["id"]
    # Identifiers only. A consumer that needs the amount or the beneficiary reads the
    # aggregate; putting them on a queue widens where a payment destination lives.
    assert set(outbox[3]) == {"payment_request_id", "trader_id", "request_number"}


def test_a_refused_submission_publishes_nothing(world: dict[str, Any]) -> None:
    """AUD-REQ-001, the other direction.

    The audit row and the outbox event are written in the command's transaction, so a
    refusal must leave neither. An event published before the guard ran would tell the
    centre a request arrived that never did.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world, attachment="quarantined")
    submit(world, created["request"]["id"], created["request"]["record_version"])

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        counts = connection.execute(
            "SELECT (SELECT count(*) FROM audit_logs WHERE action = "
            "'payment_request.submitted'), (SELECT count(*) FROM outbox_events WHERE "
            "event_type = 'PaymentRequestSubmitted')"
        ).fetchone()

    assert counts is not None
    assert counts[0] == 0, "a refused submission wrote an audit row"
    assert counts[1] == 0, "a refused submission published an event"
