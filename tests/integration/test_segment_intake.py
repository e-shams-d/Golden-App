"""Evidence attached, and the constraints that decide what a segment may claim.

M8 slice 2. `DB-SEGMENT-001` lives here because a CHECK can only be shown to refuse by asking
PostgreSQL to refuse — a model's constraint list proves the text exists, not that the database
enforces it.

The edges tested are the ones §12.4's CHECK actually turns on: all-null, a zero width, a rectangle
that runs past the right edge, and the two constraints document 04 does not state — a rectangle
without its page and a rotation without a rectangle.

**M8 slice 4's crop tests live here too**, rather than in a file of their own. The crop is the other
half of the same surface, its route's permission test is the one already in this file, and the
world fixture it needs — a bundle, a clean file, an accountant and a manager — is the one already
built here. Slice 3 made the same call for the opposite reason and it is the same reasoning: a
near-duplicate fixture is where the second copy quietly stops matching the first.

What the crop adds is a source file with **real bytes in storage**. `a_clean_file` writes a row and
no object, which is enough for a segment that only points at a file; a crop has to open one.

**M8 slice 5's previews are here too**, and for a reason that only became clear once they were
written: a preview is only meaningful against a bundle file, the bundle fixture is here, and the
`page_count` assertion `SVC-PREVIEW-001` asks for runs through the bundle upload route this file
already exercises. Two of slice 5's findings came out of that proximity: `a_clean_file` was
creating a file with no bytes in storage, and every fixture here used a file category
`app/files/ownership.py` has no resolver for, so those files were denied to everybody.

**M8 slice 7 ends here too**, and it belongs here for the same reason slice 5 did: the Definition of
Done is a claim about a *sequence* — inspect a mixed bundle, crop it reproducibly, continue without
AI — and every step of that sequence is already built in this file. A journey test in a module
of its own would have rebuilt the fixture and then diverged from it.

Covers: DB-SEGMENT-001, SVC-SEGMENT-003, SEC-SEGMENT-001, SVC-CROP-001, SVC-CROP-003, SVC-CROP-004,
SVC-CROP-005, SVC-CROP-006, AUD-CROP-001, SVC-PREVIEW-002, SEC-PREVIEW-001, API-PREVIEW-001,
SVC-PRIVACY-001, TRACE-M8-002.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery-staple"
TRADER_PHONE = "+989120000822"
IBAN = "IR820540102680020817909002"
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

    storage_root = tmp_path_factory.mktemp("segment-storage")
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=migrated.owner_url,
        redis_url="redis://127.0.0.1:6379/0",
        local_storage_root=storage_root,
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="e" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    trader_id = uuid.uuid4()
    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'Segment Trader', %s, 'active', 'approved')",
            (trader_id, TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (trader_id, TRADER_PHONE, encoded),
        )
        for username, role in (
            ("segment_accountant", "accountant"),
            # Holds `receipt_segment.read` and not `create_external`
            # (`permission_catalog.yaml:534,540`), which is what makes the write negative prove the
            # route wants *that* grant rather than merely some segment grant.
            ("segment_manager", "manager"),
            # M8 slice 5. The one role that holds `file.preview` (`:613`) and **not**
            # `file.read_sensitive_bundle` (`:630`), which makes it the only way to test the
            # ownership resolver rather than the route's permission gate. A trader is refused at the
            # gate with a 403 before ownership is consulted; this actor gets past the gate and
            # must be refused by the resolver — as a `404`, because a `403` there would confirm the
            # file id is real.
            ("segment_warehouse", "warehouse_operator"),
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
            "trader_id": trader_id,
            # M8 slice 4. The crop worker takes a `RuntimeServices`, and this is the one the app is
            # already using — so the worker's transactions go through the same roles and the same
            # storage the routes do, rather than a second runtime that might be configured
            # differently from the one under test.
            "runtime": app.state.runtime,
        }
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(autouse=True)
def a_quiet_files_queue(world: dict[str, Any]) -> Iterator[None]:
    """Every test in this module starts with nothing claimable on the `files` queue.

    **Found by the full suite, not by running these tests one at a time.** The crop tests each
    assert a report count — "the worker rendered exactly one" — and `render_crops` claims the oldest
    *due* job on the queue, not the one the test just made. `test_the_crop_writes_the_audit_row...`
    requests a crop and never drains it, so every test after it was draining somebody else's work:
    the reproduction tests found no file on their own segment, and the queue-ownership test watched
    the worker render a leftover crop and report `rendered=1` where it expected zero.

    Run individually all three passed, which is the trap. A shared queue is shared state, and a test
    that assumes it is empty is asserting something no run guarantees.

    **Cancelled rather than deleted**, because `file_derivations.created_by_job_id` points at
    succeeded jobs — slice 4 is the first writer of that column — and deleting the rows would trip
    the foreign key. Cancelling takes them out of `claimable_jobs` and leaves the history intact.
    """

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            # `finished_at` too: `ck_processing_jobs_finished_at_matches_status` requires a terminal
            # status to carry one, and it refused this fixture's first version for exactly that
            # reason — a cancelled job with no finish time is a lie.
            "UPDATE processing_jobs SET status = 'cancelled', locked_by = NULL, "
            "heartbeat_at = NULL, finished_at = now() WHERE queue_name = 'files' "
            "AND status IN ('queued', 'retry_scheduled', 'running')"
        )
        connection.commit()
    yield


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


def a_clean_file(world: dict[str, Any], name: str = "receipt.pdf") -> str:
    """A bundle source file with bytes actually in storage.

    **This used to write a row and no object**, which was fine while nothing opened the bytes. M8
    slice 5 made `upload_bundle` count a document's pages, so an attach now reads the file — and a
    row whose object is missing is a state `records_without_a_storage_object` exists to *find*, not
    one a fixture should manufacture. Writing the bytes makes the fixture describe something the
    product can actually produce.

    The category is `bank_result_bundle_source`, which is the one `app/files/ownership.py` has a
    resolver for. The earlier spelling — `bank_result_bundle` — had none, so those files were denied
    to everybody; it went unnoticed because no test in this file downloaded or previewed one.
    """

    return a_pdf_in_storage(world, name)


def a_bundle(world: dict[str, Any]) -> dict[str, Any]:
    """One uploaded bundle with one source file, through the routes slice 1 built."""

    client = world["client"]
    file_id = a_clean_file(world)
    created = client.post(
        "/api/v1/bank-result-bundles",
        json={
            "source_type": "bank_portal_download",
            "files": [{"file_id": file_id, "sequence_number": 1, "file_role": "source"}],
        },
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    return {"id": body["id"], "file_id": file_id, "bundle_file_id": body["files"][0]["id"]}


def attach(world: dict[str, Any], bundle: dict[str, Any], **overrides: Any) -> Any:
    client = world["client"]
    body: dict[str, Any] = {
        "source_file_id": bundle["file_id"],
        "bank_result_bundle_file_id": bundle["bundle_file_id"],
        "manual_fields": {
            "beneficiary_name": "علی رضایی",
            "destination_iban": IBAN,
            "amount_irr": "2000000000",
            "tracking_number": "123456",
        },
    }
    body.update(overrides)
    return client.post(
        f"/api/v1/bank-result-bundles/{bundle['id']}/receipt-segments/external",
        json=body,
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )


def insert_segment(world: dict[str, Any], bundle: dict[str, Any], **columns: Any) -> None:
    """Insert a segment with arbitrary column values, through the owner connection.

    The point of this helper is to reach states the application cannot produce. `attach_external`
    never sends a rectangle, so the only way to test §12.4's bbox CHECK at its edges is to write
    the row directly — and the owner connection is required because the provenance columns have no
    UPDATE grant and, for these tests, no application path either.
    """

    # Short names in the parametrised cases, so each case fits on one line and the *shape* of the
    # rectangle is readable rather than buried in column names repeated eight times.
    aliases = {
        "page": "page_number",
        "x": "bbox_x",
        "y": "bbox_y",
        "w": "bbox_width",
        "h": "bbox_height",
        "rotation": "rotation_degrees",
    }

    values: dict[str, Any] = {
        "bank_result_bundle_id": bundle["id"],
        "source_file_id": bundle["file_id"],
        "creation_method": "manual_external_attachment",
        "status": "created",
        "rotation_degrees": 0,
        "raw_extraction": "{}",
        "created_by_actor_type": "admin_user",
        "record_version": 1,
    }
    for key, value in columns.items():
        resolved = aliases.get(key, key)
        assert resolved in {
            *values,
            "page_number",
            "bbox_x",
            "bbox_y",
            "bbox_width",
            "bbox_height",
            "source_pixel_width",
            "source_pixel_height",
        }, f"{key!r} is not a column or a known alias; the insert would fail for the wrong reason"
        values[resolved] = value
    names = ", ".join(values)
    placeholders = ", ".join(["%s"] * len(values))
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            f"INSERT INTO receipt_segments ({names}) VALUES ({placeholders})",
            tuple(values.values()),
        )
        connection.commit()


def test_external_evidence_attaches_whole_with_no_rectangle(world: dict[str, Any]) -> None:
    """The creation method that needs no renderer, end to end.

    §12.4's bbox CHECK has an all-null branch for exactly this: the evidence is the whole file, so a
    segment with no coordinates is a complete record. `rotation_degrees` is 0 because
    `rotation_needs_a_rectangle` refuses an angle beside nothing.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle(world)

    created = attach(world, bundle)
    assert created.status_code == 201, created.text
    body = created.json()

    assert body["creation_method"] == "manual_external_attachment"
    assert body["status"] == "created"
    assert body["bbox_x"] is None
    assert body["rotation_degrees"] == 0
    assert body["segment_file_id"] is None
    # A string on the wire. `MONEY_TIME_CONTRACT.md:17`, and DOC-CONFLICT-050 is why document 05's
    # own example shows a bare number.
    assert body["extracted_amount_irr"] == "2000000000"
    assert body["extraction_confidence"] is None


