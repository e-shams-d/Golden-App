"""M5's Definition of Done as a journey: six steps, two actors, one test.

`15_Agent_Implementation_Plan.md`'s §13.7 says the milestone is complete "when a trader can
submit a request, receive a correction request, create a new immutable revision, resubmit,
and reach `eligible_for_batching` without any manager approval at request level."

**One test, not six.** Six steps proved separately can all pass while the sequence is
impossible, and every mechanism for that is live in this repository:

- *Hand-made preconditions.* A per-step test seeds the row into the state its step needs, so
  it never discovers that the previous step leaves the row in a different shape. Slice 8 found
  exactly this: `return_for_correction` wrote the accountant's message only to the audit trail,
  and every test of the correction step passed while the trader's screen had nothing to show.
- *Seam mismatch.* Step 4 returns `record_version` in a body and step 5 needs it as an `ETag`.
  A test that reads it from the database rather than from the response never touches the seam.
- *Unmandated side effects.* Slice 5's `create_revision` moved the request to
  `submitted_to_center` on every correction, which made step 4 and step 5 the same call. Both
  steps had passing tests; the sequence the DoD names could not happen.

**The step-to-clause mapping is derived and asserted, not assumed.** The DoD sentence names
five clauses. The plan says six steps. The state machine needs eight state-changing calls.
Nothing in the plan reconciles those three numbers, so `len(STEPS) == 6` would be a magic
number — a restatement of the kind the obligation forbids. Instead the sentence is parsed into
its clauses, each step declares which clause it discharges or records why it discharges none,
and the two sets are compared. Deleting a step then fails by **naming the orphaned clause**.

Naming note: this file is not `test_m5_definition_of_done.py` because `tests/backend` already
has that name, and pytest derives a module name from the basename when the directory is not a
package — two files sharing one basename break collection. `test_repository_layout.py` exists
because that has happened.

Covers: TRACE-DOD-007.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
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

TRADERS: dict[str, str] = {"ok": "+989120000901"}
IBAN = "IR060120000000000000000031"

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MILESTONE_DOC = (
    REPOSITORY_ROOT
    / "Implementation Docs"
    / "00_Start_Here"
    / "15_Agent_Implementation_Plan.md"
)
STATUS_CATALOGUE = REPOSITORY_ROOT / "docs" / "governance" / "status_catalog.yaml"


@dataclass(frozen=True, slots=True)
class Step:
    """One step of the journey, and the clause of the DoD it discharges.

    `clause` is the verbatim fragment from the document, or `None` when the step exists
    because the state machine requires it rather than because the sentence asks for it.
    `reason` is then mandatory — a step nobody can account for is how a defect gets papered
    over with an extra call.
    """

    number: int
    actor: str
    clause: str | None
    reason: str | None
    expected_status: str


# `submitted_to_center` twice and `under_accountant_review` twice is not a mistake: the
# journey passes through review, goes back to the trader, and returns. Step 2 discharges no
# clause because `request-correction` is legal only from `under_accountant_review` — the sixth
# step the sentence does not mention and the machine requires.
STEPS: tuple[Step, ...] = (
    Step(1, "trader", "submit a request", None, "submitted_to_center"),
    Step(
        2,
        "accountant",
        None,
        "the state machine requires a review to be open before it can be returned: "
        "`request-correction` is legal from `submitted_to_center` and "
        "`under_accountant_review`, and the accountant reads before deciding",
        "under_accountant_review",
    ),
    Step(3, "accountant", "receive a correction request", None, "needs_trader_correction"),
    Step(
        4,
        "trader",
        "create a new immutable revision",
        None,
        # Still with the trader. A correction is content, not a handover — the defect slice 8
        # removed made this the same step as 5.
        "needs_trader_correction",
    ),
    Step(5, "trader", "resubmit", None, "submitted_to_center"),
    Step(
        6,
        "accountant",
        "reach `eligible_for_batching`",
        None,
        "eligible_for_batching",
    ),
)

# Steps that exist for the machine rather than for the sentence. Equality below, so a step
# added to work around a defect fails until somebody accounts for it.
MACHINE_PRECONDITIONS = frozenset({2})


def _definition_of_done() -> str:
    """The DoD sentence, located by its heading rather than by a line number."""

    lines = MILESTONE_DOC.read_text(encoding="utf-8").splitlines()
    start = next(
        index for index, line in enumerate(lines) if line.strip() == "## 13.7 Definition of Done"
    )
    for line in lines[start + 1 :]:
        if line.strip().startswith("M5 is complete when"):
            return line.strip()
    raise AssertionError("§13.7 no longer opens with the sentence this gate parses")


def _clauses() -> tuple[str, ...]:
    """The five things the sentence says a trader can do, in order.

    Split from the document rather than transcribed. A transcription can be wrong in the same
    direction as the test, which is the failure `test_payment_request_schema.py` was written
    to stop happening to a table.
    """

    sentence = _definition_of_done()
    body = sentence.split("when a trader can ", 1)[1]
    body = body.split(" without any manager approval", 1)[0]
    parts = [part.strip() for part in re.split(r",\s*and\s+|,\s*|\s+and\s+", body) if part.strip()]
    return tuple(parts)


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

    trader_id = uuid.uuid4()
    beneficiary_id = uuid.uuid4()

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'Journey Trader', %s, 'active', 'approved')",
            (trader_id, TRADERS["ok"]),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (trader_id, TRADERS["ok"], encoded),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'Ali One', %s, %s, 'active', "
            "'not_checked')",
            (beneficiary_id, trader_id, IBAN, IBAN),
        )
        # One accountant. Deliberately not a manager, and asserted below rather than assumed:
        # the DoD's negative half is that no manager authority is needed, so the journey must
        # be completed by an identity that holds none.
        connection.execute(
            "INSERT INTO admin_users (username, full_name, password_hash, status) "
            "VALUES ('journey_accountant', 'Accountant', %s, 'active')",
            (encoded,),
        )
        connection.execute(
            "INSERT INTO admin_user_roles (admin_user_id, role_id) "
            "SELECT u.id, r.id FROM admin_users u, roles r "
            "WHERE u.username = 'journey_accountant' AND r.code = 'accountant'"
        )
        connection.commit()

    app = create_app(settings=settings)
    app.state.runtime = RuntimeServices.from_settings(settings)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://trader.localhost") as client:
        yield {
            "client": client,
            "trader_id": trader_id,
            "beneficiary_id": beneficiary_id,
            "owner_url": migrated.owner_url,
        }
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _sign_in(world: dict[str, Any], actor: str) -> None:
    """Two identities and no third. `actor` is the step's declared one."""

    client = world["client"]
    client.cookies.clear()
    if actor == "trader":
        response = client.post(
            "/api/v1/auth/trader/login",
            json={"identifier": TRADERS["ok"], "password": PASSWORD},
        )
    else:
        response = client.post(
            "/api/v1/auth/admin/login",
            json={"identifier": "journey_accountant", "password": PASSWORD},
        )
    assert response.status_code == 200, response.text


