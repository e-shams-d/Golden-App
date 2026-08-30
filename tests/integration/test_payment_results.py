"""The first command that records money as having moved, and the seven things true before it does.

M9 slices 3 and 4, against a real PostgreSQL.

**Seven validations, seven provocations.** §17 `:1131` lists them and they are not
interchangeable: a single test of "it refused" would leave six unproved, and each has a different
failure in the world behind it.

    attempt was sent                   -> a `created` attempt is refused
    not cancelled or superseded        -> each refused separately, because one branch can serve both
    amount is exact                    -> asserted as an absence, in tests/backend
    evidence or approved exception     -> the link must be active and point at this attempt
    no duplicate conflict remains      -> one bank tracking number pays one attempt
    paid sum does not exceed requested -> a task is opened and the confirmation refused
    permission, version, idempotency   -> If-Match, the key, and a sharp negative actor

**The overpayment test asserts both halves in one test on purpose.** A block with no task is a
silent refusal nobody follows up; a task with no block is worse, because the money would read as
paid while somebody was asked to look into it. Splitting them would let either half pass alone.

Covers: SVC-CONFIRM-001, SVC-CONFIRM-002, SVC-CONFIRM-004, SVC-CONFIRM-005, SVC-CONFIRM-006,
SEC-CONFIRM-001, AUD-CONFIRM-001, SVC-AGGREGATE-001, SVC-AGGREGATE-002, CON-AGGREGATE-001.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery-staple"
CSRF_HEADER = "X-CSRF-Token"
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"

TRADER_PHONE = "+989120006601"
IBAN = "IR060120000000000000000066"

PAID_ACTION = "payment_attempt.paid_confirmed"
FAILED_ACTION = "payment_attempt.failed_confirmed"


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
        local_storage_root=tmp_path_factory.mktemp("result-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="h" * 40,
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
            "approval_status) VALUES (%s, 'Result Trader', %s, 'active', 'approved')",
            (ids["trader"], TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (ids["trader"], TRADER_PHONE, encoded),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'Ali Nine', %s, %s, 'active', "
            "'not_checked')",
            (ids["beneficiary"], ids["trader"], IBAN, IBAN),
        )
        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'refah', 'Bank Refah', 'active')",
            (ids["profile"],),
        )
        connection.execute(
            "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, status, "
            "default_transfer_limit_irr, after_cutoff_transfer_limit_irr, cutoff_time, "
            "splitting_enabled, required_fields, rules, config_hash) "
            "VALUES (%s, %s, 1, 'active', 1000000000, NULL, NULL, TRUE, '{}', '{}', %s)",
            (ids["version"], ids["profile"], "9" * 64),
        )
        connection.execute(
            "INSERT INTO bank_accounts (id, bank_profile_id, display_name, iban, "
            "normalized_iban, account_role, status) "
            "VALUES (%s, %s, 'Centre Account', %s, %s, 'outgoing_source', 'active')",
            (ids["account"], ids["profile"], IBAN, IBAN),
        )
        connection.execute(
            "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
            "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
            "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
            "original_or_derived_relation, metadata) "
            "VALUES (%s, 'local', 'gold', %s, 'receipt.pdf', 'application/pdf', 1024, %s, "
            "'bank_result_bundle_source', 'internal', 'available', 'clean', 'admin_user', "
            "'original', '{}')",
            (ids["file"], f"results/{ids['file']}", "e" * 64),
        )
        for username, role in (
            ("result_accountant", "accountant"),
            # Holds `payment_attempt.read` (`20260801_0008:313`) and **neither** confirmation
            # grant, which is what makes the permission negatives sharp: this actor gets past any
            # guard asking for merely some attempt permission.
            ("result_manager", "manager"),
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


def admin_id(world: dict[str, Any], username: str) -> uuid.UUID:
    found = rows(world, "SELECT id FROM admin_users WHERE username = %s", username)
    return uuid.UUID(str(found[0][0]))


def a_request_with_attempts(
    world: dict[str, Any], *, requested: int, splits: tuple[int, ...]
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """One request and its attempts, inserted directly.

    The split amounts are given rather than computed so a test can build the exact shape it needs
    — one attempt equal to the request, two that sum to it, or two that sum to more.
    """

    request_id = uuid.uuid4()
    revision_id = uuid.uuid4()
    attempts: list[uuid.UUID] = []

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
            "VALUES (%s, %s, 1, %s, 'Ali Nine', %s, %s, %s, 'trader_user')",
            (revision_id, request_id, world["beneficiary_id"], IBAN, requested, "f" * 64),
        )
        connection.execute(
            "UPDATE payment_requests SET current_revision_id = %s WHERE id = %s",
            (revision_id, request_id),
        )
        for number, amount in enumerate(splits, start=1):
            attempt_id = uuid.uuid4()
            connection.execute(
                "INSERT INTO payment_attempts (id, payment_request_id, "
                "payment_request_revision_id, attempt_number, attempt_type, amount_irr, "
                "beneficiary_name_snapshot, beneficiary_iban_snapshot, bank_profile_version_id, "
                "bank_account_id, split_rule_snapshot, status, record_version) "
                "VALUES (%s, %s, %s, %s, 'original', %s, 'Ali Nine', %s, %s, %s, '{}', "
                "'sent_to_bank', 1)",
                (
                    attempt_id,
                    request_id,
                    revision_id,
                    number,
                    amount,
                    IBAN,
                    world["version_id"],
                    world["account_id"],
                ),
            )
            attempts.append(attempt_id)
        connection.commit()
    return request_id, attempts


def a_segment_and_link(world: dict[str, Any], attempt_id: uuid.UUID) -> uuid.UUID:
    """An active primary evidence link for this attempt, through slice 2's own route."""

    segment_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO receipt_segments (id, source_file_id, rotation_degrees, "
            "creation_method, status, raw_extraction, created_by_actor_type, record_version) "
            "VALUES (%s, %s, 0, 'manual_external_attachment', 'candidate_found', '{}', "
            "'admin_user', 1)",
            (segment_id, world["file_id"]),
        )
        connection.commit()

    client = world["client"]
    created = client.post(
        "/api/v1/evidence-links",
        json={
            "payment_attempt_id": str(attempt_id),
            "receipt_segment_id": str(segment_id),
            "link_type": "primary",
        },
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert created.status_code == 201, created.text
    return uuid.UUID(created.json()["id"])


def version_of(world: dict[str, Any], attempt_id: uuid.UUID) -> int:
    return int(
        rows(world, "SELECT record_version FROM payment_attempts WHERE id = %s", attempt_id)[0][0]
    )


def confirm_paid(
    world: dict[str, Any], attempt_id: uuid.UUID, **overrides: Any
) -> Any:
    client = world["client"]
    body: dict[str, Any] = {
        "bank_tracking_number": overrides.pop(
            "tracking", str(uuid.uuid4().int)[:12]
        ),
        "bank_result_at": datetime.now(UTC).isoformat(),
    }
    body.update(overrides)
    idempotency = body.pop("idempotency", None) or str(uuid.uuid4())
    version = body.pop("version", None) or version_of(world, attempt_id)
    return client.post(
        f"/api/v1/payment-attempts/{attempt_id}/confirm-paid",
        json=body,
        headers={
            **csrf(client),
            "If-Match": f'"rv-{version}"',
            "Idempotency-Key": idempotency,
        },
    )


def confirm_failed(world: dict[str, Any], attempt_id: uuid.UUID, **overrides: Any) -> Any:
    client = world["client"]
    body: dict[str, Any] = {
        "failure_code": "bank_rejected",
        "failure_reason": "Bank rejected this row.",
    }
    body.update(overrides)
    version = body.pop("version", None) or version_of(world, attempt_id)
    return client.post(
        f"/api/v1/payment-attempts/{attempt_id}/confirm-failed",
        json=body,
        headers={
            **csrf(client),
            "If-Match": f'"rv-{version}"',
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )


def set_status(world: dict[str, Any], attempt_id: uuid.UUID, status: str) -> None:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE payment_attempts SET status = %s WHERE id = %s", (status, attempt_id)
        )
        connection.commit()


# ---------------------------------------------------------------------------------------------
# The seven validations.
# ---------------------------------------------------------------------------------------------


def test_an_attempt_that_was_never_sent_cannot_be_confirmed(world: dict[str, Any]) -> None:
    """`SVC-CONFIRM-001`. §17 `:1131`: the attempt must have been sent.

    Confirming one that never left claims a bank did something it was never asked to do.
    """

    _, attempts = a_request_with_attempts(world, requested=900_000_000, splits=(900_000_000,))
    set_status(world, attempts[0], "created")
    sign_in_admin(world["client"], "result_accountant")

    refused = confirm_paid(world, attempts[0])
    assert refused.status_code == 400, refused.text
    assert "created" in refused.text

    assert rows(
        world, "SELECT status, confirmed_at FROM payment_attempts WHERE id = %s", attempts[0]
    ) == [("created", None)]


@pytest.mark.parametrize("retired", ["cancelled", "superseded"])
def test_a_retired_attempt_cannot_be_confirmed(world: dict[str, Any], retired: str) -> None:
    """`SVC-CONFIRM-002`, **each status provoked separately**.

    One branch can serve both, and a test of one alone would pass against an implementation that
    forgot the other — which is how a two-case check ships with one case.

    **The message is asserted, not only the refusal.** A negative control showed that removing the
    retired branch changes no status code: `cancelled` and `superseded` are outside
    `CONFIRMABLE_FROM` too, so the generic branch refuses them anyway. What the retired branch adds
    is guidance — "a replacement or a cancellation already decided what happens to this money"
    sends the reader to the replacement, where "only sent_to_bank may be confirmed" sends them
    looking for a way to send it. Asserting the wording is what makes that branch provable.
    """

    _, attempts = a_request_with_attempts(world, requested=900_000_000, splits=(900_000_000,))
    set_status(world, attempts[0], retired)
    sign_in_admin(world["client"], "result_accountant")

    refused = confirm_paid(world, attempts[0])
    assert refused.status_code == 400, refused.text
    assert retired in refused.text
    assert "already decided what happens to this money" in refused.text, (
        "a retired attempt was refused by the generic branch, which tells the reader to send an "
        "attempt that a replacement or a cancellation has already settled"
    )
    assert rows(
        world, "SELECT status FROM payment_attempts WHERE id = %s", attempts[0]
    ) == [(retired,)]


def test_confirming_with_no_evidence_requires_a_reason(world: dict[str, Any]) -> None:
    """`SVC-CONFIRM-004`, and the plan's G-3.

    Doc 05 `:1580` requires a reason "by policy" and no approved document states the policy, so it
    is required in every evidence-free case. The owner still owes the decision on whether such a
    confirmation needs a second person.
    """

    _, attempts = a_request_with_attempts(world, requested=900_000_000, splits=(900_000_000,))
    sign_in_admin(world["client"], "result_accountant")

    refused = confirm_paid(world, attempts[0])
    assert refused.status_code == 400, refused.text
    assert "reason" in refused.text

    accepted = confirm_paid(
        world, attempts[0], evidence_unavailable_reason="bank portal receipt not downloadable"
    )
    assert accepted.status_code == 200, accepted.text


def test_an_evidence_link_must_be_active_and_point_at_this_attempt(
    world: dict[str, Any],
) -> None:
    """`SVC-CONFIRM-004`'s other half, both failures provoked.

    A link for a different attempt would make a paid result cite evidence for somebody else's
    payment; a revoked one would cite evidence somebody withdrew.
    """

    _, attempts = a_request_with_attempts(world, requested=900_000_000, splits=(900_000_000,))
    _, others = a_request_with_attempts(world, requested=500_000_000, splits=(500_000_000,))
    sign_in_admin(world["client"], "result_accountant")

    foreign_link = a_segment_and_link(world, others[0])
    refused = confirm_paid(world, attempts[0], primary_evidence_link_id=str(foreign_link))
    assert refused.status_code == 400, refused.text
    assert "different attempt" in refused.text

    own_link = a_segment_and_link(world, attempts[0])
    accepted = confirm_paid(world, attempts[0], primary_evidence_link_id=str(own_link))
    assert accepted.status_code == 200, accepted.text


def test_one_bank_tracking_number_pays_one_attempt(world: dict[str, Any]) -> None:
    """`SVC-CONFIRM-005`. "No duplicate conflict remains."

    A bank result read twice, or one transfer confirmed against two split rows, doubles the paid
    sum — and the overpayment check would then be the only thing between that and a wrong `paid`.
    """

    _, first = a_request_with_attempts(world, requested=400_000_000, splits=(400_000_000,))
    _, second = a_request_with_attempts(world, requested=400_000_000, splits=(400_000_000,))
    sign_in_admin(world["client"], "result_accountant")

    tracking = "900000000001"
    assert confirm_paid(
        world, first[0], tracking=tracking, evidence_unavailable_reason="portal"
    ).status_code == 200

    refused = confirm_paid(
        world, second[0], tracking=tracking, evidence_unavailable_reason="portal"
    )
    assert refused.status_code == 400, refused.text
    assert tracking in refused.text
    assert rows(
        world, "SELECT status FROM payment_attempts WHERE id = %s", second[0]
    ) == [("sent_to_bank",)]


def test_a_stale_if_match_is_refused(world: dict[str, Any]) -> None:
    """`SVC-CONFIRM-006`'s version half. `command_catalog.yaml` asks for `if_match_attempt`."""

    _, attempts = a_request_with_attempts(world, requested=900_000_000, splits=(900_000_000,))
    sign_in_admin(world["client"], "result_accountant")

    refused = confirm_paid(
        world, attempts[0], version=99, evidence_unavailable_reason="portal"
    )
    assert refused.status_code in (409, 412), refused.text
    assert rows(
        world, "SELECT status FROM payment_attempts WHERE id = %s", attempts[0]
    ) == [("sent_to_bank",)]


def test_a_replayed_confirmation_does_not_move_the_version(world: dict[str, Any]) -> None:
    """`SVC-CONFIRM-006`. "Duplicate paid confirmation is idempotent" — §17 `:1185`.

    **The assertion is that `record_version` did not move**, not merely that the second call
    returned 200. An idempotent-looking route that re-applies its effect passes the weaker one.
    """

    _, attempts = a_request_with_attempts(world, requested=900_000_000, splits=(900_000_000,))
    sign_in_admin(world["client"], "result_accountant")

    replayed = str(uuid.uuid4())
    first = confirm_paid(
        world,
        attempts[0],
        idempotency=replayed,
        evidence_unavailable_reason="portal",
        tracking="900000000002",
    )
    assert first.status_code == 200, first.text
    after_first = version_of(world, attempts[0])

    second = confirm_paid(
        world,
        attempts[0],
        idempotency=replayed,
        version=first.json()["record_version"],
        evidence_unavailable_reason="portal",
        tracking="900000000002",
    )
    assert second.status_code == 200, second.text
    assert version_of(world, attempts[0]) == after_first, (
        "the replay re-applied the confirmation and moved the attempt's version"
    )


# ---------------------------------------------------------------------------------------------
# The aggregate.
# ---------------------------------------------------------------------------------------------


def test_the_request_becomes_paid_only_when_the_sum_is_exact(world: dict[str, Any]) -> None:
    """`SVC-AGGREGATE-001`. §17 `:1141`, at one rial either side of the boundary.

    Two attempts that sum to the request: the first leaves it `partially_paid`, the second makes
    it `paid`. Testing with a comfortable margin would pass against a comparison written `>=`.
    """

    request_id, attempts = a_request_with_attempts(
        world, requested=900_000_000, splits=(400_000_000, 500_000_000)
    )
    sign_in_admin(world["client"], "result_accountant")

    first = confirm_paid(world, attempts[0], evidence_unavailable_reason="portal")
    assert first.status_code == 200, first.text
    assert first.json()["request_status"] == "partially_paid"
    assert rows(world, "SELECT status FROM payment_requests WHERE id = %s", request_id) == [
        ("partially_paid",)
    ]

    second = confirm_paid(world, attempts[1], evidence_unavailable_reason="portal")
    assert second.status_code == 200, second.text
    assert second.json()["request_status"] == "paid"
    assert rows(world, "SELECT status FROM payment_requests WHERE id = %s", request_id) == [
        ("paid",)
    ]


def test_an_overpayment_is_blocked_and_opens_a_task(world: dict[str, Any]) -> None:
    """`SVC-AGGREGATE-002`. **Both halves in one test, deliberately.**

    `04_Database_Schema.md:961` calls a paid sum above the requested amount a reconciliation error
    and never a normal paid; `:1606` says it creates a task and blocks closure. A block with no
    task is a silent refusal; a task with no block records the money as paid while somebody is
    asked to look into it. Either alone would pass a split test.

    The task's type is `payment_result_discrepancy` — already in M0's approved list, which is the
    plan's G-4 answered without inventing a value.
    """

    request_id, attempts = a_request_with_attempts(
        world, requested=900_000_000, splits=(500_000_000, 500_000_000)
    )
    sign_in_admin(world["client"], "result_accountant")

    assert confirm_paid(
        world, attempts[0], evidence_unavailable_reason="portal"
    ).status_code == 200

    refused = confirm_paid(world, attempts[1], evidence_unavailable_reason="portal")
    assert refused.status_code == 400, refused.text
    assert "reconciliation" in refused.text

    assert rows(
        world, "SELECT status FROM payment_attempts WHERE id = %s", attempts[1]
    ) == [("sent_to_bank",)], "the overpaying attempt was confirmed anyway"
    assert rows(world, "SELECT status FROM payment_requests WHERE id = %s", request_id) == [
        ("partially_paid",)
    ], "the request moved on an overpayment"

    tasks = rows(
        world,
        "SELECT task_type, entity_type, status FROM manual_review_tasks WHERE entity_id = %s",
        attempts[1],
    )
    assert tasks == [("payment_result_discrepancy", "payment_attempt", "open")], tasks


def test_two_concurrent_confirmations_do_not_both_read_a_stale_sum(
    world: dict[str, Any],
) -> None:
    """`CON-AGGREGATE-001`. `04_Database_Schema.md:961` calls it a locked service transaction.

    Two connections take the request lock; the second blocks until the first commits and then sees
    the updated sum. Without the lock both would read zero paid and both would decide
    `partially_paid` from a total that had already moved.

    Asserted on the **lock itself** rather than through two route calls, which a `TestClient`
    would run sequentially and which would prove nothing about concurrency.
    """

    request_id, _ = a_request_with_attempts(
        world, requested=900_000_000, splits=(400_000_000, 500_000_000)
    )

    first = psycopg.connect(_psycopg(world["owner_url"]))
    second = psycopg.connect(_psycopg(world["owner_url"]))
    try:
        first.execute("SELECT id FROM payment_requests WHERE id = %s FOR UPDATE", (request_id,))
        second.execute("SET lock_timeout = '750ms'")
        blocked = False
        try:
            second.execute(
                "SELECT id FROM payment_requests WHERE id = %s FOR UPDATE", (request_id,)
            )
        except psycopg.errors.LockNotAvailable:
            blocked = True
            second.rollback()
        first.rollback()
    finally:
        first.close()
        second.close()

    assert blocked, (
        "a second transaction took the request lock while the first held it, so two "
        "confirmations could both read a pre-payment sum"
    )


# ---------------------------------------------------------------------------------------------
# Failure, privileges, audit, permissions.
# ---------------------------------------------------------------------------------------------


def test_confirming_failed_records_the_reason_and_pays_nothing(world: dict[str, Any]) -> None:
    """§17.3, and the aggregate is recalculated by the same function so it cannot drift."""

    request_id, attempts = a_request_with_attempts(
        world, requested=900_000_000, splits=(900_000_000,)
    )
    sign_in_admin(world["client"], "result_accountant")

    failed = confirm_failed(world, attempts[0])
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "failed"

    assert rows(
        world,
        "SELECT status, failure_code, failure_reason FROM payment_attempts WHERE id = %s",
        attempts[0],
    ) == [("failed", "bank_rejected", "Bank rejected this row.")]

    assert rows(world, "SELECT status FROM payment_requests WHERE id = %s", request_id) == [
        ("sent_to_bank",)
    ], "a failure moved the request's status; no money was paid"


def test_the_runtime_cannot_rewrite_what_was_sent(world: dict[str, Any]) -> None:
    """`SEC-CONFIRM-001`, the live half.

    `20260830_0030` grants UPDATE on the result columns and on nothing else. Read back from
    `information_schema` as the role the application connects with, because a migration is a claim
    about a grant and this is the grant.
    """

    granted = {
        row[0]
        for row in rows(
            world,
            "SELECT column_name FROM information_schema.column_privileges "
            "WHERE table_name = 'payment_attempts' AND grantee = %s "
            "AND privilege_type = 'UPDATE'",
            world["app_role"],
        )
    }
    assert granted, "the runtime holds no column UPDATE at all; this query is finding nothing"

    forbidden = {
        "amount_irr",
        "beneficiary_iban_snapshot",
        "beneficiary_name_snapshot",
        "bank_profile_version_id",
        "attempt_number",
        "attempt_type",
        "payment_request_id",
        "payment_request_revision_id",
    }
    leaked = sorted(granted & forbidden)
    assert leaked == [], (
        f"the runtime can rewrite {leaked}. A confirmation records what the bank did and must not "
        "restate what was sent."
    )
    assert "status" in granted and "bank_tracking_number" in granted, sorted(granted)


def test_each_confirmation_writes_its_catalogued_action_and_event(
    world: dict[str, Any],
) -> None:
    """`AUD-CONFIRM-001`. Two actions, two events, and the request's new status on the row."""

    _, paid = a_request_with_attempts(world, requested=300_000_000, splits=(300_000_000,))
    _, failed = a_request_with_attempts(world, requested=300_000_000, splits=(300_000_000,))
    sign_in_admin(world["client"], "result_accountant")

    assert confirm_paid(
        world, paid[0], evidence_unavailable_reason="portal", tracking="900000000003"
    ).status_code == 200
    assert confirm_failed(world, failed[0]).status_code == 200

    audited = rows(
        world,
        "SELECT action, new_values->>'request_status' FROM audit_logs "
        "WHERE entity_id IN (%s, %s) ORDER BY action",
        paid[0],
        failed[0],
    )
    assert audited == [(FAILED_ACTION, "sent_to_bank"), (PAID_ACTION, "paid")], audited

    published = {
        row[0]
        for row in rows(
            world,
            "SELECT event_type FROM outbox_events WHERE aggregate_id IN (%s, %s)",
            paid[0],
            failed[0],
        )
    }
    assert published == {"PaymentAttemptPaid", "PaymentAttemptFailed"}, published


def test_confirming_paid_needs_the_confirm_paid_permission(world: dict[str, Any]) -> None:
    """`manager` holds `payment_attempt.read` and not this grant."""

    _, attempts = a_request_with_attempts(world, requested=900_000_000, splits=(900_000_000,))

    sign_in_admin(world["client"], "result_manager")
    assert confirm_paid(world, attempts[0], evidence_unavailable_reason="x").status_code == 403

    sign_in_admin(world["client"], "result_accountant")
    assert confirm_paid(
        world, attempts[0], evidence_unavailable_reason="portal"
    ).status_code == 200


def test_confirming_failed_needs_the_confirm_failed_permission(world: dict[str, Any]) -> None:
    _, attempts = a_request_with_attempts(world, requested=900_000_000, splits=(900_000_000,))

    sign_in_admin(world["client"], "result_manager")
    assert confirm_failed(world, attempts[0]).status_code == 403

    sign_in_admin(world["client"], "result_accountant")
    assert confirm_failed(world, attempts[0]).status_code == 200
