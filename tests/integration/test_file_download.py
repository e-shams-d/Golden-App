"""Every download is authorized again, against a real database.

Covers: SEC-FILEDL-001, SEC-FILEDL-002, SEC-FILEDL-004, SEC-FILEDL-005, SEC-FILEDL-006,
SEC-FILEDL-007, API-FILE-002, API-FILE-003.

The registry's own rules are unit-tested in `tests/backend/test_file_ownership.py`. What
needs a database and a route is here: that an unreachable file is indistinguishable from a
missing one, that revoking a session changes the answer between two identical requests,
and that the headers are on every file-bearing response rather than on the one somebody
remembered.

The scan policy is the development bypass throughout, because a file that cannot become
`available` cannot be downloaded by anyone and every authorization test would pass for the
wrong reason.
"""

from __future__ import annotations

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
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"
CSRF_HEADER = "X-CSRF-Token"

# The three seeded roles this file needs, chosen from the catalogue rather than assumed.
# The first draft used the accountant as the actor who cannot reach a bundle and the tests
# failed: `file.read_sensitive_bundle` is granted to `[accountant, manager]`, so the
# accountant reads bundles by design. Reading the catalogue is what picked these.
#
# accountant           file.upload, file.download, file.preview, file.read_metadata,
#                      file.read_sensitive_bundle
# warehouse_operator   the same minus file.read_sensitive_bundle — the actor a bundle
#                      denial is actually about
# manager              file.preview, file.read_metadata, file.read_sensitive_bundle, and
#                      file.download only as a policy grant, so not by default
ACCOUNTANT = "accountant1"
WAREHOUSE = "warehouse1"
MANAGER = "manager1"

# E.164, as `trader_users.phone_number` stores it. `09...` fails authentication with a
# generic "login information is not valid", which reads like a wrong password.
TRADER_PHONE = "+989120000001"

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415408d763f8cfc00000030101003c8b9c1e0000000049454e44ae426082"
)
ELF = b"\x7fELF\x02\x01\x01" + b"\x00" * 64


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
def world(migrated: RuntimeIdentities, tmp_path: Any) -> Iterator[dict[str, Any]]:
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
        file_scan_policy="development_bypass",
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    trader_id = uuid.uuid4()
    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        for username, role in (
            (ACCOUNTANT, "accountant"),
            (WAREHOUSE, "warehouse_operator"),
            (MANAGER, "manager"),
        ):
            row = connection.execute(
                "INSERT INTO admin_users (username, full_name, password_hash, status) "
                "VALUES (%s, %s, %s, 'active') RETURNING id",
                (username, username.title(), encoded),
            ).fetchone()
            assert row
            found = connection.execute(
                "SELECT id FROM roles WHERE code = %s", (role,)
            ).fetchone()
            assert found, f"migration 0008 should have seeded {role}"
            connection.execute(
                "INSERT INTO admin_user_roles (admin_user_id, role_id) VALUES (%s, %s)",
                (row[0], found[0]),
            )
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'Goldsmith', %s, 'active', 'approved')",
            (trader_id, TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Goldsmith Contact', %s, 'active', TRUE)",
            (trader_id, TRADER_PHONE, encoded),
        )
        connection.commit()

    runtime = RuntimeServices.from_settings(settings)
    app = create_app(settings=settings, runtime_factory=lambda _settings: runtime)
    app.state.accepting_traffic = True
    with (
        TestClient(app, base_url="https://admin.localhost") as admin_client,
        TestClient(app, base_url="https://trader.localhost") as trader_client,
    ):
        yield {
            "admin": admin_client,
            "trader": trader_client,
            "url": migrated.owner_url,
            "trader_id": trader_id,
        }
    runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def sign_in_admin(client: Any, username: str = ACCOUNTANT) -> str:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    token = client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token
    return token


