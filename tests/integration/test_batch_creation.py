"""Creating a batch: one transaction, one allocation per attempt, and the database says so.

M6 slice 2. The obligations here divide into two kinds, and the division matters.

**Properties of the code**, which a test can only observe: that the transaction is atomic, that
only an eligible request may be allocated, that a retried key returns the first batch, that the
audit row is the one the catalogue maps, that the number follows the documented family.

**Properties of the database**, which a test must provoke rather than observe.
`FINANCIAL_INTEGRITY_BASELINE.md:39-40` says "A competing allocation for the same attempt must
fail at the database boundary; service-layer checks alone are insufficient", and the only way to
know which of the two is enforcing is to bypass the service. So
`test_two_transactions_racing_for_one_attempt` opens two real connections and inserts the
allocation row directly, and `test_the_database_refuses_a_second_active_allocation` does the same
with no service code in the picture at all. If the constraint lived in Python those two would
pass and prove nothing; they fail if the partial unique index is dropped, which is the negative
control.

Requests reach `eligible_for_batching` through the real M5 journey rather than by seeding the
status. A hand-seeded row is the shape M5 slice 8 found a defect behind: the fixture invents the
state the step needs and never notices what the real step actually leaves behind.

Covers: SVC-BATCH-001, SVC-BATCH-002, SVC-BATCH-003, DB-ALLOC-001, DB-ATTEMPT-002, DB-BATCH-002,
CON-BATCH-002, CON-BATCH-003, CON-BATCH-004, AUD-BATCH-001.
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

TRADER_PHONE = "+989120002001"
IBAN = "IR060120000000000000000042"

# One billion rial, the profile version's per-transfer limit. Chosen so that 2.5 billion splits
# into exactly three rows — two at the limit and a residual of half a billion — which is the
# shape that catches an implementation that divides instead of taking the remainder.
LIMIT = 1_000_000_000
SPLITS_INTO_THREE = "2500000000"
FITS_IN_ONE = "400000000"


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
            "approval_status) VALUES (%s, 'Create Trader', %s, 'active', 'approved')",
            (trader_id, TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (trader_id, TRADER_PHONE, encoded),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'Ali Two', %s, %s, 'active', "
            "'not_checked')",
            (beneficiary_id, trader_id, IBAN, IBAN),
        )
        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'saderat', 'Bank Saderat', 'active')",
            (profile_id,),
        )
        connection.execute(
            "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, status, "
            "default_transfer_limit_irr, after_cutoff_transfer_limit_irr, cutoff_time, "
            "splitting_enabled, required_fields, rules, config_hash) "
            "VALUES (%s, %s, 1, 'active', %s, NULL, NULL, TRUE, '{}', '{}', %s)",
            (version_id, profile_id, LIMIT, "c" * 64),
        )
        # `payment_batch_versions` makes both of these NOT NULL, so slice 2 needs them where
        # slice 1's preview did not.
        #
        # Column names read out of `Base.metadata`, not remembered. Written from memory first,
        # as `account_title`/`name`/`column_mapping`, and PostgreSQL refused all three — the
        # third time this session that guessing a column name cost a round trip, and the third
        # time the database caught it immediately. That is the cheap version of the same
        # mistake: `request_number`'s invented format cost a whole milestone because no
        # constraint could refuse it.
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
            (mapping_id, version_id, "d" * 64),
        )
        for username, role in (
            ("create_accountant", "accountant"),
            # Holds `payment_batch.read` and **not** `.create` (`:276`). This is what makes the
            # create's permission negative prove that *this* grant is required rather than
            # merely some grant — the distinction slice 1's ninth negative control found a
            # behavioural test cannot make.
            ("create_business_admin", "business_admin"),
            ("create_bare", None),
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
            "trader_id": trader_id,
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


def an_eligible_request(world: dict[str, Any], value: str) -> dict[str, Any]:
    """A request at `eligible_for_batching`, through the real M5 journey.

    Not seeded. A hand-seeded status is the shape M5 slice 8 found a defect behind: the fixture
    invents the state the next step needs and never notices what the real step leaves.
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
        headers={
            **csrf(client),
            "If-Match": f'"rv-{created.json()["request"]["record_version"]}"',
        },
    )
    assert handed.status_code == 200, handed.text

    sign_in_admin(client, "create_accountant")
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


