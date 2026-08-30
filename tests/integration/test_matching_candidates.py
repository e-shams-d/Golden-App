"""A suggestion is recorded, decided, and never allowed to decide anything financial.

M9 slice 1, against a real PostgreSQL.

**The milestone's first property is a negative one, and it is asserted three ways.**
`04_Database_Schema.md:1274`, `15_Agent_Implementation_Plan.md:1102` and
`command_catalog.yaml:296` all say that accepting a candidate does not mark an attempt paid. Three
documents guarding one rule is a warning that it is easy to break by accident, so:

- the attempt's **whole row** is read through `row_to_json` before and after acceptance and
  compared for byte equality — `status`, `confirmed_at` and `confirmed_by_admin_user_id` are three
  separate ways for this to go wrong and one assertion covers all of them;
- the runtime role's privileges on `payment_attempts` are read from `information_schema`, so the
  claim is about what the process *can* do rather than about what this slice's code happens to do;
- and the second of those is what makes the first meaningful. A behavioural test alone would pass
  against an implementation that simply had not written the update yet.

**Two administrators with different grants, deliberately.** `candidate_accountant` holds
`matching_candidate.create` and `.review`; `candidate_worker` holds `create` and **not** `.review`
(`20260801_0008:354`), which is what makes the decision negatives prove the routes want *that*
grant rather than merely some candidate grant. A test using only a role holding neither would pass
against a route guarded by any permission at all.

Covers: SVC-CANDIDATE-001, SVC-CANDIDATE-002, SEC-CANDIDATE-001, AUD-CANDIDATE-001.
`DB-CANDIDATE-001` is `tests/backend/test_candidate_schema.py`, which needs no database.
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

TRADER_PHONE = "+989120005801"
IBAN = "IR060120000000000000000058"

ACCEPT_ACTION = "matching_candidate.accepted_for_confirmation"


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
        local_storage_root=tmp_path_factory.mktemp("candidate-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="f" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    ids = {
        name: uuid.uuid4()
        for name in ("trader", "beneficiary", "profile", "version", "account", "file")
    }

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'Candidate Trader', %s, 'active', 'approved')",
            (ids["trader"], TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (ids["trader"], TRADER_PHONE, encoded),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'Ali Seven', %s, %s, 'active', "
            "'not_checked')",
            (ids["beneficiary"], ids["trader"], IBAN, IBAN),
        )
        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'parsian', 'Bank Parsian', 'active')",
            (ids["profile"],),
        )
        connection.execute(
            "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, status, "
            "default_transfer_limit_irr, after_cutoff_transfer_limit_irr, cutoff_time, "
            "splitting_enabled, required_fields, rules, config_hash) "
            "VALUES (%s, %s, 1, 'active', 1000000000, NULL, NULL, TRUE, '{}', '{}', %s)",
            (ids["version"], ids["profile"], "7" * 64),
        )
        connection.execute(
            "INSERT INTO bank_accounts (id, bank_profile_id, display_name, iban, "
            "normalized_iban, account_role, status) "
            "VALUES (%s, %s, 'Centre Account', %s, %s, 'outgoing_source', 'active')",
            (ids["account"], ids["profile"], IBAN, IBAN),
        )
        # A file for the segment to have been cut from. `20260801_0011`'s conditional constraint
        # makes `available` mean hashed *and* scanned clean, so both are set.
        connection.execute(
            "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
            "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
            "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
            "original_or_derived_relation, metadata) "
            "VALUES (%s, 'local', 'gold', %s, 'receipt.pdf', 'application/pdf', 1024, %s, "
            "'bank_result_bundle_source', 'internal', 'available', 'clean', 'admin_user', "
            "'original', '{}')",
            (ids["file"], f"candidates/{ids['file']}", "a" * 64),
        )
        for username, role in (
            # Holds both candidate permissions (`20260801_0008:238-239`).
            ("candidate_accountant", "accountant"),
            # Holds `matching_candidate.create` and **not** `.review` (`:354`). The sharp negative
            # for both decision routes: it gets past any "some candidate grant" guard and must
            # still be refused.
            ("candidate_worker", "system_worker"),
            # Holds neither, which is the negative for the proposal route.
            ("candidate_manager", "manager"),
        ):
            connection.execute(
                "INSERT INTO admin_users (username, full_name, password_hash, status) "
                "VALUES (%s, %s, %s, 'active')",
                (username, username, encoded),
            )
            connection.execute(
                "INSERT INTO admin_user_roles (admin_user_id, role_id) "
                "SELECT u.id, r.id FROM admin_users u, roles r "
                "WHERE u.username = %s AND r.code = %s",
                (username, role),
            )
        connection.commit()

    app = create_app(settings=settings)
    app.state.runtime = RuntimeServices.from_settings(settings)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://trader.localhost") as client:
        yield {
            "client": client,
            "app_role": migrated.app_role,
            "owner_url": migrated.owner_url,
            **{f"{name}_id": value for name, value in ids.items()},
        }
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def sign_in_admin(client: Any, username: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def csrf(client: Any) -> dict[str, str]:
    token = client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token, "signed in but no CSRF cookie was set"
    return {CSRF_HEADER: token}


def rows(world: dict[str, Any], sql: str, *parameters: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        return connection.execute(sql, parameters).fetchall()


def an_attempt(world: dict[str, Any], *, amount: int = 900_000_000) -> uuid.UUID:
    """One payment attempt, inserted directly.

    **Built with SQL rather than through the batching routes on purpose.** This module's subject
    is what a candidate may do *to* an attempt, and driving M5 through M7 to produce one would
    make every test here depend on four milestones' worth of behaviour. What matters is that the
    row is real and its columns are the ones slice 3 will write; nothing here exercises how it
    came to exist.
    """

    request_id = uuid.uuid4()
    revision_id = uuid.uuid4()
    attempt_id = uuid.uuid4()

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO payment_requests (id, trader_id, beneficiary_id, request_number, "
            "status, record_version) VALUES (%s, %s, %s, %s, 'sent_to_bank', 1)",
            (
                request_id,
                world["trader_id"],
                world["beneficiary_id"],
                f"PR-{str(request_id)[:8]}",
            ),
        )
        connection.execute(
            "INSERT INTO payment_request_revisions (id, payment_request_id, revision_number, "
            "beneficiary_id, beneficiary_name_snapshot, beneficiary_iban_snapshot, amount_irr, "
            "content_hash, created_by_actor_type) "
            "VALUES (%s, %s, 1, %s, 'Ali Seven', %s, %s, %s, 'trader_user')",
            (
                revision_id,
                request_id,
                world["beneficiary_id"],
                IBAN,
                amount,
                "b" * 64,
            ),
        )
        connection.execute(
            "UPDATE payment_requests SET current_revision_id = %s WHERE id = %s",
            (revision_id, request_id),
        )
        connection.execute(
            "INSERT INTO payment_attempts (id, payment_request_id, "
            "payment_request_revision_id, attempt_number, attempt_type, amount_irr, "
            "beneficiary_name_snapshot, beneficiary_iban_snapshot, bank_profile_version_id, "
            "bank_account_id, split_rule_snapshot, status, record_version) "
            "VALUES (%s, %s, %s, 1, 'original', %s, 'Ali Seven', %s, %s, %s, '{}', "
            "'sent_to_bank', 1)",
            (
                attempt_id,
                request_id,
                revision_id,
                amount,
                IBAN,
                world["version_id"],
                world["account_id"],
            ),
        )
        connection.commit()
    return attempt_id


def a_segment(world: dict[str, Any], *, status: str = "unmatched") -> uuid.UUID:
    segment_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO receipt_segments (id, source_file_id, rotation_degrees, "
            "creation_method, status, raw_extraction, created_by_actor_type, record_version) "
            "VALUES (%s, %s, 0, 'manual_external_attachment', %s, '{}', 'admin_user', 1)",
            (segment_id, world["file_id"], status),
        )
        connection.commit()
    return segment_id


def propose(
    world: dict[str, Any], segment_id: uuid.UUID, attempt_id: uuid.UUID, **overrides: Any
) -> Any:
    client = world["client"]
    body: dict[str, Any] = {"payment_attempt_id": str(attempt_id)}
    body.update(overrides)
    return client.post(
        f"/api/v1/receipt-segments/{segment_id}/matching-candidates",
        json=body,
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )


def accept(world: dict[str, Any], candidate_id: str, *, key: str | None = None) -> Any:
    client = world["client"]
    return client.post(
        f"/api/v1/matching-candidates/{candidate_id}/accept-for-confirmation",
        json={},
        headers={**csrf(client), "Idempotency-Key": key or str(uuid.uuid4())},
    )


def reject(world: dict[str, Any], candidate_id: str, *, reason: str | None = None) -> Any:
    client = world["client"]
    return client.post(
        f"/api/v1/matching-candidates/{candidate_id}/reject",
        json={"reason": reason} if reason is not None else {},
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )


def attempt_row(world: dict[str, Any], attempt_id: uuid.UUID) -> Any:
    """The attempt's entire row as JSON, so a comparison covers every column at once."""

    found = rows(
        world,
        "SELECT row_to_json(pa) FROM payment_attempts pa WHERE id = %s",
        attempt_id,
    )
    assert found, "the attempt disappeared"
    return found[0][0]


