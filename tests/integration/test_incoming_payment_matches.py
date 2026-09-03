"""A candidate, never a truth. M10 slice 5.

Against a real PostgreSQL. `05_API_Specification.md` §21.5, `04_Database_Schema.md` §10.7,
`06_Workflows_and_State_Machines.md` §11.

**The slice is one sentence and one test.** §21.5: "Candidate acceptance and financial confirmation
remain separate." So `test_a_match_confirms_nothing` proposes a match and reads back the match
*and* the receipt, requiring every confirmation column on both to be null and the receipt to be
`candidate_match` — which §10.3 places four states before `confirmed`. A test that only checked the
match row was created would pass against an implementation that helpfully marked the claim paid,
which is the shape this milestone has met five times.

Covers: DB-MATCH-001, CON-MATCH-001, SVC-MATCH-001.
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities
from openpyxl import Workbook

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery-staple"
CSRF_HEADER = "X-CSRF-Token"
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"
TRADER_CSRF_COOKIE = "__Host-gp_trader_csrf"

TRADER_PHONE = "+989120015001"
CLAIMED = 2_000_000_000

HEADERS = ["date", "amount_in", "tracking", "who"]
MAPPING: dict[str, Any] = {
    "columns": [
        {"header": "date", "field": "transaction_date"},
        {"header": "amount_in", "field": "amount_in_irr"},
        {"header": "tracking", "field": "tracking_number"},
        {"header": "who", "field": "counterparty_name"},
    ]
}


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


def workbook_bytes(rows: list[list[Any]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


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
        local_storage_root=tmp_path_factory.mktemp("match-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="v" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    ids = {name: uuid.uuid4() for name in ("bank", "version", "account", "mapping", "trader")}

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'matchbank', 'Match Bank', 'active')",
            (ids["bank"],),
        )
        connection.execute(
            "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, status, "
            "config_hash) VALUES (%s, %s, 1, 'active', %s)",
            (ids["version"], ids["bank"], hashlib.sha256(b"match-version").hexdigest()),
        )
        connection.execute(
            "INSERT INTO bank_accounts (id, bank_profile_id, display_name, account_role, status) "
            "VALUES (%s, %s, 'Incoming', 'incoming_destination', 'active')",
            (ids["account"], ids["bank"]),
        )
        connection.execute(
            "INSERT INTO bank_mappings (id, bank_profile_version_id, file_type, "
            "template_version, status, mapping, config_hash) "
            "VALUES (%s, %s, 'statement_import', 1, 'active', %s, %s)",
            (
                ids["mapping"],
                ids["version"],
                json.dumps(MAPPING),
                hashlib.sha256(b"match-mapping").hexdigest(),
            ),
        )
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'Buying Trader', %s, 'active', 'approved')",
            (ids["trader"], TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Buyer Contact', %s, 'active', TRUE)",
            (ids["trader"], TRADER_PHONE, encoded),
        )
        connection.execute(
            "INSERT INTO admin_users (username, full_name, password_hash, status) "
            "VALUES ('match_accountant', 'Accountant', %s, 'active')",
            (encoded,),
        )
        connection.execute(
            "INSERT INTO admin_user_roles (admin_user_id, role_id) "
            "SELECT u.id, r.id FROM admin_users u, roles r "
            "WHERE u.username = 'match_accountant' AND r.code = 'accountant'"
        )
        connection.commit()

    app = create_app(settings=settings)
    app.state.runtime = RuntimeServices.from_settings(settings)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://admin.localhost") as client:
        yield {
            "client": client,
            "owner_url": migrated.owner_url,
            "app_role": migrated.app_role,
            "runtime": app.state.runtime,
            **{f"{name}_id": value for name, value in ids.items()},
        }
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def rows(world: dict[str, Any], sql: str, *parameters: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        return connection.execute(sql, parameters).fetchall()


def sign_in_admin(world: dict[str, Any]) -> None:
    client = world["client"]
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": "match_accountant", "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


def sign_in_trader(world: dict[str, Any]) -> None:
    client = world["client"]
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/trader/login", json={"identifier": TRADER_PHONE, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def csrf(world: dict[str, Any]) -> dict[str, str]:
    client = world["client"]
    token = client.cookies.get(ADMIN_CSRF_COOKIE) or client.cookies.get(TRADER_CSRF_COOKIE)
    assert token, "signed in but no CSRF cookie was set"
    return {CSRF_HEADER: token}


def a_receipt(world: dict[str, Any]) -> str:
    """A trader's claim, written directly.

    Slice 2's own tests prove the claim path; this module's subject is what the centre does with
    one afterwards.
    """

    order_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO gold_sale_orders (id, trader_id, order_number, status, gold_type, "
            "gold_weight, weight_unit, gold_purity, expected_amount_irr, created_by_actor_type, "
            "record_version) VALUES (%s, %s, %s, 'payment_evidence_submitted', 'bullion', "
            "10.000000, 'GRAM', '18K', %s, 'trader_user', 1)",
            (order_id, world["trader_id"], f"GS-{str(order_id)[:8]}", CLAIMED),
        )
        connection.execute(
            "INSERT INTO incoming_payment_receipts (id, gold_sale_order_id, trader_id, "
            "amount_irr, status, record_version) VALUES (%s, %s, %s, %s, 'submitted', 1)",
            (receipt_id, order_id, world["trader_id"], CLAIMED),
        )
        connection.commit()
    return str(receipt_id)


def a_statement_row(world: dict[str, Any], *, leave_running: bool = False) -> str:
    """A parsed row from a run that succeeded — or, when asked, one still running."""

    from app.workers.tasks.files import parse_statements

    content = workbook_bytes(
        [["2026-08-20", str(CLAIMED), f"TRK-{uuid.uuid4().hex[:8]}", "Buyer"]]
    )
    file_id = uuid.uuid4()
    key = f"statements/{file_id}"
    world["runtime"].storage.write(key, io.BytesIO(content))
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
            "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
            "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
            "original_or_derived_relation, metadata) "
            "VALUES (%s, 'local', 'gold', %s, 'statement.xlsx', "
            "'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', %s, %s, "
            "'bank_statement', 'internal', 'available', 'clean', 'admin_user', 'original', '{}')",
            (file_id, key, len(content), hashlib.sha256(content).hexdigest()),
        )
        connection.commit()

    statement = world["client"].post(
        "/api/v1/bank-statements",
        json={
            "bank_profile_version_id": str(world["version_id"]),
            "bank_account_id": str(world["account_id"]),
            "original_file_id": str(file_id),
        },
        headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert statement.status_code == 201, statement.text
    run = world["client"].post(
        f"/api/v1/bank-statements/{statement.json()['id']}/import-runs",
        json={"bank_mapping_id": str(world["mapping_id"])},
        headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert run.status_code == 202, run.text
    parse_statements(world["runtime"])

    if leave_running:
        with psycopg.connect(_psycopg(world["owner_url"])) as connection:
            connection.execute(
                "UPDATE bank_statement_import_runs SET status = 'running' WHERE id = %s",
                (run.json()["id"],),
            )
            connection.commit()

    return str(
        rows(
            world,
            "SELECT id FROM bank_statement_rows WHERE bank_statement_import_run_id = %s",
            run.json()["id"],
        )[0][0]
    )


def propose(world: dict[str, Any], receipt_id: str, row_id: str, **overrides: Any) -> Any:
    body: dict[str, Any] = {"bank_statement_row_id": row_id}
    body.update(overrides)
    return world["client"].post(
        f"/api/v1/incoming-payment-receipts/{receipt_id}/matches",
        json=body,
        headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
    )


def stored_match(world: dict[str, Any], match_id: str) -> tuple[Any, ...]:
    return rows(
        world,
        "SELECT status, confirmed_amount_irr, confirmed_at, confirmed_by_admin_user_id, "
        "rejected_at, rejection_reason, match_method, record_version "
        "FROM incoming_payment_matches WHERE id = %s",
        match_id,
    )[0]


# --- SVC-MATCH-001 -----------------------------------------------------------


def test_a_match_confirms_nothing(world: dict[str, Any]) -> None:
    """`SVC-MATCH-001`. §21.5: "Candidate acceptance and financial confirmation remain separate."

    **The test that would pass against almost anything if it only checked the match existed.** Both
    the match and the receipt are read back: every confirmation column must be null on both, and
    the receipt must be `candidate_match`, which §10.3 places four states before `confirmed`.
    """

    sign_in_admin(world)
    receipt_id = a_receipt(world)
    row_id = a_statement_row(world)

    response = propose(world, receipt_id, row_id)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["status"] == "proposed", (
        f"the match was born {body['status']!r}. Not even `accepted_for_review` — that is a person "
        "agreeing, and §11.3's first rule is that agreeing is still not financial confirmation."
    )
    assert body["confirmed_amount_irr"] is None
    assert body["confirmed_at"] is None
    assert body["receipt_status"] == "candidate_match"

    stored = stored_match(world, body["id"])
    assert stored[1] is None, "confirmed_amount_irr was written by a proposal"
    assert stored[2] is None and stored[3] is None, "a confirming actor was recorded"

    receipt = rows(
        world,
        "SELECT status, confirmed_amount_irr, confirmed_at, confirmed_by_admin_user_id "
        "FROM incoming_payment_receipts WHERE id = %s",
        receipt_id,
    )[0]
    assert receipt[0] == "candidate_match", (
        f"the receipt is {receipt[0]!r}. A suggestion moves it to candidate_match and no further; "
        "anything past that is the centre agreeing with a figure it has not checked."
    )
    assert receipt[1] is None and receipt[2] is None and receipt[3] is None, (
        "proposing a match wrote a confirmation onto the receipt"
    )


def test_the_body_cannot_carry_a_confirmation(world: dict[str, Any]) -> None:
    """Enforcement by absence. §21.5 again, at the schema rather than in a branch.

    `status`, `confirmed_amount_irr` and `match_method` are all refused by `extra="forbid"`. The
    third is worth naming: Phase 1A has exactly one method — document 08 §8.8's manual search — and
    a field would invite a caller to claim a machine found it.
    """

    sign_in_admin(world)
    receipt_id = a_receipt(world)
    row_id = a_statement_row(world)

    for field, value in (
        ("status", "accepted_for_review"),
        ("confirmed_amount_irr", CLAIMED),
        ("match_method", "automatic"),
    ):
        response = propose(world, receipt_id, row_id, **{field: value})
        assert response.status_code == 422, (
            f"the body accepted {field!r}. A field the command would then have to refuse is a "
            f"field that should not exist: {response.text}"
        )


def test_the_method_is_recorded_as_a_human_search(world: dict[str, Any]) -> None:
    """Document 08 §8.8: "Phase 1A allows manual search and confirmation."

    And `match_score` is null for a human, deliberately. Defaulting it to 1.0 would make a person's
    judgement indistinguishable from a machine's certainty — the same argument the outgoing
    direction's `matching_candidates.score` records.
    """

    sign_in_admin(world)
    response = propose(world, a_receipt(world), a_statement_row(world))
    assert response.status_code == 201, response.text

    stored = stored_match(world, response.json()["id"])
    assert stored[6] == "manual_search"
    assert response.json()["match_score"] is None, (
        "a human search was given a score. A score nobody computed is a certainty nobody has."
    )


# --- DB-MATCH-001 ------------------------------------------------------------


def test_the_same_pair_cannot_be_proposed_twice(world: dict[str, Any]) -> None:
    """`DB-MATCH-001`. §10.7's `UNIQUE(incoming_payment_receipt_id, bank_statement_row_id)`."""

    sign_in_admin(world)
    receipt_id = a_receipt(world)
    row_id = a_statement_row(world)

    first = propose(world, receipt_id, row_id)
    assert first.status_code == 201, first.text

    second = propose(world, receipt_id, row_id)
    assert second.status_code == 409, (
        f"a repeated proposal answered {second.status_code}. §10.7's unique makes the same "
        "suggestion one row, however many people propose it."
    )