def sign_in_trader(client: Any) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/trader/login", json={"identifier": TRADER_PHONE, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def upload(client: Any, token: str, *, purpose: str = "incoming_payment_receipt") -> str:
    response = client.post(
        "/api/v1/files",
        headers={CSRF_HEADER: token, "Idempotency-Key": str(uuid.uuid4())},
        files={"file": ("receipt.png", io.BytesIO(PNG), "image/png")},
        data={"purpose": purpose},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_an_unreachable_file_answers_exactly_like_a_missing_one(world: dict[str, Any]) -> None:
    """SEC-FILEDL-001. `15_Agent_Implementation_Plan.md:720`.

    A `403` would confirm the id is real, and the id is the only secret protecting a file
    whose owner nobody has checked yet. The two answers must be identical in status and
    body, not merely both refusals.
    """

    admin = world["admin"]
    token = sign_in_admin(admin, WAREHOUSE)
    # `misc_internal` resolves to `internal_only`, which staff may reach — so this file
    # exists and is reachable, and the comparison below is against ids that are not.
    upload(admin, token, purpose="misc_internal")

    invented = admin.get(f"/api/v1/files/{uuid.uuid4()}")
    assert invented.status_code == 404

    # A real row this actor may not reach: a bundle needs the sensitive grant, which the
    # warehouse operator does not hold.
    bundle_id = _insert_bundle(world["url"])
    unreachable = admin.get(f"/api/v1/files/{bundle_id}")

    assert unreachable.status_code == invented.status_code

    # Everything except `request_id`, which is per-request by design and is the one field
    # that must differ. Comparing whole bodies failed on exactly that.
    def comparable(response: Any) -> dict[str, Any]:
        body = response.json()["error"]
        return {key: value for key, value in body.items() if key != "request_id"}

    assert comparable(unreachable) == comparable(invented), (
        "an unreachable file answered differently from a missing one, which makes the id "
        "space enumerable"
    )


def _insert_bundle(url: str) -> str:
    """A stored, available bundle, written directly.

    Direct SQL because no route uploads a bundle yet — that is M8 — and the authorization
    rule for the category exists now and must be tested now.
    """

    file_id = uuid.uuid4()
    with psycopg.connect(_psycopg(url)) as connection:
        connection.execute(
            "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
            "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
            "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
            "original_or_derived_relation) VALUES (%s, 'local', 'private', %s, "
            "'bundle.pdf', 'application/pdf', 3, %s, 'bank_result_bundle_source', "
            "'internal_only', 'available', 'clean', 'system_maintenance', 'original')",
            (file_id, f"bank_result_bundle_source/2026/08/16/{uuid.uuid4().hex}", "c" * 64),
        )
        connection.commit()
    return str(file_id)


def test_a_trader_cannot_reach_an_internal_bank_bundle(world: dict[str, Any]) -> None:
    """SEC-FILEDL-002. `15_Agent_Implementation_Plan.md:721`.

    All three routes, because a metadata leak is a leak: knowing a bundle exists, its
    size and its filename is information about other traders' payments.
    """

    bundle_id = _insert_bundle(world["url"])
    trader = world["trader"]
    sign_in_trader(trader)

    for path in ("", "/download", "/preview"):
        response = trader.get(f"/api/v1/files/{bundle_id}{path}")
        assert response.status_code in (403, 404), (path, response.text)
        assert "bundle.pdf" not in response.text


def test_staff_without_the_sensitive_grant_cannot_reach_a_bundle_either(
    world: dict[str, Any],
) -> None:
    """The bundle rule is narrower than "staff only".

    Without this, SEC-FILEDL-002 would pass against a rule that merely excluded traders.
    The warehouse operator holds `file.download` and not `file.read_sensitive_bundle`,
    which is the combination the second grant exists for — and the accountant, who holds
    both, is asserted below to still get through, so this is a narrowing rather than a
    blanket refusal.
    """

    bundle_id = _insert_bundle(world["url"])
    admin = world["admin"]

    sign_in_admin(admin, WAREHOUSE)
    assert admin.get(f"/api/v1/files/{bundle_id}").status_code == 404
    assert admin.get(f"/api/v1/files/{bundle_id}/download").status_code == 404

    sign_in_admin(admin, ACCOUNTANT)
    assert admin.get(f"/api/v1/files/{bundle_id}").status_code == 200


def test_a_row_whose_object_is_missing_refuses_without_leaking_the_key(
    world: dict[str, Any],
) -> None:
    """The defect this file found rather than the one it set out to test.

    `_insert_bundle` writes a row and no object, which is exactly the state
    `records_without_a_storage_object` exists to detect. The download route opened the
    backend and let `StorageError` escape — an unhandled exception, and its message
    carries the storage key. An error page is still a way for a storage address to leave
    the file service, which is precisely the boundary M4's Definition of Done draws.

    It is now a refusal, logged server-side with the file id and category and nothing
    else.
    """

    bundle_id = _insert_bundle(world["url"])
    admin = world["admin"]
    sign_in_admin(admin, ACCOUNTANT)

    response = admin.get(f"/api/v1/files/{bundle_id}/download")
    assert response.status_code == 404, response.text
    assert "bank_result_bundle_source/" not in response.text
    assert "storage_key" not in response.text
    assert "/private/" not in response.text


def test_a_quarantined_file_is_not_downloadable_by_its_own_uploader(
    world: dict[str, Any],
) -> None:
    """SEC-FILEDL-004. `12_Security_RBAC_Audit.md:1468`.

    By its own uploader specifically: the point of quarantine is that nobody uses the
    content, not that only strangers are kept away.
    """

    admin = world["admin"]
    token = sign_in_admin(admin)

    # An executable declared as an image: inspection quarantines it even under the bypass.
    response = admin.post(
        "/api/v1/files",
        headers={CSRF_HEADER: token, "Idempotency-Key": str(uuid.uuid4())},
        files={"file": ("photo.png", io.BytesIO(ELF), "image/png")},
        data={"purpose": "misc_internal"},
    )
    assert response.status_code == 201
    file_id = response.json()["id"]
    assert response.json()["status"] == "quarantined"

    # Metadata is visible, so the uploader learns what happened...
    metadata = admin.get(f"/api/v1/files/{file_id}")
    assert metadata.status_code == 200
    assert metadata.json()["status"] == "quarantined"
    # ...and offers no action at all.
    assert metadata.json()["allowed_actions"] == []

    assert admin.get(f"/api/v1/files/{file_id}/download").status_code == 404
    assert admin.get(f"/api/v1/files/{file_id}/preview").status_code == 404


def test_a_trader_cannot_reach_another_traders_receipt(world: dict[str, Any]) -> None:
    """SEC-FILEDL-005.

    `incoming_payment_receipt` is `trader_visible_after_publication`, and M4 builds no
    publication — so a trader who did not upload it is refused. This is the test M9 must
    edit rather than add, which is the point of asserting a refusal now.
    """

    admin = world["admin"]
    token = sign_in_admin(admin)
    file_id = upload(admin, token, purpose="incoming_payment_receipt")

    trader = world["trader"]
    sign_in_trader(trader)
    assert trader.get(f"/api/v1/files/{file_id}").status_code in (403, 404)
    assert trader.get(f"/api/v1/files/{file_id}/download").status_code in (403, 404)


def test_revoking_the_session_changes_the_answer_between_two_identical_requests(
    world: dict[str, Any],
) -> None:
    """SEC-FILEDL-006. `12_Security_RBAC_Audit.md:1530`.

    "Re-evaluates every time" proved by changing the state rather than by reading the
    code. The same request, twice, with a revocation in between.
    """

    admin = world["admin"]
    token = sign_in_admin(admin)
    file_id = upload(admin, token, purpose="misc_internal")

    first = admin.get(f"/api/v1/files/{file_id}/download")
    assert first.status_code == 200, first.text

    with psycopg.connect(_psycopg(world["url"])) as connection:
        connection.execute(
            "UPDATE auth_sessions SET revoked_at = now(), revocation_reason = 'test' "
            "WHERE revoked_at IS NULL"
        )
        connection.commit()

    second = admin.get(f"/api/v1/files/{file_id}/download")
    assert second.status_code == 401, second.text


def test_preview_authority_is_not_inherited_from_download(world: dict[str, Any]) -> None:
    """SEC-FILEDL-007. `05_API_Specification.md:1045`.

    The manager holds `file.preview` and `file.read_metadata` and not `file.download`, so
    holding one grant must not confer the other. Asserted in the direction the catalogue
    actually supports.
    """

    admin = world["admin"]
    token = sign_in_admin(admin, ACCOUNTANT)
    file_id = upload(admin, token, purpose="misc_internal")

    sign_in_admin(admin, MANAGER)
    assert admin.get(f"/api/v1/files/{file_id}/preview").status_code == 200
    assert admin.get(f"/api/v1/files/{file_id}/download").status_code == 403

    metadata = admin.get(f"/api/v1/files/{file_id}")
    assert metadata.status_code == 200
    assert metadata.json()["allowed_actions"] == ["preview"]


def test_every_file_bearing_response_refuses_caching(world: dict[str, Any]) -> None:
    """API-FILE-002. `12_Security_RBAC_Audit.md:1555`.

    All three routes rather than one, because the header that is missing is always the one
    nobody wrote a test for.
    """

    admin = world["admin"]
    token = sign_in_admin(admin)
    file_id = upload(admin, token, purpose="misc_internal")

    for path in ("", "/download", "/preview"):
        response = admin.get(f"/api/v1/files/{file_id}{path}")
        assert response.status_code == 200, (path, response.text)
        assert response.headers["Cache-Control"] == "no-store", path
        assert response.headers["X-Content-Type-Options"] == "nosniff", path

    for path in ("/download", "/preview"):
        response = admin.get(f"/api/v1/files/{file_id}{path}")
        assert response.headers["Content-Disposition"].startswith("attachment;"), path


def test_metadata_carries_no_storage_address(world: dict[str, Any]) -> None:
    """API-FILE-003, against the response model's fields as well as the payload."""

    from app.api.v1.files import FileMetadataResponse

    forbidden = {"storage_key", "storage_bucket", "storage_provider"}
    assert forbidden.isdisjoint(FileMetadataResponse.model_fields)

    admin = world["admin"]
    token = sign_in_admin(admin)
    file_id = upload(admin, token, purpose="misc_internal")

    response = admin.get(f"/api/v1/files/{file_id}")
    assert response.status_code == 200
    for name in forbidden:
        assert name not in response.text
    assert "/private/" not in response.text


def test_the_downloaded_bytes_are_the_uploaded_bytes(world: dict[str, Any]) -> None:
    """Guard the guard for every authorization test above.

    All of them assert refusals or a 200. If the download route returned an empty body,
    each would still pass while the feature did nothing.
    """

    admin = world["admin"]
    token = sign_in_admin(admin)
    file_id = upload(admin, token, purpose="misc_internal")

    response = admin.get(f"/api/v1/files/{file_id}/download")
    assert response.status_code == 200
    assert response.content == PNG
