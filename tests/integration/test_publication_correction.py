"""Correcting a published result: N+1 exists, N survives, and one person cannot do it alone.

M9 slice 7B, against a real PostgreSQL. §17.7's eight steps, `04_Database_Schema.md:1162`,
`12_Security_RBAC_Audit.md:1345`, and ADR_INDEX's POL-002.

**POL-002's own words set the headline test**: "M9 correction and UAT must prove the control cannot
be configured off." So `SEC-CORRECTION-001` does not check that the approver holds a permission — it
grants one administrator *both* permissions, which is exactly what a deployment could do by
accident, and requires the correction to be refused anyway. A control that a grant can switch off
is not a control.

**`SVC-CORRECTION-001` reads publication N back column by column** through `row_to_json`, and only
`status` may have moved. That is enforced a level below the test: `20260903_0034` grants
`UPDATE (status)` and nothing else, so `summary_payload` and `content_hash` are unwritable by the
runtime rather than merely unwritten.

Covers: SVC-CORRECTION-001, SVC-CORRECTION-002, SEC-CORRECTION-001, TRACE-M9-001.
"""

from __future__ import annotations

import json
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

TRADER_PHONE = "+989120011001"
IBAN = "IR060120000000000000000110"
AMOUNT = 400_000_000

SUPERSEDED_ACTION = "payment_publication.superseded"
CORRECTED_EVENT = "TraderResultCorrected"


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
        local_storage_root=tmp_path_factory.mktemp("correction-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="p" * 40,
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
            "approval_status) VALUES (%s, 'Corrected Trader', %s, 'active', 'approved')",
            (ids["trader"], TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (ids["trader"], TRADER_PHONE, encoded),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'Ali Fifteen', %s, %s, 'active', "
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
            (ids["version"], ids["profile"], "a" * 64),
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
            "VALUES (%s, 'local', 'gold', %s, 'crop.png', 'image/png', 512, %s, "
            "'incoming_payment_receipt', 'internal', 'available', 'clean', 'admin_user', "
            "'derived', '{}')",
            (ids["file"], f"corrections/{ids['file']}", "b" * 64),
        )
        # **Both correction permissions have `default_roles: []`, so an administrator creates the
        # roles.** That is POL-002's design rather than a gap: "preparer and approver split".
        # Modelled here the way a deployment would do it — two roles, one permission each —
        # because granting through an existing role would give it to every accountant and the
        # split would be gone before the first test ran.
        for code, permission in (
            ("test_correction_preparer", "payment_attempt.correct_result"),
            ("test_correction_approver", "payment_publication.correct"),
        ):
            connection.execute(
                "INSERT INTO roles (code, description, is_system, is_enabled) "
                "VALUES (%s, 'M9 slice 7B split control', FALSE, TRUE)",
                (code,),
            )
            connection.execute(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT r.id, p.id FROM roles r, permissions p "
                "WHERE r.code = %s AND p.code = %s",
                (code, permission),
            )

        for username, roles in (
            # The preparer: an accountant who has also been given the preparer role.
            ("correction_preparer", ("accountant", "test_correction_preparer")),
            # The approver: the second human, holding only the approver grant.
            ("correction_approver", ("manager", "test_correction_approver")),
            # **Both roles on one person**, which is what an administrator can produce in two
            # clicks and what POL-002 says must still be refused.
            (
                "correction_soloist",
                ("accountant", "test_correction_preparer", "test_correction_approver"),
            ),
            # An ordinary accountant: holds `payment_publication.publish` and neither correction
            # grant. The default state, and the sharp negative for the route guard.
            ("correction_publisher", ("accountant",)),
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
    with TestClient(app, base_url="https://admin.localhost") as client:
        yield {
            "client": client,
            "app_role": migrated.app_role,
            "owner_url": migrated.owner_url,
            **{f"{name}_id": value for name, value in ids.items()},
        }
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def rows(world: dict[str, Any], sql: str, *parameters: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        return connection.execute(sql, parameters).fetchall()


def admin_id(world: dict[str, Any], username: str) -> uuid.UUID:
    return uuid.UUID(
        str(rows(world, "SELECT id FROM admin_users WHERE username = %s", username)[0][0])
    )


def sign_in_admin(world: dict[str, Any], username: str) -> None:
    client = world["client"]
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def csrf(world: dict[str, Any]) -> dict[str, str]:
    token = world["client"].cookies.get(ADMIN_CSRF_COOKIE)
    assert token, "signed in but no CSRF cookie was set"
    return {CSRF_HEADER: token}


def a_published_request(world: dict[str, Any]) -> dict[str, Any]:
    """A request at `result_published`, with a paid attempt, two segments and an active link."""

    request_id = uuid.uuid4()
    revision_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    first_segment = uuid.uuid4()
    second_segment = uuid.uuid4()
    # A third segment carrying the *same* crop file, so a correction onto it produces a
    # byte-identical snapshot through a different link row. See
    # `test_a_correction_that_changes_nothing_is_refused`.
    third_segment = uuid.uuid4()
    link_id = uuid.uuid4()
    publication_id = uuid.uuid4()
    who = admin_id(world, "correction_publisher")

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO payment_requests (id, trader_id, beneficiary_id, request_number, "
            "status, result_published_at, record_version) "
            "VALUES (%s, %s, %s, %s, 'result_published', now(), 1)",
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
            "VALUES (%s, %s, 1, %s, 'Ali Fifteen', %s, %s, %s, 'trader_user')",
            (revision_id, request_id, world["beneficiary_id"], IBAN, AMOUNT, "c" * 64),
        )
        connection.execute(
            "UPDATE payment_requests SET current_revision_id = %s WHERE id = %s",
            (revision_id, request_id),
        )
        connection.execute(
            "INSERT INTO payment_attempts (id, payment_request_id, "
            "payment_request_revision_id, attempt_number, attempt_type, amount_irr, "
            "beneficiary_name_snapshot, beneficiary_iban_snapshot, bank_profile_version_id, "
            "bank_account_id, split_rule_snapshot, status, bank_tracking_number, "
            "bank_result_at, confirmed_by_admin_user_id, confirmed_at, record_version) "
            "VALUES (%s, %s, %s, 1, 'original', %s, 'Ali Fifteen', %s, %s, %s, '{}', 'paid', "
            "'820250903001', now(), %s, now(), 1)",
            (
                attempt_id,
                request_id,
                revision_id,
                AMOUNT,
                IBAN,
                world["version_id"],
                world["account_id"],
                who,
            ),
        )
        for segment_id in (first_segment, second_segment, third_segment):
            connection.execute(
                "INSERT INTO receipt_segments (id, source_file_id, segment_file_id, "
                "rotation_degrees, creation_method, status, raw_extraction, "
                "created_by_actor_type, record_version) "
                "VALUES (%s, %s, %s, 0, 'manual_external_attachment', 'confirmed_linked', '{}', "
                "'admin_user', 1)",
                (segment_id, world["file_id"], world["file_id"]),
            )
            connection.execute(
                "INSERT INTO manual_review_tasks (task_type, entity_type, entity_id, "
                "entity_record_version, title, priority, status, resolution_code, resolved_at, "
                "resolved_by_admin_user_id, record_version) "
                "VALUES ('segment_privacy_review', 'receipt_segment', %s, 1, 'Privacy review', "
                "3, 'resolved', 'no_action_required', now(), %s, 1)",
                (segment_id, who),
            )
        connection.execute(
            "INSERT INTO confirmed_evidence_links (id, payment_attempt_id, receipt_segment_id, "
            "link_type, status, confirmed_by_admin_user_id, confirmed_at, published_to_trader_at) "
            "VALUES (%s, %s, %s, 'primary', 'active', %s, now(), now())",
            (link_id, attempt_id, first_segment, who),
        )
        connection.execute(
            "INSERT INTO payment_result_publications (id, payment_request_id, "
            "publication_version, status, summary_payload, primary_evidence_link_id, "
            "content_hash, published_by_admin_user_id, published_at) "
            "VALUES (%s, %s, 1, 'active', %s, %s, %s, %s, now())",
            (
                publication_id,
                request_id,
                json.dumps({"request_number": "PR-OLD", "evidence_file_id": "old"}),
                link_id,
                "d" * 64,
                who,
            ),
        )
        connection.commit()

    return {
        "request_id": request_id,
        "attempt_id": attempt_id,
        "link_id": link_id,
        "publication_id": publication_id,
        "first_segment": first_segment,
        "second_segment": second_segment,
        "third_segment": third_segment,
    }


def request_version(world: dict[str, Any], request_id: uuid.UUID) -> int:
    return int(
        rows(world, "SELECT record_version FROM payment_requests WHERE id = %s", request_id)[0][0]
    )


def correct(world: dict[str, Any], case: dict[str, Any], **overrides: Any) -> Any:
    client = world["client"]
    body: dict[str, Any] = {
        "replaces_evidence_link_id": str(case["link_id"]),
        "new_receipt_segment_id": str(case["second_segment"]),
        "correction_reason": "The first crop showed the wrong transaction.",
        "approved_by_admin_user_id": str(admin_id(world, "correction_approver")),
    }
    body.update({k: v for k, v in overrides.items() if k != "version"})
    version = overrides.get("version") or request_version(world, case["request_id"])
    return client.post(
        f"/api/v1/payment-requests/{case['request_id']}/publications/corrections",
        json=body,
        headers={
            **csrf(world),
            "If-Match": f'"rv-{version}"',
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )


def publications_of(world: dict[str, Any], request_id: uuid.UUID) -> list[tuple[Any, ...]]:
    return rows(
        world,
        "SELECT publication_version, status, supersedes_publication_id, correction_reason "
        "FROM payment_result_publications WHERE payment_request_id = %s "
        "ORDER BY publication_version",
        request_id,
    )


def publication_row(world: dict[str, Any], publication_id: uuid.UUID) -> Any:
    return rows(
        world,
        "SELECT row_to_json(t) FROM "
        "(SELECT * FROM payment_result_publications WHERE id = %s) t",
        publication_id,
    )[0][0]


def test_one_person_holding_both_permissions_is_still_refused(
    world: dict[str, Any],
) -> None:
    """`SEC-CORRECTION-001`. POL-002: "the control cannot be configured off."

    **The headline test of this slice.** `correction_soloist` holds `payment_publication.correct`
    *and* is an accountant, which is what an administrator can produce in two clicks. The
    permission check passes and the correction is refused anyway, because the separation is a
    comparison of two identifiers rather than a question about grants.
    """

    case = a_published_request(world)
    sign_in_admin(world, "correction_soloist")
    soloist = admin_id(world, "correction_soloist")

    response = correct(world, case, approved_by_admin_user_id=str(soloist))
    assert response.status_code == 400, response.text
    assert "two people" in response.text
    assert len(publications_of(world, case["request_id"])) == 1


def test_a_named_approver_must_hold_the_grant(world: dict[str, Any]) -> None:
    """The other half of POL-002's split, and neither half is sufficient alone.

    `_refuse_a_single_human` stops one person doing both. This stops a preparer approving their own
    correction by typing any colleague's id: the approver's grant is read from the approver's own
    roles, so naming somebody who does not hold `payment_publication.correct` is not a second
    authorisation.
    """

    case = a_published_request(world)
    sign_in_admin(world, "correction_preparer")

    response = correct(
        world,
        case,
        approved_by_admin_user_id=str(admin_id(world, "correction_publisher")),
    )
    assert response.status_code == 400, response.text
    assert "does not hold" in response.text
    assert len(publications_of(world, case["request_id"])) == 1


def test_nobody_holds_the_correction_permission_by_default(world: dict[str, Any]) -> None:
    """POL-002 keeps `default_roles: []`, so the accountant who can publish cannot correct.

    The sharp negative: `correction_publisher` holds `payment_publication.publish` and every other
    accountant grant, and is refused here by the route guard rather than by the command.
    """

    case = a_published_request(world)
    sign_in_admin(world, "correction_publisher")

    response = correct(world, case)
    assert response.status_code == 403, response.text
    assert len(publications_of(world, case["request_id"])) == 1


def test_a_correction_creates_n_plus_one_and_supersedes_n(world: dict[str, Any]) -> None:
    """`SVC-CORRECTION-002`, and §17.7's fifth and sixth steps in one transaction."""

    case = a_published_request(world)
    sign_in_admin(world, "correction_preparer")

    response = correct(world, case)
    assert response.status_code == 201, response.text
    assert response.json()["publication_version"] == 2

    versions = publications_of(world, case["request_id"])
    assert len(versions) == 2, versions
    assert versions[0][:2] == (1, "superseded")
    assert versions[1][1] == "active"
    assert uuid.UUID(str(versions[1][2])) == case["publication_id"]
    assert "wrong transaction" in versions[1][3]

    active = [row for row in versions if row[1] == "active"]
    assert len(active) == 1, (
        "more than one publication is active. `uq_active_publication_per_request` refuses that, "
        "so this would mean the supersession and the insert did not share a transaction."
    )


def test_publication_n_survives_byte_for_byte_except_its_status(
    world: dict[str, Any],
) -> None:
    """`SVC-CORRECTION-001`. §17.7's second step, and the reason the grant is one column wide.

    Every column read before and after through `row_to_json`. `status` is permitted to move and
    nothing else is — enforced by `20260903_0034` granting `UPDATE (status)` alone, so this test
    asserts a property the database holds rather than one the command remembers.
    """

    case = a_published_request(world)
    before = publication_row(world, case["publication_id"])
    sign_in_admin(world, "correction_preparer")
    assert correct(world, case).status_code == 201

    after = publication_row(world, case["publication_id"])
    changed = {key for key in before if before[key] != after.get(key)}
    assert changed == {"status"}, (
        f"publication 1 changed in {sorted(changed)}. Only `status` may move; the payload, the "
        "hash and the actor are what the trader was shown and must survive the correction."
    )
    assert after["status"] == "superseded"


def test_the_old_evidence_is_replaced_and_kept(world: dict[str, Any]) -> None:
    """§12.6 at `:1306`: replacement "never deletes or overwrites the old relationship".

    That is what lets publication 1 still resolve — it points at a `replaced` link that is still
    there, which is the difference between preserving history and describing it.
    """

    case = a_published_request(world)
    sign_in_admin(world, "correction_preparer")
    assert correct(world, case).status_code == 201

    links = rows(
        world,
        "SELECT status, replaces_link_id, receipt_segment_id FROM confirmed_evidence_links "
        "WHERE payment_attempt_id = %s ORDER BY confirmed_at",
        case["attempt_id"],
    )
    assert len(links) == 2, links
    assert links[0][0] == "replaced"
    assert links[1][0] == "active"
    assert uuid.UUID(str(links[1][1])) == case["link_id"]
    assert uuid.UUID(str(links[1][2])) == case["second_segment"]


def test_the_ordinary_replacement_route_refuses_published_evidence(
    world: dict[str, Any],
) -> None:
    """The hole this slice closed, and it had been open since slice 2.

    An accountant with `evidence_link.replace` could swap the evidence under a published result:
    the old link became `replaced`, the publication went on citing it, and the trader went on being
    shown evidence that had been retired — with no approval, no publication N+1 and no
    notification. Doc 05 `:1855` requires all three.
    """

    case = a_published_request(world)
    sign_in_admin(world, "correction_publisher")

    response = world["client"].post(
        f"/api/v1/evidence-links/{case['link_id']}/replace",
        json={
            "new_receipt_segment_id": str(case["second_segment"]),
            "replacement_reason": "swapping it quietly",
        },
        headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 400, response.text
    assert "published result" in response.text

    status = rows(
        world, "SELECT status FROM confirmed_evidence_links WHERE id = %s", case["link_id"]
    )[0][0]
    assert status == "active", "the link was retired by the route that is supposed to refuse it"


def test_a_correction_that_changes_nothing_is_refused(world: dict[str, Any]) -> None:
    """`uq_publication_content_per_request`, reached before the supersession rather than after.

    The constraint would refuse the row anyway — but by then publication 1 is already superseded
    and the caller gets a duplicate-key error that explains nothing. The comparison uses the same
    digest the index holds, so the two cannot disagree.
    """

    case = a_published_request(world)
    sign_in_admin(world, "correction_preparer")
    assert correct(world, case).status_code == 201

    # Correct again, to a **third** segment carrying the same crop file. The link differs, so the
    # plain unique on `(attempt, segment, type)` is satisfied; the snapshot is byte-identical,
    # because what a publication shows is the crop rather than which segment row produced it.
    #
    # Correcting *back* to the first segment was the obvious way to write this and is impossible:
    # `uq_evidence_link_attempt_segment_type` refuses a second link for a pair that already has
    # one, even a `replaced` one. That constraint is doing its job — a segment cannot be re-linked
    # to an attempt it was already linked to — and it means "identical content" has to be reached
    # through a different row rather than the same one.
    second = correct(
        world,
        case,
        replaces_evidence_link_id=str(
            rows(
                world,
                "SELECT id FROM confirmed_evidence_links WHERE payment_attempt_id = %s "
                "AND status = 'active'",
                case["attempt_id"],
            )[0][0]
        ),
        new_receipt_segment_id=str(case["third_segment"]),
    )
    assert second.status_code == 400, second.text
    assert "identical" in second.text
    assert len(publications_of(world, case["request_id"])) == 2


def test_a_correction_audits_both_humans_and_notifies_the_trader(
    world: dict[str, Any],
) -> None:
    """§17.7's seventh and eighth steps, and the reason slice 7 came first.

    The audit row names the preparer and the approver: an entry recording only the calling session
    would describe a dual-control decision as one person's act, which is the one question anybody
    would ask afterwards.
    """

    case = a_published_request(world)
    sign_in_admin(world, "correction_preparer")
    response = correct(world, case)
    assert response.status_code == 201, response.text
    corrected_id = response.json()["id"]

    audit = rows(
        world,
        "SELECT new_values, reason FROM audit_logs WHERE entity_id = %s AND action = %s",
        corrected_id,
        SUPERSEDED_ACTION,
    )
    assert len(audit) == 1, audit
    assert audit[0][0]["prepared_by_admin_user_id"] == str(admin_id(world, "correction_preparer"))
    assert audit[0][0]["approved_by_admin_user_id"] == str(admin_id(world, "correction_approver"))
    assert "wrong transaction" in audit[0][1]

    events = rows(
        world,
        "SELECT event_type, payload FROM outbox_events WHERE aggregate_id = %s",
        corrected_id,
    )
    assert len(events) == 1, events
    assert events[0][0] == CORRECTED_EVENT
    assert events[0][1]["supersedes_version"] == 1

    # Slice 7's projection turns that event into the notification §17.7 requires. Run here rather
    # than assumed, because "notify the trader" is a step and not an intention.
    from app.notifications.projection import notification_deliverer
    from app.workers.dispatcher import dispatch_once

    runtime = world["client"].app.state.runtime
    dispatch_once(
        runtime.uow_factory,
        notification_deliverer(runtime.uow_factory),
        worker_id="correction-test",
    )
    messages = rows(
        world,
        "SELECT notification_type FROM notifications WHERE entity_id = %s",
        corrected_id,
    )
    assert [row[0] for row in messages] == ["payment_result_corrected"], messages


def test_a_correction_opens_a_sensitive_review_task(world: dict[str, Any]) -> None:
    """§17.7's first step. The task names the new publication, so the queue lands on what the
    trader is being shown now rather than on what they were shown before."""

    case = a_published_request(world)
    sign_in_admin(world, "correction_preparer")
    response = correct(world, case)
    assert response.status_code == 201, response.text

    task = rows(
        world,
        "SELECT task_type, entity_type, entity_record_version, priority FROM manual_review_tasks "
        "WHERE entity_id = %s",
        response.json()["id"],
    )
    assert len(task) == 1, task
    assert task[0][:2] == ("payment_result_discrepancy", "payment_result_publication")
    assert task[0][2] == 2
    assert task[0][3] == 5


def test_the_runtime_may_update_only_the_publication_status(world: dict[str, Any]) -> None:
    """The grant itself, read from `information_schema` rather than inferred from behaviour.

    **This test exists because a negative control went uncaught.** Widening `GRANTED_COLUMNS` to
    include `summary_payload` and `content_hash` changed nothing observable: the command does not
    write them, so every behavioural assertion still passed. A grant is a *capability*, and the
    only thing that can see one is a query about privileges — which is the argument
    `test_batching_table_privileges.py` opens with, applied one table further along.

    What it buys: "publication N survives byte for byte" stops depending on this command
    continuing to behave, and becomes something the next command physically cannot break.
    """

    granted = rows(
        world,
        "SELECT DISTINCT column_name FROM information_schema.column_privileges "
        "WHERE table_name = 'payment_result_publications' AND privilege_type = 'UPDATE' "
        "AND grantee = %s ORDER BY column_name",
        world["app_role"],
    )
    assert [row[0] for row in granted] == ["status"], (
        f"the runtime may update {[row[0] for row in granted]} on a publication. "
        "`04_Database_Schema.md:1162` permits exactly one change to an existing publication — it "
        "becomes `superseded` — and everything else on the row is what a trader was shown."
    )


def test_every_published_result_traces_back_to_its_bank_source(
    world: dict[str, Any],
) -> None:
    """`TRACE-M9-001`. §17 `:1200`, the milestone's Definition of Done.

    "Every trader-visible result can be traced through publication → confirmed result → confirmed
    evidence → exact bank-result source and the full correction history is preserved."

    Walked in SQL rather than asserted per hop in Python, because the claim is that the *joins*
    resolve — a chain that needs application code to follow is one an auditor cannot follow.
    """

    case = a_published_request(world)
    sign_in_admin(world, "correction_preparer")
    assert correct(world, case).status_code == 201

    chain = rows(
        world,
        "SELECT p.publication_version, p.status, a.status, a.bank_tracking_number, "
        "       l.status, s.source_file_id "
        "FROM payment_result_publications p "
        "JOIN confirmed_evidence_links l ON l.id = p.primary_evidence_link_id "
        "JOIN payment_attempts a ON a.id = l.payment_attempt_id "
        "JOIN receipt_segments s ON s.id = l.receipt_segment_id "
        "WHERE p.payment_request_id = %s ORDER BY p.publication_version",
        case["request_id"],
    )

    assert len(chain) == 2, (
        f"only {len(chain)} of this request's publications resolve to a bank source. The "
        "superseded one must resolve too — §17 `:1200` requires the full correction history to be "
        "preserved, and a chain that breaks when a version is superseded preserves nothing."
    )
    assert chain[0][1] == "superseded"
    assert chain[0][4] == "replaced", (
        "publication 1 no longer points at a link that exists in the state it was published in"
    )
    assert chain[1][1] == "active"
    assert chain[1][4] == "active"
    for row in chain:
        assert row[2] == "paid"
        assert row[3] == "820250903001"
        assert row[5] is not None, "the evidence does not name the bank document it came from"
