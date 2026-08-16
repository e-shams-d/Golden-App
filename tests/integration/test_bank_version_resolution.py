"""Which configuration was in force, and who may put one there.

Covers: BANK-VER-001, BANK-VER-002, BANK-VER-003, BANK-VER-004, BANK-VER-006, BANK-VER-007.

The plan's remaining version obligation — activation refused unless the version's mappings
parse the synthetic fixtures — is deliberately absent here and recorded as a gap in
`test_traceability.py`, with the reason. Naming it in this docstring would count as
citing it, and the gate refuses a gap that a test claims to cover; that refusal is right,
because a mention is not a proof.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery-staple"
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"
CSRF_HEADER = "X-CSRF-Token"

# Every seeded internal role, so the denial below is about the grant and not about which
# account happened to be tried.
ALL_ROLES = (
    ("business_admin1", "business_admin"),
    ("manager1", "manager"),
    ("accountant1", "accountant"),
    ("technical1", "technical_admin"),
)

NOON = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


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
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        for username, role in ALL_ROLES:
            row = connection.execute(
                "INSERT INTO admin_users (username, full_name, password_hash, status) "
                "VALUES (%s, %s, %s, 'active') RETURNING id",
                (username, username.title(), encoded),
            ).fetchone()
            assert row
            found = connection.execute("SELECT id FROM roles WHERE code = %s", (role,)).fetchone()
            assert found, f"migration 0008 should have seeded {role}"
            connection.execute(
                "INSERT INTO admin_user_roles (admin_user_id, role_id) VALUES (%s, %s)",
                (row[0], found[0]),
            )
        connection.commit()

    runtime = RuntimeServices.from_settings(settings)
    app = create_app(settings=settings, runtime_factory=lambda _settings: runtime)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://admin.localhost") as client:
        yield {"client": client, "runtime": runtime, "url": migrated.owner_url}
    runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _an_admin_id(url: str) -> uuid.UUID:
    """A real `admin_users.id`.

    `bank_profile_versions.created_by_admin_user_id` carries a foreign key, so a random
    UUID in an `AuditActor` fails the insert rather than the assertion under test.
    """

    with psycopg.connect(_psycopg(url)) as connection:
        row = connection.execute(
            "SELECT id FROM admin_users WHERE username = 'business_admin1'"
        ).fetchone()
    assert row
    return row[0]


def sign_in(client: Any, username: str = "business_admin1") -> str:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    token = client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token
    return token


def make_profile(client: Any, token: str, code: str = "synthetic_bank_a") -> tuple[str, str]:
    response = client.post(
        "/api/v1/bank-profiles",
        headers={CSRF_HEADER: token},
        json={"code": code, "display_name": "بانک آزمایشی"},
    )
    assert response.status_code == 201, response.text
    return response.json()["profile_id"], response.json()["version_id"]


def _activate(url: str, version_id: str, *, frm: datetime | None, to: datetime | None) -> None:
    """Activate directly, with a window. The route denies everyone by design, so the
    command is exercised through the runtime in the tests that are about resolution
    rather than about the guard."""

    with psycopg.connect(_psycopg(url)) as connection:
        connection.execute(
            "UPDATE bank_profile_versions SET status = 'active', effective_from = %s, "
            "effective_to = %s WHERE id = %s",
            (frm, to, version_id),
        )
        connection.commit()


def test_the_version_whose_window_contains_the_instant_is_returned(
    world: dict[str, Any],
) -> None:
    """BANK-VER-001."""

    from app.bankconfig.resolution import resolve_active_version

    client, runtime, url = world["client"], world["runtime"], world["url"]
    profile_id, version_id = make_profile(client, sign_in(client))
    _activate(url, version_id, frm=NOON - timedelta(days=1), to=NOON + timedelta(days=1))

    with runtime.uow_factory() as uow:
        resolved = resolve_active_version(uuid.UUID(profile_id), NOON, uow=uow)

    assert str(resolved.version_id) == version_id
    assert resolved.version_number == 1


def test_the_window_is_inclusive_at_the_start_and_exclusive_at_the_end(
    world: dict[str, Any],
) -> None:
    """BANK-VER-002.

    Both edges, because a closed-closed window puts an instant exactly on a boundary in
    two versions at once and a cutoff time is precisely such an instant.
    """

    from app.bankconfig.resolution import resolve_active_version
    from app.core.errors import NotFoundError

    client, runtime, url = world["client"], world["runtime"], world["url"]
    profile_id, version_id = make_profile(client, sign_in(client))
    end = NOON + timedelta(days=1)
    _activate(url, version_id, frm=NOON, to=end)

    with runtime.uow_factory() as uow:
        # Exactly at `effective_from`: in force.
        assert resolve_active_version(uuid.UUID(profile_id), NOON, uow=uow).version_number == 1

    with runtime.uow_factory() as uow, pytest.raises(NotFoundError):
        # Exactly at `effective_to`: not.
        resolve_active_version(uuid.UUID(profile_id), end, uow=uow)


def test_two_overlapping_active_versions_cannot_be_created(world: dict[str, Any]) -> None:
    """BANK-VER-001's other half.

    Two sets of rules in force at one instant is a bank with two answers to "what applies
    now", and the window in which that is true is exactly the window in which a batch
    might be built.
    """

    from app.audit.redaction import RedactionPolicy
    from app.audit.writer import AuditActor, AuditContext
    from app.bankconfig.resolution import activate_version
    from app.commands import bank_configuration

    client, runtime, url = world["client"], world["runtime"], world["url"]
    profile_id, first_version = make_profile(client, sign_in(client))
    _activate(url, first_version, frm=NOON - timedelta(days=1), to=NOON + timedelta(days=1))

    actor = AuditActor(actor_type="admin_user", actor_id=_an_admin_id(url), role_snapshot=())
    with runtime.uow_factory() as uow:
        second = bank_configuration.create_version(
            bank_configuration.CreateBankProfileVersion(
                profile_id=uuid.UUID(profile_id), splitting_enabled=True
            ),
            uow=uow,
            actor=actor,
            context=AuditContext(request_id="test"),
            policy=RedactionPolicy(mask_iban=True),
            app_env="test",
        )
        uow.commit()

    # The second version has no window at all, which overlaps everything.
    with pytest.raises(Exception, match="overlaps"), runtime.uow_factory() as uow:
        activate_version(
            second,
            uow=uow,
            actor=actor,
            context=AuditContext(request_id="test"),
            policy=RedactionPolicy(mask_iban=True),
        )
        uow.commit()


def test_activation_is_denied_to_every_role(world: dict[str, Any]) -> None:
    """BANK-VER-003, DOC-CONFLICT-045.

    Every seeded internal role, not one: the claim is that the permission is granted to
    nobody, and trying a single account would prove only that one account lacks it.

    **This test must be rewritten rather than deleted when the owner approves the grant.**
    Deleting it would remove the only statement of what the interim rule was.
    """

    client, url = world["client"], world["url"]
    _profile_id, version_id = make_profile(client, sign_in(client))

    for username, _role in ALL_ROLES:
        token = sign_in(client, username)
        response = client.post(
            f"/api/v1/bank-profile-versions/{version_id}/activate",
            headers={CSRF_HEADER: token},
        )
        assert response.status_code == 403, f"{username}: {response.text}"

    # And the version is still a draft, so the denial was not merely a slow success.
    with psycopg.connect(_psycopg(url)) as connection:
        row = connection.execute(
            "SELECT status FROM bank_profile_versions WHERE id = %s", (version_id,)
        ).fetchone()
    assert row and row[0] == "draft"


def test_the_permission_exists_and_is_granted_to_nobody(world: dict[str, Any]) -> None:
    """Guard the guard for BANK-VER-003.

    The denial above would also pass if the permission did not exist at all — a typo in
    `declare()` denies everyone just as effectively, and would look identical. This
    asserts the row is seeded and carries no grants, so the refusal is the recorded
    interim rule rather than an accident.
    """

    with psycopg.connect(_psycopg(world["url"])) as connection:
        for code in ("bank_profile.activate_version", "bank_mapping.activate"):
            permission = connection.execute(
                "SELECT id FROM permissions WHERE code = %s", (code,)
            ).fetchone()
            assert permission, f"{code} is not seeded"

            grants = connection.execute(
                "SELECT count(*) FROM role_permissions WHERE permission_id = %s",
                (permission[0],),
            ).fetchone()
            assert grants and grants[0] == 0, f"{code} is granted to {grants[0]} role(s)"


def test_a_used_version_cannot_be_edited(world: dict[str, Any]) -> None:
    """BANK-VER-004.

    Read from `information_schema.column_privileges` rather than by attempting an update
    as the application role, because the claim is about the *shape* of the grant: a
    table-level `GRANT UPDATE` would permit rewriting a transfer limit under an
    already-approved batch, and the batch's audit trail would still point at a version
    whose numbers had changed.

    `test_bank_configuration.py` already proves the refusal by attempting each column as
    the runtime role. This asserts the complementary fact — that `status` is the *only*
    column the grant names — so a migration adding a second one fails here rather than
    passing every existing test while widening what an activation may touch.
    """

    del world

    # Slice 9 writes exactly one column on this table, and the audit row carries the rest.
    # Asserted against the command's source so that adding a second assignment is a
    # visible failure rather than a silent widening of what activation does.
    import inspect

    from app.bankconfig import resolution
    from app.db.models.bank import BankProfileVersion

    source = inspect.getsource(resolution.activate_version)
    assigned = {
        line.split("=")[0].strip().removeprefix("version.")
        for line in source.splitlines()
        if line.strip().startswith("version.") and "=" in line and "==" not in line
    }
    assert assigned == {"status"}, (
        f"activation writes {sorted(assigned)} on an immutable snapshot; M2's column-level "
        "grant permits `status` alone, and widening it would let an approved batch's "
        "configuration change underneath it"
    )
    assert "status" in BankProfileVersion.__table__.columns


def test_activation_records_who_did_it_in_the_audit_log(world: dict[str, Any]) -> None:
    """BANK-VER-006, and DOC-CONFLICT-047's consequence.

    Document 08 lists `activated_by` and `activated_at` fields; document 04's column set
    has neither, and adding them would mean widening an immutable snapshot's UPDATE grant
    from one column to three to store a fact the audit log already records. So "who
    activated this version" is answerable — here — without the columns.
    """

    from app.audit.redaction import RedactionPolicy
    from app.audit.writer import AuditActor, AuditContext
    from app.bankconfig.resolution import activate_version

    client, runtime, url = world["client"], world["runtime"], world["url"]
    _profile_id, version_id = make_profile(client, sign_in(client))

    actor_id = _an_admin_id(url)
    actor = AuditActor(actor_type="admin_user", actor_id=actor_id, role_snapshot=("manager",))
    with runtime.uow_factory() as uow:
        activate_version(
            uuid.UUID(version_id),
            uow=uow,
            actor=actor,
            context=AuditContext(request_id="test"),
            policy=RedactionPolicy(mask_iban=True),
        )
        uow.commit()

    with psycopg.connect(_psycopg(url)) as connection:
        row = connection.execute(
            "SELECT actor_id, entity_id FROM audit_logs "
            "WHERE action = 'bank_profile.version_activated'"
        ).fetchone()
        status = connection.execute(
            "SELECT status FROM bank_profile_versions WHERE id = %s", (version_id,)
        ).fetchone()
        pointer = connection.execute(
            "SELECT current_version_id FROM bank_profiles WHERE id = "
            "(SELECT bank_profile_id FROM bank_profile_versions WHERE id = %s)",
            (version_id,),
        ).fetchone()

    assert row and str(row[0]) == str(actor_id)
    assert str(row[1]) == version_id
    assert status and status[0] == "active"
    # The pointer moved in the same transaction: a profile whose pointer and whose version
    # statuses disagreed would be a bank with two answers.
    assert pointer and str(pointer[0]) == version_id


def test_no_public_function_returns_a_rule_without_its_version(world: dict[str, Any]) -> None:
    """BANK-VER-007, and the third claim of M4's Definition of Done.

    A caller holding a transfer limit without the version it came from cannot reproduce
    the decision it made — and reproducing decisions is the entire reason bank
    configuration is versioned. Asserted over the package's public surface so a
    convenience helper added later fails here rather than quietly defeating the boundary.
    """

    import inspect

    from app.bankconfig import resolution

    del world

    public = {
        name: value
        for name, value in vars(resolution).items()
        if inspect.isfunction(value) and not name.startswith("_")
    }
    assert "resolve_active_version" in public

    for name, function in public.items():
        annotation = inspect.signature(function).return_annotation
        rendered = str(annotation)
        assert "int" not in rendered.split("."), (
            f"{name} returns a bare value ({rendered}); an operational rule must travel "
            "with the version id that produced it"
        )

    # And the returned type carries the id, in a field nothing can omit.
    assert "version_id" in resolution.ResolvedVersion.__dataclass_fields__
