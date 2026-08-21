"""Finalization: nine guards, one hash that has to recompute, and rows that stop being editable.

M6 slice 3. `06_Workflows_and_State_Machines.md` §16.2 and `05_API_Specification.md:1381-1388`
between them list nine things the server must verify, and every one of them is a fact that can
change between creating a batch and finalizing it — a trader files a correction, an accountant
releases an allocation, an administrator supersedes a bank profile version. So each guard is
tested by *making the thing change*, not by asserting the code contains a branch.

`DB-FINAL-001` is the one that is not about code at all: after finalization the items cannot be
updated, and that is true because `20260820_0017` grants the runtime roles no `UPDATE` on
`payment_batch_items` — immutability as the absence of a privilege rather than the presence of a
rule, on the `payment_request_revisions` precedent. It is asserted through the **app role**,
because the owner can do anything and a test using the owner connection would pass whatever the
grants said.

Covers: SVC-FINAL-001, SVC-FINAL-002, SVC-FINAL-003, DB-FINAL-001, AUD-BATCH-002.
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

TRADER_PHONE = "+989120004001"
IBAN = "IR060120000000000000000044"

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
            "approval_status) VALUES (%s, 'Final Trader', %s, 'active', 'approved')",
            (ids["trader"], TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (ids["trader"], TRADER_PHONE, encoded),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'Ali Four', %s, %s, 'active', "
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
            ("final_accountant", "accountant"),
            # Holds `payment_batch.read` and `payment_batch_version.read_approval_view` by
            # explicit grant but **not** `payment_batch_version.finalize` (`:276-280`). That is
            # what makes the permission negative prove the route wants *this* grant rather than
            # merely some batch grant — the distinction slice 1's ninth negative control showed
            # a behavioural test cannot otherwise make.
            ("final_business_admin", "business_admin"),
            ("final_manager", "manager"),
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


def a_draft_batch(world: dict[str, Any], value: str = SPLITS_INTO_TWO) -> dict[str, Any]:
    """A batch with one request's rows, through the real create route."""

    client = world["client"]
    sign_in_trader(client)
    created = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiary_id"]),
            "amount": {"value": value, "unit": "IRR"},
            "description": "to be finalized",
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

    sign_in_admin(client, "final_accountant")
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
        "batch_id": body["batch"]["id"],
        "version_id": body["current_version"]["id"],
        "record_version": body["batch"]["record_version"],
        "content_hash": body["current_version"]["content_hash"],
        "request_id": request_id,
        "revision_id": revision_id,
        "etag": batch.headers["ETag"],
    }


def finalize(
    world: dict[str, Any],
    draft: dict[str, Any],
    *,
    key: str | None = None,
    etag: str | None = None,
    note: str | None = "validated",
) -> Any:
    client = world["client"]
    return client.post(
        f"/api/v1/payment-batches/{draft['batch_id']}/versions/{draft['version_id']}/finalize",
        json={"note": note},
        headers={
            **csrf(client),
            "If-Match": etag or draft["etag"],
            "Idempotency-Key": key or str(uuid.uuid4()),
        },
    )


def test_a_draft_becomes_ready_for_approval_and_both_statuses_move(
    world: dict[str, Any],
) -> None:
    """The transition document 06 §16.2 draws, plus the projection that has to follow it.

    The container's status is a materialised view of its current version's — nine of the
    batch's eleven catalogue states are `derived: true` — so finalizing the version without
    moving the batch would make `CON-BATCH-004` false the instant this command committed. Both
    are asserted here, and the projection is re-checked across every batch in the database.
    """

    draft = a_draft_batch(world)
    sign_in_admin(world["client"], "final_accountant")

    response = finalize(world, draft)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["version"]["status"] == "ready_for_approval"
    assert body["batch"]["status"] == "ready_for_approval"
    assert body["replayed"] is False
    assert body["batch"]["record_version"] == draft["record_version"] + 1
    assert response.headers["ETag"] == f'"rv-{body["batch"]["record_version"]}"'

    # The hash does not change: finalization freezes content, it does not alter it. A different
    # hash here would mean the version a manager approves is not the version that was built.
    assert body["version"]["content_hash"] == draft["content_hash"]

    disagreements = rows(
        world,
        "SELECT b.batch_number, b.status, v.status FROM payment_batches b "
        "JOIN payment_batch_versions v ON v.id = b.current_version_id WHERE b.status <> v.status",
    )
    assert disagreements == [], f"a container's status drifted from its version: {disagreements}"


