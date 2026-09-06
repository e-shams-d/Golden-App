"""M11's Definition of Done: a person can find their work and finish it.
`15_Agent_Implementation_Plan.md:1331`.

§19's goal is that **each role can identify and complete its work from controlled queues, and every
operational failure is visible to the responsible role.** This file is that sentence as a walk.

**A walk rather than a checklist, for M10's reason.** A test asserting the sixteen queues *exist*
would prove they exist and not that anybody can work from them. So this takes one item from
creation, finds it through a queue the way a person would, acts on it, and asserts it leaves that
queue — which is the part that fails when a queue's predicate and a command's transition disagree.

**Nothing is written directly except the trader and the request.** Every later state is reached by
the command that owns it, because a walk that inserted its own intermediate rows would prove the
states exist rather than that anything can reach them.

Covers: TRACE-M11-001.
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

TRADER_PHONE = "+989120061001"
IBAN = "IR060120000000000000000301"
ACCOUNTANT = "dod_accountant"


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
        local_storage_root=tmp_path_factory.mktemp("dod-storage"),
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
            "approval_status) VALUES (%s, 'Walking Business', %s, 'active', 'approved')",
            (trader_id, TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Walking Business', %s, 'active', TRUE)",
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

        connection.execute(
            "INSERT INTO admin_users (username, full_name, password_hash, status) "
            "VALUES (%s, 'DoD Accountant', %s, 'active')",
            (ACCOUNTANT, encoded),
        )
        connection.execute(
            "INSERT INTO admin_user_roles (admin_user_id, role_id) "
            "SELECT u.id, r.id FROM admin_users u, roles r "
            "WHERE u.username = %s AND r.code = 'accountant'",
            (ACCOUNTANT,),
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
def a_quiet_world(world: dict[str, Any]) -> Iterator[None]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute("DELETE FROM payment_requests")
        connection.execute("DELETE FROM notifications")
        connection.commit()
    yield


def sign_in_admin(world: dict[str, Any]) -> None:
    client = world["client"]
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": ACCOUNTANT, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def csrf(world: dict[str, Any]) -> dict[str, str]:
    client = world["client"]
    token = client.cookies.get(ADMIN_CSRF_COOKIE) or client.cookies.get(TRADER_CSRF_COOKIE)
    assert token, "signed in but no CSRF cookie was set"
    return {CSRF_HEADER: token}


def a_submitted_request(world: dict[str, Any]) -> uuid.UUID:
    """One request waiting for the centre.

    Written directly rather than driven through M5's commands: this file's subject is the queue
    surface M11 built, and re-walking the request lifecycle would test M5 again while making the
    fixture long enough to obscure what is being asserted.
    """

    request_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO payment_requests (id, trader_id, beneficiary_id, request_number, "
            "status, record_version) VALUES (%s, %s, %s, %s, 'submitted_to_center', 1)",
            (request_id, world["trader"], world["beneficiary"], f"PR-{uuid.uuid4().hex[:8]}"),
        )
        connection.commit()
    return request_id


def test_the_milestone_walks_end_to_end(world: dict[str, Any]) -> None:
    """**TRACE-M11-001.** An accountant finds work in a queue and completes it.

    Five steps, and the fourth is the one that would fail if a queue's predicate and a command's
    transition disagreed:

    1. the report says there is something waiting;
    2. the queue names it;
    3. the accountant acts on it through the command that owns the transition;
    4. **the queue no longer names it** — the assertion a checklist could not make;
    5. the report's count drops with it.
    """

    request_id = a_submitted_request(world)
    sign_in_admin(world)
    client = world["client"]

    # 1. Identify: the report says work is waiting, without naming which queue to open.
    summary = client.get("/api/v1/reports/queue-summary").json()
    waiting = {row["queue"]: row["waiting"] for row in summary["counts"]}
    assert waiting.get("new-requests") == 1, f"the report did not see the work: {summary}"

    # 2. Locate: the queue names the item.
    queue = client.get("/api/v1/queues/new-requests").json()
    assert [item["id"] for item in queue["items"]] == [str(request_id)]
    assert queue["total"] == 1

    # 3. Act: through the command that owns the transition, not by writing the status.
    #
    # `If-Match` carries the version the *server* holds, in the `rv-N` form
    # `_parse_record_version` requires — a bare number is rejected as a conflict rather than as a
    # malformed header, which is how the first draft of this walk spent two runs looking for a
    # race that was not there.
    detail = client.get(f"/api/v1/payment-requests/{request_id}").json()
    version = detail["request"]["record_version"]
    started = client.post(
        f"/api/v1/payment-requests/{request_id}/start-review",
        headers={**csrf(world), "If-Match": f'"rv-{version}"'},
    )
    assert started.status_code == 200, started.text

    # 4. The queue lets it go. `under_accountant_review` is the adjacent state the queue excludes,
    #    so a predicate that filtered on nothing, or a command that moved the wrong column, fails
    #    exactly here.
    after = client.get("/api/v1/queues/new-requests").json()
    assert after["items"] == [], "the request stayed in the queue after somebody took it"
    assert after["total"] == 0

    # 5. And the report agrees, because it reads the same predicate rather than a second one.
    final = client.get("/api/v1/reports/queue-summary").json()
    remaining = {row["queue"]: row["waiting"] for row in final["counts"]}
    assert remaining.get("new-requests") == 0


def test_the_report_and_the_queue_cannot_disagree(world: dict[str, Any]) -> None:
    """Step 5's property, isolated across every queue the caller can read.

    The walk above proves it for one queue at one moment. This asserts it for all of them, which
    is what catches a report that counted correctly for the queue somebody tested and wrongly for
    the fifteen they did not.
    """

    for _ in range(2):
        a_submitted_request(world)
    sign_in_admin(world)
    client = world["client"]

    summary = client.get("/api/v1/reports/queue-summary").json()
    for row in summary["counts"]:
        page = client.get(f"/api/v1/queues/{row['queue']}").json()
        assert row["waiting"] == page["total"], (
            f"{row['queue']}: the report says {row['waiting']} and the queue says {page['total']}"
        )


def test_every_built_queue_is_reachable_by_somebody(world: dict[str, Any]) -> None:
    """§19's "each role can identify its work" has a failure mode nothing else here would catch.

    A queue guarded by a permission no role holds is reachable by nobody — the shape
    `bank_profile.activate_version` already has. The registry's own permission is checked against
    the seeded role grants, so a queue that becomes unreachable fails here rather than being
    discovered when somebody asks why their list is always empty.

    **Uses the seeded RBAC rather than a hand-written map**, because a hand-written one would agree
    with itself.
    """

    from app.queues.registry import BUILT

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        granted = {
            row[0]
            for row in connection.execute(
                "SELECT p.code FROM permissions p "
                "JOIN role_permissions rp ON rp.permission_id = p.id"
            ).fetchall()
        }

    unreachable = sorted(
        name for name, definition in BUILT.items() if definition.permission not in granted
    )
    assert unreachable == [], (
        f"these queues are guarded by permissions no role holds, so nobody can work from them: "
        f"{unreachable}"
    )