def test_one_receipt_may_have_several_candidates(world: dict[str, Any]) -> None:
    """`DB-MATCH-001`, the other direction, and §10.7 `:809` is why.

    "Use partial unique rules only if the business confirms strict one-row/one-receipt matching.
    The baseline supports traceable partial/combined payment cases." So a receipt may name two
    rows, a row may serve two receipts, and the schema must not have quietly decided otherwise.
    """

    sign_in_admin(world)
    receipt_id = a_receipt(world)

    first_row = a_statement_row(world)
    second_row = a_statement_row(world)

    assert propose(world, receipt_id, first_row).status_code == 201
    assert propose(world, receipt_id, second_row).status_code == 201, (
        "a second candidate for one receipt was refused. The baseline is many-to-many until the "
        "business says otherwise, which the plan's G-2 records as the owner's decision."
    )

    other_receipt = a_receipt(world)
    assert propose(world, other_receipt, first_row).status_code == 201, (
        "one statement row could not serve two receipts. §10.7's combined-payment baseline needs "
        "exactly that, and a partial unique would have refused it."
    )


def test_no_partial_unique_constrains_the_pair(world: dict[str, Any]) -> None:
    """`DB-MATCH-001`, asserted as an **absence**, with the reason cited.

    A partial unique index — "one active match per row", say — would answer §10.7 `:809`'s question
    in a migration rather than in a business decision, and every behavioural test above would still
    pass because none of them proposes a *second* match for a row that already has an active one.
    Only a look at the indexes can see it.
    """

    indexes = rows(
        world,
        "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = "
        "'incoming_payment_matches'",
    )
    partial = [
        name
        for name, definition in indexes
        if "UNIQUE" in definition and "WHERE" in definition
    ]
    assert partial == [], (
        f"a partial unique index exists on incoming_payment_matches: {partial}. §10.7 `:809` "
        "leaves strict one-row/one-receipt matching to the business, and an index is not where "
        "that decision gets taken."
    )

    # The primary key is a unique index too, and leaving it out of the expectation made the first
    # version of this assertion fail against a correct schema. Named explicitly rather than
    # filtered out, so the list says what the table is allowed to have.
    uniques = sorted(name for name, definition in indexes if "UNIQUE" in definition)
    assert uniques == [
        "pk_incoming_payment_matches",
        "uq_incoming_matches_receipt_row",
    ], f"the table's unique indexes are {uniques}. Exactly two are expected: the key and the pair."


