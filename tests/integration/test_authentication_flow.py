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
# A second staff member, added in slice 10B for one reason: the session routes are
# scoped to the caller, and a single account cannot tell "scoped to me" from "not
# scoped at all". Every earlier test here has one admin, which is why the scoping was
# asserted by a classification rather than by a request.
SECOND_ADMIN_USERNAME = "manager1"
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
            "INSERT INTO admin_users (username, full_name, password_hash, status) "
            "VALUES (%s, %s, %s, 'active')",
            (SECOND_ADMIN_USERNAME, "Manager User", encoded),
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


def test_reauthenticate_issues_a_context_bound_to_the_session(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """SEC-STEP-001 and AUD-STEP-001, end to end against the real table."""

    import uuid as _uuid

    client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    token = client.cookies.get(ADMIN_CSRF_COOKIE)
    resource_id = str(_uuid.uuid4())

    response = client.post(
        "/api/v1/auth/reauthenticate",
        json={
            "password": ADMIN_PASSWORD,
            "purpose": "payment_batch_approval",
            "resource_type": "payment_batch_version",
            "resource_id": resource_id,
        },
        headers={CSRF_HEADER: token},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    reference = body["recent_auth_reference"]
    assert reference and len(reference) > 30

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        rows = connection.execute(
            "SELECT challenge_hash, purpose, resource_id, assurance_factor, consumed_at "
            "FROM recent_auth_contexts"
        ).fetchall()

    assert len(rows) == 1
    stored_hash, purpose, stored_resource, factor, consumed = rows[0]

    assert reference not in stored_hash, "the reference itself must not be stored"
    assert purpose == "payment_batch_approval"
    assert str(stored_resource) == resource_id
    assert factor == "password"
    assert consumed is None, "issuing a context must not consume it"

    # `12_Security_RBAC_Audit.md:536` — audit-linked without the secret in plaintext.
    for _event_type, _outcome, metadata in _events(migrated):
        assert reference not in str(metadata)


def test_a_wrong_password_at_step_up_does_not_lock_the_account(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """A failed step-up is not a login attempt.

    Letting it drive the lockout counter would let anyone holding a session lock
    their own account out of a command they are entitled to perform — and, worse,
    would make a mistyped password during an approval an operational incident.
    """

    import uuid as _uuid

    client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    token = client.cookies.get(ADMIN_CSRF_COOKIE)

    for _ in range(8):
        refused = client.post(
            "/api/v1/auth/reauthenticate",
            json={
                "password": "not-the-password",
                "purpose": "payment_batch_approval",
                "resource_type": "payment_batch_version",
                "resource_id": str(_uuid.uuid4()),
            },
            headers={CSRF_HEADER: token},
        )
        assert refused.status_code == 401
        assert refused.json()["error"]["code"] == "RECENT_AUTH_REQUIRED", (
            "a failed step-up must not read as an invalid session; the caller is still signed in"
        )

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        count, locked_until = connection.execute(
            "SELECT failed_login_count, locked_until FROM admin_users WHERE username = %s",
            (ADMIN_USERNAME,),
        ).fetchone()

    assert count == 0 and locked_until is None
    # And the session still works.
    assert client.get("/api/v1/auth/me").status_code == 200


def test_step_up_requires_csrf_like_any_unsafe_method(client: Any) -> None:
    """It is a POST that writes a row, so `12_Security_RBAC_Audit.md:494` applies."""

    import uuid as _uuid

    client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )

    response = client.post(
        "/api/v1/auth/reauthenticate",
        json={
            "password": ADMIN_PASSWORD,
            "purpose": "payment_batch_approval",
            "resource_type": "payment_batch_version",
            "resource_id": str(_uuid.uuid4()),
        },
    )

    assert response.status_code == 403


def test_security_events_now_record_where_the_attempt_came_from(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """The gap slice 7 closed.

    `auth_events.ip_address` and `.user_agent` exist because
    `04_Database_Schema.md:442` requires them, and the writer had no field for
    either until now — so every event written before this slice carried NULL for
    the first thing an investigator asks.
    """

    client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": ADMIN_USERNAME, "password": "wrong"},
        headers={"X-Forwarded-For": "203.0.113.7", "User-Agent": "probe/1.0"},
    )

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        rows = connection.execute(
            "SELECT ip_address, user_agent FROM auth_events ORDER BY created_at DESC LIMIT 1"
        ).fetchall()

    assert rows, "the failed login wrote no event"
    ip_address, user_agent = rows[0]
    assert str(ip_address) == "203.0.113.7", (
        "the forwarded client address was not recorded; behind nginx request.client "
        "is the proxy, so this is the only source of the real one"
    )
    assert user_agent == "probe/1.0"


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


def test_logout_revokes_and_is_idempotent(client: Any, migrated: RuntimeIdentities) -> None:
    """API-AUTH-003 and SEC-SESS-003.

    `05_API_Specification.md:802` calls logout idempotent by definition. SEC-SESS-003
    asks for two things — a revoked session fails validation, **and** the reason is
    recorded — and the second half was unasserted until slice 10 counted it. A
    `revoked_at` with no `revocation_reason` makes an incident unreconstructable:
    "this session ended" is a different fact from "the user signed out", and
    `12_Security_RBAC_Audit.md:466-477` lists eight distinct triggers.
    """

    client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    token = client.cookies.get(ADMIN_CSRF_COOKIE)

    first = client.post("/api/v1/auth/logout", headers={CSRF_HEADER: token})
    assert first.status_code == 200

    # The session is gone, so `me` no longer authenticates.
    assert client.get("/api/v1/auth/me").status_code == 401

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        rows = connection.execute(
            "SELECT revoked_at, revocation_reason FROM auth_sessions"
        ).fetchall()

    assert rows, "the login wrote no session row"
    revoked_at, reason = rows[-1]
    assert revoked_at is not None
    assert reason == "logout", (
        f"the session was revoked with reason {reason!r}. A revocation with no recorded "
        "reason cannot be told apart from the seven other triggers doc 12:468-477 lists."
    )


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


def _sign_in(client: Any, username: str) -> str:
    """Sign in as one admin and return that session's CSRF token.

    Clears the jar first, because the tests below hold two sessions alive at once and
    a leftover cookie would make the second login look like it worked when the first
    session was still the one answering.
    """

    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": username, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    token = client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token
    return token


def _own_session_id(client: Any) -> str:
    sessions = client.get("/api/v1/auth/sessions").json()["sessions"]
    assert len(sessions) == 1, sessions
    return str(sessions[0]["id"])


def test_the_session_routes_are_scoped_to_the_caller(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """SEC-IDOR-005 and SEC-IDOR-006. The DoD's first clause, for the two routes that
    were discharging it by classification.

    `listOwnSessions` and `revokeOwnSession` are ownership-scoped — one filters on
    `column == actor.actor_id` and the other refuses when `owner != actor.actor_id`
    (`app/api/v1/auth.py:726` and `:777`) — and slice 10's gate classified them
    `session-only`, a class that carries no negative obligation. So the only thing
    asserting that a caller cannot reach another caller's sessions was the label.

    `14_Testing_QA_Acceptance.md:1284` requires the refusal not to disclose whether
    the target exists, so the revoke answers a stranger's session id exactly as it
    answers a fabricated one. That is correct and it is also why this test cannot stop
    at the status code: a route that revokes *nothing* would produce the same 200.
    The two assertions that give it meaning are that the unknown id answers
    identically, and that the victim's session still works afterwards.
    """

    # The victim's CSRF token is deliberately discarded: they never make an unsafe
    # request in this test, and holding it would invite a later edit to act as them.
    _sign_in(client, SECOND_ADMIN_USERNAME)
    victim_session = _own_session_id(client)
    victim_cookie = client.cookies.get(ADMIN_COOKIE)
    assert victim_cookie

    caller_token = _sign_in(client, ADMIN_USERNAME)
    listed = {str(row["id"]) for row in client.get("/api/v1/auth/sessions").json()["sessions"]}

    assert victim_session not in listed, (
        "the session list returned another admin's session, which is an enumerable "
        "identifier for a live credential"
    )

    revoked = client.post(
        f"/api/v1/auth/sessions/{victim_session}/revoke",
        headers={CSRF_HEADER: caller_token},
    )
    fabricated = client.post(
        f"/api/v1/auth/sessions/{uuid.uuid4()}/revoke",
        headers={CSRF_HEADER: caller_token},
    )

    assert (revoked.status_code, revoked.json()) == (
        fabricated.status_code,
        fabricated.json(),
    ), (
        "revoking somebody else's session answers differently from revoking one that "
        "does not exist, so the pair of responses tells a caller which session ids are "
        "real — an existence oracle over live credentials"
    )

    # The assertion the fabricated success makes necessary. Sent as an explicit header
    # against an emptied jar so nothing but the victim's cookie can be what answers.
    client.cookies.clear()
    still_valid = client.get(
        "/api/v1/auth/me", headers={"Cookie": f"{ADMIN_COOKIE}={victim_cookie}"}
    )

    assert still_valid.status_code == 200, (
        "one admin revoked another admin's session, so the scoping is not enforced and "
        "any staff member can sign every other staff member out"
    )

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        revocations = connection.execute(
            "SELECT count(*) FROM auth_sessions WHERE revoked_at IS NOT NULL"
        ).fetchone()
    assert revocations
    assert revocations[0] == 0, (
        "something was revoked in the database even though both calls were refused"
    )


def test_revoking_your_own_session_really_revokes_it(client: Any) -> None:
    """The positive half, and the reason the test above is not vacuous.

    Because a refused revocation returns the same 200 as a successful one, "the
    victim's session still works" is also satisfied by a route that revokes nothing at
    all — a missing `commit`, an inverted condition, a handler that returns early.
    This is the assertion that separates the two, and it belongs next to the negative
    rather than in a different file: read together they say the caller's own id is the
    one thing that changes the outcome.
    """

    token = _sign_in(client, ADMIN_USERNAME)
    own = _own_session_id(client)

    revoked = client.post(f"/api/v1/auth/sessions/{own}/revoke", headers={CSRF_HEADER: token})

    assert revoked.status_code == 200, revoked.text
    assert client.get("/api/v1/auth/me").status_code == 401, (
        "the caller revoked their own session and it still authenticates, so the "
        "route reports a revocation it did not perform"
    )


NEW_PASSWORD = "a-different-correct-horse-entirely"


def test_a_password_change_ends_the_other_sessions_and_keeps_this_one(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """API-PWD-001 and SEC-STAMP-002. The first security-stamp increment in the codebase.

    Until this route existed nothing incremented `security_stamp_version`: the value was
    copied into every session at login and compared on every request, and the two could
    never differ. So `12_Security_RBAC_Audit.md:468-477`'s requirement that a credential
    change invalidate live sessions had a comparison and no producer.

    The floor is the interesting part. "The other sessions were revoked" is a statement
    about the empty set unless the caller *had* another session, so this signs in twice
    and asserts the first cookie worked **before** the change. Without that, a route that
    revokes nothing passes, and so does one that revokes everything.

    And the surviving-session assertion is an **unsafe** request on purpose. The CSRF
    token is an HMAC over the session's stored digest, which the change does not touch —
    a safe request would prove the session authenticates while saying nothing about
    whether it can still act.
    """

    # Session one. Its cookie is captured before signing in again, because `_sign_in`
    # clears the jar and the TestClient holds only one.
    _sign_in(client, ADMIN_USERNAME)
    first_cookie = client.cookies.get(ADMIN_COOKIE)
    assert first_cookie

    # Session two, the one that will do the changing.
    second_token = _sign_in(client, ADMIN_USERNAME)

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        live = connection.execute(
            "SELECT count(*) FROM auth_sessions WHERE revoked_at IS NULL"
        ).fetchone()
        stamp_before = connection.execute(
            "SELECT security_stamp_version FROM admin_users WHERE username = %s",
            (ADMIN_USERNAME,),
        ).fetchone()
    assert live and stamp_before
    assert live[0] >= 2, (
        "the caller has fewer than two live sessions, so 'the others were revoked' is a "
        "claim about nothing and this test cannot fail"
    )

    # The first session works right now. Asserted, not assumed: if it were already dead
    # the 401 below would prove nothing about the change.
    alive_before = client.get(
        "/api/v1/auth/me", headers={"Cookie": f"{ADMIN_COOKIE}={first_cookie}"}
    )
    assert alive_before.status_code == 200

    changed = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": ADMIN_PASSWORD, "new_password": NEW_PASSWORD},
        headers={CSRF_HEADER: second_token},
    )

    assert changed.status_code == 200, changed.text
    assert changed.json() == {"changed": True}
    assert NEW_PASSWORD not in changed.text, "the response echoed the new credential"

    # The other session is gone, and the row says why. Both halves: a status-based
    # refusal alone would leave `revoked_at` NULL and prove only that something else
    # rejected the request.
    after = client.get("/api/v1/auth/me", headers={"Cookie": f"{ADMIN_COOKIE}={first_cookie}"})
    assert after.status_code == 401, (
        "a session that existed before the password change still authenticates after it"
    )

    # The caller's own session still acts. An unsafe method, so the CSRF path is
    # exercised too.
    still_acting = client.post("/api/v1/auth/logout", headers={CSRF_HEADER: second_token})
    assert still_acting.status_code == 200, (
        "the caller was signed out by their own password change — the stamp was bumped "
        "on the identity and not carried forward onto the session that did it, and "
        "`classify_stamp` demands equality"
    )

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        stamp_after = connection.execute(
            "SELECT security_stamp_version FROM admin_users WHERE username = %s",
            (ADMIN_USERNAME,),
        ).fetchone()
        reasons = connection.execute(
            "SELECT DISTINCT revocation_reason FROM auth_sessions WHERE revoked_at IS NOT NULL"
        ).fetchall()
        audited = connection.execute(
            "SELECT actor_type, outcome, new_values FROM audit_logs "
            "WHERE action = 'credential.changed_own'"
        ).fetchall()
    assert stamp_after
    assert stamp_after[0] == stamp_before[0] + 1, (
        "the identity's security stamp did not move, so nothing invalidates the sessions "
        "that copied the old value"
    )
    assert "password_changed" in {reason for (reason,) in reasons}
    assert len(audited) == 1
    assert audited[0][1] == "success"
    assert audited[0][2]["security_stamp_version"] == stamp_after[0]

    # And the credential really rotated: the old one is refused, the new one works.
    client.cookies.clear()
    old = client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    assert old.status_code == 401, "the old password still signs in, so the hash was not replaced"
    fresh = client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": ADMIN_USERNAME, "password": NEW_PASSWORD},
    )
    assert fresh.status_code == 200, (
        "the new password does not sign in, so the change ended every session for nothing"
    )


def test_a_password_change_touches_only_the_callers_own_sessions(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """The ownership half, and why this route is not classified `session-only`.

    A credential change ends sessions in bulk, which is the one operation in this module
    where a wrong `WHERE` clause signs out the whole organisation. There is no id in the
    request to get wrong — which is itself worth asserting, since the guarantee rests on
    the caller's identity coming from the session rather than from the body.
    """

    _sign_in(client, SECOND_ADMIN_USERNAME)
    other_cookie = client.cookies.get(ADMIN_COOKIE)
    assert other_cookie

    token = _sign_in(client, ADMIN_USERNAME)
    changed = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": ADMIN_PASSWORD, "new_password": NEW_PASSWORD},
        headers={CSRF_HEADER: token},
    )
    assert changed.status_code == 200, changed.text

    survived = client.get("/api/v1/auth/me", headers={"Cookie": f"{ADMIN_COOKIE}={other_cookie}"})
    assert survived.status_code == 200, (
        "another administrator's session was revoked by somebody else's password change, "
        "so the bulk revoke is not scoped to the caller"
    )

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        stamps = connection.execute(
            "SELECT username, security_stamp_version FROM admin_users ORDER BY username"
        ).fetchall()
    moved = {username: version for username, version in stamps}
    assert moved[SECOND_ADMIN_USERNAME] == 1, (
        "the other administrator's security stamp moved, which would invalidate every "
        "session they hold on their next request"
    )

    # There is no field in which to name another account, and the model forbids extras —
    # so an attempt to add one is a 422 rather than a silently ignored key.
    refused = client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": NEW_PASSWORD,
            "new_password": "another-one-entirely",
            "admin_user_id": str(uuid.uuid4()),
        },
        headers={CSRF_HEADER: token},
    )
    assert refused.status_code == 422, (
        "the route accepted a field naming another account; even ignored, its presence in "
        "the contract invites a client to believe it works"
    )


