"""What happens to an uploaded file that is not what it claims to be.

Covers: FILE-VAL-001, FILE-VAL-002, FILE-VAL-003, FILE-VAL-004, SEC-FILEUP-001.

The decision function is unit-tested in `tests/backend/test_file_inspection.py`. This file
asserts the consequences: which outcomes keep a row, which keep the bytes, and which never
reach storage at all. Those are claims about the route and the database, and they are the
half that a unit test of the detector cannot make.

Rejection and quarantine are deliberately different, and the difference is the subject
here. A malformed request is refused before anything is stored, because there is nothing
worth keeping. Bytes that were stored and then found to be something other than claimed
are kept, because that is evidence about whoever uploaded them and deleting it destroys
the only record that it happened.
"""

from __future__ import annotations

import io
import uuid
import zipfile
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
PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
ELF_BYTES = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 64


def xlsx_bytes(*, content_types: bool = True) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if content_types:
            archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
    return buffer.getvalue()


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


@pytest.fixture
def client(migrated: RuntimeIdentities, tmp_path: Any) -> Iterator[tuple[Any, Any]]:
    from app.core.config import Settings
    from app.core.runtime import RuntimeServices
    from app.main import create_app
    from app.security.passwords import Argon2Parameters, hash_password
    from fastapi.testclient import TestClient

    storage_root = tmp_path / "storage"
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=migrated.owner_url,
        redis_url="redis://127.0.0.1:6379/0",
        local_storage_root=storage_root,
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="c" * 40,
        auth_rate_limit_key_secret=None,
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
        found = connection.execute(
            "SELECT id FROM roles WHERE code = 'accountant'"
        ).fetchone()
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
        yield test_client, storage_root
    runtime.close()


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


def _upload(
    client: Any,
    token: str,
    *,
    content: bytes,
    media_type: str,
    purpose: str = "incoming_payment_receipt",
    filename: str = "evidence",
) -> Any:
    return client.post(
        "/api/v1/files",
        headers={CSRF_HEADER: token, "Idempotency-Key": str(uuid.uuid4())},
        files={"file": (filename, io.BytesIO(content), media_type)},
        data={"purpose": purpose},
    )


def _row(url: str, file_id: str) -> tuple[Any, ...]:
    with psycopg.connect(_psycopg(url)) as connection:
        row = connection.execute(
            # The mapped attribute is `metadata_payload`; the column it maps to is
            # `metadata`. SQL reads the column.
            "SELECT mime_type_declared, mime_type_detected, storage_status, "
            "metadata::text FROM file_objects WHERE id = %s",
            (file_id,),
        ).fetchone()
    assert row
    return row


def test_a_png_declared_as_a_pdf_is_quarantined_with_both_types_recorded(
    client: tuple[Any, Any], migrated: RuntimeIdentities
) -> None:
    """FILE-VAL-001.

    The declared and detected types are both kept. Reconciling them into one value would
    erase the fact that they disagreed, which is the fact worth having.
    """

    test_client, _ = client
    token = sign_in(test_client)

    response = _upload(
        test_client, token, content=PNG_BYTES, media_type="application/pdf",
        filename="receipt.pdf",
    )
    assert response.status_code == 201, response.text

    declared, detected, status, metadata = _row(migrated.owner_url, response.json()["id"])
    assert declared == "application/pdf"
    assert detected == "image/png"
    assert status == "quarantined"
    assert "declared_and_detected_type_disagree" in metadata


def test_an_executable_is_refused_even_with_an_accepted_extension(
    client: tuple[Any, Any], migrated: RuntimeIdentities
) -> None:
    """FILE-VAL-002. `15_Agent_Implementation_Plan.md:719`.

    The extension and the declared type are both acceptable; the bytes are an ELF binary.
    The reason recorded is the executable one rather than the mismatch, because "someone
    uploaded a binary" and "wrong type" warrant different attention.
    """

    test_client, _ = client
    token = sign_in(test_client)

    response = _upload(
        test_client, token, content=ELF_BYTES, media_type="image/png", filename="photo.png"
    )
    assert response.status_code == 201, response.text

    _, detected, status, metadata = _row(migrated.owner_url, response.json()["id"])
    assert detected == "application/x-executable"
    assert status == "quarantined"
    assert "executable_content" in metadata


