"""Suspension, the administrative reset, and the recovery that ends it.

Against a real database, because every claim here is about rows: a session carrying
`revoked_at` and a reason, a status that changed, a security stamp that moved, and a
credential that is nowhere in the response.

**The floor is asserted before the act, everywhere.** `API-PWD-002` says the target's
sessions are revoked; "all sessions revoked" is a statement about the empty set unless
somebody counts them first. The same trap sits under the stranding guard — "the last
administrator cannot be suspended" passes trivially in a fixture with one administrator
and no permissions at all — so these tests build the situation and check they built it.

**A credential is looked for in the headers as well as the body.** `"password" not in
body` is also true of a 500, and of a 403, and of an empty response.

Covers: API-PWD-002, SEC-ACCT-003.
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
TEMPORARY = "temporary-issued-by-an-administrator"
CHOSEN = "the-one-only-its-owner-knows"
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"
CSRF_HEADER = "X-CSRF-Token"

# Two accounts holding `business_admin`, not one. Every guard in this file is about the
# *last* administrator, so a fixture with a single one would make the guard fire on every
# act and the tests would pass without ever reaching what they mean to check.
FIRST_ADMIN = "business_admin1"
SECOND_ADMIN = "business_admin2"
ORDINARY = "accountant1"


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
        for username, role in (
            (FIRST_ADMIN, "business_admin"),
            (SECOND_ADMIN, "business_admin"),
            (ORDINARY, "accountant"),
        ):
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


def sign_in(client: Any, username: str, password: str = PASSWORD) -> str:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": username, "password": password}
    )
    assert response.status_code == 200, response.text
    token = client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token
    return token


def _account(client: Any, username: str) -> dict[str, Any]:
    listed = client.get("/api/v1/admin-users")
    assert listed.status_code == 200, listed.text
    matching = [row for row in listed.json()["admin_users"] if row["username"] == username]
    assert len(matching) == 1, listed.text
    return matching[0]


def _live_sessions(url: str, admin_user_id: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(_psycopg(url)) as connection:
        return list(
            connection.execute(
                "SELECT id, revoked_at, revocation_reason FROM auth_sessions "
                "WHERE admin_user_id = %s",
                (admin_user_id,),
            ).fetchall()
        )


def _status_and_stamp(url: str, admin_user_id: str) -> tuple[str, int]:
    with psycopg.connect(_psycopg(url)) as connection:
        row = connection.execute(
            "SELECT status, security_stamp_version FROM admin_users WHERE id = %s",
            (admin_user_id,),
        ).fetchone()
    assert row
    return str(row[0]), int(row[1])


def test_suspension_ends_the_target_s_live_sessions_with_a_reason(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """The two halves are one fact, so both are checked.

    A suspension that left sessions running would take effect at the target's next login,
    which is the one thing a suspended person has no reason to do.
    """

    sign_in(client, ORDINARY)
    sign_in(client, ORDINARY)  # a second device
    token = sign_in(client, FIRST_ADMIN)
    target = _account(client, ORDINARY)

    # THE FLOOR. Without it, "every session was revoked" is satisfied by no sessions.
    before = _live_sessions(migrated.owner_url, target["id"])
    live = [row for row in before if row[1] is None]
    assert len(live) >= 2, f"expected the target to be signed in twice, saw {before}"

    response = client.post(
        f"/api/v1/admin-users/{target['id']}/suspend",
        json={"reason": "left the company"},
        headers={"If-Match": f'"rv-{target["record_version"]}"', CSRF_HEADER: token},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "suspended"
    assert response.json()["sessions_revoked"] == len(live)

    after = _live_sessions(migrated.owner_url, target["id"])
    assert all(row[1] is not None for row in after), "a session survived the suspension"
    # And the reason, not merely the revocation: a `revoked_at` with a NULL reason leaves
    # an investigator unable to tell an administrative act from an expiry.
    assert {row[2] for row in after} == {"admin_user_suspended"}


def test_a_suspension_requires_a_reason(client: Any) -> None:
    token = sign_in(client, FIRST_ADMIN)
    target = _account(client, ORDINARY)

    response = client.post(
        f"/api/v1/admin-users/{target['id']}/suspend",
        json={"reason": "   "},
        headers={"If-Match": f'"rv-{target["record_version"]}"', CSRF_HEADER: token},
    )
    assert response.status_code == 400, response.text


def test_the_last_account_that_can_administer_staff_cannot_be_suspended(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """The guard nobody had written: one administrator can strand the deployment.

    `business_admin` is the only seeded role holding `user.*`, and the bootstrap command
    refuses once any staff account exists — so the recovery from this would be editing the
    database by hand.
    """

    token = sign_in(client, FIRST_ADMIN)
    second = _account(client, SECOND_ADMIN)

    # Suspending the second administrator is allowed: one remains.
    first = client.post(
        f"/api/v1/admin-users/{second['id']}/suspend",
        json={"reason": "on extended leave"},
        headers={"If-Match": f'"rv-{second["record_version"]}"', CSRF_HEADER: token},
    )
    assert first.status_code == 200, first.text

    # THE FLOOR, and it is the one that matters here. If the fixture granted nobody
    # `user.*`, the count would be zero, the guard would fire on the first call, and the
    # assertion below would pass while proving the opposite of what it claims.
    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        remaining = connection.execute(
            "SELECT count(DISTINCT au.id) FROM admin_users au "
            "JOIN admin_user_roles aur ON aur.admin_user_id = au.id AND aur.revoked_at IS NULL "
            "JOIN role_permissions rp ON rp.role_id = aur.role_id "
            "JOIN permissions p ON p.id = rp.permission_id "
            "WHERE au.status = 'active' AND p.code IN "
            "('user.read','user.create','user.update','user.deactivate')"
        ).fetchone()
    assert remaining and remaining[0] == 1, (
        f"expected exactly one active administrator to remain, saw {remaining}"
    )

    token = sign_in(client, FIRST_ADMIN)
    myself = _account(client, FIRST_ADMIN)
    refused = client.post(
        f"/api/v1/admin-users/{myself['id']}/suspend",
        json={"reason": "also leaving"},
        headers={"If-Match": f'"rv-{myself["record_version"]}"', CSRF_HEADER: token},
    )
    assert refused.status_code == 400, refused.text
    assert "last active account" in refused.json()["error"]["message"]


def test_reactivation_returns_a_suspended_account_and_refuses_the_other_states(
    client: Any,
) -> None:
    token = sign_in(client, FIRST_ADMIN)
    target = _account(client, ORDINARY)

    suspended = client.post(
        f"/api/v1/admin-users/{target['id']}/suspend",
        json={"reason": "under investigation"},
        headers={"If-Match": f'"rv-{target["record_version"]}"', CSRF_HEADER: token},
    )
    assert suspended.status_code == 200, suspended.text

    version = suspended.json()["record_version"]
    restored = client.post(
        f"/api/v1/admin-users/{target['id']}/reactivate",
        json={},
        headers={"If-Match": f'"rv-{version}"', CSRF_HEADER: token},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "active"

    # An already-active account is refused, so reactivation cannot be used to consume a
    # record version and make somebody else's If-Match stale.
    again = client.post(
        f"/api/v1/admin-users/{target['id']}/reactivate",
        json={},
        headers={"If-Match": f'"rv-{restored.json()["record_version"]}"', CSRF_HEADER: token},
    )
    assert again.status_code == 400, again.text


def test_the_reset_returns_no_credential_and_revokes_every_session(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """API-PWD-002, with both halves and the floor under each.

    A status-based refusal alone would leave `revoked_at` NULL and merely re-prove the
    account-state check that already exists, so the sessions are counted before and their
    reason is asserted after.
    """

    sign_in(client, ORDINARY)
    sign_in(client, ORDINARY)
    token = sign_in(client, FIRST_ADMIN)
    target = _account(client, ORDINARY)

    before = [row for row in _live_sessions(migrated.owner_url, target["id"]) if row[1] is None]
    assert len(before) >= 2, f"expected the target to be signed in twice, saw {before}"
    _, stamp_before = _status_and_stamp(migrated.owner_url, target["id"])

    response = client.post(
        f"/api/v1/admin-users/{target['id']}/password-reset",
        json={"new_password": TEMPORARY, "reason": "reported a compromise"},
        headers={"If-Match": f'"rv-{target["record_version"]}"', CSRF_HEADER: token},
    )
    assert response.status_code == 200, response.text

    # No credential in the body **or** the headers. The header half matters: a 500 also
    # has no password in its body, and so does a 403.
    body = response.text
    for secret in (TEMPORARY, "password_hash", "$argon2"):
        assert secret not in body, f"the response body carries {secret!r}"
    joined_headers = "\n".join(f"{name}: {value}" for name, value in response.headers.items())
    assert TEMPORARY not in joined_headers
    assert set(response.json()) == {"id", "status", "record_version", "sessions_revoked"}

    status, stamp_after = _status_and_stamp(migrated.owner_url, target["id"])
    assert status == "recovery_required"
    assert stamp_after == stamp_before + 1

    after = _live_sessions(migrated.owner_url, target["id"])
    assert all(row[1] is not None for row in after)
    assert {row[2] for row in after} == {"password_reset_by_administrator"}


def test_an_administrator_cannot_reset_their_own_credential(client: Any) -> None:
    """Self-reset plus `recovery_required` plus a password nobody told them is a lockout."""

    token = sign_in(client, FIRST_ADMIN)
    myself = _account(client, FIRST_ADMIN)

    response = client.post(
        f"/api/v1/admin-users/{myself['id']}/password-reset",
        json={"new_password": TEMPORARY, "reason": "rotating"},
        headers={"If-Match": f'"rv-{myself["record_version"]}"', CSRF_HEADER: token},
    )
    assert response.status_code == 400, response.text
    assert "change-password" in response.json()["error"]["message"]


def test_a_reset_account_cannot_sign_in_and_then_recovers(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """SEC-ACCT-003, from a request rather than from a pure-function call.

    The obligation is discharged today by a unit test in a file whose own docstring says
    "No database and no Redis server", which proves the state machine's table and not that
    any route consults it. This drives the whole path: reset, refused login, recovery,
    successful login.
    """

    token = sign_in(client, FIRST_ADMIN)
    target = _account(client, ORDINARY)
    client.post(
        f"/api/v1/admin-users/{target['id']}/password-reset",
        json={"new_password": TEMPORARY, "reason": "reported a compromise"},
        headers={"If-Match": f'"rv-{target["record_version"]}"', CSRF_HEADER: token},
    )

    client.cookies.clear()
    refused = client.post(
        "/api/v1/auth/admin/login", json={"identifier": ORDINARY, "password": TEMPORARY}
    )
    assert refused.status_code == 401, refused.text

    recovered = client.post(
        "/api/v1/auth/admin/recover-password",
        json={
            "username": ORDINARY,
            "current_password": TEMPORARY,
            "new_password": CHOSEN,
        },
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json() == {"recovered": True}
    # No session is issued: the temporary credential must not become access on its own.
    assert not [name for name in recovered.cookies if "session" in name]

    status, _ = _status_and_stamp(migrated.owner_url, target["id"])
    assert status == "active"

    # And the chosen credential works while the temporary one no longer does.
    assert (
        client.post(
            "/api/v1/auth/admin/login", json={"identifier": ORDINARY, "password": TEMPORARY}
        ).status_code
        == 401
    )
    sign_in(client, ORDINARY, CHOSEN)


def test_recovery_is_refused_for_an_account_that_is_not_awaiting_it(client: Any) -> None:
    """An active account has nothing to recover from.

    Permitting it would let anybody holding a working password drive their own account
    into a state only an administrator can create — and the refusal is the same
    `UNAUTHENTICATED` as a wrong password, so the route says nothing about which accounts
    have been reset.
    """

    response = client.post(
        "/api/v1/auth/admin/recover-password",
        json={"username": ORDINARY, "current_password": PASSWORD, "new_password": CHOSEN},
    )
    assert response.status_code == 401, response.text

    unknown = client.post(
        "/api/v1/auth/admin/recover-password",
        json={
            "username": f"nobody-{uuid.uuid4().hex[:8]}",
            "current_password": PASSWORD,
            "new_password": CHOSEN,
        },
    )
    assert unknown.status_code == 401
    # Indistinguishable, which is the claim. A different code or message for the two would
    # make this route a membership oracle for the centre's own staff.
    assert unknown.json()["error"]["code"] == response.json()["error"]["code"]
