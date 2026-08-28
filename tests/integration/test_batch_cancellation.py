"""Cancelling a batch after somebody has decided about it, and who is allowed to.

G-5, against a real PostgreSQL. `06_Workflows_and_State_Machines.md` §29.2 lists four
cancellation origins; M6 implemented one, because `permission_catalog.yaml` held exactly one
batch cancellation permission and the rest were unreachable under deny-by-default. The owner's
2026-08-25 decision under DOC-CONFLICT-056 added `payment_batch.cancel_approved`, granted to
`manager`, and this module is the evidence that the split it creates is a **split** rather than
a widening.

**Both directions are asserted, and only together do they mean anything.** An accountant must not
cancel an approved batch — that is the separation `FINANCIAL_INTEGRITY_BASELINE.md` §5 makes
non-configurable, arriving one verb later. And a manager must not cancel a draft, because the new
grant is for undoing a decision rather than a general power over batches. A test of one direction
alone passes against an implementation that simply gave both permissions to both roles.

**Two administrators with disjoint grants, deliberately.** `cancel_accountant` holds
`cancel_draft` and not `cancel_approved`; `cancel_manager` the reverse. With a dual-role user the
403s could not distinguish "this caller lacks the grant" from "this state needs a different
grant", which is exactly how a route-only implementation would pass.

**The final export chain is driven through the real routes** rather than inserted. What
`_refuse_if_a_final_export_was_sent` reads is a status on a row, so a hand-built row would test
the query and not the rule: `mark-sent-to-bank` is the only thing that writes that status in
production, and if it ever stopped writing it, an inserted row would keep this test green.

Covers: SVC-BATCH-006, whose second and third origins this opens. G-5 is a gap-closure
item and has no obligation ids of its own; none are invented, because the traceability
scanner counts any id in a test file as a citation and the M8 plan records that lesson
as eleven prior corrections.
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

TRADER_PHONE = "+989120005401"
IBAN = "IR060120000000000000000054"

LIMIT = 1_000_000_000
ONE_ROW = "900000000"

APPROVE_PURPOSE = "payment_batch_version.approve"
REJECT_PURPOSE = "payment_batch_version.reject"
STEP_UP_RESOURCE_TYPE = "payment_batch_version"

CHANNEL = "bank_portal_manual_upload"

CANCEL_DRAFT = "payment_batch.cancel_draft"
CANCEL_APPROVED = "payment_batch.cancel_approved"


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

    storage_root = tmp_path_factory.mktemp("storage")
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
            "approval_status) VALUES (%s, 'Cancel Trader', %s, 'active', 'approved')",
            (ids["trader"], TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (ids["trader"], TRADER_PHONE, encoded),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'Ali Six', %s, %s, 'active', "
            "'not_checked')",
            (ids["beneficiary"], ids["trader"], IBAN, IBAN),
        )
        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'saderat', 'Bank Saderat', 'active')",
            (ids["profile"],),
        )
        connection.execute(
            "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, status, "
            "default_transfer_limit_irr, after_cutoff_transfer_limit_irr, cutoff_time, "
            "splitting_enabled, required_fields, rules, config_hash) "
            "VALUES (%s, %s, 1, 'active', %s, NULL, NULL, TRUE, '{}', '{}', %s)",
            (ids["version"], ids["profile"], LIMIT, "5" * 64),
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
            (ids["mapping"], ids["version"], "6" * 64),
        )
        for username, role in (
            # Holds `cancel_draft` and not `cancel_approved` (`permission_catalog.yaml:466`),
            # plus everything needed to drive a batch as far as a sent export.
            ("cancel_accountant", "accountant"),
            # The reverse, by `20260828_0027`: `cancel_approved` and not `cancel_draft`.
            ("cancel_manager", "manager"),
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


def step_up(client: Any, version_id: str, purpose: str = APPROVE_PURPOSE) -> str:
    response = client.post(
        "/api/v1/auth/reauthenticate",
        json={
            "password": PASSWORD,
            "purpose": purpose,
            "resource_type": STEP_UP_RESOURCE_TYPE,
            "resource_id": version_id,
        },
        headers=csrf(client),
    )
    assert response.status_code == 200, response.text
    return str(response.json()["recent_auth_reference"])


def a_draft_batch(world: dict[str, Any]) -> dict[str, Any]:
    """One eligible request in one draft batch, through the routes."""

    client = world["client"]
    sign_in_trader(client)
    created = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiary_id"]),
            "amount": {"value": ONE_ROW, "unit": "IRR"},
            "description": "برای لغو",
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

    sign_in_admin(client, "cancel_accountant")
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
    body = batch.json()
    return {
        "request_id": request_id,
        "batch_id": body["batch"]["id"],
        "version_id": body["current_version"]["id"],
        "content_hash": body["current_version"]["content_hash"],
        "etag": batch.headers["ETag"],
    }


def a_finalized_batch(world: dict[str, Any]) -> dict[str, Any]:
    """`ready_for_approval`: finalized and awaiting a manager."""

    batch = a_draft_batch(world)
    client = world["client"]
    sign_in_admin(client, "cancel_accountant")
    frozen = client.post(
        f"/api/v1/payment-batches/{batch['batch_id']}/versions/{batch['version_id']}/finalize",
        json={"note": "validated"},
        headers={
            **csrf(client),
            "If-Match": batch["etag"],
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert frozen.status_code == 200, frozen.text
    return {
        **batch,
        "content_hash": frozen.json()["version"]["content_hash"],
        "etag": frozen.headers["ETag"],
    }


def an_approved_batch(world: dict[str, Any]) -> dict[str, Any]:
    """`approved`: a manager has decided, and `batch_approvals` holds the decision."""

    batch = a_finalized_batch(world)
    client = world["client"]
    sign_in_admin(client, "cancel_manager")
    approved = client.post(
        f"/api/v1/payment-batches/{batch['batch_id']}"
        f"/versions/{batch['version_id']}/approve",
        json={
            "expected_content_hash": batch["content_hash"],
            "approval_note": "approved for the bank",
        },
        headers={
            **csrf(client),
            "Idempotency-Key": str(uuid.uuid4()),
            "X-Recent-Auth": step_up(client, batch["version_id"]),
        },
    )
    assert approved.status_code == 200, approved.text
    return {**batch, "etag": approved.headers["ETag"]}


def a_rejected_batch(world: dict[str, Any]) -> dict[str, Any]:
    batch = a_finalized_batch(world)
    client = world["client"]
    sign_in_admin(client, "cancel_manager")
    rejected = client.post(
        f"/api/v1/payment-batches/{batch['batch_id']}"
        f"/versions/{batch['version_id']}/reject",
        json={
            "expected_content_hash": batch["content_hash"],
            "reason_code": "amount_disputed",
            "reason": "The total does not match the instruction.",
        },
        headers={
            **csrf(client),
            "Idempotency-Key": str(uuid.uuid4()),
            "X-Recent-Auth": step_up(client, batch["version_id"], REJECT_PURPOSE),
        },
    )
    assert rejected.status_code == 200, rejected.text
    return {**batch, "etag": rejected.headers["ETag"]}


def a_final_export_of(world: dict[str, Any], batch: dict[str, Any]) -> str:
    client = world["client"]
    sign_in_admin(client, "cancel_accountant")
    exported = client.post(
        f"/api/v1/payment-batches/{batch['batch_id']}"
        f"/versions/{batch['version_id']}/exports/final",
        json=None,
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert exported.status_code == 201, exported.text
    return str(exported.json()["id"])


def cancel(
    world: dict[str, Any], batch: dict[str, Any], *, etag: str, reason: str | None = None
) -> Any:
    client = world["client"]
    return client.post(
        f"/api/v1/payment-batches/{batch['batch_id']}/cancel",
        json={"reason": reason} if reason is not None else {},
        headers={
            **csrf(client),
            "If-Match": etag,
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )


def batch_row(world: dict[str, Any], batch_id: str) -> tuple[Any, ...]:
    found = rows(
        world,
        "SELECT status, cancelled_at, cancelled_reason FROM payment_batches WHERE id = %s",
        batch_id,
    )
    assert found, "the batch disappeared"
    return found[0]


def cancellation_audit(world: dict[str, Any], batch_id: str) -> list[tuple[Any, ...]]:
    return rows(
        world,
        "SELECT previous_values->>'status', new_values->>'status', "
        "new_values->>'authorised_by', new_values->'voided_final_exports' "
        "FROM audit_logs WHERE action = 'payment_batch.cancelled' AND entity_id = %s",
        batch_id,
    )


# ---------------------------------------------------------------------------------------------
# The two origins the owner's decision opened.
# ---------------------------------------------------------------------------------------------


def test_a_ready_for_approval_batch_is_cancelled_by_the_accountant(
    world: dict[str, Any],
) -> None:
    """§29.2: "Ready-for-approval may be cancelled with reason".

    The accountant keeps this one under the existing grant, because nothing has been decided yet
    and they are undoing their own work. Until G-5 this was refused, and the refusal named
    DOC-CONFLICT-056 — the rule existed and the permission to reach it did not.

    **The reason is recorded because one was given**, not because one was required. §29.2
    attaches "with reason" to this origin, and the command still accepts an omitted reason: a
    refusal stricter than any approved document states would be a rule this implementation
    invented.
    """

    batch = a_finalized_batch(world)
    sign_in_admin(world["client"], "cancel_accountant")

    response = cancel(world, batch, etag=batch["etag"], reason="the payment was made by hand")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"

    status, cancelled_at, reason = batch_row(world, batch["batch_id"])
    assert status == "cancelled"
    assert cancelled_at is not None
    assert reason == "the payment was made by hand"

    released = rows(
        world,
        "SELECT released_at, release_reason FROM payment_attempt_allocations "
        "WHERE payment_batch_version_id = %s",
        batch["version_id"],
    )
    assert released, "the cancelled batch had no allocations to release"
    for released_at, release_reason in released:
        assert released_at is not None
        assert release_reason == "the batch was cancelled"


def test_an_approved_batch_is_cancelled_by_the_manager_and_the_approval_stops_authorising(
    world: dict[str, Any],
) -> None:
    """The origin the new permission exists for.

    **Two audit rows, and neither is a duplicate of the other.** The batch's row says the batch
    was cancelled. The approval's row says a manager's decision stopped being operational, which
    is a different fact with a different reader and a different key — an investigator asking
    "why is the approval I remember no longer in force" looks it up by the approval's id.

    `payment_batch_approval.invalidated` is the same catalogued action a replacement writes
    (`audit_outbox_catalog.yaml:31`), because it is the same fact. What distinguishes the two
    ways an approval dies is the **absence** of `replacement_version_id` here, and this asserts
    that absence rather than leaving it to be noticed.
    """

    batch = an_approved_batch(world)
    sign_in_admin(world["client"], "cancel_manager")

    response = cancel(world, batch, etag=batch["etag"], reason="approved against the wrong quote")
    assert response.status_code == 200, response.text

    status, _, _ = batch_row(world, batch["batch_id"])
    assert status == "cancelled"

    approvals = rows(
        world,
        "SELECT id, decision FROM batch_approvals WHERE payment_batch_version_id = %s",
        batch["version_id"],
    )
    assert approvals, "an approved batch with no approval row"
    approval_id, decision = approvals[0]
    assert decision == "approved", (
        "the approval row was rewritten; §29.2 says the approval remains historical, and "
        "`batch_approvals` carries no UPDATE grant precisely so it cannot be"
    )

    recorded = rows(
        world,
        "SELECT previous_values->>'operational', new_values->>'operational', "
        "new_values->>'replacement_version_id', new_values->>'batch_status', reason "
        "FROM audit_logs WHERE action = 'payment_batch_approval.invalidated' AND entity_id = %s",
        approval_id,
    )
    assert recorded == [
        (
            "true",
            "false",
            None,
            "cancelled",
            "the approved batch was cancelled; the approval remains historical",
        )
    ], recorded


# ---------------------------------------------------------------------------------------------
# Both directions of the split. Either one alone passes against "give both to both".
# ---------------------------------------------------------------------------------------------


def test_an_accountant_cannot_cancel_an_approved_batch(world: dict[str, Any]) -> None:
    """The separation the owner's decision exists to create.

    The accountant reaches the handler — they hold `cancel_draft`, so the route's dependency
    admits them — and is refused by the command once the status is known. That is the whole
    design: the authority depends on a fact no route dependency can have.

    **The batch is read back**, because a refusal that had already released the allocations or
    moved the status would be a 403 with the damage done.
    """

    batch = an_approved_batch(world)
    sign_in_admin(world["client"], "cancel_accountant")

    refused = cancel(world, batch, etag=batch["etag"])
    assert refused.status_code == 403, refused.text

    status, cancelled_at, _ = batch_row(world, batch["batch_id"])
    assert (status, cancelled_at) == ("approved", None)

    held = rows(
        world,
        "SELECT p.code FROM permissions p JOIN role_permissions rp ON rp.permission_id = p.id "
        "JOIN roles r ON r.id = rp.role_id WHERE r.code = 'accountant' AND p.code = %s",
        CANCEL_APPROVED,
    )
    assert held == [], (
        "the refusal above would also pass if `accountant` held `cancel_approved` and something "
        "else refused; it does not hold it, so the 403 is the state check"
    )


def test_a_manager_cannot_cancel_a_draft_batch(world: dict[str, Any]) -> None:
    """The other direction, and the reason this file asserts both.

    `cancel_approved` is authority over a *decision*, not a general power over batches. A manager
    who could also cancel drafts would be taking work off an accountant's desk that no document
    puts on theirs — and, more to the point, a test of the first direction alone passes against
    an implementation that granted both permissions to both roles.

    The manager reaches the handler because they hold `cancel_approved`; the command refuses on
    the status. So this is the mirror image of the test above, down to the mechanism.
    """

    batch = a_draft_batch(world)
    sign_in_admin(world["client"], "cancel_manager")

    refused = cancel(world, batch, etag=batch["etag"])
    assert refused.status_code == 403, refused.text
    assert batch_row(world, batch["batch_id"])[0] == "draft"

    held = rows(
        world,
        "SELECT p.code FROM permissions p JOIN role_permissions rp ON rp.permission_id = p.id "
        "JOIN roles r ON r.id = rp.role_id WHERE r.code = 'manager' AND p.code = %s",
        CANCEL_DRAFT,
    )
    assert held == [], "manager holds cancel_draft, so the refusal above proves nothing"


# ---------------------------------------------------------------------------------------------
# What the exported file does to the rule.
# ---------------------------------------------------------------------------------------------


def test_cancelling_an_approved_batch_voids_its_active_final_export(
    world: dict[str, Any],
) -> None:
    """The file stops being valid, and the row stays.

    The same treatment a replacement gives, through the same helper and for the same reason:
    §29.2's "approval remains historical" applies to the artifact too. Deleting the export would
    erase the answer to "what was produced" at the moment it becomes hardest to reconstruct, and
    `voided` sits outside `uq_active_final_export_per_version`'s predicate so nothing is blocked
    by the row that remains.

    The audit row names the export it voided. Without that, the only trace is a status change
    nobody joined back to its cause.
    """

    batch = an_approved_batch(world)
    export_id = a_final_export_of(world, batch)
    before = rows(
        world, "SELECT status, export_number FROM bank_excel_exports WHERE id = %s", export_id
    )[0]
    # Generation validates the file it wrote before returning, so a fresh final export is already
    # `validated`. Asserted against the whole active set rather than the one status it happens to
    # land on: what matters here is that the export still occupies its version, which is what
    # `uq_active_final_export_per_version`'s predicate means.
    assert before[0] in ("generated", "validated", "downloaded"), before

    current = rows(
        world, "SELECT record_version FROM payment_batches WHERE id = %s", batch["batch_id"]
    )[0][0]
    sign_in_admin(world["client"], "cancel_manager")
    response = cancel(world, batch, etag=f'"rv-{current}"', reason="withdrawn")
    assert response.status_code == 200, response.text

    after = rows(world, "SELECT status FROM bank_excel_exports WHERE id = %s", export_id)
    assert after == [("voided",)], after

    audited = cancellation_audit(world, batch["batch_id"])
    assert audited, "the cancellation wrote no audit row"
    previous_status, new_status, authorised_by, voided = audited[0]
    assert (previous_status, new_status) == ("approved", "cancelled")
    assert authorised_by == CANCEL_APPROVED
    assert voided == [before[1]], voided


def test_a_batch_whose_export_was_marked_sent_cannot_be_cancelled(
    world: dict[str, Any],
) -> None:
    """§29.2 at `:1381`: "only before valid final export is sent".

    **A manager holds the permission and still cannot do this.** The constraint is on the world
    rather than on the caller — the bank has the file — so no grant lifts it, and the refusal is
    a 400 rather than a 403.

    **The rule is enforced by the status machine, and this test is what established that.** The
    first implementation queried `bank_excel_exports` for a sent final export; this test proved
    the query could never fire, because `mark-sent-to-bank` moves the batch to `sent_to_bank` and
    a batch in that status never reaches the authority check. The guard was removed and
    `CANCELLED_TOO_LATE` took its place — so what is asserted below is that the *reachable* path
    refuses, and that its message still names the rule rather than only the status list.

    Marking sent goes through the route rather than an UPDATE, because that route is the only
    thing that writes the status in production: a hand-set status would have hidden exactly the
    fact this test found.

    The export is read back too. A cancellation that refused *after* voiding would have withdrawn
    a file the bank already has, which is the outcome this rule exists to prevent.
    """

    batch = an_approved_batch(world)
    export_id = a_final_export_of(world, batch)

    client = world["client"]
    sign_in_admin(client, "cancel_accountant")
    assert client.get(f"/api/v1/bank-exports/{export_id}/download").status_code == 200
    sent = client.post(
        f"/api/v1/bank-exports/{export_id}/mark-sent-to-bank",
        json={
            "sent_at": datetime.now(UTC).isoformat(),
            "submission_channel": CHANNEL,
            "note": "Uploaded manually to the bank portal.",
        },
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert sent.status_code == 200, sent.text

    current = rows(
        world, "SELECT record_version FROM payment_batches WHERE id = %s", batch["batch_id"]
    )[0][0]
    assert batch_row(world, batch["batch_id"])[0] == "sent_to_bank", (
        "marking the export sent no longer moves the batch, so cancellation would reach the "
        "authority check with a sent export in hand and this test's premise is gone"
    )

    sign_in_admin(client, "cancel_manager")
    refused = cancel(world, batch, etag=f'"rv-{current}"', reason="too late")
    assert refused.status_code == 400, refused.text
    assert "sent" in refused.text
    # The citation without its section sign: the envelope's transport encoding is not what this
    # test is about, and asserting `§` would make an encoding change look like a rule change.
    assert "29.2" in refused.text, (
        "the refusal names the status without naming the rule, so a reader cannot tell a business "
        "constraint from an implementation limit"
    )

    assert batch_row(world, batch["batch_id"])[0] == "sent_to_bank"
    assert rows(
        world, "SELECT status FROM bank_excel_exports WHERE id = %s", export_id
    ) == [("sent_to_bank_marked",)]


# ---------------------------------------------------------------------------------------------
# The origin still unauthorised, unchanged by G-5.
# ---------------------------------------------------------------------------------------------


def test_a_rejected_batch_is_still_refused_and_the_refusal_still_names_the_conflict(
    world: dict[str, Any],
) -> None:
    """`SVC-BATCH-006`'s surviving half. The owner decided three origins, not four.

    §29.2 pairs `rejected` with `draft`, which would make it accountant work — but that pairing
    predates M7's rejection existing at all, and a batch that has been in front of a manager is
    not obviously the same case. Nobody has decided, so this stays refused, and the refusal has to
    keep saying *why*: otherwise the next reader assumes the state machine forbids it and the
    open question disappears.

    Asserted for the manager, who holds the newer and broader grant. If the widening had been
    written as "a manager may cancel anything", this is where it would show.
    """

    batch = a_rejected_batch(world)
    sign_in_admin(world["client"], "cancel_manager")

    refused = cancel(world, batch, etag=batch["etag"])
    assert refused.status_code == 400, refused.text
    assert "rejected" in refused.text
    assert "DOC-CONFLICT-056" in refused.text, (
        "the refusal does not say why the rule is unimplemented, so the next reader will assume "
        "the state machine forbids it"
    )
    assert batch_row(world, batch["batch_id"])[0] == "rejected"
