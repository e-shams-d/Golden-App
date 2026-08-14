"""Role permission changes: the step-up binding, and the alert doc 12:642 requires.

Two claims, and the second is the one that could not have been proved anywhere else.

**The step-up binding, exercised by a request for the first time.**
`app/security/step_up.py` has been complete since slice 7 and `rejection_for` had zero
production call sites, so six obligations were green against a mechanism no route
consumed. Here a context is obtained for one role and presented against another, and the
change is refused.

**The alert, on a surface where all four capabilities can actually be granted.** Three of
the four permissions `:642` names — `payment_batch_version.approve`, `audit.export`,
`retention.approve` — are granted to **no** seeded role. A design that hung this obligation
on role *assignment* could therefore never have exercised more than one of them. The
permission-set diff on this route is the only surface where all four appear.

The tests say a **row exists**. Nothing here proves anybody was notified, and no claim to
that effect is made: delivery is a channel this milestone does not build, and a test named
for it would be the most comfortable kind of false green.

Covers: AUD-ROLE-001, SEC-ROLECHANGE-001, API-ROLE-001.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery-staple"
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"
CSRF_HEADER = "X-CSRF-Token"

# Holds `role.manage` and `role.read` (`permission_catalog.yaml:283-285`).
PRIVILEGED = "business_admin1"
# Holds `role.read` through `manager`, and not `role.manage`. Genuinely authenticated,
# genuinely unauthorised for the write — the combination a permission guard exists for.
READER = "manager1"
# Holds neither. `permission_catalog.yaml:281` grants `role.read` to manager,
# business_admin and read_only_auditor, and `accountant` is not among them — so this is
# the caller the *read* routes must refuse. Chosen from the seeded catalogue rather than
# invented, so the denial proves the seed withholds the permission and not that a fixture
# forgot to grant it.
OUTSIDER = "accountant1"

# Every route this slice adds under /roles, as (method, path template, body). The denial
# below is parametrised over it, so this list is what makes one test name honest for three
# routes — and it is checked against the published contract, because a parametrised
# negative that lost a case would still pass.
ROLE_ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/api/v1/roles", None),
    ("GET", "/api/v1/roles/{role_id}", None),
    (
        "PUT",
        "/api/v1/roles/{role_id}/permissions",
        {"permission_codes": [], "reason": "should be denied"},
    ),
]

STEP_UP_PURPOSE = "role.permissions.update"

# One case per capability `12_Security_RBAC_Audit.md:642` requires an alert for, paired
# with the words the document uses. A module-level constant rather than a literal inside
# the decorator, because the guard below compares it against the mapping under test — and
# a list that exists only inside `@parametrize` cannot be compared to anything.
ALERT_CASES: list[tuple[str, str]] = [
    ("payment_batch_version.approve", "manager approval"),
    ("role.manage", "role management"),
    ("audit.export", "audit export"),
    ("retention.approve", "retention approval"),
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
            (PRIVILEGED, "business_admin"),
            (READER, "manager"),
            (OUTSIDER, "accountant"),
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


def sign_in(client: Any, username: str) -> str:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    token = client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token
    return token


def _role(client: Any, code: str) -> dict[str, Any]:
    listed = client.get("/api/v1/roles")
    assert listed.status_code == 200, listed.text
    matching = [row for row in listed.json()["roles"] if row["code"] == code]
    assert len(matching) == 1, listed.text
    return matching[0]


def _read_role(client: Any, role_id: str) -> tuple[dict[str, Any], str]:
    """The role and the ETag the update must echo."""

    response = client.get(f"/api/v1/roles/{role_id}")
    assert response.status_code == 200, response.text
    etag = response.headers.get("etag")
    assert etag, "the single-role read must publish an ETag or the update is unusable"
    return response.json(), etag


def _step_up(client: Any, token: str, role_id: str) -> str:
    response = client.post(
        "/api/v1/auth/reauthenticate",
        json={
            "password": PASSWORD,
            "purpose": STEP_UP_PURPOSE,
            "resource_type": "role",
            "resource_id": role_id,
        },
        headers={CSRF_HEADER: token},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["recent_auth_reference"])


def _alerts(url: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(_psycopg(url)) as connection:
        return list(
            connection.execute(
                "SELECT event_type, event_class, outcome, metadata FROM auth_events "
                "WHERE event_type = 'role.high_risk_permission_granted' ORDER BY created_at"
            ).fetchall()
        )


def test_an_ordinary_grant_writes_no_alert_row(client: Any, migrated: RuntimeIdentities) -> None:
    """Without this half, the alert test passes on the generic row every command writes.

    `trader.read` is held by four seeded roles and granted constantly. If it produced an
    alert, the stream would be noise and the grant that mattered would arrive inside it.
    """

    token = sign_in(client, PRIVILEGED)
    role = _role(client, "accountant")
    _, etag = _read_role(client, role["id"])

    assert _alerts(migrated.owner_url) == []

    reference = _step_up(client, token, role["id"])
    response = client.put(
        f"/api/v1/roles/{role['id']}/permissions",
        json={
            "permission_codes": [*role["permission_codes"], "trader.create"],
            "reason": "the accountant now onboards businesses",
        },
        headers={"If-Match": etag, "X-Recent-Auth": reference, CSRF_HEADER: token},
    )
    assert response.status_code == 200, response.text
    assert "trader.create" in response.json()["permission_codes"]

    assert _alerts(migrated.owner_url) == [], (
        "an ordinary permission produced a high-risk alert, which would make every alert "
        "in this table noise"
    )


@pytest.mark.parametrize(("code", "capability"), ALERT_CASES)
def test_granting_a_high_risk_permission_writes_an_alert_row(
    client: Any, migrated: RuntimeIdentities, code: str, capability: str
) -> None:
    """A row exists. Nothing here claims anybody was notified.

    Three of these four are granted to no seeded role at all, which is why the
    permission-set diff is the only surface that can exercise them — role *assignment*
    could never reach more than one.
    """

    token = sign_in(client, PRIVILEGED)
    role = _role(client, "accountant")
    _, etag = _read_role(client, role["id"])

    # THE FLOOR. An empty table before means the assertion after is about this request.
    assert _alerts(migrated.owner_url) == []

    reference = _step_up(client, token, role["id"])
    response = client.put(
        f"/api/v1/roles/{role['id']}/permissions",
        json={
            "permission_codes": [*role["permission_codes"], code],
            "reason": f"granting {code} for a documented reason",
        },
        headers={"If-Match": etag, "X-Recent-Auth": reference, CSRF_HEADER: token},
    )
    assert response.status_code == 200, response.text

    rows = _alerts(migrated.owner_url)
    assert len(rows) == 1, f"expected exactly one alert for {code}, saw {rows}"
    event_type, event_class, outcome, metadata = rows[0]
    assert event_class == "administrative"
    # `success`, not a failure: the grant succeeded. Recorded as a failure it would land
    # in `idx_auth_events_failures` and make every high-risk grant look like an incident.
    assert outcome == "success"
    assert metadata["permission_code"] == code
    # The capability in the document's own words, so the reader does not have to redo the
    # derivation at the worst possible moment.
    assert metadata["capability"] == capability
    assert metadata["role_code"] == "accountant"


def test_the_parametrisation_covers_every_alertable_capability() -> None:
    """Guard the guard: a loop that silently shrinks is this test's failure mode.

    The expected set comes from the module under test rather than being restated here, so
    a capability added to the mapping and not to the parametrisation fails immediately.
    """

    from app.security import high_risk_grants

    assert {code for code, _ in ALERT_CASES} == high_risk_grants.alertable_codes(), (
        "the alertable codes and the cases above have diverged; a capability that is "
        "mapped but not exercised is one nothing proves alerts"
    )


def test_granting_break_glass_is_refused_rather_than_alerted(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """POL-005 disables it for Phase 1A "with no endpoint, grant, feature flag...".

    Doc 12:642 lists break-glass among the capabilities to alert on. Alerting while
    permitting would be the weaker of the two readings — the alert would be the only trace
    of a capability the approved policy says cannot exist.
    """

    token = sign_in(client, PRIVILEGED)
    role = _role(client, "accountant")
    _, etag = _read_role(client, role["id"])
    reference = _step_up(client, token, role["id"])

    response = client.put(
        f"/api/v1/roles/{role['id']}/permissions",
        json={
            "permission_codes": [*role["permission_codes"], "break_glass.activate"],
            "reason": "an incident",
        },
        headers={"If-Match": etag, "X-Recent-Auth": reference, CSRF_HEADER: token},
    )
    assert response.status_code == 400, response.text
    # The catalogue's own token, `disabled_by_approved_POL_005`, rather than the prose
    # spelling `POL-005`: the refusal quotes the artifact that justifies it, so pinning
    # the artifact's string is what would fail if the justification were paraphrased away.
    assert "disabled_by_approved_POL_005" in response.json()["error"]["message"]

    # Refused, so nothing was granted and no alert was written for it either.
    assert _alerts(migrated.owner_url) == []
    fresh, _ = _read_role(client, role["id"])
    assert "break_glass.activate" not in fresh["permission_codes"]


def test_a_step_up_for_one_role_does_not_authorise_another(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """The binding the whole step-up design exists for, in the shape this route has.

    A context obtained to edit `accountant` and presented against `manager` is
    `WRONG_RESOURCE`. The client is told one thing; the reason goes to `auth_events`.
    """

    token = sign_in(client, PRIVILEGED)
    accountant = _role(client, "accountant")
    manager = _role(client, "manager")
    _, manager_etag = _read_role(client, manager["id"])

    # Issued for the accountant role, deliberately.
    reference = _step_up(client, token, accountant["id"])

    response = client.put(
        f"/api/v1/roles/{manager['id']}/permissions",
        json={
            "permission_codes": [*manager["permission_codes"], "trader.create"],
            "reason": "should not be applied",
        },
        headers={"If-Match": manager_etag, "X-Recent-Auth": reference, CSRF_HEADER: token},
    )
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "RECENT_AUTH_REQUIRED"

    # Nothing changed.
    fresh, _ = _read_role(client, manager["id"])
    assert sorted(fresh["permission_codes"]) == sorted(manager["permission_codes"])

    # And the refusal was recorded with its reason, which the client was never told.
    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        rows = connection.execute(
            "SELECT metadata FROM auth_events WHERE event_type = 'step_up.rejected'"
        ).fetchall()
    assert len(rows) == 1, f"expected the refusal to be recorded, saw {rows}"
    assert rows[0][0]["rejection_reason"] == "wrong_resource"


def test_a_context_cannot_be_spent_twice(client: Any) -> None:
    """Consumption is why no `Idempotency-Key` is required here.

    A retried request cannot re-apply the change: the second attempt is refused before it
    reaches the write.
    """

    token = sign_in(client, PRIVILEGED)
    role = _role(client, "accountant")
    _, etag = _read_role(client, role["id"])
    reference = _step_up(client, token, role["id"])

    body = {
        "permission_codes": [*role["permission_codes"], "trader.create"],
        "reason": "onboarding duties",
    }
    headers = {"If-Match": etag, "X-Recent-Auth": reference, CSRF_HEADER: token}

    assert client.put(f"/api/v1/roles/{role['id']}/permissions", json=body, headers=headers).status_code == 200

    # Same reference, and the ETag is now stale too — so this asserts the *step-up* is
    # refused by reading the code, not merely that something failed.
    _, fresh_etag = _read_role(client, role["id"])
    replay = client.put(
        f"/api/v1/roles/{role['id']}/permissions",
        json=body,
        headers={"If-Match": fresh_etag, "X-Recent-Auth": reference, CSRF_HEADER: token},
    )
    assert replay.status_code == 401, replay.text
    assert replay.json()["error"]["code"] == "RECENT_AUTH_REQUIRED"


def test_a_stale_if_match_is_refused(client: Any) -> None:
    """The digest is a content ETag because `roles` has no `record_version` column."""

    token = sign_in(client, PRIVILEGED)
    role = _role(client, "accountant")
    _, etag = _read_role(client, role["id"])

    first_reference = _step_up(client, token, role["id"])
    assert (
        client.put(
            f"/api/v1/roles/{role['id']}/permissions",
            json={
                "permission_codes": [*role["permission_codes"], "trader.create"],
                "reason": "first writer",
            },
            headers={"If-Match": etag, "X-Recent-Auth": first_reference, CSRF_HEADER: token},
        ).status_code
        == 200
    )

    second_reference = _step_up(client, token, role["id"])
    stale = client.put(
        f"/api/v1/roles/{role['id']}/permissions",
        json={
            "permission_codes": [*role["permission_codes"], "trader.suspend"],
            "reason": "second writer, holding the old view",
        },
        headers={"If-Match": etag, "X-Recent-Auth": second_reference, CSRF_HEADER: token},
    )
    assert stale.status_code == 412, stale.text


def test_both_preconditions_are_required_and_are_distinguished(client: Any) -> None:
    """428 for a missing precondition, 401 for one that does not authorise.

    The difference tells a client whether to obtain a context or to obtain a different one.
    """

    token = sign_in(client, PRIVILEGED)
    role = _role(client, "accountant")
    _, etag = _read_role(client, role["id"])
    body = {"permission_codes": role["permission_codes"], "reason": "no change"}

    no_etag = client.put(
        f"/api/v1/roles/{role['id']}/permissions",
        json=body,
        headers={"X-Recent-Auth": "irrelevant", CSRF_HEADER: token},
    )
    assert no_etag.status_code == 428, no_etag.text

    no_step_up = client.put(
        f"/api/v1/roles/{role['id']}/permissions",
        json=body,
        headers={"If-Match": etag, CSRF_HEADER: token},
    )
    assert no_step_up.status_code == 428, no_step_up.text

    bad_step_up = client.put(
        f"/api/v1/roles/{role['id']}/permissions",
        json=body,
        headers={"If-Match": etag, "X-Recent-Auth": "not-a-reference", CSRF_HEADER: token},
    )
    assert bad_step_up.status_code == 401, bad_step_up.text


def test_the_denial_parametrisation_covers_every_role_route() -> None:
    """Guard the guard. One test name is claimed for three routes in the DoD ledger.

    The expected set comes from the **committed OpenAPI contract**, not from a literal in
    this file: a hand-written expectation could be edited in the same commit as the
    parametrisation, which is no guard at all. The contract is held equal to the
    application by `openapi:check` and pinned operation by operation by
    `test_openapi_contract.py`, so widening it is a deliberate act somewhere else.
    """

    import json
    from pathlib import Path

    contract = json.loads(
        (Path(__file__).resolve().parents[2] / "services/backend/openapi/v1.json").read_text(
            encoding="utf-8"
        )
    )
    published = {
        (method.upper(), path)
        for path, operations in contract["paths"].items()
        if path.startswith("/api/v1/roles")
        for method in operations
        if method.lower() in {"get", "post", "patch", "put", "delete"}
    }
    assert len(published) >= 3, (
        f"the contract publishes only {len(published)} /roles operations, so this "
        "comparison is against almost nothing"
    )

    covered = {(method, path) for method, path, _ in ROLE_ROUTES}
    assert sorted(published - covered) == [], (
        f"these published /roles operations have no denial case: "
        f"{sorted(published - covered)}"
    )


@pytest.mark.parametrize(("method", "template", "body"), ROLE_ROUTES)
def test_an_admin_without_the_permission_is_refused(
    client: Any, method: str, template: str, body: dict[str, Any] | None
) -> None:
    """`accountant` holds neither `role.read` nor `role.manage`.

    Genuinely authenticated and genuinely unauthorised, which is the combination a
    permission guard exists for — a 401 here would prove the session check and say nothing
    about the grant.
    """

    token = sign_in(client, PRIVILEGED)
    role = _role(client, "accountant")

    token = sign_in(client, OUTSIDER)
    path = template.replace("{role_id}", role["id"])
    response = client.request(
        method,
        path,
        json=body,
        headers={"If-Match": '"anything"', "X-Recent-Auth": "anything", CSRF_HEADER: token},
    )
    assert response.status_code == 403, f"{method} {path} → {response.status_code}: {response.text}"


def test_a_reader_cannot_change_a_role(client: Any) -> None:
    """`role.read` and `role.manage` are separate, and the seeded catalogue separates them.

    The other half of the denial above: this caller *does* hold the read, so a 403 on the
    write proves the two permissions are distinguished rather than that the account was
    refused everything.
    """

    token = sign_in(client, READER)
    listed = client.get("/api/v1/roles")
    assert listed.status_code == 200, "the reader genuinely holds role.read"

    role = [row for row in listed.json()["roles"] if row["code"] == "accountant"][0]
    refused = client.put(
        f"/api/v1/roles/{role['id']}/permissions",
        json={"permission_codes": role["permission_codes"], "reason": "should be denied"},
        headers={"If-Match": '"anything"', "X-Recent-Auth": "anything", CSRF_HEADER: token},
    )
    assert refused.status_code == 403, refused.text