# ---------------------------------------------------------------------------------------------
# The negative the whole milestone rests on.
# ---------------------------------------------------------------------------------------------


def test_accepting_a_candidate_changes_nothing_about_the_attempt(
    world: dict[str, Any],
) -> None:
    """`SVC-CANDIDATE-001`. `04_Database_Schema.md:1274` and §17 `:1102`, asserted.

    **Byte equality over the whole row, not a check of three columns.** `status`, `confirmed_at`
    and `confirmed_by_admin_user_id` are the obvious ways this goes wrong, and `record_version`,
    `bank_result_at` and `bank_tracking_number` are three more. Naming them individually is how a
    test passes while a seventh column moves.
    """

    attempt_id = an_attempt(world)
    segment_id = a_segment(world)
    sign_in_admin(world["client"], "candidate_accountant")

    before = attempt_row(world, attempt_id)

    created = propose(world, segment_id, attempt_id)
    assert created.status_code == 201, created.text
    candidate_id = created.json()["id"]

    accepted = accept(world, candidate_id)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted_for_confirmation"

    assert attempt_row(world, attempt_id) == before, (
        "accepting a candidate moved the attempt. 04_Database_Schema.md:1274 says a human "
        "confirmation command is what does that, and it does not exist until slice 3."
    )

    # And no evidence link either — `command_catalog.yaml:296`'s other precondition,
    # `does_not_confirm_evidence`.
    #
    # **This assertion was a structural absence and is now a count.** Slice 1 could only check
    # that `confirmed_evidence_links` did not exist, and said so in a message that fired the day
    # slice 2 created it. That is the shape M8's screens work settled on: when an absence stops
    # being literal, the claim becomes reachability, and the guard that notices is written at the
    # same time as the weaker assertion rather than remembered later.
    assert rows(
        world,
        "SELECT count(*) FROM confirmed_evidence_links WHERE payment_attempt_id = %s",
        attempt_id,
    ) == [(0,)], (
        "accepting a candidate created a confirmed evidence link. `command_catalog.yaml:296` "
        "names `does_not_confirm_evidence` as a precondition of this command, and slice 2's "
        "`POST /evidence-links` is what a human uses instead."
    )