def test_a_wrong_current_password_changes_nothing(client: Any, migrated: RuntimeIdentities) -> None:
    """The presence check, and the reason it is not a login.

    A signed-in caller guessing their own current password must not drive the lockout:
    anyone holding a session could otherwise lock out the account they are entitled to
    use. So this asserts the refusal, that nothing changed, and that the account is still
    usable afterwards.
    """

    token = _sign_in(client, ADMIN_USERNAME)

    refused = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "not-the-current-password", "new_password": NEW_PASSWORD},
        headers={CSRF_HEADER: token},
    )

    assert refused.status_code == 401
    assert refused.json()["error"]["code"] == "RECENT_AUTH_REQUIRED", (
        "answering UNAUTHENTICATED would send a signed-in client to fix a session that is "
        "not broken"
    )

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        row = connection.execute(
            "SELECT security_stamp_version, locked_until FROM admin_users WHERE username = %s",
            (ADMIN_USERNAME,),
        ).fetchone()
        revoked = connection.execute(
            "SELECT count(*) FROM auth_sessions WHERE revoked_at IS NOT NULL"
        ).fetchone()
        events = connection.execute(
            "SELECT event_type FROM auth_events WHERE event_type = 'password.change_refused'"
        ).fetchall()
    assert row and revoked
    assert row[0] == 1, "the stamp moved on a refused change"
    assert row[1] is None, (
        "the refusal counted towards the lockout, so anyone holding a session can lock the "
        "account out of a command it is entitled to run"
    )
    assert revoked[0] == 0, "a refused change still revoked sessions"
    assert len(events) == 1, "the refusal was not recorded, so a guessing attempt is invisible"

    # Still usable, with the original credential.
    assert client.get("/api/v1/auth/me").status_code == 200
