"""The manager's decision, and the two guards that make it mean something.

M7 slice 1, against a real PostgreSQL.

**The separation rule is proved twice, at two layers, on purpose.**
`FINANCIAL_INTEGRITY_BASELINE.md` §5 requires it "at the command layer **and** by a
database-enforceable guard or transactional constraint/trigger whose race behavior is tested".
So there are two kinds of test here: ones that go through the route and read the sentence a
person is given, and ones that insert straight into the table as the runtime role and read what
PostgreSQL says. The second kind is the one that survives a service check being deleted.

**Three administrators, because two cannot tell the two guards apart.**
`approval_dual` holds `accountant` and `manager`; `approval_accountant` holds `accountant`;
`approval_manager` holds `manager`. With only a dual-role user, an actor refused as the preparer
and an actor refused as the finalizer are the same actor, and a test could not say which
constraint fired — which is exactly how a one-comparison implementation would pass a
two-comparison test. So the preparer case is prepared by `approval_dual` and finalized by
`approval_accountant`, and the finalizer case is the other way round.

**Slice 5A is here too, and it belongs here.** What a replacement does to an approval is a fact
about the approval, and its tests need the same three administrators for the same reason — the
replacement has to be approvable by somebody who did not finalize it.

**The screens' read slice is here too**, and for the same reason: the separation-of-duty status
the approval view reports is per-actor, so proving it needs the same three administrators. A
fixture with one dual-role user could not tell "you prepared it" from "you finalized it".

Covers: SEC-APPROVAL-001, SEC-APPROVAL-002, SEC-APPROVAL-003, CON-APPROVAL-001,
SVC-APPROVAL-001, AUD-APPROVAL-001, TRACE-APPROVAL-001, SVC-INVALIDATE-001, SVC-INVALIDATE-002,
AUD-INVALIDATE-001, API-APPROVALREAD-003, API-APPROVALREAD-004.
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

TRADER_PHONE = "+989120004501"
IBAN = "IR060120000000000000000045"

LIMIT = 1_000_000_000
ONE_ROW = "900000000"

APPROVE_PURPOSE = "payment_batch_version.approve"
REJECT_PURPOSE = "payment_batch_version.reject"
STEP_UP_RESOURCE_TYPE = "payment_batch_version"


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
            "approval_status) VALUES (%s, 'Approval Trader', %s, 'active', 'approved')",
            (ids["trader"], TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (ids["trader"], TRADER_PHONE, encoded),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'Ali Five', %s, %s, 'active', "
            "'not_checked')",
            (ids["beneficiary"], ids["trader"], IBAN, IBAN),
        )
        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'ayandeh', 'Bank Ayandeh', 'active')",
            (ids["profile"],),
        )
        connection.execute(
            "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, status, "
            "default_transfer_limit_irr, after_cutoff_transfer_limit_irr, cutoff_time, "
            "splitting_enabled, required_fields, rules, config_hash) "
            "VALUES (%s, %s, 1, 'active', %s, NULL, NULL, TRUE, '{}', '{}', %s)",
            (ids["version"], ids["profile"], LIMIT, "1" * 64),
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
            (ids["mapping"], ids["version"], "2" * 64),
        )
        for username, roles in (
            # Prepares and finalizes; may not decide.
            ("approval_accountant", ("accountant",)),
            # Both, which is what makes the preparer case separable from the finalizer case.
            # A deployment need not have such a person; the guard must hold if it does.
            ("approval_dual", ("accountant", "manager")),
            # The legitimate approver, who touched neither.
            ("approval_manager", ("manager",)),
            # Holds `payment_batch_version.read_approval_view` but neither decision grant, so
            # the permission negatives prove the routes want *these* grants rather than merely
            # some batch grant.
            ("approval_auditor", ("read_only_auditor",)),
        ):
            connection.execute(
                "INSERT INTO admin_users (username, full_name, password_hash, status) "
                "VALUES (%s, %s, %s, 'active')",
                (username, username, encoded),
            )
            for role in roles:
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


def sign_in_trader(client: Any) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/trader/login", json={"identifier": TRADER_PHONE, "password": PASSWORD}
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


def rows(world: dict[str, Any], sql: str, *parameters: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        return connection.execute(sql, parameters).fetchall()


def admin_id(world: dict[str, Any], username: str) -> uuid.UUID:
    found = rows(world, "SELECT id FROM admin_users WHERE username = %s", username)
    assert found, f"{username} was not seeded"
    return uuid.UUID(str(found[0][0]))


def step_up(client: Any, version_id: str, purpose: str = APPROVE_PURPOSE) -> str:
    """A recent-auth context bound to this action and this version.

    The resource is the version, which is the binding
    `FINANCIAL_INTEGRITY_BASELINE.md` §3 requires and the one `app/security/step_up.py` names
    in its own docstring: "a step-up for batch version 7 authorises version 8" is the case the
    whole approval model exists to prevent.
    """

    response = client.post(
        "/api/v1/auth/reauthenticate",
        json={
            "password": PASSWORD,
            "purpose": purpose,
            "resource_type": STEP_UP_RESOURCE_TYPE,
            "resource_id": version_id,
        },
        headers=csrf(client),
    )
    assert response.status_code == 200, response.text
    return str(response.json()["recent_auth_reference"])


def a_finalized_version(
    world: dict[str, Any], *, prepared_by: str = "approval_accountant",
    finalized_by: str = "approval_accountant", finalize: bool = True,
) -> dict[str, Any]:
    """One request, one batch, finalized — with the two actors named separately.

    `prepared_by` writes `created_by_admin_user_id` and `finalized_by` writes
    `finalized_by_admin_user_id`. Two parameters rather than one, because the whole point of
    `SEC-APPROVAL-002` is that these can differ.
    """

    client = world["client"]
    sign_in_trader(client)
    created = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiary_id"]),
            "amount": {"value": ONE_ROW, "unit": "IRR"},
            "description": "to be decided",
        },
        headers=csrf(client),
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["request"]["id"]
    revision_id = created.json()["revision"]["id"]

    handed = client.post(
        f"/api/v1/payment-requests/{request_id}/submit",
        json={},
        headers={
            **csrf(client),
            "If-Match": f'"rv-{created.json()["request"]["record_version"]}"',
        },
    )
    assert handed.status_code == 200, handed.text

    sign_in_admin(client, prepared_by)
    started = client.post(
        f"/api/v1/payment-requests/{request_id}/start-review",
        json={},
        headers={**csrf(client), "If-Match": handed.headers["ETag"]},
    )
    assert started.status_code == 200, started.text
    eligible = client.post(
        f"/api/v1/payment-requests/{request_id}/mark-eligible-for-batching",
        json={"expected_revision_id": revision_id, "review_note": "checked"},
        headers={**csrf(client), "If-Match": started.headers["ETag"]},
    )
    assert eligible.status_code == 200, eligible.text

    batch = client.post(
        "/api/v1/payment-batches",
        json={
            "items": [
                {
                    "payment_request_id": request_id,
                    "expected_revision_id": revision_id,
                    "expected_record_version": eligible.json()["record_version"],
                }
            ],
            "bank_profile_version_id": str(world["version_id"]),
            "bank_account_id": str(world["account_id"]),
            "bank_mapping_id": str(world["mapping_id"]),
        },
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert batch.status_code == 201, batch.text
    body = batch.json()
    batch_id = body["batch"]["id"]
    version_id = body["current_version"]["id"]

    if not finalize:
        # A draft: no finalizer, so nothing the separation rule could compare against. Used by
        # the status-guard test, which is the reason that comparison is never reached.
        return {
            "batch_id": batch_id,
            "version_id": version_id,
            "content_hash": body["current_version"]["content_hash"],
            "etag": batch.headers["ETag"],
        }

    if finalized_by != prepared_by:
        sign_in_admin(client, finalized_by)
    frozen = client.post(
        f"/api/v1/payment-batches/{batch_id}/versions/{version_id}/finalize",
        json={"note": "validated"},
        headers={
            **csrf(client),
            "If-Match": batch.headers["ETag"],
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert frozen.status_code == 200, frozen.text

    return {
        "batch_id": batch_id,
        "version_id": version_id,
        "content_hash": frozen.json()["version"]["content_hash"],
        "etag": frozen.headers["ETag"],
    }


def approve(
    world: dict[str, Any],
    frozen: dict[str, Any],
    *,
    reference: str | None = None,
    content_hash: str | None = None,
    key: str | None = None,
) -> Any:
    client = world["client"]
    return client.post(
        f"/api/v1/payment-batches/{frozen['batch_id']}/versions/{frozen['version_id']}/approve",
        json={
            "expected_content_hash": content_hash or frozen["content_hash"],
            "approval_note": "approved for the bank",
        },
        headers={
            **csrf(client),
            "Idempotency-Key": key or str(uuid.uuid4()),
            "X-Recent-Auth": reference or step_up(client, frozen["version_id"]),
        },
    )


def replace(world: dict[str, Any], frozen: dict[str, Any], *, etag: str) -> Any:
    """A replacement version carrying the same request, re-read so its expectations are current.

    The selection's `expected_record_version` and `expected_revision_id` are read from the
    database rather than remembered from the create call: batching moved the request, and a
    replacement that quoted stale expectations would be refused for a reason that has nothing to
    do with what these tests are about.
    """

    current = rows(
        world,
        "SELECT pr.id, pr.current_revision_id, pr.record_version FROM payment_requests pr "
        "JOIN payment_attempts pa ON pa.payment_request_id = pr.id "
        "JOIN payment_batch_items pbi ON pbi.payment_attempt_id = pa.id "
        "WHERE pbi.payment_batch_version_id = %s LIMIT 1",
        frozen["version_id"],
    )
    assert current, "the finalized version has no request behind it"
    request_id, revision_id, record_version = current[0]

    client = world["client"]
    return client.post(
        f"/api/v1/payment-batches/{frozen['batch_id']}/versions",
        json={
            "items": [
                {
                    "payment_request_id": str(request_id),
                    "expected_revision_id": str(revision_id),
                    "expected_record_version": record_version,
                }
            ],
            "bank_profile_version_id": str(world["version_id"]),
            "bank_account_id": str(world["account_id"]),
            "bank_mapping_id": str(world["mapping_id"]),
            "reason": "the beneficiary was corrected",
        },
        headers={**csrf(client), "If-Match": etag, "Idempotency-Key": str(uuid.uuid4())},
    )


def approvals_of(world: dict[str, Any], version_id: str) -> list[tuple[Any, ...]]:
    return rows(
        world,
        "SELECT decision, approved_content_hash, decided_by_admin_user_id, decided_at "
        "FROM batch_approvals WHERE payment_batch_version_id = %s",
        version_id,
    )


def test_approving_records_the_exact_hash_and_moves_both_statuses(
    world: dict[str, Any],
) -> None:
    """`TRACE-APPROVAL-001`. One row answers "what did the manager approve".

    The DoD's chain starts here: the approval names the content hash, so the question is
    answered from the decision itself rather than by correlating it with a version read at some
    later time, when the version may have been superseded.

    Both statuses move because the container's is a projection of its current version's — nine
    of the batch's eleven catalogue states are `derived: true`.
    """

    frozen = a_finalized_version(world)
    sign_in_admin(world["client"], "approval_manager")

    response = approve(world, frozen)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["approval"]["decision"] == "approved"
    assert body["approval"]["approved_content_hash"] == frozen["content_hash"]
    assert body["version"]["status"] == "approved"
    assert body["batch"]["status"] == "approved"

    stored = rows(
        world,
        "SELECT decision, approved_content_hash, decided_by_admin_user_id, reason "
        "FROM batch_approvals WHERE payment_batch_version_id = %s",
        frozen["version_id"],
    )
    assert len(stored) == 1, "one decision per version"
    decision, stored_hash, decided_by, _reason = stored[0]
    assert decision == "approved"
    assert stored_hash == frozen["content_hash"]
    assert uuid.UUID(str(decided_by)) == admin_id(world, "approval_manager")


def test_rejecting_records_the_reason_and_no_hash(world: dict[str, Any]) -> None:
    """`:1461` — "Rejection reason is mandatory" — and §11.7's CHECK, which stores no hash.

    A rejection carrying a hash would look like an approval to anything that reads the column,
    and the composite foreign key that ties an approval to its version's content would then be
    enforced on a row that approved nothing.
    """

    frozen = a_finalized_version(world)
    client = world["client"]
    sign_in_admin(client, "approval_manager")

    response = client.post(
        f"/api/v1/payment-batches/{frozen['batch_id']}/versions/{frozen['version_id']}/reject",
        json={
            "expected_content_hash": frozen["content_hash"],
            "reason_code": "beneficiary_review_required",
            "reason": "One row must be corrected before approval.",
        },
        headers={
            **csrf(client),
            "Idempotency-Key": str(uuid.uuid4()),
            "X-Recent-Auth": step_up(client, frozen["version_id"], REJECT_PURPOSE),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["approval"]["decision"] == "rejected"
    assert response.json()["approval"]["approved_content_hash"] is None
    assert response.json()["version"]["status"] == "rejected"

    stored = rows(
        world,
        "SELECT decision, approved_content_hash, reason FROM batch_approvals "
        "WHERE payment_batch_version_id = %s",
        frozen["version_id"],
    )
    assert stored == [
        ("rejected", None, "One row must be corrected before approval.")
    ], stored


def test_the_finalizer_cannot_approve_the_version_they_froze(world: dict[str, Any]) -> None:
    """`SEC-APPROVAL-001` at the command layer.

    `approval_dual` finalizes and then tries to decide. The preparer here is
    `approval_accountant`, so the *only* rule that can refuse this is the finalizer comparison —
    which is what makes this test about that comparison rather than about either.
    """

    frozen = a_finalized_version(
        world, prepared_by="approval_accountant", finalized_by="approval_dual"
    )
    sign_in_admin(world["client"], "approval_dual")

    response = approve(world, frozen)

    assert response.status_code == 400, response.text
    assert "finalized" in response.json()["error"]["message"]
    assert rows(
        world,
        "SELECT 1 FROM batch_approvals WHERE payment_batch_version_id = %s",
        frozen["version_id"],
    ) == []


def test_the_preparer_cannot_approve_the_version_they_built(world: dict[str, Any]) -> None:
    """`SEC-APPROVAL-002`, the stricter reading of `12_Security_RBAC_Audit.md:1111`.

    `approval_dual` prepares and `approval_accountant` finalizes, so the finalizer comparison
    passes and only the preparer comparison can refuse. Under the one-comparison reading this
    approval would succeed — and the person who chose every row in the file would have approved
    it.

    **G-2 is open.** If the owner decides "finalizer" alone, this test and the
    `ck_batch_approvals_approver_is_not_preparer` constraint go together, and the sibling test
    above still holds. Named here so that relaxation is a deliberate edit rather than a
    discovery.
    """

    frozen = a_finalized_version(
        world, prepared_by="approval_dual", finalized_by="approval_accountant"
    )
    sign_in_admin(world["client"], "approval_dual")

    response = approve(world, frozen)

    assert response.status_code == 400, response.text
    assert "prepared" in response.json()["error"]["message"]


def test_the_database_refuses_a_self_approval_with_no_service_in_the_way(
    world: dict[str, Any],
) -> None:
    """`SEC-APPROVAL-001`'s other half: the guard §5 calls database-enforceable.

    The command's check is bypassed entirely — this inserts as the runtime role, which is what a
    second code path, a future worker, or a deleted service check would do.
    `FINANCIAL_INTEGRITY_BASELINE.md` §5 requires the guard to survive exactly that, and the
    negative control for this obligation is to drop the CHECK and watch this fail.

    The row is otherwise valid: the version is real, the copies are the version's own values,
    and the hash is the version's. Only the decider is wrong.
    """

    frozen = a_finalized_version(
        world, prepared_by="approval_accountant", finalized_by="approval_dual"
    )
    finalizer = admin_id(world, "approval_dual")
    preparer = admin_id(world, "approval_accountant")

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(f'SET ROLE "{world["app_role"]}"')
        with pytest.raises(psycopg.errors.CheckViolation) as refused:
            connection.execute(
                "INSERT INTO batch_approvals (payment_batch_version_id, decision, "
                "decided_by_admin_user_id, decided_at, approved_content_hash, "
                "authentication_context, version_finalized_by_admin_user_id, "
                "version_created_by_admin_user_id) "
                "VALUES (%s, 'approved', %s, now(), %s, '{}', %s, %s)",
                (
                    frozen["version_id"],
                    finalizer,
                    frozen["content_hash"],
                    finalizer,
                    preparer,
                ),
            )
        connection.rollback()

    assert "ck_batch_approvals_approver_is_not_finalizer" in str(refused.value)


def test_the_database_refuses_an_approval_naming_a_hash_the_version_does_not_have(
    world: dict[str, Any],
) -> None:
    """`TRACE-APPROVAL-001` as a schema fact.

    §11.7 says "a deferred database trigger or the application transaction must verify that an
    approval hash equals the referenced version hash". Here it is a composite foreign key, so
    the verification does not depend on which code path wrote the row — and a decision that
    named content nobody reviewed cannot be stored at all.
    """

    frozen = a_finalized_version(world)
    manager = admin_id(world, "approval_manager")
    finalizer = admin_id(world, "approval_accountant")

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(f'SET ROLE "{world["app_role"]}"')
        with pytest.raises(psycopg.errors.ForeignKeyViolation) as refused:
            connection.execute(
                "INSERT INTO batch_approvals (payment_batch_version_id, decision, "
                "decided_by_admin_user_id, decided_at, approved_content_hash, "
                "authentication_context, version_finalized_by_admin_user_id, "
                "version_created_by_admin_user_id) "
                "VALUES (%s, 'approved', %s, now(), %s, '{}', %s, %s)",
                (frozen["version_id"], manager, "b" * 64, finalizer, finalizer),
            )
        connection.rollback()

    assert "fk_batch_approvals_approved_hash" in str(refused.value)


def test_two_concurrent_decisions_on_one_version_produce_one_row(
    world: dict[str, Any],
) -> None:
    """`CON-APPROVAL-001`. `UNIQUE(payment_batch_version_id)` decides, not a prior read.

    Two open transactions, both inserting, neither having seen the other — which is precisely
    what a `SELECT ... WHERE NOT EXISTS` cannot refuse. The second blocks until the first
    commits and is then refused by the constraint.
    """

    frozen = a_finalized_version(world)
    manager = admin_id(world, "approval_manager")
    finalizer = admin_id(world, "approval_accountant")
    statement = (
        "INSERT INTO batch_approvals (payment_batch_version_id, decision, "
        "decided_by_admin_user_id, decided_at, approved_content_hash, authentication_context, "
        "version_finalized_by_admin_user_id, version_created_by_admin_user_id) "
        "VALUES (%s, 'approved', %s, now(), %s, '{}', %s, %s)"
    )
    parameters = (frozen["version_id"], manager, frozen["content_hash"], finalizer, finalizer)

    first = psycopg.connect(_psycopg(world["owner_url"]))
    second = psycopg.connect(_psycopg(world["owner_url"]))
    try:
        first.execute(f'SET ROLE "{world["app_role"]}"')
        second.execute(f'SET ROLE "{world["app_role"]}"')
        first.execute(statement, parameters)
        first.commit()

        with pytest.raises(psycopg.errors.UniqueViolation) as refused:
            second.execute(statement, parameters)
        second.rollback()
    finally:
        first.close()
        second.close()

    assert "uq_batch_approvals_one_per_version" in str(refused.value)
    assert len(
        rows(
            world,
            "SELECT 1 FROM batch_approvals WHERE payment_batch_version_id = %s",
            frozen["version_id"],
        )
    ) == 1


def test_a_second_decision_through_the_route_is_told_which_one_won(
    world: dict[str, Any],
) -> None:
    """The half of `CON-APPROVAL-001` a person meets: the loser learns the outcome.

    A bare 409 would send a manager to ask a colleague what happened. The decision that won is
    in the message, so the screen can say it.
    """

    frozen = a_finalized_version(world)
    sign_in_admin(world["client"], "approval_manager")
    assert approve(world, frozen).status_code == 200

    second = approve(world, frozen)
    assert second.status_code == 409, second.text
    assert "approved" in second.json()["error"]["message"]


def test_a_stale_content_hash_is_refused(world: dict[str, Any]) -> None:
    """`SVC-APPROVAL-001`. `:1443` — "The command is blocked when the content hash differs."

    The hash is the concurrency token on this route, and a stronger one than a record version: a
    record version says *when* the manager read, the hash says *what* they read. A manager whose
    screen predates a replacement is holding the previous version's digest, and approving on it
    would bind a decision to content they never saw.
    """

    frozen = a_finalized_version(world)
    sign_in_admin(world["client"], "approval_manager")

    response = approve(world, frozen, content_hash="c" * 64)

    assert response.status_code == 409, response.text
    assert "stale" in response.json()["error"]["message"]
    assert rows(
        world,
        "SELECT 1 FROM batch_approvals WHERE payment_batch_version_id = %s",
        frozen["version_id"],
    ) == []


def test_a_context_issued_for_another_version_does_not_authorise_this_one(
    world: dict[str, Any],
) -> None:
    """`SEC-APPROVAL-003`. The binding the whole step-up design exists for.

    `app/security/step_up.py`'s own docstring names this case: "otherwise a step-up for batch
    version 7 authorises version 8, which is the case the whole approval model exists to
    prevent". Here it is, with two real versions.

    The client is told `RECENT_AUTH_REQUIRED` and nothing else; `WRONG_RESOURCE` goes to
    `auth_events`, so a caller cannot map which contexts exist by reading error messages.
    """

    mine = a_finalized_version(world)
    other = a_finalized_version(world)
    client = world["client"]
    sign_in_admin(client, "approval_manager")

    response = approve(world, mine, reference=step_up(client, other["version_id"]))

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "RECENT_AUTH_REQUIRED"

    recorded = rows(
        world,
        "SELECT metadata->>'rejection_reason' FROM auth_events "
        "WHERE event_type = 'step_up.rejected' ORDER BY created_at DESC LIMIT 1",
    )
    assert recorded == [("wrong_resource",)], recorded


def test_a_context_issued_to_reject_does_not_authorise_an_approval(
    world: dict[str, Any],
) -> None:
    """`SEC-APPROVAL-003`, bound to the action as well as the resource.

    Two purposes rather than one, so re-authenticating to refuse a batch cannot be spent
    authorising it. `FINANCIAL_INTEGRITY_BASELINE.md` §3 lists action alongside resource, and
    the two failures are different: the wrong resource pays the wrong people, the wrong action
    pays them when somebody meant to stop it.
    """

    frozen = a_finalized_version(world)
    client = world["client"]
    sign_in_admin(client, "approval_manager")

    response = approve(
        world, frozen, reference=step_up(client, frozen["version_id"], REJECT_PURPOSE)
    )

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "RECENT_AUTH_REQUIRED"


def test_a_consumed_context_cannot_decide_a_second_version(world: dict[str, Any]) -> None:
    """`SEC-APPROVAL-003`. Consumption is recorded in the command's transaction.

    The negative control for this obligation reuses a spent context. It fails as
    `ALREADY_CONSUMED` because `consumed_at` was written in the same transaction as the
    approval — had it been written separately, a timeout-and-retry would have approved twice on
    one step-up.
    """

    frozen = a_finalized_version(world)
    client = world["client"]
    sign_in_admin(client, "approval_manager")

    reference = step_up(client, frozen["version_id"])
    assert approve(world, frozen, reference=reference).status_code == 200

    spent = rows(
        world,
        "SELECT consumed_at IS NOT NULL, consumed_by_command FROM recent_auth_contexts "
        "WHERE purpose = %s ORDER BY created_at DESC LIMIT 1",
        APPROVE_PURPOSE,
    )
    assert spent == [(True, APPROVE_PURPOSE)], spent

    # A different version, so the refusal is the spent context rather than the one-decision rule.
    another = a_finalized_version(world)
    sign_in_admin(client, "approval_manager")
    replayed = approve(world, another, reference=reference)

    assert replayed.status_code == 401, replayed.text
    assert replayed.json()["error"]["code"] == "RECENT_AUTH_REQUIRED"


def test_approval_writes_its_catalogued_action_and_the_one_event_it_owes(
    world: dict[str, Any],
) -> None:
    """`AUD-APPROVAL-001`. `command_catalog.yaml:152-153`, both names from the registry."""

    frozen = a_finalized_version(world)
    sign_in_admin(world["client"], "approval_manager")
    assert approve(world, frozen).status_code == 200

    audited = rows(
        world,
        "SELECT action, new_values->>'content_hash', new_values->>'decision' FROM audit_logs "
        "WHERE entity_id = %s AND action = 'payment_batch_version.approved'",
        frozen["version_id"],
    )
    assert audited == [
        ("payment_batch_version.approved", frozen["content_hash"], "approved")
    ], audited

    published = rows(
        world,
        "SELECT event_type, payload->>'approved_content_hash' FROM outbox_events "
        "WHERE aggregate_id = %s",
        frozen["version_id"],
    )
    assert ("PaymentBatchVersionApproved", frozen["content_hash"]) in published


def test_rejection_writes_its_action_and_publishes_nothing(world: dict[str, Any]) -> None:
    """`AUD-APPROVAL-001`'s other half, and it asserts an **absence** deliberately.

    `command_catalog.yaml:166` gives rejection `"outbox_event": null` and
    `audit_outbox_catalog.yaml` defines no rejection event. An invented
    `PaymentBatchVersionRejected` would be an event type no consumer contract names — the same
    shape as an audit action nothing catalogues. Asserted rather than left implicit, so the
    absence reads as a decision rather than as forgetfulness.
    """

    frozen = a_finalized_version(world)
    client = world["client"]
    sign_in_admin(client, "approval_manager")

    response = client.post(
        f"/api/v1/payment-batches/{frozen['batch_id']}/versions/{frozen['version_id']}/reject",
        json={
            "expected_content_hash": frozen["content_hash"],
            "reason_code": "amount_disputed",
            "reason": "The total does not match the instruction.",
        },
        headers={
            **csrf(client),
            "Idempotency-Key": str(uuid.uuid4()),
            "X-Recent-Auth": step_up(client, frozen["version_id"], REJECT_PURPOSE),
        },
    )
    assert response.status_code == 200, response.text

    assert rows(
        world,
        "SELECT action FROM audit_logs WHERE entity_id = %s AND "
        "action = 'payment_batch_version.rejected'",
        frozen["version_id"],
    ) == [("payment_batch_version.rejected",)]

    # Finalization already published `PaymentBatchVersionReadyForApproval` against this same
    # aggregate, so the claim is that the rejection added **nothing**, not that the queue is
    # empty. The first version of this assertion read `== []` and failed on finalization's own
    # event — which would have been the easy thing to "fix" by filtering for a rejection event
    # type, and that filter would have passed just as well if one were later invented.
    assert rows(
        world,
        "SELECT event_type FROM outbox_events WHERE aggregate_id = %s ORDER BY event_type",
        frozen["version_id"],
    ) == [("PaymentBatchVersionReadyForApproval",)], (
        "a rejection publishes nothing of its own; command_catalog.yaml:166 gives it "
        "outbox_event: null and audit_outbox_catalog.yaml defines no rejection event"
    )


def test_a_repeated_idempotency_key_replays_instead_of_deciding_twice(
    world: dict[str, Any],
) -> None:
    """A retry after a timeout returns the first answer rather than meeting the one-decision rule.

    Without this a client that lost the response would be told `409 already approved` for work it
    performed itself, which is indistinguishable from a colleague having decided.
    """

    frozen = a_finalized_version(world)
    client = world["client"]
    sign_in_admin(client, "approval_manager")

    key = str(uuid.uuid4())
    first = approve(world, frozen, key=key)
    assert first.status_code == 200, first.text

    second = approve(world, frozen, key=key, reference=step_up(client, frozen["version_id"]))
    assert second.status_code == 200, second.text
    assert second.json()["replayed"] is True
    assert second.json()["approval"]["id"] == first.json()["approval"]["id"]


def test_a_version_that_is_not_ready_for_approval_cannot_be_decided(
    world: dict[str, Any],
) -> None:
    """A draft has not been finalized, so there is no recorded finalizer to compare against.

    This is the guard that makes `_finalizer`'s `RuntimeError` unreachable rather than merely
    unlikely: reaching the separation comparison with a null finalizer would mean a version left
    `draft` without one.

    **A draft, not an already-approved version.** The obvious way to write this test is to
    approve something and then try again — but a decided version is refused earlier, by the
    one-decision rule, and this test would then have passed while proving nothing about the
    status guard. `test_a_second_decision_through_the_route_is_told_which_one_won` covers that
    path under its own name.
    """

    draft = a_finalized_version(world, finalize=False)
    client = world["client"]
    sign_in_admin(client, "approval_manager")

    response = approve(world, draft)

    assert response.status_code == 400, response.text
    assert "draft" in response.json()["error"]["message"]
    assert rows(
        world,
        "SELECT 1 FROM batch_approvals WHERE payment_batch_version_id = %s",
        draft["version_id"],
    ) == []


def test_both_headers_are_required(world: dict[str, Any]) -> None:
    """`command_catalog.yaml:149-150`: idempotency required, recent-auth required, action-bound.

    428 for both, and not 401 for the missing context: the caller presented none at all, which
    is a missing precondition. 401 is for a context that was presented and did not authorise
    this — the difference tells a client whether to obtain one or to obtain a different one.
    """

    frozen = a_finalized_version(world)
    client = world["client"]
    sign_in_admin(client, "approval_manager")
    body = {"expected_content_hash": frozen["content_hash"], "approval_note": None}
    path = (
        f"/api/v1/payment-batches/{frozen['batch_id']}"
        f"/versions/{frozen['version_id']}/approve"
    )

    without_key = client.post(
        path,
        json=body,
        headers={**csrf(client), "X-Recent-Auth": step_up(client, frozen["version_id"])},
    )
    assert without_key.status_code == 428, without_key.text

    without_context = client.post(
        path, json=body, headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())}
    )
    assert without_context.status_code == 428, without_context.text


def test_the_approval_view_needs_its_own_read_permission(world: dict[str, Any]) -> None:
    """`permission_catalog.yaml:475`. The auditor may look; the trader may not.

    Signed in as the trader rather than as an admin without the grant, because the trader is the
    caller for whom the whole batch surface must be unreachable — a batch has no trader, so there
    is no ownership scope that could ever make this row theirs.
    """

    frozen = a_finalized_version(world)
    client = world["client"]
    path = (
        f"/api/v1/payment-batches/{frozen['batch_id']}"
        f"/versions/{frozen['version_id']}/approval-view"
    )

    sign_in_trader(client)
    assert client.get(path).status_code == 403

    sign_in_admin(client, "approval_auditor")
    permitted = client.get(path)
    assert permitted.status_code == 200, permitted.text
    assert permitted.json()["version"]["content_hash"] == frozen["content_hash"]
    assert permitted.json()["prior_decision"] is None


def test_approving_needs_the_approve_permission(world: dict[str, Any]) -> None:
    """The negative signs in holding `read_approval_view` and neither decision grant.

    That is what makes this prove the route wants *this* grant rather than merely some batch
    grant — the distinction M6 slice 1's negative control showed a behavioural test cannot
    otherwise make, because the seed gives one role several.
    """

    frozen = a_finalized_version(world)
    sign_in_admin(world["client"], "approval_auditor")

    response = approve(world, frozen)

    assert response.status_code == 403, response.text


def test_rejecting_needs_the_reject_permission(world: dict[str, Any]) -> None:
    """`:483`. Separate from approve, because stopping a payment and authorising one are not
    the same authority — and the catalogue gives them separate rows."""

    frozen = a_finalized_version(world)
    client = world["client"]
    sign_in_admin(client, "approval_auditor")

    response = client.post(
        f"/api/v1/payment-batches/{frozen['batch_id']}/versions/{frozen['version_id']}/reject",
        json={
            "expected_content_hash": frozen["content_hash"],
            "reason_code": "not_permitted",
            "reason": "An auditor should not be able to reach this.",
        },
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 403, response.text


def test_a_replacement_makes_the_prior_approval_historical_and_changes_nothing_about_it(
    world: dict[str, Any],
) -> None:
    """`SVC-INVALIDATE-001`. §29.2: "approval remains historical".

    Two halves, and the second is the one worth asserting. The approval stops being operational —
    its version is `superseded` and is no longer the batch's current one. And the decision row is
    **byte-identical** afterwards: §11.7 says approved/rejected rows are never updated, and there
    is no UPDATE grant that would let this command touch it even by accident. What the manager
    decided is exactly what the record still says; only its subject moved out from under it.
    """

    frozen = a_finalized_version(world)
    client = world["client"]
    sign_in_admin(client, "approval_manager")
    approved = approve(world, frozen)
    assert approved.status_code == 200, approved.text
    before = approvals_of(world, frozen["version_id"])
    assert len(before) == 1

    sign_in_admin(client, "approval_accountant")
    replaced = replace(world, frozen, etag=f'"rv-{approved.json()["batch"]["record_version"]}"')
    assert replaced.status_code == 201, replaced.text

    assert approvals_of(world, frozen["version_id"]) == before, (
        "the decision row changed; §11.7 says approved/rejected rows are never updated"
    )

    state = rows(
        world,
        "SELECT v.status, b.status, b.current_version_id <> v.id FROM payment_batch_versions v "
        "JOIN payment_batches b ON b.id = v.payment_batch_id WHERE v.id = %s",
        frozen["version_id"],
    )
    assert state == [("superseded", "draft", True)], state


def test_no_decision_transfers_to_the_replacement(world: dict[str, Any]) -> None:
    """`SVC-INVALIDATE-001`. `15_Agent_Implementation_Plan.md:931`: no decision is transferred.

    The negative control for this obligation is to carry the approval forward, and the reason it
    is worth a test is that carrying it forward is the *helpful-looking* behaviour: the same rows,
    the same total, the same manager — why make them decide again? Because "the same rows" is
    precisely what a replacement is not obliged to be, and the approval named a content hash that
    the new version does not have.
    """

    frozen = a_finalized_version(world)
    client = world["client"]
    sign_in_admin(client, "approval_manager")
    approved = approve(world, frozen)
    assert approved.status_code == 200, approved.text

    sign_in_admin(client, "approval_accountant")
    replaced = replace(world, frozen, etag=f'"rv-{approved.json()["batch"]["record_version"]}"')
    assert replaced.status_code == 201, replaced.text
    replacement_id = replaced.json()["current_version"]["id"]

    assert approvals_of(world, replacement_id) == [], (
        "the replacement arrived already approved; no decision transfers"
    )
    assert replaced.json()["current_version"]["status"] == "draft"

    view = client.get(
        f"/api/v1/payment-batches/{frozen['batch_id']}/versions/{replacement_id}/approval-view"
    )
    assert view.status_code == 200, view.text
    assert view.json()["prior_decision"] is None


def test_the_replacement_is_approved_under_the_same_separation_rule(
    world: dict[str, Any],
) -> None:
    """`SVC-INVALIDATE-002`. `FINANCIAL_INTEGRITY_BASELINE.md` §5 applies afresh.

    The replacement is prepared and finalized by `approval_dual`, who then tries to approve it.
    Refused as the finalizer — the same guard slice 1 built, on a version that did not exist when
    the first decision was taken. A manager who approved version 1 has no standing on version 2
    that they finalized.
    """

    frozen = a_finalized_version(world)
    client = world["client"]
    sign_in_admin(client, "approval_manager")
    approved = approve(world, frozen)
    assert approved.status_code == 200, approved.text

    sign_in_admin(client, "approval_dual")
    replaced = replace(world, frozen, etag=f'"rv-{approved.json()["batch"]["record_version"]}"')
    assert replaced.status_code == 201, replaced.text
    replacement = {
        "batch_id": frozen["batch_id"],
        "version_id": replaced.json()["current_version"]["id"],
        "content_hash": replaced.json()["current_version"]["content_hash"],
    }

    frozen_again = client.post(
        f"/api/v1/payment-batches/{replacement['batch_id']}"
        f"/versions/{replacement['version_id']}/finalize",
        json={"note": "validated again"},
        headers={
            **csrf(client),
            "If-Match": replaced.headers["ETag"],
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert frozen_again.status_code == 200, frozen_again.text

    refused = approve(world, replacement)
    assert refused.status_code == 400, refused.text
    assert "finalized" in refused.json()["error"]["message"]

    # And the legitimate approver still can, so the refusal above is about who asked rather than
    # about the replacement being unapprovable.
    sign_in_admin(client, "approval_manager")
    second = approve(world, replacement)
    assert second.status_code == 200, second.text
    assert len(approvals_of(world, replacement["version_id"])) == 1


def test_the_invalidation_is_recorded_as_its_own_catalogued_action(
    world: dict[str, Any],
) -> None:
    """`AUD-INVALIDATE-001`. `payment_batch_approval.invalidated`, from the registry.

    A second audit row beside the replacement's own, because they answer different questions:
    one says why a new version exists, this one says why the approval somebody remembers is no
    longer in force. `audit_outbox_catalog.yaml:31` names it and its `outbox_events` list names
    nothing for it, so nothing is published — asserted, because an invented
    `PaymentBatchApprovalInvalidated` would be an event type no consumer contract names.
    """

    frozen = a_finalized_version(world)
    client = world["client"]
    sign_in_admin(client, "approval_manager")
    approved = approve(world, frozen)
    assert approved.status_code == 200, approved.text
    approval_id = approved.json()["approval"]["id"]

    sign_in_admin(client, "approval_accountant")
    replaced = replace(world, frozen, etag=f'"rv-{approved.json()["batch"]["record_version"]}"')
    assert replaced.status_code == 201, replaced.text

    recorded = rows(
        world,
        "SELECT entity_type, previous_values->>'operational', new_values->>'operational', "
        "new_values->>'replacement_version_id', reason FROM audit_logs "
        "WHERE action = 'payment_batch_approval.invalidated' AND entity_id = %s",
        approval_id,
    )
    assert recorded == [
        (
            "batch_approval",
            "true",
            "false",
            replaced.json()["current_version"]["id"],
            "a replacement version was created; no decision transfers to it",
        )
    ], recorded

    assert rows(
        world,
        "SELECT event_type FROM outbox_events WHERE aggregate_id = %s",
        replaced.json()["current_version"]["id"],
    ) == [], "an invalidation publishes nothing; the catalogue defines no event for it"


def test_replacing_a_version_nobody_decided_writes_no_invalidation(
    world: dict[str, Any],
) -> None:
    """The control, and without it the test above proves almost nothing.

    An implementation that wrote `payment_batch_approval.invalidated` on **every** replacement
    would pass every assertion above — the row would be there, with the right shape, for the
    right approval id. What makes the record mean something is that it appears only when a
    decision actually existed to invalidate.

    M6's replacement path is unchanged for this case, and that is the claim: a batch replaced
    before anybody approved it produces exactly the audit trail it did before slice 5A.
    """

    frozen = a_finalized_version(world)
    client = world["client"]
    sign_in_admin(client, "approval_accountant")

    replaced = replace(world, frozen, etag=frozen["etag"])
    assert replaced.status_code == 201, replaced.text

    assert rows(
        world,
        "SELECT 1 FROM audit_logs a JOIN payment_batch_versions v "
        "ON v.payment_batch_id = %s WHERE a.action = 'payment_batch_approval.invalidated' "
        "AND a.entity_id IN (SELECT id FROM batch_approvals "
        "                    WHERE payment_batch_version_id = v.id)",
        frozen["batch_id"],
    ) == [], "an invalidation was recorded for a version nobody had decided"


def test_the_separation_status_names_the_rule_that_refuses_each_actor(
    world: dict[str, Any],
) -> None:
    """`API-APPROVALREAD-003`. Three actors, three different answers.

    The negative control for this obligation is a status that always says "may decide" — which
    would render unchanged on the screen of the accountant who prepared the version, inviting a
    refusal instead of explaining one. So each actor is asserted separately, and the *reason*
    matters as much as the boolean: a preparer hands the file to a colleague, a finalizer asks a
    different manager, and the two remedies are not interchangeable.

    `approval_dual` prepares and `approval_accountant` finalizes, so the two refusals can be told
    apart at all.
    """

    frozen = a_finalized_version(
        world, prepared_by="approval_dual", finalized_by="approval_accountant"
    )
    client = world["client"]
    path = (
        f"/api/v1/payment-batches/{frozen['batch_id']}"
        f"/versions/{frozen['version_id']}/approval-view"
    )

    sign_in_admin(client, "approval_dual")
    prepared = client.get(path)
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["separation_of_duty"]["may_decide"] is False
    assert "prepared" in prepared.json()["separation_of_duty"]["reason"]

    sign_in_admin(client, "approval_accountant")
    finalized = client.get(path)
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["separation_of_duty"]["may_decide"] is False
    assert "finalized" in finalized.json()["separation_of_duty"]["reason"]

    sign_in_admin(client, "approval_manager")
    permitted = client.get(path)
    assert permitted.status_code == 200, permitted.text
    assert permitted.json()["separation_of_duty"] == {"may_decide": True, "reason": None}


def test_the_separation_status_agrees_with_what_the_command_does(
    world: dict[str, Any],
) -> None:
    """The status is advisory and must not disagree with the guard it advises about.

    A screen that said "you may decide" to somebody the command refuses would be worse than no
    status at all. So the claim is checked against the outcome: whoever the view says may decide,
    can; whoever it refuses, is refused with the matching rule.
    """

    frozen = a_finalized_version(
        world, prepared_by="approval_accountant", finalized_by="approval_dual"
    )
    client = world["client"]
    path = (
        f"/api/v1/payment-batches/{frozen['batch_id']}"
        f"/versions/{frozen['version_id']}/approval-view"
    )

    sign_in_admin(client, "approval_dual")
    advised = client.get(path).json()["separation_of_duty"]
    assert advised["may_decide"] is False

    refused = approve(world, frozen)
    assert refused.status_code == 400, refused.text
    # Both name the finalizer rule, in their own words.
    assert "finalized" in advised["reason"]
    assert "finalized" in refused.json()["error"]["message"]


def test_the_counts_come_from_the_version_not_the_live_tables(world: dict[str, Any]) -> None:
    """`API-APPROVALREAD-002`'s behavioural half.

    The beneficiary is renamed after the version is frozen. A count taken from `beneficiaries`
    would be answering "how many beneficiaries exist" on a screen asking "how many are in this
    file" — and the two diverge silently, which is the worst way for a number on an approval
    screen to be wrong.
    """

    frozen = a_finalized_version(world)
    client = world["client"]
    sign_in_admin(client, "approval_manager")

    before = client.get(
        f"/api/v1/payment-batches/{frozen['batch_id']}"
        f"/versions/{frozen['version_id']}/approval-view"
    )
    assert before.status_code == 200, before.text
    assert before.json()["request_count"] == 1
    assert before.json()["trader_count"] == 1
    assert before.json()["beneficiary_count"] == 1

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE beneficiaries SET status = 'inactive' WHERE id = %s",
            (world["beneficiary_id"],),
        )
        connection.commit()

    after = client.get(
        f"/api/v1/payment-batches/{frozen['batch_id']}"
        f"/versions/{frozen['version_id']}/approval-view"
    )
    assert after.json()["beneficiary_count"] == 1, (
        "the count moved when a live row changed; it must come from the version's own items"
    )

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE beneficiaries SET status = 'active' WHERE id = %s",
            (world["beneficiary_id"],),
        )
        connection.commit()


def test_the_queue_filters_to_what_is_awaiting_a_decision(world: dict[str, Any]) -> None:
    """`API-APPROVALREAD-004`. A queue, and a history that stays reachable.

    §13.4 requires a superseded version's page to remain readable, so the filter must be a
    filter and not the only view. Both are asserted: the flag narrows, its absence does not.
    """

    frozen = a_finalized_version(world)
    client = world["client"]
    sign_in_admin(client, "approval_manager")

    queued = client.get("/api/v1/payment-batches?awaiting_decision=true")
    assert queued.status_code == 200, queued.text
    waiting = {entry["id"] for entry in queued.json()["batches"]}
    assert frozen["batch_id"] in waiting

    assert approve(world, frozen).status_code == 200

    after = client.get("/api/v1/payment-batches?awaiting_decision=true")
    assert frozen["batch_id"] not in {entry["id"] for entry in after.json()["batches"]}, (
        "an approved version is still in the queue"
    )

    everything = client.get("/api/v1/payment-batches")
    assert frozen["batch_id"] in {entry["id"] for entry in everything.json()["batches"]}, (
        "the unfiltered list dropped it too; §13.4 needs the history readable"
    )


def test_the_queue_row_identifies_the_exact_version(world: dict[str, Any]) -> None:
    """`API-APPROVALREAD-001`'s behavioural half, and §13.2's opening sentence.

    "Each row must identify the exact version, not only the logical batch." A row carrying a
    batch reference alone would ask a manager to decide about a container that has had several
    versions — which is the defect that sentence exists to prevent.
    """

    frozen = a_finalized_version(world)
    sign_in_admin(world["client"], "approval_manager")

    listed = world["client"].get("/api/v1/payment-batches?awaiting_decision=true")
    assert listed.status_code == 200, listed.text
    row = next(
        entry for entry in listed.json()["batches"] if entry["id"] == frozen["batch_id"]
    )

    assert row["version_id"] == frozen["version_id"]
    assert row["version_number"] == 1
    assert row["bank"] == "Bank Ayandeh"
    assert row["source_account"] == "Centre Account"
    assert row["mapping_version"] == 1
    assert row["warning_count"] == 0
    assert row["prepared_by"] == "approval_accountant"
    assert row["finalized_by"] == "approval_accountant"
    assert row["version_created_at"] is not None


def test_the_approval_view_shows_the_decision_once_one_exists(world: dict[str, Any]) -> None:
    """`:1409` — "prior decision if any".

    A manager arriving after a colleague sees the answer rather than a button that will fail,
    and an auditor reads the same row without holding either decision grant.
    """

    frozen = a_finalized_version(world)
    client = world["client"]
    sign_in_admin(client, "approval_manager")
    approved = approve(world, frozen)
    assert approved.status_code == 200, approved.text

    sign_in_admin(client, "approval_auditor")
    view = client.get(
        f"/api/v1/payment-batches/{frozen['batch_id']}"
        f"/versions/{frozen['version_id']}/approval-view"
    )
    assert view.status_code == 200, view.text
    assert view.json()["prior_decision"]["decision"] == "approved"
    assert view.json()["prior_decision"]["approved_content_hash"] == frozen["content_hash"]
