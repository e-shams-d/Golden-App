"""The two reads the screens need, and the scope that makes them safe.

M5 slice 8. Until this slice the aggregate published eleven operations and exactly one of
them read — the revision history. A trader could not list their own requests and an
accountant had no queue at all, so the screens the milestone's demo depends on had nothing
to render. Document 05 defines both at `:1061` and `:1125`.

The scoping is the part worth reading. A trader's rows come from
`app/security/ownership.py`'s `scoped()`, which takes the actor and not an id, because the
mandatory IDOR case is not "validate the submitted `trader_id`" but "have no argument to
submit it to". `test_a_trader_asking_for_another_traders_id_still_gets_its_own` is that
sentence as a test.

Covers: API-REQ-002, API-REQ-003.
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

TRADERS: dict[str, str] = {"ok": "+989120000801", "other": "+989120000802"}
IBAN_ONE = "IR060120000000000000000021"
IBAN_TWO = "IR060120000000000000000022"


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
        local_storage_root=tmp_path_factory.mktemp("storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="c" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    traders = {name: uuid.uuid4() for name in TRADERS}
    beneficiaries = {"ok": uuid.uuid4(), "other": uuid.uuid4()}

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        for name, phone in TRADERS.items():
            connection.execute(
                "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
                "approval_status) VALUES (%s, %s, %s, 'active', 'approved')",
                (traders[name], f"Trader {name}", phone),
            )
            connection.execute(
                "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
                "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
                (traders[name], phone, encoded),
            )
        for key, iban, full_name in (("ok", IBAN_ONE, "Ali One"), ("other", IBAN_TWO, "Other")):
            connection.execute(
                "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
                "status, verification_status) VALUES (%s, %s, %s, %s, %s, 'active', "
                "'not_checked')",
                (beneficiaries[key], traders[key], full_name, iban, iban),
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
            "traders": traders,
            "beneficiaries": beneficiaries,
            "owner_url": migrated.owner_url,
        }
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def sign_in(client: Any, trader: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/trader/login",
        json={"identifier": TRADERS[trader], "password": PASSWORD},
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


def open_draft(world: dict[str, Any], trader: str, value: str = "500") -> Any:
    client = world["client"]
    response = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiaries"][trader]),
            "amount": {"value": value, "unit": "TOMAN"},
            "description": f"{trader} draft",
        },
        headers=csrf(client),
    )
    assert response.status_code == 201, response.text
    return response.json()


def a_request_for(world: dict[str, Any], trader: str, value: str = "500") -> str:
    sign_in(world["client"], trader)
    return str(open_draft(world, trader, value)["request"]["id"])


# --- API-REQ-002: the list, and the scope that is inferred rather than validated ----------


def test_a_traders_list_holds_only_its_own_requests(world: dict[str, Any]) -> None:
    """`API-REQ-002`, and the ownership negative for `listPaymentRequests`.

    Not "the other trader's rows are absent" by counting — the ids are compared, because a
    count passes on a list that happens to be the right length.
    """

    client = world["client"]
    mine = a_request_for(world, "ok")
    theirs = a_request_for(world, "other")

    sign_in(client, "ok")
    response = client.get("/api/v1/payment-requests")

    assert response.status_code == 200, response.text
    ids = {item["request"]["id"] for item in response.json()["items"]}
    assert mine in ids
    assert theirs not in ids
    owners = {item["request"]["trader_id"] for item in response.json()["items"]}
    assert owners == {str(world["traders"]["ok"])}


def test_a_trader_asking_for_another_traders_id_still_gets_its_own(
    world: dict[str, Any],
) -> None:
    """`API-REQ-002`. "Trader scope is always inferred" (`05_API_Specification.md:1075`).

    The mandatory IDOR case from `14_Testing_QA_Acceptance.md:1274-1284` is "trader A
    submits `trader_id` belonging to B". Neither a refusal nor B's rows: A gets A's, because
    for a trader the parameter is never read. A refusal would be an answer to a question
    they should not be able to ask — a `403` on B's id confirms B exists.
    """

    client = world["client"]
    mine = a_request_for(world, "ok")
    theirs = a_request_for(world, "other")

    sign_in(client, "ok")
    response = client.get(
        "/api/v1/payment-requests", params={"trader_id": str(world["traders"]["other"])}
    )

    assert response.status_code == 200, response.text
    ids = {item["request"]["id"] for item in response.json()["items"]}
    assert mine in ids, "the trader's own rows disappeared when they named another trader"
    assert theirs not in ids


def test_listing_needs_the_read_permission(world: dict[str, Any]) -> None:
    """The permission negative for `listPaymentRequests`. `403`, not an empty list.

    An empty list would read as "you have no requests", which is a different and false
    statement about the centre's queue.
    """

    a_request_for(world, "ok")

    sign_in_admin(world["client"], "staff_bare")
    response = world["client"].get("/api/v1/payment-requests")

    assert response.status_code == 403, response.text


def test_the_centre_sees_requests_across_traders(world: dict[str, Any]) -> None:
    """`API-REQ-002`. The queue an accountant works from, which did not exist before."""

    client = world["client"]
    mine = a_request_for(world, "ok")
    theirs = a_request_for(world, "other")

    sign_in_admin(client, "staff_granted")
    response = client.get("/api/v1/payment-requests")

    assert response.status_code == 200, response.text
    ids = {item["request"]["id"] for item in response.json()["items"]}
    assert {mine, theirs} <= ids


def test_the_centre_may_filter_by_trader(world: dict[str, Any]) -> None:
    """`API-REQ-002`. The parameter a trader's request never reaches is an internal filter."""

    client = world["client"]
    mine = a_request_for(world, "ok")
    theirs = a_request_for(world, "other")

    sign_in_admin(client, "staff_granted")
    response = client.get(
        "/api/v1/payment-requests", params={"trader_id": str(world["traders"]["ok"])}
    )

    assert response.status_code == 200, response.text
    ids = {item["request"]["id"] for item in response.json()["items"]}
    assert mine in ids
    assert theirs not in ids