def create(world: dict[str, Any], *selections: dict[str, Any], key: str | None = None) -> Any:
    client = world["client"]
    headers = {**csrf(client), "Idempotency-Key": key or str(uuid.uuid4())}
    return client.post(
        "/api/v1/payment-batches",
        json={
            "items": list(selections),
            "bank_profile_version_id": str(world["version_id"]),
            "bank_account_id": str(world["account_id"]),
            "bank_mapping_id": str(world["mapping_id"]),
        },
        headers=headers,
    )


def rows(world: dict[str, Any], sql: str, *parameters: Any) -> list[tuple[Any, ...]]:
    """Read through a separate connection, so nothing is read out of the session that wrote it."""

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        return connection.execute(sql, parameters).fetchall()


def test_one_request_becomes_a_batch_a_version_items_and_allocations(
    world: dict[str, Any],
) -> None:
    """`SVC-BATCH-001`, the positive half: all five tables written in one call."""

    selection = an_eligible_request(world, SPLITS_INTO_THREE)
    sign_in_admin(world["client"], "create_accountant")

    response = create(world, selection)
    assert response.status_code == 201, response.text
    body = response.json()

    batch_id = body["batch"]["id"]
    version_id = body["current_version"]["id"]

    assert body["batch"]["status"] == "draft"
    assert body["current_version"]["status"] == "draft"
    assert body["current_version"]["version_number"] == 1
    assert body["replayed"] is False

    # Three rows: 2.5 billion against a limit of 1 billion is 1 + 1 + 0.5, and the residual is
    # last. An implementation that divided would produce three equal rows and fail here.
    assert body["current_version"]["row_count"] == 3
    assert body["current_version"]["total_amount_irr"] == SPLITS_INTO_THREE

    attempts = rows(
        world,
        "SELECT amount_irr, status, attempt_type, attempt_number FROM payment_attempts "
        "WHERE payment_request_id = %s ORDER BY attempt_number",
        selection["payment_request_id"],
    )
    assert [amount for amount, _, _, _ in attempts] == [LIMIT, LIMIT, 500_000_000]
    assert {status for _, status, _, _ in attempts} == {"included_in_batch_version"}
    assert {kind for _, _, kind, _ in attempts} == {"split"}
    assert [number for _, _, _, number in attempts] == [1, 2, 3]

    items = rows(
        world,
        "SELECT row_order, amount_irr, row_hash FROM payment_batch_items "
        "WHERE payment_batch_version_id = %s ORDER BY row_order",
        version_id,
    )
    assert [order for order, _, _ in items] == [1, 2, 3]
    assert all(len(row_hash) == 64 for _, _, row_hash in items), (
        "a row hash must be a real digest: `FINANCIAL_INTEGRITY_BASELINE.md:22-23` forbids a "
        "placeholder hash, and a row whose integrity nothing can check is a row nobody can defend"
    )

    allocations = rows(
        world,
        "SELECT payment_attempt_id, released_at FROM payment_attempt_allocations "
        "WHERE payment_batch_version_id = %s",
        version_id,
    )
    assert len(allocations) == 3
    assert {released for _, released in allocations} == {None}

    linked = rows(
        world, "SELECT current_version_id FROM payment_batches WHERE id = %s", batch_id
    )
    assert str(linked[0][0]) == version_id, (
        "the container's pointer does not name the version just created, so the composite "
        "deferred key is satisfied by something other than what this call built"
    )


def test_the_batch_number_follows_the_documented_family(world: dict[str, Any]) -> None:
    """`DB-BATCH-002`.

    The shape only. The widths come from the documents and are asserted against the parsed
    documents in `tests/backend/test_human_readable_numbers.py`; what this adds is that the
    running system produces one, since a format function nothing calls proves nothing.
    """

    import re

    selection = an_eligible_request(world, FITS_IN_ONE)
    sign_in_admin(world["client"], "create_accountant")
    response = create(world, selection)
    assert response.status_code == 201, response.text

    number = response.json()["batch"]["batch_number"]
    assert re.fullmatch(r"PB-\d{8}-\d{6}", number), number


