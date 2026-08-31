"""Publishing a result: three uniques, one hash, and nothing a client could have made up.

M9 slice 5, against a real PostgreSQL. `05_API_Specification.md` §20.1-20.2,
`04_Database_Schema.md` §11.9, `15_Agent_Implementation_Plan.md` §17.6.

**The most interesting test here is the one that publishes twice.** `UNIQUE(payment_request_id,
content_hash)` refuses a republished identical snapshot, and it can only do that because the
digest is blind to the clock, to the counter and to who pressed the button. A test that merely
published once would pass against a hash that included `published_at` — and that hash would make
the constraint permanently unable to fire while still appearing in every schema report.

**Immutability is asserted against the runtime role, not against the owner.** `SET ROLE` does not
survive a `ROLLBACK` and the owner may do anything, which is the trap
`test_batching_table_privileges.py` documents at length: a test that tried to UPDATE as the owner
would succeed and prove nothing.

Covers: DB-PUBLICATION-001, SVC-PUBLICATION-001, SVC-PUBLICATION-002, SVC-PUBLICATION-004,
SVC-PUBLICATION-005, SEC-PUBLICATION-001, SEC-PUBLICATION-002, AUD-PUBLICATION-002.
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

TRADER_PHONE = "+989120008001"
IBAN = "IR060120000000000000000080"

PUBLISH_ACTION = "payment_publication.created"
PUBLISH_EVENT = "PaymentResultPublicationCreated"

AMOUNT = 700_000_000


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
        local_storage_root=tmp_path_factory.mktemp("publication-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="k" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    ids = {
        name: uuid.uuid4()
        for name in (
            "trader",
            "beneficiary",
            "profile",
            "version",
            "account",
            "bundle_file",
            "crop_file",
        )
    }

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'Publication Trader', %s, 'active', 'approved')",
            (ids["trader"], TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (ids["trader"], TRADER_PHONE, encoded),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'Ali Twelve', %s, %s, 'active', "
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
            "VALUES (%s, %s, 1, 'active', 1000000000, NULL, NULL, TRUE, '{}', '{}', %s)",
            (ids["version"], ids["profile"], "a" * 64),
        )
        connection.execute(
            "INSERT INTO bank_accounts (id, bank_profile_id, display_name, iban, "
            "normalized_iban, account_role, status) "
            "VALUES (%s, %s, 'Centre Account', %s, %s, 'outgoing_source', 'active')",
            (ids["account"], ids["profile"], IBAN, IBAN),
        )
        # Two files, and the difference between them is the whole of `SEC-PUBLICATION-001`: the
        # bundle is every trader's results in one document, the crop is this payment alone.
        for key, purpose, name in (
            ("bundle_file", "bank_result_bundle_source", "bundle.pdf"),
            ("crop_file", "incoming_payment_receipt", "crop.png"),
        ):
            connection.execute(
                "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
                "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
                "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
                "original_or_derived_relation, metadata) "
                "VALUES (%s, 'local', 'gold', %s, %s, 'application/pdf', 1024, %s, %s, "
                "'internal', 'available', 'clean', 'admin_user', 'original', '{}')",
                (ids[key], f"publications/{ids[key]}", name, "b" * 64, purpose),
            )
        for username, role in (
            # Holds `payment_publication.preview` and `.publish` (`20260801_0008:250-251`).
            ("publication_accountant", "accountant"),
            # Holds every batch approval permission and neither publication grant. The sharp
            # negative: seniority is not the thing these routes ask for.
            ("publication_manager", "manager"),
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
    return uuid.UUID(
        str(rows(world, "SELECT id FROM admin_users WHERE username = %s", username)[0][0])
    )


def a_paid_request(world: dict[str, Any], *, status: str = "paid") -> dict[str, Any]:
    """One request, one revision, one attempt already `paid`, and its crop.

    Inserted directly rather than driven through five milestones of API calls, for the reason
    every M9 module gives: this file's subject is what publication does, and building the state
    through the confirmation route would make each test here depend on slice 3 as well.
    """

    request_id = uuid.uuid4()
    revision_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    segment_id = uuid.uuid4()

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO payment_requests (id, trader_id, beneficiary_id, request_number, "
            "status, record_version) VALUES (%s, %s, %s, %s, %s, 1)",
            (
                request_id,
                world["trader_id"],
                world["beneficiary_id"],
                f"PR-{str(request_id)[:8]}",
                status,
            ),
        )
        connection.execute(
            "INSERT INTO payment_request_revisions (id, payment_request_id, revision_number, "
            "beneficiary_id, beneficiary_name_snapshot, beneficiary_iban_snapshot, amount_irr, "
            "content_hash, created_by_actor_type) "
            "VALUES (%s, %s, 1, %s, 'Ali Twelve', %s, %s, %s, 'trader_user')",
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
            "VALUES (%s, %s, %s, 1, 'original', %s, 'Ali Twelve', %s, %s, %s, '{}', 'paid', "
            "'820250830001', now(), %s, now(), 1)",
            (
                attempt_id,
                request_id,
                revision_id,
                AMOUNT,
                IBAN,
                world["version_id"],
                world["account_id"],
                # §19.3's first guard reads this column, not the request's derived status. A
                # fixture that left it null would be setting up a state slice 3 cannot produce.
                admin_id(world, "publication_accountant"),
            ),
        )
        # `source_file_id` is the bundle and `segment_file_id` is the crop. Both set, because a
        # real segment has both and the test would be weaker if the unsafe one were absent.
        connection.execute(
            "INSERT INTO receipt_segments (id, source_file_id, segment_file_id, "
            "rotation_degrees, creation_method, status, raw_extraction, created_by_actor_type, "
            "record_version) "
            "VALUES (%s, %s, %s, 0, 'manual_external_attachment', 'confirmed_linked', '{}', "
            "'admin_user', 1)",
            (segment_id, world["bundle_file_id"], world["crop_file_id"]),
        )
        connection.commit()

    return {
        "request_id": request_id,
        "revision_id": revision_id,
        "attempt_id": attempt_id,
        "segment_id": segment_id,
    }


def an_evidence_link(
    world: dict[str, Any],
    case: dict[str, Any],
    *,
    status: str = "active",
    segment_id: uuid.UUID | None = None,
) -> uuid.UUID:
    link_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO confirmed_evidence_links (id, payment_attempt_id, receipt_segment_id, "
            "link_type, status, confirmed_by_admin_user_id, confirmed_at) "
            "VALUES (%s, %s, %s, 'primary', %s, %s, now())",
            (
                link_id,
                case["attempt_id"],
                segment_id or case["segment_id"],
                status,
                admin_id(world, "publication_accountant"),
            ),
        )
        connection.commit()
    return link_id


def preview(world: dict[str, Any], request_id: uuid.UUID, **body: Any) -> Any:
    client = world["client"]
    return client.post(
        f"/api/v1/payment-requests/{request_id}/publications/preview",
        json=body,
        headers=csrf(client),
    )


def request_version(world: dict[str, Any], request_id: uuid.UUID) -> int:
    return int(
        rows(world, "SELECT record_version FROM payment_requests WHERE id = %s", request_id)[0][0]
    )


def publish(world: dict[str, Any], request_id: uuid.UUID, **body: Any) -> Any:
    """`If-Match` against the **request**, per §19.3's eighth guard.

    The version is read here rather than passed by each test, because the header is a
    concurrency control and not the subject of most of these tests. The one test whose subject
    it *is* passes `version=` explicitly.
    """

    client = world["client"]
    version = body.pop("version", None) or request_version(world, request_id)
    return client.post(
        f"/api/v1/payment-requests/{request_id}/publications",
        json=body,
        headers={
            **csrf(client),
            "If-Match": f'"rv-{version}"',
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )


def a_resolved_privacy_review(world: dict[str, Any], segment_id: uuid.UUID) -> uuid.UUID:
    """A `segment_privacy_review` task, resolved against the segment's current version.

    §16.5's check is a version comparison rather than a flag, so the task has to record the
    version its reviewer looked at. Inserted directly: M8 owns the review workflow and driving it
    here would make every publication test depend on that milestone's routes.
    """

    task_id = uuid.uuid4()
    version = int(
        rows(world, "SELECT record_version FROM receipt_segments WHERE id = %s", segment_id)[0][0]
    )
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO manual_review_tasks (id, task_type, entity_type, entity_id, "
            "entity_record_version, title, priority, status, resolution_code, resolved_at, "
            "resolved_by_admin_user_id, record_version) "
            "VALUES (%s, 'segment_privacy_review', 'receipt_segment', %s, %s, "
            "'Privacy review', 3, 'resolved', 'no_action_required', now(), %s, 1)",
            (task_id, segment_id, version, admin_id(world, "publication_accountant")),
        )
        connection.commit()
    return task_id


def publications_of(world: dict[str, Any], request_id: uuid.UUID) -> list[tuple[Any, ...]]:
    return rows(
        world,
        "SELECT publication_version, status, content_hash FROM payment_result_publications "
        "WHERE payment_request_id = %s ORDER BY publication_version",
        request_id,
    )


def test_a_preview_validates_and_persists_no_publication(world: dict[str, Any]) -> None:
    """§20.1: "It is not persisted as active publication."

    And `06_Workflows_and_State_Machines.md:600`: the preview *is* what moves a `paid` request to
    `result_ready_for_trader`. Both halves asserted together, because getting one right and the
    other wrong is what "not persisted" would otherwise hide.
    """

    sign_in_admin(world["client"], "publication_accountant")
    case = a_paid_request(world)

    response = preview(world, case["request_id"])
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["next_publication_version"] == 1
    assert body["request_status"] == "result_ready_for_trader"
    assert len(body["content_hash"]) == 64
    assert publications_of(world, case["request_id"]) == []

    stored = rows(
        world, "SELECT status FROM payment_requests WHERE id = %s", case["request_id"]
    )
    assert stored[0][0] == "result_ready_for_trader"


def test_the_preview_hash_is_the_published_hash(world: dict[str, Any]) -> None:
    """`SVC-PUBLICATION-001`. Canonical and stable across a re-computation.

    Not a re-render of the same object in one call: the preview and the publish are two requests,
    two transactions and two constructions of the payload. If `unversioned_digest` depended on
    dictionary ordering or on anything about the process, this is where it would show.
    """

    sign_in_admin(world["client"], "publication_accountant")
    case = a_paid_request(world)
    link_id = an_evidence_link(world, case)
    a_resolved_privacy_review(world, case["segment_id"])

    first = preview(world, case["request_id"], primary_evidence_link_id=str(link_id))
    assert first.status_code == 200, first.text
    second = preview(world, case["request_id"], primary_evidence_link_id=str(link_id))
    assert second.status_code == 200, second.text
    assert first.json()["content_hash"] == second.json()["content_hash"], (
        "two previews of one unchanged result produced different digests, so the hash depends on "
        "something other than the content"
    )

    published = publish(world, case["request_id"], primary_evidence_link_id=str(link_id))
    assert published.status_code == 201, published.text
    assert published.json()["content_hash"] == first.json()["content_hash"], (
        "the published hash differs from the previewed one, so a publisher approved a snapshot "
        "and something else was stored"
    )


def test_the_snapshot_is_derived_and_masks_the_iban(world: dict[str, Any]) -> None:
    """§17 `:1153`'s content, and the IBAN masked before it is stored.

    The stored JSONB is read back from the database rather than from the response, because the
    thing that must be safe for years is the column.
    """

    sign_in_admin(world["client"], "publication_accountant")
    case = a_paid_request(world)
    link_id = an_evidence_link(world, case)
    a_resolved_privacy_review(world, case["segment_id"])

    assert preview(world, case["request_id"]).status_code == 200
    response = publish(world, case["request_id"], primary_evidence_link_id=str(link_id))
    assert response.status_code == 201, response.text

    stored = rows(
        world,
        "SELECT summary_payload FROM payment_result_publications WHERE payment_request_id = %s",
        case["request_id"],
    )[0][0]

    assert stored["beneficiary_name"] == "Ali Twelve"
    assert stored["amount_irr"] == str(AMOUNT)
    assert stored["paid_total_irr"] == str(AMOUNT)
    assert stored["attempts"][0]["bank_name"] == "Bank Melli"
    assert stored["attempts"][0]["bank_tracking_number"] == "820250830001"
    assert stored["evidence_file_id"] == str(world["crop_file_id"])

    masked = stored["beneficiary_iban_masked"]
    assert masked != IBAN, "the full IBAN was written into a column retained for years"
    assert masked.startswith("IR06") and masked.endswith(IBAN[-4:]), masked
    assert IBAN not in str(stored), f"the full IBAN appears somewhere in {stored}"


def test_the_bundle_never_enters_a_publication(world: dict[str, Any]) -> None:
    """`SEC-PUBLICATION-001`, at the point where the file id is chosen.

    The segment in `a_paid_request` carries both file ids. The publication must take the crop, and
    the assertion is against the bundle's id specifically rather than "some file id".
    """

    sign_in_admin(world["client"], "publication_accountant")
    case = a_paid_request(world)
    link_id = an_evidence_link(world, case)
    a_resolved_privacy_review(world, case["segment_id"])

    assert preview(world, case["request_id"]).status_code == 200
    response = publish(world, case["request_id"], primary_evidence_link_id=str(link_id))
    assert response.status_code == 201, response.text

    payload = response.json()["summary_payload"]
    assert payload["evidence_file_id"] != str(world["bundle_file_id"]), (
        "the publication points a trader at the bank's mixed bundle — "
        "`15_Agent_Implementation_Plan.md:721` names this exact failure"
    )
    assert payload["evidence_file_id"] == str(world["crop_file_id"])


def test_a_segment_with_no_crop_is_refused_rather_than_degraded(
    world: dict[str, Any],
) -> None:
    """The refusal that keeps the rule above true when the data is imperfect.

    A segment with no crop has only the bundle to offer, so publishing it must fail. The
    alternative — publishing with no evidence at all — would be quieter and would leave a
    publication claiming evidence in its link column and showing none.
    """

    sign_in_admin(world["client"], "publication_accountant")
    case = a_paid_request(world)

    cropless = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO receipt_segments (id, source_file_id, rotation_degrees, "
            "creation_method, status, raw_extraction, created_by_actor_type, record_version) "
            "VALUES (%s, %s, 0, 'manual_external_attachment', 'confirmed_linked', '{}', "
            "'admin_user', 1)",
            (cropless, world["bundle_file_id"]),
        )
        connection.commit()

    link_id = an_evidence_link(world, case, segment_id=cropless)
    # Reviewed for privacy, so the refusal below is unambiguously about the missing crop. Without
    # this the test would pass on the privacy guard and prove nothing about the bundle.
    a_resolved_privacy_review(world, cropless)

    response = preview(world, case["request_id"], primary_evidence_link_id=str(link_id))
    assert response.status_code == 400, response.text
    assert "no crop" in response.text
    assert publications_of(world, case["request_id"]) == []


def test_republishing_an_identical_snapshot_is_refused(world: dict[str, Any]) -> None:
    """`SVC-PUBLICATION-002` and `DB-PUBLICATION-001`, in one act.

    **The test that would pass against a broken hash if it published only once.** Two publications
    of an unchanged result must collide — on `uq_active_publication_per_request` first, and on
    `uq_publication_content_per_request` if the first row were ever superseded without the content
    changing. Either way the second attempt must not produce a version 2 that says the same thing.
    """

    sign_in_admin(world["client"], "publication_accountant")
    case = a_paid_request(world)

    assert preview(world, case["request_id"]).status_code == 200
    first = publish(world, case["request_id"])
    assert first.status_code == 201, first.text

    # Put the request back where a second publish would be permitted, so the refusal comes from
    # the publication table rather than from the status guard. Done as the owner, deliberately:
    # this is the test setting up a state the application itself cannot reach.
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE payment_requests SET status = 'result_ready_for_trader' WHERE id = %s",
            (case["request_id"],),
        )
        connection.commit()

    second = publish(world, case["request_id"])
    assert second.status_code == 409, (
        f"a second publication of an unchanged result returned {second.status_code}. "
        "`04_Database_Schema.md:1154` gives two uniques that each forbid it, and a content hash "
        "that included the clock would defeat both."
    )
    assert "identical" in second.text or "this content" in second.text, second.text
    assert len(publications_of(world, case["request_id"])) == 1


def test_only_one_publication_is_active_per_request(world: dict[str, Any]) -> None:
    """`DB-PUBLICATION-001`. The partial unique, proved by the database refusing the row.

    Written directly against the table with a *different* content hash, so the only constraint
    that can refuse it is `uq_active_publication_per_request`. Through the API the status guard
    would refuse first and this index would never be reached.
    """

    sign_in_admin(world["client"], "publication_accountant")
    case = a_paid_request(world)
    assert preview(world, case["request_id"]).status_code == 200
    assert publish(world, case["request_id"]).status_code == 201

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(
                "INSERT INTO payment_result_publications (payment_request_id, "
                "publication_version, status, summary_payload, content_hash, "
                "published_by_admin_user_id, published_at) "
                "VALUES (%s, 2, 'active', '{}', %s, %s, now())",
                (
                    case["request_id"],
                    "d" * 64,
                    admin_id(world, "publication_accountant"),
                ),
            )
        connection.rollback()

    assert len(publications_of(world, case["request_id"])) == 1


def test_the_runtime_role_cannot_rewrite_what_a_trader_was_shown(
    world: dict[str, Any],
) -> None:
    """§11.9's word "immutable", as a privilege rather than as a description.

    **The claim narrowed when slice 7B landed, and the obligation did not.** This test used to
    assert the runtime could not update a publication *at all*, which was right while nothing
    could supersede one — slice 5 withheld the grant deliberately. `20260903_0034` grants
    `UPDATE (status)` with the correction that needs it, so the honest claim is now the one
    `04_Database_Schema.md:1162` actually makes: a publication may become `superseded`, and
    everything a trader was shown stays unwritable.

    So the attempt below moved from `status` to `summary_payload`. `SET ROLE` first: the owner may
    do anything, and a test that skipped that step would pass against a table with every grant —
    the trap `test_batching_table_privileges.py` was written to record.

    `test_the_runtime_may_update_only_the_publication_status` reads the grant itself, which is what
    catches a widening this behavioural test cannot see.
    """

    sign_in_admin(world["client"], "publication_accountant")
    case = a_paid_request(world)
    assert preview(world, case["request_id"]).status_code == 200
    assert publish(world, case["request_id"]).status_code == 201

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(f'SET ROLE "{world["app_role"]}"')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "UPDATE payment_result_publications SET summary_payload = '{}' "
                "WHERE payment_request_id = %s",
                (case["request_id"],),
            )
        connection.rollback()

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(f'SET ROLE "{world["app_role"]}"')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "UPDATE payment_result_publications SET content_hash = %s "
                "WHERE payment_request_id = %s",
                ("e" * 64, case["request_id"]),
            )
        connection.rollback()


def test_a_request_that_was_not_previewed_cannot_be_published(
    world: dict[str, Any],
) -> None:
    """`06_Workflows_and_State_Machines.md:601` has one arrow into `result_published`.

    Publishing straight from `paid` would skip the step that validates the snapshot, which is the
    only thing standing between a bad crop and a trader.
    """

    sign_in_admin(world["client"], "publication_accountant")
    case = a_paid_request(world)

    response = publish(world, case["request_id"])
    assert response.status_code == 400, response.text
    assert "result_ready_for_trader" in response.text
    assert publications_of(world, case["request_id"]) == []


def test_a_partially_paid_request_cannot_be_previewed(world: dict[str, Any]) -> None:
    """13.2 draws no arrow from `partially_paid` into publication, and none from `failed`.

    Refused rather than quietly allowed. The M9 plan records the open question this creates: a
    trader whose payment failed still needs telling, and the workflow document gives no path.
    """

    sign_in_admin(world["client"], "publication_accountant")
    case = a_paid_request(world, status="partially_paid")

    response = preview(world, case["request_id"])
    assert response.status_code == 400, response.text
    assert "partially_paid" in response.text


def test_evidence_from_another_request_is_refused(world: dict[str, Any]) -> None:
    """§17 `:1185`'s isolation rule, arriving through a field that looks entirely legitimate.

    The link is active and points at a real attempt — just somebody else's. Slice 3 refuses
    evidence pointing at a different *attempt*; here the aggregate is one level up.
    """

    sign_in_admin(world["client"], "publication_accountant")
    mine = a_paid_request(world)
    theirs = a_paid_request(world)
    foreign_link = an_evidence_link(world, theirs)

    response = preview(
        world, mine["request_id"], primary_evidence_link_id=str(foreign_link)
    )
    assert response.status_code == 400, response.text
    assert "different payment request" in response.text


def test_a_replaced_evidence_link_cannot_be_published(world: dict[str, Any]) -> None:
    """Only an active link may be cited. `04_Database_Schema.md:1306` keeps the old ones forever
    precisely so that an *existing* publication still resolves — a new one must cite what is
    current."""

    sign_in_admin(world["client"], "publication_accountant")
    case = a_paid_request(world)
    stale = an_evidence_link(world, case, status="replaced")

    response = preview(world, case["request_id"], primary_evidence_link_id=str(stale))
    assert response.status_code == 400, response.text
    assert "replaced" in response.text


def test_publishing_marks_the_evidence_as_seen_by_the_trader(
    world: dict[str, Any],
) -> None:
    """`confirmed_evidence_links.published_to_trader_at`, which slice 2 created and left unwritten.

    Its migration named this slice as the writer. A column that nothing ever writes is the same
    defect as a mechanism nothing calls, and it stayed one for exactly two slices.
    """

    sign_in_admin(world["client"], "publication_accountant")
    case = a_paid_request(world)
    link_id = an_evidence_link(world, case)
    a_resolved_privacy_review(world, case["segment_id"])

    assert preview(world, case["request_id"]).status_code == 200
    assert (
        publish(
            world, case["request_id"], primary_evidence_link_id=str(link_id)
        ).status_code
        == 201
    )

    published_at = rows(
        world,
        "SELECT published_to_trader_at FROM confirmed_evidence_links WHERE id = %s",
        link_id,
    )[0][0]
    assert published_at is not None, (
        "the evidence a trader was just shown is not marked as published, so nothing distinguishes "
        "it from a link still safe to revoke quietly"
    )

    # `06_Workflows_and_State_Machines.md:1066`: `confirmed_linked --> published: included in
    # active publication`. **Nothing wrote this status until slice 5.** The catalogue approved it,
    # the CHECK admitted it, `RESOLVED_SEGMENT_STATUSES` counted it, and slice 2's own comment
    # promised M9 would write it — a status with no writer, which is the mechanism-with-no-caller
    # defect wearing a different hat.
    segment_status = rows(
        world, "SELECT status FROM receipt_segments WHERE id = %s", case["segment_id"]
    )[0][0]
    assert segment_status == "published", (
        f"the cited segment is still {segment_status}. Document 06 draws "
        "`confirmed_linked --> published: included in active publication`, and without this write "
        "`published` is a status the whole system can describe and nothing can reach."
    )


def test_publishing_records_an_audit_row_and_an_outbox_event(
    world: dict[str, Any],
) -> None:
    """`AUD-PUBLICATION-002`. Both catalogued: `audit_outbox_catalog.yaml:46` and `:77`.

    The audit row carries the hash and **not** the payload: the payload is already stored
    immutably on the row this entry names, and copying a trader's financial detail into a second
    retained place buys nothing.
    """

    sign_in_admin(world["client"], "publication_accountant")
    case = a_paid_request(world)
    assert preview(world, case["request_id"]).status_code == 200
    response = publish(world, case["request_id"], message_to_trader="Your result is ready.")
    assert response.status_code == 201, response.text
    publication_id = response.json()["id"]

    audit = rows(
        world,
        "SELECT action, entity_type, new_values, reason FROM audit_logs "
        "WHERE entity_id = %s AND action = %s",
        publication_id,
        PUBLISH_ACTION,
    )
    assert len(audit) == 1, f"expected one {PUBLISH_ACTION} row, got {audit}"
    assert audit[0][1] == "payment_result_publication"
    assert audit[0][2]["content_hash"] == response.json()["content_hash"]
    assert "beneficiary_name" not in audit[0][2]
    assert audit[0][3] == "Your result is ready."

    events = rows(
        world,
        "SELECT event_type, payload FROM outbox_events WHERE aggregate_id = %s",
        publication_id,
    )
    assert len(events) == 1, f"expected one outbox event, got {events}"
    assert events[0][0] == PUBLISH_EVENT
    assert events[0][1]["publication_version"] == 1


def test_a_manager_may_neither_preview_nor_publish(world: dict[str, Any]) -> None:
    """`20260801_0008:250-251` gives both grants to the accountant alone.

    The manager holds every batch approval permission, so a guard that merely asked for seniority
    would let this through.
    """

    case = a_paid_request(world)
    sign_in_admin(world["client"], "publication_manager")

    assert preview(world, case["request_id"]).status_code == 403
    assert publish(world, case["request_id"]).status_code == 403
    assert publications_of(world, case["request_id"]) == []


def test_publishing_replays_rather_than_publishing_twice(world: dict[str, Any]) -> None:
    """`idempotency: required`, from `command_catalog.yaml`'s publish row.

    A retried POST — the network dropped the response, the accountant pressed again — must return
    the publication that exists rather than colliding on a unique. Both outcomes refuse a second
    row; only one of them tells the caller what happened.
    """

    sign_in_admin(world["client"], "publication_accountant")
    case = a_paid_request(world)
    assert preview(world, case["request_id"]).status_code == 200

    client = world["client"]
    key = str(uuid.uuid4())
    headers = {
        **csrf(client),
        "If-Match": f'"rv-{request_version(world, case["request_id"])}"',
        "Idempotency-Key": key,
    }
    url = f"/api/v1/payment-requests/{case['request_id']}/publications"

    first = client.post(url, json={}, headers=headers)
    assert first.status_code == 201, first.text
    second = client.post(url, json={}, headers=headers)
    assert second.status_code == 201, second.text

    assert second.json()["id"] == first.json()["id"]
    assert len(publications_of(world, case["request_id"])) == 1


def test_evidence_with_no_privacy_review_cannot_be_published(world: dict[str, Any]) -> None:
    """`SEC-PUBLICATION-002`. §19.3: "no unresolved privacy warning exists".

    **The caller M8 built a mechanism for and could not write.** `privacy_verification` says so in
    its own docstring — "There is deliberately no setter... publication is M9's, and a guard on a
    path that does not exist would be untestable". This is that path, and this is the test that
    would have been untestable.
    """

    sign_in_admin(world["client"], "publication_accountant")
    case = a_paid_request(world)
    link_id = an_evidence_link(world, case)

    response = preview(world, case["request_id"], primary_evidence_link_id=str(link_id))
    assert response.status_code == 400, response.text
    assert "privacy review" in response.text
    assert publications_of(world, case["request_id"]) == []


def test_a_review_of_an_earlier_segment_version_does_not_count(
    world: dict[str, Any],
) -> None:
    """§16.5's check is per segment version, and this is what that buys.

    Somebody reviewed version 1; the crop was then re-rendered. A flag would still say "verified"
    and a trader would be shown an image nobody looked at. The comparison says no, with nothing to
    remember to reset — which is the only form of the rule that cannot rot.
    """

    sign_in_admin(world["client"], "publication_accountant")
    case = a_paid_request(world)
    link_id = an_evidence_link(world, case)
    a_resolved_privacy_review(world, case["segment_id"])

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE receipt_segments SET record_version = record_version + 1 WHERE id = %s",
            (case["segment_id"],),
        )
        connection.commit()

    response = preview(world, case["request_id"], primary_evidence_link_id=str(link_id))
    assert response.status_code == 400, response.text
    assert "privacy review" in response.text


def test_a_result_no_person_confirmed_cannot_be_published(world: dict[str, Any]) -> None:
    """`SVC-PUBLICATION-005`. §19.3's first guard: "financial result is human-confirmed".

    The attempt is `paid` and `confirmed_by_admin_user_id` is null — the state a direct write or a
    future automated path could produce. Checked against the column rather than the request's
    status, because the status is *derived* and asking a calculation to vouch for a person is how
    an unconfirmed result would slip through looking correct.
    """

    sign_in_admin(world["client"], "publication_accountant")
    case = a_paid_request(world)
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE payment_attempts SET confirmed_by_admin_user_id = NULL WHERE id = %s",
            (case["attempt_id"],),
        )
        connection.commit()

    response = preview(world, case["request_id"])
    assert response.status_code == 400, response.text
    assert "human-confirmed" in response.text
    assert publications_of(world, case["request_id"]) == []


def test_a_stale_if_match_refuses_the_publication(world: dict[str, Any]) -> None:
    """`SVC-PUBLICATION-005`. §19.3's eighth guard: "expected version is valid".

    The accountant read the request at one version and something else moved it. Publishing anyway
    would put a snapshot of a request that has since changed in front of a trader, immutably.
    """

    sign_in_admin(world["client"], "publication_accountant")
    case = a_paid_request(world)
    assert preview(world, case["request_id"]).status_code == 200

    # Read the version, then let something else move the request — which is the situation the
    # header exists for. The first draft used `version - 1` and got 0, which is falsy, so the
    # helper's `or` quietly substituted the current version and the test passed against nothing.
    stale = request_version(world, case["request_id"])
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE payment_requests SET record_version = record_version + 1 WHERE id = %s",
            (case["request_id"],),
        )
        connection.commit()

    response = publish(world, case["request_id"], version=stale)
    assert response.status_code == 412, response.text
    assert publications_of(world, case["request_id"]) == []


def test_publishing_without_an_if_match_is_refused(world: dict[str, Any]) -> None:
    sign_in_admin(world["client"], "publication_accountant")
    case = a_paid_request(world)
    assert preview(world, case["request_id"]).status_code == 200

    client = world["client"]
    response = client.post(
        f"/api/v1/payment-requests/{case['request_id']}/publications",
        json={},
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 428, response.text
    assert publications_of(world, case["request_id"]) == []


def test_publishing_without_an_idempotency_key_is_refused(world: dict[str, Any]) -> None:
    sign_in_admin(world["client"], "publication_accountant")
    case = a_paid_request(world)
    assert preview(world, case["request_id"]).status_code == 200

    client = world["client"]
    response = client.post(
        f"/api/v1/payment-requests/{case['request_id']}/publications",
        json={},
        headers=csrf(client),
    )
    assert response.status_code == 428, response.text
    assert publications_of(world, case["request_id"]) == []
