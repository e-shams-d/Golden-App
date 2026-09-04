"""The queue contract, asserted against a real database. M11 slice 2.

`15_Agent_Implementation_Plan.md:1256` (§19), and the plan's **G-1**.

§19.2 names twenty-four queues; document 05 defines a route for none of them. So this file is not
testing an approved contract — it is testing **the one this slice decided**, which is why the
decision is asserted here rather than only described in a docstring. If the owner reverses G-1, the
failures name the paths.

**§19 `:1298`'s six rules get six assertions, not one.** A single "the queue paginates" test passes
against an implementation missing four of them. The rules are: cursor pagination, stable ordering,
allowlisted filters, allowlisted sorting, permission-aware counts, and no unbounded read.

**The ordering test seeds rows that share a timestamp.** A stable-ordering assertion over rows a
second apart passes against a sort with no tiebreak at all, because every page boundary lands
somewhere unambiguous. Ties are the only condition under which instability is observable, and a
work queue — where a trader submits several requests in one sitting — is where ties actually occur.

Covers: API-QUEUE-001, SEC-QUEUE-001.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery-staple"
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"
TRADER_CSRF_COOKIE = "__Host-gp_trader_csrf"

TRADER_PHONE = "+989120041001"
OTHER_PHONE = "+989120041002"
# `IR` plus twenty-four digits, which is what `ck_beneficiaries_normalized_iban_shape` enforces.
IBANS = {
    "trader": "IR060120000000000000000101",
    "other": "IR060120000000000000000102",
}
ACCOUNTANT = "queue_accountant"
# `permission_catalog.yaml:444` gives `payment_request.read` to four roles. The warehouse operator
# holds none of them, which makes it the honest "authenticated but ungranted" admin for the
# permission negative — a role that exists rather than one invented for the test.
UNGRANTED_ADMIN = "queue_warehouse"

QUEUE = "/api/v1/queues/new-requests"

SUBMITTED = "submitted_to_center"
# The adjacent state, and the whole reason the queue is asserted as an exclusion rather than only
# as an inclusion. A request somebody is already reviewing is not new; a queue that returns it hands
# two people the same work. Slice 3 owes this same shape for the accountant's other ten.
UNDER_REVIEW = "under_accountant_review"


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
        local_storage_root=tmp_path_factory.mktemp("queue-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="y" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    ids: dict[str, uuid.UUID] = {}

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        for key, phone, name in (
            ("trader", TRADER_PHONE, "First Business"),
            ("other", OTHER_PHONE, "Second Business"),
        ):
            trader_id = uuid.uuid4()
            connection.execute(
                "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
                "approval_status) VALUES (%s, %s, %s, 'active', 'approved')",
                (trader_id, name, phone),
            )
            connection.execute(
                "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
                "status, is_primary) VALUES (%s, %s, %s, %s, 'active', TRUE)",
                (trader_id, phone, name, encoded),
            )
            ids[key] = trader_id

            # `payment_requests.beneficiary_id` is NOT NULL — a request is always *to* somebody.
            # One per trader, because a beneficiary belongs to the business that entered it.
            beneficiary_id = uuid.uuid4()
            # `ck_beneficiaries_normalized_iban_shape` wants `IR` and twenty-four digits. A
            # generated one with a letter in it fails the CHECK, which is the constraint doing its
            # job — so these are written out rather than derived from the fixture key.
            iban = IBANS[key]
            connection.execute(
                "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
                "status, verification_status) VALUES (%s, %s, %s, %s, %s, 'active', "
                "'not_checked')",
                (beneficiary_id, trader_id, f"{name} Payee", iban, iban),
            )
            ids[f"{key}_beneficiary"] = beneficiary_id

        for username, role in ((ACCOUNTANT, "accountant"), (UNGRANTED_ADMIN, "warehouse_operator")):
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
            "runtime": app.state.runtime,
            "owner_url": migrated.owner_url,
            **{f"{name}_id": value for name, value in ids.items()},
        }
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(autouse=True)
def an_empty_queue(world: dict[str, Any]) -> Iterator[None]:
    """The database is module-scoped, so a count assertion counts earlier tests without this."""

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute("DELETE FROM payment_requests")
        connection.commit()
    yield


def request_row(
    world: dict[str, Any],
    *,
    status: str = SUBMITTED,
    trader: str = "trader",
    created_at: datetime | None = None,
    number: str | None = None,
) -> uuid.UUID:
    """One payment request, written directly.

    Seeded rather than walked through M5's commands on purpose: this file tests the *queue* — who
    may read it, how it pages, what it excludes — and driving eight commands per row would test M5
    a second time while making the tie-breaking and pagination cases impractical to construct.
    `tests/integration/test_payment_requests.py` owns the lifecycle.
    """

    request_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO payment_requests (id, trader_id, beneficiary_id, request_number, "
            "status, created_at) VALUES (%s, %s, %s, %s, %s, COALESCE(%s, now()))",
            (
                request_id,
                world[f"{trader}_id"],
                world[f"{trader}_beneficiary_id"],
                number or f"PR-{uuid.uuid4().hex[:10]}",
                status,
                created_at,
            ),
        )
        connection.commit()
    return request_id


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


# --- SEC-QUEUE-001: who may read it, and what the allowlist does with an unknown key -------


def test_no_trader_can_reach_an_internal_queue(world: dict[str, Any]) -> None:
    """The ownership question, answered where `test_ownership_scope.py`'s exemption says it is.

    That exemption argues the queue needs no `scoped()` call because no trader can reach it. This
    is the assertion the argument rests on; without it the exemption is a claim about a grant
    nobody checked.
    """

    request_row(world)
    sign_in_trader(world)

    response = world["client"].get(QUEUE)
    assert response.status_code == 403, response.text


def test_an_admin_without_the_grant_is_refused(world: dict[str, Any]) -> None:
    """Authenticated is not authorised. A warehouse operator holds no `payment_request.read`."""

    request_row(world)
    sign_in(world, UNGRANTED_ADMIN)

    response = world["client"].get(QUEUE)
    assert response.status_code == 403, response.text


def test_an_unauthenticated_caller_is_refused(world: dict[str, Any]) -> None:
    request_row(world)
    world["client"].cookies.clear()

    assert world["client"].get(QUEUE).status_code == 401


def test_a_sort_key_that_is_not_allowlisted_is_refused(world: dict[str, Any]) -> None:
    """SEC-QUEUE-001. Refused, not ignored — and `status` is chosen to make that sharp.

    `status` is a real column of `payment_requests`, so a 400 here is the allowlist doing its job
    rather than the name failing to resolve. An implementation that ignored it would return the
    default ordering and a 200, which looks identical to success from the caller's side.
    """

    request_row(world)
    sign_in(world, ACCOUNTANT)

    response = world["client"].get(QUEUE, params={"sort": "status"})
    assert response.status_code == 400, response.text


def test_a_filter_that_is_not_allowlisted_is_not_silently_applied(world: dict[str, Any]) -> None:
    """The queue's defining status is deliberately not a filter.

    `/queues/new-requests?status=paid` must not be a way to reach a different queue through the
    wrong name. FastAPI does not bind an undeclared query parameter, so the guarantee is that the
    parameter changes nothing — asserted by comparing against the unfiltered page rather than by a
    status code, because "ignored" and "refused" are both acceptable answers here and "applied" is
    not.
    """

    request_row(world)
    request_row(world, status=UNDER_REVIEW)
    sign_in(world, ACCOUNTANT)

    plain = world["client"].get(QUEUE)
    smuggled = world["client"].get(QUEUE, params={"status": UNDER_REVIEW})
    assert plain.status_code == 200, plain.text
    assert smuggled.status_code in (200, 400), smuggled.text
    if smuggled.status_code == 200:
        assert smuggled.json()["items"] == plain.json()["items"]
        assert [item["status"] for item in smuggled.json()["items"]] == [SUBMITTED]


# --- API-QUEUE-001: §19 :1298's six rules, one assertion each ------------------------------


def test_the_contract_refuses_a_filter_the_queue_does_not_allowlist(
    world: dict[str, Any],
) -> None:
    """`read_queue_page`'s allowlist check, asserted where it can actually be reached.

    **This test exists because a negative control went NOT CAUGHT.** Deleting
    `definition.spec.require_filterable(name)` from `read_queue_page` changed nothing, and the
    reason is that the route cannot express the attack: FastAPI binds only declared query
    parameters, so the one filter that ever reaches the contract is `trader_id`, which *is*
    allowlisted. The route-level test above therefore cannot fail, whatever the contract does.

    That does not make the guard unnecessary — it makes it untested. Slices 3 to 5 add twenty-three
    more queues, each with its own `filters` frozenset, and the first route that builds its filter
    dict from several parameters will hand this function a name some other queue allowlists and
    this one does not. So the guard is called directly, one layer below the route, which is the
    only place the wrong input can be constructed.
    """

    from app.db.models.payment_request import PaymentRequest as PR
    from app.db.pagination import InvalidListParameterError
    from app.queues.contract import read_queue_page
    from app.queues.payment_requests import NEW_REQUESTS
    from sqlalchemy import select as sa_select

    request_row(world)
    actor = _any_actor(world)

    with world["runtime"].uow_factory() as uow:
        with pytest.raises(InvalidListParameterError):
            read_queue_page(
                uow.session,
                NEW_REQUESTS,
                sa_select(PR),
                actor=actor,
                # A real column of the table, and deliberately not in the queue's `filters`. The
                # queue is *defined* by its status; letting a caller filter on it would make this
                # path a way to reach a different queue through the wrong name.
                filters={"status": UNDER_REVIEW},
            )
        uow.rollback()


def _any_actor(world: dict[str, Any]) -> Any:
    """An `ActorContext` for a direct call, since `read_queue_page` takes one.

    The value is irrelevant to this queue — `_submitted_and_unclaimed` discards the actor, because
    no trader can reach the route to be scoped — but the signature requires one, and building it
    here keeps that fact visible rather than hiding it behind a mock.
    """

    from app.security.actor import ActorContext, ActorType, Audience

    return ActorContext(
        actor_type=ActorType.ADMIN_USER,
        actor_id=uuid.uuid4(),
        audience=Audience.ADMIN,
        session_id=uuid.uuid4(),
        security_stamp_version=1,
    )


def test_the_queue_returns_its_own_state_and_excludes_the_adjacent_one(
    world: dict[str, Any],
) -> None:
    """The first half passes against a query returning everything; the second is the test."""

    new = request_row(world)
    request_row(world, status=UNDER_REVIEW)
    sign_in(world, ACCOUNTANT)

    body = world["client"].get(QUEUE).json()
    assert {item["id"] for item in body["items"]} == {str(new)}
    assert {item["status"] for item in body["items"]} == {SUBMITTED}


def test_the_count_is_the_work_waiting_not_the_page_size(world: dict[str, Any]) -> None:
    """Rule five: permission-aware counts.

    Asserted with a `limit` **smaller than the queue**, because with a page big enough to hold
    everything `total` and `len(items)` are the same number and the test proves nothing. `total`
    must also exclude the adjacent state, or it is counting a different set than the rows.
    """

    for _ in range(5):
        request_row(world)
    request_row(world, status=UNDER_REVIEW)
    sign_in(world, ACCOUNTANT)

    body = world["client"].get(QUEUE, params={"limit": 2}).json()
    assert len(body["items"]) == 2
    assert body["total"] == 5


def test_the_count_reflects_the_filter_that_was_applied(world: dict[str, Any]) -> None:
    """A count computed before the filter is a count of a different question."""

    for _ in range(3):
        request_row(world)
    request_row(world, trader="other")
    sign_in(world, ACCOUNTANT)

    body = world["client"].get(QUEUE, params={"trader_id": str(world["other_id"])}).json()
    assert body["total"] == 1
    assert {item["trader_id"] for item in body["items"]} == {str(world["other_id"])}


def test_the_page_is_bounded_even_when_the_caller_asks_for_nothing(
    world: dict[str, Any],
) -> None:
    """Rule six: no client loading of all financial records.

    The default limit is 50, so 60 rows must not come back in one page. This is the rule M5's own
    `GET /payment-requests` does not satisfy — it selects every matching row — which is recorded in
    `app/queues/payment_requests.py` and is why the queue is a new route rather than a filter on
    that one.
    """

    for _ in range(60):
        request_row(world)
    sign_in(world, ACCOUNTANT)

    body = world["client"].get(QUEUE).json()
    assert len(body["items"]) == 50
    assert body["next_cursor"] is not None
    assert body["total"] == 60


def test_a_limit_outside_the_cap_is_refused_rather_than_clamped(world: dict[str, Any]) -> None:
    """Clamping would let a caller ask for 10,000, receive 200, and believe they had them all."""

    request_row(world)
    sign_in(world, ACCOUNTANT)

    assert world["client"].get(QUEUE, params={"limit": 10_000}).status_code == 400
    assert world["client"].get(QUEUE, params={"limit": 0}).status_code == 400


def test_the_walk_is_stable_when_every_row_shares_a_timestamp(world: dict[str, Any]) -> None:
    """Rules one and two together, under the only condition that can expose them.

    Six requests written at the same instant — which is what happens when a trader submits several
    in one sitting. Without `id` as the unique tiebreak, `ORDER BY created_at` leaves ties in an
    order PostgreSQL may change between executions, and the cursor then repeats or drops rows at
    the page boundary. Asserted on the **set and the count together**: a walk that returned one row
    twice and missed another has the right length and the wrong content.
    """

    stamp = datetime.now(UTC) - timedelta(hours=1)
    expected = {str(request_row(world, created_at=stamp)) for _ in range(6)}
    sign_in(world, ACCOUNTANT)

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(6):
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        response = world["client"].get(QUEUE, params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert cursor is None, "the walk did not terminate"
    assert len(seen) == len(set(seen)), f"a row was returned twice across pages: {seen}"
    assert set(seen) == expected


def test_the_oldest_request_is_at_the_top(world: dict[str, Any]) -> None:
    """A work queue is drained from the bottom, unlike every other list in this project.

    Newest-first would starve the tail: the request that has waited longest would sink further with
    every new submission. This is the one place `descending=False` is correct, so it gets its own
    assertion rather than being implied by the pagination test.
    """

    base = datetime.now(UTC) - timedelta(days=1)
    oldest = request_row(world, created_at=base)
    request_row(world, created_at=base + timedelta(hours=1))
    request_row(world, created_at=base + timedelta(hours=2))
    sign_in(world, ACCOUNTANT)

    body = world["client"].get(QUEUE).json()
    assert body["items"][0]["id"] == str(oldest)


def test_a_cursor_the_api_did_not_issue_is_refused(world: dict[str, Any]) -> None:
    """An opaque token is not a number to increment, and a forged one is a 400 rather than a 500."""

    request_row(world)
    sign_in(world, ACCOUNTANT)

    assert world["client"].get(QUEUE, params={"cursor": "not-a-cursor"}).status_code == 400


def test_the_row_carries_only_what_triage_needs(world: dict[str, Any]) -> None:
    """§19 `:1298`'s last rule in its mildest form: a queue is not a second detail surface.

    Asserted by equality on the key set. A queue row that grew an amount field would be a
    disclosure decision made by whoever added it, and slice 5's technical-admin redaction is the
    same rule where it bites hardest.
    """

    request_row(world)
    sign_in(world, ACCOUNTANT)

    item = world["client"].get(QUEUE).json()["items"][0]
    assert set(item) == {"id", "request_number", "trader_id", "status", "created_at"}


def test_the_response_names_the_queue_it_answered(world: dict[str, Any]) -> None:
    """One envelope for twenty-four routes, so the envelope has to say which one this is."""

    request_row(world)
    sign_in(world, ACCOUNTANT)

    assert world["client"].get(QUEUE).json()["queue"] == "new-requests"


# --- The registry, which is what makes the unbuilt queues visible --------------------------


def test_every_queue_in_the_document_is_built_or_planned() -> None:
    """§19.2 names twenty-four; a queue in neither collection is one nobody decided to skip.

    This is the assertion that keeps the registry honest as slices 3 to 5 land: a forgotten queue
    is silent, and silence is what `PLANNED` exists to convert into a failure.
    """

    from app.queues.registry import BUILT, PLANNED

    assert not (BUILT.keys() & PLANNED.keys()), (
        f"queues both built and planned: {sorted(BUILT.keys() & PLANNED.keys())}. A built queue "
        "must be removed from PLANNED in the same commit."
    )
    # Twenty-four in §19.2, less `ai-status`, which the document admits "only when enabled" and no
    # AI path exists to enable.
    assert len(BUILT) + len(PLANNED) == 23


def test_no_queue_allowlists_a_filter_it_cannot_apply() -> None:
    """`QueueDefinition.__post_init__` refuses one at import; this proves the guard is live.

    A construction-time check nothing exercises is indistinguishable from one that was never
    written — the same reason M11 slice 1 exercised its two granted columns.
    """

    from app.db.models.payment_request import PaymentRequest
    from app.db.pagination import ListSpec, SortField
    from app.queues.contract import QueueDefinition

    with pytest.raises(ValueError, match="no column bound"):
        QueueDefinition(
            name="broken",
            permission="payment_request.read",
            spec=ListSpec(
                sorts=(SortField("id", PaymentRequest.id, unique=True),),
                filters=frozenset({"trader_id"}),
                default_sort="id",
            ),
            predicate=lambda statement, _actor: statement,
            source="test",
            filter_columns={},
        )


def test_every_built_queue_names_a_permission_the_catalogue_holds() -> None:
    """A queue guarded by a name `declare()` would refuse is a route that cannot be mounted."""

    from app.queues.registry import BUILT
    from app.security.permission_catalogue import APPROVED_PERMISSIONS

    unknown = sorted(
        definition.permission
        for definition in BUILT.values()
        if definition.permission not in APPROVED_PERMISSIONS
    )
    assert unknown == [], f"queues guarded by permissions the catalogue does not hold: {unknown}"
