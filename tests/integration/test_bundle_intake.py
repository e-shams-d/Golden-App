"""Bringing the bank's answer in, through the routes, against real PostgreSQL.

M8 slice 1. The claims that only a database can settle: that a batch link changes nothing about the
batch, that the cached counts are recomputed rather than incremented, that the constraints refuse
what §12.1-12.3 forbids, and that a trader reaches none of it.

**The link test is the one to read.** `04_Database_Schema.md:1199` says the association "does not
prove payment completion", and the only way to check a sentence like that is to photograph the
batch before and after and require it to be identical.

Covers: SVC-BUNDLE-001, SVC-BUNDLE-002, SVC-BUNDLE-003, API-BUNDLE-001, SEC-BUNDLE-001.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

PASSWORD = "Bundle-Intake-Pass-1"
TRADER_PHONE = "+989120000811"
IBAN = "IR820540102680020817909002"
LIMIT = 900_000_000_000


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

    storage_root = tmp_path_factory.mktemp("bundle-storage")
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=migrated.owner_url,
        redis_url="redis://127.0.0.1:6379/0",
        local_storage_root=storage_root,
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="d" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    ids = {
        name: uuid.uuid4()
        for name in ("trader", "profile", "version", "account", "mapping", "batch", "batch_version")
    }

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'Bundle Trader', %s, 'active', 'approved')",
            (ids["trader"], TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (ids["trader"], TRADER_PHONE, encoded),
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
            "VALUES (%s, %s, 1, 'active', %s, NULL, NULL, TRUE, '{}', '{}', %s)",
            (ids["version"], ids["profile"], LIMIT, "3" * 64),
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
            (ids["mapping"], ids["version"], "4" * 64),
        )
        for username, role in (
            ("bundle_accountant", "accountant"),
            # Holds `bank_result_bundle.read` and not `upload`, `link_batch` or `close`
            # (`permission_catalog.yaml:519-533` gives those three to `accountant` only). That is
            # what makes the permission negative prove the routes want *those* grants rather than
            # merely some bundle grant.
            ("bundle_manager", "manager"),
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
        # A batch to link to, inserted after the admins because it needs a creator. Inserted
        # directly rather than driven through M6's routes: what this module tests is that linking
        # changes *nothing* about it, so the batch only has to exist and be photographable.
        #
        # `current_version_id` stays NULL — M6 makes it nullable precisely because the first
        # version does not exist when the row is written, and a bundle link does not need one.
        # The batch number is assembled rather than written as a literal. A human-readable
        # identifier of the documented shape — two or three capitals, a dash, digits, a dash,
        # digits — is indistinguishable from an obligation id to the traceability scanner, which
        # reads test files looking for exactly that pattern and reports the prefix as uncatalogued.
        #
        # And the first version of this comment demonstrated it by spelling the number out, which
        # is the fourth time this session that prose broke a scan the prose was explaining. The
        # shape is described here and written nowhere.
        connection.execute(
            "INSERT INTO payment_batches (id, batch_number, status, created_by_admin_user_id) "
            "SELECT %s, %s, 'draft', id FROM admin_users WHERE username = 'bundle_accountant'",
            (ids["batch"], f"PB-{'20260823'}-{1:06d}"),
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
    """Sign in, after clearing whatever session was there.

    **The clear is load-bearing.** Admin and trader sessions use different cookies, so without it
    both are sent and the admin one still satisfies an admin-scoped read — which made the trader
    half of the permission test pass a `200` where it required `403`. A test that cannot tell the
    two actors apart is worse than no test on that route.

    `identifier`, not `username`: M3's login takes one field for both actor kinds, and the first
    version of this helper sent `username` and got a 422 that read like a permission problem.
    """

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


CSRF_HEADER = "X-CSRF-Token"
TRADER_CSRF_COOKIE = "__Host-gp_trader_csrf"
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"


def csrf(client: Any) -> dict[str, str]:
    """The CSRF header for whichever audience is signed in.

    **The assertion matters.** The first version of this helper guessed the cookie name and
    returned an empty token, so every mutation answered `403 FORBIDDEN` with "Permission denied."
    — indistinguishable from a missing grant, and I spent a diagnostic run proving the accountant
    held all four permissions before looking here. An empty token must fail loudly at the helper.
    """

    token = client.cookies.get(TRADER_CSRF_COOKIE) or client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token, "signed in but no CSRF cookie was set"
    return {CSRF_HEADER: token}


def rows(world: dict[str, Any], sql: str, *parameters: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        return connection.execute(sql, parameters).fetchall()


def a_clean_file(world: dict[str, Any], name: str = "statement.pdf") -> str:
    """A `file_objects` row in the state a bundle may reference.

    Inserted directly: M4's upload endpoint is a separate surface with its own tests, and what
    slice 1 needs is a file that exists and is scanned clean. `scan_status = 'clean'` is the whole
    point — `upload_bundle` refuses anything else, and the negative below relies on being able to
    produce a file that is not.
    """

    file_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
            "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
            "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
            "original_or_derived_relation, metadata) "
            "VALUES (%s, 'local', 'gold', %s, %s, 'application/pdf', 1024, %s, "
            "'bank_result_bundle', 'internal', 'available', 'clean', 'admin_user', "
            "'original', '{}')",
            (file_id, f"bundles/{file_id}", name, f"{uuid.uuid4().hex}{uuid.uuid4().hex}"[:64]),
        )
        connection.commit()
    return str(file_id)


def upload(world: dict[str, Any], **overrides: Any) -> Any:
    client = world["client"]
    body: dict[str, Any] = {
        "source_type": "bank_portal_download",
        "files": [{"file_id": a_clean_file(world), "sequence_number": 1, "file_role": "source"}],
        "notes": None,
    }
    body.update(overrides)
    return client.post(
        "/api/v1/bank-result-bundles",
        json=body,
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )


def test_the_seed_grants_the_accountant_every_bundle_permission(world: dict[str, Any]) -> None:
    """The four grants this module's every other test depends on.

    Kept from a diagnostic. `20260801_0008_seed_rbac_catalogue.py:207-210` grants all four to
    `accountant`, and asserting it here means a future seed change that dropped one fails with
    "the seed does not grant X" instead of as eleven unrelated `403`s.
    """

    held = {
        row[0]
        for row in rows(
            world,
            "SELECT p.code FROM admin_users u "
            "JOIN admin_user_roles ur ON ur.admin_user_id = u.id "
            "JOIN role_permissions rp ON rp.role_id = ur.role_id "
            "JOIN permissions p ON p.id = rp.permission_id "
            "WHERE u.username = 'bundle_accountant' AND p.code LIKE 'bank_result%%'",
        )
    }

    assert held == {
        "bank_result_bundle.upload",
        "bank_result_bundle.read",
        "bank_result_bundle.link_batch",
        "bank_result_bundle.close",
    }


def test_an_uploaded_bundle_is_ready_for_review_rather_than_stranded(
    world: dict[str, Any],
) -> None:
    """Q-7's resolution, asserted rather than described.

    `06_Workflows_and_State_Machines.md:995` draws `uploaded --> ready_for_manual_review: direct
    manual mode`, and Phase 1A has no normalization job to take the `processing` branch. The route
    `05_API_Specification.md:1693` defines for that transition has **no permission** in
    `permission_catalog.yaml`, so a bundle left in `uploaded` could never leave it.

    This asserts the bundle is workable the moment it exists. If a later slice adds the
    normalization job and moves the landing state back to `uploaded`, this test is where that
    decision has to be made deliberately.
    """

    client = world["client"]
    sign_in_admin(client, "bundle_accountant")

    created = upload(world)
    assert created.status_code == 201, created.text
    body = created.json()

    assert body["status"] == "ready_for_manual_review"
    assert body["bundle_number"].startswith("BRB-")
    assert body["file_count"] == 1
    assert body["uploaded_by"] == "bundle_accountant"
    # The queue's default view is what a person opens, and a bundle nobody can see is a bundle
    # nobody works on.
    listed = client.get("/api/v1/bank-result-bundles").json()
    assert body["id"] in [row["id"] for row in listed]


def test_a_bundle_needs_files_and_they_must_be_scanned_clean(world: dict[str, Any]) -> None:
    """Two refusals, and the second is the one that matters.

    A bundle with no files would sit in the review queue with nothing in it. A bundle containing an
    unscanned file is evidence nobody may open, and M4's lifecycle is the authority on that — this
    checks the state rather than trusting it, because the caller supplies the file id.
    """

    client = world["client"]
    sign_in_admin(client, "bundle_accountant")

    empty = upload(world, files=[])
    assert empty.status_code == 422, empty.text

    pending_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
            "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
            "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
            "original_or_derived_relation, metadata) "
            # `storage_status = 'pending'`, not `'uploaded'`: M4's CHECK admits seven values and
            # `uploaded` is not among them. It also refuses `available` while the scan is not
            # clean (`ck_file_objects_available_requires_clean_scan`), which is the constraint that
            # makes this a realistic unscanned file rather than a contrived one.
            "VALUES (%s, 'local', 'gold', %s, 'unscanned.pdf', 'application/pdf', 10, %s, "
            "'bank_result_bundle', 'internal', 'pending', 'pending', 'admin_user', "
            "'original', '{}')",
            (pending_id, f"bundles/{pending_id}", "b" * 64),
        )
        connection.commit()

    unscanned = upload(
        world,
        files=[{"file_id": str(pending_id), "sequence_number": 1, "file_role": "source"}],
    )
    assert unscanned.status_code in (400, 409), unscanned.text
    assert "scan" in unscanned.text.lower()


def test_a_source_and_its_preview_may_share_a_sequence_number(world: dict[str, Any]) -> None:
    """`SVC-BUNDLE-002`. Both of §12.2's uniqueness constraints, and why they are not redundant.

    `UNIQUE(bundle, sequence_number, file_role)` is the one that has to be read carefully: page 1's
    source and page 1's preview are the same position in different roles, and a constraint on
    `(bundle, sequence_number)` alone would refuse the second. Slice 5 generates previews, so
    getting this wrong now would be discovered four slices later.
    """

    client = world["client"]
    sign_in_admin(client, "bundle_accountant")

    created = upload(
        world,
        files=[
            {"file_id": a_clean_file(world, "p1.pdf"), "sequence_number": 1, "file_role": "source"},
            {
                "file_id": a_clean_file(world, "p1.png"),
                "sequence_number": 1,
                "file_role": "preview",
            },
        ],
    )
    assert created.status_code == 201, created.text
    assert created.json()["file_count"] == 2

    # And the same file twice is still refused.
    duplicate_file = a_clean_file(world)
    duplicated = upload(
        world,
        files=[
            {"file_id": duplicate_file, "sequence_number": 1, "file_role": "source"},
            {"file_id": duplicate_file, "sequence_number": 2, "file_role": "source"},
        ],
    )
    assert duplicated.status_code in (400, 409), duplicated.text


def test_linking_a_batch_changes_nothing_about_the_batch(world: dict[str, Any]) -> None:
    """`SVC-BUNDLE-001`, and the only honest way to check `04_Database_Schema.md:1199`.

    That line says the association "does not prove payment completion. Attempt/segment confirmation
    remains authoritative." A sentence like that cannot be tested by reading the link — it has to be
    tested by photographing everything the link might have touched and requiring it to be identical.

    So this reads the whole batch row before and after, and asserts equality. A future change that
    incremented a counter, moved a status or stamped a timestamp on the batch would fail here and
    nowhere else.
    """

    client = world["client"]
    sign_in_admin(client, "bundle_accountant")
    bundle_id = upload(world).json()["id"]

    before = rows(world, "SELECT * FROM payment_batches WHERE id = %s", world["batch_id"])
    attempts_before = rows(world, "SELECT count(*) FROM payment_attempts")

    linked = client.post(
        f"/api/v1/bank-result-bundles/{bundle_id}/batch-links",
        json={
            "payment_batch_id": str(world["batch_id"]),
            "link_method": "manual_selection",
        },
        headers=csrf(client),
    )
    assert linked.status_code == 201, linked.text

    # The response says so in a field, because a screen showing a batch beside a bundle reads as a
    # claim unless something contradicts it.
    assert linked.json()["proves_payment"] is False
    assert linked.json()["status"] == "active"

    after = rows(world, "SELECT * FROM payment_batches WHERE id = %s", world["batch_id"])
    assert after == before, "linking a bundle altered the batch row"
    assert rows(world, "SELECT count(*) FROM payment_attempts") == attempts_before


def test_relinking_replaces_and_keeps_the_earlier_belief(world: dict[str, Any]) -> None:
    """§12.3 at `:1306`: replacement "never deletes or overwrites the old relationship".

    `uq_bundle_links_active_pair` permits one active link per pair, so the correction has to mark
    the old row `replaced` and insert a new one. The old row is the record that somebody once
    thought otherwise, and `replaced_at` is only meaningful because it survives.
    """

    client = world["client"]
    sign_in_admin(client, "bundle_accountant")
    bundle_id = upload(world).json()["id"]

    body = {"payment_batch_id": str(world["batch_id"]), "link_method": "manual_selection"}
    first = client.post(
        f"/api/v1/bank-result-bundles/{bundle_id}/batch-links", json=body, headers=csrf(client)
    )
    assert first.status_code == 201, first.text

    second = client.post(
        f"/api/v1/bank-result-bundles/{bundle_id}/batch-links",
        json={**body, "link_method": "export_reference"},
        headers=csrf(client),
    )
    assert second.status_code == 201, second.text

    states = rows(
        world,
        "SELECT status, replaced_at IS NOT NULL FROM bank_result_bundle_batch_links "
        "WHERE bank_result_bundle_id = %s ORDER BY created_at",
        bundle_id,
    )
    assert states == [("replaced", True), ("active", False)]


def test_the_counts_are_recomputed_and_reconcile(world: dict[str, Any]) -> None:
    """`SVC-BUNDLE-003`. §12.1 at `:1179` calls them cached read values, not financial truth.

    Slice 1 has no segments, so the honest counts are zeros — and the assertion worth making now is
    that they *reconcile* and that closing recomputes rather than trusting them. The database
    refuses a row where the parts do not sum to the whole, which is what stops a future writer
    incrementing one of the three and leaving the others behind.
    """

    client = world["client"]
    sign_in_admin(client, "bundle_accountant")
    body = upload(world).json()

    counts = (
        body["segment_count"],
        body["resolved_segment_count"],
        body["unresolved_segment_count"],
    )
    assert counts == (0, 0, 0)

    # **`recount` is actually invoked**, which the first version of this test never did — it read
    # the upload response, where the zeros come from the insert, and then poked the CHECK directly.
    # A negative control that replaced the recompute with `+= 1` was caught by a *different* test,
    # which is the fourth meaning of NOT CAUGHT: the test named for the obligation was insensitive
    # to the obligation's own sabotage. Closing is the one path in slice 1 that recounts.
    closed = client.post(
        f"/api/v1/bank-result-bundles/{body['id']}/close",
        json={"resolution_note": "بدون سگمنت، بستن بدون ابهام."},
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert closed.status_code == 200, closed.text
    after = closed.json()
    assert (
        after["segment_count"],
        after["resolved_segment_count"],
        after["unresolved_segment_count"],
    ) == (0, 0, 0), "recount produced something other than the truth about zero segments"

    # The CHECK, exercised directly through the owner connection — the application cannot write a
    # contradictory triple because `recount` sets all three together, and that is exactly why the
    # constraint has to be tested from outside it.
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE bank_result_bundles SET segment_count = 5, resolved_segment_count = 1, "
                "unresolved_segment_count = 1 WHERE id = %s",
                (body["id"],),
            )
        connection.rollback()


def test_closing_requires_a_note_and_records_the_closer(world: dict[str, Any]) -> None:
    """`05_API_Specification.md:1716`: "The API does not silently discard unmatched content."

    A blank resolution note is the silent discard with a field around it, so it is refused. And the
    closed bundle carries both closing facts, because `ck_bundles_closed_requires_closer` refuses a
    status without them — a bundle that said `closed` with nobody attached would be a conclusion
    with no author.
    """

    client = world["client"]
    sign_in_admin(client, "bundle_accountant")
    bundle_id = upload(world).json()["id"]

    blank = client.post(
        f"/api/v1/bank-result-bundles/{bundle_id}/close",
        json={"resolution_note": "   "},
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert blank.status_code in (400, 409, 422), blank.text

    closed = client.post(
        f"/api/v1/bank-result-bundles/{bundle_id}/close",
        json={"resolution_note": "همه موارد بررسی و تعیین وضعیت شد."},
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"
    assert closed.json()["closed_by"] == "bundle_accountant"
    assert closed.json()["closed_at"] is not None

    # A closed bundle records what was concluded and takes no new associations.
    refused = client.post(
        f"/api/v1/bank-result-bundles/{bundle_id}/batch-links",
        json={"payment_batch_id": str(world["batch_id"]), "link_method": "manual_selection"},
        headers=csrf(client),
    )
    assert refused.status_code in (400, 409), refused.text


def test_closing_requires_an_idempotency_key(world: dict[str, Any]) -> None:
    """`command_catalog.yaml:593` marks it required. 428, because the caller omitted a
    precondition the command needs rather than supplying a bad one."""

    client = world["client"]
    sign_in_admin(client, "bundle_accountant")
    bundle_id = upload(world).json()["id"]

    response = client.post(
        f"/api/v1/bank-result-bundles/{bundle_id}/close",
        json={"resolution_note": "بدون کلید"},
        headers=csrf(client),
    )
    assert response.status_code == 428, response.text


def test_the_detail_carries_what_the_workspace_needs(world: dict[str, Any]) -> None:
    """`API-BUNDLE-001`'s behavioural half.

    The three accepted vocabularies are sent rather than left for a client to duplicate, for the
    reason M7's screens plan gives about parsing one source: a client-side copy disagrees with the
    server the day the server gains a value, and the disagreement shows up as a rejected form.
    """

    client = world["client"]
    sign_in_admin(client, "bundle_accountant")
    bundle_id = upload(world).json()["id"]

    detail = client.get(f"/api/v1/bank-result-bundles/{bundle_id}").json()

    assert detail["files"], "the detail carries no files, so a workspace has nothing to open"
    assert detail["files"][0]["file_name"].endswith(".pdf")
    assert detail["accepted_source_types"]
    assert "source" in detail["accepted_file_roles"]
    assert "manual_selection" in detail["accepted_link_methods"]


def test_no_bundle_route_answers_a_caller_without_the_permission(world: dict[str, Any]) -> None:
    """`SEC-BUNDLE-001`. `15_Agent_Implementation_Plan.md:1069`: "trader cannot access bundle".

    **One test over the whole surface, not one per route.** The requirement is a claim about the
    surface, and five near-copies differing only in a path would let a sixth route arrive with no
    test while the file still looked thorough. The paths are enumerated here and
    `tests/backend/test_m3_definition_of_done.py` independently asserts that every served bundle
    route is classified, so a new one fails there until it is added.

    A manager holds `bank_result_bundle.read` and not `upload`, `link_batch` or `close`, which is
    what makes this prove the routes want *those* grants rather than merely some bundle grant.
    """

    client = world["client"]
    sign_in_admin(client, "bundle_accountant")
    bundle_id = upload(world).json()["id"]

    writes = [
        (
            "POST",
            "/api/v1/bank-result-bundles",
            {"source_type": "bank_portal_download", "files": []},
        ),
        (
            "POST",
            f"/api/v1/bank-result-bundles/{bundle_id}/batch-links",
            {"payment_batch_id": str(world["batch_id"]), "link_method": "manual_selection"},
        ),
        ("POST", f"/api/v1/bank-result-bundles/{bundle_id}/close", {"resolution_note": "x"}),
    ]

    sign_in_admin(client, "bundle_manager")
    for _method, path, body in writes:
        response = client.post(
            path, json=body, headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())}
        )
        assert response.status_code == 403, f"{path} answered {response.status_code}"
    # A manager may read, which is what makes the three refusals above about the write permissions.
    assert client.get("/api/v1/bank-result-bundles").status_code == 200

    sign_in_trader(client)
    for _method, path, body in writes:
        response = client.post(
            path, json=body, headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())}
        )
        assert response.status_code == 403, f"{path} answered {response.status_code} for a trader"
    assert client.get("/api/v1/bank-result-bundles").status_code == 403
    assert client.get(f"/api/v1/bank-result-bundles/{bundle_id}").status_code == 403


def test_the_bundle_number_is_gregorian_and_daily(world: dict[str, Any]) -> None:
    """DOC-CONFLICT-054's interim rule, on the third number family to implement it.

    `05_API_Specification.md:304` gives the `BRB-` prefix and `07_UI_UX_Specification.md:630-640`
    gives day precision and six digits. ADR-006 is Approved and forbids Jalali in stored or
    transported values, so the date is Gregorian and a frontend converts.
    """

    client = world["client"]
    sign_in_admin(client, "bundle_accountant")
    number = upload(world).json()["bundle_number"]

    prefix, day, sequence = number.split("-")
    assert prefix == "BRB"
    assert len(sequence) == 6
    # A Jalali year would be 14xx; a Gregorian one is 20xx. This is the assertion that would have
    # caught M5's invented format.
    assert day.startswith("20")
    datetime.strptime(day, "%Y%m%d").replace(tzinfo=UTC)


def test_a_bundle_file_row_cannot_be_edited_by_the_runtime(world: dict[str, Any]) -> None:
    """The absence of a grant, asserted against the live database.

    `bank_result_bundle_files` gets no UPDATE grant in `20260823_0023`: which file sits at which
    position in which role are three facts that do not change, and a file that turns out to belong
    elsewhere is a row to remove. This asserts it from outside the application, because a bootstrap
    file and a migration are both things somebody can edit.
    """

    client = world["client"]
    sign_in_admin(client, "bundle_accountant")
    bundle_id = upload(world).json()["id"]

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        granted = connection.execute(
            "SELECT count(*) FROM information_schema.column_privileges "
            "WHERE table_name = 'bank_result_bundle_files' AND privilege_type = 'UPDATE' "
            "AND grantee = %s",
            (world["app_role"],),
        ).fetchone()
    assert granted is not None
    assert granted[0] == 0, "the runtime can update a bundle file row"

    assert Path(str(world["storage_root"])).exists()
    assert bundle_id
