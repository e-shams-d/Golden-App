"""Deciding a retry is needed, and creating one — two acts, not one.

M9 slice 3B, against a real PostgreSQL. **The slice the plan forgot**: §17 `:1121` names five
payment-result commands and the plan mentioned three.

**The central property is again a negative one.** §17.4 in its own words: "This does not itself
create or send a retry." That is the third time in this milestone that what a command must *not*
do is the thing worth testing — after acceptance not paying and a dispute not reversing — and the
assertion is a count of the request's attempts before and after, because a status-only test passes
against an implementation that helpfully created the retry as well.

**The beneficiary comes from the referenced revision.** §17.5 rejects free-form beneficiary and
IBAN changes, and the strongest way to reject a field is to have nowhere for it to arrive.
`SVC-RETRY-002` asserts the absence over the request model and then proves the values really are
copied from the revision.

Covers: SVC-RETRY-001, SVC-RETRY-002, AUD-RETRY-001.
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

TRADER_PHONE = "+989120007001"
IBAN = "IR060120000000000000000070"
OTHER_IBAN = "IR060120000000000000000071"

RETRY_ACTION = "payment_attempt.retry_created"
MARKED_ACTION = "payment_attempt.retry_required"


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
        local_storage_root=tmp_path_factory.mktemp("retry-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="j" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    ids = {
        name: uuid.uuid4()
        for name in ("trader", "beneficiary", "other_beneficiary", "profile", "version", "account")
    }

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'Retry Trader', %s, 'active', 'approved')",
            (ids["trader"], TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (ids["trader"], TRADER_PHONE, encoded),
        )
        for key, name, iban in (
            ("beneficiary", "Ali Ten", IBAN),
            # The corrected destination a revision may carry. §17.5's whole point is that a
            # beneficiary change reaches a retry *through* a revision and never through the body.
            ("other_beneficiary", "Reza Eleven", OTHER_IBAN),
        ):
            connection.execute(
                "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
                "status, verification_status) VALUES (%s, %s, %s, %s, %s, 'active', "
                "'not_checked')",
                (ids[key], ids["trader"], name, iban, iban),
            )
        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'saman', 'Bank Saman', 'active')",
            (ids["profile"],),
        )
        connection.execute(
            "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, status, "
            "default_transfer_limit_irr, after_cutoff_transfer_limit_irr, cutoff_time, "
            "splitting_enabled, required_fields, rules, config_hash) "
            "VALUES (%s, %s, 1, 'active', 1000000000, NULL, NULL, TRUE, '{}', '{}', %s)",
            (ids["version"], ids["profile"], "a" * 64),
        )
        connection.execute(
            "INSERT INTO bank_accounts (id, bank_profile_id, display_name, iban, "
            "normalized_iban, account_role, status) "
            "VALUES (%s, %s, 'Centre Account', %s, %s, 'outgoing_source', 'active')",
            (ids["account"], ids["profile"], IBAN, IBAN),
        )
        for username, role in (
            ("retry_accountant", "accountant"),
            # Holds `payment_attempt.read` and not `create_retry`.
            ("retry_manager", "manager"),
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


def a_failed_attempt(world: dict[str, Any], *, amount: int = 800_000_000) -> dict[str, Any]:
    """One request, one revision, one attempt already `failed`.

    Inserted directly for the reason slices 1 to 3 give: this module's subject is what a retry
    does, and driving four milestones to produce a failure would make every test here depend on
    their behaviour.
    """

    request_id = uuid.uuid4()
    revision_id = uuid.uuid4()
    attempt_id = uuid.uuid4()

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO payment_requests (id, trader_id, beneficiary_id, request_number, "
            "status, record_version) VALUES (%s, %s, %s, %s, 'sent_to_bank', 1)",
            (request_id, world["trader_id"], world["beneficiary_id"], f"PR-{str(request_id)[:8]}"),
        )
        connection.execute(
            "INSERT INTO payment_request_revisions (id, payment_request_id, revision_number, "
            "beneficiary_id, beneficiary_name_snapshot, beneficiary_iban_snapshot, amount_irr, "
            "content_hash, created_by_actor_type) "
            "VALUES (%s, %s, 1, %s, 'Ali Ten', %s, %s, %s, 'trader_user')",
            (revision_id, request_id, world["beneficiary_id"], IBAN, amount, "b" * 64),
        )
        connection.execute(
            "UPDATE payment_requests SET current_revision_id = %s WHERE id = %s",
            (revision_id, request_id),
        )
        connection.execute(
            "INSERT INTO payment_attempts (id, payment_request_id, "
            "payment_request_revision_id, attempt_number, attempt_type, amount_irr, "
            "beneficiary_name_snapshot, beneficiary_iban_snapshot, bank_profile_version_id, "
            "bank_account_id, split_rule_snapshot, status, failure_code, failure_reason, "
            "record_version) "
            "VALUES (%s, %s, %s, 1, 'original', %s, 'Ali Ten', %s, %s, %s, '{}', 'failed', "
            "'bank_rejected', 'Bank rejected this row.', 1)",
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

    return {"request_id": request_id, "revision_id": revision_id, "attempt_id": attempt_id}


def a_corrected_revision(world: dict[str, Any], case: dict[str, Any]) -> uuid.UUID:
    """A second revision on the same request, pointing at a different beneficiary.

    This is the *only* route by which a retry may change where the money goes, which is what
    §17.5 means by "material beneficiary changes must exist in the referenced request revision".
    """

    revision_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO payment_request_revisions (id, payment_request_id, revision_number, "
            "beneficiary_id, beneficiary_name_snapshot, beneficiary_iban_snapshot, amount_irr, "
            "content_hash, created_by_actor_type) "
            "VALUES (%s, %s, 2, %s, 'Reza Eleven', %s, 800000000, %s, 'admin_user')",
            (revision_id, case["request_id"], world["other_beneficiary_id"], OTHER_IBAN, "c" * 64),
        )
        connection.commit()
    return revision_id


def version_of(world: dict[str, Any], attempt_id: uuid.UUID) -> int:
    return int(
        rows(world, "SELECT record_version FROM payment_attempts WHERE id = %s", attempt_id)[0][0]
    )


def mark_retry(world: dict[str, Any], attempt_id: uuid.UUID, **overrides: Any) -> Any:
    client = world["client"]
    body: dict[str, Any] = {"reason": "the bank rejected the destination account"}
    body.update(overrides)
    version = body.pop("version", None) or version_of(world, attempt_id)
    return client.post(
        f"/api/v1/payment-attempts/{attempt_id}/mark-retry-required",
        json=body,
        headers={
            **csrf(client),
            "If-Match": f'"rv-{version}"',
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )


def create_retry(
    world: dict[str, Any], attempt_id: uuid.UUID, revision_id: uuid.UUID, **overrides: Any
) -> Any:
    client = world["client"]
    body: dict[str, Any] = {
        "payment_request_revision_id": str(revision_id),
        "amount_irr": 800_000_000,
        "reason": "retry against the corrected revision",
    }
    body.update(overrides)
    version = body.pop("version", None) or version_of(world, attempt_id)
    return client.post(
        f"/api/v1/payment-attempts/{attempt_id}/retry",
        json=body,
        headers={
            **csrf(client),
            "If-Match": f'"rv-{version}"',
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )


def attempts_of(world: dict[str, Any], request_id: uuid.UUID) -> list[tuple[Any, ...]]:
    return rows(
        world,
        "SELECT attempt_number, attempt_type, status, retry_of_attempt_id, "
        "beneficiary_iban_snapshot FROM payment_attempts WHERE payment_request_id = %s "
        "ORDER BY attempt_number",
        request_id,
    )


# ---------------------------------------------------------------------------------------------
# §17.4: the decision, which creates nothing.
# ---------------------------------------------------------------------------------------------


def test_marking_retry_required_creates_no_attempt(world: dict[str, Any]) -> None:
    """`SVC-RETRY-001`. §17.4: "This does not itself create or send a retry."

    **Counted, not inferred.** A test of the status alone passes against an implementation that
    marks *and* creates, which is the shortcut this command exists to refuse — the same shape as
    slice 1's acceptance not paying.
    """

    case = a_failed_attempt(world)
    sign_in_admin(world["client"], "retry_accountant")

    before = attempts_of(world, case["request_id"])
    assert len(before) == 1

    marked = mark_retry(world, case["attempt_id"])
    assert marked.status_code == 200, marked.text
    assert marked.json()["status"] == "retry_required"

    after = attempts_of(world, case["request_id"])
    assert len(after) == 1, f"marking a retry created an attempt: {after}"
    assert after[0][2] == "retry_required"


def test_marking_retry_required_needs_a_reason(world: dict[str, Any]) -> None:
    """§17.4: "Reason required"."""

    case = a_failed_attempt(world)
    sign_in_admin(world["client"], "retry_accountant")

    refused = mark_retry(world, case["attempt_id"], reason="")
    assert refused.status_code == 422, refused.text
    assert rows(
        world, "SELECT status FROM payment_attempts WHERE id = %s", case["attempt_id"]
    ) == [("failed",)]


def test_a_paid_attempt_cannot_be_marked_for_retry(world: dict[str, Any]) -> None:
    """`06_Workflows_and_State_Machines.md:682-683` draws no arrow from `paid`.

    Money that moved is *corrected*, which is slice 7's command — retrying it would send a second
    payment for a transfer the bank already made.
    """

    case = a_failed_attempt(world)
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE payment_attempts SET status = 'paid' WHERE id = %s", (case["attempt_id"],)
        )
        connection.commit()

    sign_in_admin(world["client"], "retry_accountant")
    refused = mark_retry(world, case["attempt_id"])
    assert refused.status_code == 400, refused.text
    assert "paid" in refused.text
    assert rows(
        world, "SELECT status FROM payment_attempts WHERE id = %s", case["attempt_id"]
    ) == [("paid",)]


# ---------------------------------------------------------------------------------------------
# §17.5: the retry itself.
# ---------------------------------------------------------------------------------------------


def test_a_retry_carries_its_lineage_and_supersedes_the_original(
    world: dict[str, Any],
) -> None:
    """`SVC-RETRY-002`. `06_Workflows_and_State_Machines.md:684`.

    The new attempt points at the old one, takes the next number, and is `created` — unbatched,
    which `:1636` requires. The original becomes `superseded` in the same transaction, so two
    retries of one failure cannot exist.
    """

    case = a_failed_attempt(world)
    sign_in_admin(world["client"], "retry_accountant")
    assert mark_retry(world, case["attempt_id"]).status_code == 200

    created = create_retry(world, case["attempt_id"], case["revision_id"])
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "created"
    assert created.json()["attempt_number"] == 2

    chain = attempts_of(world, case["request_id"])
    assert len(chain) == 2, chain
    assert chain[0][2] == "superseded", "the original was not retired"
    assert chain[1][1] == "retry"
    assert str(chain[1][3]) == str(case["attempt_id"]), "the retry does not name what it retries"


def test_a_second_retry_of_one_failure_is_refused(world: dict[str, Any]) -> None:
    """The consequence of retiring the original in the same transaction.

    Without it, two accountants each holding a stale view would each create a retry and the
    request would carry two live attempts for one failed payment.
    """

    case = a_failed_attempt(world)
    sign_in_admin(world["client"], "retry_accountant")
    assert mark_retry(world, case["attempt_id"]).status_code == 200
    assert create_retry(world, case["attempt_id"], case["revision_id"]).status_code == 201

    again = create_retry(world, case["attempt_id"], case["revision_id"])
    assert again.status_code in (400, 409), again.text
    assert len(attempts_of(world, case["request_id"])) == 2


def test_a_retry_takes_its_beneficiary_from_the_referenced_revision(
    world: dict[str, Any],
) -> None:
    """`SVC-RETRY-002`. §17.5: "Material beneficiary changes must exist in the referenced
    request revision."

    The corrected destination reaches the retry because a *revision* carries it — never because a
    caller asked for it. The request body has no beneficiary field at all, which
    `tests/backend/test_payment_result_shape.py` asserts; this proves the values really are
    copied from the revision rather than from the original attempt.
    """

    case = a_failed_attempt(world)
    corrected = a_corrected_revision(world, case)
    sign_in_admin(world["client"], "retry_accountant")
    assert mark_retry(world, case["attempt_id"]).status_code == 200

    created = create_retry(world, case["attempt_id"], corrected)
    assert created.status_code == 201, created.text

    chain = attempts_of(world, case["request_id"])
    assert chain[0][4] == IBAN, "the original's destination was rewritten"
    assert chain[1][4] == OTHER_IBAN, (
        "the retry kept the original's IBAN instead of taking the referenced revision's, so a "
        "corrected destination would never reach the bank"
    )


def test_a_revision_from_another_request_is_refused(world: dict[str, Any]) -> None:
    """The check that makes the rule above meaningful.

    A revision belonging to a different request would let a retry take any beneficiary in the
    system — the free-form change §17.5 forbids, arriving through a field that looks legitimate.
    """

    case = a_failed_attempt(world)
    foreign = a_failed_attempt(world)
    sign_in_admin(world["client"], "retry_accountant")
    assert mark_retry(world, case["attempt_id"]).status_code == 200

    refused = create_retry(world, case["attempt_id"], foreign["revision_id"])
    assert refused.status_code == 400, refused.text
    assert "different payment request" in refused.text
    assert len(attempts_of(world, case["request_id"])) == 1


def test_an_unmarked_attempt_cannot_be_retried(world: dict[str, Any]) -> None:
    """§17.4's decision comes first, and the two commands are separate acts."""

    case = a_failed_attempt(world)
    sign_in_admin(world["client"], "retry_accountant")

    refused = create_retry(world, case["attempt_id"], case["revision_id"])
    assert refused.status_code == 400, refused.text
    assert "retry_required" in refused.text
    assert len(attempts_of(world, case["request_id"])) == 1


