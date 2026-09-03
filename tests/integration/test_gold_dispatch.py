"""Gold moves, and only when it may. M10 slice 7.

Against a real PostgreSQL. `05_API_Specification.md` §21.7, `04_Database_Schema.md` §10.8,
`06_Workflows_and_State_Machines.md` §12, `15_Agent_Implementation_Plan.md:1236`.

**The guard is the sentence the milestone was built toward:** "Gold cannot be dispatched unless the
approved payment/settlement condition is satisfied or an explicitly authorized override is recorded
with reason and audit."

Two properties carry the slice. **A warehouse operator can record a dispatch and cannot authorise
an override** — which holds because of who the seed grants what, not because of a branch. And
**four dispatch types exist, two of which move no metal**; a test that treated them alike would
pass against an implementation that dispatched gold for an offset.

Covers: SEC-DISPATCH-001, SVC-DISPATCH-001, SVC-SETTLEMENT-001.
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
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"
TRADER_CSRF_COOKIE = "__Host-gp_trader_csrf"

TRADER_PHONE = "+989120019001"
PRICED = 50_000_000_000


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
        local_storage_root=tmp_path_factory.mktemp("dispatch-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="x" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)
    trader_id = uuid.uuid4()

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'Dispatch Trader', %s, 'active', 'approved')",
            (trader_id, TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Buyer', %s, 'active', TRUE)",
            (trader_id, TRADER_PHONE, encoded),
        )
        # Three internal actors, one per authority. The warehouse operator is the subject of
        # `SEC-DISPATCH-001`; the manager holds the override on the owner's 2026-09-03 decision.
        for username, role in (
            ("dispatch_warehouse", "warehouse_operator"),
            ("dispatch_manager", "manager"),
            ("dispatch_accountant", "accountant"),
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
            # The runtime role, not the owner. A control granting `dispatch_type` went NOT CAUGHT
            # because the privilege query asked about `current_user`, which is the owner this
            # module connects as and which holds every privilege — so the assertion was true of a
            # role nobody runs the application under.
            "app_role": migrated.app_role,
            "runtime": app.state.runtime,
            "trader_id": trader_id,
        }
    app.state.runtime.close()


def names_are_read(names: list[str]) -> bool:
    """Guard the guard: an empty privilege list makes every `not in` assertion true."""

    return len(names) > 0


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


def an_order(
    world: dict[str, Any],
    *,
    paid: int,
    status: str = "incoming_payment_confirmed",
    claimed: int | None = None,
) -> str:
    """An order priced at `PRICED` with `paid` rials confirmed against it.

    The confirmed sum is written as a receipt rather than as a column, because there is no column:
    the guard reads `sum(confirmed_amount_irr)` and a fixture that set a total directly would be
    testing a different function.

    **`claimed` defaults to `paid` and every guard test that matters overrides it.** A control
    swapping the guard's `confirmed_amount_irr` for `amount_irr` went NOT CAUGHT because the two
    were always equal here — the fourth meaning of NOT CAUGHT, a fixture that made the test unable
    to fail. A trader claiming more than the centre confirmed is the attack the guard exists for.
    """

    order_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO gold_sale_orders (id, trader_id, order_number, status, gold_type, "
            "gold_weight, weight_unit, gold_purity, expected_amount_irr, created_by_actor_type, "
            "record_version) VALUES (%s, %s, %s, %s, 'bullion', 10.000000, 'GRAM', '18K', %s, "
            "'trader_user', 1)",
            (order_id, world["trader_id"], f"GS-{str(order_id)[:8]}", status, PRICED),
        )
        if paid:
            connection.execute(
                "INSERT INTO incoming_payment_receipts (id, gold_sale_order_id, trader_id, "
                "amount_irr, confirmed_amount_irr, confirmed_at, confirmed_by_admin_user_id, "
                "status, record_version) SELECT %s, %s, %s, %s, %s, now(), u.id, 'confirmed', 1 "
                "FROM admin_users u WHERE u.username = 'dispatch_accountant'",
                (uuid.uuid4(), order_id, world["trader_id"], claimed or paid, paid),
            )
        elif claimed:
            # A claim nobody confirmed. This is the row that makes the guard's choice of column
            # observable: reading `amount_irr` releases the gold, reading `confirmed_amount_irr`
            # refuses.
            connection.execute(
                "INSERT INTO incoming_payment_receipts (id, gold_sale_order_id, trader_id, "
                "amount_irr, status, record_version) VALUES (%s, %s, %s, %s, 'submitted', 1)",
                (uuid.uuid4(), order_id, world["trader_id"], claimed),
            )
        connection.commit()
    return str(order_id)


def dispatch(
    world: dict[str, Any],
    order_id: str,
    *,
    dispatch_type: str = "physical_dispatch",
    version: int = 1,
    reason: str | None = None,
    weight: str | None = "10.000000",
) -> Any:
    body: dict[str, Any] = {"dispatch_type": dispatch_type}
    if weight is not None:
        body["gold_weight"] = weight
        body["weight_unit"] = "GRAM"
    if reason is not None:
        body["guard_override_reason"] = reason
    return world["client"].post(
        f"/api/v1/gold-sale-orders/{order_id}/dispatches",
        json=body,
        headers={
            **csrf(world),
            "Idempotency-Key": str(uuid.uuid4()),
            "If-Match": f'"rv-{version}"',
        },
    )


def stored(world: dict[str, Any], dispatch_id: str) -> tuple[Any, ...]:
    return rows(
        world,
        "SELECT dispatch_type, status, dispatched_at, guard_override_at, "
        "guard_override_reason, guard_override_by_admin_user_id, weight "
        "FROM gold_dispatches WHERE id = %s",
        dispatch_id,
    )[0]


# --- SVC-DISPATCH-001 --------------------------------------------------------


def test_a_paid_order_dispatches_without_an_override(world: dict[str, Any]) -> None:
    """`SVC-DISPATCH-001`, the branch where the guard passes.

    No override columns are set, and that matters as much as the dispatch succeeding: a row that
    recorded an override on the happy path would make the overridden ones unfindable.
    """

    sign_in(world, "dispatch_warehouse")
    order_id = an_order(world, paid=PRICED)

    response = dispatch(world, order_id)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["status"] == "dispatched"
    assert body["confirmed_total_irr"] == PRICED
    assert body["guard_override_at"] is None

    record = stored(world, body["id"])
    assert record[3] is None and record[4] is None and record[5] is None, (
        "a dispatch that passed the guard recorded an override"
    )
    assert rows(world, "SELECT status FROM gold_sale_orders WHERE id = %s", order_id)[0][0] == (
        "dispatched"
    )


def test_an_unpaid_order_is_refused(world: dict[str, Any]) -> None:
    """`SVC-DISPATCH-001`. §18 `:1236`: gold cannot be dispatched unless the condition is satisfied.

    A partially paid order is the realistic case — half the money arrived and somebody is under
    pressure to release the metal — and it is refused exactly like an unpaid one.
    """

    sign_in(world, "dispatch_warehouse")

    # The third case is the one a control found missing: the trader *claims* the full amount and
    # the centre has confirmed none of it. A guard reading `amount_irr` would release the gold on
    # the trader's own word, which is what slice 2 exists to make impossible.
    for paid, claimed in ((0, None), (PRICED // 2, None), (0, PRICED)):
        order_id = an_order(world, paid=paid, claimed=claimed)
        response = dispatch(world, order_id)
        assert response.status_code == 403, (
            f"an order with {paid} of {PRICED} confirmed (claimed {claimed}) answered "
            f"{response.status_code}: {response.text}"
        )
        assert rows(
            world, "SELECT count(*) FROM gold_dispatches WHERE gold_sale_order_id = %s", order_id
        )[0][0] == 0, "a refused dispatch left a row behind"


def test_a_manager_may_override_with_a_reason(world: dict[str, Any]) -> None:
    """`SVC-DISPATCH-001`, the other branch. The owner's decision of 2026-09-03.

    The override is recorded on the row — who, when and why — because §18 `:1236` asks for it to be
    "recorded with reason and audit", which is two places. Reading the dispatch is how an operator
    answers "was this gold released against confirmed money", and that must not require a log
    search.
    """

    sign_in(world, "dispatch_manager")
    order_id = an_order(world, paid=0)

    response = dispatch(world, order_id, reason="trader delivered cash to the branch in person")
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["guard_override_at"] is not None
    assert "cash to the branch" in body["guard_override_reason"]
    assert body["confirmed_total_irr"] == 0

    record = stored(world, body["id"])
    assert record[5] is not None, "an override recorded no authorising actor"

    entry = rows(
        world,
        "SELECT action, new_values, reason FROM audit_logs WHERE entity_id = %s "
        "ORDER BY occurred_at DESC LIMIT 1",
        body["id"],
    )[0]
    assert entry[0] == "gold_sale.dispatched"
    assert entry[1]["payment_guard_passed"] is False, (
        "the audit entry does not say the guard was bypassed. A reader asking whether this gold "
        "was released against confirmed money must get a yes or a no without reasoning about "
        "which nullable columns are set."
    )
    assert "cash to the branch" in entry[2]


def test_an_override_without_a_reason_is_refused(world: dict[str, Any]) -> None:
    """§18 `:1236`: "recorded with reason". A blank one records two of the three facts.

    Whitespace as well as empty, because the table's CHECK uses `btrim` and a reason of three
    spaces would otherwise satisfy a `min_length`.
    """

    sign_in(world, "dispatch_manager")

    for reason in (None, "", "   "):
        order_id = an_order(world, paid=0)
        response = dispatch(world, order_id, reason=reason)
        assert response.status_code == 400, (
            f"an override with reason {reason!r} answered {response.status_code}: {response.text}"
        )


# --- SEC-DISPATCH-001 --------------------------------------------------------


def test_a_warehouse_operator_cannot_override_the_guard(world: dict[str, Any]) -> None:
    """`SEC-DISPATCH-001`, and the plan calls it the sharp negative: somebody who may **record** a
    dispatch and may not **authorise an override**.

    **This holds because of the seed, not because of a branch.** `permission_catalog.yaml` grants
    `gold_sale.dispatch` to `warehouse_operator` alone, and its `dispatch_control` constraint reads
    "warehouse cannot override financial verification"; `20260911_0042` seeds
    `gold_sale.dispatch_override` for the manager. Deleting the check in the command would not make
    this pass — the permission simply is not in the operator's set.

    A trader is checked in the same test for the same reason `test_no_trader_can_reach_the_matching
    _surface` checks every route at once: a surface where one caller is denied and another is not
    is a surface nobody has finished checking.
    """

    order_id = an_order(world, paid=0)

    sign_in(world, "dispatch_warehouse")
    refused = dispatch(world, order_id, reason="I decided it was fine")
    assert refused.status_code == 403, (
        f"a warehouse operator overrode the payment guard, answering {refused.status_code}. The "
        "catalogue's dispatch_control constraint says warehouse cannot override financial "
        "verification."
    )

    sign_in_trader(world)
    trader = dispatch(world, order_id)
    assert trader.status_code == 403, (
        f"a trader reached the dispatch surface, answering {trader.status_code}"
    )

    assert rows(
        world, "SELECT count(*) FROM gold_dispatches WHERE gold_sale_order_id = %s", order_id
    )[0][0] == 0


def test_the_override_permission_is_the_managers_alone(world: dict[str, Any]) -> None:
    """The seed itself, read from the database.

    A behavioural test proves the warehouse operator is refused *today*. This proves why: exactly
    one role holds the permission. A later migration granting it more widely — to
    `business_admin`, say, which `20260828_0027` explicitly refused for the batch cancellation —
    would fail here rather than in a review nobody scheduled.
    """

    granted = rows(
        world,
        "SELECT r.code FROM role_permissions rp "
        "JOIN roles r ON r.id = rp.role_id "
        "JOIN permissions p ON p.id = rp.permission_id "
        "WHERE p.code = 'gold_sale.dispatch_override' ORDER BY r.code",
    )
    assert [row[0] for row in granted] == ["manager"], (
        f"gold_sale.dispatch_override is held by {[row[0] for row in granted]}. The owner's "
        "2026-09-03 decision names the manager, and widening it is a decision rather than a "
        "migration detail."
    )


# --- SVC-SETTLEMENT-001 ------------------------------------------------------


def test_an_offset_settlement_moves_no_metal(world: dict[str, Any]) -> None:
    """`SVC-SETTLEMENT-001`. §18 `:1240`: "offset settlement is distinct from physical receipt".

    Four types exist and two of them move no gold. The distinction is visible in three places at
    once — the dispatch's status, its `dispatched_at`, and the order's status — and a test checking
    only that the row was created would pass against an implementation that dispatched metal for an
    offset.
    """

    sign_in(world, "dispatch_warehouse")

    physical = an_order(world, paid=PRICED)
    settlement = an_order(world, paid=PRICED)

    moved = dispatch(world, physical, dispatch_type="physical_dispatch")
    offset = dispatch(world, settlement, dispatch_type="offset_settlement", weight=None)
    assert moved.status_code == 201, moved.text
    assert offset.status_code == 201, offset.text

    assert moved.json()["status"] == "dispatched"
    assert offset.json()["status"] == "settled", (
        f"an offset settlement is {offset.json()['status']!r}. `settled` and `dispatched` are two "
        "of document 06 §12.2's six states and they mean different things happened."
    )

    assert stored(world, moved.json()["id"])[2] is not None
    assert stored(world, offset.json()["id"])[2] is None, (
        "an offset settlement recorded a dispatched_at. Nothing left the building, so there is no "
        "moment of leaving to record."
    )

    assert moved.json()["order_status"] == "dispatched"
    assert offset.json()["order_status"] == "settled_or_offset", (
        f"an offset left the order {offset.json()['order_status']!r}; `status_catalog.yaml` has "
        "`settled_or_offset` for exactly this and `dispatched` for the other."
    )


def test_all_four_types_are_accepted_and_split_two_and_two(world: dict[str, Any]) -> None:
    """§10.8's four, and the split is asserted rather than assumed.

    `physical_receipt` is the one worth naming: it is a *physical* type even though the metal is
    arriving rather than leaving, so a split derived from the word "dispatch" would classify it
    wrongly. The model names the two tuples explicitly for that reason.
    """

    sign_in(world, "dispatch_warehouse")
    outcomes = {}
    for kind in (
        "physical_dispatch",
        "physical_receipt",
        "offset_settlement",
        "manual_settlement",
    ):
        order_id = an_order(world, paid=PRICED)
        response = dispatch(
            world,
            order_id,
            dispatch_type=kind,
            weight="10.000000" if kind.startswith("physical") else None,
        )
        assert response.status_code == 201, f"{kind}: {response.text}"
        outcomes[kind] = response.json()["status"]

    assert outcomes == {
        "physical_dispatch": "dispatched",
        "physical_receipt": "dispatched",
        "offset_settlement": "settled",
        "manual_settlement": "settled",
    }, f"the four types produced {outcomes}"


def test_an_unknown_dispatch_type_is_refused(world: dict[str, Any]) -> None:
    """§10.8 names four. A fifth would be a business decision arriving through a request body."""

    sign_in(world, "dispatch_warehouse")
    order_id = an_order(world, paid=PRICED)

    response = dispatch(world, order_id, dispatch_type="courier_handoff")
    assert response.status_code == 400, response.text
    assert "not a dispatch type" in response.text


# --- Document 06 §12.3 -------------------------------------------------------


def test_the_runtime_cannot_convert_a_dispatch_into_a_settlement(world: dict[str, Any]) -> None:
    """Document 06 §12.3: "A physical dispatch cannot be converted **silently** into offset
    settlement; create a replacement/superseding settlement record."

    Enforced by absence: `dispatch_type` carries no UPDATE grant, so the conversion is not
    something a later branch can be talked into. No behavioural test can see this — no command
    updates the column — which is why it is read from `information_schema`.
    """

    granted = rows(
        world,
        "SELECT DISTINCT column_name FROM information_schema.column_privileges "
        "WHERE table_name = 'gold_dispatches' AND privilege_type = 'UPDATE' "
        "AND grantee = %s ORDER BY column_name",
        world["app_role"],
    )
    assert names_are_read(names := [row[0] for row in granted]), (
        "the privilege query returned nothing, so every assertion below is true of an empty set. "
        "A control granting dispatch_type went NOT CAUGHT for exactly this reason."
    )
    assert "dispatch_type" not in names, (
        f"the runtime may update dispatch_type: {names}. §12.3 forbids converting a physical "
        "dispatch silently into a settlement, and a grant is what makes it possible at all."
    )
    for frozen in ("weight", "weight_unit", "guard_override_reason", "guard_override_at"):
        assert frozen not in names, (
            f"{frozen} is writable after the fact. An override or a weight that could be added or "
            "edited later would let a dispatch be relabelled once nobody is watching."
        )


def test_the_route_itself_refuses_an_accountant_on_a_paid_order(world: dict[str, Any]) -> None:
    """The route guard, isolated. `SEC-DISPATCH-001`'s other half.

    **Written twice, because the first version was still not isolating it.** A control replacing
    the guard's body went NOT CAUGHT; the fix was a fully paid order so the command's own guard
    would not refuse first; and it went NOT CAUGHT *again* — because the caller was a trader, and
    a trader is refused by the audience split before any route guard runs. This platform separates
    audiences by host, so no trader request ever reaches an `admin.localhost` route and a
    trader-based test cannot exercise a route's permission check at all.

    The accountant is the caller that isolates it: a legitimate internal user who holds neither
    `gold_sale.dispatch` nor `gold_sale.dispatch_override`, on an order whose payment guard passes.
    With the route guard removed the dispatch succeeds; with it, 403. Nothing else in the stack has
    an opinion.

    The third meaning of NOT CAUGHT twice over — defence in depth hiding which layer is actually
    load-bearing.
    """

    order_id = an_order(world, paid=PRICED)

    sign_in(world, "dispatch_accountant")
    response = dispatch(world, order_id)
    assert response.status_code == 403, (
        f"an accountant dispatched a paid order, answering {response.status_code}. The command "
        "would allow it — the payment guard passes — so the route is the only thing that can say "
        "no, and the accountant holds neither dispatch permission."
    )
    assert rows(
        world, "SELECT count(*) FROM gold_dispatches WHERE gold_sale_order_id = %s", order_id
    )[0][0] == 0


def test_a_stale_if_match_is_refused(world: dict[str, Any]) -> None:
    """Two operators dispatching one order. The second must be told."""

    sign_in(world, "dispatch_warehouse")
    order_id = an_order(world, paid=PRICED)

    response = dispatch(world, order_id, version=99)
    assert response.status_code in {409, 412}, response.text
