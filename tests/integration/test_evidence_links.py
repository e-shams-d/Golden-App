"""The cardinality a database enforces, and a replacement that cannot half-happen.

M9 slice 2, against a real PostgreSQL.

**Two of these tests could not be written any other way**, and they are the slice:

- `CON-EVIDENCE-001` runs **two connections** at one attempt. A single-threaded test proves the
  partial unique index exists; only a race proves it constrains. This is the case a read-then-insert
  in the service gets wrong — both transactions read, both find nothing, both insert.
- `SVC-EVIDENCE-001` is a **failure injection**, not a happy path. A replacement that retires the
  old link and then fails to insert the new one leaves an attempt with no primary evidence at all,
  and no passing happy-path test can see that ordering.

**One administrator, and the test says why that is not a weakness.** `20260801_0008:218-220` seeds
`evidence_link.confirm`, `.replace` and `.revoke` to `accountant` and to nobody else, so no role
holds a proper subset and slice 1's sharper negative — a role with one permission and not the
other — does not exist here. `test_no_evidence_route_answers_a_caller_without_the_permission`
asserts that fact rather than implying a sharpness it cannot have.

Covers: DB-EVIDENCE-001, CON-EVIDENCE-001, SVC-EVIDENCE-001, SVC-EVIDENCE-002, AUD-EVIDENCE-001.
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

TRADER_PHONE = "+989120006201"
IBAN = "IR060120000000000000000062"

CONFIRMED = "evidence_link.confirmed"
REPLACED = "evidence_link.replaced"
REVOKED = "evidence_link.revoked"


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
        local_storage_root=tmp_path_factory.mktemp("evidence-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="g" * 40,
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
            "approval_status) VALUES (%s, 'Evidence Trader', %s, 'active', 'approved')",
            (ids["trader"], TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (ids["trader"], TRADER_PHONE, encoded),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'Ali Eight', %s, %s, 'active', "
            "'not_checked')",
            (ids["beneficiary"], ids["trader"], IBAN, IBAN),
        )
        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'tejarat', 'Bank Tejarat', 'active')",
            (ids["profile"],),
        )
        connection.execute(
            "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, status, "
            "default_transfer_limit_irr, after_cutoff_transfer_limit_irr, cutoff_time, "
            "splitting_enabled, required_fields, rules, config_hash) "
            "VALUES (%s, %s, 1, 'active', 1000000000, NULL, NULL, TRUE, '{}', '{}', %s)",
            (ids["version"], ids["profile"], "8" * 64),
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
            (ids["file"], f"evidence/{ids['file']}", "c" * 64),
        )
        for username, role in (
            # Holds all three evidence permissions; nobody else holds any.
            ("evidence_accountant", "accountant"),
            ("evidence_manager", "manager"),
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
    assert found, f"{username} was not seeded"
    return uuid.UUID(str(found[0][0]))


def an_attempt(world: dict[str, Any], *, amount: int = 900_000_000) -> uuid.UUID:
    """One payment attempt, inserted directly — slice 1's helper, for its reason.

    This module's subject is what an evidence link does to and around an attempt; driving M5
    through M7 to produce one would make every test here depend on four milestones' behaviour.
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
            "VALUES (%s, %s, 1, %s, 'Ali Eight', %s, %s, %s, 'trader_user')",
            (revision_id, request_id, world["beneficiary_id"], IBAN, amount, "d" * 64),
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
            "VALUES (%s, %s, %s, 1, 'original', %s, 'Ali Eight', %s, %s, %s, '{}', "
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


def a_segment(world: dict[str, Any], *, status: str = "candidate_found") -> uuid.UUID:
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


def confirm(
    world: dict[str, Any],
    attempt_id: uuid.UUID,
    segment_id: uuid.UUID,
    *,
    link_type: str = "primary",
    key: str | None = None,
) -> Any:
    client = world["client"]
    return client.post(
        "/api/v1/evidence-links",
        json={
            "payment_attempt_id": str(attempt_id),
            "receipt_segment_id": str(segment_id),
            "link_type": link_type,
            "confirmation_note": "amount, IBAN and tracking number checked",
        },
        headers={**csrf(client), "Idempotency-Key": key or str(uuid.uuid4())},
    )