def test_the_finalizer_is_recorded_from_the_session(world: dict[str, Any]) -> None:
    """`SEC-FINAL-001`, read back from the row.

    `FINANCIAL_INTEGRITY_BASELINE.md` §5 requires a *recorded* finalizer that M7 must refuse as
    an approver. Document 04 §11.5 has no such column — `DOC-CONFLICT-055` — so
    `20260821_0018` added one, and this is what makes the column evidence rather than decoration.

    Also asserted: the finalizer is **not** silently the creator. Both are `final_accountant`
    here because one fixture cannot be two people, so the check is that the column is populated
    and equals the acting session's admin user, which is the part a future two-accountant flow
    depends on.
    """

    draft = a_draft_batch(world)
    sign_in_admin(world["client"], "final_accountant")
    assert finalize(world, draft).status_code == 200

    recorded = rows(
        world,
        "SELECT v.finalized_by_admin_user_id, v.created_by_admin_user_id, u.username "
        "FROM payment_batch_versions v "
        "JOIN admin_users u ON u.id = v.finalized_by_admin_user_id WHERE v.id = %s",
        draft["version_id"],
    )
    assert len(recorded) == 1, "no finalizer was recorded, so M7 has nothing to compare against"
    finalized_by, created_by, username = recorded[0]
    assert username == "final_accountant"
    assert finalized_by is not None
    del created_by  # equal here by fixture; the separation M7 enforces needs the column, not this


def test_a_draft_without_every_allocation_cannot_finalize(world: dict[str, Any]) -> None:
    """`SVC-FINAL-002`. `FINANCIAL_INTEGRITY_BASELINE.md:44-45`, provoked rather than reasoned.

    The allocation is deleted directly, because release needs an `UPDATE` grant slice 4 has not
    added yet — the absence `tests/integration/test_batch_creation.py` proves. Deleting produces
    the same state finalization must refuse: a row in a version that no longer owns the attempt,
    so another version could claim it and the same money could leave twice.
    """

    draft = a_draft_batch(world)

    allocations = rows(
        world,
        "SELECT id FROM payment_attempt_allocations WHERE payment_batch_version_id = %s "
        "ORDER BY payment_batch_item_id LIMIT 1",
        draft["version_id"],
    )
    assert allocations, "the draft has no allocations, so this test would prove nothing"

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "DELETE FROM payment_attempt_allocations WHERE id = %s", (allocations[0][0],)
        )
        connection.commit()

    sign_in_admin(world["client"], "final_accountant")
    response = finalize(world, draft)
    assert response.status_code == 400, response.text
    assert "active allocation" in response.text

    still_draft = rows(
        world, "SELECT status FROM payment_batch_versions WHERE id = %s", draft["version_id"]
    )
    assert still_draft[0][0] == "draft", "the refusal left the version half-finalized"


def test_a_changed_total_is_refused_even_though_the_rows_are_untouched(
    world: dict[str, Any],
) -> None:
    """`SVC-FINAL-003`, provoked so that **only** the totals check can fire.

    The version's stored `total_amount_irr` is changed and no row is, so the content hash still
    recomputes correctly and the row count still matches. That isolation is the point: an earlier
    version of this file asserted "the hash failed *or* the total failed", which meant removing
    either guard left the other firing and the test passed both times. A disjunction written to
    avoid depending on execution order ended up unable to detect a missing guard.

    `04_Database_Schema.md:171` is what makes this exact rather than approximate: "Exact equality
    is required unless a future explicitly modeled fee/rounding component is introduced."
    """

    draft = a_draft_batch(world)

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE payment_batch_versions SET total_amount_irr = total_amount_irr + 1 "
            "WHERE id = %s",
            (draft["version_id"],),
        )
        connection.commit()

    sign_in_admin(world["client"], "final_accountant")
    response = finalize(world, draft)
    assert response.status_code == 400, response.text
    assert "rows sum to" in response.text, response.text
    assert "content hash" not in response.text, (
        "the hash guard fired too, so this provocation is not isolating the totals check"
    )


