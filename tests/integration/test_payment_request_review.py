"""The centre's half of the journey: review, return, resubmit, mark eligible.

M5 slice 7, driven through the routes as the two actors really would.

`SVC-REVIEW-001`'s enumeration lives in `tests/backend/test_review_transitions.py`, which
parses document 06's state machine and needs no database. What is here is the behaviour
that enumeration cannot show: that the API actually refuses every pairing the document does
not draw, that the journey runs end to end, and that each action leaves the trail it owes.

Every aggregate query is scoped to the request under test. These files share one database
by module, and an unscoped `WHERE action = 'payment_request.review_started'` would claim
"starting a review wrote an audit row" while asserting only "some review somewhere did".

Covers: SVC-REVIEW-002, SEC-REQ-003, AUD-REQ-002.
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

TRADERS: dict[str, str] = {"ok": "+989120000701", "other": "+989120000702"}
IBAN_ONE = "IR060120000000000000000011"
IBAN_TWO = "IR060120000000000000000012"

# The three accountant routes, by the path suffix and the body each needs. Kept as data so
# the permission negatives and the refusal matrix iterate rather than repeat.
REVIEW_ACTIONS: dict[str, str] = {
    "start_review": "start-review",
    "request_correction": "request-correction",
    "mark_eligible": "mark-eligible-for-batching",
}


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
    beneficiaries = {"ok_one": uuid.uuid4(), "ok_two": uuid.uuid4()}

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
        for key, iban, full_name in (
            ("ok_one", IBAN_ONE, "Ali One"),
            ("ok_two", IBAN_TWO, "Reza Two"),
        ):
            connection.execute(
                "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
                "status, verification_status) VALUES (%s, %s, %s, %s, %s, 'active', "
                "'not_checked')",
                (beneficiaries[key], traders["ok"], full_name, iban, iban),
            )

        for username in ("staff_granted", "staff_bare"):
            connection.execute(
                "INSERT INTO admin_users (username, full_name, password_hash, status) "
                "VALUES (%s, %s, %s, 'active')",
                (username, f"{username} User", encoded),
            )
        # `staff_granted` is an accountant, which the RBAC seed gives all three review
        # permissions. `staff_bare` holds no role, which is what the permission negatives
        # need: a signed-in internal caller who simply lacks the grant.
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


def _write(client: Any, path: str, version: int, body: dict[str, Any] | None = None) -> Any:
    """A write with `If-Match` and the CSRF token, which the negatives need too.

    The token is sent deliberately even where the test expects a refusal. CSRF failure and
    permission denial share the `FORBIDDEN` envelope, so a permission negative that omits
    the token asserts `403` and proves nothing about permissions.
    """

    return client.post(
        path,
        json=body if body is not None else {},
        headers={**csrf(client), "If-Match": f'"rv-{version}"'},
    )


def open_draft(world: dict[str, Any], beneficiary: str = "ok_one", value: str = "500") -> Any:
    client = world["client"]
    return client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiaries"][beneficiary]),
            "amount": {"value": value, "unit": "TOMAN"},
            "description": "original",
        },
        headers=csrf(client),
    ).json()


def action_body(action: str, revision_id: str | None = None) -> dict[str, Any]:
    if action == "request_correction":
        return {"reason_code": "invalid_iban", "message_to_trader": "Fix the IBAN."}
    if action == "mark_eligible":
        return {"expected_revision_id": revision_id, "review_note": "Checked."}
    return {}


def act(
    world: dict[str, Any],
    action: str,
    request_id: str,
    version: int,
    revision_id: str | None = None,
) -> Any:
    return _write(
        world["client"],
        f"/api/v1/payment-requests/{request_id}/{REVIEW_ACTIONS[action]}",
        version,
        action_body(action, revision_id),
    )


def submit(world: dict[str, Any], request_id: str, version: int) -> Any:
    return _write(world["client"], f"/api/v1/payment-requests/{request_id}/submit", version)


def correct(world: dict[str, Any], request_id: str, version: int, value: str = "600") -> Any:
    client = world["client"]
    return client.post(
        f"/api/v1/payment-requests/{request_id}/revisions",
        json={
            "beneficiary_id": str(world["beneficiaries"]["ok_one"]),
            "amount": {"value": value, "unit": "TOMAN"},
            "description": "corrected",
            "revision_reason": "the accountant asked",
        },
        headers={
            **csrf(client),
            "If-Match": f'"rv-{version}"',
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )


def cancel(world: dict[str, Any], request_id: str, version: int, reason: str | None) -> Any:
    return _write(
        world["client"],
        f"/api/v1/payment-requests/{request_id}/cancel",
        version,
        {} if reason is None else {"reason": reason},
    )


def request_row(world: dict[str, Any], request_id: str) -> tuple[str, int]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        row = connection.execute(
            "SELECT status, record_version FROM payment_requests WHERE id = %s",
            (request_id,),
        ).fetchone()
    assert row is not None
    return str(row[0]), int(row[1])


def audit_actions(world: dict[str, Any], request_id: str) -> list[str]:
    """Every audit action for this request, in order. Scoped to `entity_id`."""

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        rows = connection.execute(
            "SELECT action FROM audit_logs WHERE entity_id = %s ORDER BY created_at, action",
            (request_id,),
        ).fetchall()
    return [str(row[0]) for row in rows]


def outbox_events(world: dict[str, Any], request_id: str) -> list[str]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        rows = connection.execute(
            "SELECT event_type FROM outbox_events WHERE aggregate_id = %s ORDER BY created_at",
            (request_id,),
        ).fetchall()
    return [str(row[0]) for row in rows]


def a_submitted_request(world: dict[str, Any]) -> tuple[str, int, str]:
    """A request handed to the centre. Returns `(id, record_version, revision_id)`."""

    sign_in(world["client"], "ok")
    created = open_draft(world)
    handed = submit(world, created["request"]["id"], created["request"]["record_version"])
    assert handed.status_code == 200, handed.text
    return (
        created["request"]["id"],
        handed.json()["record_version"],
        created["revision"]["id"],
    )


def a_request_under_review(world: dict[str, Any]) -> tuple[str, int, str]:
    request_id, version, revision_id = a_submitted_request(world)
    sign_in_admin(world["client"], "staff_granted")
    started = act(world, "start_review", request_id, version)
    assert started.status_code == 200, started.text
    return request_id, started.json()["record_version"], revision_id


# --- SEC-REQ-003: the permission negatives the M3 DoD gate demands by name ---------------


# Three separate tests rather than one parametrised body, because the M3 DoD gate names
# each of them and looks the name up: a parametrised id is not the function it demands.
def test_starting_a_review_needs_the_review_permission(world: dict[str, Any]) -> None:
    """`SEC-REQ-003`. `403`, not `404`: an internal caller already knows requests exist."""

    request_id, version, _revision_id = a_submitted_request(world)
    sign_in_admin(world["client"], "staff_bare")

    refused = act(world, "start_review", request_id, version)

    assert refused.status_code == 403, refused.text
    assert request_row(world, request_id)[0] == "submitted_to_center"


def test_returning_a_request_needs_the_correction_permission(world: dict[str, Any]) -> None:
    """`SEC-REQ-003`."""

    request_id, version, _revision_id = a_submitted_request(world)
    sign_in_admin(world["client"], "staff_bare")

    refused = act(world, "request_correction", request_id, version)

    assert refused.status_code == 403, refused.text
    assert request_row(world, request_id)[0] == "submitted_to_center"


def test_marking_eligible_needs_the_mark_eligible_permission(world: dict[str, Any]) -> None:
    """`SEC-REQ-003`."""

    request_id, version, revision_id = a_request_under_review(world)
    sign_in_admin(world["client"], "staff_bare")

    refused = act(world, "mark_eligible", request_id, version, revision_id)

    assert refused.status_code == 403, refused.text
    assert request_row(world, request_id)[0] == "under_accountant_review"


@pytest.mark.parametrize("action", sorted(REVIEW_ACTIONS))
def test_a_trader_cannot_perform_an_accountant_action(world: dict[str, Any], action: str) -> None:
    """`SEC-REQ-003`, the half that matters most.

    A trader session carries no permissions at all (`app/security/actor.py:113-118`), so
    these routes refuse it — including on the trader's *own* request, which is the case a
    route guarded by ownership alone would have allowed.
    """

    request_id, version, revision_id = a_request_under_review(world)

    sign_in(world["client"], "ok")
    refused = act(world, action, request_id, version, revision_id)

    assert refused.status_code == 403, refused.text
    assert request_row(world, request_id)[0] == "under_accountant_review"


# --- SVC-REVIEW-002: the journey ---------------------------------------------------------


def test_a_returned_request_is_corrected_resubmitted_and_reviewed_again(
    world: dict[str, Any],
) -> None:
    """`SVC-REVIEW-002`, and the milestone's Definition of Done in one test.

    Six steps, each through the API as the actor who owns it. The resubmission is an
    explicit `submit`, which is what the DoD's word "resubmit" means and what document 06
    `:641` gives both origins for — `create_revision` used to do it as a side effect, so a
    trader editing a draft filed it.
    """

    client = world["client"]
    request_id, version, first_revision = a_submitted_request(world)

    sign_in_admin(client, "staff_granted")
    started = act(world, "start_review", request_id, version)
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "under_accountant_review"

    returned = act(world, "request_correction", request_id, started.json()["record_version"])
    assert returned.status_code == 200, returned.text
    assert returned.json()["status"] == "needs_trader_correction"

    sign_in(client, "ok")
    corrected = correct(world, request_id, returned.json()["record_version"])
    assert corrected.status_code == 201, corrected.text
    second_revision = corrected.json()["revision"]["id"]
    assert second_revision != first_revision
    # Still with the trader. The correction is content, not a handover.
    assert corrected.json()["request"]["status"] == "needs_trader_correction"

    resubmitted = submit(world, request_id, corrected.json()["request"]["record_version"])
    assert resubmitted.status_code == 200, resubmitted.text
    assert resubmitted.json()["status"] == "submitted_to_center"

    sign_in_admin(client, "staff_granted")
    reviewed = act(world, "start_review", request_id, resubmitted.json()["record_version"])
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "under_accountant_review"

    eligible = act(
        world, "mark_eligible", request_id, reviewed.json()["record_version"], second_revision
    )
    assert eligible.status_code == 200, eligible.text
    assert eligible.json()["status"] == "eligible_for_batching"

    sign_in(client, "ok")
    history = client.get(f"/api/v1/payment-requests/{request_id}/revisions")
    assert history.status_code == 200, history.text
    numbers = [item["revision_number"] for item in history.json()["items"]]
    assert numbers == [1, 2], "the history must hold both revisions after a correction"
    assert history.json()["current_revision_id"] == second_revision


def test_marking_eligible_refuses_a_superseded_revision(world: dict[str, Any]) -> None:
    """Document 06 `:644`'s "current revision valid" guard.

    The accountant names the revision they validated. If a correction landed while they
    were reading, marking eligible would send a revision nobody approved for batching.
    """

    client = world["client"]
    request_id, version, first_revision = a_submitted_request(world)

    sign_in_admin(client, "staff_granted")
    returned = act(world, "request_correction", request_id, version)
    assert returned.status_code == 200, returned.text

    sign_in(client, "ok")
    corrected = correct(world, request_id, returned.json()["record_version"])
    assert corrected.status_code == 201, corrected.text
    resubmitted = submit(world, request_id, corrected.json()["request"]["record_version"])

    sign_in_admin(client, "staff_granted")
    reviewed = act(world, "start_review", request_id, resubmitted.json()["record_version"])

    stale = act(
        world, "mark_eligible", request_id, reviewed.json()["record_version"], first_revision
    )

    assert stale.status_code == 400, stale.text
    assert stale.json()["error"]["code"] == "BUSINESS_RULE_VIOLATION"
    assert request_row(world, request_id)[0] == "under_accountant_review"


# --- SVC-REVIEW-001, the behavioural half: undocumented pairings are refused -------------


@pytest.mark.parametrize(
    ("action", "reachable_from"),
    [
        ("start_review", "draft"),
        ("mark_eligible", "draft"),
        ("mark_eligible", "submitted_to_center"),
        ("start_review", "under_accountant_review"),
    ],
)
def test_an_undocumented_pairing_is_refused(
    world: dict[str, Any], action: str, reachable_from: str
) -> None:
    """Document 06 draws no arrow for any of these, so the API refuses each one.

    The full enumeration is in `tests/backend/test_review_transitions.py`, which compares
    the code's table against the document. This drives the cases through the routes, so a
    guard that is declared and not consulted fails here rather than passing there.
    """

    client = world["client"]
    if reachable_from == "draft":
        sign_in(client, "ok")
        created = open_draft(world)
        request_id = created["request"]["id"]
        version = created["request"]["record_version"]
        revision_id = created["revision"]["id"]
    elif reachable_from == "submitted_to_center":
        request_id, version, revision_id = a_submitted_request(world)
    else:
        request_id, version, revision_id = a_request_under_review(world)

    sign_in_admin(client, "staff_granted")
    refused = act(world, action, request_id, version, revision_id)

    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["code"] == "BUSINESS_RULE_VIOLATION"
    assert request_row(world, request_id)[0] == reachable_from


def in_a_documented_origin(world: dict[str, Any], action: str) -> tuple[str, int, str]:
    """A request in a state the action is actually permitted from.

    Needed because the state guard runs before the version comparison, which the first
    version of the test below did not account for: it drove `start_review` at a request
    already under review and got `400` for the wrong state rather than `412` for the stale
    version. Both answers are right; the test was asking the wrong question.
    """

    if action == "mark_eligible":
        return a_request_under_review(world)
    request_id, version, revision_id = a_submitted_request(world)
    # Signed in as the accountant before returning. `a_submitted_request` leaves the
    # trader's session in place, and a caller that forgot got `403 FORBIDDEN` where it
    # expected `428` — the same envelope a CSRF failure uses, so the message named
    # permissions and read like a guard bug rather than a signed-in-as-the-wrong-actor one.
    sign_in_admin(world["client"], "staff_granted")
    return request_id, version, revision_id


@pytest.mark.parametrize("action", sorted(REVIEW_ACTIONS))
def test_a_review_action_requires_if_match(world: dict[str, Any], action: str) -> None:
    """`428` for absent and `412` for stale, as the other write routes answer."""

    client = world["client"]
    request_id, version, revision_id = in_a_documented_origin(world, action)
    path = f"/api/v1/payment-requests/{request_id}/{REVIEW_ACTIONS[action]}"

    absent = client.post(path, json=action_body(action, revision_id), headers=csrf(client))
    assert absent.status_code == 428, absent.text

    stale = act(world, action, request_id, version - 1, revision_id)
    assert stale.status_code == 412, stale.text


def test_the_state_guard_answers_before_the_version_comparison(world: dict[str, Any]) -> None:
    """Two accountants opening the same queue, and what the second one is told.

    `400` naming the state it found, not `412`. Deliberate and consistent with `submit` and
    `cancel`, which also refuse an impossible transition before comparing versions: the
    second accountant's problem is not a stale tab they can refresh away, it is that the
    request has already moved on, and a `412` would send them to re-read and try again.
    """

    request_id, version, _revision_id = a_submitted_request(world)

    sign_in_admin(world["client"], "staff_granted")
    first = act(world, "start_review", request_id, version)
    assert first.status_code == 200, first.text

    # A stale version *and* a state that no longer permits the action. The state wins.
    second = act(world, "start_review", request_id, version)

    assert second.status_code == 400, second.text
    assert "under_accountant_review" in second.json()["error"]["message"]


# --- SVC-REVIEW-003: cancellation, and what a cancelled request accepts ------------------


def test_a_trader_cannot_cancel_a_request_under_review(world: dict[str, Any]) -> None:
    """§29.1 reads "Internal with reason" for that row, where its neighbours read
    "Trader/internal". The exclusion is the rule, not an omission."""

    request_id, version, _revision_id = a_request_under_review(world)

    sign_in(world["client"], "ok")
    refused = cancel(world, request_id, version, "changed my mind")

    assert refused.status_code == 400, refused.text
    assert request_row(world, request_id)[0] == "under_accountant_review"


def test_the_centre_may_cancel_a_request_under_review(world: dict[str, Any]) -> None:
    """The other half of the same row: refusing the trader is not refusing everyone."""

    request_id, version, _revision_id = a_request_under_review(world)

    sign_in_admin(world["client"], "staff_granted")
    cancelled = cancel(world, request_id, version, "duplicate of an earlier request")

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"


def test_cancelling_a_submitted_request_requires_a_reason(world: dict[str, Any]) -> None:
    """§29.1 says "with policy/reason" from `submitted_to_center` onward, and says nothing
    of the kind for `draft` — a draft nobody else has seen may just be abandoned."""

    request_id, version, _revision_id = a_submitted_request(world)

    sign_in_admin(world["client"], "staff_granted")
    refused = cancel(world, request_id, version, None)

    assert refused.status_code == 400, refused.text
    assert request_row(world, request_id)[0] == "submitted_to_center"


def test_a_draft_is_cancelled_without_a_reason(world: dict[str, Any]) -> None:
    """The contrast that makes the test above mean something."""

    sign_in(world["client"], "ok")
    created = open_draft(world)

    cancelled = cancel(
        world, created["request"]["id"], created["request"]["record_version"], None
    )

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"


@pytest.mark.parametrize("action", sorted(REVIEW_ACTIONS))
def test_a_cancelled_request_accepts_no_further_transition(
    world: dict[str, Any], action: str
) -> None:
    """`SVC-REVIEW-003`'s second half. `cancelled` is absent from every origin list."""

    client = world["client"]
    request_id, version, revision_id = a_submitted_request(world)

    sign_in_admin(client, "staff_granted")
    cancelled = cancel(world, request_id, version, "withdrawn")
    assert cancelled.status_code == 200, cancelled.text

    refused = act(world, action, request_id, cancelled.json()["record_version"], revision_id)

    assert refused.status_code == 400, refused.text
    assert request_row(world, request_id)[0] == "cancelled"