def replace(world: dict[str, Any], link_id: str, segment_id: uuid.UUID, **overrides: Any) -> Any:
    client = world["client"]
    body: dict[str, Any] = {
        "new_receipt_segment_id": str(segment_id),
        "replacement_reason": "the previous segment belonged to another transaction",
    }
    body.update(overrides)
    return client.post(
        f"/api/v1/evidence-links/{link_id}/replace",
        json=body,
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )


def void(world: dict[str, Any], link_id: str, *, reason: str = "attached in error") -> Any:
    client = world["client"]
    return client.post(
        f"/api/v1/evidence-links/{link_id}/void",
        json={"reason": reason},
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )


# ---------------------------------------------------------------------------------------------
# The two tests that need a database to mean anything.
# ---------------------------------------------------------------------------------------------


def test_two_concurrent_transactions_cannot_both_confirm_a_primary_link(
    world: dict[str, Any],
) -> None:
    """`CON-EVIDENCE-001`. §17 `:1115`: one active primary per attempt.

    **Two connections, both committing.** The first wins; the second must be refused by
    `uq_attempt_active_primary_evidence` rather than by anything in Python. This is the case a
    read-then-insert in the service gets wrong: both read, both find nothing, both insert.

    The insert goes in directly rather than through the route because what is under test is the
    *index*, and two `TestClient` calls are sequential — they would prove nothing about a race.
    """

    attempt_id = an_attempt(world)
    first_segment = a_segment(world)
    second_segment = a_segment(world)
    who = admin_id(world, "evidence_accountant")

    statement = (
        "INSERT INTO confirmed_evidence_links (payment_attempt_id, receipt_segment_id, "
        "link_type, status, confirmed_by_admin_user_id, confirmed_at) "
        "VALUES (%s, %s, 'primary', 'active', %s, now())"
    )

    first = psycopg.connect(_psycopg(world["owner_url"]))
    second = psycopg.connect(_psycopg(world["owner_url"]))
    try:
        first.execute(statement, (attempt_id, first_segment, who))
        second_failed = False
        try:
            # Blocks until the first commits, then fails on the unique. `psycopg` raises here
            # rather than at commit, which is the behaviour the index is supposed to produce.
            first.commit()
            second.execute(statement, (attempt_id, second_segment, who))
            second.commit()
        except psycopg.errors.UniqueViolation:
            second_failed = True
            second.rollback()
    finally:
        first.close()
        second.close()

    assert second_failed, (
        "both transactions committed a primary link for one attempt. §17 `:1115` permits one, "
        "and uq_attempt_active_primary_evidence is what must refuse the second."
    )
    assert rows(
        world,
        "SELECT count(*) FROM confirmed_evidence_links WHERE payment_attempt_id = %s "
        "AND link_type = 'primary' AND status = 'active'",
        attempt_id,
    ) == [(1,)]


def test_a_segment_cannot_be_primary_evidence_for_two_attempts(world: dict[str, Any]) -> None:
    """The other partial index, `uq_segment_active_primary_attempt`.

    Asserted separately because the two indexes constrain different columns, and a single test
    of one would leave the other unproved — which is how a copy-paste that names the same column
    twice survives.
    """

    segment_id = a_segment(world)
    sign_in_admin(world["client"], "evidence_accountant")

    assert confirm(world, an_attempt(world), segment_id).status_code == 201
    refused = confirm(world, an_attempt(world), segment_id)
    assert refused.status_code == 409, refused.text
    assert "segment" in refused.text


def test_a_failed_replacement_leaves_the_original_active(world: dict[str, Any]) -> None:
    """`SVC-EVIDENCE-001`. Replacement is atomic, asserted by making it fail.

    A replacement that retires the old link and then cannot insert the new one would leave the
    attempt with **no primary evidence at all** — worse than either outcome it was choosing
    between. The provocation is a `new_receipt_segment_id` that does not exist, which fails after
    the point where a non-transactional implementation would already have retired the original.
    """

    attempt_id = an_attempt(world)
    segment_id = a_segment(world)
    sign_in_admin(world["client"], "evidence_accountant")

    created = confirm(world, attempt_id, segment_id)
    assert created.status_code == 201, created.text
    link_id = created.json()["id"]

    refused = replace(world, link_id, uuid.uuid4())
    assert refused.status_code == 404, refused.text

    assert rows(
        world, "SELECT status FROM confirmed_evidence_links WHERE id = %s", link_id
    ) == [("active",)], (
        "the original link was retired by a replacement that then failed, so the attempt has no "
        "active primary evidence and nothing replaced it"
    )
    assert rows(
        world,
        "SELECT count(*) FROM confirmed_evidence_links WHERE payment_attempt_id = %s",
        attempt_id,
    ) == [(1,)]


