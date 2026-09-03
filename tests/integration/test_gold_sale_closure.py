"""The end of the chain, and the walk that proves the chain exists. M10 slice 8.

`06_Workflows_and_State_Machines.md` §8.2 and §12.3, `15_Agent_Implementation_Plan.md:1250`.

**`TRACE-M10-001` is the milestone's own Definition of Done**, and it is the last test in this
file: one order walked from creation to `closed` through every command M10 built, with each hop
asserted against the state the machine names. Nothing is stubbed and nothing is written directly
except the trader and the bank configuration — every business row is produced by the route that
owns it, because a walk that inserted its own intermediate states would prove the states exist and
not that anything can reach them.

Covers: SVC-GOLDCORRECT-001, TRACE-M10-001.
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

TRADER_PHONE = "+989120021001"
OTHER_PHONE = "+989120021002"
UNIT_PRICE = 5_000_000_000
WEIGHT = "10.000000"
PRICED = UNIT_PRICE * 10

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
        local_storage_root=tmp_path_factory.mktemp("closure-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="y" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    ids = {
        name: uuid.uuid4()
        for name in ("bank", "version", "account", "mapping", "trader", "other")
    }

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'closebank', 'Close Bank', 'active')",
            (ids["bank"],),
        )
        connection.execute(
            "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, status, "
            "config_hash) VALUES (%s, %s, 1, 'active', %s)",
            (ids["version"], ids["bank"], hashlib.sha256(b"close-version").hexdigest()),
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
                hashlib.sha256(b"close-mapping").hexdigest(),
            ),
        )
        for key, phone, name in (
            ("trader", TRADER_PHONE, "Buying Trader"),
            ("other", OTHER_PHONE, "Another Trader"),
        ):
            connection.execute(
                "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
                "approval_status) VALUES (%s, %s, %s, 'active', 'approved')",
                (ids[key], name, phone),
            )
            connection.execute(
                "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
                "status, is_primary) VALUES (%s, %s, %s, %s, 'active', TRUE)",
                (ids[key], phone, name, encoded),
            )
        for username, role in (
            ("close_accountant", "accountant"),
            ("close_warehouse", "warehouse_operator"),
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


def sign_in(world: dict[str, Any], username: str) -> None:
    client = world["client"]
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def sign_in_trader(world: dict[str, Any], phone: str = TRADER_PHONE) -> None:
    client = world["client"]
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/trader/login", json={"identifier": phone, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def csrf(world: dict[str, Any]) -> dict[str, str]:
    client = world["client"]
    token = client.cookies.get(ADMIN_CSRF_COOKIE) or client.cookies.get(TRADER_CSRF_COOKIE)
    assert token, "signed in but no CSRF cookie was set"
    return {CSRF_HEADER: token}


def headers(world: dict[str, Any], *, version: int | None = None) -> dict[str, str]:
    sent = {**csrf(world), "Idempotency-Key": str(uuid.uuid4())}
    if version is not None:
        sent["If-Match"] = f'"rv-{version}"'
    return sent


def a_dispatched_order(world: dict[str, Any], *, kind: str = "physical_dispatch") -> dict[str, Any]:
    """One order walked from creation to dispatched, through the real routes.

    Returned as a dict so the walk test and the guard tests share one path — every hop asserted
    here is asserted once, and a change that breaks the chain breaks every test rather than one.
    """

    client = world["client"]

    sign_in_trader(world)
    created = client.post(
        "/api/v1/gold-sale-orders",
        json={
            "gold_type": "bullion",
            "gold_weight": WEIGHT,
            "weight_unit": "GRAM",
            "gold_purity": "18K",
        },
        headers=headers(world),
    )
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]

    submitted = client.post(
        f"/api/v1/gold-sale-orders/{order_id}/submit",
        headers=headers(world, version=created.json()["record_version"]),
    )
    assert submitted.status_code == 200, submitted.text

    sign_in(world, "close_accountant")
    priced = client.post(
        f"/api/v1/gold-sale-orders/{order_id}/pricing-versions",
        json={"unit_price_irr": UNIT_PRICE},
        headers=headers(world, version=submitted.json()["record_version"]),
    )
    assert priced.status_code == 201, priced.text

    order_version = rows(
        world, "SELECT record_version FROM gold_sale_orders WHERE id = %s", order_id
    )[0][0]

    sign_in_trader(world)
    receipt = client.post(
        f"/api/v1/gold-sale-orders/{order_id}/incoming-payment-receipts",
        json={"amount_irr": PRICED},
        headers=headers(world),
    )
    assert receipt.status_code == 201, receipt.text
    receipt_id = receipt.json()["id"]

    sign_in(world, "close_accountant")
    row_id = _a_statement_row(world)
    match = client.post(
        f"/api/v1/incoming-payment-receipts/{receipt_id}/matches",
        json={"bank_statement_row_id": row_id},
        headers=headers(world),
    )
    assert match.status_code == 201, match.text

    confirmed = client.post(
        f"/api/v1/incoming-payment-receipts/{receipt_id}/confirm",
        json={
            "confirmed_amount_irr": PRICED,
            "incoming_payment_match_id": match.json()["id"],
        },
        headers=headers(world, version=match.json()["record_version"] + 1),
    )
    assert confirmed.status_code == 200, confirmed.text

    order_version = rows(
        world, "SELECT record_version FROM gold_sale_orders WHERE id = %s", order_id
    )[0][0]

    sign_in(world, "close_warehouse")
    body: dict[str, Any] = {"dispatch_type": kind}
    if kind.startswith("physical"):
        body["gold_weight"] = WEIGHT
        body["weight_unit"] = "GRAM"
    dispatched = client.post(
        f"/api/v1/gold-sale-orders/{order_id}/dispatches",
        json=body,
        headers=headers(world, version=order_version),
    )
    assert dispatched.status_code == 201, dispatched.text

    return {
        "order_id": order_id,
        "receipt_id": receipt_id,
        "dispatch_id": dispatched.json()["id"],
        "dispatch_version": dispatched.json()["record_version"],
        "order_status": dispatched.json()["order_status"],
    }


def _a_statement_row(world: dict[str, Any]) -> str:
    from app.workers.tasks.files import parse_statements

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    sheet.append(["2026-08-20", str(PRICED), f"TRK-{uuid.uuid4().hex[:8]}", "Buyer"])
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
        headers=headers(world),
    )
    assert statement.status_code == 201, statement.text
    run = world["client"].post(
        f"/api/v1/bank-statements/{statement.json()['id']}/import-runs",
        json={"bank_mapping_id": str(world["mapping_id"])},
        headers=headers(world),
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


# --- Document 06 §8.2's last two edges ---------------------------------------


def test_the_trader_acknowledges_and_the_order_closes(world: dict[str, Any]) -> None:
    """`dispatched --> received_by_trader --> closed`, both edges through their own routes."""

    case = a_dispatched_order(world)
    assert case["order_status"] == "dispatched"

    sign_in_trader(world)
    acknowledged = world["client"].post(
        f"/api/v1/gold-sale-orders/{case['order_id']}/dispatches/{case['dispatch_id']}"
        "/acknowledge",
        headers=headers(world, version=case["dispatch_version"]),
    )
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["order_status"] == "received_by_trader"
    assert acknowledged.json()["dispatch_status"] == "delivered"

    sign_in(world, "close_accountant")
    closed = world["client"].post(
        f"/api/v1/gold-sale-orders/{case['order_id']}/close",
        json={"closure_note": "gold handed over at the counter"},
        headers=headers(world, version=acknowledged.json()["order_record_version"]),
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["order_status"] == "closed"
    assert closed.json()["closed_at"] is not None


def test_a_settlement_closes_without_an_acknowledgement(world: dict[str, Any]) -> None:
    """§8.2's other edge: `settled_or_offset --> closed`, with no trader in it.

    Nothing moved, so there is nothing for the trader to confirm arriving — and requiring an
    acknowledgement would leave every offset permanently open.
    """

    case = a_dispatched_order(world, kind="offset_settlement")
    assert case["order_status"] == "settled_or_offset"

    order_version = rows(
        world, "SELECT record_version FROM gold_sale_orders WHERE id = %s", case["order_id"]
    )[0][0]

    sign_in(world, "close_accountant")
    closed = world["client"].post(
        f"/api/v1/gold-sale-orders/{case['order_id']}/close",
        json={},
        headers=headers(world, version=order_version),
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["order_status"] == "closed"


def test_an_order_still_in_transit_cannot_close(world: dict[str, Any]) -> None:
    """The closure guard §21.1 names, and what makes it a guard rather than an assignment.

    Metal is moving and nobody has confirmed it arriving; closing would record an ending nobody
    witnessed.
    """

    case = a_dispatched_order(world)
    order_version = rows(
        world, "SELECT record_version FROM gold_sale_orders WHERE id = %s", case["order_id"]
    )[0][0]

    sign_in(world, "close_accountant")
    response = world["client"].post(
        f"/api/v1/gold-sale-orders/{case['order_id']}/close",
        json={},
        headers=headers(world, version=order_version),
    )
    assert response.status_code == 400, response.text
    assert "dispatched" in response.text


def test_a_second_dispatch_in_transit_blocks_closing(world: dict[str, Any]) -> None:
    """The guard behind the status check, isolated — and it needed its own test.

    **Two controls went NOT CAUGHT because each guard was masked by the other**, which is the same
    shape slice 7 met: defence in depth hiding which layer is load-bearing. The status check
    refuses a `dispatched` order and the sweep refuses an order with metal moving, and every
    existing case tripped both.

    This is the case only the sweep can see. The order reaches `received_by_trader` — so the status
    check is satisfied — while a *second* physical dispatch is still in transit. An order may carry
    several, and closing here would record an ending for gold nobody has confirmed arriving.
    """

    case = a_dispatched_order(world)

    sign_in_trader(world)
    acknowledged = world["client"].post(
        f"/api/v1/gold-sale-orders/{case['order_id']}/dispatches/{case['dispatch_id']}"
        "/acknowledge",
        headers=headers(world, version=case["dispatch_version"]),
    )
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["order_status"] == "received_by_trader"

    # A second movement on the same order, still in transit. Written directly because the dispatch
    # route would move the order back to `dispatched` and re-arm the status check — and the point
    # of this test is the state where only the sweep can refuse.
    second = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO gold_dispatches (id, gold_sale_order_id, dispatch_type, status, "
            "weight, weight_unit, created_by_admin_user_id, dispatched_at, record_version) "
            "SELECT %s, %s, 'physical_dispatch', 'dispatched', 1.000000, 'GRAM', u.id, now(), 1 "
            "FROM admin_users u WHERE u.username = 'close_warehouse'",
            (second, case["order_id"]),
        )
        connection.commit()

    order_version = rows(
        world, "SELECT record_version FROM gold_sale_orders WHERE id = %s", case["order_id"]
    )[0][0]

    sign_in(world, "close_accountant")
    response = world["client"].post(
        f"/api/v1/gold-sale-orders/{case['order_id']}/close",
        json={},
        headers=headers(world, version=order_version),
    )
    assert response.status_code == 400, (
        f"an order with a second dispatch in transit closed, answering {response.status_code}. "
        "The status said received_by_trader and metal was still moving."
    )
    assert str(second) in response.text, (
        "the refusal does not name the dispatch that is still moving, so an operator cannot act "
        "on it"
    )


def test_a_settlement_cannot_be_acknowledged(world: dict[str, Any]) -> None:
    """A settlement moved no metal, so there is nothing to confirm arriving."""

    case = a_dispatched_order(world, kind="manual_settlement")

    sign_in_trader(world)
    response = world["client"].post(
        f"/api/v1/gold-sale-orders/{case['order_id']}/dispatches/{case['dispatch_id']}"
        "/acknowledge",
        headers=headers(world, version=case["dispatch_version"]),
    )
    assert response.status_code == 400, response.text


# --- The two negative tests the surface owes ---------------------------------


def test_a_second_trader_cannot_acknowledge_somebody_elses_gold(world: dict[str, Any]) -> None:
    """Ownership, and 404 rather than 403.

    An authorisation error over a guessable id tells the second trader the dispatch exists, which
    `app/security/ownership.py` refuses to do — the same call every trader-scoped route in this
    milestone makes.
    """

    case = a_dispatched_order(world)

    sign_in_trader(world, OTHER_PHONE)
    response = world["client"].post(
        f"/api/v1/gold-sale-orders/{case['order_id']}/dispatches/{case['dispatch_id']}"
        "/acknowledge",
        headers=headers(world, version=case["dispatch_version"]),
    )
    assert response.status_code == 404, (
        f"a second trader acknowledging somebody else's gold answered {response.status_code}; 404 "
        "and 403 must be indistinguishable here"
    )
    assert rows(
        world, "SELECT status FROM gold_dispatches WHERE id = %s", case["dispatch_id"]
    )[0][0] == "dispatched"


def test_the_centre_cannot_acknowledge_on_a_traders_behalf(world: dict[str, Any]) -> None:
    """The permission half of a `DUAL` route, and it refuses the *internal* caller.

    "The trader says the gold arrived" is a different assertion from "the centre says so", and the
    audit row is where that difference has to survive — the same call slice 2 made for the payment
    claim. An accountant with every gold-sale permission is refused, because none of them is the
    trader.
    """

    case = a_dispatched_order(world)

    sign_in(world, "close_accountant")
    response = world["client"].post(
        f"/api/v1/gold-sale-orders/{case['order_id']}/dispatches/{case['dispatch_id']}"
        "/acknowledge",
        headers=headers(world, version=case["dispatch_version"]),
    )
    assert response.status_code == 403, (
        f"the centre acknowledged on a trader's behalf, answering {response.status_code}"
    )
    assert rows(
        world, "SELECT confirmed_at FROM gold_dispatches WHERE id = %s", case["dispatch_id"]
    )[0][0] is None


def test_no_trader_can_close_their_own_order(world: dict[str, Any]) -> None:
    """Closing is the centre's judgement that the business is finished.

    A trader may say the gold arrived — that is the acknowledgement above — and may not decide the
    order is done. `gold_sale.review` is the permission the catalogue gives that judgement, and no
    trader holds it.
    """

    case = a_dispatched_order(world)

    sign_in_trader(world)
    acknowledged = world["client"].post(
        f"/api/v1/gold-sale-orders/{case['order_id']}/dispatches/{case['dispatch_id']}"
        "/acknowledge",
        headers=headers(world, version=case["dispatch_version"]),
    )
    assert acknowledged.status_code == 200, acknowledged.text

    response = world["client"].post(
        f"/api/v1/gold-sale-orders/{case['order_id']}/close",
        json={},
        headers=headers(world, version=acknowledged.json()["order_record_version"]),
    )
    assert response.status_code == 403, (
        f"a trader closed their own order, answering {response.status_code}"
    )


# --- SVC-GOLDCORRECT-001 -----------------------------------------------------


def test_a_correction_preserves_the_superseded_pricing_row(world: dict[str, Any]) -> None:
    """`SVC-GOLDCORRECT-001`. §18 `:1246`: "corrections preserve prior pricing/payment/dispatch
    history".

    Read back through `row_to_json` — the M9 slice 7B pattern — so every column is compared rather
    than the two somebody thought to name. A repricing supersedes the earlier version; the earlier
    row must be byte-identical afterwards apart from the supersession stamp that marks it
    historical.
    """

    client = world["client"]
    sign_in_trader(world)
    created = client.post(
        "/api/v1/gold-sale-orders",
        json={
            "gold_type": "bullion",
            "gold_weight": WEIGHT,
            "weight_unit": "GRAM",
            "gold_purity": "18K",
        },
        headers=headers(world),
    )
    order_id = created.json()["id"]
    submitted = client.post(
        f"/api/v1/gold-sale-orders/{order_id}/submit",
        headers=headers(world, version=created.json()["record_version"]),
    )

    sign_in(world, "close_accountant")
    first = client.post(
        f"/api/v1/gold-sale-orders/{order_id}/pricing-versions",
        json={"unit_price_irr": UNIT_PRICE},
        headers=headers(world, version=submitted.json()["record_version"]),
    )
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]

    before = rows(
        world,
        "SELECT row_to_json(t) FROM (SELECT * FROM gold_sale_pricing_versions WHERE id = %s) t",
        first_id,
    )[0][0]

    order_version = rows(
        world, "SELECT record_version FROM gold_sale_orders WHERE id = %s", order_id
    )[0][0]
    second = client.post(
        f"/api/v1/gold-sale-orders/{order_id}/pricing-versions",
        json={"unit_price_irr": UNIT_PRICE * 2},
        headers=headers(world, version=order_version),
    )
    assert second.status_code == 201, second.text

    after = rows(
        world,
        "SELECT row_to_json(t) FROM (SELECT * FROM gold_sale_pricing_versions WHERE id = %s) t",
        first_id,
    )[0][0]

    changed = {
        key for key in before if before[key] != after[key]
    } | {key for key in after if key not in before}
    assert changed <= {"superseded_at"}, (
        f"repricing changed {sorted(changed)} on the superseded row. Only the supersession stamp "
        "may move; everything else is what the earlier price *was*, and a correction that edits it "
        "destroys the history §18 `:1246` requires."
    )
    assert after["superseded_at"] is not None
    assert after["unit_price_irr"] == before["unit_price_irr"]


# --- TRACE-M10-001, the Definition of Done -----------------------------------


def test_the_milestone_walks_end_to_end(world: dict[str, Any]) -> None:
    """`TRACE-M10-001`. §18 `:1250`:

    > M10 is complete when a trader order can be priced, paid or settled, verified, dispatched, and
    > closed with a traceable manual workflow.

    Six words, six hops, each through the route that owns it. **Nothing is inserted directly**
    except the trader and the bank configuration, because a walk that wrote its own intermediate
    states would prove the states exist and not that anything can reach them — which is the
    difference between a Definition of Done and a list of columns.

    The trace is asserted at the end by joining every table the walk touched: an order, a pricing
    version, a receipt, a statement row, a match, a dispatch. Each hop resolves to the next, which
    is what "traceable" means.
    """

    case = a_dispatched_order(world)
    order_id = case["order_id"]

    sign_in_trader(world)
    acknowledged = world["client"].post(
        f"/api/v1/gold-sale-orders/{order_id}/dispatches/{case['dispatch_id']}/acknowledge",
        headers=headers(world, version=case["dispatch_version"]),
    )
    assert acknowledged.status_code == 200, acknowledged.text

    sign_in(world, "close_accountant")
    closed = world["client"].post(
        f"/api/v1/gold-sale-orders/{order_id}/close",
        json={"closure_note": "complete"},
        headers=headers(world, version=acknowledged.json()["order_record_version"]),
    )
    assert closed.status_code == 200, closed.text

    walk = rows(
        world,
        """
        SELECT o.status,
               p.unit_price_irr,
               r.confirmed_amount_irr,
               m.confirmation_status,
               row.amount_in_irr,
               run.status,
               d.dispatch_type,
               d.status,
               o.closed_at
        FROM gold_sale_orders o
        JOIN gold_sale_pricing_versions p ON p.id = o.current_pricing_version_id
        JOIN incoming_payment_receipts r ON r.gold_sale_order_id = o.id
        JOIN incoming_payment_matches m ON m.incoming_payment_receipt_id = r.id
        JOIN bank_statement_rows row ON row.id = m.bank_statement_row_id
        JOIN bank_statement_import_runs run
          ON run.id = row.bank_statement_import_run_id
        JOIN gold_dispatches d ON d.gold_sale_order_id = o.id
        WHERE o.id = %s
        """,
        order_id,
    )

    assert len(walk) == 1, (
        f"the chain resolved to {len(walk)} rows. Every hop from order to dispatch must join, "
        "which is what §18 `:1250` means by traceable."
    )
    (
        order_status,
        unit_price,
        confirmed,
        confirmation_status,
        row_amount,
        run_status,
        dispatch_type,
        dispatch_status,
        closed_at,
    ) = walk[0]

    assert order_status == "closed"
    assert unit_price == UNIT_PRICE
    assert confirmed == PRICED, "the confirmed amount is not what the bank row shows"
    assert confirmation_status == "active", "the match is not the authoritative one"
    assert row_amount == PRICED, "the statement row does not carry the amount that was confirmed"
    assert run_status == "succeeded", "the row came from a parse that did not finish"
    assert dispatch_type == "physical_dispatch"
    assert dispatch_status == "delivered", "the trader's acknowledgement did not reach the dispatch"
    assert closed_at is not None

    # And the audit trail says the same thing, because a chain of rows with no record of who moved
    # them is traceable only in the weakest sense.
    #
    # **Gathered by walking the chain, not by asking which rows mention the order.** The first
    # version of this assertion did the latter and missed two actions: `incoming_match.proposed`
    # names the *match* and `incoming_payment.confirmed` names the *receipt*, because an audit row
    # names the thing that changed. Following the entity chain is what traceability means — if the
    # trail could only be found by every row carrying the order id, the chain would be doing no
    # work.
    entity_ids = [
        entry[0]
        for entry in rows(
            world,
            """
            SELECT o.id FROM gold_sale_orders o WHERE o.id = %s
            UNION ALL
            SELECT r.id FROM incoming_payment_receipts r WHERE r.gold_sale_order_id = %s
            UNION ALL
            SELECT m.id FROM incoming_payment_matches m
              JOIN incoming_payment_receipts r ON r.id = m.incoming_payment_receipt_id
             WHERE r.gold_sale_order_id = %s
            UNION ALL
            SELECT d.id FROM gold_dispatches d WHERE d.gold_sale_order_id = %s
            """,
            order_id,
            order_id,
            order_id,
            order_id,
        )
    ]
    assert len(entity_ids) >= 4, (
        f"the chain yielded {len(entity_ids)} entities to look for audit rows against; an order, "
        "a receipt, a match and a dispatch are the minimum this walk creates"
    )

    actions = [
        entry[0]
        for entry in rows(
            world,
            "SELECT action FROM audit_logs WHERE entity_id = ANY(%s) ORDER BY occurred_at",
            entity_ids,
        )
    ]
    for expected in (
        "gold_sale.created",
        "gold_sale.priced",
        "incoming_receipt.submitted",
        "incoming_match.proposed",
        "incoming_payment.confirmed",
        "gold_sale.dispatched",
        "gold_dispatch.acknowledged",
        "gold_sale.closed",
    ):
        assert expected in actions, (
            f"{expected!r} is missing from the order's audit trail: {actions}"
        )
