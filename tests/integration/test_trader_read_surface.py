"""The centre's read surface over the businesses it approves.

Until these routes existed, a staff member could approve a business only if somebody
told them its id out of band. `POST /traders/register` returns no identifier on purpose —
returning one would let a caller tell a real registration from the no-op a duplicate
produces, which is the membership oracle that endpoint exists to avoid — so the id was
reachable only through the database.

**Brought forward from M5 deliberately.** `SEC-IDOR-004` sat pending with the note
"needs an internal list endpoint", and this is that endpoint. Discharging the obligation
here rather than inheriting it silently is the point: an early endpoint that quietly
carried somebody else's pending obligation would be exactly the drift the traceability
gate exists to stop.

Covers: API-TRADER-001, SEC-IDOR-004.
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

# Holds `trader.read` and the four decisions (`_0008:285-295`).
STAFF = "business_admin1"
# Holds no `trader.*` at all. `technical_admin` is seeded without the trader family, so it
# is the caller a read guard is for: authenticated, and entitled to nothing here.
UNPRIVILEGED = "technical_admin1"


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
def client(migrated: RuntimeIdentities, tmp_path: Any) -> Iterator[Any]:
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

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        for username, role in ((STAFF, "business_admin"), (UNPRIVILEGED, "technical_admin")):
            row = connection.execute(
                "INSERT INTO admin_users (username, full_name, password_hash, status) "
                "VALUES (%s, %s, %s, 'active') RETURNING id",
                (username, username.title(), encoded),
            ).fetchone()
            assert row
            found = connection.execute("SELECT id FROM roles WHERE code = %s", (role,)).fetchone()
            assert found, f"migration 0008 should have seeded {role}"
            connection.execute(
                "INSERT INTO admin_user_roles (admin_user_id, role_id) VALUES (%s, %s)",
                (row[0], found[0]),
            )
        connection.commit()

    app = create_app(settings=settings)
    app.state.runtime = RuntimeServices.from_settings(settings)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://admin.localhost") as test_client:
        yield test_client
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def sign_in(client: Any, username: str) -> str:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    token = client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token
    return token


def register(client: Any, phone: str, name: str) -> None:
    response = client.post(
        "/api/v1/traders/register",
        json={
            "display_name": name,
            "primary_phone": phone,
            "contact_full_name": f"{name} Contact",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200, response.text


def test_the_center_can_find_a_registration_without_touching_the_database(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """API-TRADER-001. The whole reason this slice exists.

    Registration deliberately returns no identifier, so before this endpoint the only way
    to learn the id of a business awaiting approval was `psql`. This asserts the operator
    path end to end: register, list, read, approve — with the `If-Match` taken from the
    read rather than invented.
    """

    del migrated
    register(client, "09121110301", "Goldsmith One")
    register(client, "09121110302", "Goldsmith Two")

    token = sign_in(client, STAFF)
    listed = client.get("/api/v1/traders")

    assert listed.status_code == 200, listed.text
    businesses = listed.json()["traders"]
    assert len(businesses) == 2
    assert {row["display_name"] for row in businesses} == {"Goldsmith One", "Goldsmith Two"}
    assert all(row["approval_status"] == "pending_approval" for row in businesses)

    target = next(row for row in businesses if row["display_name"] == "Goldsmith One")
    single = client.get(f"/api/v1/traders/{target['id']}")
    assert single.status_code == 200, single.text
    assert single.headers["ETag"] == f'"rv-{single.json()["record_version"]}"'

    # The point of the ETag: it is what an operator's screen hands back to approve.
    approved = client.post(
        f"/api/v1/traders/{target['id']}/approve",
        json={},
        headers={
            CSRF_HEADER: token,
            "If-Match": single.headers["ETag"],
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["approval_status"] == "approved"

    # And the list reflects it, so the operator sees the result of their own action.
    after = client.get("/api/v1/traders").json()["traders"]
    assert {row["display_name"]: row["approval_status"] for row in after} == {
        "Goldsmith One": "approved",
        "Goldsmith Two": "pending_approval",
    }


def test_one_business_response_carries_no_other_business(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """SEC-IDOR-004, which has been pending since slice 6 for want of this endpoint.

    The obligation is that an admin response for one trader contains no other trader's
    data. Asserted by registering a second business with distinctive values and searching
    the serialised response for them — a field-by-field check would pass while a nested
    object leaked, and would also pass if the field names were guessed wrongly.

    **The business asked for is the one registered second, and that is not incidental.**
    The first version of this test asked for the first-registered business, and a negative
    control that made the route ignore the id entirely and return `SELECT * LIMIT 1`
    passed it: the row it wrongly returned happened to be the row that was wanted. A test
    for "the response is about the business you asked for" has to ask for one that a
    route ignoring the question would not stumble onto.
    """

    del migrated
    register(client, "09121110303", "Hidden Goldsmith")
    register(client, "09121110304", "Visible Goldsmith")

    sign_in(client, STAFF)
    businesses = client.get("/api/v1/traders").json()["traders"]
    visible = next(row for row in businesses if row["display_name"] == "Visible Goldsmith")
    hidden = next(row for row in businesses if row["display_name"] == "Hidden Goldsmith")
    assert businesses[0]["display_name"] == "Hidden Goldsmith", (
        "the ordering assumption this test depends on no longer holds: the business it "
        "asks for must not be the one a route ignoring the id would return"
    )

    single = client.get(f"/api/v1/traders/{visible['id']}")
    assert single.status_code == 200

    # The direct form of the same question, which no ordering accident can satisfy.
    assert single.json()["id"] == visible["id"], (
        "the response is about a different business than the one requested, so the route "
        "is not reading the id at all"
    )

    assert "Hidden Goldsmith" not in single.text, (
        "the response for one business carried another business's name"
    )
    assert hidden["primary_phone"] not in single.text, (
        "the response for one business carried another business's phone number"
    )
    assert str(hidden["id"]) not in single.text

    # And the positive half: it does carry the one that was asked for. Without this the
    # assertions above are satisfied by an empty response.
    assert single.json()["display_name"] == "Visible Goldsmith"
    assert single.json()["primary_phone"] == visible["primary_phone"]


def test_reading_traders_without_the_permission_is_refused(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """The denial branch for both read routes.

    `technical_admin` is seeded without any `trader.*` grant, so this is the combination a
    guard exists for: genuinely authenticated, genuinely unauthorised. Paired below with
    the privileged caller succeeding, because "returns 403" is equally satisfied by a
    route that refuses everybody.
    """

    del migrated
    register(client, "09121110305", "Goldsmith Three")

    sign_in(client, STAFF)
    target = client.get("/api/v1/traders").json()["traders"][0]["id"]

    token = sign_in(client, UNPRIVILEGED)
    for path in ("/api/v1/traders", f"/api/v1/traders/{target}"):
        refused = client.get(path)
        assert refused.status_code == 403, f"{path}: {refused.text}"
        assert refused.json()["error"]["code"] == "FORBIDDEN"

    # Which control refused it. A GET carries no CSRF requirement, so the 403 cannot be
    # the CSRF check here — but the probe is cheap and it keeps this test honest if a
    # future change makes these routes unsafe.
    probe = client.post("/api/v1/auth/logout", headers={CSRF_HEADER: token})
    assert probe.status_code == 200


def test_a_trader_cannot_reach_the_center_read_surface(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """The audience half, which is what actually protects this endpoint.

    A trader resolves no permissions at all — access on their side is ownership-scoped —
    so `requires(trader.read)` refuses them without any filter being written. That is the
    stronger arrangement: a filter can be written wrongly, and an empty permission set
    cannot.
    """

    del migrated
    register(client, "09121110306", "Goldsmith Four")

    client.cookies.clear()
    signed_in = client.post(
        "/api/v1/auth/trader/login",
        json={"identifier": "09121110306", "password": PASSWORD},
    )
    assert signed_in.status_code == 200, signed_in.text
    assert client.cookies.get(TRADER_CSRF_COOKIE)

    refused = client.get("/api/v1/traders")
    assert refused.status_code in {401, 403}, refused.text
    assert "Goldsmith Four" not in refused.text, (
        "the refusal echoed the caller's own business, which would confirm to a probing "
        "trader that the endpoint reads the table they are asking about"
    )