def test_an_edited_row_is_refused_even_though_the_total_still_sums(
    world: dict[str, Any],
) -> None:
    """`SVC-FINAL-001`, provoked so that **only** the hash recomputation can fire.

    The beneficiary name on one row is changed. It is part of the row hash and the content hash
    and is not part of any sum, so the counts and the total still agree and the only thing that
    can notice is the recomputation.

    That is also the change that matters most. An amount is checked twice over; a **payee name**
    is checked by nothing except the hash — and a row whose name was edited after a manager
    approved it pays the right amount to the wrong person.

    The edit goes through the owner connection because the runtime roles hold no `UPDATE` on
    `payment_batch_items` at all, which `test_batching_table_privileges.py` states as a matrix.
    So this simulates the one actor the grants cannot stop: a privileged operator, or a future
    migration.
    """

    draft = a_draft_batch(world)

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE payment_batch_items SET beneficiary_name_snapshot = %s "
            "WHERE payment_batch_version_id = %s AND row_order = 1",
            ("Someone Else", draft["version_id"]),
        )
        connection.commit()

    sign_in_admin(world["client"], "final_accountant")
    response = finalize(world, draft)
    assert response.status_code == 400, response.text
    assert "content hash" in response.text, response.text
    assert "rows sum to" not in response.text, (
        "the totals guard fired too, so this provocation is not isolating the hash check"
    )


def test_a_row_count_that_disagrees_with_the_rows_is_refused(world: dict[str, Any]) -> None:
    """The third guard in the same sentence, isolated the same way.

    A row is deleted rather than added: adding one would need a unique `row_order` and an
    allocation, and would trip several guards at once. Deleting the last row leaves `row_count`
    one too high while every remaining row is untouched — so the count check is the first thing
    that can notice, before the total or the hash.
    """

    draft = a_draft_batch(world)

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        # The allocation references the item, so it goes first. Both are the owner's to remove;
        # neither runtime role holds `DELETE` on either table.
        connection.execute(
            "DELETE FROM payment_attempt_allocations WHERE payment_batch_item_id IN "
            "(SELECT id FROM payment_batch_items WHERE payment_batch_version_id = %s "
            "ORDER BY row_order DESC LIMIT 1)",
            (draft["version_id"],),
        )
        connection.execute(
            "DELETE FROM payment_batch_items WHERE id IN "
            "(SELECT id FROM payment_batch_items WHERE payment_batch_version_id = %s "
            "ORDER BY row_order DESC LIMIT 1)",
            (draft["version_id"],),
        )
        connection.commit()

    sign_in_admin(world["client"], "final_accountant")
    response = finalize(world, draft)
    assert response.status_code == 400, response.text
    assert "rows and holds" in response.text, response.text