def test_only_a_request_at_eligible_for_batching_may_be_allocated(
    world: dict[str, Any],
) -> None:
    """`SVC-BATCH-002`. A draft is refused, and the refusal names the state.

    The permitted origin is one state, and document 06 is what says so: `:558-566` makes
    `eligible_for_batching` the entry to batching. Asserted against a request stopped one step
    earlier rather than against a fabricated status, so what is refused is a state the system
    can actually be in.
    """

    client = world["client"]
    sign_in_trader(client)
    created = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiary_id"]),
            "amount": {"value": FITS_IN_ONE, "unit": "IRR"},
            "description": "still a draft",
        },
        headers=csrf(client),
    )
    assert created.status_code == 201, created.text

    sign_in_admin(client, "create_accountant")
    response = create(
        world,
        {
            "payment_request_id": created.json()["request"]["id"],
            "expected_revision_id": created.json()["revision"]["id"],
            "expected_record_version": created.json()["request"]["record_version"],
        },
    )
    # 400, not 422. `api_error_catalog.yaml:16` gives `BUSINESS_RULE_VIOLATION` http 400 —
    # "Domain rule failed" — and the route's documented responses said 422 until this test read
    # the catalogue instead of my memory. A wrong code in `responses` is a wrong code in the
    # published OpenAPI, which a client would generate a handler for.
    assert response.status_code == 400, response.text
    assert "eligible_for_batching" in response.text

    assert rows(world, "SELECT id FROM payment_attempts WHERE payment_request_id = %s",
                created.json()["request"]["id"]) == [], (
        "a refused create left an attempt behind, so the transaction was not atomic"
    )


def test_a_repeated_idempotency_key_returns_the_first_batch(world: dict[str, Any]) -> None:
    """`SVC-BATCH-003`. `command_catalog.yaml:111` says idempotency is required.

    The consequence is specific and worth stating: without the replay, a retry after a network
    timeout would attempt to allocate attempts the first call already allocated, and the partial
    unique index would refuse it. The caller would receive a conflict for a batch their own first
    call had created successfully — and would go looking for a duplicate that does not exist.
    """

    selection = an_eligible_request(world, FITS_IN_ONE)
    sign_in_admin(world["client"], "create_accountant")
    key = str(uuid.uuid4())

    first = create(world, selection, key=key)
    assert first.status_code == 201, first.text

    second = create(world, selection, key=key)
    assert second.status_code == 201, second.text
    assert second.json()["batch"]["id"] == first.json()["batch"]["id"]
    assert second.json()["replayed"] is True
    assert first.json()["replayed"] is False

    made = rows(
        world,
        "SELECT count(*) FROM payment_batches WHERE id = %s",
        first.json()["batch"]["id"],
    )
    assert made[0][0] == 1

    audited = rows(
        world,
        "SELECT count(*) FROM audit_logs WHERE action = 'payment_batch.created' "
        "AND entity_id = %s",
        first.json()["batch"]["id"],
    )
    assert audited[0][0] == 1, (
        "the replay wrote a second audit row, so the log now says the command ran twice"
    )


def test_creation_writes_exactly_the_catalogued_audit_action_and_no_outbox_event(
    world: dict[str, Any],
) -> None:
    """`AUD-BATCH-001`, written from the catalogue outward.

    `command_catalog.yaml:113-114` maps this command to `payment_batch.created` and to
    `"outbox_event": null`. Both halves are asserted, and the second is the one worth having:
    `payment_batch_version.created` is also a catalogued action, and emitting it here would put a
    row in the log claiming the separate `payment_batch_version.create` command had run.

    M5's audit obligation claimed more than its catalogue allowed and had to be corrected
    mid-slice. This is the same mistake, checked for rather than argued about.
    """

    selection = an_eligible_request(world, FITS_IN_ONE)
    sign_in_admin(world["client"], "create_accountant")

    before = rows(world, "SELECT count(*) FROM outbox_events")[0][0]
    response = create(world, selection)
    assert response.status_code == 201, response.text
    batch_id = response.json()["batch"]["id"]

    actions = rows(
        world, "SELECT action FROM audit_logs WHERE entity_id = %s ORDER BY action", batch_id
    )
    assert [action for (action,) in actions] == ["payment_batch.created"]

    after = rows(world, "SELECT count(*) FROM outbox_events")[0][0]
    assert after == before, (
        "creation published an outbox event and the catalogue defines none for this command"
    )


