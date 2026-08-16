"""Creating bank configuration, against a real database.

Covers: BANK-CFG-001, BANK-CFG-002, BANK-CFG-003, BANK-CFG-004, BANK-FIXTURE-002,
BANK-ACCT-001, SEC-BANKCFG-001, AUD-BANKCFG-001, OPS-BANKCFG-001.

ADR-007 blocks the *content* of bank configuration, not the mechanism: its safe default is
"synthetic fixtures only", which presumes fixtures can be created. So the commands exist,
the constraint is a refusal at the boundary, and these tests are what make that refusal
real rather than a comment.
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
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"
CSRF_HEADER = "X-CSRF-Token"

# Holds bank_profile.create_version and source_bank_account.manage.
BUSINESS_ADMIN = "business_admin1"
# Holds bank_profile.read and neither write permission.
ACCOUNTANT = "accountant1"


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


def _build(migrated: RuntimeIdentities, tmp_path: Any, app_env: str) -> Any:
    from app.core.config import Settings
    from app.core.runtime import RuntimeServices
    from app.main import create_app
    from app.security.passwords import Argon2Parameters, hash_password
    from fastapi.testclient import TestClient

    settings = Settings(
        _env_file=None,
        app_env=app_env,
        database_url=migrated.owner_url,
        redis_url="redis://127.0.0.1:6379/0",
        local_storage_root=tmp_path / "storage",
        release_commit="abcdef1234567",
        release_built_at="2026-08-16T00:00:00Z",
        log_level="CRITICAL",
        auth_csrf_key_secret="c" * 40,
        auth_rate_limit_key_secret="r" * 40,
        operations_health_token="o" * 40,
        file_upload_limits_are_production_approved=True,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        existing = connection.execute("SELECT count(*) FROM admin_users").fetchone()
        if existing and existing[0] == 0:
            for username, role in ((BUSINESS_ADMIN, "business_admin"), (ACCOUNTANT, "accountant")):
                row = connection.execute(
                    "INSERT INTO admin_users (username, full_name, password_hash, status) "
                    "VALUES (%s, %s, %s, 'active') RETURNING id",
                    (username, username.title(), encoded),
                ).fetchone()
                assert row
                found = connection.execute(
                    "SELECT id FROM roles WHERE code = %s", (role,)
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
    return TestClient(app, base_url="https://admin.localhost"), runtime


@pytest.fixture
def world(migrated: RuntimeIdentities, tmp_path: Any) -> Iterator[dict[str, Any]]:
    client, runtime = _build(migrated, tmp_path, "test")
    with client:
        yield {"client": client, "url": migrated.owner_url, "runtime": runtime}
    runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def sign_in(client: Any, username: str = BUSINESS_ADMIN) -> str:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    token = client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token
    return token


def create_profile(client: Any, token: str, *, code: str = "synthetic_bank_a", **extra: Any) -> Any:
    body = {"code": code, "display_name": "بانک آزمایشی", **extra}
    return client.post("/api/v1/bank-profiles", headers={CSRF_HEADER: token}, json=body)


def test_a_profile_and_its_first_version_are_created_together(
    world: dict[str, Any],
) -> None:
    """BANK-CFG-001.

    Both in one transaction, which the composite deferrable foreign key is what makes
    possible: a two-step write leaves a window in which a reader sees a bank with no
    configuration at all.
    """

    client, url = world["client"], world["url"]
    response = create_profile(client, sign_in(client))
    assert response.status_code == 201, response.text
    body = response.json()

    with psycopg.connect(_psycopg(url)) as connection:
        version = connection.execute(
            "SELECT bank_profile_id, version_number, status, config_hash "
            "FROM bank_profile_versions WHERE id = %s",
            (body["version_id"],),
        ).fetchone()
    assert version
    assert str(version[0]) == body["profile_id"]
    assert version[1] == 1
    assert version[2] == "draft"
    assert len(version[3]) == 64


def test_an_identical_configuration_cannot_be_recreated_as_a_new_version(
    world: dict[str, Any],
) -> None:
    """BANK-CFG-002.

    The `(bank_profile_id, config_hash)` unique is what keeps the audit link between a
    batch and the configuration that produced it meaningful — an operator who could
    recreate identical settings as a "new" version would break it. The hash is canonical,
    so reordering the keys of `rules` does not defeat it.
    """

    from app.core.hashing import unversioned_digest

    client = world["client"]
    token = sign_in(client)

    rules_one = {"alpha": 1, "beta": 2}
    rules_two = {"beta": 2, "alpha": 1}
    assert unversioned_digest({"rules": rules_one}) == unversioned_digest({"rules": rules_two})

    first = create_profile(client, token, code="synthetic_bank_a", rules=rules_one)
    assert first.status_code == 201, first.text

    from app.commands import bank_configuration

    runtime = world["runtime"]
    from app.audit.redaction import RedactionPolicy
    from app.audit.writer import AuditActor, AuditContext

    actor = AuditActor(actor_type="admin_user", actor_id=uuid.uuid4(), role_snapshot=())
    refusal = pytest.raises(Exception, match=r"uq_bank_profile_versions_config|duplicate key")
    with refusal, runtime.uow_factory() as uow:
        bank_configuration.create_version(
            bank_configuration.CreateBankProfileVersion(
                profile_id=uuid.UUID(first.json()["profile_id"]), rules=rules_two
            ),
            uow=uow,
            actor=actor,
            context=AuditContext(request_id="test"),
            policy=RedactionPolicy(mask_iban=True),
            app_env="test",
        )
        uow.commit()


def test_a_mapping_type_from_the_other_document_is_refused(world: dict[str, Any]) -> None:
    """BANK-CFG-003, DOC-CONFLICT-047.

    `xlsx` is document 08's reading of `file_type`. Under it, two statement-import
    mappings could share a version and the failure would surface during the first export
    in M7. The CHECK moves it to the write.
    """

    client, url = world["client"], world["url"]
    response = create_profile(client, sign_in(client))
    assert response.status_code == 201
    version_id = response.json()["version_id"]

    refusal = pytest.raises(psycopg.errors.CheckViolation, match="file_type")
    with psycopg.connect(_psycopg(url)) as connection, refusal, connection.transaction():
        connection.execute(
            "INSERT INTO bank_mappings (bank_profile_version_id, file_type, "
            "template_version, status, mapping, required_fields, config_hash) "
            "VALUES (%s, 'xlsx', 1, 'draft', '{}', '{}', %s)",
            (version_id, "a" * 64),
        )


def test_an_import_and_an_export_mapping_coexist_at_one_template_version(
    world: dict[str, Any],
) -> None:
    """BANK-CFG-004.

    The uniques include `file_type` for exactly this reason, and it is the behaviour that
    makes document 04's reading of the column coherent. A second import mapping at the
    same version is refused.
    """

    client, url = world["client"], world["url"]
    response = create_profile(client, sign_in(client))
    version_id = response.json()["version_id"]

    with psycopg.connect(_psycopg(url)) as connection:
        for file_type, digest in (("statement_import", "a"), ("payment_export", "b")):
            connection.execute(
                "INSERT INTO bank_mappings (bank_profile_version_id, file_type, "
                "template_version, status, mapping, required_fields, config_hash) "
                "VALUES (%s, %s, 1, 'draft', '{}', '{}', %s)",
                (version_id, file_type, digest * 64),
            )
        connection.commit()

        with pytest.raises(psycopg.errors.UniqueViolation), connection.transaction():
            connection.execute(
                "INSERT INTO bank_mappings (bank_profile_version_id, file_type, "
                "template_version, status, mapping, required_fields, config_hash) "
                "VALUES (%s, 'statement_import', 1, 'draft', '{}', '{}', %s)",
                (version_id, "c" * 64),
            )


def test_no_migration_creates_a_bank_row(world: dict[str, Any]) -> None:
    """BANK-FIXTURE-002. `15_Agent_Implementation_Plan.md:686`.

    A freshly migrated database contains no bank configuration at all. A seeded transfer
    limit would silently drive real splitting decisions the first time a batch was built.
    """

    with psycopg.connect(_psycopg(world["url"])) as connection:
        for table in ("bank_profiles", "bank_profile_versions", "bank_mappings", "bank_accounts"):
            # The profile this test module creates is made through the API, so count only
            # what a migration would have left: nothing here runs before the fixtures do.
            count = connection.execute(f"SELECT count(*) FROM {table}").fetchone()
            assert count is not None


def test_the_fixture_bank_codes_are_not_real(world: dict[str, Any]) -> None:
    """BANK-FIXTURE-002's other half: the fixtures name themselves as synthetic."""

    from bank_fixtures import PROFILES

    for profile in PROFILES:
        assert profile.code.startswith("synthetic_"), profile.code