def test_a_superseded_revision_stops_its_batch_from_finalizing(world: dict[str, Any]) -> None:
    """Document 06 §16.2: "selected request revisions are still current and eligible".

    **The state this guards against cannot be reached through M6's API, and that is a finding
    rather than a reason to drop the test.** Trying to reach it the honest way is how it turned
    up: `request-correction` refuses a request at `eligible_for_batching` — it moves one from
    `submitted_to_center` or `under_accountant_review` — and `create_revision` accepts only
    `draft` or `needs_trader_correction`. So once an accountant marks a request eligible, no M5
    command can give it a newer revision. The trader's remedy from that state is cancellation,
    which §29.1 permits and M5 slice 7 implemented; editing is not on offer.

    The guard is still required. Document 06 §16.2 lists it, and the paths that reach it are M6
    slice 4's replacement versions and the post-payment corrections of M7 and M8. A guard for a
    state a *later* milestone reaches is not a guard for a state nothing reaches — and writing it
    now, while the reasoning is in front of somebody, is cheaper than writing it in M8 next to
    code that assumes it already exists.

    So the newer revision is inserted directly, the same technique
    `test_a_draft_without_every_allocation_cannot_finalize` uses and for the same reason: the
    test's job is to prove the guard fires, not to prove M5 has a route to the state.
    """

    draft = a_draft_batch(world)

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        original = connection.execute(
            "SELECT payment_request_id, beneficiary_id, beneficiary_name_snapshot, "
            "beneficiary_iban_snapshot, amount_irr FROM payment_request_revisions WHERE id = %s",
            (draft["revision_id"],),
        ).fetchone()
        assert original is not None
        request_id, beneficiary_id, name, iban, amount = original

        # Revision 2, with a different amount so its content hash differs — the table's
        # `UNIQUE(payment_request_id, content_hash)` would otherwise refuse a copy, which is M5
        # slice 3's rule that a correction changing nothing is not a correction.
        replacement = connection.execute(
            "INSERT INTO payment_request_revisions (payment_request_id, revision_number, "
            "beneficiary_id, beneficiary_name_snapshot, beneficiary_iban_snapshot, amount_irr, "
            "content_hash, created_by_actor_type) "
            "VALUES (%s, 2, %s, %s, %s, %s, %s, 'trader_user') RETURNING id",
            (request_id, beneficiary_id, name, iban, amount - 1, "9" * 64),
        ).fetchone()
        assert replacement is not None
        connection.execute(
            "UPDATE payment_requests SET current_revision_id = %s WHERE id = %s",
            (replacement[0], request_id),
        )
        connection.commit()

    sign_in_admin(world["client"], "final_accountant")
    response = finalize(world, draft)
    assert response.status_code == 400, response.text
    assert "newer revision" in response.text, response.text

    still_draft = rows(
        world, "SELECT status FROM payment_batch_versions WHERE id = %s", draft["version_id"]
    )
    assert still_draft[0][0] == "draft", "the refusal left the version half-finalized"


def test_a_request_that_left_eligible_stops_its_batch_from_finalizing(
    world: dict[str, Any],
) -> None:
    """The second half of the same sentence: "and eligible".

    Reached through the real API, because this half *is* reachable: `payment_request.cancel` is
    permitted from `eligible_for_batching` (§29.1, and M5 slice 7's `CANCELLABLE`), and it is the
    remedy a trader actually has once their request is queued.

    A cancelled request in a bank file is money leaving for something the trader withdrew. The
    allocation still exists — cancelling a request does not release it, which is slice 4's work —
    so nothing but this guard stands between the cancellation and the payment.
    """

    draft = a_draft_batch(world)
    client = world["client"]

    current = rows(
        world, "SELECT record_version FROM payment_requests WHERE id = %s", draft["request_id"]
    )
    sign_in_trader(client)
    cancelled = client.post(
        f"/api/v1/payment-requests/{draft['request_id']}/cancel",
        json={},
        headers={**csrf(client), "If-Match": f'"rv-{current[0][0]}"'},
    )
    assert cancelled.status_code == 200, cancelled.text

    sign_in_admin(client, "final_accountant")
    response = finalize(world, draft)
    assert response.status_code == 400, response.text
    assert "no longer eligible" in response.text, response.text


def test_a_version_carrying_a_validation_error_cannot_finalize(world: dict[str, Any]) -> None:
    """Document 06 §16.2: "no validation error exists".

    **Nothing in M6 produces a validation error, and that is why this test exists.**
    `create_batch` writes `{"errors": [], "warnings": []}` unconditionally and the preview returns
    the same, so the guard could be deleted and every other test would still pass — which is
    exactly what a negative control reported. A guard nothing can trigger is indistinguishable
    from a guard that is not there.

    The error is written into the summary directly, the same technique the allocation and revision
    guards use. Producing errors is not M6's: the plan's slice-3 heading names the validation
    summary but assigns no obligation to *filling* it, and the things that will fill it are M7's
    export validation and the beneficiary block/override warnings document 06 §16.2 also lists.
    What M6 owes is that the column exists, is read, and refuses finalization when it is not
    empty — and that is now asserted rather than assumed.

    `warnings` are deliberately not tested as a refusal, because §16.2 refuses on *errors* only:
    "beneficiary block/override warnings are **resolved**" is a separate clause about a mechanism
    M6 does not have. Treating a warning as blocking would be an unmandated refusal.
    """

    draft = a_draft_batch(world)

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE payment_batch_versions SET validation_summary = %s WHERE id = %s",
            ('{"errors": ["beneficiary iban failed a check"], "warnings": []}',
             draft["version_id"]),
        )
        connection.commit()

    sign_in_admin(world["client"], "final_accountant")
    response = finalize(world, draft)
    assert response.status_code == 400, response.text
    assert "validation error" in response.text, response.text
    assert "beneficiary iban failed a check" in response.text, (
        "the refusal does not name the error, so an accountant is told to fix something without "
        "being told what"
    )

    still_draft = rows(
        world, "SELECT status FROM payment_batch_versions WHERE id = %s", draft["version_id"]
    )
    assert still_draft[0][0] == "draft"