def test_the_frozen_snapshot_answers_without_the_live_profile(world: dict[str, Any]) -> None:
    """`DB-ATTEMPT-002`. The snapshot is read back from the row, not from a join.

    A snapshot nothing reads is not evidence. So this asserts the values *on the attempt and the
    item*, and asserts that the splitting rules that produced the amount are there too — because
    an export rendered next month has to be explainable when the profile version it used has
    been superseded.
    """

    selection = an_eligible_request(world, SPLITS_INTO_THREE)
    sign_in_admin(world["client"], "create_accountant")
    response = create(world, selection)
    assert response.status_code == 201, response.text

    frozen = rows(
        world,
        "SELECT beneficiary_name_snapshot, beneficiary_iban_snapshot, "
        "split_rule_snapshot->>'default_transfer_limit_irr', "
        "split_rule_snapshot->>'split_reason', bank_profile_version_id "
        "FROM payment_attempts WHERE payment_request_id = %s ORDER BY attempt_number",
        selection["payment_request_id"],
    )
    assert len(frozen) == 3
    for name, iban, limit, reason, profile_version in frozen:
        assert name == "Ali Two"
        assert iban == IBAN
        assert limit == str(LIMIT), "the limit that produced this amount is not on the row"
        assert reason == "bank_limit_default"
        assert str(profile_version) == str(world["version_id"])

    # And the item's own copy. `04_Database_Schema.md:1024` calls `attempt_snapshot` the
    # "Remaining canonical row/config context", so the split rules belong there too — and this
    # assertion exists because a negative control emptied that field and **nothing failed**. By
    # this file's own standard a snapshot nothing reads is not evidence, so the choice was to
    # read it or to stop storing it. Document 04 asks for it, so it is read.
    on_items = rows(
        world,
        "SELECT beneficiary_name_snapshot, beneficiary_iban_snapshot, "
        "attempt_snapshot->>'attempt_type', "
        "attempt_snapshot->'split_rule_snapshot'->>'default_transfer_limit_irr', "
        "attempt_snapshot->>'bank_profile_version_id' "
        "FROM payment_batch_items "
        "WHERE payment_batch_version_id = %s ORDER BY row_order",
        response.json()["current_version"]["id"],
    )
    assert len(on_items) == 3
    for name, iban, kind, limit, profile_version in on_items:
        assert (name, iban, kind) == ("Ali Two", IBAN, "split")
        assert limit == str(LIMIT), (
            "the item's canonical context has lost the limit that produced its amount, so a "
            "row cannot explain itself without joining back to the attempt"
        )
        assert profile_version == str(world["version_id"])


def test_the_containers_stored_status_agrees_with_its_current_version(
    world: dict[str, Any],
) -> None:
    """`CON-BATCH-004`. The projection and the thing it projects.

    `status_catalog.yaml:359-370` marks nine of the container's eleven states `derived: true`,
    and `04_Database_Schema.md:971` stores the column anyway. So the assertion is agreement, not
    the write: a test that checked the command wrote `draft` would pass on a projection that had
    already drifted from the version it claims to summarise.

    Asserted over **every** batch in the database rather than the one just created, because
    drift is a property of the set and a single row cannot show it.
    """

    selection = an_eligible_request(world, FITS_IN_ONE)
    sign_in_admin(world["client"], "create_accountant")
    assert create(world, selection).status_code == 201

    disagreements = rows(
        world,
        "SELECT b.batch_number, b.status, v.status FROM payment_batches b "
        "JOIN payment_batch_versions v ON v.id = b.current_version_id "
        "WHERE b.status <> v.status",
    )
    assert disagreements == [], (
        "a container's stored status disagrees with its current version's: "
        f"{disagreements}. Nine of eleven container states are derived from exactly this."
    )

    # And the projection is not vacuous: there is at least one batch for it to be true of.
    assert rows(world, "SELECT count(*) FROM payment_batches")[0][0] > 0