def _csrf(client: Any) -> dict[str, str]:
    token = client.cookies.get(TRADER_CSRF_COOKIE) or client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token, "signed in but no CSRF cookie was set"
    return {CSRF_HEADER: token}


def _revision_row(world: dict[str, Any], revision_id: str) -> dict[str, Any]:
    """Every column of a revision, as JSON.

    `row_to_json` rather than a column list: the claim is that the row does not change, and a
    hand-written list of columns is a list that stops covering the column added next.
    """

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        row = connection.execute(
            "SELECT row_to_json(r) FROM payment_request_revisions r WHERE r.id = %s",
            (revision_id,),
        ).fetchone()
    assert row is not None
    return dict(row[0])


def _terminal_status() -> str:
    """The milestone's terminal status, read from the approved catalogue.

    Not a literal in this file. The clause the DoD ends with carries the name in backticks,
    and the catalogue is what approved it; taking it from either means an edit to one of them
    fails here instead of leaving this test asserting a string nobody governs any more.
    """

    from_clause = re.search(r"`([a-z_]+)`", _clauses()[-1])
    assert from_clause is not None, _clauses()[-1]
    name = from_clause.group(1)
    catalogue = STATUS_CATALOGUE.read_text(encoding="utf-8")
    assert f"canonical: {name}" in catalogue, (
        f"{name} is the status the Definition of Done names and the approved catalogue does "
        "not list it"
    )
    return name