def test_attaching_evidence_recounts_the_bundle(world: dict[str, Any]) -> None:
    """`SVC-SEGMENT-003`, and the moment slice 1's `recount` stopped returning zeros.

    §12.1 at `:1179` requires the cached counts to be recomputed transactionally from the segments.
    This is the first caller that changes what there is to count, so it is the first test that can
    tell recomputation from a hard-coded zero.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle(world)

    assert attach(world, bundle).status_code == 201
    assert attach(world, bundle, bank_result_bundle_file_id=None).status_code == 201

    detail = client.get(f"/api/v1/bank-result-bundles/{bundle['id']}").json()
    assert detail["segment_count"] == 2
    # Both are `created`, which is a queue status, so neither is resolved.
    assert detail["resolved_segment_count"] == 0
    assert detail["unresolved_segment_count"] == 2

    # And a bundle with unresolved segments cannot be closed — slice 1 wrote that refusal against a
    # count that was always zero, so this is the first time it has been exercised for real.
    refused = client.post(
        f"/api/v1/bank-result-bundles/{bundle['id']}/close",
        json={"resolution_note": "زودهنگام"},
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert refused.status_code in (400, 409), refused.text
    assert "unresolved" in refused.text.lower()


def test_a_closed_bundle_takes_no_new_evidence(world: dict[str, Any]) -> None:
    """A closed bundle records what was concluded. Adding evidence afterwards would mean the
    conclusion was reached without it."""

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle(world)

    closed = client.post(
        f"/api/v1/bank-result-bundles/{bundle['id']}/close",
        json={"resolution_note": "هیچ محتوای مرتبطی نداشت."},
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert closed.status_code == 200, closed.text

    refused = attach(world, bundle)
    assert refused.status_code in (400, 409), refused.text


def test_the_bundle_file_must_hold_the_source_file(world: dict[str, Any]) -> None:
    """Provenance that points at the wrong thing is worse than provenance that points at nothing.

    A segment naming a bundle position that holds a different file would claim its evidence came
    from somewhere it did not. Refused rather than tolerated, because nothing downstream could
    detect it.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle(world)
    other = a_bundle(world)

    mismatched = attach(
        world, bundle, bank_result_bundle_file_id=other["bundle_file_id"]
    )
    assert mismatched.status_code in (400, 409), mismatched.text


@pytest.mark.parametrize(
    ("label", "columns"),
    [
        # §12.4's in-bounds branch, four ways.
        ("zero width", {"page": 1, "x": "0.1", "y": "0.1", "w": "0", "h": "0.2"}),
        ("past the right edge", {"page": 1, "x": "0.5", "y": "0.1", "w": "0.6", "h": "0.2"}),
        ("past the bottom edge", {"page": 1, "x": "0.1", "y": "0.9", "w": "0.2", "h": "0.2"}),
        ("negative origin", {"page": 1, "x": "-0.1", "y": "0.1", "w": "0.2", "h": "0.2"}),
        # Q-11: the case §12.4 accepts, because its in-bounds branch evaluates to NULL.
        ("half a rectangle", {"page": 1, "x": "0.1", "y": "0.1", "w": "0.2"}),
        # The two constraints §12.4 does not state.
        ("a rectangle with no page", {"x": "0.1", "y": "0.1", "w": "0.2", "h": "0.2"}),
        ("a rotation with no rectangle", {"rotation": 90}),
        (
            "an angle no preview can produce",
            {"page": 1, "x": "0.1", "y": "0.1", "w": "0.2", "h": "0.2", "rotation": 45},
        ),
    ],
)
def test_the_database_refuses_an_unreproducible_rectangle(
    world: dict[str, Any], label: str, columns: dict[str, Any]
) -> None:
    """`DB-SEGMENT-001`. §12.4's CHECK at each edge, plus the two constraints it does not state.

    Every case here is a row that would sit in the table looking like evidence and be impossible to
    reproduce. Eight, because a single "the CHECK exists" assertion passes with any one branch of it
    deleted — `SVC-INTEGRITY-001`'s lesson from M7, applied to a constraint instead of a function.

    The last two are DOC-CONFLICT-057's: a rotation stored beside no rectangle describes nothing,
    and an angle no preview control can produce could never be reproduced by one.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle(world)

    with pytest.raises(psycopg.errors.CheckViolation):
        insert_segment(world, bundle, **columns)

    assert label


def test_the_database_accepts_a_reproducible_rectangle(world: dict[str, Any]) -> None:
    """The positive control for the eight refusals above.

    Without it every one of them could pass because the insert was malformed for some unrelated
    reason — the fourth meaning of NOT CAUGHT, arriving as eight false confirmations.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle(world)

    insert_segment(
        world,
        bundle,
        page_number=2,
        bbox_x="0.105000",
        bbox_y="0.220000",
        bbox_width="0.790000",
        bbox_height="0.160000",
        rotation_degrees=90,
        creation_method="manual_in_panel_crop",
        source_pixel_width=1600,
        source_pixel_height=2200,
    )

    stored = rows(
        world,
        "SELECT bbox_x, bbox_width, rotation_degrees FROM receipt_segments "
        "WHERE bank_result_bundle_id = %s AND creation_method = 'manual_in_panel_crop'",
        bundle["id"],
    )
    assert len(stored) == 1
    # The exact decimal, not a float. A rectangle stored as 0.10500000000000001 reproduces a
    # different crop, and `NUMERIC(10,6)` is what makes the stored value the one that was sent.
    assert str(stored[0][0]) == "0.105000"
    assert str(stored[0][1]) == "0.790000"
    assert stored[0][2] == 90


def test_the_read_returns_provenance_as_exact_decimals(world: dict[str, Any]) -> None:
    """A reader who cannot see the rectangle cannot check the crop.

    Returned as strings for the same reason they are stored as `NUMERIC`: a JSON float would hand a
    browser a value the database never held, and the whole point of these four numbers is that they
    are the ones the crop was made from.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle(world)
    insert_segment(
        world,
        bundle,
        page_number=1,
        bbox_x="0.250000",
        bbox_y="0.100000",
        bbox_width="0.500000",
        bbox_height="0.300000",
        rotation_degrees=270,
        creation_method="manual_in_panel_crop",
    )

    segment_id = rows(
        world,
        "SELECT id FROM receipt_segments WHERE bank_result_bundle_id = %s "
        "AND creation_method = 'manual_in_panel_crop'",
        bundle["id"],
    )[0][0]

    body = client.get(f"/api/v1/receipt-segments/{segment_id}").json()
    assert body["bbox_x"] == "0.250000"
    assert body["bbox_width"] == "0.500000"
    assert body["rotation_degrees"] == 270
    assert body["page_number"] == 1


def test_no_segment_route_answers_a_caller_without_the_permission(
    world: dict[str, Any],
) -> None:
    """`SEC-SEGMENT-001`. `15_Agent_Implementation_Plan.md:1069`: "trader cannot access ... internal
    segment".

    One test over the surface rather than one per route, for slice 1's reason: the requirement is a
    claim about the surface, and near-copies differing only in a path let a later route arrive
    untested while the file still looks thorough.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle(world)
    segment_id = attach(world, bundle).json()["id"]

    write_path = f"/api/v1/bank-result-bundles/{bundle['id']}/receipt-segments/external"
    read_path = f"/api/v1/receipt-segments/{segment_id}"

    # A manager may read evidence and may not create it.
    sign_in_admin(client, "segment_manager")
    assert client.get(read_path).status_code == 200
    assert client.post(
        write_path,
        json={"source_file_id": bundle["file_id"]},
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    ).status_code == 403

    # A trader reaches neither.
    sign_in_trader(client)
    assert client.get(read_path).status_code == 403
    assert client.post(
        write_path,
        json={"source_file_id": bundle["file_id"]},
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    ).status_code == 403