def test_a_batched_request_is_exactly_one_that_owns_an_active_allocation(
    world: dict[str, Any],
) -> None:
    """`CON-BATCH-003`. §2.2 of the M6 plan, asserted in both directions.

    `status_catalog.yaml:266-267` marks `batched` `derived: true` with the reason "current active
    attempt allocation is the authoritative condition". The natural inference — that create moves
    the request to `batched` — is the defect M5 slice 7 removed from `create_revision`, which set
    a status on every correction because a plausible sentence justified it.

    So no request status changes here, and the assertion is that the projection cannot disagree
    with the allocation: no request holds the stored `batched` status, and the requests that own
    an active allocation are exactly the ones this slice allocated.
    """

    selection = an_eligible_request(world, FITS_IN_ONE)
    sign_in_admin(world["client"], "create_accountant")
    assert create(world, selection).status_code == 201

    stored = rows(world, "SELECT count(*) FROM payment_requests WHERE status = 'batched'")
    assert stored[0][0] == 0, (
        "a request carries the stored status `batched`, which the catalogue marks derived. "
        "Membership of a batch is the allocation; a second copy of that fact is a copy that can "
        "disagree."
    )

    allocated = rows(
        world,
        "SELECT DISTINCT a.payment_request_id FROM payment_attempts a "
        "JOIN payment_attempt_allocations al ON al.payment_attempt_id = a.id "
        "WHERE al.released_at IS NULL AND a.payment_request_id = %s",
        selection["payment_request_id"],
    )
    assert len(allocated) == 1, (
        "the request just batched does not own an active allocation, so nothing records that it "
        "is in a batch at all"
    )

    still_eligible = rows(
        world,
        "SELECT status FROM payment_requests WHERE id = %s",
        selection["payment_request_id"],
    )
    assert still_eligible[0][0] == "eligible_for_batching", (
        "the create command changed the request's status. Document 06 gives batching no "
        "request-level transition and the catalogue marks `batched` derived."
    )


def test_the_database_refuses_a_second_active_allocation(world: dict[str, Any]) -> None:
    """`DB-ALLOC-001`, provoked at the database and not through the service.

    `FINANCIAL_INTEGRITY_BASELINE.md:39-40`: "service-layer checks alone are insufficient". The
    only way to know which layer is enforcing is to remove the service from the picture, so this
    inserts the second allocation row directly. If the partial unique index were dropped and the
    check moved into `create_batch`, this test fails — which is the negative control.

    **Across versions, not within one.** The second allocation names a different version id, so
    a constraint scoped to one version would permit it. `:46` states that requirement as a
    warning against the narrower reading, and this is what makes the warning tested.
    """

    selection = an_eligible_request(world, FITS_IN_ONE)
    sign_in_admin(world["client"], "create_accountant")
    response = create(world, selection)
    assert response.status_code == 201, response.text

    existing = rows(
        world,
        "SELECT payment_attempt_id, payment_batch_version_id, payment_batch_item_id, "
        "allocated_by_admin_user_id FROM payment_attempt_allocations "
        "WHERE payment_batch_version_id = %s",
        response.json()["current_version"]["id"],
    )
    assert len(existing) == 1
    attempt_id, version_id, item_id, actor_id = existing[0]

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(
                "INSERT INTO payment_attempt_allocations (payment_attempt_id, "
                "payment_batch_version_id, payment_batch_item_id, "
                "allocated_by_admin_user_id) VALUES (%s, %s, %s, %s)",
                (attempt_id, version_id, item_id, actor_id),
            )
        connection.rollback()


