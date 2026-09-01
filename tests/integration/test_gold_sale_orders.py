"""Placing, submitting and pricing a gold sale order.

M10 slice 1, against a real PostgreSQL. `05_API_Specification.md` §21.1-21.2,
`04_Database_Schema.md` §10.1-10.2.

**The pricing tests are the slice.** §10.2 at `:731` requires that updating a price *creates a row*
and repoints the order transactionally, and `UNIQUE(gold_sale_order_id, content_hash)` refuses a
re-price that changed nothing. Both are properties of what survives, so both read the old row back
rather than trusting the command.

**`gold_weight` is the first non-integer quantity this system stores**, and two tests exist because
of it: the amount is computed rather than submitted, and the weight survives a round trip through
JSON, `Decimal`, `NUMERIC` and back without becoming a float.

Covers: DB-GOLDSALE-001, SVC-PRICING-001, SVC-PRICING-002.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery-staple"
CSRF_HEADER = "X-CSRF-Token"
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"
TRADER_CSRF_COOKIE = "__Host-gp_trader_csrf"

OWNER_PHONE = "+989120012001"
OTHER_PHONE = "+989120012002"

WEIGHT = "125.500000"
UNIT_PRICE = 80_000_000


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
        local_storage_root=tmp_path_factory.mktemp("gold-sale-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="q" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    ids = {name: uuid.uuid4() for name in ("owner", "other")}

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        for key, phone, name in (
            ("owner", OWNER_PHONE, "Gold Buyer"),
            ("other", OTHER_PHONE, "Other Buyer"),
        ):
            connection.execute(
                "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
                "approval_status) VALUES (%s, %s, %s, 'active', 'approved')",
                (ids[key], name, phone),
            )
            connection.execute(
                "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
                "status, is_primary) VALUES (%s, %s, %s, %s, 'active', TRUE)",
                (ids[key], phone, f"{name} Contact", encoded),
            )
        for username, role in (
            # Holds `gold_sale.price`, `.review`, `.read`, `.cancel` (`20260801_0008:227-230`).
            ("gold_accountant", "accountant"),
            # Holds `gold_sale.read` and **not** `.price` (`:309`). The sharp negative for pricing:
            # it gets past any "some gold-sale grant" guard and must still be refused.
            ("gold_manager", "manager"),
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
            **{f"{name}_id": value for name, value in ids.items()},
        }
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def rows(world: dict[str, Any], sql: str, *parameters: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        return connection.execute(sql, parameters).fetchall()


def sign_in_trader(world: dict[str, Any], phone: str) -> None:
    client = world["client"]
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/trader/login", json={"identifier": phone, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def sign_in_admin(world: dict[str, Any], username: str) -> None:
    client = world["client"]
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def csrf(world: dict[str, Any]) -> dict[str, str]:
    client = world["client"]
    token = client.cookies.get(TRADER_CSRF_COOKIE) or client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token, "signed in but no CSRF cookie was set"
    return {CSRF_HEADER: token}


def create_order(world: dict[str, Any], **overrides: Any) -> Any:
    client = world["client"]
    body: dict[str, Any] = {
        "gold_type": "bullion",
        "gold_weight": WEIGHT,
        "weight_unit": "GRAM",
        "gold_purity": "18K",
    }
    body.update(overrides)
    return client.post(
        "/api/v1/gold-sale-orders",
        json=body,
        headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
    )


def order_version(world: dict[str, Any], order_id: str) -> int:
    return int(
        rows(world, "SELECT record_version FROM gold_sale_orders WHERE id = %s", order_id)[0][0]
    )


def submit(world: dict[str, Any], order_id: str, **overrides: Any) -> Any:
    client = world["client"]
    version = overrides.get("version") or order_version(world, order_id)
    return client.post(
        f"/api/v1/gold-sale-orders/{order_id}/submit",
        json={},
        headers={
            **csrf(world),
            "If-Match": f'"rv-{version}"',
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )


def price(world: dict[str, Any], order_id: str, **overrides: Any) -> Any:
    client = world["client"]
    body: dict[str, Any] = {"unit_price_irr": UNIT_PRICE}
    body.update({k: v for k, v in overrides.items() if k != "version"})
    version = overrides.get("version") or order_version(world, order_id)
    return client.post(
        f"/api/v1/gold-sale-orders/{order_id}/pricing-versions",
        json=body,
        headers={
            **csrf(world),
            "If-Match": f'"rv-{version}"',
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )


def a_submitted_order(world: dict[str, Any]) -> str:
    sign_in_trader(world, OWNER_PHONE)
    created = create_order(world)
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]
    assert submit(world, order_id).status_code == 200
    return str(order_id)


def versions_of(world: dict[str, Any], order_id: str) -> list[tuple[Any, ...]]:
    return rows(
        world,
        "SELECT version_number, unit_price_irr, expected_amount_irr, content_hash, superseded_at "
        "FROM gold_sale_pricing_versions WHERE gold_sale_order_id = %s ORDER BY version_number",
        order_id,
    )


def test_a_trader_places_an_order_with_a_weight_and_no_price(world: dict[str, Any]) -> None:
    """§21.1. What a trader orders is a mass; what it costs is the centre's."""

    sign_in_trader(world, OWNER_PHONE)
    response = create_order(world)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["status"] == "draft"
    assert body["expected_amount_irr"] is None
    assert body["current_pricing_version_id"] is None
    assert body["order_number"].startswith("GS-")
    assert Decimal(body["gold_weight"]) == Decimal(WEIGHT)