def test_the_runtime_cannot_rewrite_provenance(world: dict[str, Any]) -> None:
    """`SVC-SEGMENT-002`'s database half, asserted from outside the application.

    The API half is `tests/backend/test_segment_surface.py`: no request model accepts these fields.
    This is the other reason they cannot change — there is no grant — and the two are independent,
    which is the right number for a rule whose failure is silent.
    """

    granted = rows(
        world,
        "SELECT column_name FROM information_schema.column_privileges "
        "WHERE table_name = 'receipt_segments' AND privilege_type = 'UPDATE' "
        "AND grantee = %s ORDER BY column_name",
        world["app_role"],
    )
    writable = {row[0] for row in granted}

    frozen = {
        "source_file_id",
        "bank_result_bundle_id",
        "bank_result_bundle_file_id",
        "page_number",
        "bbox_x",
        "bbox_y",
        "bbox_width",
        "bbox_height",
        "rotation_degrees",
        "source_pixel_width",
        "source_pixel_height",
        "renderer_version",
        "creation_method",
        "created_by_actor_type",
        "created_by_actor_id",
        "created_at",
    }

    assert writable, "no UPDATE grant at all; the assertion below would be vacuous"
    leaked = sorted(frozen & writable)
    assert leaked == [], f"the runtime can rewrite provenance: {leaked}"
    # And it can write what a person typed, plus the file the crop worker attaches.
    assert "extracted_amount_irr" in writable
    assert "segment_file_id" in writable


# ---------------------------------------------------------------------------
# M8 slice 4: the in-panel crop.
# ---------------------------------------------------------------------------

# The same two-page PDF `tests/backend/test_crop_renderer.py` uses. Duplicated deliberately rather
# than imported across the backend/integration boundary: the renderer test owns it as the subject of
# a measurement, and this file needs it as a fixture. A shared constant would couple a change made
# for one purpose to the other.
TWO_PAGES = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R 5 0 R]/Count 2>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 400]/Contents 4 0 R"
    b"/Resources<</Font<</F1 7 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 44>>stream\n"
    b"BT /F1 24 Tf 20 300 Td (PAGE ONE) Tj ET\n"
    b"endstream endobj\n"
    b"5 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 400]/Contents 6 0 R"
    b"/Resources<</Font<</F1 7 0 R>>>>>>endobj\n"
    b"6 0 obj<</Length 44>>stream\n"
    b"BT /F1 24 Tf 20 300 Td (PAGE TWO) Tj ET\n"
    b"endstream endobj\n"
    b"7 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"trailer<</Root 1 0 R>>\n"
)

# 300x400 points at scale 2.0, upright and quarter-turned. Written out rather than computed, because
# a test that derived these from the same code under test would agree with a bug in it.
UPRIGHT = (600, 800)
TURNED = (800, 600)

A_RECTANGLE = {"x": "0.105000", "y": "0.220000", "width": "0.500000", "height": "0.300000"}


def a_pdf_in_storage(world: dict[str, Any], name: str = "bundle.pdf") -> str:
    """A file row whose bytes are actually there, with the digest storage would measure.

    `a_clean_file` above writes a row and no object, which is enough for a segment that only points
    at a file. A crop has to open one — and the digest must be the real one, because `SVC-CROP-003`
    compares it before and after.
    """

    file_id = uuid.uuid4()
    key = f"segments/{file_id}"
    target = world["storage_root"] / key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(TWO_PAGES)

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
            "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
            "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
            "original_or_derived_relation, metadata) "
            "VALUES (%s, 'local', 'gold', %s, %s, 'application/pdf', %s, %s, "
            "'bank_result_bundle_source', 'internal', 'available', 'clean', 'admin_user', "
            "'original', '{}')",
            (file_id, key, name, len(TWO_PAGES), hashlib.sha256(TWO_PAGES).hexdigest()),
        )
        connection.commit()
    return str(file_id)


