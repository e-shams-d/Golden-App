"""The one report M11 builds, and the two roles it must answer differently. M11 slice 7.

`15_Agent_Implementation_Plan.md:1331`.

§19's goal is that each role can *identify* its work. The report exists so a person can ask "is
there anything for me" once instead of opening sixteen pages, and the property that makes it
correct rather than merely convenient is that **two roles asking the same question get different
answers**.

Three ways it could be wrong, and each is a separate test:

- it could count queues the caller may not read — the leak §19 `:1298`'s permission-aware rule
  forbids, and the one a single-role test cannot see;
- it could report a queue the caller may not read as `0` rather than omitting it, which still says
  "that queue exists and is empty";
- it could be reachable without `report.read` at all.

**No `Covers:` line.** The plan gives slice 7 one obligation — the milestone walk — and this file
is not it: it tests the report, not that a role can carry work from a queue to completion. The
first draft cited an id that does not exist in any catalogue, which is worth recording because a
plausible-looking identifier is exactly the kind of citation nobody checks.
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
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"
TRADER_PHONE = "+989120051001"
IBAN = "IR060120000000000000000201"

ACCOUNTANT = "report_accountant"
WAREHOUSE = "report_warehouse"
AUDITOR = "report_auditor"
REPORT = "/api/v1/reports/queue-summary"


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
        local_storage_root=tmp_path_factory.mktemp("report-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="y" * 40,
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


def a_reconciliation_task(world: dict[str, Any]) -> uuid.UUID:
    """One open task of a type the reconciliation queue names."""

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


def test_two_roles_asking_the_same_question_get_different_answers(
    world: dict[str, Any],
) -> None:
    """**The property that makes this report correct rather than convenient.**

    The accountant and the read-only auditor both hold `report.read` and both hold
    `payment_request.read`, so both see `new-requests`. Only the accountant holds
    `manual_review.read`, so only the accountant sees `reconciliation-tasks`.

    A test with one role would pass against a report that counted every queue for everybody. The
    pair is chosen so that the two summaries **overlap in one queue and differ in another** — an
    entirely disjoint pair could not tell "permission-aware" from "each role gets a fixed list".
    """

    a_new_request(world)
    a_reconciliation_task(world)

    sign_in(world, ACCOUNTANT)
    accountant = {row["queue"] for row in world["client"].get(REPORT).json()["counts"]}
    sign_in(world, AUDITOR)
    auditor = {row["queue"] for row in world["client"].get(REPORT).json()["counts"]}

    assert "new-requests" in accountant and "new-requests" in auditor, "the shared queue is missing"
    assert "reconciliation-tasks" in accountant
    assert "reconciliation-tasks" not in auditor, (
        "the auditor was told how much reconciliation work exists, which needs manual_review.read"
    )


def test_the_warehouse_cannot_read_any_report_and_that_is_a_recorded_gap(
    world: dict[str, Any],
) -> None:
    """§19's goal is that **each** role can identify its work. One cannot.

    `report.read` goes to `accountant, manager, business_admin, read_only_auditor`;
    `gold_sale.dispatch` goes to `warehouse_operator` alone. No role holds both, so the warehouse's
    three queues can never appear in anybody's summary, and the warehouse operator cannot ask for a
    summary at all.

    This is asserted rather than worked around. Granting `report.read` to the warehouse operator
    would be inventing an authority the catalogue does not give, which is the same refusal this
    milestone made for `payment_publication.correct` and `report.export`. The gap belongs to M0.

    When it is closed, this test fails and says so — which is the point of writing it as an
    assertion rather than a comment.
    """

    an_order_ready_for_dispatch(world)

    sign_in(world, WAREHOUSE)
    assert world["client"].get(REPORT).status_code == 403

    # And no other role can see the queue on their behalf.
    for username in (ACCOUNTANT, AUDITOR):
        sign_in(world, username)
        queues = {row["queue"] for row in world["client"].get(REPORT).json()["counts"]}
        assert "orders-ready-for-dispatch" not in queues


def test_a_queue_the_caller_cannot_read_is_absent_rather_than_zero(
    world: dict[str, Any],
) -> None:
    """A zero would say "that queue exists and is empty", which is somebody else's business.

    Asserted with the dispatch queue **non-empty**: if it held nothing, a leak reporting `0` and
    the correct omission would look identical.
    """

    an_order_ready_for_dispatch(world)

    sign_in(world, ACCOUNTANT)
    body = world["client"].get(REPORT).json()

    for row in body["counts"]:
        assert row["queue"] != "orders-ready-for-dispatch", (
            "a queue the accountant cannot read appeared in their summary"
        )


def test_the_count_matches_what_the_queue_itself_returns(world: dict[str, Any]) -> None:
    """One definition of "waiting", not two.

    The report reads through the queue's own predicate, so a queue whose definition changes cannot
    drift from its own summary. Asserted against the queue endpoint rather than against a number
    written here, which would be a third definition.
    """

    for _ in range(3):
        a_new_request(world)

    sign_in(world, ACCOUNTANT)
    summary = world["client"].get(REPORT).json()
    queue = world["client"].get("/api/v1/queues/new-requests").json()

    reported = next(row["waiting"] for row in summary["counts"] if row["queue"] == "new-requests")
    assert reported == queue["total"] == 3


def test_the_total_is_the_sum_of_what_this_caller_may_see(world: dict[str, Any]) -> None:
    """Not a system-wide total: two roles get different totals, which is the point."""

    a_new_request(world)
    an_order_ready_for_dispatch(world)

    sign_in(world, ACCOUNTANT)
    body = world["client"].get(REPORT).json()

    assert body["total"] == sum(row["waiting"] for row in body["counts"])
    assert body["total"] == 1, "the dispatch queue leaked into the accountant's total"


def test_a_role_without_the_report_grant_cannot_ask(world: dict[str, Any]) -> None:
    """`report.read` decides whether the question may be asked at all.

    The warehouse operator holds queue grants and not this one, which is the refusal worth testing:
    a caller who can read a queue directly still cannot read the report over it.
    """

    sign_in(world, WAREHOUSE)
    assert world["client"].get(REPORT).status_code == 403


def test_an_unauthenticated_caller_is_refused(world: dict[str, Any]) -> None:
    world["client"].cookies.clear()
    assert world["client"].get(REPORT).status_code == 401


def test_no_export_route_exists(world: dict[str, Any]) -> None:
    """§19 names report export; `report.export` is granted to no role.

    A route behind it would refuse every caller — the `bank_profile.activate_version` shape this
    project already carries once. Asserted as a 404 rather than trusted to a docstring, because
    "we did not build it" and "we built it and it denies everybody" look the same from a plan.
    """

    sign_in(world, ACCOUNTANT)
    for path in ("/api/v1/reports/queue-summary/export", "/api/v1/reports/export"):
        assert world["client"].get(path).status_code == 404, f"{path} exists"