def test_a_cancelled_request_is_not_cancelled_again(world: dict[str, Any]) -> None:
    """Not in `CANCELLABLE` either, so the same rule refuses a second cancellation."""

    request_id, version, _revision_id = a_submitted_request(world)

    sign_in_admin(world["client"], "staff_granted")
    first = cancel(world, request_id, version, "withdrawn")
    assert first.status_code == 200, first.text

    again = cancel(world, request_id, first.json()["record_version"], "withdrawn twice")

    assert again.status_code == 400, again.text


# --- AUD-REQ-002: audited, and emitted where the catalogue defines an event ---------------


def test_each_review_action_writes_its_catalogued_audit_row(world: dict[str, Any]) -> None:
    """`AUD-REQ-002`. The three names are all in `audit_outbox_catalog.yaml`."""

    client = world["client"]
    request_id, version, _revision_id = a_submitted_request(world)

    sign_in_admin(client, "staff_granted")
    started = act(world, "start_review", request_id, version)
    returned = act(world, "request_correction", request_id, started.json()["record_version"])

    sign_in(client, "ok")
    corrected = correct(world, request_id, returned.json()["record_version"])
    resubmitted = submit(world, request_id, corrected.json()["request"]["record_version"])

    sign_in_admin(client, "staff_granted")
    reviewed = act(world, "start_review", request_id, resubmitted.json()["record_version"])
    eligible = act(
        world,
        "mark_eligible",
        request_id,
        reviewed.json()["record_version"],
        corrected.json()["revision"]["id"],
    )
    assert eligible.status_code == 200, eligible.text

    actions = audit_actions(world, request_id)

    for expected in (
        "payment_request.review_started",
        "payment_request.correction_requested",
        "payment_request.marked_eligible",
    ):
        assert expected in actions, f"{expected} wrote no audit row for this request"