def test_the_runtime_holds_no_privilege_on_payment_attempts_after_this_slice(
    world: dict[str, Any],
) -> None:
    """`SEC-CANDIDATE-001`, and it is what makes the test above mean something.

    A behavioural assertion that acceptance did not write an attempt passes equally well against
    an implementation that simply has not written the update *yet*. This one reads what the
    process is permitted to do, from `information_schema`, as the role the application actually
    connects with.

    **`SELECT` and `INSERT` are expected**: M6 creates attempts and every read needs them. What
    must be absent is `UPDATE`, which is the privilege slice 3 adds column by column — and when
    slice 3 lands, this test changes to name exactly those columns rather than being deleted.
    """

    granted = rows(
        world,
        "SELECT DISTINCT privilege_type FROM information_schema.table_privileges "
        "WHERE table_name = 'payment_attempts' AND grantee = %s ORDER BY privilege_type",
        world["app_role"],
    )
    held = {row[0] for row in granted}

    assert "UPDATE" not in held, (
        f"the runtime can UPDATE payment_attempts and slice 1 grants no such thing: "
        f"{sorted(held)}. Accepting a candidate is then one line away from marking a payment paid."
    )
    assert "DELETE" not in held, f"the runtime can DELETE payment_attempts: {sorted(held)}"
    # The control: a query returning nothing at all would satisfy both assertions above while
    # proving the role cannot read the table either, which would mean the query is wrong.
    assert "SELECT" in held, (
        f"the runtime cannot even read payment_attempts ({sorted(held)}), so this query is not "
        "finding the grants and the absences above prove nothing"
    )


