"""Staff account administration against a real database.

Two things here are worth reading before the tests.

**The parametrised denial is guarded.** One test name covers all four routes in the DoD
gate's ledger, which is efficient and is also how a parametrised negative quietly stops
covering a route: somebody deletes a case and the test still passes. So the
parametrisation is asserted against the route list itself.

**The idempotency assertions are the point of the create test.** Doc 05 requires the
header and `12_Security_RBAC_Audit.md` §12 requires the record to be resolved and
completed. The four trader decision routes require the header and discard it — a defect
this file must not reproduce — so a replay must return the *first* account rather than
create a second person with the same name, and a reused key with a different body must be
refused.

Covers: API-ADMIN-001, API-ADMIN-002, API-ADMIN-003.
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

# Holds `user.create`, `user.read`, `user.update`, `user.deactivate` — the only seeded
# role that does (`_0008:292-295`).
PRIVILEGED = "business_admin1"
# Holds `trader.read` and four other reads, and none of the `user.*` four. The combination
# a permission guard exists for: genuinely authenticated, genuinely unauthorised.
UNPRIVILEGED = "accountant1"

# Every route this slice adds, as (method, path template, body). The DoD gate names one
# test for all four, so this list is what makes that honest.
ADMIN_USER_ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/api/v1/admin-users", None),
    ("GET", "/api/v1/admin-users/{admin_user_id}", None),
    (
        "POST",
        "/api/v1/admin-users",
        {
            "username": "newcomer1",
            "full_name": "New Comer",
            "password": PASSWORD,
            "role_codes": ["accountant"],
        },
    ),
    ("PATCH", "/api/v1/admin-users/{admin_user_id}", {"full_name": "Renamed Person"}),
    # Slice 8E's three. Added here rather than in that slice's own file because the guard
    # below derives the expected set from the published contract, so a new route with no
    # denial case fails this file — which is exactly what it was built to do, and did.
    ("POST", "/api/v1/admin-users/{admin_user_id}/suspend", {"reason": "left the company"}),
    ("POST", "/api/v1/admin-users/{admin_user_id}/reactivate", {}),
    (
        "POST",
        "/api/v1/admin-users/{admin_user_id}/password-reset",
        {"new_password": PASSWORD, "reason": "reported a compromise"},
    ),
]


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
    """One privileged and one unprivileged staff member, both from the seeded roles.

    The grants come from migration `_0008` rather than being invented here: a test that
    granted its own permissions would prove the route reads *a* grant, not that the
    seeded catalogue actually contains one.
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
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        for username, role in ((PRIVILEGED, "business_admin"), (UNPRIVILEGED, "accountant")):
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


def _account_id(client: Any, username: str) -> str:
    """Read an id through the API, as a caller would, using a privileged session."""

    sign_in(client, PRIVILEGED)
    listed = client.get("/api/v1/admin-users")
    assert listed.status_code == 200, listed.text
    matching = [row for row in listed.json()["admin_users"] if row["username"] == username]
    assert len(matching) == 1, listed.text
    return str(matching[0]["id"])


