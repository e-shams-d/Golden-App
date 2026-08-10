"""The mandatory IDOR cases, against two real traders and a real database.

`14_Testing_QA_Acceptance.md:1274-1282` names seven. Three are exercisable today
and are here; four name resources that arrive in M4 and M5, and are recorded as
deferred **with the milestone that owns them** rather than quietly absent — a
deferral nobody can see is indistinguishable from a case nobody thought of.

Two traders exist in this fixture and that is the point. Slice 1's defect — a
primary-contact index that permitted one primary contact in the entire database —
survived M2 precisely because no test ever created a second trader. Every
isolation claim needs two parties to mean anything.

Covers: SEC-IDOR-001, SEC-IDOR-002, SEC-IDOR-003, SEC-IDOR-005, API-PROFILE-001,
API-PROFILE-002.
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

TRADER_A_PHONE = "+989120000001"
TRADER_B_PHONE = "+989120000002"
PASSWORD = "correct-horse-battery-staple"
CSRF_HEADER = "X-CSRF-Token"
TRADER_CSRF_COOKIE = "__Host-gp_trader_csrf"

# The four cases whose resources do not exist until a later milestone. Named with
# their owner so `TRACE-DOD-002` can require a deferral to say who is responsible;
# an unowned deferral is a case that never gets written.
DEFERRED_IDOR_CASES: dict[str, str] = {
    "trader A reads trader B's payment request": "M5",
    "trader A downloads trader B's publication file": "M7",
    "trader A guesses a mixed bank-bundle file id": "M4",
    "an admin response includes unrelated trader data": "M5",
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
    """Two trader businesses, each with its own primary contact, and one admin."""

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

    trader_a, trader_b = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        for trader_id, name, phone in (
            (trader_a, "Trader A", TRADER_A_PHONE),
            (trader_b, "Trader B", TRADER_B_PHONE),
        ):
            connection.execute(
                "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
                "approval_status) VALUES (%s, %s, %s, 'active', 'approved')",
                (trader_id, name, phone),
            )
            connection.execute(
                "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
                "status, is_primary) VALUES (%s, %s, %s, %s, 'active', TRUE)",
                (trader_id, phone, f"{name} Contact", encoded),
            )
        connection.execute(
            "INSERT INTO admin_users (username, full_name, password_hash, status) "
            "VALUES ('staff1', 'Staff User', %s, 'active')",
            (encoded,),
        )
        connection.commit()

    app = create_app(settings=settings)
    app.state.runtime = RuntimeServices.from_settings(settings)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://trader.localhost") as client:
        yield {"client": client, "trader_a": trader_a, "trader_b": trader_b}
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def sign_in(client: Any, phone: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/trader/login", json={"identifier": phone, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def test_a_trader_sees_only_its_own_business(world: dict[str, Any]) -> None:
    """SEC-IDOR-001, and the guard-the-guard: A and B must see *different* rows.

    A profile endpoint that returned the same business to everyone would satisfy
    "A cannot see B" by accident.
    """

    client = world["client"]

    sign_in(client, TRADER_A_PHONE)
    a_body = client.get("/api/v1/me/trader/profile").json()

    sign_in(client, TRADER_B_PHONE)
    b_body = client.get("/api/v1/me/trader/profile").json()

    assert a_body["id"] == str(world["trader_a"])
    assert b_body["id"] == str(world["trader_b"])
    assert a_body["id"] != b_body["id"]
    assert a_body["primary_phone"] == TRADER_A_PHONE
    assert TRADER_B_PHONE not in str(a_body), "trader A's response mentions trader B"


def test_there_is_no_field_in_which_to_submit_another_traders_id(
    world: dict[str, Any],
) -> None:
    """SEC-IDOR-002, the mandatory case at `14_Testing_QA_Acceptance.md:1280`.

    The defence is structural rather than validating: the profile routes take no
    `trader_id` at all, so there is nothing to submit it in. Sending one anyway is
    refused by `extra="forbid"` rather than silently ignored — an ignored field
    would let a caller believe it had been honoured.
    """

    client = world["client"]
    sign_in(client, TRADER_A_PHONE)

    current = client.get("/api/v1/me/trader/profile").json()
    token = client.cookies.get(TRADER_CSRF_COOKIE)

    response = client.patch(
        "/api/v1/me/trader/profile",
        json={"display_name": "Renamed", "trader_id": str(world["trader_b"])},
        headers={CSRF_HEADER: token, "If-Match": f'"rv-{current["record_version"]}"'},
    )

    assert response.status_code == 422, (
        "an unexpected trader_id was accepted or ignored; it must be refused"
    )

    # And trader B is untouched.
    sign_in(client, TRADER_B_PHONE)
    assert client.get("/api/v1/me/trader/profile").json()["display_name"] == "Trader B"


def test_a_trader_session_is_refused_on_an_internal_endpoint(world: dict[str, Any]) -> None:
    """SEC-IDOR-003. Refused by audience, before any ownership question is asked."""

    client = world["client"]
    sign_in(client, TRADER_A_PHONE)

    # An operations surface, which requires an internal token rather than a session.
    assert client.get("/api/v1/operations/release-evidence").status_code in {401, 403}


def test_an_admin_has_no_ownership_scope(world: dict[str, Any]) -> None:
    """Doc 12:316: an internal session is not ownership of a trader account.

    The profile route answers 404 rather than showing an arbitrary business —
    Phase 1A has no support workflow, so there is no correct trader to show.
    """

    client = world["client"]
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": "staff1", "password": PASSWORD}
    )
    assert response.status_code == 200

    assert client.get("/api/v1/me/trader/profile").status_code == 404


def test_the_patch_cannot_change_identity_or_status(world: dict[str, Any]) -> None:
    """API-PROFILE-002.

    `05_API_Specification.md:925` requires phone changes to use a controlled
    identity workflow, and a business must not be able to approve itself.
    """

    client = world["client"]
    sign_in(client, TRADER_A_PHONE)
    current = client.get("/api/v1/me/trader/profile").json()
    token = client.cookies.get(TRADER_CSRF_COOKIE)
    headers = {CSRF_HEADER: token, "If-Match": f'"rv-{current["record_version"]}"'}

    for forbidden in (
        {"primary_phone": "+989129999999"},
        {"approval_status": "approved"},
        {"operational_status": "active"},
        {"credit_limit_irr": 10_000_000},
    ):
        response = client.patch("/api/v1/me/trader/profile", json=forbidden, headers=headers)
        assert response.status_code == 422, f"{forbidden} was accepted"

    assert client.get("/api/v1/me/trader/profile").json()["primary_phone"] == TRADER_A_PHONE


def test_the_patch_requires_a_fresh_if_match(world: dict[str, Any]) -> None:
    """API-PROFILE-001. 428 when absent, 412 when stale — different instructions."""

    client = world["client"]
    sign_in(client, TRADER_A_PHONE)
    current = client.get("/api/v1/me/trader/profile").json()
    token = client.cookies.get(TRADER_CSRF_COOKIE)

    missing = client.patch(
        "/api/v1/me/trader/profile",
        json={"display_name": "New Name"},
        headers={CSRF_HEADER: token},
    )
    assert missing.status_code == 428

    stale = client.patch(
        "/api/v1/me/trader/profile",
        json={"display_name": "New Name"},
        headers={CSRF_HEADER: token, "If-Match": '"rv-999"'},
    )
    assert stale.status_code == 412

    fresh = client.patch(
        "/api/v1/me/trader/profile",
        json={"display_name": "New Name"},
        headers={CSRF_HEADER: token, "If-Match": f'"rv-{current["record_version"]}"'},
    )
    assert fresh.status_code == 200
    assert fresh.json()["display_name"] == "New Name"
    assert fresh.json()["record_version"] == current["record_version"] + 1


def test_the_profile_never_carries_internal_fields(world: dict[str, Any]) -> None:
    """`04_Database_Schema.md:464` marks `notes_internal` never trader-visible."""

    client = world["client"]
    sign_in(client, TRADER_A_PHONE)

    body = client.get("/api/v1/me/trader/profile").json()

    assert "notes_internal" not in body
    assert "risk_level" not in body


def test_every_deferred_idor_case_names_its_milestone() -> None:
    """TRACE-DOD-002's shape, applied to the four cases M3 cannot exercise.

    A deferral without an owner is a case nobody will write. Requiring a milestone
    turns "not yet" into a commitment that a later gate can check.
    """

    assert len(DEFERRED_IDOR_CASES) == 4
    for case, milestone in DEFERRED_IDOR_CASES.items():
        assert milestone.startswith("M"), (
            f"{case} defers to {milestone!r}, which names no milestone"
        )
