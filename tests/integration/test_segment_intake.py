"""Evidence attached, and the constraints that decide what a segment may claim.

M8 slice 2. `DB-SEGMENT-001` lives here because a CHECK can only be shown to refuse by asking
PostgreSQL to refuse — a model's constraint list proves the text exists, not that the database
enforces it.

The edges tested are the ones §12.4's CHECK actually turns on: all-null, a zero width, a rectangle
that runs past the right edge, and the two constraints document 04 does not state — a rectangle
without its page and a rotation without a rectangle.

Covers: DB-SEGMENT-001, SVC-SEGMENT-003, SEC-SEGMENT-001.
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


def a_clean_file(world: dict[str, Any], name: str = "receipt.pdf") -> str:
    file_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
            "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
            "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
            "original_or_derived_relation, metadata) "
            "VALUES (%s, 'local', 'gold', %s, %s, 'application/pdf', 2048, %s, "
            "'bank_result_bundle', 'internal', 'available', 'clean', 'admin_user', "
            "'original', '{}')",
            (file_id, f"segments/{file_id}", name, f"{uuid.uuid4().hex}{uuid.uuid4().hex}"[:64]),
        )
        connection.commit()
    return str(file_id)


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