def test_the_runtime_cannot_rewrite_a_candidates_evidence(world: dict[str, Any]) -> None:
    """`DB-MATCH-001`, read as a privilege rather than inferred from behaviour.

    **Four columns are frozen at insert**: the receipt, the row, the method and the score. A
    candidate whose subject or whose evidence could be swapped afterwards is one nobody can audit —
    the audit row would describe a decision about a different pair than the one now stored.

    No behavioural test can see this: no command updates those columns, so removing the restriction
    changes nothing observable. A grant is a capability, and only a privilege query observes one.
    `matching_candidates`, the outgoing twin, froze exactly the same four.
    """

    granted = rows(
        world,
        "SELECT DISTINCT column_name FROM information_schema.column_privileges "
        "WHERE table_name = 'incoming_payment_matches' AND privilege_type = 'UPDATE' "
        "AND grantee = %s ORDER BY column_name",
        world["app_role"],
    )
    assert [row[0] for row in granted] == [
        # M10 slice 6 added this one, and the list is asserted exactly so that adding it had to be
        # a decision. It is the confirmation axis — document 06 §11.2's `active / replaced /
        # revoked` — and it moves for the same reason `status` does.
        "confirmation_status",
        "confirmed_amount_irr",
        "confirmed_at",
        "confirmed_by_admin_user_id",
        "rejected_at",
        "rejected_by_admin_user_id",
        "rejection_reason",
        "replaces_match_id",
        "status",
        "updated_at",
    ], (
        f"the runtime may update {[row[0] for row in granted]} on a match. Only the decision and "
        "the confirmation move; the pair, the method and the score are what the decision was made "
        "about."
    )


