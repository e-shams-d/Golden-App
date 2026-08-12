"""The platform creating its own first staff account, against a real database.

Before this existed, a fresh deployment could accept a public trader registration and
then never act on it: approval needs `trader.approve`, permissions resolve only through
`admin_user_roles`, and no code in the repository constructed an `AdminUser` or an
`AdminUserRole`. The only creation path anywhere was raw SQL inside test fixtures.

The tests drive `main()` rather than `bootstrap()` wherever they can. That is the
difference between proving the function works and proving *the command* works: argument
parsing, the settings load, the session factory and the commit are all places this can
fail in a deployment and nowhere else.

Covers: SEED-ACCT-002.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from io import StringIO
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

PASSWORD = "a-long-install-time-password"
USERNAME = "installer1"
# The only seeded role holding `user.create`, which is what the command requires
# before it will grant anything — see the test that asserts the refusal.
BOOTSTRAP_ROLE = "business_admin"


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
def invoke(migrated: RuntimeIdentities, tmp_path: Any, monkeypatch: Any) -> Iterator[Any]:
    """Run the real command against the migrated database, deterministically.

    `Settings` is configured with `env_file=".env"` (`app/core/config.py:32`), so a run
    from the repository root would read the developer's private file — present locally,
    absent in CI, which is precisely the shape of difference that makes a test lie in
    one environment. Changing directory first means the only configuration is what this
    fixture sets.
    """

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", migrated.owner_url)
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("RELEASE_COMMIT", "abcdef1234567")
    monkeypatch.setenv("LOG_LEVEL", "CRITICAL")

    from app.cli.create_first_admin import main

    def run(
        *,
        username: str = USERNAME,
        role: str = BOOTSTRAP_ROLE,
        password: str = PASSWORD,
    ) -> int:
        return main(
            ["--username", username, "--full-name", "Installer Person", "--role", role],
            secret_stream=StringIO(password + "\n"),
        )

    yield run


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _counts(migrated: RuntimeIdentities) -> tuple[int, int, int]:
    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        admins = connection.execute("SELECT count(*) FROM admin_users").fetchone()
        grants = connection.execute("SELECT count(*) FROM admin_user_roles").fetchone()
        audits = connection.execute(
            "SELECT count(*) FROM audit_logs WHERE action = 'admin_user.bootstrapped'"
        ).fetchone()
    assert admins and grants and audits
    return (admins[0], grants[0], audits[0])


def test_a_fresh_deployment_has_no_staff_at_all(migrated: RuntimeIdentities) -> None:
    """The precondition, asserted rather than assumed.

    Every claim below is about a transition from zero. Without this, "one admin exists
    afterwards" describes an unknown starting point — and the migrations could seed one
    tomorrow without a single test noticing that this file had stopped testing a
    bootstrap.
    """

    assert _counts(migrated) == (0, 0, 0), (
        "a migrated database already contains staff, so either a migration seeded an "
        "identity — which SEED-ACCT-001 forbids — or this file is no longer testing a "
        "bootstrap"
    )


def test_the_command_creates_the_account_its_grant_and_its_audit_row(
    invoke: Any, migrated: RuntimeIdentities, capsys: Any
) -> None:
    """SEED-ACCT-002. One account, one grant, one audit row, one transaction."""

    assert _counts(migrated) == (0, 0, 0)

    assert invoke() == 0

    assert _counts(migrated) == (1, 1, 1), (
        "the command must create the identity, the role grant and the audit record "
        "together; an account without a grant cannot act, and a grant without an audit "
        "row is the most privileged act in the system's life going unrecorded"
    )

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        row = connection.execute(
            "SELECT username, status, password_hash, security_stamp_version FROM admin_users"
        ).fetchone()
        grant = connection.execute(
            "SELECT granted_by_admin_id, revoked_at FROM admin_user_roles"
        ).fetchone()
        audit = connection.execute(
            "SELECT actor_type, actor_id, outcome, entity_type, new_values FROM audit_logs "
            "WHERE action = 'admin_user.bootstrapped'"
        ).fetchone()
    assert row and grant and audit

    username, status, password_hash, stamp = row
    assert username == USERNAME
    assert status == "active", (
        "created as recovery_required, which refuses authentication while no code "
        "invokes AccountAction.RECOVER and no change-password route exists — a "
        "correctly-provisioned account nobody can ever use"
    )
    assert password_hash.startswith("$argon2"), "the password must be stored hashed"
    assert PASSWORD not in password_hash
    assert stamp == 1

    granted_by, revoked_at = grant
    assert granted_by is None, (
        "naming the new account as its own grantor would read, to anyone auditing "
        "later, as a self-elevation performed through the API"
    )
    assert revoked_at is None

    actor_type, actor_id, outcome, entity_type, new_values = audit
    assert (actor_type, actor_id) == ("system_maintenance", None), (
        "there is no human to attribute this to, and inventing one would make the row "
        "indistinguishable from a real attributed action"
    )
    assert outcome == "success"
    assert entity_type == "admin_user"
    assert new_values["role"] == BOOTSTRAP_ROLE


def test_the_bootstrapped_account_can_actually_do_the_job(
    invoke: Any, migrated: RuntimeIdentities
) -> None:
    """The half that makes the row worth inserting.

    `18_Production_Setup_and_Runbook.md:1105` says not to grant financial authority to
    the installer by default, so this asserts both directions: the account can approve a
    trader and add a colleague, and it cannot approve a payment batch version. The
    negative half is what makes this a test of the requirement rather than a test that
    a row exists.
    """

    assert invoke() == 0

    from app.security.permissions import resolve_for_admin

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        found = connection.execute("SELECT id FROM admin_users").fetchone()
    assert found
    admin_id = found[0]

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    # The driver is named explicitly: without `+psycopg` SQLAlchemy reaches for
    # psycopg2, which this project does not install.
    engine = create_engine(
        _psycopg(migrated.owner_url).replace("postgresql://", "postgresql+psycopg://", 1)
    )
    try:
        with Session(engine) as session:
            # Two sets: the roles an audit row records, and the permissions a guard
            # consults. It is the second that decides whether this account can work.
            roles, granted = resolve_for_admin(session, admin_id)
    finally:
        engine.dispose()

    assert roles == frozenset({BOOTSTRAP_ROLE})

    assert "trader.approve" in granted, (
        "the first administrator cannot approve a trader, so the platform still cannot "
        "act on the registration it accepts"
    )
    assert "user.create" in granted, (
        "the first administrator cannot add a second one, which makes this the only "
        "account the deployment will ever have"
    )
    assert "payment_batch_version.approve" not in granted, (
        "doc 18:1105 says not to give the installer financial authority by default"
    )


def test_it_refuses_once_the_platform_has_any_staff(
    invoke: Any, migrated: RuntimeIdentities
) -> None:
    """The guard is on the platform having no staff, not on the username being free.

    The second call deliberately uses a **different** username. A repeat of the same
    name would be refused by `admin_users.username`'s unique index whether the guard
    exists or not, so the test would stay green with the guard deleted — which is the
    control that proved it.
    """

    assert invoke() == 0
    before = _counts(migrated)

    assert invoke(username="installer2") == 2, (
        "a second bootstrap succeeded, so the command left behind a way to mint staff "
        "accounts from a shell without any existing administrator authorising it"
    )
    assert _counts(migrated) == before, "the refused call still changed the database"


def test_it_refuses_a_role_that_could_not_add_a_second_administrator(
    invoke: Any, migrated: RuntimeIdentities
) -> None:
    """A role chosen wrongly is the quiet failure this command has to prevent.

    `technical_admin` provisions perfectly and yields an administrator who holds no
    `user.create`, so the deployment ends up with exactly one account forever and no way
    to add another without a second visit to the database. The refusal reads the seeded
    grant rather than a list written in the command, so it cannot disagree with
    migration `_0008`.
    """

    assert invoke(role="technical_admin") == 3
    assert _counts(migrated) == (0, 0, 0), "a refused role still created something"

    assert invoke(role="no_such_role") == 3
    assert _counts(migrated) == (0, 0, 0)


def test_nothing_it_prints_contains_the_password(
    invoke: Any, migrated: RuntimeIdentities, capsys: Any
) -> None:
    """Doc 18:1099 — the command must not print the password.

    Asserted together with the positive half, because "the password is absent from the
    output" is also satisfied by a command that prints nothing at all, or that failed.
    """

    assert invoke() == 0
    captured = capsys.readouterr()

    assert USERNAME in captured.out, "the operator is told nothing they can act on"

    # The audit id must be a real one. `AuditWriter.record` stages the row without
    # committing, so its primary key is unassigned until a flush — and the first run of
    # this suite printed `audit_logs id None`, pointing the operator at a record it
    # could not name.
    printed = [line for line in captured.out.splitlines() if line.startswith("audit_logs id ")]
    assert len(printed) == 1, captured.out
    identifier = printed[0].removeprefix("audit_logs id ").strip()
    assert uuid.UUID(identifier), identifier

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        found = connection.execute(
            "SELECT count(*) FROM audit_logs WHERE id = %s", (identifier,)
        ).fetchone()
    assert found and found[0] == 1, "the printed audit id names no row in audit_logs"

    assert PASSWORD not in captured.out
    assert PASSWORD not in captured.err