def test_the_correction_request_records_its_reason_and_message(world: dict[str, Any]) -> None:
    """A request handed back without a recorded reason is one nobody can answer for."""

    request_id, version, _revision_id = a_submitted_request(world)

    sign_in_admin(world["client"], "staff_granted")
    returned = act(world, "request_correction", request_id, version)
    assert returned.status_code == 200, returned.text

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        row = connection.execute(
            "SELECT new_values FROM audit_logs WHERE entity_id = %s AND action = "
            "'payment_request.correction_requested'",
            (request_id,),
        ).fetchone()

    assert row is not None, "the correction request wrote no audit row"
    assert row[0]["reason_code"] == "invalid_iban"
    assert row[0]["message_to_trader"] == "Fix the IBAN."


def test_the_returned_request_carries_the_message_to_its_trader(world: dict[str, Any]) -> None:
    """The precondition for showing it: the note has to reach the trader at all.

    Slice 7 recorded `message_to_trader` in the audit trail and nowhere else, and no trader
    reads audit rows — so a returned request arrived with no reason attached, and the
    trader's rational move was to resubmit it unchanged. Document 04 `:839` has a column for
    it, `review_note`, and slice 7 wrote none of the three review columns. Slice 8 found
    this by trying to build the screen.

    The correction screen's own obligation is named where that screen is tested, not here.
    The traceability scanner counts any occurrence of an id as a citation, so naming it in
    this docstring would have discharged a screen that does not exist — which it did, until
    this sentence replaced it.
    """

    client = world["client"]
    request_id, version, _revision_id = a_submitted_request(world)

    sign_in_admin(client, "staff_granted")
    returned = act(world, "request_correction", request_id, version)
    assert returned.status_code == 200, returned.text

    sign_in(client, "ok")
    detail = client.get(f"/api/v1/payment-requests/{request_id}")

    assert detail.status_code == 200, detail.text
    assert detail.json()["request"]["review_note"] == "Fix the IBAN."
    assert detail.json()["request"]["reviewed_at"] is not None