def test_the_denial_parametrisation_covers_every_admin_user_route(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """Guard the guard. The DoD gate names one test for four routes.

    A parametrised negative that lost a case would still pass, and the gate would still
    report every route covered — so the expected set is **derived from the committed
    OpenAPI contract** rather than written here. A hand-written expectation in this file
    could be edited in the same commit as the parametrisation, which is no guard at all;
    the contract is held equal to the application by `openapi:check` and pinned operation
    by operation by `test_openapi_contract.py`, so widening it is a deliberate act
    elsewhere.
    """

    del client, migrated
    import json
    from pathlib import Path

    contract = json.loads(
        (Path(__file__).resolve().parents[2] / "services/backend/openapi/v1.json").read_text(
            encoding="utf-8"
        )
    )
    # Paths in the contract carry the `/api/v1` prefix. The first version of this filter
    # stripped it from the wrong side and matched nothing — caught by the floor below
    # rather than by silently comparing two empty sets, which is the entire reason the
    # floor is here.
    published = {
        (method.upper(), path)
        for path, operations in contract["paths"].items()
        if path.startswith("/api/v1/admin-users")
        for method in operations
        if method.lower() in {"get", "post", "patch", "put", "delete"}
    }
    assert len(published) >= 4, (
        f"the contract publishes only {len(published)} /admin-users operations, so this "
        "comparison is against almost nothing"
    )

    covered = {(method, path) for method, path, _ in ADMIN_USER_ROUTES}
    missing = sorted(published - covered)
    assert missing == [], (
        f"these published /admin-users operations have no denial case: {missing}. The DoD "
        "gate names one test for all of them, so a route missing from the parametrisation "
        "is reported covered by a case that does not exist."
    )


@pytest.mark.parametrize(("method", "template", "body"), ADMIN_USER_ROUTES)
def test_an_admin_without_the_permission_is_refused(
    client: Any, migrated: RuntimeIdentities, method: str, template: str, body: Any
) -> None:
    """The denial branch, for each of the four canonical permissions.

    Every request is otherwise valid — a real target id, a fresh `If-Match`, an
    `Idempotency-Key` — so the only thing wrong with it is the caller. That is what lets
    the negative control flip the result to 200 when a guard is deleted: omit the header
    and the mutant answers 428 instead, and the control cannot tell a missing guard from
    a present one.
    """

    del migrated
    target = _account_id(client, UNPRIVILEGED)
    version = client.get(f"/api/v1/admin-users/{target}").json()["record_version"]

    token = sign_in(client, UNPRIVILEGED)
    headers = {
        CSRF_HEADER: token,
        "If-Match": f'"rv-{version}"',
        "Idempotency-Key": str(uuid.uuid4()),
    }
    path = template.replace("{admin_user_id}", target)
    refused = client.request(method, path, json=body, headers=headers)

    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["code"] == "FORBIDDEN"

    # Which control refused it. `CsrfRequiredError` and `ForbiddenError` are byte-identical
    # by design, so without this the assertion above is also satisfied by a wrong CSRF
    # token and says nothing about the permission.
    probe = client.post("/api/v1/auth/logout", headers={CSRF_HEADER: token})
    assert probe.status_code == 200, (
        "the CSRF token this request carried was not accepted, so the 403 above is the "
        "CSRF check answering rather than the permission guard"
    )


def test_a_privileged_admin_can_list_and_read(client: Any, migrated: RuntimeIdentities) -> None:
    """The positive half. Without it, 'returns 403' is satisfied by a route that refuses
    everybody — a broken guard, a wrong path, a typo in the declared permission."""

    del migrated
    sign_in(client, PRIVILEGED)

    listed = client.get("/api/v1/admin-users")
    assert listed.status_code == 200, listed.text
    usernames = {row["username"] for row in listed.json()["admin_users"]}
    assert {PRIVILEGED, UNPRIVILEGED} <= usernames

    target = next(row for row in listed.json()["admin_users"] if row["username"] == UNPRIVILEGED)
    single = client.get(f"/api/v1/admin-users/{target['id']}")
    assert single.status_code == 200, single.text
    assert single.json()["username"] == UNPRIVILEGED
    assert single.json()["role_codes"] == ["accountant"]
    assert single.headers["ETag"] == f'"rv-{single.json()["record_version"]}"'


def test_no_admin_user_response_carries_a_credential(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """`12_Security_RBAC_Audit.md:383`. Asserted against the response text, not the model.

    A field-by-field check passes while a nested object leaks; searching the serialised
    body catches both. The stored hash is read from the database and looked for verbatim,
    so this cannot pass because the test guessed the wrong field name.
    """

    sign_in(client, PRIVILEGED)
    listed = client.get("/api/v1/admin-users")
    target = next(row for row in listed.json()["admin_users"] if row["username"] == UNPRIVILEGED)
    single = client.get(f"/api/v1/admin-users/{target['id']}")

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        stored = connection.execute(
            "SELECT password_hash FROM admin_users WHERE username = %s", (UNPRIVILEGED,)
        ).fetchone()
    assert stored and stored[0].startswith("$argon2")

    for response in (listed, single):
        assert stored[0] not in response.text, "a response carried the stored password hash"
        assert "password" not in response.text.lower()
        # The lockout counters are equally absent: they tell a reader how close an account
        # is to locking, which is a probe rather than an administrative fact.
        assert "failed_login" not in response.text
        assert "locked_until" not in response.text


def test_creating_an_account_is_idempotent_under_a_repeated_key(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """API-ADMIN-002, and the assertion the trader decision routes cannot make.

    Those four require `Idempotency-Key` and discard it, so a retry is only stopped by
    optimistic concurrency. This one claims the record, so the second identical request
    returns the first account rather than a second person with the same name — and a
    reused key with a *different* body is refused rather than silently applied.
    """

    token = sign_in(client, PRIVILEGED)
    key = str(uuid.uuid4())
    payload = {
        "username": "newcomer1",
        "full_name": "New Comer",
        "password": PASSWORD,
        "role_codes": ["accountant"],
    }

    first = client.post(
        "/api/v1/admin-users",
        json=payload,
        headers={CSRF_HEADER: token, "Idempotency-Key": key},
    )
    assert first.status_code == 200, first.text
    assert first.json()["role_codes"] == ["accountant"]

    replay = client.post(
        "/api/v1/admin-users",
        json=payload,
        headers={CSRF_HEADER: token, "Idempotency-Key": key},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == first.json()["id"], (
        "the retry created a second account, so the idempotency record is required and "
        "not used — the defect the trader decision routes have"
    )

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        count = connection.execute(
            "SELECT count(*) FROM admin_users WHERE username = 'newcomer1'"
        ).fetchone()
        completed = connection.execute(
            "SELECT count(*) FROM idempotency_records WHERE operation = 'admin_user.create'"
        ).fetchone()
    assert count and count[0] == 1
    assert completed and completed[0] == 1, "no idempotency record was written at all"

    # The same key with a different body is a different request wearing a used name.
    conflicting = client.post(
        "/api/v1/admin-users",
        json={**payload, "username": "someone-else"},
        headers={CSRF_HEADER: token, "Idempotency-Key": key},
    )
    assert conflicting.status_code == 409, conflicting.text


def test_a_creation_must_name_a_role_that_exists(client: Any, migrated: RuntimeIdentities) -> None:
    """Refused rather than filtered. An account created with an unknown role silently
    dropped would carry less authority than the caller asked for, and they would find out
    the next time that person could not do their job."""

    del migrated
    token = sign_in(client, PRIVILEGED)
    refused = client.post(
        "/api/v1/admin-users",
        json={
            "username": "newcomer2",
            "full_name": "New Comer",
            "password": PASSWORD,
            "role_codes": ["no_such_role"],
        },
        headers={CSRF_HEADER: token, "Idempotency-Key": str(uuid.uuid4())},
    )

    assert refused.status_code == 400, refused.text
    assert "no_such_role" in refused.text


def test_an_amendment_requires_a_fresh_if_match(client: Any, migrated: RuntimeIdentities) -> None:
    """Doc 05:870 requires `If-Match`. Absent is 428, stale is 412, and the distinction
    matters: the first is a client that never sent one, the second is a client whose view
    of the record is out of date."""

    target = _account_id(client, UNPRIVILEGED)
    token = sign_in(client, PRIVILEGED)

    without = client.patch(
        f"/api/v1/admin-users/{target}",
        json={"full_name": "Renamed"},
        headers={CSRF_HEADER: token},
    )
    assert without.status_code == 428, without.text

    stale = client.patch(
        f"/api/v1/admin-users/{target}",
        json={"full_name": "Renamed"},
        headers={CSRF_HEADER: token, "If-Match": '"rv-99"'},
    )
    assert stale.status_code == 412, stale.text

    current = client.get(f"/api/v1/admin-users/{target}").json()["record_version"]
    applied = client.patch(
        f"/api/v1/admin-users/{target}",
        json={"full_name": "Renamed Properly"},
        headers={CSRF_HEADER: token, "If-Match": f'"rv-{current}"'},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["full_name"] == "Renamed Properly"
    assert applied.json()["record_version"] == current + 1

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        audited = connection.execute(
            "SELECT previous_values, new_values FROM audit_logs WHERE action = 'admin_user.updated'"
        ).fetchall()
    assert len(audited) == 1
    assert audited[0][0]["full_name"] != audited[0][1]["full_name"], (
        "the audit row records the same value on both sides, so it cannot show what changed"
    )


def test_an_amendment_cannot_change_the_username_status_or_roles(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """The four fields PATCH deliberately refuses, each because it belongs to its own
    command. `extra="forbid"` makes an attempt a 422 rather than a silently ignored key —
    an ignored key is worse, because the caller believes it worked."""

    del migrated
    target = _account_id(client, UNPRIVILEGED)
    token = sign_in(client, PRIVILEGED)
    version = client.get(f"/api/v1/admin-users/{target}").json()["record_version"]
    headers = {CSRF_HEADER: token, "If-Match": f'"rv-{version}"'}

    for field, value in (
        ("username", "renamed-login"),
        ("status", "deactivated"),
        ("password", "a-new-one"),
        ("role_codes", ["business_admin"]),
    ):
        refused = client.patch(
            f"/api/v1/admin-users/{target}", json={field: value}, headers=headers
        )
        assert refused.status_code == 422, f"PATCH accepted {field}: {refused.text}"