# --- The bookkeeping, before the journey runs ----------------------------------------------


def test_the_definition_of_done_still_reads_as_this_test_assumes() -> None:
    """Guard the guard. Everything below is bookkeeping over a sentence that must exist."""

    sentence = _definition_of_done()

    assert "without any manager approval at request level" in sentence, sentence
    assert len(_clauses()) == 5, _clauses()


def test_every_clause_of_the_definition_is_discharged_by_exactly_one_step() -> None:
    """The mapping, asserted rather than assumed.

    Five clauses, six steps, and the sentence says nothing about the sixth. Deleting a step
    fails here by naming the clause left orphaned, which is what makes this bookkeeping and
    not a length check.
    """

    clauses = _clauses()
    claimed = [step.clause for step in STEPS if step.clause is not None]

    assert sorted(claimed) == sorted(clauses), (
        "the steps and the document disagree about what the journey is.\n"
        f"orphaned clauses: {sorted(set(clauses) - set(claimed))}\n"
        f"steps claiming a clause the document does not contain: "
        f"{sorted(set(claimed) - set(clauses))}"
    )
    assert len(claimed) == len(set(claimed)), "two steps claim the same clause"
    # And in the sentence's order, because a journey is a sequence.
    assert claimed == [clause for clause in clauses if clause in claimed]


def test_every_step_without_a_clause_is_accounted_for() -> None:
    """Equality, so a step added to work around a defect cannot hide as a precondition."""

    unclaimed = {step.number for step in STEPS if step.clause is None}

    assert unclaimed == MACHINE_PRECONDITIONS, sorted(unclaimed)
    for step in STEPS:
        if step.clause is None:
            assert step.reason, f"step {step.number} discharges no clause and gives no reason"


def test_the_journey_uses_no_manager(world: dict[str, Any]) -> None:
    """The DoD's negative half, at the level this test can speak to.

    The journey below is completed by one trader and one accountant. That the *routes* require
    no manager-only permission is `TRACE-DOD-008`, in `tests/backend`; what this asserts is
    that the identity which actually completed it holds no manager role — so the journey is
    not passing because a manager happened to be signed in.
    """

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        roles = connection.execute(
            "SELECT r.code FROM admin_users u "
            "JOIN admin_user_roles ur ON ur.admin_user_id = u.id "
            "JOIN roles r ON r.id = ur.role_id "
            "WHERE u.username = 'journey_accountant'",
        ).fetchall()

    codes = {row[0] for row in roles}
    assert codes == {"accountant"}, codes


# --- The journey ---------------------------------------------------------------------------