def test_the_internal_note_reaches_no_response(world: dict[str, Any]) -> None:
    """The other half: `internal_note` is the accountant's own and stays in the audit trail.

    Document 05 `:1131` says trader responses omit internal-only data, and this is that
    data. Asserted against the whole response body rather than one field, because a leak
    would arrive as a field nobody thought about.
    """

    client = world["client"]
    request_id, version, _revision_id = a_submitted_request(world)
    secret = "beneficiary looks like the one from the March dispute"

    sign_in_admin(client, "staff_granted")
    returned = _write(
        client,
        f"/api/v1/payment-requests/{request_id}/request-correction",
        version,
        {
            "reason_code": "invalid_iban",
            "message_to_trader": "Fix the IBAN.",
            "internal_note": secret,
        },
    )
    assert returned.status_code == 200, returned.text

    sign_in(client, "ok")
    detail = client.get(f"/api/v1/payment-requests/{request_id}")
    listing = client.get("/api/v1/payment-requests")

    assert secret not in detail.text
    assert secret not in listing.text
    # And not to the centre either: nothing renders it, so nothing can leak it later by
    # being handed to a screen that shows everything it is given.
    sign_in_admin(client, "staff_granted")
    assert secret not in client.get(f"/api/v1/payment-requests/{request_id}").text