def test_the_status_filter_narrows_the_queue(world: dict[str, Any]) -> None:
    """`API-REQ-002`. The filter an accountant actually opens the screen with."""

    client = world["client"]
    draft = a_request_for(world, "ok")

    submitted = a_request_for(world, "ok")
    handed = client.post(
        f"/api/v1/payment-requests/{submitted}/submit",
        json={},
        headers={**csrf(client), "If-Match": '"rv-1"'},
    )
    assert handed.status_code == 200, handed.text

    sign_in_admin(client, "staff_granted")
    response = client.get("/api/v1/payment-requests", params={"status": "submitted_to_center"})

    assert response.status_code == 200, response.text
    ids = {item["request"]["id"] for item in response.json()["items"]}
    assert submitted in ids
    assert draft not in ids, "a draft appeared in the submitted queue"


def test_the_list_carries_the_current_revision(world: dict[str, Any]) -> None:
    """`API-REQ-002`. A queue without the amount and the beneficiary cannot be triaged."""

    request_id = a_request_for(world, "ok", value="750")

    sign_in(world["client"], "ok")
    response = world["client"].get("/api/v1/payment-requests")

    assert response.status_code == 200, response.text
    row = next(
        item for item in response.json()["items"] if item["request"]["id"] == request_id
    )
    assert row["current_revision"] is not None
    assert row["current_revision"]["entered_amount"] == {"value": "750", "unit": "TOMAN"}
    assert row["current_revision"]["beneficiary_name_snapshot"] == "Ali One"


# --- API-REQ-003: one request, and what may be done to it --------------------------------


def test_another_traders_request_is_indistinguishable_from_a_missing_one(
    world: dict[str, Any],
) -> None:
    """The ownership negative for `getPaymentRequest`.

    `app/security/ownership.py` requires this: a `404`-versus-`403` difference over
    guessable identifiers is an enumeration oracle, so both answers are byte-identical.
    """

    theirs = a_request_for(world, "other")

    sign_in(world["client"], "ok")
    not_mine = world["client"].get(f"/api/v1/payment-requests/{theirs}")
    absent = world["client"].get(f"/api/v1/payment-requests/{uuid.uuid4()}")

    assert not_mine.status_code == 404, not_mine.text
    assert absent.status_code == 404
    assert not_mine.json()["error"]["code"] == absent.json()["error"]["code"]
    assert not_mine.json()["error"]["message"] == absent.json()["error"]["message"]