def test_the_weight_survives_the_round_trip_exactly(world: dict[str, Any]) -> None:
    """`gold_weight` is the first non-integer quantity this system stores.

    JSON string to `Decimal` to `NUMERIC(20, 6)` and back. Compared with `Decimal`, not `float`:
    a float comparison would pass for a value that had already lost precision, which is the whole
    reason `app/core/hashing.py` refuses floats.
    """

    sign_in_trader(world, OWNER_PHONE)
    awkward = "0.000001"
    response = create_order(world, gold_weight=awkward)
    assert response.status_code == 201, response.text

    stored = rows(
        world,
        "SELECT gold_weight FROM gold_sale_orders WHERE id = %s",
        response.json()["id"],
    )[0][0]
    assert stored == Decimal(awkward), f"{stored} is not {awkward}"


def test_an_unapproved_weight_unit_is_refused(world: dict[str, Any]) -> None:
    """`04_Database_Schema.md:180` names `GRAM` and `MITHQAL`.

    **`KILOGRAM` is the value this implementation first invented**, and it is the one this test
    uses, so the refusal is exercised against the mistake that was actually made rather than
    against a nonsense string.
    """

    sign_in_trader(world, OWNER_PHONE)
    response = create_order(world, weight_unit="KILOGRAM")
    assert response.status_code in {400, 422}, response.text


def test_mithqal_is_accepted(world: dict[str, Any]) -> None:
    """The other half: the unit gold is actually quoted in inside Iran.

    Without this, the previous test would pass against an implementation that accepted only
    `GRAM` — the list would be narrower than the document and nothing would say so.
    """

    sign_in_trader(world, OWNER_PHONE)
    response = create_order(world, weight_unit="MITHQAL")
    assert response.status_code == 201, response.text
    assert response.json()["weight_unit"] == "MITHQAL"


def test_pricing_computes_the_amount_rather_than_accepting_one(
    world: dict[str, Any],
) -> None:
    """`SVC-PRICING-002`. There is no amount field, so there is nothing to disagree with.

    The expected amount is the unit price times the weight, quantised once. Asserted against the
    arithmetic rather than against a constant, so a changed weight in the fixture cannot silently
    make the assertion meaningless.
    """

    order_id = a_submitted_order(world)
    sign_in_admin(world, "gold_accountant")

    response = price(world, order_id)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["version_number"] == 1
    assert body["expected_amount_irr"] == int(Decimal(WEIGHT) * Decimal(UNIT_PRICE))
    assert len(body["content_hash"]) == 64

    order = rows(
        world,
        "SELECT expected_amount_irr, current_pricing_version_id, status "
        "FROM gold_sale_orders WHERE id = %s",
        order_id,
    )[0]
    assert order[0] == body["expected_amount_irr"]
    assert str(order[1]) == body["id"]
    assert order[2] == "priced"