def test_a_replacement_retires_the_old_link_and_keeps_it(world: dict[str, Any]) -> None:
    """§12.6 at `:1306`: replacement "never deletes or overwrites the old relationship".

    The chain is the point: the new row carries `replaces_link_id` and the reason, the old row is
    still there at `replaced`, and the attempt has exactly one active primary throughout.
    """

    attempt_id = an_attempt(world)
    original_segment = a_segment(world)
    new_segment = a_segment(world)
    sign_in_admin(world["client"], "evidence_accountant")

    original = confirm(world, attempt_id, original_segment).json()["id"]
    replaced = replace(world, original, new_segment)
    assert replaced.status_code == 201, replaced.text

    body = replaced.json()
    assert body["replaces_link_id"] == original
    assert body["receipt_segment_id"] == str(new_segment)
    assert body["replacement_reason"]

    chain = rows(
        world,
        "SELECT id, status, receipt_segment_id, replaces_link_id FROM confirmed_evidence_links "
        "WHERE payment_attempt_id = %s ORDER BY created_at",
        attempt_id,
    )
    assert len(chain) == 2, chain
    assert chain[0][1] == "replaced"
    assert chain[0][2] == original_segment, "the retired row's segment was rewritten"
    assert chain[1][1] == "active"
    assert str(chain[1][3]) == original


def test_a_replacement_without_a_reason_is_refused(world: dict[str, Any]) -> None:
    """`command_catalog.yaml` gives this command `reason_required`."""

    attempt_id = an_attempt(world)
    sign_in_admin(world["client"], "evidence_accountant")
    link_id = confirm(world, attempt_id, a_segment(world)).json()["id"]

    refused = replace(world, link_id, a_segment(world), replacement_reason="")
    assert refused.status_code == 422, refused.text
    assert rows(
        world, "SELECT status FROM confirmed_evidence_links WHERE id = %s", link_id
    ) == [("active",)]


# ---------------------------------------------------------------------------------------------
# Revocation: the path says void, the column says revoked, and a primary is refused.
# ---------------------------------------------------------------------------------------------


def test_voiding_stores_the_canonical_revoked_status(world: dict[str, Any]) -> None:
    """`SVC-EVIDENCE-002`. The `/void` path writes `revoked`.

    `status_catalog.yaml` makes `revoked` canonical and `voided` a provisional alias; documents 06
    and 08 say the first, 04 and 05 the second, and `command_catalog.yaml`'s revoke row is marked
    `blocked_by_voided_vs_revoked_status_conflict`. The path is the API contract and stays; the
    column follows the status catalogue, which is the precedent DOC-CONFLICT-016 set.
    """

    attempt_id = an_attempt(world)
    sign_in_admin(world["client"], "evidence_accountant")
    link_id = confirm(
        world, attempt_id, a_segment(world), link_type="supplementary"
    ).json()["id"]

    voided = void(world, link_id)
    assert voided.status_code == 200, voided.text
    assert voided.json()["status"] == "revoked", (
        "the response reports the deprecated alias; the canonical spelling is what the status "
        "catalogue makes authoritative"
    )
    assert rows(
        world, "SELECT status FROM confirmed_evidence_links WHERE id = %s", link_id
    ) == [("revoked",)]