def test_reading_one_request_needs_the_read_permission(world: dict[str, Any]) -> None:
    """The permission negative for `getPaymentRequest`. `403` for an internal caller."""

    request_id = a_request_for(world, "ok")

    sign_in_admin(world["client"], "staff_bare")
    response = world["client"].get(f"/api/v1/payment-requests/{request_id}")

    assert response.status_code == 403, response.text


def test_the_detail_carries_a_usable_precondition(world: dict[str, Any]) -> None:
    """`API-REQ-003`. The `ETag` is where a screen gets its `If-Match`.

    Proved by using it, not by matching its shape: the read's `ETag` is sent straight back
    to a command that requires `If-Match`, and the command accepts it. A test that only
    asserted `"rv-1"` would pass on a value no route would take.
    """

    client = world["client"]
    request_id = a_request_for(world, "ok")

    detail = client.get(f"/api/v1/payment-requests/{request_id}")
    assert detail.status_code == 200, detail.text
    etag = detail.headers["ETag"]
    assert etag == f'"rv-{detail.json()["request"]["record_version"]}"'

    handed = client.post(
        f"/api/v1/payment-requests/{request_id}/submit",
        json={},
        headers={**csrf(client), "If-Match": etag},
    )
    assert handed.status_code == 200, handed.text


def test_the_detail_carries_the_current_revision(world: dict[str, Any]) -> None:
    """`API-REQ-003`. Document 05 `:1131` asks for it first."""

    request_id = a_request_for(world, "ok", value="900")

    detail = world["client"].get(f"/api/v1/payment-requests/{request_id}")

    assert detail.status_code == 200, detail.text
    revision = detail.json()["current_revision"]
    assert revision is not None
    assert revision["revision_number"] == 1
    assert revision["entered_amount"] == {"value": "900", "unit": "TOMAN"}
    assert revision["id"] == detail.json()["request"]["current_revision_id"]


def test_the_detail_offers_what_the_command_tables_permit(world: dict[str, Any]) -> None:
    """`API-REQ-003`, the wiring half.

    That the projection agrees with document 06 is checked in
    `tests/backend/test_review_transitions.py`, which needs no database. What this adds is
    that the route carries the projection through rather than computing its own answer — so
    a route that hard-coded a plausible list would fail here and pass there.
    """

    from app.commands.payment_request import allowed_actions

    client = world["client"]
    request_id = a_request_for(world, "ok")

    as_trader = client.get(f"/api/v1/payment-requests/{request_id}").json()
    assert as_trader["allowed_actions"] == list(allowed_actions("draft", by_trader=True))

    sign_in_admin(client, "staff_granted")
    as_staff = client.get(f"/api/v1/payment-requests/{request_id}").json()
    assert as_staff["allowed_actions"] == list(allowed_actions("draft", by_trader=False))


def test_a_traders_detail_offers_no_accountant_action(world: dict[str, Any]) -> None:
    """`API-REQ-003` and `SEC-REQ-003` from the read side.

    A trader session resolves no permissions, so any review action offered here would be a
    button that answers `403`. Checked on a request that is actually in review, which is the
    state where the accountant's actions are the ones available.
    """

    client = world["client"]
    request_id = a_request_for(world, "ok")

    handed = client.post(
        f"/api/v1/payment-requests/{request_id}/submit",
        json={},
        headers={**csrf(client), "If-Match": '"rv-1"'},
    )
    assert handed.status_code == 200, handed.text

    sign_in_admin(client, "staff_granted")
    started = client.post(
        f"/api/v1/payment-requests/{request_id}/start-review",
        json={},
        headers={**csrf(client), "If-Match": handed.headers["ETag"]},
    )
    assert started.status_code == 200, started.text

    sign_in(client, "ok")
    offered = client.get(f"/api/v1/payment-requests/{request_id}").json()["allowed_actions"]

    for action in (
        "payment_request.start_review",
        "payment_request.request_correction",
        "payment_request.mark_eligible",
    ):
        assert action not in offered, f"{action} was offered to the trader"
    # And under review §29.1 gives the trader no cancellation either.
    assert "payment_request.cancel" not in offered