# ---------------------------------------------------------------------------------------------
# The reason rule, both cases.
# ---------------------------------------------------------------------------------------------


def test_a_rejection_without_a_reason_is_refused(world: dict[str, Any]) -> None:
    """`SVC-CANDIDATE-002`, first case.

    `05_API_Specification.md:1820` requires a reason for a high-confidence candidate and gives no
    threshold anywhere, so the implementation requires one always and says so. Asserted here with
    a scored candidate, which is the case the document certainly covers.
    """

    attempt_id = an_attempt(world)
    segment_id = a_segment(world)
    sign_in_admin(world["client"], "candidate_accountant")

    created = propose(world, segment_id, attempt_id, score="0.97", method="rule_engine")
    assert created.status_code == 201, created.text
    candidate_id = created.json()["id"]

    refused = reject(world, candidate_id)
    assert refused.status_code == 400, refused.text
    assert "reason" in refused.text

    assert rows(
        world, "SELECT status FROM matching_candidates WHERE id = %s", candidate_id
    ) == [("proposed",)]

    accepted = reject(world, candidate_id, reason="the tracking number belongs to another payment")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "rejected"


def test_an_accepted_candidate_can_be_overridden_and_the_override_needs_a_reason(
    world: dict[str, Any],
) -> None:
    """`SVC-CANDIDATE-002`, second case — and the transition the first model refused.

    `:1820` requires a reason when "overriding a previously accepted candidate", which only means
    something if acceptance can be undone. The first version of `PERMITTED_TRANSITIONS` made
    `accepted_for_confirmation` terminal and would have answered 400 to an operation the API
    specification describes. Being stricter than an approved document is still deviation.
    """

    attempt_id = an_attempt(world)
    segment_id = a_segment(world)
    sign_in_admin(world["client"], "candidate_accountant")

    created = propose(world, segment_id, attempt_id)
    candidate_id = created.json()["id"]
    assert accept(world, candidate_id).status_code == 200

    refused = reject(world, candidate_id)
    assert refused.status_code == 400, refused.text

    overridden = reject(world, candidate_id, reason="accepted in error; wrong attempt")
    assert overridden.status_code == 200, overridden.text
    assert overridden.json()["status"] == "rejected"

    # §21.2: "Candidate reasons, score, algorithm/provider version, and input snapshot are
    # retained." The row is never deleted, and its identity is unchanged.
    kept = rows(
        world,
        "SELECT receipt_segment_id, payment_attempt_id, method FROM matching_candidates "
        "WHERE id = %s",
        candidate_id,
    )
    assert kept == [(segment_id, attempt_id, "manual")]


def test_a_rejected_candidate_takes_no_further_decision(world: dict[str, Any]) -> None:
    """The transition table's terminal states, provoked rather than read.

    `status_catalog.yaml` marks `rejected` terminal. Without this, `PERMITTED_TRANSITIONS` is a
    dictionary nothing consults.
    """

    attempt_id = an_attempt(world)
    segment_id = a_segment(world)
    sign_in_admin(world["client"], "candidate_accountant")

    candidate_id = propose(world, segment_id, attempt_id).json()["id"]
    assert reject(world, candidate_id, reason="not this one").status_code == 200

    refused = accept(world, candidate_id)
    assert refused.status_code == 400, refused.text
    assert "rejected" in refused.text