def test_the_amount_is_computed_in_decimal_and_not_through_a_float(
    world: dict[str, Any],
) -> None:
    """`SVC-PRICING-002`, with inputs a float actually gets wrong.

    **This test exists because a negative control went uncaught.** The control replaced the
    `Decimal` multiplication with a float one and nothing failed — the main fixture prices
    `125.500000` grams, and `125.5` is exactly representable in binary floating point, so both
    routes give the same answer. The assertion could not have failed however the arithmetic was
    written: insensitive by construction, which is the fourth meaning of NOT CAUGHT.

    `0.29 times 100` is the discriminator. In `Decimal` it is exactly `29`; as a float it is
    `28.999999999999996`, and truncation makes that **28** — a rial the trader was quoted and
    would not have been charged.
    """

    sign_in_trader(world, OWNER_PHONE)
    created = create_order(world, gold_weight="0.290000")
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]
    assert submit(world, order_id).status_code == 200

    sign_in_admin(world, "gold_accountant")
    response = price(world, order_id, unit_price_irr=100)
    assert response.status_code == 201, response.text
    assert response.json()["expected_amount_irr"] == 29, (
        "0.29 times 100 came out as something other than 29, which is what binary floating "
        "point does to it. `app/core/hashing.py` refuses floats for this reason and the "
        "arithmetic must not reintroduce one."
    )


def test_the_pricing_body_accepts_no_amount(world: dict[str, Any]) -> None:
    """The absence, asserted at the boundary. `extra="forbid"` turns it into a 422."""

    order_id = a_submitted_order(world)
    sign_in_admin(world, "gold_accountant")

    response = price(world, order_id, expected_amount_irr=1)
    assert response.status_code == 422, response.text


def test_re_pricing_creates_a_version_and_supersedes_the_old_one(
    world: dict[str, Any],
) -> None:
    """`SVC-PRICING-001`. §10.2 at `:731`, both halves in one transaction.

    Version 1 is read back column by column: only `superseded_at` may have moved. That is enforced
    a level below this test — the migration grants `superseded_at` alone on the pricing table — so
    the assertion is about a property the database holds rather than one the command remembers.
    """

    order_id = a_submitted_order(world)
    sign_in_admin(world, "gold_accountant")
    assert price(world, order_id).status_code == 201

    before = rows(
        world,
        "SELECT row_to_json(t) FROM (SELECT * FROM gold_sale_pricing_versions "
        "WHERE gold_sale_order_id = %s AND version_number = 1) t",
        order_id,
    )[0][0]

    second = price(world, order_id, unit_price_irr=UNIT_PRICE + 1_000_000)
    assert second.status_code == 201, second.text
    assert second.json()["version_number"] == 2

    after = rows(
        world,
        "SELECT row_to_json(t) FROM (SELECT * FROM gold_sale_pricing_versions "
        "WHERE gold_sale_order_id = %s AND version_number = 1) t",
        order_id,
    )[0][0]

    changed = {key for key in before if before[key] != after.get(key)}
    assert changed == {"superseded_at"}, (
        f"version 1 changed in {sorted(changed)}. §10.2 calls it an immutable snapshot; only "
        "being superseded may happen to it."
    )
    assert after["superseded_at"] is not None

    order = rows(
        world,
        "SELECT current_pricing_version_id FROM gold_sale_orders WHERE id = %s",
        order_id,
    )[0][0]
    assert str(order) == second.json()["id"], "the order still points at the old version"


def test_re_pricing_at_identical_figures_is_refused(world: dict[str, Any]) -> None:
    """`DB-GOLDSALE-001`. `UNIQUE(gold_sale_order_id, content_hash)`, and M5's argument.

    An accountant who re-prices without changing anything has not re-priced, and a second identical
    row would reach a reviewer looking like new work.
    """

    order_id = a_submitted_order(world)
    sign_in_admin(world, "gold_accountant")
    assert price(world, order_id).status_code == 201

    again = price(world, order_id)
    assert again.status_code == 409, again.text
    assert "identical" in again.text or "re-pricing" in again.text
    assert len(versions_of(world, order_id)) == 1


def test_a_draft_cannot_be_priced(world: dict[str, Any]) -> None:
    """Nobody has handed the order to the centre yet."""

    sign_in_trader(world, OWNER_PHONE)
    created = create_order(world)
    assert created.status_code == 201
    order_id = created.json()["id"]

    sign_in_admin(world, "gold_accountant")
    response = price(world, order_id)
    assert response.status_code == 400, response.text
    assert "draft" in response.text