def a_bundle_with_a_pdf(world: dict[str, Any]) -> dict[str, Any]:
    client = world["client"]
    file_id = a_pdf_in_storage(world)
    created = client.post(
        "/api/v1/bank-result-bundles",
        json={
            "source_type": "bank_portal_download",
            "files": [{"file_id": file_id, "sequence_number": 1, "file_role": "source"}],
        },
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    return {"id": body["id"], "file_id": file_id, "bundle_file_id": body["files"][0]["id"]}


def request_a_crop(world: dict[str, Any], bundle: dict[str, Any], **overrides: Any) -> Any:
    client = world["client"]
    body: dict[str, Any] = {
        "source_file_id": bundle["file_id"],
        "bank_result_bundle_file_id": bundle["bundle_file_id"],
        "page_number": 1,
        "bbox": dict(A_RECTANGLE),
        "client_source_dimensions": {"width": UPRIGHT[0], "height": UPRIGHT[1]},
        "rotation_degrees": 0,
    }
    body.update(overrides)
    return client.post(
        f"/api/v1/bank-result-bundles/{bundle['id']}/receipt-segments/crop",
        json=body,
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )


def run_the_worker(world: dict[str, Any], passes: int = 1) -> Any:
    """The `files` queue, drained through the real task rather than by calling the command.

    Going through `render_crops` is the point: it is what claims the job, what decides a failure is
    retryable, and what escalates. Calling `render_pending_crop` directly would test the render and
    none of the machinery that has to surround it.
    """

    from app.workers.tasks.files import render_crops

    return render_crops(world["runtime"], limit=passes)


def drain(world: dict[str, Any]) -> Any:
    """Run the worker and insist it rendered, reporting the job's own error when it did not.

    Written after the first run of these tests returned `failed=1` and nothing else. The worker
    deliberately swallows every render exception — that is what keeps a failed crop from abandoning
    its lease — so a test that only asserts a count leaves whoever reads it with no way to tell a
    corrupt PDF from a missing grant. The error is already in the row; this reads it out.
    """

    report = run_the_worker(world)
    if report.rendered != 1:
        failures = rows(
            world,
            "SELECT status, last_error_code, last_error_message FROM processing_jobs "
            "WHERE job_type = 'receipt_segment.render_crop' AND last_error_code IS NOT NULL "
            "ORDER BY updated_at DESC LIMIT 3",
        )
        raise AssertionError(f"the worker rendered nothing: {report}; recent failures: {failures}")
    return report


def test_a_crop_is_requested_then_rendered(world: dict[str, Any]) -> None:
    """`SVC-CROP-001`. The ten requirements, walked in the order they happen.

    One test for the path that works and separate tests for each refusal below, because the
    requirements that are *absences* cannot be asserted by the same run that proves a crop works.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle_with_a_pdf(world)

    accepted = request_a_crop(world, bundle)

    # 202, not 201: the row exists and the image does not.
    assert accepted.status_code == 202, accepted.text
    body = accepted.json()
    segment_id = body["segment"]["id"]

    # Requirement 4: both records, and the segment carrying no file yet.
    assert body["segment"]["segment_file_id"] is None
    assert body["segment"]["creation_method"] == "manual_in_panel_crop"
    assert body["processing_job_status"] == "queued"

    # Requirement 8, recorded at request time because slice 2 froze these three columns.
    assert body["segment"]["source_pixel_width"] == UPRIGHT[0]
    assert body["segment"]["source_pixel_height"] == UPRIGHT[1]
    assert body["segment"]["renderer_version"].startswith("pypdfium2/")
    # The rectangle comes back as the exact decimals it was sent as, not as floats.
    assert body["segment"]["bbox_x"] == A_RECTANGLE["x"]
    assert body["segment"]["bbox_width"] == A_RECTANGLE["width"]

    # Requirement 5: on the `files` queue, which is the queue this task routes to.
    queued = rows(
        world,
        "SELECT job_type, queue_name, provider FROM processing_jobs WHERE id = %s",
        body["processing_job_id"],
    )
    assert queued == [("receipt_segment.render_crop", "files", "pypdfium2")]

    drain(world)

    # Requirement 7: a derived file with storage's own checksum, and a derivation accounting for it.
    linked = rows(
        world,
        "SELECT f.sha256_hash, f.mime_type_declared, f.original_or_derived_relation, "
        "d.derivation_type, d.renderer_version, d.created_by_job_id "
        "FROM receipt_segments s JOIN file_objects f ON f.id = s.segment_file_id "
        "JOIN file_derivations d ON d.derived_file_id = f.id WHERE s.id = %s",
        segment_id,
    )
    assert len(linked) == 1, "a rendered crop has exactly one derived file and one derivation"
    digest, media_type, relation, derivation_type, renderer, job_id = linked[0]
    assert media_type == "image/png"
    assert relation == "derived"
    assert derivation_type == "crop"
    assert renderer.startswith("pypdfium2/")
    assert len(digest) == 64
    # The first row ever written to this column: it has existed since M4 with no writer at all.
    assert str(job_id) == body["processing_job_id"]

    # And the job says what it produced.
    finished = rows(
        world,
        "SELECT status, output_payload FROM processing_jobs WHERE id = %s",
        body["processing_job_id"],
    )
    assert finished[0][0] == "succeeded"
    assert finished[0][1]["derived_file_id"]


def test_the_source_file_is_untouched_by_its_own_crop(world: dict[str, Any]) -> None:
    """`SVC-CROP-003`. `08_Bank_File_and_Result_Processing.md:137`, measured rather than assumed.

    Both halves: the bytes on disk and the row's recorded digest. A test that only checked the row
    would pass while the object had been overwritten, and one that only checked the bytes would pass
    while the row had been edited to match a different file.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle_with_a_pdf(world)

    stored = rows(
        world,
        "SELECT storage_key, sha256_hash FROM file_objects WHERE id = %s",
        bundle["file_id"],
    )[0]
    path = world["storage_root"] / stored[0]
    before = path.read_bytes()

    assert request_a_crop(world, bundle).status_code == 202
    assert run_the_worker(world).rendered == 1

    after = path.read_bytes()
    assert after == before, "the source PDF changed while its crop was being taken"
    assert hashlib.sha256(after).hexdigest() == stored[1], "the source no longer matches its row"
    assert before == TWO_PAGES, (
        "if the source were not the document this test wrote, the comparison above would be "
        "comparing two copies of the wrong thing"
    )


def test_a_rectangle_drawn_against_the_wrong_raster_is_refused(world: dict[str, Any]) -> None:
    """The check §16.4 does not name, and the only one a bounds test cannot make.

    Every coordinate here is between 0 and 1, so the rectangle is valid; it was normalised against a
    raster twice the size of the one the server renders. Accepting it would store a perfectly
    well-formed rectangle describing a region the operator never selected.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle_with_a_pdf(world)

    refused = request_a_crop(
        world, bundle, client_source_dimensions={"width": 1200, "height": 1600}
    )

    assert refused.status_code == 400, refused.text
    assert "raster" in refused.json()["error"]["message"]
    # And nothing was written. A refusal that left a segment behind would be worse than accepting.
    assert rows(
        world,
        "SELECT count(*) FROM receipt_segments WHERE bank_result_bundle_id = %s",
        bundle["id"],
    ) == [(0,)]


def test_a_rotated_crop_must_report_the_rotated_raster(world: dict[str, Any]) -> None:
    """DOC-CONFLICT-057, from the outside.

    The upright raster is 600x800 and the quarter-turned one is 800x600, so sending the angle
    without the matching dimensions is refused. That is the same fact as "the rectangle means
    nothing without the angle", observed from the direction a client experiences it.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle_with_a_pdf(world)

    wrong = request_a_crop(world, bundle, rotation_degrees=90)
    assert wrong.status_code == 400, wrong.text

    right = request_a_crop(
        world,
        bundle,
        rotation_degrees=90,
        client_source_dimensions={"width": TURNED[0], "height": TURNED[1]},
    )
    assert right.status_code == 202, right.text
    assert right.json()["segment"]["rotation_degrees"] == 90
    assert right.json()["segment"]["source_pixel_width"] == TURNED[0]

    assert run_the_worker(world).rendered == 1


def test_an_angle_no_preview_can_produce_is_refused(world: dict[str, Any]) -> None:
    """The four permitted angles, at the route.

    `08_...Processing.md:985` gives clockwise and counter-clockwise rotation and nothing else, so an
    arbitrary angle could never have been produced by the control that is supposed to have created
    it — nor reproduced by it later.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle_with_a_pdf(world)

    refused = request_a_crop(world, bundle, rotation_degrees=45)
    assert refused.status_code == 400, refused.text


def test_a_retry_renders_no_second_file(world: dict[str, Any]) -> None:
    """`SVC-CROP-005`, first half. §16.4's ninth requirement at the worker.

    Draining the queue twice is the realistic version of a redelivered message. The assertion is on
    the *count* of derived files rather than on what the second call returned: a second file would
    leave two objects in storage both claiming to be this segment's evidence.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle_with_a_pdf(world)
    segment_id = request_a_crop(world, bundle).json()["segment"]["id"]

    assert run_the_worker(world).rendered == 1
    second = run_the_worker(world)

    assert second.rendered == 0, "the worker rendered the same crop twice"
    derived = rows(
        world,
        "SELECT count(*) FROM file_derivations d JOIN receipt_segments s "
        "ON s.segment_file_id = d.derived_file_id WHERE s.id = %s",
        segment_id,
    )
    assert derived == [(1,)]


def test_a_failed_render_leaves_no_evidence(world: dict[str, Any]) -> None:
    """`SVC-CROP-005`, second half. `15_Agent_Implementation_Plan.md:1069`.

    The source is replaced with bytes that are not a PDF *after* the request is accepted, which is
    the only way to reach the render's failure path: the request path opens the document, so a file
    that was never readable would have been refused before a job existed.

    What matters is the pair of assertions. The job records the failure, and the segment still has
    no file — a segment pointing at a half-written object is the artifact this lifecycle exists to
    prevent.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle_with_a_pdf(world)
    accepted = request_a_crop(world, bundle).json()
    segment_id = accepted["segment"]["id"]

    key = rows(world, "SELECT storage_key FROM file_objects WHERE id = %s", bundle["file_id"])
    (world["storage_root"] / key[0][0]).write_bytes(b"this is not a PDF")

    report = run_the_worker(world)
    assert report.failed == 1, f"a corrupt source rendered successfully: {report}"

    segment = rows(
        world, "SELECT segment_file_id, status FROM receipt_segments WHERE id = %s", segment_id
    )
    assert segment[0][0] is None, "a failed render left a file on the segment"
    assert segment[0][1] == "created", "a failed render changed the segment status"

    job = rows(
        world,
        "SELECT status, last_error_code FROM processing_jobs WHERE id = %s",
        accepted["processing_job_id"],
    )
    assert job[0][0] in {"retry_scheduled", "dead_lettered"}
    assert job[0][1], "the job records no error code, so nobody can tell why it failed"


def test_a_quarantined_source_cannot_be_cropped(world: dict[str, Any]) -> None:
    """`SVC-CROP-006`. §16.4's second requirement, at both ends.

    Asserted twice on purpose. A source quarantined before the request is refused at the route, and
    one quarantined after the request is refused at the worker. The second is the one that matters
    operationally: a scanner verdict arriving between the two would otherwise produce a crop of a
    file the platform has decided nobody may open.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")

    early = a_bundle_with_a_pdf(world)
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            # Both columns, because `ck_file_objects_available_requires_clean_scan` refuses an
            # `available` file that is not clean — the constraint being right: a quarantined file is
            # one nobody may open *and* one storage should not serve.
            "UPDATE file_objects SET scan_status = 'infected', storage_status = 'quarantined' "
            "WHERE id = %s",
            (early["file_id"],),
        )
        connection.commit()
    refused = request_a_crop(world, early)
    assert refused.status_code == 400, refused.text
    assert "scan status" in refused.json()["error"]["message"]

    late = a_bundle_with_a_pdf(world)
    accepted = request_a_crop(world, late).json()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE file_objects SET scan_status = 'infected', storage_status = 'quarantined' "
            "WHERE id = %s",
            (late["file_id"],),
        )
        connection.commit()

    assert run_the_worker(world).failed == 1
    assert rows(
        world,
        "SELECT segment_file_id FROM receipt_segments WHERE id = %s",
        accepted["segment"]["id"],
    ) == [(None,)]