# --- CON-MATCH-001 -----------------------------------------------------------


def test_two_accountants_proposing_the_same_pair(world: dict[str, Any]) -> None:
    """`CON-MATCH-001`. The unique decides, not a read-then-insert.

    Both sessions pass any `SELECT` written before the `INSERT`; only the constraint separates
    them. The second gets 409 rather than a second row or a 500 — the command catches the
    integrity error and says what happened in terms an accountant can act on.
    """

    sign_in_admin(world)
    receipt_id = a_receipt(world)
    row_id = a_statement_row(world)

    from app.core.errors import ConflictError
    from app.db.models.incoming_match import IncomingPaymentMatch

    runtime = world["runtime"]
    with runtime.uow_factory() as first_uow:
        first_uow.session.add(
            IncomingPaymentMatch(
                incoming_payment_receipt_id=uuid.UUID(receipt_id),
                bank_statement_row_id=uuid.UUID(row_id),
                status="proposed",
                match_method="manual_search",
                match_reasons=[],
                record_version=1,
            )
        )
        first_uow.commit()

    response = propose(world, receipt_id, row_id)
    assert response.status_code == 409, (
        f"the losing proposal answered {response.status_code}, not 409. A race the unique refuses "
        "must surface as a conflict rather than a 500."
    )
    assert ConflictError is not None  # the type the command raises, named so the import is real