def test_only_the_correction_request_publishes_an_outbox_event(world: dict[str, Any]) -> None:
    """`AUD-REQ-002`, read against the catalogue rather than against the obligation's first
    wording.

    `audit_outbox_catalog.yaml` lists one accountant event, `PaymentRequestCorrectionRequested`,
    and its own open items say the mapping is "exactly one audit action and zero or more
    outbox events" — so a command with no event is anticipated. Publishing invented names
    for the other two would decide an open M0 naming question on the owner's behalf.
    """

    client = world["client"]
    request_id, version, _revision_id = a_submitted_request(world)

    sign_in_admin(client, "staff_granted")
    started = act(world, "start_review", request_id, version)
    assert started.status_code == 200, started.text
    returned = act(world, "request_correction", request_id, started.json()["record_version"])
    assert returned.status_code == 200, returned.text

    events = outbox_events(world, request_id)

    # Exactly two, and the order matters: `start_review` ran between them and published
    # nothing. An `in` assertion would pass while a third event nobody catalogued appeared.
    assert events == ["PaymentRequestSubmitted", "PaymentRequestCorrectionRequested"], events


def test_a_refused_review_action_writes_nothing(world: dict[str, Any]) -> None:
    """The transaction is one unit: a refusal leaves no audit row and no event."""

    request_id, version, revision_id = a_submitted_request(world)
    before_actions = audit_actions(world, request_id)
    before_events = outbox_events(world, request_id)

    sign_in_admin(world["client"], "staff_granted")
    # `mark_eligible` from `submitted_to_center` is an arrow the document does not draw.
    refused = act(world, "mark_eligible", request_id, version, revision_id)
    assert refused.status_code == 400, refused.text

    assert audit_actions(world, request_id) == before_actions
    assert outbox_events(world, request_id) == before_events
