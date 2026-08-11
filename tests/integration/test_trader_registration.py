"""Registration and the center's four decisions, against a real database.

The registration path is the only unauthenticated write surface on the platform,
so the tests that matter most here are the ones about what it *does not* say.

Covers: API-REG-001, API-REG-002, API-REG-003, API-PENDING-001, API-APPROVE-001,
API-APPROVE-002.
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
STAFF_USERNAME = "business_admin1"
# Holds `audit.read` and several others but NOT `trader.approve` — migration
# `_0008:285` grants that to business_admin and manager only. Exists so the denial
# branch of `requires()` has a caller who is genuinely authenticated and genuinely
# unauthorised, which is the only combination a permission guard is for.
UNPRIVILEGED_USERNAME = "accountant1"


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
    """One staff member holding the four trader permissions, and nothing else.

    The role grants come from migration `_0008`'s seed rather than being invented
    here: a test that granted its own permissions would prove the route reads a
    grant, not that the seeded catalogue actually contains one.
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
        row = connection.execute(
            "INSERT INTO admin_users (username, full_name, password_hash, status) "
            "VALUES (%s, 'Business Admin', %s, 'active') RETURNING id",
            (STAFF_USERNAME, encoded),
        ).fetchone()
        assert row
        admin_id = row[0]

        role = connection.execute("SELECT id FROM roles WHERE code = 'business_admin'").fetchone()
        assert role, "migration 0008 should have seeded business_admin"
        connection.execute(
            "INSERT INTO admin_user_roles (admin_user_id, role_id) VALUES (%s, %s)",
            (admin_id, role[0]),
        )

        other = connection.execute(
            "INSERT INTO admin_users (username, full_name, password_hash, status) "
            "VALUES (%s, 'Accountant', %s, 'active') RETURNING id",
            (UNPRIVILEGED_USERNAME, encoded),
        ).fetchone()
        assert other
        accountant_role = connection.execute(
            "SELECT id FROM roles WHERE code = 'accountant'"
        ).fetchone()
        assert accountant_role, "migration 0008 should have seeded accountant"
        connection.execute(
            "INSERT INTO admin_user_roles (admin_user_id, role_id) VALUES (%s, %s)",
            (other[0], accountant_role[0]),
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


def _traders(migrated: RuntimeIdentities) -> list[tuple[Any, ...]]:
    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        return connection.execute(
            "SELECT id, display_name, primary_phone, approval_status, operational_status, "
            "record_version FROM traders ORDER BY created_at"
        ).fetchall()


def _trader_users(migrated: RuntimeIdentities) -> list[tuple[Any, ...]]:
    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        return connection.execute(
            "SELECT trader_id, phone_number, is_primary, status FROM trader_users"
        ).fetchall()


def register(client: Any, phone: str, name: str = "Goldsmith") -> Any:
    return client.post(
        "/api/v1/traders/register",
        json={
            "display_name": name,
            "primary_phone": phone,
            "contact_full_name": f"{name} Contact",
            "password": PASSWORD,
        },
    )


def sign_in_admin(client: Any, username: str) -> str:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": username, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    token = client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token
    return token


def sign_in_staff(client: Any) -> str:
    return sign_in_admin(client, STAFF_USERNAME)


def decision_headers(token: str, version: int) -> dict[str, str]:
    return {
        CSRF_HEADER: token,
        "If-Match": f'"rv-{version}"',
        "Idempotency-Key": str(uuid.uuid4()),
    }


def test_registration_creates_the_business_and_its_primary_contact(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """API-REG-001. Both rows, in one transaction."""

    response = register(client, "09121110001")

    assert response.status_code == 200, response.text
    assert response.json() == {"accepted": True, "pending_approval": True}

    traders = _traders(migrated)
    assert len(traders) == 1
    _id, _name, phone, approval, operational, _version = traders[0]

    assert phone == "+989121110001", "the phone must be stored in its normalised form"
    assert approval == "pending_approval"
    assert operational == "inactive", (
        "a newly registered business must not be able to transact; approval is what "
        "grants that, and starting active would make approval only ever remove it"
    )

    contacts = _trader_users(migrated)
    assert len(contacts) == 1
    assert contacts[0][1] == "+989121110001"
    assert contacts[0][2] is True, "the registering contact is the primary one"


def test_two_businesses_can_each_register_a_primary_contact(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """API-REG-002, and the end-to-end form of slice 1's defect.

    The index M2 shipped permitted one primary contact in the entire database, so
    this is the request that would have failed on the second trader ever — with a
    unique violation on a column the caller never set.
    """

    assert register(client, "09121110002", "First").status_code == 200
    assert register(client, "09121110003", "Second").status_code == 200

    assert len(_traders(migrated)) == 2
    contacts = _trader_users(migrated)
    assert len(contacts) == 2
    assert all(contact[2] is True for contact in contacts)
    assert len({contact[0] for contact in contacts}) == 2, "each contact its own business"


def test_a_duplicate_registration_is_indistinguishable_from_a_new_one(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """API-REG-003. A public endpoint must not be a membership oracle.

    "This number is already registered" would let anyone enumerate which
    goldsmiths deal with this center — commercially useful information, freely
    available, with no account needed.
    """

    first = register(client, "09121110004")
    second = register(client, "09121110004")

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json(), (
        "the duplicate answered differently, so the endpoint reveals who is already registered"
    )
    assert len(_traders(migrated)) == 1, "the duplicate must not create a second row"

    # The distinction the caller is denied still reaches the audit trail.
    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        outcomes = connection.execute(
            "SELECT outcome FROM audit_logs WHERE action = 'trader.registered' ORDER BY occurred_at"
        ).fetchall()

    assert [row[0] for row in outcomes] == ["success", "rejected"]


def test_a_malformed_phone_number_is_also_indistinguishable(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """Otherwise the endpoint still discriminates, just more coarsely."""

    response = register(client, "not-a-phone-number")

    assert response.status_code == 200
    assert response.json() == {"accepted": True, "pending_approval": True}
    assert _traders(migrated) == []


def test_registration_accepts_persian_digits(client: Any, migrated: RuntimeIdentities) -> None:
    """The ordinary path for a trader typing their own number."""

    assert register(client, "۰۹۱۲۱۱۱۰۰۰۵").status_code == 200

    assert _traders(migrated)[0][2] == "+989121110005"


def test_a_pending_trader_reaches_only_the_pending_surface(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """API-PENDING-001. `12_Security_RBAC_Audit.md:431`.

    They can sign in — the *account* is active — and read their own profile, which
    is what tells them approval is pending. They cannot change anything, because
    the *business* is not approved. That split is DOC-CONFLICT-024's separation
    doing visible work.
    """

    register(client, "09121110006")

    client.cookies.clear()
    signed_in = client.post(
        "/api/v1/auth/trader/login",
        json={"identifier": "09121110006", "password": PASSWORD},
    )
    assert signed_in.status_code == 200, "a pending trader must still be able to sign in"

    profile = client.get("/api/v1/me/trader/profile")
    assert profile.status_code == 200
    assert profile.json()["approval_status"] == "pending_approval"

    refused = client.patch(
        "/api/v1/me/trader/profile",
        json={"display_name": "Renamed"},
        headers={
            CSRF_HEADER: client.cookies.get(TRADER_CSRF_COOKIE),
            "If-Match": f'"rv-{profile.json()["record_version"]}"',
        },
    )
    assert refused.status_code == 403
    assert "approval" in refused.json()["error"]["message"].lower(), (
        "the message must say approval is pending; 'permission denied' would send "
        "the trader looking for a setting that does not exist"
    )


def test_approval_activates_the_business_and_is_idempotent(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """API-APPROVE-001."""

    register(client, "09121110007")
    trader_id = str(_traders(migrated)[0][0])
    version = _traders(migrated)[0][5]

    token = sign_in_staff(client)
    headers = {
        CSRF_HEADER: token,
        "If-Match": f'"rv-{version}"',
        "Idempotency-Key": str(uuid.uuid4()),
    }

    approved = client.post(f"/api/v1/traders/{trader_id}/approve", json={}, headers=headers)

    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["approval_status"] == "approved"
    assert body["operational_status"] == "active"
    assert body["approved_at"] is not None
    assert approved.headers["ETag"] == f'"rv-{body["record_version"]}"'


def test_a_decision_requires_both_if_match_and_an_idempotency_key(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """Neither substitutes for the other.

    `If-Match` stops a decision landing on a business somebody else just changed;
    the idempotency key stops a retried approval approving twice.
    """

    register(client, "09121110008")
    trader_id = str(_traders(migrated)[0][0])
    version = _traders(migrated)[0][5]
    token = sign_in_staff(client)

    without_match = client.post(
        f"/api/v1/traders/{trader_id}/approve",
        json={},
        headers={CSRF_HEADER: token, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert without_match.status_code == 428

    without_key = client.post(
        f"/api/v1/traders/{trader_id}/approve",
        json={},
        headers={CSRF_HEADER: token, "If-Match": f'"rv-{version}"'},
    )
    assert without_key.status_code == 428

    stale = client.post(
        f"/api/v1/traders/{trader_id}/approve",
        json={},
        headers={
            CSRF_HEADER: token,
            "If-Match": '"rv-999"',
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert stale.status_code == 412


def test_rejecting_requires_a_reason(client: Any, migrated: RuntimeIdentities) -> None:
    """`05_API_Specification.md:894`. A rejection nobody explained cannot be reviewed."""

    register(client, "09121110009")
    trader_id = str(_traders(migrated)[0][0])
    version = _traders(migrated)[0][5]
    token = sign_in_staff(client)
    headers = {
        CSRF_HEADER: token,
        "If-Match": f'"rv-{version}"',
        "Idempotency-Key": str(uuid.uuid4()),
    }

    assert (
        client.post(f"/api/v1/traders/{trader_id}/reject", json={}, headers=headers).status_code
        == 400
    )

    with_reason = client.post(
        f"/api/v1/traders/{trader_id}/reject",
        json={"reason": "Identity documents could not be verified."},
        headers=headers,
    )
    assert with_reason.status_code == 200
    assert with_reason.json()["approval_status"] == "rejected"


def test_an_approved_trader_cannot_be_rejected(client: Any, migrated: RuntimeIdentities) -> None:
    """Refused loudly rather than as a no-op that returns 200.

    An operator who rejected an already-approved business needs to know the
    request did not do what they meant.
    """

    register(client, "09121110010")
    trader_id = str(_traders(migrated)[0][0])
    token = sign_in_staff(client)

    version = _traders(migrated)[0][5]
    client.post(
        f"/api/v1/traders/{trader_id}/approve",
        json={},
        headers={
            CSRF_HEADER: token,
            "If-Match": f'"rv-{version}"',
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )

    current = _traders(migrated)[0][5]
    refused = client.post(
        f"/api/v1/traders/{trader_id}/reject",
        json={"reason": "changed our mind"},
        headers={
            CSRF_HEADER: token,
            "If-Match": f'"rv-{current}"',
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )

    assert refused.status_code == 400


def test_each_decision_writes_audit_and_outbox_in_the_same_transaction(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """API-APPROVE-002. `05_API_Specification.md:878` requires both."""

    register(client, "09121110011")
    trader_id = str(_traders(migrated)[0][0])
    token = sign_in_staff(client)
    version = _traders(migrated)[0][5]

    client.post(
        f"/api/v1/traders/{trader_id}/approve",
        json={},
        headers={
            CSRF_HEADER: token,
            "If-Match": f'"rv-{version}"',
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        audit = connection.execute(
            "SELECT action, outcome, previous_values, new_values FROM audit_logs "
            "WHERE action = 'trader.approved'"
        ).fetchall()
        outbox = connection.execute(
            "SELECT event_type, payload FROM outbox_events WHERE event_type = 'TraderApproved'"
        ).fetchall()

    assert len(audit) == 1
    _action, outcome, previous, new = audit[0]
    assert outcome == "success"
    assert previous["approval_status"] == "pending_approval"
    assert new["approval_status"] == "approved"

    assert len(outbox) == 1
    assert outbox[0][1] == {"trader_id": trader_id}, (
        "the event must carry no phone number or name; a consumer that needs them "
        "reads the aggregate"
    )


def test_an_authenticated_admin_without_the_permission_is_refused(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """The first test in this repository to reach the denial branch of `requires()`.

    `14_Testing_QA_Acceptance.md:1270` requires positive **and** negative tests for
    every permission, and adds that role-name checks alone are insufficient. Until
    slice 10 counted them, every authorization refusal in the suite was at the
    audience, ownership, state or policy layer — the `ForbiddenError` inside the
    guard was never reached by any test, so the one line that turns a missing grant
    into a 403 was unexercised across five merged slices.

    The caller is genuinely authenticated and genuinely unauthorised, which is the
    only combination that exercises it.
    """

    register(client, "09121110013")
    trader_id = str(_traders(migrated)[0][0])
    version = _traders(migrated)[0][5]

    token = sign_in_admin(client, UNPRIVILEGED_USERNAME)
    refused = client.post(
        f"/api/v1/traders/{trader_id}/approve",
        json={},
        headers=decision_headers(token, version),
    )

    assert refused.status_code == 403, (
        "an authenticated admin lacking trader.approve was not refused, so the "
        "permission guard is not the thing deciding this route"
    )
    assert refused.json()["error"]["code"] == "FORBIDDEN"

    # Nothing changed. A 403 that still applied the decision would be worse than no
    # guard, because the response would misreport what happened.
    assert _traders(migrated)[0][3] == "pending_approval"


def test_the_same_call_succeeds_for_a_role_that_holds_the_permission(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """The positive half, and the reason the negative one above means anything.

    Without it, "approve returns 403" would also be satisfied by a route that
    refuses everybody — a broken guard, a wrong path, a typo in the declared
    permission. The pair is what separates "the grant decides" from "nothing works".
    """

    register(client, "09121110014")
    trader_id = str(_traders(migrated)[0][0])
    version = _traders(migrated)[0][5]

    token = sign_in_admin(client, STAFF_USERNAME)
    allowed = client.post(
        f"/api/v1/traders/{trader_id}/approve",
        json={},
        headers=decision_headers(token, version),
    )

    assert allowed.status_code == 200, allowed.text
    assert _traders(migrated)[0][3] == "approved"


def test_a_revoked_grant_stops_granting_immediately(
    client: Any, migrated: RuntimeIdentities
) -> None:
    """SEC-PERM-002 through HTTP, rather than against the resolver in isolation.

    Permissions resolve per request, so revoking a role must take effect on the
    next call rather than when the session expires. Revoking *after* the session
    exists is the case that tells the two apart — and a resolver test cannot,
    because it has no session.
    """

    register(client, "09121110015")
    trader_id = str(_traders(migrated)[0][0])
    version = _traders(migrated)[0][5]
    token = sign_in_admin(client, STAFF_USERNAME)

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "UPDATE admin_user_roles SET revoked_at = now() WHERE admin_user_id = "
            "(SELECT id FROM admin_users WHERE username = %s)",
            (STAFF_USERNAME,),
        )
        connection.commit()

    refused = client.post(
        f"/api/v1/traders/{trader_id}/approve",
        json={},
        headers=decision_headers(token, version),
    )

    assert refused.status_code == 403, (
        "the grant was revoked and the session still carried it, so permissions are "
        "cached at login rather than resolved per request"
    )


def test_a_trader_cannot_approve_itself(client: Any, migrated: RuntimeIdentities) -> None:
    """The permission guard, from the other side of the audience boundary."""

    register(client, "09121110012")
    trader_id = str(_traders(migrated)[0][0])

    client.cookies.clear()
    client.post(
        "/api/v1/auth/trader/login",
        json={"identifier": "09121110012", "password": PASSWORD},
    )

    refused = client.post(
        f"/api/v1/traders/{trader_id}/approve",
        json={},
        headers={
            CSRF_HEADER: client.cookies.get(TRADER_CSRF_COOKIE) or "",
            "If-Match": '"rv-1"',
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )

    assert refused.status_code in {401, 403}
    assert _traders(migrated)[0][3] == "pending_approval"