# --- Document 08 §8.2, as far as this slice can enforce it -------------------


def test_a_row_from_an_unfinished_run_cannot_be_matched(world: dict[str, Any]) -> None:
    """Document 08 §8.2: "confirmed rows become available for matching."

    The confirmation half needs the review axis M0 still owes — the plan's G-4 — so what is
    enforced here is the execution half: the run must have succeeded. A row from a run still
    `running` belongs to a parse nobody has finished, and matching against it would rest the
    platform's belief about incoming money on it.
    """

    sign_in_admin(world)
    receipt_id = a_receipt(world)
    row_id = a_statement_row(world, leave_running=True)

    response = propose(world, receipt_id, row_id)
    assert response.status_code == 400, response.text
    assert "running" in response.text


# --- Rejection ---------------------------------------------------------------


def test_a_rejection_records_who_and_why(world: dict[str, Any]) -> None:
    """§8.8: a match decision records "actor, time, reason, and warnings".

    And the row survives. §10.7's "Multiple records support partial/combined scenarios and
    corrections" only means something if a refused suggestion stays readable — a deletion would
    make the judgement itself disappear.
    """

    sign_in_admin(world)
    receipt_id = a_receipt(world)
    row_id = a_statement_row(world)
    created = propose(world, receipt_id, row_id)
    assert created.status_code == 201, created.text
    match_id = created.json()["id"]

    response = world["client"].post(
        f"/api/v1/incoming-payment-receipts/{receipt_id}/matches/{match_id}/reject",
        json={"rejection_reason": "the amount matches but the sender is a different trader"},
        headers={
            **csrf(world),
            "Idempotency-Key": str(uuid.uuid4()),
            "If-Match": f'"rv-{created.json()["record_version"]}"',
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "rejected"

    stored = stored_match(world, match_id)
    assert stored[0] == "rejected"
    assert stored[4] is not None, "a rejection recorded no time"
    assert "different trader" in stored[5]
    assert rows(
        world, "SELECT count(*) FROM incoming_payment_matches WHERE id = %s", match_id
    )[0][0] == 1, "the rejected candidate was deleted rather than kept"

    actor = rows(
        world,
        "SELECT rejected_by_admin_user_id FROM incoming_payment_matches WHERE id = %s",
        match_id,
    )[0][0]
    assert actor is not None, (
        "a rejection recorded no actor. The table's CHECK requires the pair, and §8.8 requires the "
        "person."
    )


def test_a_rejection_without_a_reason_is_refused(world: dict[str, Any]) -> None:
    """§8.8 requires a match decision to record actor, time **and reason**.

    **This test exists because a control went NOT CAUGHT.** Removing both the schema's `min_length`
    and the command's blank check changed nothing the suite could see: every rejection test above
    sends a real sentence, so nothing ever asked what happens without one. The second meaning — the
    sabotage was fine and the gate was missing.

    Blank and whitespace-only are both refused, and by two mechanisms deliberately: `min_length`
    turns an empty string into a 422 at the edge, and the command's `.strip()` catches the spaces
    that get past it. A reason of three spaces records two of the three things §8.8 asks for while
    looking like it recorded all of them.
    """

    sign_in_admin(world)
    receipt_id = a_receipt(world)
    created = propose(world, receipt_id, a_statement_row(world))
    match_id = created.json()["id"]
    version = created.json()["record_version"]

    for reason, expected in (("", 422), ("   ", 400)):
        response = world["client"].post(
            f"/api/v1/incoming-payment-receipts/{receipt_id}/matches/{match_id}/reject",
            json={"rejection_reason": reason},
            headers={
                **csrf(world),
                "Idempotency-Key": str(uuid.uuid4()),
                "If-Match": f'"rv-{version}"',
            },
        )
        assert response.status_code == expected, (
            f"a rejection reason of {reason!r} answered {response.status_code}, expected "
            f"{expected}: {response.text}"
        )

    assert stored_match(world, match_id)[0] == "proposed", (
        "the match was rejected despite the refusal, so the guard reported an error and acted "
        "anyway"
    )


def test_a_stale_if_match_is_refused(world: dict[str, Any]) -> None:
    """Two accountants deciding one candidate. The second must be told, not silently ignored."""

    sign_in_admin(world)
    receipt_id = a_receipt(world)
    row_id = a_statement_row(world)
    created = propose(world, receipt_id, row_id)
    match_id = created.json()["id"]

    response = world["client"].post(
        f"/api/v1/incoming-payment-receipts/{receipt_id}/matches/{match_id}/reject",
        json={"rejection_reason": "stale attempt"},
        headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4()), "If-Match": '"rv-99"'},
    )
    assert response.status_code == 409, response.text