def test_the_crop_writes_the_audit_row_the_catalogue_names(world: dict[str, Any]) -> None:
    """`AUD-CROP-001`. `audit_outbox_catalog.yaml:38` names the action; this is it.

    **And no outbox event**, which the catalogue also says: nothing outside the platform acts on
    evidence being cut out of a page. Asserted as an absence, because an event nobody consumes is
    still an event somebody has to explain.

    The rectangle is in `new_values` so the audit row alone reproduces the crop, which is why it is
    there rather than only in `receipt_segments`.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle_with_a_pdf(world)
    segment_id = request_a_crop(world, bundle).json()["segment"]["id"]

    entries = rows(
        world,
        "SELECT action, outcome, new_values, actor_type FROM audit_logs "
        "WHERE entity_type = 'receipt_segment' AND entity_id = %s",
        segment_id,
    )
    assert len(entries) == 1, f"expected one audit row for the crop, found {len(entries)}"
    action, outcome, new_values, actor_type = entries[0]
    assert action == "receipt_segment.crop_created"
    assert outcome == "success"
    assert actor_type == "admin_user"
    assert new_values["rotation_degrees"] == 0
    assert new_values["bbox"] == [
        A_RECTANGLE["x"],
        A_RECTANGLE["y"],
        A_RECTANGLE["width"],
        A_RECTANGLE["height"],
    ]

    events = rows(
        world, "SELECT count(*) FROM outbox_events WHERE aggregate_id = %s", segment_id
    )
    assert events == [(0,)], "the catalogue gives this action no outbox event"


def test_the_crop_route_needs_the_crop_permission(world: dict[str, Any]) -> None:
    """`SEC-SEGMENT-001` for slice 4's route.

    Separate from the surface test above rather than folded into it: that test builds a segment by
    attaching a file, and a crop needs a PDF in storage. Folding them would make the older test
    depend on the newer fixture for no gain.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle_with_a_pdf(world)

    # A manager may read evidence and may not cut it out.
    sign_in_admin(client, "segment_manager")
    assert request_a_crop(world, bundle).status_code == 403

    sign_in_trader(client)
    assert request_a_crop(world, bundle).status_code == 403


def test_the_crop_route_requires_an_idempotency_key(world: dict[str, Any]) -> None:
    """`command_catalog.yaml:277` says `idempotency: required`, not recommended.

    Without one, a retried request produces a second segment claiming the same rectangle, a second
    render job, and a bundle whose segment count double-counts one piece of evidence.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle_with_a_pdf(world)

    response = client.post(
        f"/api/v1/bank-result-bundles/{bundle['id']}/receipt-segments/crop",
        json={
            "source_file_id": bundle["file_id"],
            "bank_result_bundle_file_id": bundle["bundle_file_id"],
            "page_number": 1,
            "bbox": dict(A_RECTANGLE),
            "client_source_dimensions": {"width": UPRIGHT[0], "height": UPRIGHT[1]},
        },
        headers=csrf(client),
    )

    assert response.status_code == 428, response.text


def test_the_stored_row_alone_reproduces_the_crop(world: dict[str, Any]) -> None:
    """`SVC-CROP-004`, and the strong form of it.

    `tests/backend/test_crop_renderer.py` proves the renderer is deterministic. This proves the
    *row* is sufficient: nothing is read from the job, the request or this test's own constants —
    the five stored values are fetched back out of `receipt_segments` and fed to the renderer, and
    the bytes are compared against the object storage actually holds.

    **On a rotated page, deliberately.** DOC-CONFLICT-057 is only a real conflict if the angle
    changes the result, so an upright crop would reproduce correctly even with the rotation
    forgotten — which is exactly the negative control this slice runs. §16.6 asks for reproduction
    "within approved tolerance" and no document approves one; equality holds, so Q-3 records that
    there is nothing to approve.
    """

    from app.exports.crop import Rectangle, render_crop

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle_with_a_pdf(world)

    accepted = request_a_crop(
        world,
        bundle,
        rotation_degrees=270,
        client_source_dimensions={"width": TURNED[0], "height": TURNED[1]},
    )
    assert accepted.status_code == 202, accepted.text
    segment_id = accepted.json()["segment"]["id"]
    drain(world)

    # Everything needed to render again, read back from the database rather than remembered.
    stored = rows(
        world,
        "SELECT s.page_number, s.bbox_x, s.bbox_y, s.bbox_width, s.bbox_height, "
        "s.rotation_degrees, s.renderer_version, f.storage_key, src.storage_key "
        "FROM receipt_segments s "
        "JOIN file_objects f ON f.id = s.segment_file_id "
        "JOIN file_objects src ON src.id = s.source_file_id "
        "WHERE s.id = %s",
        segment_id,
    )
    assert len(stored) == 1, "the crop was not rendered, so there is nothing to reproduce"
    page, x, y, width, height, rotation, renderer, crop_key, source_key = stored[0]

    original = (world["storage_root"] / source_key).read_bytes()
    again = render_crop(
        original,
        page_number=page,
        rectangle=Rectangle(x=x, y=y, width=width, height=height),
        rotation_degrees=rotation,
    )

    on_disk = (world["storage_root"] / crop_key).read_bytes()
    assert again.content == on_disk, (
        "the stored provenance does not reproduce the stored crop, so nobody can verify that this "
        "image is the region the operator selected"
    )
    assert again.renderer_version == renderer
    assert rotation == 270, "the rotated case is the only one that tests the angle at all"
    assert len(on_disk) > 0


def test_forgetting_the_rotation_would_reproduce_the_wrong_region(world: dict[str, Any]) -> None:
    """DOC-CONFLICT-057's negative control, run in the product rather than in a sabotage script.

    The plan's control for `SVC-CROP-004` is "store the bbox without the rotation". Rather than
    breaking the code to watch a test fail, this asserts the fact the control depends on: the same
    stored rectangle rendered at 0 degrees is **not** the crop that was stored at 270. If these were
    equal, storing the angle would be optional and DOC-CONFLICT-057 would not exist.

    Run as a test rather than a script because the property is permanent. A future renderer that
    ignored rotation would make this fail, which is the moment somebody needs to know.
    """

    from app.exports.crop import Rectangle, render_crop

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle_with_a_pdf(world)

    accepted = request_a_crop(
        world,
        bundle,
        rotation_degrees=270,
        client_source_dimensions={"width": TURNED[0], "height": TURNED[1]},
    )
    segment_id = accepted.json()["segment"]["id"]
    drain(world)

    stored = rows(
        world,
        "SELECT s.bbox_x, s.bbox_y, s.bbox_width, s.bbox_height, f.storage_key, src.storage_key "
        "FROM receipt_segments s "
        "JOIN file_objects f ON f.id = s.segment_file_id "
        "JOIN file_objects src ON src.id = s.source_file_id WHERE s.id = %s",
        segment_id,
    )
    x, y, width, height, crop_key, source_key = stored[0]
    original = (world["storage_root"] / source_key).read_bytes()
    rectangle = Rectangle(x=x, y=y, width=width, height=height)

    without_the_angle = render_crop(
        original, page_number=1, rectangle=rectangle, rotation_degrees=0
    )
    with_the_angle = render_crop(
        original, page_number=1, rectangle=rectangle, rotation_degrees=270
    )
    on_disk = (world["storage_root"] / crop_key).read_bytes()

    assert with_the_angle.content == on_disk
    assert without_the_angle.content != on_disk, (
        "rendering without the stored rotation produced the same image, so the rotation column "
        "records nothing and DOC-CONFLICT-057 is not a conflict after all"
    )


def test_the_worker_leaves_another_tasks_job_alone(world: dict[str, Any]) -> None:
    """The `files` queue will not hold only crops, and this is the branch that matters when it does.

    Slice 5 puts preview rendering on this queue. Until then the "claimed something I cannot run"
    path has no caller in the product — the shape this repository has now hit thirteen times — so it
    is exercised directly rather than left to be discovered by whoever adds the second task.

    **Released, not failed.** Marking it failed would consume the attempts of a job this worker
    never tried, so the preview worker would find one already halfway to dead-lettered for nothing.
    """

    other = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO processing_jobs (id, job_type, queue_name, status, input_payload) "
            "VALUES (%s, 'file.render_preview', 'files', 'queued', '{}')",
            (other,),
        )
        connection.commit()

    report = run_the_worker(world)

    assert report == report.__class__(rendered=0, failed=0, escalated=0), (
        f"a job this task does not own was treated as work: {report}"
    )
    state = rows(
        world,
        "SELECT status, attempt_count, last_error_code FROM processing_jobs WHERE id = %s",
        other,
    )
    assert state[0][0] == "retry_scheduled", "the job was not handed back to the queue"
    assert state[0][2] is None, "an untried job was given an error code"
    # The claim did consume an attempt, which is `claim_jobs` being deliberate: a worker that
    # crashes mid-run must still have used one, or a poison job is retried forever.
    assert state[0][1] == 1


def test_rendering_one_segment_twice_makes_one_file(world: dict[str, Any]) -> None:
    """`SVC-CROP-005` at the command, which is the only place the guard is reachable.

    **Written because a negative control was right and the test was not.** Removing
    `render_pending_crop`'s already-rendered early return reported NOT CAUGHT through the worker,
    and the reason is that the worker's idempotency comes from somewhere else entirely: after a
    success the job is `succeeded`, so a second pass claims nothing and never reaches the guard. Two
    independent protections, and the queue-level one was hiding the command-level one.

    The guard still matters, and this is where it is reachable: anything that renders a segment
    without going through the queue — a re-render from the workspace, a repair script, slice 6 —
    asks this function directly. So it is called directly here, twice, and one file must exist.
    """

    from app.commands.receipt_crop import render_pending_crop
    from app.core.time import utc_now

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle_with_a_pdf(world)
    segment_id = uuid.UUID(request_a_crop(world, bundle).json()["segment"]["id"])

    runtime = world["runtime"]
    with runtime.uow_factory() as uow:
        first = render_pending_crop(
            segment_id, uow=uow, storage=runtime.storage, now=utc_now()
        )
        uow.commit()
    with runtime.uow_factory() as uow:
        second = render_pending_crop(
            segment_id, uow=uow, storage=runtime.storage, now=utc_now()
        )
        uow.commit()

    assert first == second, "the second render produced a different file for the same segment"
    derived = rows(
        world,
        "SELECT count(*) FROM file_derivations d JOIN receipt_segments s "
        "ON s.segment_file_id = d.derived_file_id WHERE s.id = %s",
        segment_id,
    )
    assert derived == [(1,)]


def test_a_renderer_upgrade_between_request_and_render_is_refused(
    world: dict[str, Any],
) -> None:
    """The check requirement 8 became, once slice 2's grants made rewriting impossible.

    A crop is requested, the platform is upgraded, and the worker then renders with a renderer the
    row does not name. The row cannot be corrected — `20260824_0024` grants the runtime no UPDATE on
    `renderer_version` — and it should not be: provenance that gets edited to match the file it is
    supposed to describe describes nothing.

    So the render refuses and the operator re-requests. Simulated from the owner connection, because
    that is the only writer that *can* create this state — which is itself the point.

    **This test exists because a negative control could not create the state.** Changing
    `RENDERER_VERSION` in the source changes what `request_crop` stores *and* what the render
    produces, so the two still agree and the sabotage reported NOT CAUGHT. The control was right: no
    edit to that constant can produce drift, only a deploy between two moments can.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle_with_a_pdf(world)
    accepted = request_a_crop(world, bundle).json()
    segment_id = accepted["segment"]["id"]

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE receipt_segments SET renderer_version = 'pypdfium2/4.0.0 pdfium/1.0.0.0' "
            "WHERE id = %s",
            (segment_id,),
        )
        connection.commit()

    report = run_the_worker(world)
    assert report.failed == 1, f"a crop rendered against provenance it does not match: {report}"

    state = rows(
        world,
        "SELECT segment_file_id, renderer_version FROM receipt_segments WHERE id = %s",
        segment_id,
    )
    assert state[0][0] is None, "a mismatched render still attached a file"
    assert state[0][1] == "pypdfium2/4.0.0 pdfium/1.0.0.0", (
        "the worker rewrote the provenance to match its own output, which is the failure this "
        "refusal exists to prevent"
    )

    job = rows(
        world,
        "SELECT last_error_message FROM processing_jobs WHERE id = %s",
        accepted["processing_job_id"],
    )
    assert "provenance" in (job[0][0] or ""), (
        f"the job does not say why it refused: {job[0][0]!r}"
    )