# ---------------------------------------------------------------------------------------------
# What the proposal does to the segment, and to nothing else.
# ---------------------------------------------------------------------------------------------


def test_a_proposal_moves_the_segment_to_candidate_found(world: dict[str, Any]) -> None:
    """`06_Workflows_and_State_Machines.md:1062`: `unmatched --> candidate_found`.

    The one status change a suggestion is allowed to cause, and it is on the segment rather than
    on anything financial. A segment already past that point keeps its status, which the second
    half asserts — the arrow exists only from `created` and `unmatched`.
    """

    attempt_id = an_attempt(world)
    segment_id = a_segment(world, status="unmatched")
    sign_in_admin(world["client"], "candidate_accountant")

    assert propose(world, segment_id, attempt_id).status_code == 201
    assert rows(
        world, "SELECT status FROM receipt_segments WHERE id = %s", segment_id
    ) == [("candidate_found",)]

    linked = a_segment(world, status="confirmed_linked")
    assert propose(world, linked, an_attempt(world)).status_code == 201
    assert rows(world, "SELECT status FROM receipt_segments WHERE id = %s", linked) == [
        ("confirmed_linked",)
    ], "a suggestion rewrote a segment that had already been decided"


def test_the_same_pair_takes_one_candidate_per_method(world: dict[str, Any]) -> None:
    """§12.5's unique, and why `method` is in it.

    A rule engine and a person may both suggest the same link; collapsing those would lose which
    one a reviewer accepted. So the same method twice is refused and a second method is not.
    """

    attempt_id = an_attempt(world)
    segment_id = a_segment(world)
    sign_in_admin(world["client"], "candidate_accountant")

    assert propose(world, segment_id, attempt_id).status_code == 201
    again = propose(world, segment_id, attempt_id)
    assert again.status_code == 409, again.text

    other = propose(world, segment_id, attempt_id, method="rule_engine", score="0.4")
    assert other.status_code == 201, other.text


def test_a_replayed_proposal_creates_one_candidate(world: dict[str, Any]) -> None:
    """Idempotency, and the reason it is required although no catalogue row asks.

    Without a key the retry is refused by the unique as a 409, which tells the client somebody
    else proposed this link — when in fact they did it themselves.
    """

    attempt_id = an_attempt(world)
    segment_id = a_segment(world)
    client = world["client"]
    sign_in_admin(client, "candidate_accountant")

    key = str(uuid.uuid4())
    body = {"payment_attempt_id": str(attempt_id)}
    first = client.post(
        f"/api/v1/receipt-segments/{segment_id}/matching-candidates",
        json=body,
        headers={**csrf(client), "Idempotency-Key": key},
    )
    assert first.status_code == 201, first.text
    second = client.post(
        f"/api/v1/receipt-segments/{segment_id}/matching-candidates",
        json=body,
        headers={**csrf(client), "Idempotency-Key": key},
    )
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]

    assert rows(
        world,
        "SELECT count(*) FROM matching_candidates WHERE receipt_segment_id = %s",
        segment_id,
    ) == [(1,)]


def test_the_proposal_requires_an_idempotency_key(world: dict[str, Any]) -> None:
    attempt_id = an_attempt(world)
    segment_id = a_segment(world)
    client = world["client"]
    sign_in_admin(client, "candidate_accountant")

    refused = client.post(
        f"/api/v1/receipt-segments/{segment_id}/matching-candidates",
        json={"payment_attempt_id": str(attempt_id)},
        headers=csrf(client),
    )
    assert refused.status_code == 428, refused.text


# ---------------------------------------------------------------------------------------------
# Audit.
# ---------------------------------------------------------------------------------------------