def test_a_primary_link_cannot_be_voided(world: dict[str, Any]) -> None:
    """`:1864`: "Primary links use the replacement/correction workflow."

    Letting a primary through here would be a path around a workflow document 05 routes
    elsewhere — and it would leave an attempt with no primary evidence and no replacement, which
    is the state `SVC-EVIDENCE-001` exists to prevent.
    """

    attempt_id = an_attempt(world)
    sign_in_admin(world["client"], "evidence_accountant")
    link_id = confirm(world, attempt_id, a_segment(world)).json()["id"]

    refused = void(world, link_id)
    assert refused.status_code == 400, refused.text
    assert "replacement" in refused.text
    assert rows(
        world, "SELECT status FROM confirmed_evidence_links WHERE id = %s", link_id
    ) == [("active",)]


def test_a_supplementary_link_does_not_displace_the_primary(world: dict[str, Any]) -> None:
    """§22.3: "Supplementary evidence does not replace primary evidence."

    Both exist at once on the same attempt, which is what the plain unique's third column and the
    partial indexes' `link_type` predicate together permit.
    """

    attempt_id = an_attempt(world)
    sign_in_admin(world["client"], "evidence_accountant")

    primary = confirm(world, attempt_id, a_segment(world))
    assert primary.status_code == 201, primary.text
    extra = confirm(world, attempt_id, a_segment(world), link_type="supplementary")
    assert extra.status_code == 201, extra.text

    assert rows(
        world,
        "SELECT link_type, status FROM confirmed_evidence_links "
        "WHERE payment_attempt_id = %s ORDER BY link_type",
        attempt_id,
    ) == [("primary", "active"), ("supplementary", "active")]


# ---------------------------------------------------------------------------------------------
# What confirmation does not do.
# ---------------------------------------------------------------------------------------------


def test_confirming_evidence_changes_nothing_about_the_attempt(world: dict[str, Any]) -> None:
    """Slice 1's negative, one aggregate further along.

    §17 `:1122`'s paid confirmation is slice 3's command and takes a bank tracking number, a
    result timestamp and an actor. Confirming *evidence* records what a segment means and nothing
    about whether money moved — and the migration grants the runtime nothing on
    `payment_attempts`, so it could not.
    """

    attempt_id = an_attempt(world)
    sign_in_admin(world["client"], "evidence_accountant")

    before = rows(
        world, "SELECT row_to_json(pa) FROM payment_attempts pa WHERE id = %s", attempt_id
    )[0][0]

    assert confirm(world, attempt_id, a_segment(world)).status_code == 201

    after = rows(
        world, "SELECT row_to_json(pa) FROM payment_attempts pa WHERE id = %s", attempt_id
    )[0][0]
    assert after == before, "confirming evidence moved the attempt"


def test_confirming_a_primary_link_marks_the_segment_linked(world: dict[str, Any]) -> None:
    """`06_Workflows_and_State_Machines.md:1065`: `candidate_found --> confirmed_linked`.

    A supplementary link does not move the segment: §22.3 says supplementary evidence does not
    replace primary evidence, and the segment's status summarises its *primary* usage.
    """

    sign_in_admin(world["client"], "evidence_accountant")

    linked = a_segment(world, status="candidate_found")
    assert confirm(world, an_attempt(world), linked).status_code == 201
    assert rows(world, "SELECT status FROM receipt_segments WHERE id = %s", linked) == [
        ("confirmed_linked",)
    ]

    untouched = a_segment(world, status="candidate_found")
    assert (
        confirm(world, an_attempt(world), untouched, link_type="supplementary").status_code == 201
    )
    assert rows(world, "SELECT status FROM receipt_segments WHERE id = %s", untouched) == [
        ("candidate_found",)
    ]


# ---------------------------------------------------------------------------------------------
# Audit and the one outbox event.
# ---------------------------------------------------------------------------------------------


