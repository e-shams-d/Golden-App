"""Opening a draft request, and cancelling one, against a real database.

M5 slice 3. Four traders exist in this fixture rather than two, because `SEC-REQ-001`
is about two *different* status axes: DOC-CONFLICT-024 keeps `approval_status` and
`operational_status` separate, and a guard that checked one would let the other
through. A business awaiting approval and a business suspended today are both refused,
for different reasons, and only four traders can show that.

Covers: SEC-REQ-001, CON-REQ-001.
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

IBAN = "IR060120000000000000000001"

# Four businesses, one per combination that matters. `ok` is the only one that may
# create a request; each of the other three is refused by a different column.
TRADERS: dict[str, tuple[str, str, str]] = {
    "ok": ("+989120000101", "active", "approved"),
    "pending": ("+989120000102", "active", "pending_approval"),
    "suspended": ("+989120000103", "suspended", "approved"),
    "other": ("+989120000104", "active", "approved"),
}


@pytest.fixture
def migrated(provisioned_database: RuntimeIdentities) -> RuntimeIdentities:
    result = run_alembic(
        provisioned_database.migrator_url,
        "upgrade",
        "head",
        app_role=provisioned_database.app_role,
        worker_role=provisioned_database.worker_role,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return provisioned_database


@pytest.fixture
def world(migrated: RuntimeIdentities, tmp_path: Any) -> Iterator[dict[str, Any]]:
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
        local_storage_root=tmp_path / "storage",
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="c" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    ids: dict[str, uuid.UUID] = {name: uuid.uuid4() for name in TRADERS}
    beneficiaries: dict[str, uuid.UUID] = {name: uuid.uuid4() for name in TRADERS}

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        for name, (phone, operational, approval) in TRADERS.items():
            connection.execute(
                "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
                "approval_status) VALUES (%s, %s, %s, %s, %s)",
                (ids[name], f"Trader {name}", phone, operational, approval),
            )
            connection.execute(
                "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
                "status, is_primary) VALUES (%s, %s, %s, %s, 'active', TRUE)",
                (ids[name], phone, f"{name} Contact", encoded),
            )
            connection.execute(
                "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
                "status, verification_status) VALUES (%s, %s, 'Ali', %s, %s, 'active', "
                "'not_checked')",
                (beneficiaries[name], ids[name], IBAN, IBAN),
            )

        for username in ("staff_granted", "staff_bare"):
            connection.execute(
                "INSERT INTO admin_users (username, full_name, password_hash, status) "
                "VALUES (%s, %s, %s, 'active')",
                (username, f"{username} User", encoded),
            )
        connection.execute(
            "INSERT INTO admin_user_roles (admin_user_id, role_id) "
            "SELECT u.id, r.id FROM admin_users u, roles r "
            "WHERE u.username = 'staff_granted' AND r.code = 'accountant'"
        )
        connection.commit()

    app = create_app(settings=settings)
    app.state.runtime = RuntimeServices.from_settings(settings)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://trader.localhost") as client:
        yield {
            "client": client,
            "traders": ids,
            "beneficiaries": beneficiaries,
            "owner_url": migrated.owner_url,
        }
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def sign_in_trader(client: Any, name: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/trader/login",
        json={"identifier": TRADERS[name][0], "password": PASSWORD},
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


def open_draft(client: Any, beneficiary: uuid.UUID, **extra: Any) -> Any:
    return client.post(
        "/api/v1/payment-requests",
        json={"beneficiary_id": str(beneficiary), "amount_irr": "5000000", **extra},
        headers=csrf(client),
    )


def test_a_draft_is_a_request_and_its_first_revision(world: dict[str, Any]) -> None:
    """The ordinary path, and the shape the milestone rests on.

    The response carries both, and the request's `current_revision_id` names the
    revision — proving the deferrable composite pointer was satisfied inside one
    transaction rather than left null and patched later.
    """

    client = world["client"]
    sign_in_trader(client, "ok")

    created = open_draft(client, world["beneficiaries"]["ok"], description="rent")
    assert created.status_code == 201, created.text
    body = created.json()

    assert body["request"]["status"] == "draft"
    assert body["request"]["trader_id"] == str(world["traders"]["ok"])
    assert body["request"]["current_revision_id"] == body["revision"]["id"]
    assert body["revision"]["revision_number"] == 1
    assert body["revision"]["amount_irr"] == "5000000"
    assert body["revision"]["beneficiary_iban_snapshot"] == IBAN
    assert body["revision"]["beneficiary_name_snapshot"] == "Ali"
    assert len(body["revision"]["content_hash"]) == 64

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        rows = connection.execute(
            "SELECT count(*) FROM payment_request_revisions WHERE payment_request_id = %s",
            (body["request"]["id"],),
        ).fetchone()
    assert rows is not None and rows[0] == 1


def test_money_crosses_the_api_as_a_string(world: dict[str, Any]) -> None:
    """`15_Agent_Implementation_Plan.md:800`.

    Slice 4 owns the conversion; this is the contract half, and it belongs here
    because the response schema is set by this slice. A JSON number would be a float
    in most clients, and a float is not a currency.
    """

    client = world["client"]
    sign_in_trader(client, "ok")

    created = open_draft(
        client,
        world["beneficiaries"]["ok"],
        entered_amount_value="500",
        entered_amount_unit="TOMAN",
    )
    assert created.status_code == 201, created.text
    revision = created.json()["revision"]

    assert isinstance(revision["amount_irr"], str)
    assert isinstance(revision["entered_amount_value"], str)
    assert revision["entered_amount_unit"] == "TOMAN"


@pytest.mark.parametrize("trader", ["pending", "suspended"])
def test_a_trader_that_is_not_operable_cannot_open_a_draft(
    world: dict[str, Any], trader: str
) -> None:
    """SEC-REQ-001, `15_Agent_Implementation_Plan.md:806`.

    Both statuses, because they are different axes. `pending` is approved-not-yet and
    `suspended` is barred-today, and a guard reading only `approval_status` would let
    the suspended business keep creating requests — which is exactly what suspension
    exists to stop.
    """

    client = world["client"]
    sign_in_trader(client, trader)

    refused = open_draft(client, world["beneficiaries"][trader])

    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["code"] == "BUSINESS_RULE_VIOLATION"

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        count = connection.execute(
            "SELECT count(*) FROM payment_requests WHERE trader_id = %s",
            (world["traders"][trader],),
        ).fetchone()
    assert count is not None and count[0] == 0, "the refusal still wrote a row"


def test_an_operable_trader_is_not_refused(world: dict[str, Any]) -> None:
    """SEC-REQ-001, guard-the-guard.

    Without this, a guard that refused everybody would satisfy both cases above and
    look like a working status check.
    """

    client = world["client"]
    sign_in_trader(client, "ok")
    assert open_draft(client, world["beneficiaries"]["ok"]).status_code == 201


def test_a_trader_cannot_open_a_request_under_another_trader(world: dict[str, Any]) -> None:
    """SEC-REQ-001, the ownership negative.

    Two ways it could go wrong and both are asserted. The body's `trader_id` is for
    internal callers and must be ignored on the trader path; and a beneficiary
    belonging to another trader must answer as a missing one rather than confirming
    the id is real.
    """

    client = world["client"]
    sign_in_trader(client, "ok")

    submitted = open_draft(
        client,
        world["beneficiaries"]["ok"],
        trader_id=str(world["traders"]["other"]),
    )
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["request"]["trader_id"] == str(world["traders"]["ok"]), (
        "the submitted trader_id was honoured; a trader opened a request under another"
    )

    borrowed = open_draft(client, world["beneficiaries"]["other"])
    assert borrowed.status_code == 404, (
        "another trader's beneficiary must answer as a missing one, not confirm it exists"
    )


def test_an_admin_without_the_request_permission_is_refused(world: dict[str, Any]) -> None:
    """The permission negative for both routes.

    `staff_bare` holds a real session and no request permission. The CSRF token is
    sent, because a missing one is refused with the identical `FORBIDDEN` envelope and
    a version of this test that omitted it would assert `403`, pass, and prove nothing.
    The `staff_granted` half is what makes the refusal about the grant.
    """

    client = world["client"]

    sign_in_trader(client, "ok")
    created = open_draft(client, world["beneficiaries"]["ok"]).json()["request"]

    sign_in_admin(client, "staff_bare")
    refused = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiaries"]["ok"]),
            "amount_irr": "1000",
            "trader_id": str(world["traders"]["ok"]),
        },
        headers=csrf(client),
    )
    assert refused.status_code == 403, refused.text

    refused_cancel = client.post(
        f"/api/v1/payment-requests/{created['id']}/cancel",
        json={},
        headers={**csrf(client), "If-Match": f'"rv-{created["record_version"]}"'},
    )
    assert refused_cancel.status_code == 403, refused_cancel.text

    sign_in_admin(client, "staff_granted")
    allowed = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiaries"]["ok"]),
            "amount_irr": "1000",
            "trader_id": str(world["traders"]["ok"]),
        },
        headers=csrf(client),
    )
    assert allowed.status_code != 403, (
        f"the permitted admin was refused too ({allowed.status_code}), so the 403 above "
        f"was not about the permission: {allowed.text}"
    )


def test_cancelling_requires_a_current_if_match(world: dict[str, Any]) -> None:
    """CON-REQ-001. `15_Agent_Implementation_Plan.md:812`.

    Three answers, and the difference between the first two matters: `428` when the
    header is absent and `412` when it is stale. Answering `412` to a caller who sent
    nothing would send them hunting for a value they never had.
    """

    client = world["client"]
    sign_in_trader(client, "ok")
    created = open_draft(client, world["beneficiaries"]["ok"]).json()["request"]
    path = f"/api/v1/payment-requests/{created['id']}/cancel"

    without = client.post(path, json={}, headers=csrf(client))
    assert without.status_code == 428, without.text

    stale = client.post(path, json={}, headers={**csrf(client), "If-Match": '"rv-99"'})
    assert stale.status_code == 412, stale.text

    current = client.post(
        path,
        json={"reason": "changed my mind"},
        headers={**csrf(client), "If-Match": f'"rv-{created["record_version"]}"'},
    )
    assert current.status_code == 200, current.text
    assert current.json()["status"] == "cancelled"
    assert current.headers["ETag"] == f'"rv-{current.json()["record_version"]}"'


def test_a_stale_if_match_does_not_overwrite(world: dict[str, Any]) -> None:
    """CON-REQ-001, and the half the status code alone does not prove.

    "Returns 412 rather than overwriting" is two claims. A route could answer `412`
    after having already written, and the response would look identical. So the row is
    read back afterwards and must still be a draft.
    """

    client = world["client"]
    sign_in_trader(client, "ok")
    created = open_draft(client, world["beneficiaries"]["ok"]).json()["request"]

    stale = client.post(
        f"/api/v1/payment-requests/{created['id']}/cancel",
        json={"reason": "should not apply"},
        headers={**csrf(client), "If-Match": '"rv-99"'},
    )
    assert stale.status_code == 412

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        row = connection.execute(
            "SELECT status, cancelled_at, cancelled_reason, record_version "
            "FROM payment_requests WHERE id = %s",
            (created["id"],),
        ).fetchone()

    assert row is not None
    assert row[0] == "draft", "the stale request was applied anyway"
    assert row[1] is None and row[2] is None
    assert row[3] == created["record_version"], "record_version moved on a refused write"


def test_a_trader_cannot_cancel_another_traders_request(world: dict[str, Any]) -> None:
    """SEC-REQ-001, the ownership negative on the write path.

    A `404` rather than a `403`, so the id is not confirmed. And the row is read back:
    a guard that answered `404` after writing would be indistinguishable from one that
    refused.
    """

    client = world["client"]

    sign_in_trader(client, "other")
    theirs = open_draft(client, world["beneficiaries"]["other"]).json()["request"]

    sign_in_trader(client, "ok")
    refused = client.post(
        f"/api/v1/payment-requests/{theirs['id']}/cancel",
        json={},
        headers={**csrf(client), "If-Match": f'"rv-{theirs["record_version"]}"'},
    )
    assert refused.status_code == 404, refused.text

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        row = connection.execute(
            "SELECT status FROM payment_requests WHERE id = %s", (theirs["id"],)
        ).fetchone()
    assert row is not None and row[0] == "draft"


def test_cancelling_deletes_nothing(world: dict[str, Any]) -> None:
    """The revision survives the cancellation.

    A cancelled request is part of the trader's history and the revision is what says
    what they had asked for. Cancelling is a status change, and anything that removed
    the revision would lose the record of the intent that was abandoned.
    """

    client = world["client"]
    sign_in_trader(client, "ok")
    created = open_draft(client, world["beneficiaries"]["ok"]).json()

    client.post(
        f"/api/v1/payment-requests/{created['request']['id']}/cancel",
        json={"reason": "no longer needed"},
        headers={
            **csrf(client),
            "If-Match": f'"rv-{created["request"]["record_version"]}"',
        },
    )

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        row = connection.execute(
            "SELECT count(*) FROM payment_request_revisions WHERE id = %s",
            (created["revision"]["id"],),
        ).fetchone()
        request_row = connection.execute(
            "SELECT status, current_revision_id, cancelled_reason FROM payment_requests "
            "WHERE id = %s",
            (created["request"]["id"],),
        ).fetchone()

    assert row is not None and row[0] == 1, "the revision was removed"
    assert request_row is not None
    assert request_row[0] == "cancelled"
    assert str(request_row[1]) == created["revision"]["id"], "the pointer was cleared"
    assert request_row[2] == "no longer needed"


def test_a_non_draft_request_is_not_cancelled_here(world: dict[str, Any]) -> None:
    """The transition guard.

    Only `draft` is cancellable in this slice. Document 06 permits cancellation from
    later states through the review workflow, which is slice 7's authority — a cancel
    that reached a batched request would invalidate work downstream, so this refuses
    rather than assuming.
    """

    client = world["client"]
    sign_in_trader(client, "ok")
    created = open_draft(client, world["beneficiaries"]["ok"]).json()["request"]

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE payment_requests SET status = 'submitted_to_center' WHERE id = %s",
            (created["id"],),
        )
        connection.commit()

    refused = client.post(
        f"/api/v1/payment-requests/{created['id']}/cancel",
        json={},
        headers={**csrf(client), "If-Match": f'"rv-{created["record_version"]}"'},
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["code"] == "BUSINESS_RULE_VIOLATION"


def test_an_inactive_beneficiary_cannot_receive_a_new_request(world: dict[str, Any]) -> None:
    """`06_Workflows_and_State_Machines.md:299`.

    "New requests may use only `active` beneficiaries." A retired beneficiary stays
    readable and stays attached to the requests that already reference it; what it
    stops being is a destination for new ones.
    """

    client = world["client"]
    sign_in_trader(client, "ok")

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE beneficiaries SET status = 'inactive' WHERE id = %s",
            (world["beneficiaries"]["ok"],),
        )
        connection.commit()

    refused = open_draft(client, world["beneficiaries"]["ok"])
    assert refused.status_code == 400, refused.text


def test_each_draft_gets_its_own_request_number(world: dict[str, Any]) -> None:
    """`04_Database_Schema.md:833`, "human-readable unique".

    Two drafts, two numbers, both carrying the year and month. A number that encoded
    nothing would be one nobody could use on the phone, which is what
    "human-readable" is for.
    """

    client = world["client"]
    sign_in_trader(client, "ok")

    first = open_draft(client, world["beneficiaries"]["ok"]).json()["request"]
    second = open_draft(client, world["beneficiaries"]["ok"]).json()["request"]

    assert first["request_number"] != second["request_number"]
    assert first["request_number"].startswith("GP-")
    assert len(first["request_number"].split("-")) == 3


def test_creation_writes_its_audit_row(world: dict[str, Any]) -> None:
    """The catalogued action, read back from a separate connection.

    `payment_request.created` and `payment_request.cancelled` are both in
    `audit_outbox_catalog.yaml` — unlike the beneficiary actions, which are not
    catalogued at all. The catalogue enumerates the financial flow, and this is it.
    """

    client = world["client"]
    sign_in_trader(client, "ok")
    created = open_draft(client, world["beneficiaries"]["ok"]).json()["request"]
    client.post(
        f"/api/v1/payment-requests/{created['id']}/cancel",
        json={"reason": "done"},
        headers={**csrf(client), "If-Match": f'"rv-{created["record_version"]}"'},
    )

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        rows = connection.execute(
            "SELECT action, outcome FROM audit_logs WHERE entity_type = 'payment_request' "
            "ORDER BY occurred_at"
        ).fetchall()

    assert [row[0] for row in rows] == [
        "payment_request.created",
        "payment_request.cancelled",
    ]
    assert {row[1] for row in rows} == {"success"}