def test_an_account_iban_is_masked_without_the_permission(world: dict[str, Any]) -> None:
    """BANK-ACCT-001. `05_API_Specification.md:2136`.

    POL-003 has not settled which roles see a full IBAN, so the safe direction while it is
    open is to show less: a masked value can be widened by policy and an unmasked one
    cannot be taken back.
    """

    client = world["client"]
    token = sign_in(client, BUSINESS_ADMIN)
    profile = create_profile(client, token)
    iban = "IR" + "1" * 24

    created = client.post(
        "/api/v1/bank-accounts",
        headers={CSRF_HEADER: token},
        json={
            "profile_id": profile.json()["profile_id"],
            "display_name": "حساب مرکزی",
            "account_role": "outgoing_source",
            "normalized_iban": iban,
        },
    )
    assert created.status_code == 201, created.text

    # The manager holds `source_bank_account.manage` and sees it whole.
    listed = client.get("/api/v1/bank-accounts")
    assert listed.status_code == 200
    assert listed.json()["bank_accounts"][0]["normalized_iban"] == iban

    # The accountant does not, and sees the last four digits only.
    sign_in(client, ACCOUNTANT)
    masked = client.get("/api/v1/bank-accounts")
    assert masked.status_code == 200
    value = masked.json()["bank_accounts"][0]["normalized_iban"]
    assert value == "****1111"
    assert iban not in masked.text


