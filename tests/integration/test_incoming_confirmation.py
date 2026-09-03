"""A person decides the money arrived. M10 slice 6.

Against a real PostgreSQL. `05_API_Specification.md` §21.6, `04_Database_Schema.md` §10.3 and
§10.7, `06_Workflows_and_State_Machines.md` §11.

**§21.6's last line is what every test here checks from one side or another:** "Partial, excess, or
ambiguous amounts produce explicit order state/review tasks. They are not silently treated as fully
paid."

The arithmetic case is the one worth reading first. Two receipts of 40 against an order priced at
100 leave the order `incoming_payment_partially_confirmed` even though the *second* receipt was
confirmed in full — because the order's state comes from the sum of confirmed receipts and never
from the receipt in front of the accountant. There is no cached total and there must not be one:
`04_Database_Schema.md:469` forbids a second copy of a balance.

Covers: SVC-INCOMING-001, SVC-INCOMING-002, AUD-INCOMING-001.
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

TRADER_PHONE = "+989120017001"
PRICED = 100_000_000_000

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
        local_storage_root=tmp_path_factory.mktemp("confirm-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="w" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    ids = {name: uuid.uuid4() for name in ("bank", "version", "account", "mapping", "trader")}

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'confbank', 'Confirm Bank', 'active')",
            (ids["bank"],),
        )
        connection.execute(
            "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, status, "
            "config_hash) VALUES (%s, %s, 1, 'active', %s)",
            (ids["version"], ids["bank"], hashlib.sha256(b"conf-version").hexdigest()),
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
                hashlib.sha256(b"conf-mapping").hexdigest(),
            ),
        )
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'Confirming Trader', %s, 'active', 'approved')",
            (ids["trader"], TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Buyer', %s, 'active', TRUE)",
            (ids["trader"], TRADER_PHONE, encoded),
        )
        connection.execute(
            "INSERT INTO admin_users (username, full_name, password_hash, status) "
            "VALUES ('conf_accountant', 'Accountant', %s, 'active')",
            (encoded,),
        )
        connection.execute(
            "INSERT INTO admin_user_roles (admin_user_id, role_id) "
            "SELECT u.id, r.id FROM admin_users u, roles r "
            "WHERE u.username = 'conf_accountant' AND r.code = 'accountant'"
        )
        connection.commit()

    app = create_app(settings=settings)
    app.state.runtime = RuntimeServices.from_settings(settings)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://admin.localhost") as client:
        yield {
            "client": client,
            "owner_url": migrated.owner_url,
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
        json={"identifier": "conf_accountant", "password": PASSWORD},
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


def an_order(world: dict[str, Any], *, priced: int | None = PRICED) -> str:
    order_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO gold_sale_orders (id, trader_id, order_number, status, gold_type, "
            "gold_weight, weight_unit, gold_purity, expected_amount_irr, created_by_actor_type, "
            "record_version) VALUES (%s, %s, %s, 'payment_evidence_submitted', 'bullion', "
            "10.000000, 'GRAM', '18K', %s, 'trader_user', 1)",
            (order_id, world["trader_id"], f"GS-{str(order_id)[:8]}", priced),
        )
        connection.commit()
    return str(order_id)


def a_receipt(world: dict[str, Any], order_id: str, amount: int) -> str:
    receipt_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO incoming_payment_receipts (id, gold_sale_order_id, trader_id, "
            "amount_irr, status, record_version) VALUES (%s, %s, %s, %s, 'submitted', 1)",
            (receipt_id, order_id, world["trader_id"], amount),
        )
        connection.commit()
    return str(receipt_id)


def confirm(
    world: dict[str, Any],
    receipt_id: str,
    amount: int,
    *,
    version: int = 1,
    match_id: str | None = None,
    note: str | None = None,
) -> Any:
    body: dict[str, Any] = {"confirmed_amount_irr": amount}
    if match_id is not None:
        body["incoming_payment_match_id"] = match_id
    if note is not None:
        body["confirmation_note"] = note
    return world["client"].post(
        f"/api/v1/incoming-payment-receipts/{receipt_id}/confirm",
        json=body,
        headers={
            **csrf(world),
            "Idempotency-Key": str(uuid.uuid4()),
            "If-Match": f'"rv-{version}"',
        },
    )


def order_status(world: dict[str, Any], order_id: str) -> str:
    return rows(world, "SELECT status FROM gold_sale_orders WHERE id = %s", order_id)[0][0]


def tasks_for(world: dict[str, Any], entity_id: str) -> list[tuple[Any, ...]]:
    return rows(
        world,
        "SELECT task_type, entity_type, status, title FROM manual_review_tasks "
        "WHERE entity_id = %s",
        entity_id,
    )


# --- SVC-INCOMING-001 --------------------------------------------------------


def test_two_partial_payments_aggregate_to_the_order(world: dict[str, Any]) -> None:
    """`SVC-INCOMING-001`. §18 `:1240`: "multiple receipts and partial incoming payments aggregate
    correctly".

    **The second receipt is confirmed in full and the order is still partial**, because the order's
    state comes from the sum and not from the receipt in front of the accountant. That is the whole
    assertion: a command reading only its own receipt would mark the order confirmed here and every
    single-receipt test would still pass.
    """

    sign_in_admin(world)
    order_id = an_order(world)
    first = a_receipt(world, order_id, 40_000_000_000)
    second = a_receipt(world, order_id, 40_000_000_000)

    assert confirm(world, first, 40_000_000_000).status_code == 200
    assert order_status(world, order_id) == "incoming_payment_partially_confirmed"

    response = confirm(world, second, 40_000_000_000)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["confirmed_total_irr"] == 80_000_000_000, (
        f"the order totals {body['confirmed_total_irr']} after two confirmations of 40 billion. "
        "The sum is read from the confirmed receipts, not from this one."
    )
    assert body["receipt_status"] == "partially_confirmed"
    assert order_status(world, order_id) == "incoming_payment_partially_confirmed", (
        "the order was marked confirmed while 20 billion of 100 is still outstanding"
    )


def test_the_last_payment_completes_the_order(world: dict[str, Any]) -> None:
    """The other half of the same arithmetic: when the sum reaches the price, the order closes."""

    sign_in_admin(world)
    order_id = an_order(world)
    first = a_receipt(world, order_id, 60_000_000_000)
    second = a_receipt(world, order_id, 40_000_000_000)

    confirm(world, first, 60_000_000_000)
    response = confirm(world, second, 40_000_000_000)

    assert response.status_code == 200, response.text
    assert response.json()["confirmed_total_irr"] == PRICED
    assert response.json()["receipt_status"] == "confirmed"
    assert order_status(world, order_id) == "incoming_payment_confirmed"


def test_no_column_caches_the_paid_total(world: dict[str, Any]) -> None:
    """`04_Database_Schema.md:469` forbids a second copy of a balance.

    Asserted as an absence over the schema, because a cached total is invisible to every
    behavioural test until it goes stale — and the moment it goes stale is a correction, which is
    exactly when nobody is looking at the arithmetic.
    """

    columns = {
        row[0]
        for row in rows(
            world,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'gold_sale_orders'",
        )
    }
    forbidden = {"paid_amount_irr", "confirmed_amount_irr", "confirmed_total_irr", "paid_total_irr"}
    assert not (columns & forbidden), (
        f"gold_sale_orders caches a paid total in {sorted(columns & forbidden)}. `:469` forbids a "
        "second copy of a balance, and `final_amount_irr` is the priced figure rather than a "
        "running sum."
    )


# --- SVC-INCOMING-002 --------------------------------------------------------


def test_an_overpayment_is_refused_and_opens_a_task(world: dict[str, Any]) -> None:
    """`SVC-INCOMING-002`. §21.6: excess is not silently treated as fully paid.

    **Both halves, and the second is the one M9 got wrong first time.** The confirmation is refused
    *and* the review task survives — a refusal that rolled back its own record would leave nobody
    asked to look at the discrepancy, and a task without the refusal would record the money as
    received while somebody is still deciding.
    """

    sign_in_admin(world)
    order_id = an_order(world)
    receipt_id = a_receipt(world, order_id, 120_000_000_000)

    response = confirm(world, receipt_id, 120_000_000_000)
    assert response.status_code == 400, response.text
    assert "would total" in response.text

    receipt = rows(
        world,
        "SELECT status, confirmed_amount_irr, confirmed_at FROM incoming_payment_receipts "
        "WHERE id = %s",
        receipt_id,
    )[0]
    assert receipt[0] == "submitted", (
        f"the receipt is {receipt[0]!r} after a refused confirmation; nothing should have moved"
    )
    assert receipt[1] is None and receipt[2] is None

    opened = tasks_for(world, receipt_id)
    assert len(opened) == 1, (
        f"{len(opened)} tasks survived the refusal. The task is the point of refusing — a "
        "transaction that rolls back its own record leaves nobody asked to look."
    )
    task_type, entity_type, status, title = opened[0]
    assert task_type == "incoming_payment_discrepancy", (
        f"the task is a {task_type!r}. Borrowing an outgoing-payment or statement-row type would "
        "file this in a queue an accountant filters for something else."
    )
    assert entity_type == "incoming_payment_receipt", (
        f"the task points at a {entity_type!r} while carrying a receipt id — a reference nothing "
        "can navigate"
    )
    assert status == "open"
    assert "120000000000" in title and "100000000000" in title


def test_an_overpayment_across_two_receipts_is_also_refused(world: dict[str, Any]) -> None:
    """The sum is what the guard reads, not this receipt's amount.

    Sixty and sixty against a hundred: neither is an overpayment alone, and together they are. A
    guard comparing only the receipt in front of it would accept both.
    """

    sign_in_admin(world)
    order_id = an_order(world)
    first = a_receipt(world, order_id, 60_000_000_000)
    second = a_receipt(world, order_id, 60_000_000_000)

    assert confirm(world, first, 60_000_000_000).status_code == 200
    response = confirm(world, second, 60_000_000_000)

    assert response.status_code == 400, (
        f"the second confirmation answered {response.status_code}. 60 + 60 is 120 against 100 "
        "priced, and the guard reads the sum."
    )
    assert order_status(world, order_id) == "incoming_payment_partially_confirmed", (
        "the refused confirmation moved the order anyway"
    )


def test_a_confirmation_of_nothing_is_refused(world: dict[str, Any]) -> None:
    """§10.3's CHECK permits a confirmed amount of zero; this route does not.

    The column allows zero because a *correction* may find that nothing arrived — that is slice
    8's. Confirming zero is not a confirmation, and the schema rejects it at the edge (422) rather
    than recording an event that says money moved when none did.
    """

    sign_in_admin(world)
    order_id = an_order(world)
    receipt_id = a_receipt(world, order_id, 10_000_000_000)

    response = confirm(world, receipt_id, 0)
    assert response.status_code == 422, response.text


# --- AUD-INCOMING-001 --------------------------------------------------------


def test_the_audit_entry_carries_both_figures(world: dict[str, Any]) -> None:
    """`AUD-INCOMING-001`. `incoming_payment.confirmed`, one of the two catalogued M10 actions.

    **Both figures**: what this confirmation added and what the order now totals. An entry with
    only the first cannot answer "was the order fully paid at this moment", which is the question
    every later reader of a partial payment asks.
    """

    sign_in_admin(world)
    order_id = an_order(world)
    receipt_id = a_receipt(world, order_id, 30_000_000_000)

    confirmed = confirm(world, receipt_id, 30_000_000_000, note="checked against row 14")
    assert confirmed.status_code == 200, confirmed.text

    entry = rows(
        world,
        "SELECT action, entity_type, new_values, reason FROM audit_logs "
        "WHERE entity_id = %s ORDER BY occurred_at DESC LIMIT 1",
        receipt_id,
    )[0]
    assert entry[0] == "incoming_payment.confirmed"
    assert entry[1] == "incoming_payment_receipt"
    assert entry[2]["confirmed_amount_irr"] == "30000000000"
    assert entry[2]["order_confirmed_total_irr"] == "30000000000"
    assert entry[2]["expected_amount_irr"] == str(PRICED)
    assert entry[2]["order_status"] == "incoming_payment_partially_confirmed"
    # Null and present, so a reader can tell "no bank row was cited" from "the field was forgotten".
    assert "incoming_payment_match_id" in entry[2]
    assert entry[2]["incoming_payment_match_id"] is None
    assert entry[3] == "checked against row 14"


# --- The outbox event slice 6 was meant to publish ----------------------------


def test_a_completed_order_publishes_the_event_the_catalogue_names(
    world: dict[str, Any],
) -> None:
    """`GoldOrderReadyForDispatch`, and M10 slice 8 added it because slice 6 did not.

    `command_catalog.yaml`'s `incoming_payment.confirm` names the event; slice 6 declared
    `outbox_event_type=None` after reading the wrong catalogue file, and no gate could see the
    absence — the registry test asked whether a *declared* event was real and never whether a
    *required* one was declared. `test_a_command_row_that_names_an_event_has_one_declared` asks the
    second question now.

    A missing event is silent in a way a wrong one is not: nothing fires, nobody is told, and every
    test passes because none of them was asked to observe an absence.
    """

    sign_in_admin(world)
    order_id = an_order(world)
    receipt_id = a_receipt(world, order_id, PRICED)

    assert confirm(world, receipt_id, PRICED).status_code == 200

    events = rows(
        world,
        "SELECT event_type, aggregate_type, payload FROM outbox_events WHERE aggregate_id = %s",
        order_id,
    )
    assert len(events) == 1, (
        f"{len(events)} outbox events for a completed order; the catalogue names exactly one."
    )
    assert events[0][0] == "GoldOrderReadyForDispatch"
    assert events[0][1] == "gold_sale_order"
    assert events[0][2]["confirmed_total_irr"] == str(PRICED)
    assert events[0][2]["order_status"] == "incoming_payment_confirmed"


def test_a_partial_confirmation_publishes_nothing(world: dict[str, Any]) -> None:
    """The event's name is a claim that the order may now move, so it fires on the transition only.

    Publishing on every confirmation would say "ready for dispatch" while money is still
    outstanding, and a trigger that is wrong half the time is one nothing downstream can act on.
    """

    sign_in_admin(world)
    order_id = an_order(world)
    receipt_id = a_receipt(world, order_id, 30_000_000_000)

    assert confirm(world, receipt_id, 30_000_000_000).status_code == 200

    assert rows(
        world, "SELECT count(*) FROM outbox_events WHERE aggregate_id = %s", order_id
    )[0][0] == 0, "a partially paid order announced itself ready for dispatch"


def test_the_trader_is_told_their_order_is_ready(world: dict[str, Any]) -> None:
    """The projection's first non-payment-request aggregate, end to end.

    M9 slice 7 built the projection around `payment_request_id`; a gold sale order has none, so
    `_gold_order_message` resolves the trader through the order instead. The whole path is asserted
    — confirm, enqueue, dispatch, notification — because each half alone has been green while the
    other was missing, which is the defect this slice exists to close.
    """

    from app.notifications.projection import notification_deliverer
    from app.workers.dispatcher import dispatch_once

    sign_in_admin(world)
    order_id = an_order(world)
    receipt_id = a_receipt(world, order_id, PRICED)
    assert confirm(world, receipt_id, PRICED).status_code == 200

    runtime = world["runtime"]
    dispatch_once(
        runtime.uow_factory,
        notification_deliverer(runtime.uow_factory),
        worker_id="test-dispatcher",
    )

    messages = rows(
        world,
        "SELECT notification_type, title, body, entity_type, status FROM notifications "
        "WHERE entity_id = %s",
        order_id,
    )
    assert len(messages) == 1, (
        f"{len(messages)} notifications for a completed order; the trader is told once."
    )
    notification_type, title, body, entity_type, status = messages[0]
    assert notification_type == "gold_order_ready_for_dispatch"
    assert entity_type == "gold_sale_order"
    assert status == "unread"

    order_number = rows(
        world, "SELECT order_number FROM gold_sale_orders WHERE id = %s", order_id
    )[0][0]
    assert order_number in title, (
        f"the title is {title!r} and does not name the order. The order number is what the trader "
        "recognises."
    )
    assert str(PRICED) in body


# --- Document 06 §11.2 and §11.3 ---------------------------------------------


def test_confirming_a_match_sets_the_second_axis(world: dict[str, Any]) -> None:
    """Document 06 §11.2's `active`, on the column slice 6 added.

    The candidate's own `status` does not move: it was `proposed` and it stays `proposed`, because
    the two lifecycles are separate and overwriting the first with the second would lose which
    route the candidate took to get here.
    """

    from app.workers.tasks.files import parse_statements

    sign_in_admin(world)
    order_id = an_order(world)
    receipt_id = a_receipt(world, order_id, 25_000_000_000)
    row_id = _a_statement_row(world, parse_statements)

    proposed = world["client"].post(
        f"/api/v1/incoming-payment-receipts/{receipt_id}/matches",
        json={"bank_statement_row_id": row_id},
        headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert proposed.status_code == 201, proposed.text
    match_id = proposed.json()["id"]

    # Proposing moved the receipt, so its version is 2.
    response = confirm(world, receipt_id, 25_000_000_000, version=2, match_id=match_id)
    assert response.status_code == 200, response.text

    match = rows(
        world,
        "SELECT status, confirmation_status, confirmed_amount_irr, confirmed_at "
        "FROM incoming_payment_matches WHERE id = %s",
        match_id,
    )[0]
    assert match[0] == "proposed", (
        f"the candidate's status became {match[0]!r}. The two lifecycles are separate columns; "
        "overwriting the first loses which route the candidate took."
    )
    assert match[1] == "active", (
        f"the confirmation axis is {match[1]!r}. Document 06 §11.2's first state is what an "
        "authoritative match carries."
    )
    assert match[2] == 25_000_000_000
    assert match[3] is not None


def test_a_statement_row_cannot_fund_two_claims(world: dict[str, Any]) -> None:
    """Document 06 §11.3's third rule: "A row already used in an active match causes a
    duplicate/conflict guard."

    409 rather than 400, because the right answer is usually to correct the earlier match rather
    than abandon this one. And the guard lives in the command rather than in a partial unique
    index, because an index would answer §10.7 `:809`'s open cardinality question in a migration —
    which is what slice 5's `test_no_partial_unique_constrains_the_pair` exists to prevent.
    """

    from app.workers.tasks.files import parse_statements

    sign_in_admin(world)
    row_id = _a_statement_row(world, parse_statements)

    first_order = an_order(world)
    first_receipt = a_receipt(world, first_order, 25_000_000_000)
    first_match = world["client"].post(
        f"/api/v1/incoming-payment-receipts/{first_receipt}/matches",
        json={"bank_statement_row_id": row_id},
        headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert first_match.status_code == 201
    assert confirm(
        world, first_receipt, 25_000_000_000, version=2, match_id=first_match.json()["id"]
    ).status_code == 200

    second_order = an_order(world)
    second_receipt = a_receipt(world, second_order, 25_000_000_000)
    second_match = world["client"].post(
        f"/api/v1/incoming-payment-receipts/{second_receipt}/matches",
        json={"bank_statement_row_id": row_id},
        headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert second_match.status_code == 201, (
        "the second *proposal* was refused. §10.7's baseline is many-to-many for candidates; only "
        "an active confirmation is guarded."
    )

    response = confirm(
        world, second_receipt, 25_000_000_000, version=2, match_id=second_match.json()["id"]
    )
    assert response.status_code == 409, (
        f"a second claim confirmed against the same bank row, answering {response.status_code}. "
        "One credit cannot pay two different orders."
    )


def _a_statement_row(world: dict[str, Any], parse_statements: Any) -> str:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    sheet.append(["2026-08-20", "25000000000", f"TRK-{uuid.uuid4().hex[:8]}", "Buyer"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    content = buffer.getvalue()

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
    return str(
        rows(
            world,
            "SELECT id FROM bank_statement_rows WHERE bank_statement_import_run_id = %s",
            run.json()["id"],
        )[0][0]
    )


# --- Concurrency and authorisation -------------------------------------------


def test_a_stale_if_match_is_refused(world: dict[str, Any]) -> None:
    """Two accountants confirming one receipt. The second must be told."""

    sign_in_admin(world)
    order_id = an_order(world)
    receipt_id = a_receipt(world, order_id, 10_000_000_000)

    response = confirm(world, receipt_id, 10_000_000_000, version=99)
    assert response.status_code == 409, response.text


def test_a_receipt_cannot_be_confirmed_twice(world: dict[str, Any]) -> None:
    """A closed claim is corrected, not re-decided. Slice 8's, and refused here."""

    sign_in_admin(world)
    order_id = an_order(world)
    receipt_id = a_receipt(world, order_id, PRICED)

    assert confirm(world, receipt_id, PRICED).status_code == 200
    response = confirm(world, receipt_id, PRICED, version=2)
    assert response.status_code == 400, response.text
    assert "confirmed" in response.text


def test_no_trader_can_confirm_their_own_payment(world: dict[str, Any]) -> None:
    """`permission_catalog.yaml` gives a trader no `incoming_payment.confirm`.

    Its own test rather than the matching one, because the permission is different: a test proving
    `.match` is denied proves nothing about `.confirm`. And the reasoning is the point of the whole
    milestone — a trader who could confirm their own claim would be deciding that their own money
    arrived, which is the one thing a bank statement exists to answer independently.
    """

    sign_in_admin(world)
    order_id = an_order(world)
    receipt_id = a_receipt(world, order_id, 10_000_000_000)

    sign_in_trader(world)
    response = confirm(world, receipt_id, 10_000_000_000)
    assert response.status_code == 403, (
        f"a trader confirming their own payment answered {response.status_code}"
    )