# ---------------------------------------------------------------------------
# M8 slice 5: previews. doc 08 `:983`, doc 05 `:1041-1042`.
# ---------------------------------------------------------------------------

# A one-page JPEG-like PNG with an off-centre mark, so a wrong rotation is visible rather than
# plausible. Built here rather than imported from the renderer test: that file owns it as the
# subject of a measurement and this one needs a fixture, and a shared constant would couple a
# change made for one purpose to the other.
def an_image_file(world: dict[str, Any]) -> str:
    from PIL import Image

    picture = Image.new("RGB", (40, 20), (255, 255, 255))
    for x in range(10):
        for y in range(5):
            picture.putpixel((x, y), (255, 0, 0))
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")
    return _stored_file(world, buffer.getvalue(), "receipt.png", "image/png")


def a_pdf_file(world: dict[str, Any]) -> str:
    return _stored_file(world, TWO_PAGES, "bundle.pdf", "application/pdf")


def a_spreadsheet_file(world: dict[str, Any]) -> str:
    """A file with no pages at all, which is most of what a bank actually sends."""

    return _stored_file(
        world,
        b"account,amount\nIR000000000000000000000000,1000\n",
        "results.csv",
        "text/csv",
    )


def _stored_file(world: dict[str, Any], content: bytes, name: str, media_type: str) -> str:
    file_id = uuid.uuid4()
    key = f"previews/{file_id}"
    target = world["storage_root"] / key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
            "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
            "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
            "original_or_derived_relation, metadata) "
            "VALUES (%s, 'local', 'gold', %s, %s, %s, %s, %s, "
            "'bank_result_bundle_source', 'internal', 'available', 'clean', 'admin_user', "
            "'original', '{}')",
            (
                file_id,
                key,
                name,
                media_type,
                len(content),
                hashlib.sha256(content).hexdigest(),
            ),
        )
        connection.commit()
    return str(file_id)


def preview(world: dict[str, Any], file_id: str, page: int = 1, **query: Any) -> Any:
    suffix = "".join(f"&{k}={v}" for k, v in query.items())
    return world["client"].get(f"/api/v1/files/{file_id}/pages/{page}/preview?x=1{suffix}")