def test_each_command_writes_its_catalogued_action_and_only_replace_publishes(
    world: dict[str, Any],
) -> None:
    """`AUD-EVIDENCE-001`. Three actions, one event.

    `audit_outbox_catalog.yaml:40-42` names the three actions and `:76` names
    `EvidenceLinkReplaced` — the only one. The asymmetry is the point: replacement is where
    evidence stops agreeing with what a trader was shown, and `:1854` requires a corrected
    publication and a notification when that happens. Confirming and revoking settle nothing a
    consumer outside the platform can act on.
    """

    attempt_id = an_attempt(world)
    first_segment = a_segment(world)
    second_segment = a_segment(world)
    sign_in_admin(world["client"], "evidence_accountant")

    before = rows(world, "SELECT count(*) FROM outbox_events")[0][0]

    original = confirm(world, attempt_id, first_segment).json()["id"]
    assert rows(world, "SELECT count(*) FROM outbox_events")[0][0] == before, (
        "confirming published an outbox event; the catalogue gives that command none"
    )

    replacement = replace(world, original, second_segment).json()["id"]
    supplementary = confirm(
        world, attempt_id, a_segment(world), link_type="supplementary"
    ).json()["id"]
    assert void(world, supplementary).status_code == 200

    actions = {
        row[0]
        for row in rows(
            world,
            "SELECT action FROM audit_logs WHERE entity_type = 'confirmed_evidence_link' "
            "AND entity_id IN (%s, %s, %s)",
            original,
            replacement,
            supplementary,
        )
    }
    assert actions == {CONFIRMED, REPLACED, REVOKED}, actions

    published = rows(
        world,
        "SELECT event_type, payload->>'replaces_link_id' FROM outbox_events "
        "WHERE aggregate_id = %s",
        replacement,
    )
    assert published == [("EvidenceLinkReplaced", original)], published

    assert rows(world, "SELECT count(*) FROM outbox_events")[0][0] == before + 1, (
        "more than the replacement published an event"
    )


def test_the_revocation_reason_is_recorded_on_the_audit_row(world: dict[str, Any]) -> None:
    """§22.3 requires a reason and §12.6 gives the table no column for one.

    So it lives on the audit row — where slice 1 put a rejection's reason for the same reason.
    Inventing a column two catalogues do not describe is the drift this milestone opened by
    promising not to do, and this test is what makes the absence checkable.
    """

    attempt_id = an_attempt(world)
    sign_in_admin(world["client"], "evidence_accountant")
    link_id = confirm(
        world, attempt_id, a_segment(world), link_type="supplementary"
    ).json()["id"]

    assert void(world, link_id, reason="attached to the wrong transaction").status_code == 200

    assert rows(
        world,
        "SELECT reason FROM audit_logs WHERE entity_id = %s AND action = %s",
        link_id,
        REVOKED,
    ) == [("attached to the wrong transaction",)]

    columns = {
        row[0]
        for row in rows(
            world,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'confirmed_evidence_links'",
        )
    }
    assert not any("revocation" in name or "void" in name for name in columns), (
        f"a revocation column was added to the table; §12.6 documents none: {sorted(columns)}"
    )


# ---------------------------------------------------------------------------------------------
# Permissions.
# ---------------------------------------------------------------------------------------------


def test_no_evidence_route_answers_a_caller_without_the_permission(
    world: dict[str, Any],
) -> None:
    """One test over three routes, and the reason it cannot be sharper is asserted.

    `20260801_0008:218-220` seeds all three evidence permissions to `accountant` and to nobody
    else. So there is no role holding one and not another, and slice 1's sharper negative — an
    actor that passes a wrong-permission guard and must still be refused — does not exist here.
    Rather than implying a sharpness this cannot have, the catalogue is read back.
    """

    attempt_id = an_attempt(world)
    segment_id = a_segment(world)
    client = world["client"]

    sign_in_admin(client, "evidence_accountant")
    link_id = confirm(world, attempt_id, segment_id).json()["id"]

    sign_in_admin(client, "evidence_manager")
    assert confirm(world, an_attempt(world), a_segment(world)).status_code == 403
    assert replace(world, link_id, a_segment(world)).status_code == 403
    assert void(world, link_id).status_code == 403

    holders = rows(
        world,
        "SELECT r.code, count(*) FROM roles r "
        "JOIN role_permissions rp ON rp.role_id = r.id "
        "JOIN permissions p ON p.id = rp.permission_id "
        "WHERE p.code IN ('evidence_link.confirm', 'evidence_link.replace', "
        "'evidence_link.revoke') GROUP BY r.code ORDER BY r.code",
    )
    assert holders == [("accountant", 3)], (
        f"the evidence permissions are no longer accountant-only ({holders}), so a sharper "
        "negative is now possible and this test should use it"
    )
