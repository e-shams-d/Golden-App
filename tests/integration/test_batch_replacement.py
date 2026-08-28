"""Replacement, release, and cancellation: every way a version leaves, and the evidence it leaves.

M6 slice 4. Three exits, and the interesting property is shared: each one has to release the
allocations it held, because the partial unique index refuses to allocate an attempt that is
already active somewhere. A supersession that kept its allocations would produce a replacement
with no rows; a cancellation that kept them would hold a trader's request hostage — permanently
unbatchable, with nothing saying why.

`SVC-BATCH-008` is the baseline's double-payment negative test, and it is the one worth reading:
no sequence of replace, release and re-allocate produces two active allocations for one attempt.
Asserted over the whole table rather than over the rows a test touched, because "the two I looked
at are fine" is not the claim.

Covers: SVC-BATCH-005, SVC-BATCH-006, SVC-BATCH-007, SVC-BATCH-008, AUD-BATCH-003.
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

TRADER_PHONE = "+989120005001"
IBAN = "IR060120000000000000000045"

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

    ids = {
        name: uuid.uuid4()
        for name in ("trader", "beneficiary", "profile", "version", "account", "mapping")
    }

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'Replace Trader', %s, 'active', 'approved')",
            (ids["trader"], TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (ids["trader"], TRADER_PHONE, encoded),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'Ali Five', %s, %s, 'active', "
            "'not_checked')",
            (ids["beneficiary"], ids["trader"], IBAN, IBAN),
        )
        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'mellat', 'Bank Mellat', 'active')",
            (ids["profile"],),
        )
        connection.execute(
            "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, status, "
            "default_transfer_limit_irr, after_cutoff_transfer_limit_irr, cutoff_time, "
            "splitting_enabled, required_fields, rules, config_hash) "
            "VALUES (%s, %s, 1, 'active', %s, NULL, NULL, TRUE, '{}', '{}', %s)",
            (ids["version"], ids["profile"], LIMIT, "3" * 64),
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
            (ids["mapping"], ids["version"], "4" * 64),
        )
        for username, role in (
            ("replace_accountant", "accountant"),
            # Holds `payment_batch.read` and neither `payment_batch_version.create` nor
            # `payment_batch.cancel_draft` (`:276-280`), so both permission negatives prove the
            # route wants *its* grant rather than merely some batch grant.
            ("replace_business_admin", "business_admin"),
            ("replace_manager", "manager"),
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
    assert (
        client.post(
            "/api/v1/auth/trader/login",
            json={"identifier": TRADER_PHONE, "password": PASSWORD},
        ).status_code
        == 200
    )


def sign_in_admin(client: Any, username: str) -> None:
    client.cookies.clear()
    assert (
        client.post(
            "/api/v1/auth/admin/login", json={"identifier": username, "password": PASSWORD}
        ).status_code
        == 200
    )


def csrf(client: Any) -> dict[str, str]:
    token = client.cookies.get(TRADER_CSRF_COOKIE) or client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token
    return {CSRF_HEADER: token}


def rows(world: dict[str, Any], sql: str, *parameters: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        return connection.execute(sql, parameters).fetchall()


def an_eligible_request(world: dict[str, Any], value: str) -> dict[str, Any]:
    client = world["client"]
    sign_in_trader(client)
    created = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiary_id"]),
            "amount": {"value": value, "unit": "IRR"},
            "description": "to be replaced",
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

    sign_in_admin(client, "replace_accountant")
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


def _selection_body(world: dict[str, Any], *selections: dict[str, Any]) -> dict[str, Any]:
    return {
        "items": list(selections),
        "bank_profile_version_id": str(world["version_id"]),
        "bank_account_id": str(world["account_id"]),
        "bank_mapping_id": str(world["mapping_id"]),
    }


def a_batch(world: dict[str, Any], value: str = SPLITS_INTO_TWO) -> dict[str, Any]:
    selection = an_eligible_request(world, value)
    sign_in_admin(world["client"], "replace_accountant")
    response = world["client"].post(
        "/api/v1/payment-batches",
        json=_selection_body(world, selection),
        headers={**csrf(world["client"]), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return {
        "batch_id": body["batch"]["id"],
        "version_id": body["current_version"]["id"],
        "etag": response.headers["ETag"],
        "selection": selection,
        "content_hash": body["current_version"]["content_hash"],
    }


def finalize(world: dict[str, Any], batch: dict[str, Any]) -> Any:
    return world["client"].post(
        f"/api/v1/payment-batches/{batch['batch_id']}/versions/{batch['version_id']}/finalize",
        json={"note": "ready"},
        headers={
            **csrf(world["client"]),
            "If-Match": batch["etag"],
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )


def replace(
    world: dict[str, Any], batch: dict[str, Any], *, etag: str, selection: dict[str, Any]
) -> Any:
    return world["client"].post(
        f"/api/v1/payment-batches/{batch['batch_id']}/versions",
        json={**_selection_body(world, selection), "reason": "wrong selection"},
        headers={
            **csrf(world["client"]),
            "If-Match": etag,
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )


def cancel(world: dict[str, Any], batch: dict[str, Any], *, etag: str) -> Any:
    return world["client"].post(
        f"/api/v1/payment-batches/{batch['batch_id']}/cancel",
        json={},
        headers={
            **csrf(world["client"]),
            "If-Match": etag,
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )


def test_a_replacement_supersedes_and_leaves_the_old_rows_byte_identical(
    world: dict[str, Any],
) -> None:
    """`SVC-BATCH-005`. Every column, before and after, through `row_to_json`.

    The M5 pattern, because "the amount is unchanged" would pass while a status, a timestamp or a
    hash moved. Only two columns on the superseded version may change — `status` and
    `superseded_at`, the two `20260820_0017` granted — and its **items** may change not at all:
    the version is a historical record of what was proposed, and a replacement does not rewrite
    history, it adds to it.
    """

    batch = a_batch(world)
    sign_in_admin(world["client"], "replace_accountant")
    finalized = finalize(world, batch)
    assert finalized.status_code == 200, finalized.text

    before_items = rows(
        world,
        "SELECT row_to_json(i) FROM payment_batch_items i "
        "WHERE payment_batch_version_id = %s ORDER BY row_order",
        batch["version_id"],
    )
    before_version = rows(
        world,
        "SELECT row_to_json(v) FROM payment_batch_versions v WHERE id = %s",
        batch["version_id"],
    )
    assert before_items and before_version

    second = an_eligible_request(world, "700000000")
    sign_in_admin(world["client"], "replace_accountant")
    response = replace(world, batch, etag=finalized.headers["ETag"], selection=second)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["current_version"]["version_number"] == 2
    assert body["current_version"]["status"] == "draft"
    assert body["batch"]["status"] == "draft", (
        "the container did not follow its new current version back to draft; §15.4 draws "
        "`rejected --> draft` and `approval_invalidated --> draft` for exactly this"
    )
    assert body["current_version"]["content_hash"] != batch["content_hash"]

    after_items = rows(
        world,
        "SELECT row_to_json(i) FROM payment_batch_items i "
        "WHERE payment_batch_version_id = %s ORDER BY row_order",
        batch["version_id"],
    )
    assert after_items == before_items, (
        "the superseded version's items changed. They are the historical record of what was "
        "proposed, and the migration grants no UPDATE on that table at all — so this failing "
        "means something reached them by a path nobody intended."
    )

    after_version = rows(
        world,
        "SELECT row_to_json(v) FROM payment_batch_versions v WHERE id = %s",
        batch["version_id"],
    )
    changed = {
        key
        for key, value in after_version[0][0].items()
        if before_version[0][0].get(key) != value
    }
    assert changed == {"status", "superseded_at"}, (
        f"the superseded version changed {sorted(changed)}; only status and superseded_at are "
        "granted, and only those two should move"
    )
    assert after_version[0][0]["status"] == "superseded"
    assert after_version[0][0]["finalized_by_admin_user_id"] is not None, (
        "supersession erased who finalized the old version, which is the identity M7's "
        "separation rule has to compare against"
    )


def test_the_replacement_releases_the_old_allocations_and_keeps_the_evidence(
    world: dict[str, Any],
) -> None:
    """`SVC-BATCH-007`. The row is updated, never deleted, and the item stays.

    `FINANCIAL_INTEGRITY_BASELINE.md:41-43` asks that "allocation/release evidence remain
    immutable and queryable". So after a supersession the old allocation is still there, with a
    `released_at` and a `release_reason` — and the batch item it pointed at is untouched, because
    releasing an allocation does not un-propose the row.
    """

    batch = a_batch(world)
    sign_in_admin(world["client"], "replace_accountant")
    finalized = finalize(world, batch)
    assert finalized.status_code == 200, finalized.text

    original = rows(
        world,
        "SELECT id, payment_attempt_id, payment_batch_item_id FROM payment_attempt_allocations "
        "WHERE payment_batch_version_id = %s ORDER BY payment_batch_item_id",
        batch["version_id"],
    )
    assert original, "the finalized version holds no allocations"

    second = an_eligible_request(world, "800000000")
    sign_in_admin(world["client"], "replace_accountant")
    assert replace(
        world, batch, etag=finalized.headers["ETag"], selection=second
    ).status_code == 201

    released = rows(
        world,
        "SELECT id, released_at, release_reason FROM payment_attempt_allocations "
        "WHERE payment_batch_version_id = %s ORDER BY payment_batch_item_id",
        batch["version_id"],
    )
    assert len(released) == len(original), (
        "an allocation row disappeared. Release is an update, not a delete — deleted evidence is "
        "not queryable, which is the sentence this behaviour comes from."
    )
    for _identifier, released_at, reason in released:
        assert released_at is not None, "an allocation was left active on a superseded version"
        assert reason, "a release recorded a time and no reason, which is half the evidence"

    still_there = rows(
        world,
        "SELECT count(*) FROM payment_batch_items WHERE payment_batch_version_id = %s",
        batch["version_id"],
    )
    assert still_there[0][0] == len(original), "the superseded version's items were removed"


def test_no_sequence_of_replacement_leaves_two_active_allocations(
    world: dict[str, Any],
) -> None:
    """`SVC-BATCH-008`. The baseline's double-payment negative test.

    Replace twice, so the same request's attempts pass through three versions, and then assert
    over the **whole table** that no attempt holds two active allocations. Asserting over the rows
    this test touched would be the weaker claim, and the weaker claim is the one that passes while
    a second batch elsewhere holds the same attempt.

    The partial unique index makes this a property of the database rather than of the code — but
    that is exactly why it is worth checking after a sequence that releases and re-allocates: an
    index only refuses what reaches it, and a release that ran at the wrong moment would let the
    next allocation through legitimately.
    """

    batch = a_batch(world)
    sign_in_admin(world["client"], "replace_accountant")
    etag = finalize(world, batch).headers["ETag"]

    for value in ("600000000", "500000000"):
        selection = an_eligible_request(world, value)
        sign_in_admin(world["client"], "replace_accountant")
        response = replace(world, batch, etag=etag, selection=selection)
        assert response.status_code == 201, response.text
        etag = response.headers["ETag"]

    doubled = rows(
        world,
        "SELECT payment_attempt_id, count(*) FROM payment_attempt_allocations "
        "WHERE released_at IS NULL GROUP BY payment_attempt_id HAVING count(*) > 1",
    )
    assert doubled == [], (
        f"these attempts hold more than one active allocation: {doubled}. That is the double "
        "payment `FINANCIAL_INTEGRITY_BASELINE.md` §2 exists to make impossible."
    )

    versions = rows(
        world,
        "SELECT version_number, status FROM payment_batch_versions "
        "WHERE payment_batch_id = %s ORDER BY version_number",
        batch["batch_id"],
    )
    assert [number for number, _ in versions] == [1, 2, 3]
    assert [status for _, status in versions] == ["superseded", "superseded", "draft"]


def test_supersession_is_recorded_in_the_replacements_own_audit_row(
    world: dict[str, Any],
) -> None:
    """`AUD-BATCH-003`, and G-8 answered without inventing a catalogue name.

    The plan offered two options: catalogue a `payment_batch_version.superseded` action, or let the
    replacement's own creation action carry the record. The second needs no invention —
    `payment_batch_version.created` is catalogued — and it puts "which version replaced which" in
    one row rather than in two that have to be correlated.
    """

    batch = a_batch(world)
    sign_in_admin(world["client"], "replace_accountant")
    etag = finalize(world, batch).headers["ETag"]

    second = an_eligible_request(world, "900000000")
    sign_in_admin(world["client"], "replace_accountant")
    response = replace(world, batch, etag=etag, selection=second)
    assert response.status_code == 201, response.text

    audited = rows(
        world,
        "SELECT action, previous_values, new_values FROM audit_logs "
        "WHERE entity_id = %s AND action = 'payment_batch_version.created'",
        response.json()["current_version"]["id"],
    )
    assert len(audited) == 1, f"expected one creation row, got {len(audited)}"
    _action, previous, new = audited[0]

    assert previous["superseded_version_id"] == batch["version_id"]
    assert previous["superseded_version_number"] == 1
    assert previous["superseded_from_status"] == "ready_for_approval"
    assert previous["released_allocations"] >= 1, (
        "the audit row says no allocations were released, and a superseded finalized version "
        "certainly held some"
    )
    assert new["status"] == "draft"


def test_a_draft_batch_can_be_cancelled_and_its_allocations_are_released(
    world: dict[str, Any],
) -> None:
    """`SVC-BATCH-006`, the permitted origin. §29.2: "Draft/rejected batch may be cancelled".

    No reason is sent, and none is required: §29.2 attaches "with reason" to the
    ready-for-approval case only, so demanding one here would be an unmandated refusal.

    The allocations are released because a cancelled batch that kept them would hold its attempts
    hostage — the index would refuse to allocate them anywhere else, and the trader's eligible
    request would be permanently unbatchable with nothing saying why. That is asserted by
    re-batching the same request afterwards, which is the only proof that matters.
    """

    batch = a_batch(world)
    sign_in_admin(world["client"], "replace_accountant")

    response = cancel(world, batch, etag=batch["etag"])
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"

    released = rows(
        world,
        "SELECT released_at, release_reason FROM payment_attempt_allocations "
        "WHERE payment_batch_version_id = %s",
        batch["version_id"],
    )
    assert released, "the cancelled batch had no allocations to release"
    for released_at, reason in released:
        assert released_at is not None
        assert reason == "the batch was cancelled"

    # The proof: the same request can be batched again. Nothing else demonstrates that the
    # attempts were actually freed rather than merely marked.
    again = world["client"].post(
        "/api/v1/payment-batches",
        json=_selection_body(world, batch["selection"]),
        headers={**csrf(world["client"]), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert again.status_code == 201, (
        f"the request could not be re-batched after its batch was cancelled: {again.text}"
    )


def test_a_finalized_batch_is_cancellable_by_the_accountant_and_releases_its_allocations(
    world: dict[str, Any],
) -> None:
    """`SVC-BATCH-006`'s second origin, opened by G-5.

    Until the owner's 2026-08-25 decision this was refused and the refusal named
    DOC-CONFLICT-056: §29.2 permits cancelling a ready-for-approval batch "with reason" and
    `permission_catalog.yaml` held no permission that authorised it, so the rule was unreachable
    under deny-by-default. It stays with the **accountant** — nothing has been decided yet, so
    they are undoing their own work — which is why the assertion here is a 200 for the same
    caller the old refusal was written against.

    The release is asserted for the reason this whole module exists: a cancellation that kept its
    allocations would leave the trader's request permanently unbatchable.

    `tests/integration/test_batch_cancellation.py` carries the rest — the approved origin, both
    directions of the permission split, and the `rejected` origin that is still refused.
    """

    batch = a_batch(world)
    sign_in_admin(world["client"], "replace_accountant")
    finalized = finalize(world, batch)
    assert finalized.status_code == 200, finalized.text

    response = cancel(world, batch, etag=finalized.headers["ETag"])
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"

    changed = rows(
        world,
        "SELECT status, cancelled_at FROM payment_batches WHERE id = %s",
        batch["batch_id"],
    )
    assert changed[0][0] == "cancelled"
    assert changed[0][1] is not None

    released = rows(
        world,
        "SELECT released_at FROM payment_attempt_allocations WHERE payment_batch_version_id = %s",
        batch["version_id"],
    )
    assert released, "the cancelled batch had no allocations to release"
    assert all(released_at is not None for (released_at,) in released)


def test_a_cancelled_batch_takes_no_replacement(world: dict[str, Any]) -> None:
    """§15.4 draws no arrow out of `cancelled`, and `status_catalog.yaml:370` marks it terminal.

    A replacement on a cancelled batch would revive it — the container's status is a projection of
    its current version's, so a new draft version would move it back to `draft` and the
    cancellation would silently become undone.
    """

    batch = a_batch(world)
    sign_in_admin(world["client"], "replace_accountant")
    cancelled = cancel(world, batch, etag=batch["etag"])
    assert cancelled.status_code == 200, cancelled.text

    selection = an_eligible_request(world, "400000000")
    sign_in_admin(world["client"], "replace_accountant")
    response = replace(world, batch, etag=cancelled.headers["ETag"], selection=selection)
    assert response.status_code == 400, response.text
    assert "cancelled" in response.text


def test_replacing_needs_the_version_create_permission(world: dict[str, Any]) -> None:
    """`business_admin` holds `payment_batch.read` and not `payment_batch_version.create`."""

    batch = a_batch(world)
    sign_in_admin(world["client"], "replace_accountant")
    etag = finalize(world, batch).headers["ETag"]
    selection = an_eligible_request(world, "300000000")

    for username in ("replace_business_admin", "replace_manager"):
        sign_in_admin(world["client"], username)
        refused = replace(world, batch, etag=etag, selection=selection)
        assert refused.status_code == 403, f"{username}: {refused.text}"

    sign_in_trader(world["client"])
    assert replace(world, batch, etag=etag, selection=selection).status_code == 403

    sign_in_admin(world["client"], "replace_accountant")
    assert replace(world, batch, etag=etag, selection=selection).status_code == 201


def test_cancelling_a_draft_needs_the_cancel_draft_permission(world: dict[str, Any]) -> None:
    """`payment_batch.cancel_draft` is `accountant`-only (`:466`), and still is after G-5.

    **The two refusals now happen at different layers, and that is the point.**
    `replace_business_admin` holds neither cancellation grant, so the route's dependency refuses
    before the batch is read. `replace_manager` holds `cancel_approved` and reaches the handler,
    where `authority_for_cancelling` sees a draft and refuses on the state.

    Same status code, different mechanism — which is why
    `tests/integration/test_batch_cancellation.py` asserts the manager case again with the
    catalogue read back, so a 403 that arrived for the wrong reason cannot pass for this one.
    """

    batch = a_batch(world)

    for username in ("replace_business_admin", "replace_manager"):
        sign_in_admin(world["client"], username)
        refused = cancel(world, batch, etag=batch["etag"])
        assert refused.status_code == 403, f"{username}: {refused.text}"

    sign_in_trader(world["client"])
    assert cancel(world, batch, etag=batch["etag"]).status_code == 403

    sign_in_admin(world["client"], "replace_accountant")
    assert cancel(world, batch, etag=batch["etag"]).status_code == 200


def test_a_repeated_key_replays_both_commands(world: dict[str, Any]) -> None:
    """Neither a second version nor a second cancellation on a retry.

    `command_catalog.yaml:124` says `"idempotency": "required"` for the replacement. For the
    cancellation there is **no row at all** — G-4 — so the requirement is inferred from its
    neighbours, and this is what makes the inference testable: without a replay, a retry would
    release allocations twice and overwrite the reason the first release recorded.
    """

    batch = a_batch(world)
    sign_in_admin(world["client"], "replace_accountant")
    etag = finalize(world, batch).headers["ETag"]
    selection = an_eligible_request(world, "250000000")
    sign_in_admin(world["client"], "replace_accountant")

    key = str(uuid.uuid4())
    body = {**_selection_body(world, selection), "reason": "same request twice"}
    path = f"/api/v1/payment-batches/{batch['batch_id']}/versions"
    headers = {**csrf(world["client"]), "If-Match": etag, "Idempotency-Key": key}

    first = world["client"].post(path, json=body, headers=headers)
    assert first.status_code == 201, first.text
    second = world["client"].post(path, json=body, headers=headers)
    assert second.status_code == 201, second.text
    assert second.json()["replayed"] is True
    assert second.json()["current_version"]["id"] == first.json()["current_version"]["id"]

    made = rows(
        world,
        "SELECT count(*) FROM payment_batch_versions WHERE payment_batch_id = %s",
        batch["batch_id"],
    )
    assert made[0][0] == 2, "the retry created a third version"

    cancel_key = str(uuid.uuid4())
    cancel_path = f"/api/v1/payment-batches/{batch['batch_id']}/cancel"
    cancel_headers = {
        **csrf(world["client"]),
        "If-Match": first.headers["ETag"],
        "Idempotency-Key": cancel_key,
    }
    assert world["client"].post(cancel_path, json={}, headers=cancel_headers).status_code == 200
    replayed = world["client"].post(cancel_path, json={}, headers=cancel_headers)
    assert replayed.status_code == 200, replayed.text

    audited = rows(
        world,
        "SELECT count(*) FROM audit_logs WHERE action = 'payment_batch.cancelled' "
        "AND entity_id = %s",
        batch["batch_id"],
    )
    assert audited[0][0] == 1, "the replayed cancellation wrote a second audit row"


def test_both_commands_require_both_headers(world: dict[str, Any]) -> None:
    """Four refusals, and none of them writes.

    `If-Match` and `Idempotency-Key` answer different questions — "is the batch still in the state
    you read" and "have I already sent this" — so each is refused separately and a caller who
    omitted the wrong one is told which.

    Written because a negative control dropped the replacement's `If-Match` requirement and
    **nothing failed**: every other test in this file sends both headers, so the file proved the
    headers *worked* and never that they were *required*. `command_catalog.yaml:122-124` says
    `if_match_batch_required` and `"idempotency": "required"` for the replacement; the
    cancellation has no row at all (G-4) and inherits the same contract from its neighbours,
    which is exactly why it needs asserting rather than citing.
    """

    batch = a_batch(world)
    sign_in_admin(world["client"], "replace_accountant")
    selection = an_eligible_request(world, "220000000")
    sign_in_admin(world["client"], "replace_accountant")

    versions_before = rows(
        world,
        "SELECT count(*) FROM payment_batch_versions WHERE payment_batch_id = %s",
        batch["batch_id"],
    )[0][0]

    replacement_path = f"/api/v1/payment-batches/{batch['batch_id']}/versions"
    cancel_path = f"/api/v1/payment-batches/{batch['batch_id']}/cancel"
    body = _selection_body(world, selection)

    for path, payload in ((replacement_path, body), (cancel_path, {})):
        no_match = world["client"].post(
            path,
            json=payload,
            headers={**csrf(world["client"]), "Idempotency-Key": str(uuid.uuid4())},
        )
        assert no_match.status_code == 428, f"{path} without If-Match: {no_match.text}"

        no_key = world["client"].post(
            path,
            json=payload,
            headers={**csrf(world["client"]), "If-Match": batch["etag"]},
        )
        assert no_key.status_code == 428, f"{path} without Idempotency-Key: {no_key.text}"

    assert (
        rows(
            world,
            "SELECT count(*) FROM payment_batch_versions WHERE payment_batch_id = %s",
            batch["batch_id"],
        )[0][0]
        == versions_before
    ), "a refused call created a version"

    still_draft = rows(
        world, "SELECT status, cancelled_at FROM payment_batches WHERE id = %s", batch["batch_id"]
    )
    assert still_draft[0] == ("draft", None), "a refused call cancelled the batch"


def test_a_malformed_if_match_is_refused_rather_than_guessed(world: dict[str, Any]) -> None:
    """412, and not a default.

    The control that found the gap above replaced the missing-header refusal with a *default* of
    `"rv-1"`, which is the shape of the mistake worth naming: a precondition that falls back to a
    guess is not a precondition. `api_error_catalog.yaml` gives 412 the meaning "If-Match value is
    stale", and a value the parser cannot read is a caller who cannot be told their precondition
    held.
    """

    batch = a_batch(world)
    sign_in_admin(world["client"], "replace_accountant")

    for value in ('"nonsense"', '"rv-"', "rv-1", '"rv-abc"'):
        response = world["client"].post(
            f"/api/v1/payment-batches/{batch['batch_id']}/cancel",
            json={},
            headers={
                **csrf(world["client"]),
                "If-Match": value,
                "Idempotency-Key": str(uuid.uuid4()),
            },
        )
        # `rv-1` unquoted is well-formed — the parser strips quotes — so it reaches the
        # compare-and-swap and is refused as stale or accepted on its merits. Everything else is
        # unreadable and must be 412.
        if value == "rv-1":
            assert response.status_code in {200, 412}, response.text
            continue
        assert response.status_code == 412, f"{value}: {response.text}"