def test_a_warning_alone_does_not_block_finalization(world: dict[str, Any]) -> None:
    """The other half of the same clause, and the unmandated refusal it would be.

    §16.2 lists "no validation error exists" and, separately, "beneficiary block/override warnings
    are resolved". A warning is not an error, and refusing on one would be a stricter rule than
    any document states — the mirror of the unmandated *side effect* this milestone has been
    avoiding, and the same mistake M5 slice 7 made by requiring a cancellation reason §29.1 does
    not ask for.
    """

    draft = a_draft_batch(world)

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE payment_batch_versions SET validation_summary = %s WHERE id = %s",
            ('{"errors": [], "warnings": ["beneficiary was added recently"]}',
             draft["version_id"]),
        )
        connection.commit()

    sign_in_admin(world["client"], "final_accountant")
    response = finalize(world, draft)
    assert response.status_code == 200, response.text
    assert response.json()["version"]["validation_summary"]["warnings"] == [
        "beneficiary was added recently"
    ], "the warning was dropped; a manager should see what the accountant saw"


def test_a_superseded_bank_profile_version_stops_finalization(world: dict[str, Any]) -> None:
    """Document 06 §16.2: "bank profile/mapping/account remain valid".

    A manager approving a version built on retired configuration would be approving a file that
    cannot be produced: M7 renders the export from exactly these three rows.
    """

    draft = a_draft_batch(world)

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE bank_mappings SET status = 'retired' WHERE id = %s",
            (world["mapping_id"],),
        )
        connection.commit()
    try:
        sign_in_admin(world["client"], "final_accountant")
        response = finalize(world, draft)
        assert response.status_code == 400, response.text
        assert "mapping" in response.text
    finally:
        with psycopg.connect(_psycopg(world["owner_url"])) as connection:
            connection.execute(
                "UPDATE bank_mappings SET status = 'active' WHERE id = %s",
                (world["mapping_id"],),
            )
            connection.commit()


def test_a_finalized_version_cannot_be_finalized_again(world: dict[str, Any]) -> None:
    """`draft -> ready_for_approval` is the only arrow into finalization.

    With a *fresh* idempotency key, so this is the state guard answering rather than the replay.
    A second finalization would move the batch's record version again and write a second audit
    row claiming the same version became immutable twice.
    """

    draft = a_draft_batch(world)
    sign_in_admin(world["client"], "final_accountant")

    first = finalize(world, draft)
    assert first.status_code == 200, first.text

    again = finalize(world, draft, etag=first.headers["ETag"], key=str(uuid.uuid4()))
    assert again.status_code == 400, again.text
    assert "only a draft may be finalized" in again.text


def test_a_repeated_idempotency_key_replays_instead_of_refusing(
    world: dict[str, Any],
) -> None:
    """The difference the key makes, and why the catalogue requires one.

    Without the replay, a retry after a network timeout would meet the `draft`-only guard and be
    told the version is already `ready_for_approval` — a failure reported for work that
    succeeded. The audit row is written once, which is the part that matters for a log somebody
    later reads to reconstruct who froze what.
    """

    draft = a_draft_batch(world)
    sign_in_admin(world["client"], "final_accountant")
    key = str(uuid.uuid4())

    first = finalize(world, draft, key=key)
    assert first.status_code == 200, first.text

    second = finalize(world, draft, key=key)
    assert second.status_code == 200, second.text
    assert second.json()["replayed"] is True
    assert second.json()["version"]["id"] == first.json()["version"]["id"]

    audited = rows(
        world,
        "SELECT count(*) FROM audit_logs WHERE action = 'payment_batch_version.finalized' "
        "AND entity_id = %s",
        draft["version_id"],
    )
    assert audited[0][0] == 1, "the replay wrote a second audit row"