def test_a_manager_cannot_price_an_order(world: dict[str, Any]) -> None:
    """`20260801_0008:309` gives the manager `gold_sale.read` and not `.price`.

    The sharp negative: a manager holds a gold-sale grant, so a guard asking for "some gold-sale
    permission" would let this through.
    """

    order_id = a_submitted_order(world)
    sign_in_admin(world, "gold_manager")

    response = price(world, order_id)
    assert response.status_code == 403, response.text
    assert versions_of(world, order_id) == []


def test_another_trader_cannot_see_or_submit_the_order(world: dict[str, Any]) -> None:
    """A second trader gets 404, not 403, on every route that names an order.

    An authorisation error over a guessable identifier confirms the order exists, which is the
    enumeration oracle `app/security/ownership.py` exists to prevent.
    """

    sign_in_trader(world, OWNER_PHONE)
    created = create_order(world)
    order_id = created.json()["id"]

    sign_in_trader(world, OTHER_PHONE)
    assert world["client"].get(f"/api/v1/gold-sale-orders/{order_id}").status_code == 404
    assert submit(world, order_id).status_code == 404


def test_a_traders_list_holds_only_their_own_orders(world: dict[str, Any]) -> None:
    """§21.1's "scoped list", through `scoped()` rather than a hand-written predicate."""

    sign_in_trader(world, OWNER_PHONE)
    mine = create_order(world).json()["id"]

    sign_in_trader(world, OTHER_PHONE)
    theirs = create_order(world).json()["id"]
    listed = {row["id"] for row in world["client"].get("/api/v1/gold-sale-orders").json()}

    assert theirs in listed
    assert mine not in listed, "one trader's list contained another trader's order"


def test_an_accountant_sees_every_order(world: dict[str, Any]) -> None:
    """The other half of the dual guard: an internal caller is not scoped by ownership."""

    sign_in_trader(world, OWNER_PHONE)
    mine = create_order(world).json()["id"]

    sign_in_admin(world, "gold_accountant")
    listed = {row["id"] for row in world["client"].get("/api/v1/gold-sale-orders").json()}
    assert mine in listed


def test_creating_replays_rather_than_placing_two_orders(world: dict[str, Any]) -> None:
    """A retried POST — the network dropped the response — returns the order that exists."""

    sign_in_trader(world, OWNER_PHONE)
    client = world["client"]
    key = str(uuid.uuid4())
    body = {
        "gold_type": "bullion",
        "gold_weight": WEIGHT,
        "weight_unit": "GRAM",
        "gold_purity": "18K",
    }
    headers = {**csrf(world), "Idempotency-Key": key}

    first = client.post("/api/v1/gold-sale-orders", json=body, headers=headers)
    assert first.status_code == 201, first.text
    second = client.post("/api/v1/gold-sale-orders", json=body, headers=headers)
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]


def test_a_stale_if_match_refuses_a_submission(world: dict[str, Any]) -> None:
    sign_in_trader(world, OWNER_PHONE)
    order_id = create_order(world).json()["id"]

    stale = order_version(world, order_id)
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE gold_sale_orders SET record_version = record_version + 1 WHERE id = %s",
            (order_id,),
        )
        connection.commit()

    assert submit(world, order_id, version=stale).status_code == 412


def test_the_three_actions_are_audited(world: dict[str, Any]) -> None:
    """All three names are declared rather than catalogued — the M10 plan's G-3.

    Asserted here so the declarations are exercised: a `catalogued=False` entry nothing writes is
    a reason recorded for a name nobody uses.
    """

    order_id = a_submitted_order(world)
    sign_in_admin(world, "gold_accountant")
    assert price(world, order_id).status_code == 201

    actions = {
        row[0]
        for row in rows(
            world, "SELECT action FROM audit_logs WHERE entity_id = %s", order_id
        )
    }
    assert {"gold_sale.created", "gold_sale.submitted", "gold_sale.priced"} <= actions, actions

    events = rows(
        world, "SELECT event_type FROM outbox_events WHERE aggregate_id = %s", order_id
    )
    assert events == [], (
        f"a gold-sale command enqueued {events}. `audit_outbox_catalog.yaml` lists no gold-sale "
        "event at all, and telling the trader a price is slice 8's notification wiring."
    )