# ---------------------------------------------------------------------------------------------
# Audit and permissions.
# ---------------------------------------------------------------------------------------------


def test_the_retry_audit_row_names_what_it_retries(world: dict[str, Any]) -> None:
    """`AUD-RETRY-001`. `audit_outbox_catalog.yaml:45` names the action; no outbox event.

    An unbatched, unsent retry is a plan, and nothing outside the platform can act on a plan —
    which is what the catalogue's `outbox_event: null` says and what this asserts.
    """

    case = a_failed_attempt(world)
    sign_in_admin(world["client"], "retry_accountant")
    before = rows(world, "SELECT count(*) FROM outbox_events")[0][0]

    assert mark_retry(world, case["attempt_id"]).status_code == 200
    created = create_retry(world, case["attempt_id"], case["revision_id"])
    retry_id = created.json()["id"]

    audited = rows(
        world,
        "SELECT action, new_values->>'retry_of_attempt_id' FROM audit_logs "
        "WHERE entity_id = %s AND action = %s",
        retry_id,
        RETRY_ACTION,
    )
    assert audited == [(RETRY_ACTION, str(case["attempt_id"]))], audited

    marked = rows(
        world,
        "SELECT action, previous_values->>'status' FROM audit_logs "
        "WHERE entity_id = %s AND action = %s",
        case["attempt_id"],
        MARKED_ACTION,
    )
    assert marked == [(MARKED_ACTION, "failed")], marked

    assert rows(world, "SELECT count(*) FROM outbox_events")[0][0] == before, (
        "a retry published an outbox event; the catalogue gives both commands none"
    )


def test_no_retry_route_answers_a_caller_without_the_permission(
    world: dict[str, Any],
) -> None:
    """`manager` holds `payment_attempt.read` and not `payment_attempt.create_retry`."""

    case = a_failed_attempt(world)

    sign_in_admin(world["client"], "retry_manager")
    assert mark_retry(world, case["attempt_id"]).status_code == 403
    assert create_retry(world, case["attempt_id"], case["revision_id"]).status_code == 403

    sign_in_admin(world["client"], "retry_accountant")
    assert mark_retry(world, case["attempt_id"]).status_code == 200