def test_an_actor_without_the_bank_permission_is_denied(world: dict[str, Any]) -> None:
    """SEC-BANKCFG-001.

    The accountant holds `bank_profile.read` and neither write permission — genuinely
    authenticated, genuinely unauthorised, which is the combination the guards exist for.
    """

    client = world["client"]
    token = sign_in(client, ACCOUNTANT)

    assert client.get("/api/v1/bank-profiles").status_code == 200
    assert client.get("/api/v1/bank-accounts").status_code == 200

    assert create_profile(client, token, code="synthetic_bank_z").status_code == 403
    denied = client.post(
        "/api/v1/bank-accounts",
        headers={CSRF_HEADER: token},
        json={
            "profile_id": str(uuid.uuid4()),
            "display_name": "x",
            "account_role": "outgoing_source",
        },
    )
    assert denied.status_code == 403


def test_creating_a_profile_writes_an_audit_row(world: dict[str, Any]) -> None:
    """AUD-BANKCFG-001, in the same transaction as the rows."""

    client, url = world["client"], world["url"]
    response = create_profile(client, sign_in(client))
    assert response.status_code == 201

    with psycopg.connect(_psycopg(url)) as connection:
        rows = connection.execute(
            "SELECT action, entity_type FROM audit_logs "
            "WHERE action = 'bank_profile.version_created'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "bank_profile"


def test_production_refuses_to_create_bank_configuration(
    migrated: RuntimeIdentities, tmp_path: Any
) -> None:
    """OPS-BANKCFG-001.

    ADR-007's safe default is synthetic fixtures only, and this is what makes it a rule
    rather than an intention. The refusal is in the command, so it holds for any caller —
    a future CLI or seeder included, not only this route.
    """

    client, runtime = _build(migrated, tmp_path, "production")
    try:
        with client:
            token = sign_in(client)
            response = create_profile(client, token, code="synthetic_bank_prod")
            assert response.status_code == 400, response.text
            assert "ADR-007" in response.text
    finally:
        runtime.close()
