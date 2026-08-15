"""What the scan policy does to a real upload, and what the database does regardless.

Covers: FILE-SCAN-001, FILE-SCAN-003, FILE-LIFE-001.

Two of these prove the same rule from opposite sides, and the separation is the point. The
application decides not to write `available` without a clean scan; the database refuses it
independently. A test that only exercised the command could not tell which of the two was
holding — so one goes through the route and one goes around it with direct SQL.
"""

from __future__ import annotations

import io
import re
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery-staple"
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"
CSRF_HEADER = "X-CSRF-Token"
UPLOADER = "accountant1"

PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415408d763f8cfc00000030101003c8b9c1e0000000049454e44ae426082"
)
ELF_BYTES = b"\x7fELF\x02\x01\x01" + b"\x00" * 64


@pytest.fixture
def migrated(provisioned_database: RuntimeIdentities) -> RuntimeIdentities:
    result = run_alembic(
        provisioned_database.migrator_url,
        "upgrade",
        "head",
        app_role=provisioned_database.app_role,
        worker_role=provisioned_database.worker_role,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return provisioned_database


def _build_client(migrated: RuntimeIdentities, tmp_path: Any, policy: str) -> Iterator[Any]:
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
        local_storage_root=tmp_path / "storage",
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="c" * 40,
        auth_rate_limit_key_secret=None,
        file_scan_policy=policy,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        row = connection.execute(
            "INSERT INTO admin_users (username, full_name, password_hash, status) "
            "VALUES (%s, %s, %s, 'active') RETURNING id",
            (UPLOADER, UPLOADER.title(), encoded),
        ).fetchone()
        assert row
        found = connection.execute("SELECT id FROM roles WHERE code = 'accountant'").fetchone()
        assert found
        connection.execute(
            "INSERT INTO admin_user_roles (admin_user_id, role_id) VALUES (%s, %s)",
            (row[0], found[0]),
        )
        connection.commit()

    runtime = RuntimeServices.from_settings(settings)
    app = create_app(settings=settings, runtime_factory=lambda _settings: runtime)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://admin.localhost") as test_client:
        yield test_client
    runtime.close()


@pytest.fixture
def unscanned_client(migrated: RuntimeIdentities, tmp_path: Any) -> Iterator[Any]:
    """The production default: no scanner configured."""

    yield from _build_client(migrated, tmp_path, "none")


@pytest.fixture
def bypass_client(migrated: RuntimeIdentities, tmp_path: Any) -> Iterator[Any]:
    """The development bypass, which reports every file clean."""

    yield from _build_client(migrated, tmp_path, "development_bypass")


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def sign_in(client: Any) -> str:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": UPLOADER, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    token = client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token
    return token


def _upload(client: Any, token: str) -> Any:
    return client.post(
        "/api/v1/files",
        headers={CSRF_HEADER: token, "Idempotency-Key": str(uuid.uuid4())},
        files={"file": ("receipt.png", io.BytesIO(PNG_BYTES), "image/png")},
        data={"purpose": "incoming_payment_receipt"},
    )


def _states(url: str, file_id: str) -> tuple[str, str]:
    with psycopg.connect(_psycopg(url)) as connection:
        row = connection.execute(
            "SELECT storage_status, scan_status FROM file_objects WHERE id = %s",
            (file_id,),
        ).fetchone()
    assert row
    return row[0], row[1]


def test_with_no_scanner_a_perfect_upload_is_quarantined(
    unscanned_client: Any, migrated: RuntimeIdentities
) -> None:
    """FILE-SCAN-001.

    Nothing is wrong with this file: the purpose accepts it, the signature matches the
    declaration, the structure is fine. It is quarantined solely because nothing scanned
    it, which is ADR-008's safe default arriving as an outcome rather than a promise.
    """

    token = sign_in(unscanned_client)
    response = _upload(unscanned_client, token)
    assert response.status_code == 201, response.text

    storage_status, scan_status = _states(migrated.owner_url, response.json()["id"])
    assert storage_status == "quarantined"
    assert scan_status == "pending"
    assert response.json()["status"] == "quarantined"


def test_with_the_bypass_the_same_upload_becomes_available(
    bypass_client: Any, migrated: RuntimeIdentities
) -> None:
    """The other direction, and what keeps the test above meaningful.

    Without this, "quarantined" could be the only outcome the code can produce, and
    FILE-SCAN-001 would pass against an upload path that never works at all.
    """

    token = sign_in(bypass_client)
    response = _upload(bypass_client, token)
    assert response.status_code == 201, response.text

    storage_status, scan_status = _states(migrated.owner_url, response.json()["id"])
    assert storage_status == "available"
    assert scan_status == "clean"
    assert response.json()["status"] == "available"


def test_a_failed_inspection_stays_quarantined_even_under_the_bypass(
    bypass_client: Any, migrated: RuntimeIdentities
) -> None:
    """Both conditions are required, not either.

    The bypass reports clean; the content is an executable declared as an image. A file
    that satisfied one condition and not the other must not become available, and with a
    permissive scanner this is the only test that says so.

    Two independent guards hold it: the command never hands a failed inspection to the
    scanner, and availability requires `finding.is_acceptable` as well as a clean scan.
    The negative control has to remove **both** before this fails, which is what defence
    in depth looks like from the outside — worth recording, because a control that
    removed one and saw nothing happen would otherwise read as a test proving nothing.
    """

    token = sign_in(bypass_client)
    response = bypass_client.post(
        "/api/v1/files",
        headers={CSRF_HEADER: token, "Idempotency-Key": str(uuid.uuid4())},
        files={
            "file": ("photo.png", io.BytesIO(ELF_BYTES), "image/png"),
        },
        data={"purpose": "incoming_payment_receipt"},
    )
    assert response.status_code == 201, response.text

    storage_status, scan_status = _states(migrated.owner_url, response.json()["id"])
    assert storage_status == "quarantined"
    # Not scanned at all: a file already refused by inspection is not worth a scanner call.
    assert scan_status == "pending"


def test_the_database_refuses_available_without_a_clean_scan(
    migrated: RuntimeIdentities,
) -> None:
    """FILE-SCAN-003.

    Direct SQL, bypassing the application entirely. The command's own guard and the
    constraint are proved separately on purpose: a test that only went through the route
    could not tell which of the two was holding, and the constraint is the one that still
    holds when a future code path forgets.
    """

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        for scan_status in ("pending", "suspicious", "failed", "skipped_by_approved_policy"):
            refusal = pytest.raises(
                psycopg.errors.CheckViolation, match="available_requires_clean_scan"
            )
            with refusal, connection.transaction():
                    connection.execute(
                        "INSERT INTO file_objects (storage_provider, storage_bucket, "
                        "storage_key, original_filename, mime_type_declared, size_bytes, "
                        "sha256_hash, category, visibility_scope, storage_status, "
                        "scan_status, uploaded_by_actor_type, original_or_derived_relation) "
                        "VALUES ('local', 'private', %s, 'x.png', 'image/png', 3, %s, "
                        "'misc_internal', 'internal_only', 'available', %s, "
                        "'system_maintenance', 'original')",
                        (f"misc_internal/2026/08/16/{uuid.uuid4().hex}", "a" * 64, scan_status),
                    )

        # And the one value that is permitted, so the constraint is a whitelist rather
        # than a refusal of everything.
        with connection.transaction():
            connection.execute(
                "INSERT INTO file_objects (storage_provider, storage_bucket, storage_key, "
                "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
                "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
                "original_or_derived_relation) "
                "VALUES ('local', 'private', %s, 'x.png', 'image/png', 3, %s, "
                "'misc_internal', 'internal_only', 'available', 'clean', "
                "'system_maintenance', 'original')",
                (f"misc_internal/2026/08/16/{uuid.uuid4().hex}", "b" * 64),
            )


def test_the_python_state_tuple_equals_the_database_check(
    migrated: RuntimeIdentities,
) -> None:
    """FILE-LIFE-001.

    Read from `information_schema` rather than restated here, so a state added to one side
    and not the other fails. DOC-CONFLICT-036 approved seven values; `deleted_by_policy`
    is refused because its only writer would be the policy-driven deletion ADR-005 blocks
    from existing.
    """

    from app.files.states import STORAGE_STATUSES

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        row = connection.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ck_file_objects_storage_status'"
        ).fetchone()
    assert row, "the storage_status CHECK is missing"

    in_database = set(re.findall(r"'([a-z_]+)'::", row[0]))
    assert in_database == set(STORAGE_STATUSES), (
        f"the CHECK admits {sorted(in_database)} and the Python tuple lists "
        f"{sorted(STORAGE_STATUSES)}"
    )
    assert "deleted_by_policy" not in in_database