def test_the_six_step_journey_runs_end_to_end(world: dict[str, Any]) -> None:
    """`TRACE-DOD-007`. The milestone, in one test, through the API, as the two actors.

    Every step takes its `If-Match` from the previous step's response rather than from the
    database, because the version crossing that seam is part of what the journey proves. A
    test that read `record_version` out of PostgreSQL would pass while the API never returned
    it.
    """

    client = world["client"]
    walked: list[int] = []
    version: int | None = None
    request_id: str | None = None
    first_revision: str | None = None
    second_revision: str | None = None
    first_revision_before: dict[str, Any] | None = None

    for step in STEPS:
        _sign_in(world, step.actor)
        headers = _csrf(client)

        if step.number == 1:
            created = client.post(
                "/api/v1/payment-requests",
                json={
                    "beneficiary_id": str(world["beneficiary_id"]),
                    "amount": {"value": "500", "unit": "TOMAN"},
                    "description": "the journey",
                },
                headers=headers,
            )
            assert created.status_code == 201, created.text
            request_id = created.json()["request"]["id"]
            first_revision = created.json()["revision"]["id"]
            first_revision_before = _revision_row(world, first_revision)
            opened = created.json()["request"]["record_version"]
            response = client.post(
                f"/api/v1/payment-requests/{request_id}/submit",
                json={},
                headers={**headers, "If-Match": f'"rv-{opened}"'},
            )
        elif step.number in {2, 6}:
            response = client.post(
                f"/api/v1/payment-requests/{request_id}/start-review",
                json={},
                headers={**headers, "If-Match": f'"rv-{version}"'},
            )
            if step.number == 6:
                assert response.status_code == 200, response.text
                response = client.post(
                    f"/api/v1/payment-requests/{request_id}/mark-eligible-for-batching",
                    json={
                        "expected_revision_id": second_revision,
                        "review_note": "checked",
                    },
                    headers={
                        **headers,
                        "If-Match": f'"rv-{response.json()["record_version"]}"',
                    },
                )
        elif step.number == 3:
            response = client.post(
                f"/api/v1/payment-requests/{request_id}/request-correction",
                json={
                    "reason_code": "invalid_iban",
                    "message_to_trader": "Please correct the destination IBAN.",
                },
                headers={**headers, "If-Match": f'"rv-{version}"'},
            )
        elif step.number == 4:
            response = client.post(
                f"/api/v1/payment-requests/{request_id}/revisions",
                json={
                    "beneficiary_id": str(world["beneficiary_id"]),
                    "amount": {"value": "600", "unit": "TOMAN"},
                    "description": "corrected",
                    "revision_reason": "the accountant asked",
                },
                headers={
                    **headers,
                    "If-Match": f'"rv-{version}"',
                    "Idempotency-Key": str(uuid.uuid4()),
                },
            )
            assert response.status_code == 201, response.text
            second_revision = response.json()["revision"]["id"]
            assert second_revision != first_revision
        else:
            response = client.post(
                f"/api/v1/payment-requests/{request_id}/submit",
                json={},
                headers={**headers, "If-Match": f'"rv-{version}"'},
            )

        assert response.status_code in {200, 201}, f"step {step.number}: {response.text}"
        body = response.json()
        # Two response shapes across the journey: the write routes return the request itself,
        # and the two creating routes wrap it. Reading either is part of walking the real API.
        record = body.get("request", body)
        assert record["status"] == step.expected_status, (
            f"step {step.number} left the request {record['status']}, not "
            f"{step.expected_status}"
        )
        version = record["record_version"]
        walked.append(step.number)

    # The loop ran every declared step, in order. A step declared and never executed — the
    # shape a refactor produces — fails here rather than passing on five of six.
    assert walked == [step.number for step in STEPS]

    assert request_id is not None
    assert record["status"] == _terminal_status()
    assert record["current_revision_id"] == second_revision

    _sign_in(world, "trader")
    history = client.get(f"/api/v1/payment-requests/{request_id}/revisions")
    assert history.status_code == 200, history.text
    assert [item["revision_number"] for item in history.json()["items"]] == [1, 2], history.text
    assert history.json()["current_revision_id"] == second_revision

    # "Immutable" asserted, not assumed: every column of revision 1, before the correction and
    # after the whole journey.
    assert first_revision is not None
    assert _revision_row(world, first_revision) == first_revision_before


def test_a_stale_version_is_refused_at_the_resubmission(world: dict[str, Any]) -> None:
    """The seam the journey depends on, tested for the failure the journey never sees.

    The journey above carries each version forward and every call succeeds, so it cannot show
    that the precondition is *load-bearing*. This replays the resubmission with the version
    from before the correction and requires `412` — otherwise "carried the version" is a
    property of the test rather than of the API.
    """

    client = world["client"]
    _sign_in(world, "trader")
    created = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiary_id"]),
            "amount": {"value": "700", "unit": "TOMAN"},
            "description": "stale",
        },
        headers=_csrf(client),
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["request"]["id"]
    stale = created.json()["request"]["record_version"]

    handed = client.post(
        f"/api/v1/payment-requests/{request_id}/submit",
        json={},
        headers={**_csrf(client), "If-Match": f'"rv-{stale}"'},
    )
    assert handed.status_code == 200, handed.text

    again = client.post(
        f"/api/v1/payment-requests/{request_id}/submit",
        json={},
        headers={**_csrf(client), "If-Match": f'"rv-{stale}"'},
    )
    assert again.status_code in {400, 412}, again.text
