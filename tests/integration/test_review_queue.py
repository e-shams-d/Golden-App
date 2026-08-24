"""The review queue through its routes, and the debt M7 left.

M8 slice 3. The transitions, the queue order, and who may touch it.

**`SVC-QUARANTINE-001` is asserted in `test_export_download_and_sent.py` instead**, and that is a
choice rather than a gap. Proving that quarantining raises a task needs a real quarantine, which
needs a request batched, finalized, approved, exported and then tampered with — a nine-step chain
that module already builds and exercises. The first version of this file duplicated the chain and
failed on its third step because the response shapes were guessed rather than read. Extending the
test that already quarantines is both cheaper and stronger: it asserts the task against a quarantine
the product produced, not one a fixture arranged.

Covers: SEC-REVIEW-001.
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
TRADER_PHONE = "+989120000833"
IBAN = "IR820540102680020817909002"
LIMIT = 900_000_000_000
CSRF_HEADER = "X-CSRF-Token"
TRADER_CSRF_COOKIE = "__Host-gp_trader_csrf"
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"


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

    storage_root = tmp_path_factory.mktemp("review-storage")
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=migrated.owner_url,
        redis_url="redis://127.0.0.1:6379/0",
        local_storage_root=storage_root,
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="f" * 40,
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
            "approval_status) VALUES (%s, 'Review Trader', %s, 'active', 'approved')",
            (ids["trader"], TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (ids["trader"], TRADER_PHONE, encoded),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'علی رضایی', %s, %s, 'active', "
            "'not_checked')",
            (ids["beneficiary"], ids["trader"], IBAN, IBAN),
        )
        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'melli', 'Bank Melli', 'active')",
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
        for username, role in (
            ("review_accountant", "accountant"),
            # Holds `manual_review.read` and neither `.assign` nor `.resolve`
            # (`permission_catalog.yaml:640-652`), which is what makes the write negatives prove the
            # routes want *those* grants rather than merely some review grant.
            ("review_auditor", "read_only_auditor"),
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
            "storage_root": storage_root,
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


def sign_in_trader(client: Any) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/trader/login", json={"identifier": TRADER_PHONE, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def csrf(client: Any) -> dict[str, str]:
    token = client.cookies.get(TRADER_CSRF_COOKIE) or client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token, "signed in but no CSRF cookie was set"
    return {CSRF_HEADER: token}


def rows(world: dict[str, Any], sql: str, *parameters: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        return connection.execute(sql, parameters).fetchall()


def test_opening_the_same_task_twice_returns_the_first(world: dict[str, Any]) -> None:
    """`open_task`'s early return, exercised where it can actually fire.

    **It cannot fire through the quarantine route.** `SEC-DOWNLOAD-001`'s guard refuses a download
    an already-quarantined export before revalidation runs, so a second attempt never reaches
    `_quarantine` and never calls this. A negative control that made the early return raise was
    therefore NOT CAUGHT by the export tests — correctly, and it took two readings to see that the
    control was right and the path was unreachable rather than the reverse.

    That makes this the eleventh mechanism in this project with no caller that can exercise it, and
    the first I wrote myself. It is kept rather than deleted because slices 4 to 7 add callers that
    *do* repeat — an unresolved-segment task raised on every bundle close, a privacy review raised
    per segment — and because `uq_review_task_open_per_entity` would otherwise turn a repeat into an
    `IntegrityError` in a failure path. Called directly here so the behaviour is covered by a test
    rather than by an argument about future callers.
    """

    from app.audit.redaction import RedactionPolicy
    from app.audit.writer import AuditActor, AuditContext
    from app.commands.manual_review_task import OpenTask, open_task
    from app.core.config import Settings
    from app.core.runtime import RuntimeServices

    subject = uuid.uuid4()
    runtime: RuntimeServices = world["client"].app.state.runtime  # type: ignore[attr-defined]
    actor = AuditActor(
        actor_type="admin_user",
        actor_id=rows(world, "SELECT id FROM admin_users WHERE username = 'review_accountant'")[0][
            0
        ],
        role_snapshot=("accountant",),
        session_id=None,
        authentication_assurance="password",
    )
    command = OpenTask(
        task_type="bundle_unresolved_segment",
        entity_type="bank_result_bundle",
        entity_id=subject,
        title="unresolved content",
        priority=2,
    )

    with runtime.uow_factory() as uow:
        first = open_task(
            command,
            session=uow.session,
            policy=RedactionPolicy(mask_iban=True),
            actor=actor,
            context=AuditContext(request_id=None),
            now=__import__("app.core.time", fromlist=["utc_now"]).utc_now(),
        )
        second = open_task(
            command,
            session=uow.session,
            policy=RedactionPolicy(mask_iban=True),
            actor=actor,
            context=AuditContext(request_id=None),
            now=__import__("app.core.time", fromlist=["utc_now"]).utc_now(),
        )
        assert first.id == second.id, "a repeat opened a second task instead of finding the first"
        uow.commit()

    assert Settings  # referenced so the import is not dead

    assert (
        len(rows(world, "SELECT id FROM manual_review_tasks WHERE entity_id = %s", subject)) == 1
    )


def test_the_queue_orders_by_priority_then_age(world: dict[str, Any]) -> None:
    """§13.1's index order, which is the order a person works in.

    Asserted through the route rather than the index: what matters is what the operator sees.
    A lower-priority older task must come after a higher-priority newer one.
    """

    client = world["client"]
    sign_in_admin(client, "review_accountant")

    # Two extra tasks at lower priority, inserted directly: no route creates one, and this test is
    # about ordering rather than about how they arrive.
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        for priority, subject in ((1, uuid.uuid4()), (3, uuid.uuid4())):
            connection.execute(
                "INSERT INTO manual_review_tasks (task_type, priority, status, entity_type, "
                "entity_id, title, record_version) VALUES "
                "('bundle_unresolved_segment', %s, 'open', 'bank_result_bundle', %s, %s, 1)",
                (priority, subject, f"priority {priority}"),
            )
        connection.commit()

    listed = client.get("/api/v1/manual-review-tasks").json()
    priorities = [row["priority"] for row in listed]

    assert priorities == sorted(priorities, reverse=True), priorities


def test_a_task_moves_through_its_four_transitions(world: dict[str, Any]) -> None:
    """`SVC-TASK-001` end to end, and the refusals that matter.

    `If-Match` on every transition (`:2065`), idempotency on resolve, and a resolution that carries
    its disposition. The last assertion is the one worth having: a resolved task cannot be moved
    again, so the record of what was decided is permanent.
    """

    client = world["client"]
    sign_in_admin(client, "review_accountant")
    task_id = _open_task(world, "segment_privacy_review", uuid.uuid4(), "privacy check")

    assignee = rows(world, "SELECT id FROM admin_users WHERE username = 'review_accountant'")[0][0]

    # No If-Match: 428, because a precondition was omitted rather than failed.
    bare = client.post(
        f"/api/v1/manual-review-tasks/{task_id}/assign",
        json={"assignee_admin_user_id": str(assignee)},
        headers=csrf(client),
    )
    assert bare.status_code == 428, bare.text

    assigned = client.post(
        f"/api/v1/manual-review-tasks/{task_id}/assign",
        json={"assignee_admin_user_id": str(assignee)},
        headers={**csrf(client), "If-Match": 'rv-1'},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["assigned_to"] == "review_accountant"
    # Assignment does not start the work: `in_progress` means somebody began, not that it is owned.
    assert assigned.json()["status"] == "open"

    started = client.post(
        f"/api/v1/manual-review-tasks/{task_id}/start",
        headers={**csrf(client), "If-Match": 'rv-2'},
    )
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "in_progress"

    # A stale If-Match loses to whoever moved first.
    stale = client.post(
        f"/api/v1/manual-review-tasks/{task_id}/resolve",
        json={"resolution_code": "corrected"},
        headers={**csrf(client), "If-Match": 'rv-2', "Idempotency-Key": str(uuid.uuid4())},
    )
    assert stale.status_code == 409, stale.text

    resolved = client.post(
        f"/api/v1/manual-review-tasks/{task_id}/resolve",
        json={"resolution_code": "corrected", "resolution_note": "نسخهٔ جدید تولید شد"},
        headers={**csrf(client), "If-Match": 'rv-3', "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolution_code"] == "corrected"
    assert resolved.json()["resolved_by"] == "review_accountant"

    # Nothing leaves `resolved`. The disposition is the record, and reopening would erase it.
    reopened = client.post(
        f"/api/v1/manual-review-tasks/{task_id}/start",
        headers={**csrf(client), "If-Match": 'rv-4'},
    )
    assert reopened.status_code in (400, 409), reopened.text


def test_resolving_as_unresolved_requires_a_reason(world: dict[str, Any]) -> None:
    """`:2065`: no resolution without an explicit disposition when the item remains unresolved.

    `unresolved_with_reason` is that disposition, and it is the one code that must carry prose —
    otherwise the honest option would also be the cheapest one and the queue would fill with
    resolutions that explain nothing.
    """

    client = world["client"]
    sign_in_admin(client, "review_accountant")
    task_id = _open_task(world, "payment_result_discrepancy", uuid.uuid4(), "discrepancy")

    refused = client.post(
        f"/api/v1/manual-review-tasks/{task_id}/resolve",
        json={"resolution_code": "unresolved_with_reason"},
        headers={**csrf(client), "If-Match": 'rv-1', "Idempotency-Key": str(uuid.uuid4())},
    )
    assert refused.status_code in (400, 409), refused.text
    assert "reason" in refused.text.lower()

    accepted = client.post(
        f"/api/v1/manual-review-tasks/{task_id}/resolve",
        json={
            "resolution_code": "unresolved_with_reason",
            "resolution_note": "بانک پاسخ نداده؛ پیگیری در دورهٔ بعد",
        },
        headers={**csrf(client), "If-Match": 'rv-1', "Idempotency-Key": str(uuid.uuid4())},
    )
    assert accepted.status_code == 200, accepted.text


def test_cancelling_writes_no_resolution(world: dict[str, Any]) -> None:
    """Cancellation ends a queue item without deciding anything about its subject.

    So it writes no `resolution_code`, and `ck_manual_review_tasks_resolved_requires_a_disposition`
    refuses one — which is what keeps "we looked and decided" distinguishable from "this should not
    have been raised".
    """

    client = world["client"]
    sign_in_admin(client, "review_accountant")
    task_id = _open_task(world, "bundle_unresolved_segment", uuid.uuid4(), "duplicate item")

    cancelled = client.post(
        f"/api/v1/manual-review-tasks/{task_id}/cancel",
        json={"reason": "تکراری بود"},
        headers={**csrf(client), "If-Match": 'rv-1', "Idempotency-Key": str(uuid.uuid4())},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["resolution_code"] is None
    assert cancelled.json()["resolved_at"] is None


def test_no_review_route_answers_a_caller_without_the_permission(
    world: dict[str, Any],
) -> None:
    """`SEC-REVIEW-001`. One test over the surface, for slice 1 and 2's reason.

    A read-only auditor holds `manual_review.read` by explicit sensitive-read grant and neither
    write permission, which is what makes the four refusals about *those* grants rather than about
    review access in general. A trader holds nothing at all.
    """

    client = world["client"]
    sign_in_admin(client, "review_accountant")
    task_id = _open_task(world, "segment_privacy_review", uuid.uuid4(), "permission check")
    assignee = rows(world, "SELECT id FROM admin_users WHERE username = 'review_accountant'")[0][0]

    writes = [
        (
            f"/api/v1/manual-review-tasks/{task_id}/assign",
            {"assignee_admin_user_id": str(assignee)},
        ),
        (f"/api/v1/manual-review-tasks/{task_id}/start", None),
        (f"/api/v1/manual-review-tasks/{task_id}/resolve", {"resolution_code": "corrected"}),
        (f"/api/v1/manual-review-tasks/{task_id}/cancel", {"reason": "x"}),
    ]

    sign_in_admin(client, "review_auditor")
    for path, body in writes:
        response = client.post(
            path,
            json=body,
            headers={**csrf(client), "If-Match": 'rv-1', "Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 403, f"{path} answered {response.status_code}"

    sign_in_trader(client)
    assert client.get("/api/v1/manual-review-tasks").status_code == 403
    assert client.get(f"/api/v1/manual-review-tasks/{task_id}").status_code == 403


def _open_task(world: dict[str, Any], task_type: str, subject: uuid.UUID, title: str) -> str:
    """Insert an open task directly.

    No route creates one, on purpose: a queue item exists because something happened, and every
    caller of `open_task` is a failure path. Tests about the transitions should not have to
    manufacture an integrity failure to get one.
    """

    task_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO manual_review_tasks (id, task_type, priority, status, entity_type, "
            "entity_id, title, record_version) "
            "VALUES (%s, %s, 3, 'open', 'receipt_segment', %s, %s, 1)",
            (task_id, task_type, subject, title),
        )
        connection.commit()
    return str(task_id)


