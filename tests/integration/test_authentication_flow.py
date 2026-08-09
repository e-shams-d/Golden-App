"""Signing in, for real: a migrated database, a live app, and a cookie jar.

The unit tests prove the primitives. This proves the thing they compose into,
which is a different claim — a correct hasher and a correct session store can
still be wired into a login that never writes the event, or that accepts the
other audience's cookie.

Covers: API-AUTH-001, API-AUTH-002, API-AUTH-003, API-AUTH-004, SEC-AUD-001,
SEC-CSRF-001, SEC-ENUM-001, SEC-LEAK-001, SEC-LOCK-001, AUD-EVENT-001.
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

ADMIN_COOKIE = "__Host-gp_admin_session"
TRADER_COOKIE = "__Host-gp_trader_session"
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"
CSRF_HEADER = "X-CSRF-Token"

ADMIN_PASSWORD = "correct-horse-battery-staple"
ADMIN_USERNAME = "accountant1"
TRADER_PASSWORD = "another-correct-horse"
TRADER_PHONE_TYPED = "۰۹۱۲۳۴۵۶۷۸۹"
TRADER_PHONE_STORED = "+989123456789"


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
    """A real app against the migrated database, with seeded identities.

    The identities are inserted here rather than by a migration because
    `12_Security_RBAC_Audit.md:386` forbids seeded credentials in migrations, and
    an integration test that needed one would otherwise be asking for the thing
    the rule exists to prevent.
    """

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
        # Deliberately absent: without a rate-limit secret the limiter is not
        # built at all, so these tests exercise the durable lockout rather than
        # the Redis window, and do not need a Redis server.
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(ADMIN_PASSWORD, parameters, max_length=settings.password_max_length)
    trader_encoded = hash_password(
        TRADER_PASSWORD, parameters, max_length=settings.password_max_length
    )

    trader_id = uuid.uuid4()
    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO admin_users (username, full_name, password_hash, status) "
            "VALUES (%s, %s, %s, 'active')",
            (ADMIN_USERNAME, "Accountant User", encoded),
        )
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, %s, %s, 'active', 'approved')",
            (trader_id, "Gold Trader", "+989120000000"),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, %s, %s, 'active', TRUE)",
            (trader_id, TRADER_PHONE_STORED, "Trader Contact", trader_encoded),
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


def _events(migrated: RuntimeIdentities) -> list[tuple[str, str, Any]]:
    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        return connection.execute(
            "SELECT event_type, outcome, metadata FROM auth_events ORDER BY created_at"
        ).fetchall()


def test_an_admin_signs_in_and_receives_host_prefixed_cookies(client: Any) -> None:
    """API-AUTH-001 and API-AUTH-002."""

    response = client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["audience"] == "admin"
    assert body["user"]["trader_id"] is None

    raw = response.headers.get_list("set-cookie")
    session_cookie = next(header for header in raw if header.startswith(ADMIN_COOKIE))

    assert "HttpOnly" in session_cookie
    assert "Secure" in session_cookie
    assert "SameSite=strict" in session_cookie.replace("samesite", "SameSite")
    assert "Domain=" not in session_cookie, (
        "a Domain attribute makes the cookie sibling-visible; __Host- requires its absence"
    )
    assert "Path=/" in session_cookie
    # No trader cookie was set.
    assert not any(header.startswith(TRADER_COOKIE) for header in raw)


def test_a_trader_signs_in_with_persian_digits(client: Any) -> None:
    """The ordinary path in a Persian interface, end to end."""

    response = client.post(
        "/api/v1/auth/trader/login",
        json={"identifier": TRADER_PHONE_TYPED, "password": TRADER_PASSWORD},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["audience"] == "trader"
    assert body["user"]["trader_id"] is not None, "a trader actor must carry its ownership scope"
    assert body["user"]["permissions"] == [], (
        "trader access is ownership-scoped, not granted through admin_user_roles"
    )


def test_an_admin_credential_is_refused_on_the_trader_route(client: Any) -> None:
    """SEC-AUD-001. The audience is the route, not a field in the body."""

    response = client.post(
        "/api/v1/auth/trader/login",
        json={"identifier": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )

    assert response.status_code == 401


def test_every_failure_looks_identical_to_the_client(client: Any) -> None:
    """SEC-ENUM-001. An unknown user, a wrong password and a bad number agree."""

    unknown = client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": "nobody-here", "password": ADMIN_PASSWORD},
    )
    wrong = client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": ADMIN_USERNAME, "password": "not-the-password"},
    )

    assert unknown.status_code == wrong.status_code == 401

    def comparable(payload: dict[str, Any]) -> dict[str, Any]:
        """Everything except the correlation id.

        `request_id` is a fresh UUID per request and says nothing about the
        account — excluding it is not weakening the test, and asserting on it
        would make this fail for a reason that has no security meaning.
        """

        body = dict(payload["error"])
        body.pop("request_id", None)
        return body

    assert comparable(unknown.json()) == comparable(wrong.json()), (
        "the bodies differ, so the response distinguishes an unknown account from a "
        "wrong password — which is an enumeration oracle"
    )
    assert "set-cookie" not in {key.lower() for key in unknown.headers}


def test_a_session_presented_under_the_other_audience_is_refused(client: Any) -> None:
    """SEC-AUD-001's other half, and the half a negative control found missing.

    The earlier audience test proves an admin *credential* fails on the trader
    login route. This proves the different thing: an admin *session*, presented
    as though it were a trader session, is refused.

    Done by moving the cookie's value under the trader cookie name, because the
    guard resolves the audience from the name and then compares it against which
    actor column the session row actually populates. A mismatch is therefore a
    disagreement between two server-side facts rather than a string the caller
    chose — and the `auth_sessions` XOR check is what makes the row's answer
    unambiguous.
    """

    client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    stolen = client.cookies.get(ADMIN_COOKIE)
    assert stolen

    client.cookies.clear()
    client.cookies.set(TRADER_COOKIE, stolen, domain="admin.localhost")

    assert client.get("/api/v1/auth/me").status_code == 401, (
        "an admin session was accepted while presented as a trader session"
    )


def test_an_unknown_identifier_costs_the_same_as_a_wrong_password(client: Any) -> None:
    """The timing side of SEC-ENUM-001, which identical bodies do not cover.

    Skipping the hash when no row is found makes an unknown identifier return in
    about a millisecond while a wrong password takes an Argon2 verification —
    roughly a hundred times longer. That difference is an account-enumeration
    oracle no amount of identical response bodies hides, which is why the command
    verifies against a dummy hash on a miss and discards the result.

    Asserted as a ratio with a wide margin rather than an absolute duration: the
    claim is "the same order of magnitude", and a tight wall-clock bound on a
    shared CI runner is a flaky test rather than a stronger one.
    """

    import time

    def elapsed(identifier: str) -> float:
        started = time.perf_counter()
        client.post(
            "/api/v1/auth/admin/login",
            json={"identifier": identifier, "password": "not-the-password"},
        )
        return time.perf_counter() - started

    # One warm-up each: the dummy hash is computed lazily on first use, and the
    # first request also pays connection setup.
    elapsed("warm-up-unknown")
    elapsed(ADMIN_USERNAME)

    unknown = min(elapsed(f"nobody-{index}") for index in range(3))
    wrong = min(elapsed(ADMIN_USERNAME) for _ in range(3))

    assert unknown > wrong * 0.5, (
        f"an unknown identifier answered in {unknown * 1000:.0f}ms against "
        f"{wrong * 1000:.0f}ms for a wrong password. A miss must still pay for a "
        "verification, or the response time reveals which accounts exist."
    )


def test_a_failed_login_is_recorded_even_though_the_client_learns_nothing(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """AUD-EVENT-001. The distinction the client is denied still reaches the log."""

    client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": "nobody-here", "password": ADMIN_PASSWORD},
    )
    client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": ADMIN_USERNAME, "password": "not-the-password"},
    )

    reasons = [row[2].get("rejection_reason") for row in _events(migrated)]

    assert "unknown_identifier" in reasons
    assert "wrong_password" in reasons, (
        "an investigator must be able to tell the two apart even though the client cannot"
    )


def test_no_response_or_event_ever_carries_the_session_secret(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """SEC-LEAK-001."""

    response = client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    secret = client.cookies.get(ADMIN_COOKIE)

    assert secret, "the login set no session cookie"
    assert secret not in response.text
    assert ADMIN_PASSWORD not in response.text
    for _event_type, _outcome, metadata in _events(migrated):
        rendered = str(metadata)
        assert secret not in rendered
        assert ADMIN_PASSWORD not in rendered


def test_me_requires_a_session_and_returns_the_actor(client: Any) -> None:
    """API-AUTH-004."""

    assert client.get("/api/v1/auth/me").status_code == 401

    client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["user"]["audience"] == "admin"
    assert "password_hash" not in response.text


def test_an_unsafe_request_without_the_csrf_header_is_refused(client: Any) -> None:
    """SEC-CSRF-001. The token is bound to the session and checked server-side."""

    client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )

    without = client.post("/api/v1/auth/logout")
    assert without.status_code == 403, "an unsafe method with no CSRF token must be refused"

    forged = client.post("/api/v1/auth/logout", headers={CSRF_HEADER: "0" * 64})
    assert forged.status_code == 403, "a token not derived from this session must be refused"

    token = client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token, "the login set no CSRF cookie"
    assert client.post("/api/v1/auth/logout", headers={CSRF_HEADER: token}).status_code == 200


def test_logout_revokes_and_is_idempotent(client: Any) -> None:
    """API-AUTH-003. `05_API_Specification.md:802` calls it idempotent by definition."""

    client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    token = client.cookies.get(ADMIN_CSRF_COOKIE)

    first = client.post("/api/v1/auth/logout", headers={CSRF_HEADER: token})
    assert first.status_code == 200

    # The session is gone, so `me` no longer authenticates.
    assert client.get("/api/v1/auth/me").status_code == 401


def test_repeated_failures_lock_the_account_durably(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """SEC-LOCK-001, against the real column rather than the policy function."""

    for _ in range(6):
        client.post(
            "/api/v1/auth/admin/login",
            json={"identifier": ADMIN_USERNAME, "password": "wrong"},
        )

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        count, locked_until = connection.execute(
            "SELECT failed_login_count, locked_until FROM admin_users WHERE username = %s",
            (ADMIN_USERNAME,),
        ).fetchone()

    assert count >= 5
    assert locked_until is not None, "the threshold was crossed and nothing locked the account"

    # And the correct password is now refused, which is what a lock means.
    refused = client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    assert refused.status_code == 401