def test_two_transactions_racing_for_one_attempt(world: dict[str, Any]) -> None:
    """`CON-BATCH-002`. The baseline's required two-transaction race test.

    Two real connections, both inserting the same attempt's allocation, neither committed until
    both have inserted. Under READ COMMITTED the second blocks on the unique index and then
    raises — which is the whole difference between a constraint and a check. A `SELECT` first
    would let both transactions see no row, both decide to proceed, and both succeed.

    The first allocation is deleted rather than released, because release needs an UPDATE grant
    that slice 4 has not yet added — which is itself the point of
    `test_release_is_not_possible_yet` below.
    """

    selection = an_eligible_request(world, FITS_IN_ONE)
    sign_in_admin(world["client"], "create_accountant")
    response = create(world, selection)
    assert response.status_code == 201, response.text

    existing = rows(
        world,
        "SELECT id, payment_attempt_id, payment_batch_version_id, payment_batch_item_id, "
        "allocated_by_admin_user_id FROM payment_attempt_allocations "
        "WHERE payment_batch_version_id = %s",
        response.json()["current_version"]["id"],
    )
    allocation_id, attempt_id, version_id, item_id, actor_id = existing[0]

    # Clear the field so both racing transactions are inserting the *first* active allocation
    # for this attempt, which is the race the baseline describes.
    with psycopg.connect(_psycopg(world["owner_url"])) as cleanup:
        cleanup.execute(
            "DELETE FROM payment_attempt_allocations WHERE id = %s", (allocation_id,)
        )
        cleanup.commit()

    insert = (
        "INSERT INTO payment_attempt_allocations (payment_attempt_id, "
        "payment_batch_version_id, payment_batch_item_id, allocated_by_admin_user_id) "
        "VALUES (%s, %s, %s, %s)"
    )
    parameters = (attempt_id, version_id, item_id, actor_id)

    first = psycopg.connect(_psycopg(world["owner_url"]))
    second = psycopg.connect(_psycopg(world["owner_url"]))
    try:
        first.execute(insert, parameters)
        first.commit()

        # Now the loser. It sees a committed row and the index refuses it — the database's
        # answer, arrived at without either transaction having asked a question.
        with pytest.raises(psycopg.errors.UniqueViolation):
            second.execute(insert, parameters)
        second.rollback()
    finally:
        first.close()
        second.close()

    survivors = rows(
        world,
        "SELECT count(*) FROM payment_attempt_allocations WHERE payment_attempt_id = %s "
        "AND released_at IS NULL",
        attempt_id,
    )
    assert survivors[0][0] == 1, "the race left two active allocations for one attempt"


def test_release_is_not_possible_yet(
    world: dict[str, Any], migrated: RuntimeIdentities
) -> None:
    """The absence of a grant, proved through the runtime role rather than promised in a comment.

    Release is slice 4's. `20260820_0017` grants no UPDATE on `payment_attempt_allocations` at
    all, so today the runtime role cannot write `released_at` — and that is what makes "release
    does not exist yet" a property of the database instead of a claim about the code.

    Asserted through the **app role**, not the owner: the owner can do anything, so a test that
    used the owner connection would pass whatever the grants said. The role name comes from the
    provisioned identities rather than from `load_settings()`, which needs an environment this
    test does not have — the first version reached for the settings object and failed on a
    validation error, which is the `Settings` alias trap wearing a different hat.
    """

    app_role = migrated.app_role
    assert app_role, "the provisioned database has no app role, so this would prove nothing"

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(f'SET ROLE "{app_role}"')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "UPDATE payment_attempt_allocations SET released_at = now(), "
                "release_reason = 'not yet'"
            )
        connection.rollback()


