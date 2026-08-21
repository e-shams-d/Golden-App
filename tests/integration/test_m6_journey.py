"""M6's Definition of Done, walked once through the API as the accountant.

`15_Agent_Implementation_Plan.md:897`, verbatim:

> M6 is complete when an accountant can produce an exact immutable batch version ready for
> manager review and all row-level bank data is frozen in relational snapshots.

**The sentence is parsed out of the plan and split into clauses, and each step declares which
clause it discharges.** That is M5's pattern and it is not ceremony: M5's own gate found that its
Definition-of-Done sentence named five clauses where the plan's prose said six steps, so a journey
test written from the prose would have proved something the sentence did not ask for. A sentence
transcribed into a docstring can drift from the sentence; one read from the file cannot.

The second clause is the one most easily satisfied in appearance. "All row-level bank data is
frozen in relational snapshots" is true of a column written once and never read — frozen, and
worthless. So `TRACE-DOD-011` reads every field the export will need **back from the finalized
version**, with the live bank profile version *deactivated first*, so a read that reached for it
would fail rather than quietly agree.

Covers: TRACE-DOD-010, TRACE-DOD-011.
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

TRADER_PHONE = "+989120006001"
IBAN = "IR060120000000000000000046"
BENEFICIARY_NAME = "Ali Six"
DESCRIPTION = "settlement for invoice 42"

LIMIT = 1_000_000_000
# 2.5 billion against a 1 billion limit: two rows at the limit and a residual of half a billion.
# The residual is what a rounding implementation gets wrong, so the journey carries one.
AMOUNT = "2500000000"

PLAN = (
    Path(__file__).resolve().parents[2] / "docs" / "handoff" / "M6_IMPLEMENTATION_PLAN.md"
)


def definition_of_done() -> str:
    """The DoD sentence, read from the plan's own quotation of `:897`.

    Parsed rather than transcribed. The plan quotes it in a blockquote under a heading whose text
    is asserted, so a restructured document fails here instead of silently supplying a different
    sentence.
    """

    text = PLAN.read_text(encoding="utf-8")
    heading = "## 1.2 Definition of Done (verbatim)"
    assert heading in text, f"{heading!r} is gone from the M6 plan; its layout changed"

    section = text[text.index(heading) : text.index("\n## ", text.index(heading) + len(heading))]
    quoted = [
        line.lstrip("> ").strip() for line in section.splitlines() if line.startswith(">")
    ]
    sentence = " ".join(part for part in quoted if part)
    assert sentence.startswith("M6 is complete when"), sentence
    return sentence


def clauses() -> tuple[str, ...]:
    """The DoD's two clauses, split on its own conjunction.

    Two, and the count is asserted below rather than assumed: if the sentence is ever amended to
    name three, a journey covering two would pass while leaving the third unproven.
    """

    sentence = definition_of_done()
    body = sentence.removeprefix("M6 is complete when").strip()
    parts = tuple(part.strip() for part in re.split(r"\band\b", body) if part.strip())
    return parts


@dataclass(frozen=True, slots=True)
class Step:
    """One step of the journey, and the clause it discharges.

    `clause` is an index into `clauses()`, or `None` with a reason. A step that discharges nothing
    is not forbidden — signing in proves no clause — but it has to say so, because "this step is
    here for setup" and "nobody checked which clause this proves" look identical otherwise.
    """

    name: str
    clause: int | None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.clause is None and not self.reason:
            raise ValueError(f"{self.name} discharges no clause and gives no reason")


JOURNEY: tuple[Step, ...] = (
    Step("the trader opens a request", None, reason="M5's surface; the precondition, not the DoD"),
    Step("the trader submits it", None, reason="M5's surface"),
    Step("the accountant starts review", None, reason="M5's surface"),
    Step("the accountant marks it eligible", None, reason="M5's surface; the entry to batching"),
    Step("the accountant previews the batch", None, reason="advisory, and writes nothing"),
    Step("the accountant creates the batch", 0),
    Step("the accountant finalizes the version", 0),
    Step("the frozen row answers without the live profile", 1),
)


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

    ids = {
        name: uuid.uuid4()
        for name in ("trader", "beneficiary", "profile", "version", "account", "mapping")
    }

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'Journey Trader', %s, 'active', 'approved')",
            (ids["trader"], TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (ids["trader"], TRADER_PHONE, encoded),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, %s, %s, %s, 'active', 'not_checked')",
            (ids["beneficiary"], ids["trader"], BENEFICIARY_NAME, IBAN, IBAN),
        )
        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'journey', 'Journey Bank', 'active')",
            (ids["profile"],),
        )
        connection.execute(
            "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, status, "
            "default_transfer_limit_irr, after_cutoff_transfer_limit_irr, cutoff_time, "
            "splitting_enabled, required_fields, rules, config_hash) "
            "VALUES (%s, %s, 1, 'active', %s, NULL, NULL, TRUE, '{}', '{}', %s)",
            (ids["version"], ids["profile"], LIMIT, "5" * 64),
        )
        connection.execute(
            "INSERT INTO bank_accounts (id, bank_profile_id, display_name, iban, "
            "normalized_iban, account_role, status) "
            "VALUES (%s, %s, 'Centre Account', %s, %s, 'outgoing_source', 'active')",
            (ids["account"], ids["profile"], IBAN, IBAN),
        )
        connection.execute(
            "INSERT INTO bank_mappings (id, bank_profile_version_id, file_type, "
            "template_version, status, mapping, config_hash) "
            "VALUES (%s, %s, 'outgoing_excel', 1, 'active', '{}', %s)",
            (ids["mapping"], ids["version"], "6" * 64),
        )
        # One accountant, and nothing else. The DoD says "an accountant can produce", so the
        # journey is walked by exactly that role — a fixture with a manager to hand would let a
        # manager-only requirement slip through unnoticed.
        connection.execute(
            "INSERT INTO admin_users (username, full_name, password_hash, status) "
            "VALUES ('journey_accountant', 'Journey', %s, 'active')",
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
            "owner_url": migrated.owner_url,
            **{f"{name}_id": value for name, value in ids.items()},
        }
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def csrf(client: Any) -> dict[str, str]:
    token = client.cookies.get(TRADER_CSRF_COOKIE) or client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token
    return {CSRF_HEADER: token}


def rows(world: dict[str, Any], sql: str, *parameters: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        return connection.execute(sql, parameters).fetchall()


def test_the_definition_of_done_still_names_two_clauses() -> None:
    """The control on the mapping below, and it is the assertion M5's gate learned to make.

    If the sentence is amended to name three clauses, a journey covering two passes while leaving
    the third unproven — and the failure looks like success. So the count is asserted by equality
    and both clauses are matched by their own words.
    """

    parts = clauses()
    assert len(parts) == 2, f"the DoD now names {len(parts)} clauses: {parts}"

    assert "immutable batch version ready for manager review" in parts[0], parts[0]
    assert "row-level bank data is frozen in relational snapshots" in parts[1], parts[1]


def test_every_journey_step_declares_the_clause_it_discharges() -> None:
    """No step is present without saying why, and both clauses are covered.

    A step that discharges nothing is fine and has to say so. What is not fine is a clause no step
    claims: that is a Definition of Done half-proved by a test that passes.
    """

    covered = {step.clause for step in JOURNEY if step.clause is not None}
    assert covered == {0, 1}, (
        f"the journey covers clauses {sorted(covered)} of {len(clauses())}; every clause needs a "
        "step that claims it"
    )

    for step in JOURNEY:
        if step.clause is None:
            assert step.reason, step.name
        else:
            assert 0 <= step.clause < len(clauses()), step


def test_an_accountant_can_produce_an_exact_immutable_version_ready_for_review(
    world: dict[str, Any],
) -> None:
    """`TRACE-DOD-010`. The whole journey, through the API, as one role.

    Signed in as `journey_accountant` for everything after the trader's own two steps, and the
    fixture creates no other administrator — so a manager-only requirement anywhere in the path
    fails here rather than being masked by a fixture that happened to hold the grant.
    """

    client = world["client"]

    # Steps 1-2: the trader's own. M5's surface, and the precondition rather than the DoD.
    client.cookies.clear()
    assert (
        client.post(
            "/api/v1/auth/trader/login",
            json={"identifier": TRADER_PHONE, "password": PASSWORD},
        ).status_code
        == 200
    )
    created = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiary_id"]),
            "amount": {"value": AMOUNT, "unit": "IRR"},
            "description": DESCRIPTION,
        },
        headers=csrf(client),
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["request"]["id"]
    revision_id = created.json()["revision"]["id"]

    submitted = client.post(
        f"/api/v1/payment-requests/{request_id}/submit",
        json={},
        headers={
            **csrf(client),
            "If-Match": f'"rv-{created.json()["request"]["record_version"]}"',
        },
    )
    assert submitted.status_code == 200, submitted.text

    # Steps 3-8: the accountant's, and only the accountant's.
    client.cookies.clear()
    assert (
        client.post(
            "/api/v1/auth/admin/login",
            json={"identifier": "journey_accountant", "password": PASSWORD},
        ).status_code
        == 200
    )

    reviewing = client.post(
        f"/api/v1/payment-requests/{request_id}/start-review",
        json={},
        headers={**csrf(client), "If-Match": submitted.headers["ETag"]},
    )
    assert reviewing.status_code == 200, reviewing.text
    eligible = client.post(
        f"/api/v1/payment-requests/{request_id}/mark-eligible-for-batching",
        json={"expected_revision_id": revision_id, "review_note": "checked"},
        headers={**csrf(client), "If-Match": reviewing.headers["ETag"]},
    )
    assert eligible.status_code == 200, eligible.text

    selection = {
        "payment_request_id": request_id,
        "expected_revision_id": revision_id,
        "expected_record_version": eligible.json()["record_version"],
    }
    configuration = {
        "bank_profile_version_id": str(world["version_id"]),
        "bank_account_id": str(world["account_id"]),
        "bank_mapping_id": str(world["mapping_id"]),
    }

    # Step 5: the preview. Advisory, and it must leave the request exactly as it found it —
    # otherwise "the accountant looked" would be a state change.
    before = rows(
        world, "SELECT row_to_json(r) FROM payment_requests r WHERE id = %s", request_id
    )
    preview = client.post(
        "/api/v1/payment-batches/preview",
        json={"items": [selection], **configuration},
        headers=csrf(client),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["row_count"] == 3, preview.text
    assert preview.json()["total_amount_irr"] == AMOUNT
    after = rows(
        world, "SELECT row_to_json(r) FROM payment_requests r WHERE id = %s", request_id
    )
    assert after == before, "the preview changed the request it was previewing"

    # Step 6: the batch.
    batch = client.post(
        "/api/v1/payment-batches",
        json={"items": [selection], **configuration},
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert batch.status_code == 201, batch.text
    batch_id = batch.json()["batch"]["id"]
    version_id = batch.json()["current_version"]["id"]
    assert batch.json()["current_version"]["row_count"] == 3
    assert batch.json()["current_version"]["total_amount_irr"] == AMOUNT

    # Step 7: the finalization. This is the sentence's first clause.
    finalized = client.post(
        f"/api/v1/payment-batches/{batch_id}/versions/{version_id}/finalize",
        json={"note": "validated and ready for manager review"},
        headers={
            **csrf(client),
            "If-Match": batch.headers["ETag"],
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["version"]["status"] == "ready_for_approval"
    assert finalized.json()["batch"]["status"] == "ready_for_approval"

    # "Exact" and "immutable", as the sentence says. The hash is unchanged by finalization, and
    # the runtime role holds no UPDATE on the items — asserted as a matrix in
    # `test_batching_table_privileges.py`, and relied on here.
    assert (
        finalized.json()["version"]["content_hash"]
        == batch.json()["current_version"]["content_hash"]
    )

    detail = client.get(f"/api/v1/payment-batches/{batch_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["active_allocation_count"] == 3, (
        "a row does not own its allocation, so the version a manager would review is not one "
        "finalization should have accepted"
    )
    assert [item["amount_irr"] for item in detail.json()["items"]] == [
        str(LIMIT),
        str(LIMIT),
        "500000000",
    ]

    # Nothing in the journey needed a manager. The accountant produced it alone, which is what
    # "an accountant can produce" means, and `test_m6_definition_of_done.py` asserts the
    # structural half — that no batch route *could* have required one.
    assert rows(
        world,
        "SELECT count(*) FROM admin_users u JOIN admin_user_roles ur ON ur.admin_user_id = u.id "
        "JOIN roles r ON r.id = ur.role_id WHERE r.code = 'manager'",
    )[0][0] == 0, "the fixture grew a manager, so this journey no longer proves it needed none"


def test_the_frozen_snapshot_answers_after_the_live_profile_is_deactivated(
    world: dict[str, Any],
) -> None:
    """`TRACE-DOD-011`. The DoD's second clause, and the one satisfied in appearance.

    "All row-level bank data is frozen in relational snapshots" is true of a column written once
    and never read. So this **deactivates the bank profile version** and then reads every field an
    export needs out of the finalized version — the beneficiary name and IBAN, the amount, the
    description, the row order, the configuration ids, and the splitting rules that produced the
    amount.

    Deactivating first is what makes the read meaningful. A snapshot that agreed with a live
    profile would agree either way; a snapshot read while the profile says something else is the
    only proof the value came from the row.
    """

    client = world["client"]
    client.cookies.clear()
    assert (
        client.post(
            "/api/v1/auth/admin/login",
            json={"identifier": "journey_accountant", "password": PASSWORD},
        ).status_code
        == 200
    )

    version = rows(
        world,
        "SELECT v.id FROM payment_batch_versions v WHERE v.status = 'ready_for_approval' "
        "ORDER BY v.created_at DESC LIMIT 1",
    )
    assert version, "no finalized version; the journey test must run first"
    version_id = version[0][0]

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE bank_profile_versions SET status = 'superseded' WHERE id = %s",
            (world["version_id"],),
        )
        connection.commit()
    try:
        frozen = rows(
            world,
            "SELECT i.row_order, i.amount_irr, i.beneficiary_name_snapshot, "
            "i.beneficiary_iban_snapshot, i.description_snapshot, "
            "i.attempt_snapshot->>'bank_profile_version_id', "
            "i.attempt_snapshot->'split_rule_snapshot'->>'default_transfer_limit_irr', "
            "i.row_hash "
            "FROM payment_batch_items i WHERE i.payment_batch_version_id = %s "
            "ORDER BY i.row_order",
            version_id,
        )
        assert len(frozen) == 3, frozen

        for order, amount, name, iban, description, profile_version, limit, row_hash in frozen:
            assert name == BENEFICIARY_NAME, "the payee name is not on the row"
            assert iban == IBAN, "the destination is not on the row"
            assert description == DESCRIPTION
            assert str(profile_version) == str(world["version_id"])
            assert limit == str(LIMIT), (
                "the limit that produced this amount is not on the row, so the split cannot be "
                "explained without a profile that has since been superseded"
            )
            assert len(row_hash) == 64
            assert order in (1, 2, 3)
            assert amount > 0

        assert [row[1] for row in frozen] == [LIMIT, LIMIT, 500_000_000]

        # And the version's own configuration, which the export renders from.
        configuration = rows(
            world,
            "SELECT bank_profile_version_id, bank_account_id, bank_mapping_id, content_hash, "
            "row_count, total_amount_irr FROM payment_batch_versions WHERE id = %s",
            version_id,
        )
        profile_id, account_id, mapping_id, content_hash, row_count, total = configuration[0]
        assert str(profile_id) == str(world["version_id"])
        assert str(account_id) == str(world["account_id"])
        assert str(mapping_id) == str(world["mapping_id"])
        assert len(content_hash) == 64
        assert row_count == 3
        assert total == int(AMOUNT)

        # The route still answers, with the profile superseded. A read that reached for the live
        # profile would fail or return the wrong limit here.
        owning_batch = rows(
            world,
            "SELECT payment_batch_id FROM payment_batch_versions WHERE id = %s",
            version_id,
        )[0][0]
        detail = client.get(f"/api/v1/payment-batches/{owning_batch}")
        assert detail.status_code == 200, detail.text
        assert [item["beneficiary_iban"] for item in detail.json()["items"]] == [IBAN] * 3
    finally:
        with psycopg.connect(_psycopg(world["owner_url"])) as connection:
            connection.execute(
                "UPDATE bank_profile_versions SET status = 'active' WHERE id = %s",
                (world["version_id"],),
            )
            connection.commit()