def test_a_match_under_another_receipt_is_not_found(world: dict[str, Any]) -> None:
    """The path asserts a relationship, and "wrong receipt" would confirm the match exists.

    404 rather than 400, on `app/security/ownership.py`'s rule — applied here between two internal
    resources rather than between two traders, because the reasoning is about what an answer
    reveals rather than about who is asking.
    """

    sign_in_admin(world)
    receipt_id = a_receipt(world)
    other_receipt = a_receipt(world)
    created = propose(world, receipt_id, a_statement_row(world))
    match_id = created.json()["id"]

    response = world["client"].post(
        f"/api/v1/incoming-payment-receipts/{other_receipt}/matches/{match_id}/reject",
        json={"rejection_reason": "wrong receipt"},
        headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4()), "If-Match": '"rv-1"'},
    )
    assert response.status_code == 404, response.text


def test_a_rejected_candidate_stays_in_the_history(world: dict[str, Any]) -> None:
    """The list route, and why it exists.

    A refused suggestion is history rather than a deletion, and history nobody can read is
    indistinguishable from a row that was removed.
    """

    sign_in_admin(world)
    receipt_id = a_receipt(world)
    first = propose(world, receipt_id, a_statement_row(world))
    world["client"].post(
        f"/api/v1/incoming-payment-receipts/{receipt_id}/matches/{first.json()['id']}/reject",
        json={"rejection_reason": "wrong row"},
        headers={
            **csrf(world),
            "Idempotency-Key": str(uuid.uuid4()),
            "If-Match": f'"rv-{first.json()["record_version"]}"',
        },
    )
    propose(world, receipt_id, a_statement_row(world))

    listed = world["client"].get(f"/api/v1/incoming-payment-receipts/{receipt_id}/matches")
    assert listed.status_code == 200, listed.text
    statuses = [entry["status"] for entry in listed.json()]
    assert statuses == ["rejected", "proposed"], (
        f"the history reads {statuses}. Both decisions must be visible, oldest first."
    )


# --- SEC-MATCH: the negative coverage the surface owes ------------------------


def test_no_trader_can_reach_the_matching_surface(world: dict[str, Any]) -> None:
    """`permission_catalog.yaml` gives a trader neither `incoming_payment.match` nor
    `incoming_receipt.read`.

    Every route, not one: a surface where the writes are closed and the read is open is how a list
    endpoint becomes the leak. And the reasoning is not only authorisation: which bank row proves a
    claim is the centre's judgement, and a trader who could propose one would be deciding their own
    case.
    """

    sign_in_admin(world)
    receipt_id = a_receipt(world)
    row_id = a_statement_row(world)
    created = propose(world, receipt_id, row_id)
    match_id = created.json()["id"]

    sign_in_trader(world)
    client = world["client"]
    attempts = (
        client.get(f"/api/v1/incoming-payment-receipts/{receipt_id}/matches"),
        client.post(
            f"/api/v1/incoming-payment-receipts/{receipt_id}/matches",
            json={"bank_statement_row_id": row_id},
            headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
        ),
        client.post(
            f"/api/v1/incoming-payment-receipts/{receipt_id}/matches/{match_id}/reject",
            json={"rejection_reason": "mine now"},
            headers={
                **csrf(world),
                "Idempotency-Key": str(uuid.uuid4()),
                "If-Match": '"rv-1"',
            },
        ),
    )
    for response in attempts:
        assert response.status_code == 403, (
            f"{response.request.method} {response.request.url.path} answered "
            f"{response.status_code}; a trader holds neither matching permission"
        )
