"""Which queues are mine. M11 Screens slice 2.

`15_Agent_Implementation_Plan.md:1260`, §19.3 (`:1298`), §20.1 (`:2114`).

A queue screen cannot show a person their work without first asking which queues are theirs, and
the two candidate answers were both wrong:

- **a copy of the registry in TypeScript** — sixteen names, sixteen permissions and thirty-two
  allowlists, kept in step with the backend by nobody;
- **`GET /reports/queue-summary`** — which counts the same queues and is guarded by `report.read`,
  a grant `warehouse_operator` and `technical_admin` do not hold. Between them they hold four of
  the sixteen queues, and the warehouse operator's whole working day is three of them.

So `GET /api/v1/queues` exists, and this file is about the one property that makes it safe: **it
adds no authority.** Every number it returns is one the caller could already read from that
queue's own page, and every queue it omits is one that page would refuse.

`test_queue_summary_report.py` proved the report is permission-aware. This proves the index is,
and — the part a single-surface test cannot see — that the two agree.

Covers: UI-QUEUE-001.
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
TRADER_PHONE = "+989120052001"
IBAN = "IR060120000000000000000202"

ACCOUNTANT = "index_accountant"
WAREHOUSE = "index_warehouse"
AUDITOR = "index_auditor"
# An active administrator holding no role at all. Authentication and authorisation are separate,
# and this account is what makes "no grant is required to ask" testable: there is no seeded admin
# role with zero queue grants, so one has to be made.
ROLELESS = "index_roleless"

INDEX = "/api/v1/queues"
REPORT = "/api/v1/reports/queue-summary"

# `gold_sale.dispatch`, which `warehouse_operator` holds alone.
WAREHOUSE_QUEUES = frozenset(
    {"orders-ready-for-dispatch", "blocked-dispatches", "receipt-confirmation-work"}
)


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
        local_storage_root=tmp_path_factory.mktemp("index-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="z" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    ids: dict[str, uuid.UUID] = {}
    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        trader_id = uuid.uuid4()
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'A Business', %s, 'active', 'approved')",
            (trader_id, TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'A Business', %s, 'active', TRUE)",
            (trader_id, TRADER_PHONE, encoded),
        )
        beneficiary_id = uuid.uuid4()
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'Payee', %s, %s, 'active', "
            "'not_checked')",
            (beneficiary_id, trader_id, IBAN, IBAN),
        )
        ids["trader"] = trader_id
        ids["beneficiary"] = beneficiary_id

        for username, role in (
            (ACCOUNTANT, "accountant"),
            (WAREHOUSE, "warehouse_operator"),
            (AUDITOR, "read_only_auditor"),
            (ROLELESS, None),
        ):
            connection.execute(
                "INSERT INTO admin_users (username, full_name, password_hash, status) "
                "VALUES (%s, %s, %s, 'active')",
                (username, username, encoded),
            )
            if role is None:
                continue
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
        yield {"client": client, "owner_url": migrated.owner_url, **ids}
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(autouse=True)
def an_empty_world(world: dict[str, Any]) -> Iterator[None]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute("DELETE FROM payment_requests")
        connection.execute("DELETE FROM gold_sale_orders")
        connection.execute("DELETE FROM manual_review_tasks")
        connection.commit()
    yield


def sign_in(world: dict[str, Any], username: str) -> None:
    client = world["client"]
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def index_of(world: dict[str, Any]) -> dict[str, Any]:
    response = world["client"].get(INDEX)
    assert response.status_code == 200, response.text
    return dict(response.json())


def a_new_request(world: dict[str, Any]) -> uuid.UUID:
    request_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO payment_requests (id, trader_id, beneficiary_id, request_number, "
            "status) VALUES (%s, %s, %s, %s, 'submitted_to_center')",
            (request_id, world["trader"], world["beneficiary"], f"PR-{uuid.uuid4().hex[:8]}"),
        )
        connection.commit()
    return request_id


def a_reconciliation_task(world: dict[str, Any]) -> uuid.UUID:
    task_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO manual_review_tasks (id, task_type, priority, status, entity_type, "
            "entity_id, title, record_version) VALUES (%s, 'payment_result_discrepancy', 3, "
            "'open', 'payment_attempt', %s, 'seeded', 1)",
            (task_id, uuid.uuid4()),
        )
        connection.commit()
    return task_id


def an_order_ready_for_dispatch(world: dict[str, Any]) -> uuid.UUID:
    order_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO gold_sale_orders (id, trader_id, order_number, status, gold_type, "
            "gold_weight, weight_unit, gold_purity, created_by_actor_type) "
            "VALUES (%s, %s, %s, 'incoming_payment_confirmed', 'bullion', 10.0, 'GRAM', '750', "
            "'trader_user')",
            (order_id, world["trader"], f"GS-{uuid.uuid4().hex[:8]}"),
        )
        connection.commit()
    return order_id


def test_the_index_omits_a_queue_whose_grant_the_caller_lacks(world: dict[str, Any]) -> None:
    """The negative `test_m3_definition_of_done.py` classified this route as owing.

    **The route refuses nobody**, so its negative cannot be a status code. What it must not do is
    tell somebody about a queue they may not read — and the failure that matters is *silent*: an
    index that ignored grants would look like a working screen to everybody.

    The accountant and the read-only auditor are the pair, chosen the way the report test chose
    them: both hold `payment_request.read`, so both must see `new-requests`; only the accountant
    holds `manual_review.read`, so only the accountant may see `reconciliation-tasks`. An entirely
    disjoint pair could not tell "permission-aware" from "each role gets a fixed list".

    The shared queue is asserted **present** for both, because "reconciliation-tasks is absent from
    the auditor's index" is also satisfied by an index that returned nothing at all, which is the
    failure mode of a filter that has stopped matching.
    """

    a_new_request(world)
    a_reconciliation_task(world)

    sign_in(world, ACCOUNTANT)
    accountant = {row["name"] for row in index_of(world)["items"]}
    sign_in(world, AUDITOR)
    auditor = {row["name"] for row in index_of(world)["items"]}

    assert "new-requests" in accountant and "new-requests" in auditor, "the shared queue is missing"
    assert "reconciliation-tasks" in accountant
    assert "reconciliation-tasks" not in auditor, (
        "the auditor was shown the reconciliation queue, which needs manual_review.read"
    )


def test_the_warehouse_operator_reaches_this_and_not_the_report(world: dict[str, Any]) -> None:
    """**The reason this route exists**, and the whole argument for it in one test.

    `report.read` goes to `accountant, manager, business_admin, read_only_auditor`.
    `gold_sale.dispatch` goes to `warehouse_operator` alone. So a landing page built on the report
    answers 403 to the one role whose entire day is three queues — asserted here rather than
    described, because if `report.read` is ever granted to the warehouse the argument changes and
    this test should be the thing that says so.

    The index answers, and answers with **exactly** the three. An equality rather than a
    containment: an index that returned all sixteen to everybody would satisfy "contains the
    warehouse's three".
    """

    an_order_ready_for_dispatch(world)

    sign_in(world, WAREHOUSE)
    assert world["client"].get(REPORT).status_code == 403, (
        "the warehouse operator can now read reports; the argument for a separate index has "
        "changed and `app/queues/index.py` should be revisited rather than this line relaxed"
    )

    listed = index_of(world)
    assert {row["name"] for row in listed["items"]} == WAREHOUSE_QUEUES


def test_no_grant_is_required_to_ask_and_the_answer_is_empty_rather_than_a_refusal(
    world: dict[str, Any],
) -> None:
    """An active administrator with no role at all.

    The alternative design guarded the index by some permission, and every candidate was wrong:
    inventing one is a governance act, and borrowing `report.read` refuses two roles that hold
    queues. What is left is a route that requires a session and nothing else.

    **200 with an empty list, not 403.** The distinction is the whole point: a refusal says "you
    may not ask", which is false, where an empty list says "nothing here is yours", which is true.
    A screen can render the second honestly and can only guess at the first.
    """

    a_new_request(world)
    a_reconciliation_task(world)
    an_order_ready_for_dispatch(world)

    sign_in(world, ROLELESS)
    listed = index_of(world)

    assert listed["items"] == []
    assert listed["total"] == 0
    # And the queues genuinely have rows in them, so the empty list is a scoping result rather
    # than an empty database.
    sign_in(world, ACCOUNTANT)
    assert index_of(world)["total"] > 0


def test_an_unauthenticated_caller_is_refused(world: dict[str, Any]) -> None:
    """No session, no actor to scope by. `requires(...)` is absent; the actor dependency is not."""

    world["client"].cookies.clear()
    assert world["client"].get(INDEX).status_code == 401


def test_the_index_discloses_nothing_the_queue_pages_do_not(world: dict[str, Any]) -> None:
    """The safety argument for an unguarded door, asserted rather than written in a docstring.

    For every entry the index returns, the caller can open that queue and be told the same number.
    If that holds, the index is an aggregation of things this person may already read, and giving
    it its own grant would protect nothing.

    `waiting` is compared against the queue page's own `total` — which is not a coincidence but a
    shared implementation: `visible_queues` counts through `summarise_queues`, which counts through
    `read_queue_page`, which is what the page uses. **The test is here to catch the day that stops
    being true**, because on that day the index becomes a second definition of "waiting" and the
    two numbers start to drift.
    """

    an_order_ready_for_dispatch(world)
    sign_in(world, WAREHOUSE)

    for entry in index_of(world)["items"]:
        page = world["client"].get(f"{INDEX}/{entry['name']}")
        assert page.status_code == 200, f"{entry['name']}: {page.text}"
        assert page.json()["total"] == entry["waiting"], (
            f"{entry['name']}: the index says {entry['waiting']} and the page says "
            f"{page.json()['total']}. Two definitions of waiting have appeared."
        )


def test_every_filter_and_sort_the_index_advertises_is_one_the_queue_accepts(
    world: dict[str, Any],
) -> None:
    """The index tells a screen which controls to render. A wrong name is a 400 in somebody's face.

    `read_queue_page` **refuses** an unlisted sort rather than ignoring it, which is the right
    behaviour and also what makes an advertised-but-unaccepted name a visible failure rather than a
    quiet one. So each advertised sort is exercised, and the default is exercised by name too — a
    `default_sort` the route would refuse is the same defect one step further from view.
    """

    an_order_ready_for_dispatch(world)
    sign_in(world, WAREHOUSE)

    entries = index_of(world)["items"]
    assert entries, "no queues to check, so this test is about nothing"

    for entry in entries:
        assert entry["sorts"], f"{entry['name']} advertises no sort, so no ordering is selectable"
        assert entry["default_sort"] in entry["sorts"], (
            f"{entry['name']}: default_sort {entry['default_sort']!r} is not among its own "
            f"sortable fields {entry['sorts']}"
        )
        for sort in entry["sorts"]:
            response = world["client"].get(f"{INDEX}/{entry['name']}?sort={sort}")
            assert response.status_code == 200, (
                f"{entry['name']} advertises sort {sort!r} and the route answered "
                f"{response.status_code}: {response.text}"
            )


def test_the_page_walks_a_cursor_and_never_an_offset(world: dict[str, Any]) -> None:
    """§19.3's paging rule, and `UI-QUEUE-001`'s second half.

    An offset re-reads the table from the top on every page: rows shift under a person draining a
    queue, so items are skipped or seen twice — and a queue is the one place that matters, because
    the whole purpose is to work through every row exactly once.

    Asserted three ways, because "the response has a `next_cursor`" is satisfied by an
    implementation that also honours an offset:

    1. two rows and `limit=1` produce a cursor, and following it yields the *other* row;
    2. following it to the end yields `next_cursor: null` rather than repeating;
    3. `offset` **does nothing** — sending it returns the same first row.

    The third assertion originally demanded a 400 and failed: FastAPI ignores query parameters a
    route does not declare, everywhere in this application, and making one route refuse them would
    be a framework-wide decision taken for one screen. **The demand was the wrong question.** What
    §19.3 needs is that an offset cannot be used to page — and a parameter that is ignored cannot.
    "Ignored" is checked positively here rather than assumed: the row returned with `offset=1` is
    asserted to be the *same* row, which is what distinguishes ignoring from honouring.

    The contract half — that no queue path declares such a parameter, so no client is invited to
    try — is in `tests/backend/test_queue_screens_exist.py`, which reads the published OpenAPI.
    """

    first = an_order_ready_for_dispatch(world)
    second = an_order_ready_for_dispatch(world)
    sign_in(world, WAREHOUSE)

    page_one = world["client"].get(f"{INDEX}/orders-ready-for-dispatch?limit=1")
    assert page_one.status_code == 200, page_one.text
    body_one = page_one.json()
    assert len(body_one["items"]) == 1
    assert body_one["total"] == 2
    assert body_one["next_cursor"], "a page smaller than the total returned no cursor"

    page_two = world["client"].get(
        f"{INDEX}/orders-ready-for-dispatch?limit=1&cursor={body_one['next_cursor']}"
    )
    assert page_two.status_code == 200, page_two.text
    body_two = page_two.json()
    assert len(body_two["items"]) == 1

    seen = {body_one["items"][0]["id"], body_two["items"][0]["id"]}
    assert seen == {str(first), str(second)}, (
        f"the two pages returned {seen}, so the cursor did not advance past the first row"
    )
    assert body_two["next_cursor"] is None, "the last page offered a cursor to nowhere"

    # An offset does nothing. Compared against page one's row rather than merely checked for a
    # 200: an honoured offset would also answer 200, and would answer it with the second row.
    ignored = world["client"].get(f"{INDEX}/orders-ready-for-dispatch?limit=1&offset=1")
    assert ignored.status_code == 200, ignored.text
    assert ignored.json()["items"][0]["id"] == body_one["items"][0]["id"], (
        "`offset=1` skipped a row, so the queue is offset-pageable after all. Offset paging skips "
        "and repeats rows under concurrent writes, which is exactly what draining a queue does "
        "to it."
    )