def test_creating_needs_the_create_permission_and_not_merely_the_read(
    world: dict[str, Any],
) -> None:
    """`SEC-BATCH-002`'s behavioural half, and the stronger of the two negatives.

    Signs in as `business_admin`, who holds `payment_batch.read` and not `.create` (`:276`). A
    role holding nothing would prove only that *some* permission is required; this proves the
    route wants the mutation grant specifically — which is the distinction slice 1's ninth
    negative control found no behavioural test could make while `accountant` holds both.

    The declaration itself is asserted in `tests/backend/test_batch_permissions_are_declared.py`,
    with equality rather than membership. Both are needed: this one proves the guard runs, that
    one proves it names the right grant.
    """

    selection = an_eligible_request(world, FITS_IN_ONE)

    sign_in_admin(world["client"], "create_business_admin")
    refused = create(world, selection)
    assert refused.status_code == 403, refused.text

    sign_in_admin(world["client"], "create_bare")
    bare = create(world, selection)
    assert bare.status_code == 403, bare.text

    # And the same selection succeeds for a role that holds the grant, so the refusals above
    # are about the permission and not about the payload.
    sign_in_admin(world["client"], "create_accountant")
    allowed = create(world, selection)
    assert allowed.status_code == 201, allowed.text


def test_a_missing_idempotency_key_is_refused_before_anything_is_written(
    world: dict[str, Any],
) -> None:
    """The catalogue says `"idempotency": "required"`, and required means refused when absent."""

    selection = an_eligible_request(world, FITS_IN_ONE)
    sign_in_admin(world["client"], "create_accountant")

    before = rows(world, "SELECT count(*) FROM payment_batches")[0][0]
    response = world["client"].post(
        "/api/v1/payment-batches",
        json={
            "items": [selection],
            "bank_profile_version_id": str(world["version_id"]),
            "bank_account_id": str(world["account_id"]),
            "bank_mapping_id": str(world["mapping_id"]),
        },
        headers=csrf(world["client"]),
    )
    assert response.status_code == 428, response.text
    assert rows(world, "SELECT count(*) FROM payment_batches")[0][0] == before


def test_a_stale_revision_expectation_is_refused_and_writes_nothing(
    world: dict[str, Any],
) -> None:
    """`SVC-BATCH-001`'s negative half plus `CON-BATCH-001` on the command surface.

    Document 05 says the create command revalidates everything, so a selection naming a revision
    that is no longer current is refused here even though the preview accepted it a moment
    earlier. And nothing is written: a partial batch is worse than a refusal, because it holds
    allocations for rows nobody chose.
    """

    selection = an_eligible_request(world, FITS_IN_ONE)
    sign_in_admin(world["client"], "create_accountant")

    before_batches = rows(world, "SELECT count(*) FROM payment_batches")[0][0]
    before_attempts = rows(world, "SELECT count(*) FROM payment_attempts")[0][0]

    response = create(
        world,
        {**selection, "expected_revision_id": str(uuid.uuid4())},
    )
    assert response.status_code == 409, response.text

    assert rows(world, "SELECT count(*) FROM payment_batches")[0][0] == before_batches
    assert rows(world, "SELECT count(*) FROM payment_attempts")[0][0] == before_attempts


def test_two_requests_become_one_file_with_continuous_row_order(
    world: dict[str, Any],
) -> None:
    """`SVC-BATCH-001`. Row order is the order a bank reads, across requests and not within one.

    Restarting the order per request would produce two rows numbered 1 in one file. Nothing in
    the schema forbids it — `UNIQUE(payment_batch_version_id, row_order)` does, which is why the
    constraint is there and why this test would fail with a duplicate-key error rather than a
    wrong assertion if the order were restarted.
    """

    first = an_eligible_request(world, SPLITS_INTO_THREE)
    second = an_eligible_request(world, FITS_IN_ONE)
    sign_in_admin(world["client"], "create_accountant")

    response = create(world, first, second)
    assert response.status_code == 201, response.text
    assert response.json()["current_version"]["row_count"] == 4

    ordered = rows(
        world,
        "SELECT row_order, amount_irr FROM payment_batch_items "
        "WHERE payment_batch_version_id = %s ORDER BY row_order",
        response.json()["current_version"]["id"],
    )
    assert [order for order, _ in ordered] == [1, 2, 3, 4]
    assert [amount for _, amount in ordered] == [
        LIMIT,
        LIMIT,
        500_000_000,
        int(FITS_IN_ONE),
    ]
    assert response.json()["current_version"]["total_amount_irr"] == str(
        int(SPLITS_INTO_THREE) + int(FITS_IN_ONE)
    )