def test_a_structurally_broken_spreadsheet_is_quarantined(
    client: tuple[Any, Any], migrated: RuntimeIdentities
) -> None:
    """FILE-VAL-003.

    The signature is a valid ZIP and the declared type is right; the archive has no
    `[Content_Types].xml`, so it is not a spreadsheet anything can open. A statement that
    cannot be read must fail here rather than inside M8's import.
    """

    test_client, _ = client
    token = sign_in(test_client)

    response = _upload(
        test_client,
        token,
        content=xlsx_bytes(content_types=False),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        purpose="bank_statement",
        filename="statement.xlsx",
    )
    assert response.status_code == 201, response.text

    _, detected, status, metadata = _row(migrated.owner_url, response.json()["id"])
    assert status == "quarantined"
    assert "structurally_unreadable" in metadata
    # The signature was a genuine ZIP, so detection succeeded and the file still failed.
    # Worth asserting rather than discarding: it distinguishes "we could not tell what
    # this was" from "we knew what it was and it was broken", which are different
    # findings for whoever reviews the quarantine.
    assert detected == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_a_readable_spreadsheet_is_not_quarantined_for_structure(
    client: tuple[Any, Any], migrated: RuntimeIdentities
) -> None:
    """The other direction, and the one that keeps the structural check honest: a gate
    that failed everything would pass the test above while making uploads impossible."""

    test_client, _ = client
    token = sign_in(test_client)

    response = _upload(
        test_client,
        token,
        content=xlsx_bytes(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        purpose="bank_statement",
        filename="statement.xlsx",
    )
    assert response.status_code == 201, response.text

    _, detected, status, metadata = _row(migrated.owner_url, response.json()["id"])
    assert detected == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "structurally_unreadable" not in metadata
    assert "quarantine_reason" not in metadata
    # Still quarantined, and for a different reason entirely: no scanner exists until
    # slice 4. Asserted here so that when the scan policy lands and this becomes
    # `available`, the change is a visible edit to a stated expectation rather than a
    # silent widening nobody notices.
    assert status == "quarantined"


def test_a_quarantined_file_keeps_its_bytes_and_its_row(
    client: tuple[Any, Any], migrated: RuntimeIdentities
) -> None:
    """FILE-VAL-004.

    Nothing in the validation path calls a delete. The file is evidence about whoever
    uploaded it, and `12_Security_RBAC_Audit.md:1571` refuses automatic deletion of
    evidence for the same reason one milestone later.
    """

    test_client, storage_root = client
    token = sign_in(test_client)

    response = _upload(
        test_client, token, content=ELF_BYTES, media_type="image/png", filename="photo.png"
    )
    assert response.status_code == 201, response.text

    stored = [path for path in storage_root.rglob("*") if path.is_file()]
    assert len(stored) == 1
    assert stored[0].read_bytes() == ELF_BYTES

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        count = connection.execute("SELECT count(*) FROM file_objects").fetchone()
    assert count and count[0] == 1


def test_a_declared_type_the_purpose_refuses_never_reaches_storage(
    client: tuple[Any, Any], migrated: RuntimeIdentities
) -> None:
    """SEC-FILEUP-001, and the rejection half of the distinction.

    A malformed request is refused before a byte is written — there is nothing worth
    keeping, and storing it would create an object the reconciliation checks would then
    have to explain.
    """

    test_client, storage_root = client
    token = sign_in(test_client)

    response = _upload(
        test_client,
        token,
        content=PNG_BYTES,
        media_type="image/png",
        purpose="bank_statement",
        filename="not-a-statement.png",
    )
    assert response.status_code == 400, response.text

    assert [path for path in storage_root.rglob("*") if path.is_file()] == []
    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        count = connection.execute("SELECT count(*) FROM file_objects").fetchone()
    assert count and count[0] == 0


def test_the_outcome_follows_the_bytes_not_the_name(
    client: tuple[Any, Any], migrated: RuntimeIdentities
) -> None:
    """FILE-VAL-005 at the route.

    The same PNG twice, once named `.png` and once named `.pdf`, both declared as PNG.
    Identical outcomes, because the name is metadata and the bytes are the fact. This is
    the property that makes extension-based acceptance impossible to reintroduce quietly.
    """

    test_client, _ = client
    token = sign_in(test_client)

    honest = _upload(
        test_client, token, content=PNG_BYTES, media_type="image/png", filename="a.png"
    )
    misnamed = _upload(
        test_client, token, content=PNG_BYTES, media_type="image/png", filename="a.pdf"
    )
    assert honest.status_code == 201 and misnamed.status_code == 201

    first = _row(migrated.owner_url, honest.json()["id"])
    second = _row(migrated.owner_url, misnamed.json()["id"])
    assert first[1:] == second[1:], "the filename changed the outcome"