def test_a_multi_page_pdf_and_a_rotated_image_both_render(world: dict[str, Any]) -> None:
    """`SVC-PREVIEW-001`. §16 `:1069`'s first test, both halves of it.

    The two document kinds go through different renderers — PDFium for one, Pillow for the other —
    so a test that only covered PDFs would leave the image path unexercised while looking complete.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")

    document = a_pdf_file(world)
    page_one = preview(world, document, 1)
    assert page_one.status_code == 200, page_one.text
    assert page_one.headers["content-type"] == "image/png"
    assert page_one.content.startswith(b"\x89PNG")

    page_two = preview(world, document, 2)
    assert page_two.status_code == 200, page_two.text
    assert page_two.content != page_one.content, "both pages rendered the same image"

    # Page three of a two-page document is a mistake, not an empty picture.
    assert preview(world, document, 3).status_code == 400

    picture = an_image_file(world)
    upright = preview(world, picture, 1)
    assert upright.status_code == 200, upright.text
    turned = preview(world, picture, 1, rotation_degrees=90)
    assert turned.status_code == 200, turned.text
    assert turned.content != upright.content, "rotation did not change the image"


def test_the_page_count_on_the_bundle_is_the_documents_own(world: dict[str, Any]) -> None:
    """`SVC-PREVIEW-001`'s other half, and the finding that made it worth writing.

    §16 asks that the page count match `bank_result_bundle_files.page_count`. Until this slice that
    column held whatever the caller sent, so the assertion would have compared the renderer against
    a number a client made up. It is now counted from the document, and a claim that disagrees is
    refused rather than quietly corrected — a caller describing four pages of a three-page file is
    referencing a different file than they mean.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    document = a_pdf_file(world)

    created = client.post(
        "/api/v1/bank-result-bundles",
        json={
            "source_type": "bank_portal_download",
            "files": [{"file_id": document, "sequence_number": 1, "file_role": "source"}],
        },
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert created.status_code == 201, created.text
    entry = created.json()["files"][0]

    assert entry["page_count"] == 2, "the count did not come from the document"
    assert entry["preview_path"] == f"/api/v1/files/{document}/pages/1/preview"

    # A claim that disagrees is refused.
    wrong = client.post(
        "/api/v1/bank-result-bundles",
        json={
            "source_type": "bank_portal_download",
            "files": [
                {
                    "file_id": a_pdf_file(world),
                    "sequence_number": 1,
                    "file_role": "source",
                    "page_count": 7,
                }
            ],
        },
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert wrong.status_code == 400, wrong.text
    assert "claiming 7 pages" in wrong.json()["error"]["message"]


def test_a_file_with_no_pages_offers_no_preview(world: dict[str, Any]) -> None:
    """The honest answer for most bank results, and information a client cannot compute.

    A CSV has no page. `preview_path` comes back `None` so the workspace can grey the file out
    instead of offering a link that refuses. A page count sent for it is refused too, because it
    is a claim nothing could ever check.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")

    created = client.post(
        "/api/v1/bank-result-bundles",
        json={
            "source_type": "bank_portal_download",
            "files": [
                {"file_id": a_spreadsheet_file(world), "sequence_number": 1, "file_role": "source"}
            ],
        },
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert created.status_code == 201, created.text
    entry = created.json()["files"][0]
    assert entry["page_count"] is None
    assert entry["preview_path"] is None

    refused = client.post(
        "/api/v1/bank-result-bundles",
        json={
            "source_type": "bank_portal_download",
            "files": [
                {
                    "file_id": a_spreadsheet_file(world),
                    "sequence_number": 1,
                    "file_role": "source",
                    "page_count": 3,
                }
            ],
        },
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert refused.status_code == 400, refused.text
    assert "no pages to count" in refused.json()["error"]["message"]


def test_a_preview_is_a_derived_file_and_never_the_original(world: dict[str, Any]) -> None:
    """`SVC-PREVIEW-002`, and it is a correction rather than a new rule.

    `GET /files/{id}/preview` served the *original bytes* from M4 until this slice, with a comment
    saying a later milestone would resolve it to a derivation. That made the preview permission act
    as a download permission — exactly the separation `05_API_Specification.md:1045` asks for.

    Asserted three ways, because "it is derived" has three separate meanings: the bytes differ from
    the source, a `file_derivations` row accounts for the output, and the derived row is marked
    `derived` rather than `original`.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    document = a_pdf_file(world)

    source_bytes = rows(
        world, "SELECT storage_key FROM file_objects WHERE id = %s", document
    )[0][0]
    original = (world["storage_root"] / source_bytes).read_bytes()

    response = client.get(f"/api/v1/files/{document}/preview")
    assert response.status_code == 200, response.text

    assert response.content != original, "the preview served the source file"
    assert response.content.startswith(b"\x89PNG"), "a preview of a PDF is a page image"

    derived = rows(
        world,
        "SELECT f.original_or_derived_relation, d.derivation_type, d.renderer_version "
        "FROM file_derivations d JOIN file_objects f ON f.id = d.derived_file_id "
        "WHERE d.source_file_id = %s",
        document,
    )
    assert len(derived) == 1, f"expected one preview derivation, found {len(derived)}"
    assert derived[0][0] == "derived"
    assert derived[0][1] == "preview"
    assert derived[0][2].startswith("pypdfium2/")


def test_the_second_request_for_a_page_renders_nothing_new(world: dict[str, Any]) -> None:
    """The cache, which is what makes rendering on demand affordable.

    Two requests for one page must leave **one** derivation. A second row would mean two stored
    images claiming to be the same page, and `file_derivations`' reproducibility unique exists to
    make that impossible — matched on `parameters_hash`, which is why the parameters are hashed
    rather than compared as JSONB.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    document = a_pdf_file(world)

    first = preview(world, document, 1)
    second = preview(world, document, 1)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.content == second.content, "the same page rendered differently twice"

    stored = rows(
        world,
        "SELECT count(*) FROM file_derivations WHERE source_file_id = %s AND derivation_type = "
        "'preview'",
        document,
    )
    assert stored == [(1,)]

    # A different rotation is a different derivation, not a cache hit on the same one.
    preview(world, document, 1, rotation_degrees=180)
    assert rows(
        world,
        "SELECT count(*) FROM file_derivations WHERE source_file_id = %s AND derivation_type = "
        "'preview'",
        document,
    ) == [(2,)]


def test_the_preview_returns_the_dimensions_a_client_cannot_invent(
    world: dict[str, Any],
) -> None:
    """`API-PREVIEW-001`. doc 05 `:1773` makes the client send `client_source_dimensions`.

    It has to get them from somewhere, and the crop route refuses a rectangle drawn against the
    wrong raster — so a client guessing here is a client whose crops are all rejected. The numbers
    swap on a quarter turn, which is why they come back per request rather than once per file.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    document = a_pdf_file(world)

    upright = preview(world, document, 1)
    assert upright.headers["X-Preview-Pixel-Width"] == "600"
    assert upright.headers["X-Preview-Pixel-Height"] == "800"
    assert upright.headers["X-Preview-Page-Number"] == "1"
    assert upright.headers["X-Preview-Rotation-Degrees"] == "0"
    assert upright.headers["X-Preview-Renderer-Version"].startswith("pypdfium2/")

    turned = preview(world, document, 1, rotation_degrees=90)
    assert turned.headers["X-Preview-Pixel-Width"] == "800"
    assert turned.headers["X-Preview-Pixel-Height"] == "600"

    # And the numbers describe the image actually returned, not a stored guess about it.
    from PIL import Image

    assert Image.open(io.BytesIO(turned.content)).size == (800, 600)


def test_a_preview_is_refused_without_the_bundle_permission(world: dict[str, Any]) -> None:
    """`SEC-PREVIEW-001`. doc 05 `:1045`: "A trader cannot preview an internal mixed bundle."

    **Two different refusals, and the difference is the point.** A trader holds no `file.preview` at
    all, so the route's permission gate stops them with a `403` before ownership is even consulted.
    A `warehouse_operator` *does* hold `file.preview` and not `file.read_sensitive_bundle`, so they
    get past the gate and must be refused by the ownership resolver, which answers `404`.

    The first version asserted `404` for the trader and was simply wrong about the code. Only the
    second actor tests the resolver; a test with the trader alone would have passed while
    `sensitive_internal_bundle` did nothing at all.

    **And no preview URL is guessable**, which is the requirement's other half: a refused page
    answers exactly as a page of a file that does not exist, in both directions. A `403` where a
    `404` belongs confirms the id is real, and the id is the only secret protecting an internal
    bundle.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    document = a_pdf_file(world)
    assert preview(world, document, 1).status_code == 200, "the control: an authorised read works"

    # Past the permission gate, refused by the resolver — and indistinguishable from not found.
    sign_in_admin(client, "segment_warehouse")
    refused = preview(world, document, 1)
    assert refused.status_code == 404, refused.text
    assert preview(world, str(uuid.uuid4()), 1).status_code == 404, (
        "a real file and an invented one answer differently, so the id space is enumerable"
    )
    assert client.get(f"/api/v1/files/{document}/preview").status_code == 404

    # Stopped at the gate, before ownership. Both ids answer alike here too, so nothing leaks.
    sign_in_trader(client)
    assert preview(world, document, 1).status_code == 403
    assert preview(world, str(uuid.uuid4()), 1).status_code == 403


# ---------------------------------------------------------------------------
# M8 slice 7: privacy review and the Definition of Done.
# ---------------------------------------------------------------------------


def resolve_privacy_task(world: dict[str, Any], segment_id: str, code: str = "no_action_required",
                         note: str | None = None) -> Any:
    """Find the segment's open privacy task and resolve it, as an operator would."""

    client = world["client"]
    task = rows(
        world,
        "SELECT id, record_version FROM manual_review_tasks WHERE entity_id = %s AND task_type = "
        "'segment_privacy_review' AND status IN ('open', 'in_progress')",
        segment_id,
    )
    assert len(task) == 1, f"expected one open privacy task, found {len(task)}"
    task_id, version = task[0]

    body: dict[str, Any] = {"resolution_code": code}
    if note is not None:
        body["resolution_note"] = note
    # Both headers. `05_API_Specification.md:2065` requires `If-Match` on every task transition —
    # two people working one queue is the normal case, not the edge case — and slice 3 made the
    # command idempotent too, so a retried resolve does not record a second decision.
    return client.post(
        f"/api/v1/manual-review-tasks/{task_id}/resolve",
        json=body,
        headers={
            **csrf(client),
            # `rv-<n>`, not a bare number: the ETag is an opaque token and the platform gave it a
            # shape so a client cannot accidentally send something else that happens to parse.
            "If-Match": f"rv-{version}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )


def test_a_crop_raises_a_privacy_task_nobody_has_to_remember(world: dict[str, Any]) -> None:
    """§16.5, attached at the moment the obligation arises.

    "Before evidence can be included in publication, the operator must verify that the crop does not
    reveal unrelated names, IBANs, amounts, tracking references, or transactions." A crop is when
    that obligation starts, so the task is raised there — not left for somebody to remember, and not
    invented at publication time when the person who drew the rectangle has moved on.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle_with_a_pdf(world)
    segment_id = request_a_crop(world, bundle).json()["segment"]["id"]

    task = rows(
        world,
        "SELECT task_type, status, priority, entity_type, entity_record_version "
        "FROM manual_review_tasks WHERE entity_id = %s",
        segment_id,
    )
    assert len(task) == 1
    assert task[0][0] == "segment_privacy_review"
    assert task[0][1] == "open"
    # Priority 3, not the quarantine path's 5: evidence waiting to be checked is ordinary work.
    assert task[0][2] == 3
    assert task[0][3] == "receipt_segment"
    # Nothing verified yet, so nothing claimed. The version arrives when a person resolves it.
    assert task[0][4] is None


def test_the_verification_records_who_when_and_which_version(world: dict[str, Any]) -> None:
    """`SVC-PRIVACY-001`. All four facts, and the fourth is the one that took a migration.

    A resolved task already carried actor, time and subject. `entity_record_version` is what makes
    the record *about a version* rather than about a segment in general — and that is the difference
    between a verification and a wish.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle_with_a_pdf(world)
    segment_id = request_a_crop(world, bundle).json()["segment"]["id"]

    before = rows(
        world, "SELECT record_version FROM receipt_segments WHERE id = %s", segment_id
    )[0][0]

    resolved = resolve_privacy_task(world, segment_id)
    assert resolved.status_code == 200, resolved.text

    record = rows(
        world,
        "SELECT resolved_by_admin_user_id, resolved_at, entity_id, entity_record_version, "
        "resolution_code FROM manual_review_tasks WHERE entity_id = %s",
        segment_id,
    )[0]
    assert record[0] is not None, "no actor recorded, so nobody is accountable for the check"
    assert record[1] is not None, "no time recorded"
    assert str(record[2]) == segment_id
    assert record[3] == before, "the version verified is not the version the segment had"
    assert record[4] == "no_action_required"

    detail = client.get(f"/api/v1/receipt-segments/{segment_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["privacy_verified"] is True
    assert detail.json()["privacy_verified_at"] is not None


def test_a_segment_changed_after_its_check_is_unverified_again(world: dict[str, Any]) -> None:
    """`SVC-PRIVACY-001`'s per-version half, and the reason it is a comparison and not a flag.

    The crop is verified, then rendered — which bumps `record_version` — and the verification stops
    applying with nothing to remember to reset. A stored boolean would still say `true`, and it
    would be attesting to an image nobody looked at.

    Rendering is the realistic way this happens: a queued crop verified before its worker ran.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle_with_a_pdf(world)
    segment_id = request_a_crop(world, bundle).json()["segment"]["id"]

    assert resolve_privacy_task(world, segment_id).status_code == 200
    assert client.get(f"/api/v1/receipt-segments/{segment_id}").json()["privacy_verified"] is True

    # The worker renders, `record_version` moves, and the check no longer describes this segment.
    drain(world)

    after = client.get(f"/api/v1/receipt-segments/{segment_id}").json()
    assert after["privacy_verified"] is False, (
        "a segment re-rendered after its privacy check still claims to be verified"
    )
    # And the task is still named, because "checked at version 1, now version 2" is a different
    # situation from "never checked" and an operator has to tell them apart.
    assert after["privacy_review_task_id"] is not None


def test_an_unresolved_disposition_verifies_nothing(world: dict[str, Any]) -> None:
    """The honest close must not be the dangerous one.

    `unresolved_with_reason` exists to close a task whose subject was *not* put right. Treating
    it as a pass would mean an operator who wrote "this crop shows another customer's IBAN" had
    thereby marked it publishable.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")
    bundle = a_bundle_with_a_pdf(world)
    segment_id = request_a_crop(world, bundle).json()["segment"]["id"]

    resolved = resolve_privacy_task(
        world,
        segment_id,
        code="unresolved_with_reason",
        note="the image includes a second transaction belonging to another customer",
    )
    assert resolved.status_code == 200, resolved.text

    detail = client.get(f"/api/v1/receipt-segments/{segment_id}").json()
    assert detail["privacy_verified"] is False
    assert detail["privacy_review_task_id"] is None, (
        "a task closed as unresolved is being offered as the segment's verification"
    )


def test_the_definition_of_done_as_one_journey(world: dict[str, Any]) -> None:
    """`TRACE-M8-002`. §16.7, in the order §16.7 puts it.

    "M8 is complete when an accountant can securely inspect a mixed bank bundle, create a
    reproducible internal rectangular crop, and continue the workflow without OCR or AI."

    **One test for the sequence, because nine steps proved separately can all pass while the
    sequence is impossible.** M5 slice 5 shipped exactly that: every command worked and no operator
    could get from the first to the last. So this walks the whole path through the API with one
    session, in order, and asserts at each step only what that step establishes.
    """

    client = world["client"]
    sign_in_admin(client, "segment_accountant")

    # 1. A mixed bundle: a document with pages beside a spreadsheet with none. "Mixed" is §16.7's
    #    word and this is what it means operationally — the bundle a bank actually sends.
    pdf = a_pdf_file(world)
    sheet = a_spreadsheet_file(world)
    created = client.post(
        "/api/v1/bank-result-bundles",
        json={
            "source_type": "bank_portal_download",
            "files": [
                {"file_id": pdf, "sequence_number": 1, "file_role": "source"},
                {"file_id": sheet, "sequence_number": 2, "file_role": "source"},
            ],
        },
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert created.status_code == 201, created.text
    bundle = created.json()
    assert bundle["status"] == "ready_for_manual_review", (
        "the bundle needs a permission that does not exist to reach review; slice 1's Q-7"
    )

    # 2. Inspect it: the page count came from the document, and the file with no pages says so.
    document = next(f for f in bundle["files"] if f["file_id"] == pdf)
    spreadsheet = next(f for f in bundle["files"] if f["file_id"] == sheet)
    assert document["page_count"] == 2
    assert document["preview_path"] is not None
    assert spreadsheet["page_count"] is None
    assert spreadsheet["preview_path"] is None, "a file with no pages must not offer a preview"

    # 3. Look at a page. This is the "securely" in §16.7 — the same route refuses a trader and an
    #    admin without the sensitive grant, asserted in this file's security tests.
    page = client.get(f"/api/v1/files/{pdf}/pages/2/preview")
    assert page.status_code == 200, page.text
    raster = (
        int(page.headers["X-Preview-Pixel-Width"]),
        int(page.headers["X-Preview-Pixel-Height"]),
    )

    # 4. Draw a rectangle on it and submit, using the raster the server just reported.
    accepted = client.post(
        f"/api/v1/bank-result-bundles/{bundle['id']}/receipt-segments/crop",
        json={
            "source_file_id": pdf,
            "bank_result_bundle_file_id": document["id"],
            "page_number": 2,
            "bbox": dict(A_RECTANGLE),
            "client_source_dimensions": {"width": raster[0], "height": raster[1]},
            "rotation_degrees": 0,
            "manual_fields": {"amount_irr": "2000000000", "tracking_number": "998877"},
        },
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert accepted.status_code == 202, accepted.text
    segment_id = accepted.json()["segment"]["id"]

    # 5. The worker renders it.
    drain(world)

    # 6. Reproducible: the stored row alone rebuilds the stored image, byte for byte.
    from app.exports.crop import Rectangle, render_crop

    stored = rows(
        world,
        "SELECT s.page_number, s.bbox_x, s.bbox_y, s.bbox_width, s.bbox_height, "
        "s.rotation_degrees, f.storage_key, src.storage_key "
        "FROM receipt_segments s JOIN file_objects f ON f.id = s.segment_file_id "
        "JOIN file_objects src ON src.id = s.source_file_id WHERE s.id = %s",
        segment_id,
    )
    assert len(stored) == 1, "the crop was not rendered, so there is nothing reproducible"
    page_no, x, y, w, h, rotation, crop_key, source_key = stored[0]
    again = render_crop(
        (world["storage_root"] / source_key).read_bytes(),
        page_number=page_no,
        rectangle=Rectangle(x=x, y=y, width=w, height=h),
        rotation_degrees=rotation,
    )
    assert again.content == (world["storage_root"] / crop_key).read_bytes()

    # 7. Continue the workflow: the privacy check §16.5 requires is in front of a person, and
    #    resolving it is what "continue" means at this stage — M9 reads the result.
    assert resolve_privacy_task(world, segment_id).status_code == 200
    assert client.get(f"/api/v1/receipt-segments/{segment_id}").json()["privacy_verified"] is True

    # 8. Without OCR or AI. Nothing in the journey touched either, and the segment says by which
    #    method it was made.
    method = rows(
        world, "SELECT creation_method FROM receipt_segments WHERE id = %s", segment_id
    )[0][0]
    assert method == "manual_in_panel_crop"

    # `TRACE-M8-003` asked for `ai_usage_logs` to be empty after this journey, and the stronger fact
    # is that **the table does not exist**. `04_Database_Schema.md:1381` specifies it and no
    # migration has built it, because nothing in Phase 1A uses a model — so there is no row to
    # count and no writer to have written one.
    #
    # Asserted as absence rather than emptiness on purpose: `SELECT count(*)` against a missing
    # table raises, and a test that caught that exception and called it success would pass equally
    # well if the table existed and the query were misspelled.
    present = rows(
        world,
        "SELECT count(*) FROM information_schema.tables WHERE table_name = %s",
        "ai_usage_logs",
    )
    assert present == [(0,)], (
        "ai_usage_logs now exists, so this assertion has to become the emptiness check "
        "TRACE-M8-003 originally described"
    )

    # 9. And the fallback stayed available throughout, which §16.6's last test asks for: the
    #    spreadsheet nothing can render is still workable as whole-file evidence.
    fallback = client.post(
        f"/api/v1/bank-result-bundles/{bundle['id']}/receipt-segments/external",
        json={"source_file_id": sheet, "bank_result_bundle_file_id": spreadsheet["id"]},
        headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert fallback.status_code == 201, fallback.text
    assert fallback.json()["creation_method"] == "manual_external_attachment"