def test_finalization_writes_its_catalogued_action_and_the_one_event_it_owes(
    world: dict[str, Any],
) -> None:
    """`AUD-BATCH-002`, and the outbox event creation deliberately did not publish.

    `command_catalog.yaml:140` gives this command
    `"outbox_event": "PaymentBatchVersionReadyForApproval"` where `payment_batch.create` had
    `null`. So the assertion is both halves: this action, and this event, and no other.

    The payload is checked for what it does **not** carry. `payment_request._publish` puts
    identifiers on a queue and nothing else, and the same reasoning applies harder here: a
    beneficiary IBAN on a message bus is a payment destination in a second place, and a consumer
    that needs one can read the version through an authorised route.
    """

    draft = a_draft_batch(world)
    sign_in_admin(world["client"], "final_accountant")
    assert finalize(world, draft).status_code == 200

    actions = rows(
        world,
        "SELECT action FROM audit_logs WHERE entity_id = %s ORDER BY action",
        draft["version_id"],
    )
    assert [action for (action,) in actions] == ["payment_batch_version.finalized"]

    events = rows(
        world,
        "SELECT event_type, payload FROM outbox_events WHERE aggregate_id = %s",
        draft["version_id"],
    )
    assert len(events) == 1, f"expected exactly one outbox event, got {events}"
    event_type, payload = events[0]
    assert event_type == "PaymentBatchVersionReadyForApproval"
    assert payload["content_hash"] == draft["content_hash"]
    for absent in ("beneficiary_iban", "beneficiary_name", "rows", "items"):
        assert absent not in payload, (
            f"the outbox payload carries {absent!r}; a payment destination on a message bus is "
            "a payment destination in a second place"
        )


def test_a_finalized_versions_rows_cannot_be_updated_by_the_runtime_role(
    world: dict[str, Any],
) -> None:
    """`DB-FINAL-001`. Immutability as the absence of a privilege.

    `20260820_0017` grants the runtime roles no `UPDATE` on `payment_batch_items` at all — not
    column-level, not on one column: none. So this is not a rule the application enforces and
    could forget; it is a privilege the database does not hold.

    Asserted through the **app role**. The owner can do anything, so a test using the owner
    connection would pass whatever the grants said — which is exactly how an immutability claim
    becomes decoration.
    """

    draft = a_draft_batch(world)
    sign_in_admin(world["client"], "final_accountant")
    assert finalize(world, draft).status_code == 200

    app_role = world["app_role"]
    assert app_role, "no app role, so this test would prove nothing"

    # **`SET ROLE` is re-issued after every rollback, and that is not defensive.** A `ROLLBACK`
    # reverts `SET ROLE` to the session default, so the first version of this test ran its second
    # statement as the *owner* — which can do anything — and the delete was refused by an
    # unrelated foreign key instead of by a privilege. It looked like a finding about grants and
    # was a finding about `SET ROLE`.
    statements = (
        (
            "UPDATE payment_batch_items SET amount_irr = 1 WHERE payment_batch_version_id = %s",
            "an amount a bank is instructed with",
        ),
        (
            "UPDATE payment_batch_items SET beneficiary_iban_snapshot = %s "
            "WHERE payment_batch_version_id = %s",
            "the destination the money goes to",
        ),
        (
            "DELETE FROM payment_batch_items WHERE payment_batch_version_id = %s",
            "a row from a version a manager is about to approve",
        ),
    )

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        for statement, what in statements:
            connection.execute(f'SET ROLE "{app_role}"')
            parameters: tuple[Any, ...] = (
                (IBAN, draft["version_id"])
                if "beneficiary_iban_snapshot" in statement
                else (draft["version_id"],)
            )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(statement, parameters)
            assert what  # named so a failure says which write was permitted
            connection.rollback()