def test_acceptance_writes_the_catalogued_audit_action(world: dict[str, Any]) -> None:
    """`AUD-CANDIDATE-001`. `audit_outbox_catalog.yaml:39` names it, and this is the one M9 name
    that needed nothing invented.

    The row records **both sides** of the suggestion, because an audit reader asking what was
    accepted needs the segment and the attempt — the candidate id alone resolves to a row whose
    own columns could not be read from an audit trail.

    **And no outbox event**, which `command_catalog.yaml:298` states as `outbox_event: null`.
    Asserted rather than assumed: an invented `MatchingCandidateAccepted` would be an event type
    no consumer contract names.
    """

    attempt_id = an_attempt(world)
    segment_id = a_segment(world)
    sign_in_admin(world["client"], "candidate_accountant")

    candidate_id = propose(world, segment_id, attempt_id).json()["id"]
    before = rows(world, "SELECT count(*) FROM outbox_events")[0][0]
    assert accept(world, candidate_id).status_code == 200

    audited = rows(
        world,
        "SELECT action, new_values->>'status', new_values->>'receipt_segment_id', "
        "new_values->>'payment_attempt_id', previous_values->>'status' "
        "FROM audit_logs WHERE entity_id = %s AND action = %s",
        candidate_id,
        ACCEPT_ACTION,
    )
    assert audited == [
        (
            ACCEPT_ACTION,
            "accepted_for_confirmation",
            str(segment_id),
            str(attempt_id),
            "proposed",
        )
    ], audited

    assert rows(world, "SELECT count(*) FROM outbox_events")[0][0] == before, (
        "acceptance published an outbox event; command_catalog.yaml:298 gives it "
        "outbox_event: null"
    )


# ---------------------------------------------------------------------------------------------
# Permission negatives, one per route.
# ---------------------------------------------------------------------------------------------


def test_proposing_needs_the_create_permission(world: dict[str, Any]) -> None:
    """`manager` holds neither candidate permission (`20260801_0008:238-239,354`)."""

    attempt_id = an_attempt(world)
    segment_id = a_segment(world)

    sign_in_admin(world["client"], "candidate_manager")
    assert propose(world, segment_id, attempt_id).status_code == 403

    sign_in_admin(world["client"], "candidate_accountant")
    assert propose(world, segment_id, attempt_id).status_code == 201


def test_accepting_needs_the_review_permission(world: dict[str, Any]) -> None:
    """The sharp negative: `system_worker` holds `create` and **not** `.review` (`:354`).

    A role holding neither would be refused by any guard at all, including one that asked for the
    wrong permission. This one gets past "some candidate grant" and must still be refused.
    """

    attempt_id = an_attempt(world)
    segment_id = a_segment(world)

    sign_in_admin(world["client"], "candidate_accountant")
    candidate_id = propose(world, segment_id, attempt_id).json()["id"]

    sign_in_admin(world["client"], "candidate_worker")
    assert accept(world, candidate_id).status_code == 403

    sign_in_admin(world["client"], "candidate_accountant")
    assert accept(world, candidate_id).status_code == 200


def test_rejecting_needs_the_review_permission(world: dict[str, Any]) -> None:
    attempt_id = an_attempt(world)
    segment_id = a_segment(world)

    sign_in_admin(world["client"], "candidate_accountant")
    candidate_id = propose(world, segment_id, attempt_id).json()["id"]

    sign_in_admin(world["client"], "candidate_worker")
    assert reject(world, candidate_id, reason="not mine to decide").status_code == 403

    sign_in_admin(world["client"], "candidate_accountant")
    assert reject(world, candidate_id, reason="wrong attempt").status_code == 200


def test_listing_needs_the_review_permission(world: dict[str, Any]) -> None:
    segment_id = a_segment(world)
    client = world["client"]

    sign_in_admin(client, "candidate_worker")
    refused = client.get(f"/api/v1/receipt-segments/{segment_id}/matching-candidates")
    assert refused.status_code == 403, refused.text

    sign_in_admin(client, "candidate_accountant")
    allowed = client.get(f"/api/v1/receipt-segments/{segment_id}/matching-candidates")
    assert allowed.status_code == 200, allowed.text
    assert allowed.json() == []

    missing = client.get(f"/api/v1/receipt-segments/{uuid.uuid4()}/matching-candidates")
    assert missing.status_code == 404, (
        "a segment that does not exist reads the same as one with no candidates, so the list "
        "cannot tell a reviewer they are looking at the wrong thing"
    )