def test_a_stale_if_match_is_refused_and_writes_nothing(world: dict[str, Any]) -> None:
    """`command_catalog.yaml:139`'s `if_match_batch_and_lock_current_version`, first half.

    The accountant is acting on a screen that has moved. Refused with 409 and nothing written:
    a half-finalized version is worse than a refusal, because a manager could be shown it.
    """

    draft = a_draft_batch(world)
    sign_in_admin(world["client"], "final_accountant")

    # **412, not 409.** `api_error_catalog.yaml` gives 412 the meaning "If-Match value is stale",
    # and `compare_and_swap` raises `VersionConflictError` for exactly that. The first version of
    # this test expected 409 because the command had an unreachable `rows_affected == 0` branch
    # that raised one — dead code shaped like a guard, now removed. The helper's answer was right
    # and the branch that contradicted it was both dead and wrong.
    response = finalize(world, draft, etag='"rv-99"')
    assert response.status_code == 412, response.text

    still_draft = rows(
        world,
        "SELECT status, finalized_by_admin_user_id FROM payment_batch_versions WHERE id = %s",
        draft["version_id"],
    )
    assert still_draft[0] == ("draft", None)


def test_both_headers_are_required(world: dict[str, Any]) -> None:
    """Missing either is 428, and neither writes.

    Two separate refusals rather than one, because they answer different questions and a client
    that omitted the wrong one needs to be told which.
    """

    draft = a_draft_batch(world)
    client = world["client"]
    sign_in_admin(client, "final_accountant")
    path = f"/api/v1/payment-batches/{draft['batch_id']}/versions/{draft['version_id']}/finalize"

    no_key = client.post(
        path, json={"note": None}, headers={**csrf(client), "If-Match": draft["etag"]}
    )
    assert no_key.status_code == 428, no_key.text

    no_match = client.post(
        path,
        json={"note": None},
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert no_match.status_code == 428, no_match.text

    assert (
        rows(world, "SELECT status FROM payment_batch_versions WHERE id = %s", draft["version_id"])[
            0
        ][0]
        == "draft"
    )


def test_finalizing_needs_the_finalize_permission(world: dict[str, Any]) -> None:
    """`SEC-FINAL-001`'s access half, and the stronger of the two negatives.

    `business_admin` holds `payment_batch.read` and not `payment_batch_version.finalize`, so this
    proves the route wants *this* grant rather than merely some batch grant. `manager` is the
    other interesting refusal: the role that will eventually **approve** cannot finalize, which
    is `FINANCIAL_INTEGRITY_BASELINE.md` §5 showing up in the permission catalogue before M7
    writes a line of approval code.

    A trader is refused too, and holds no permission at all.
    """

    draft = a_draft_batch(world)

    for username in ("final_business_admin", "final_manager"):
        sign_in_admin(world["client"], username)
        refused = finalize(world, draft)
        assert refused.status_code == 403, f"{username}: {refused.text}"

    sign_in_trader(world["client"])
    assert finalize(world, draft).status_code == 403

    sign_in_admin(world["client"], "final_accountant")
    assert finalize(world, draft).status_code == 200


def test_a_version_that_is_not_the_batchs_current_one_cannot_finalize(
    world: dict[str, Any],
) -> None:
    """Document 06 §16.2's first guard, and a 404 for a version from another batch.

    Two different refusals, and the difference is what a caller may learn: a version belonging to
    a *different* batch is indistinguishable from one that does not exist, because whether an id
    exists elsewhere is not this route's to teach.
    """

    first = a_draft_batch(world)
    second = a_draft_batch(world, "300000000")

    sign_in_admin(world["client"], "final_accountant")
    crossed = world["client"].post(
        f"/api/v1/payment-batches/{first['batch_id']}/versions/{second['version_id']}/finalize",
        json={"note": None},
        headers={
            **csrf(world["client"]),
            "If-Match": first["etag"],
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert crossed.status_code == 404, crossed.text

    unknown = world["client"].post(
        f"/api/v1/payment-batches/{first['batch_id']}/versions/{uuid.uuid4()}/finalize",
        json={"note": None},
        headers={
            **csrf(world["client"]),
            "If-Match": first["etag"],
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert unknown.status_code == 404, unknown.text
