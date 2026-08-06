"""Fixtures for tests that need a real PostgreSQL.

These never run against SQLite. The behaviour under test — extensions, role
privileges, constraint enforcement, transactional guarantees — either does not
exist in SQLite or behaves differently there, so a passing SQLite run would be
evidence of nothing.

Configuration is one environment variable, `INTEGRATION_ADMIN_DATABASE_URL`,
pointing at an identity allowed to create databases. Each test that asks for one
gets a disposable database created from it and dropped afterwards.

When that variable is absent the tests skip, so a developer without a database
still gets a useful `verify-native` run. Skipping is dangerous in CI though: a
silently skipped gate looks exactly like a passing one. So when `CI` is set the
tests fail instead, and say what to configure.
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

# `tests/fixtures` is shared with the unit suite. Inserted here rather than relying
# on a parent conftest: rootdir is `services/backend`, which is not an ancestor of
# `tests/`, so pytest never collects a conftest above these directories.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))

from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities, replay_all

ADMIN_URL_VARIABLE = "INTEGRATION_ADMIN_DATABASE_URL"

# The identities the stack actually runs as. Names are per-test so a leaked role
# from a failed run cannot collide with the next one; roles are cluster-wide.
MIGRATOR = "role_migrator"
APP = "role_app"
WORKER = "role_worker"
READONLY = "role_readonly"
BACKUP = "role_backup"

ROLE_PASSWORD = "itest-password"


def _role_names(suffix: str) -> dict[str, str]:
    """Per-run role names. Roles are cluster-wide, so a leak must not collide."""

    return {
        "migration_role": f"{MIGRATOR}_{suffix}",
        "app_role": f"{APP}_{suffix}",
        "worker_role": f"{WORKER}_{suffix}",
        "readonly_role": f"{READONLY}_{suffix}",
        "backup_role": f"{BACKUP}_{suffix}",
    }


def _admin_url() -> str | None:
    value = os.environ.get(ADMIN_URL_VARIABLE, "").strip()
    return value or None


def _running_in_ci() -> bool:
    return os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}


@pytest.fixture(scope="session")
def admin_url() -> str:
    """The privileged connection string, or a skip/failure explaining its absence."""

    value = _admin_url()
    if value:
        return value
    message = (
        f"{ADMIN_URL_VARIABLE} is not set, so no real PostgreSQL is available. "
        "Set it to a connection string for an identity that may create databases, "
        "for example "
        "postgresql://postgres:postgres@127.0.0.1:5432/postgres"
    )
    if _running_in_ci():
        pytest.fail(
            f"{message}\n"
            "Failing rather than skipping: in CI a skipped integration gate is "
            "indistinguishable from a passing one, and these tests are the only "
            "check that the schema behaves against the database it targets."
        )
    pytest.skip(message)


def _with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment))


def _psycopg_url(url: str) -> str:
    """psycopg does not accept SQLAlchemy's ``postgresql+psycopg://`` prefix."""

    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def disposable_database(admin_url: str) -> Iterator[str]:
    """Create an empty database for one test and drop it afterwards.

    Empty means empty: no extensions and no schema beyond a fresh `public`. A
    migration that assumes something already provisioned has to fail here, which
    is the point of testing against a database rather than a developer's own.
    """

    name = f"itest_{uuid.uuid4().hex[:16]}"
    admin = _psycopg_url(admin_url)

    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(f'CREATE DATABASE "{name}"')
    try:
        yield _with_database(admin_url, name)
    finally:
        with psycopg.connect(admin, autocommit=True) as connection:
            # Terminate stragglers first; a lingering session makes DROP fail and
            # would leak a database per failed test run.
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            connection.execute(f'DROP DATABASE IF EXISTS "{name}"')


@pytest.fixture
def disposable_connection(disposable_database: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(_psycopg_url(disposable_database), autocommit=True) as connection:
        yield connection


@pytest.fixture
def provisioned_database(disposable_database: str, admin_url: str) -> Iterator[RuntimeIdentities]:
    """A disposable database with the real bootstrap replayed against it.

    Replayed, not re-stated. A test that sets up its own approximation of the
    provisioning proves only that the approximation behaves as written; it cannot
    notice the real file changing.
    """

    suffix = uuid.uuid4().hex[:10]
    roles = _role_names(suffix)
    password = ROLE_PASSWORD
    database = urlsplit(_psycopg_url(disposable_database)).path.lstrip("/")

    with psycopg.connect(_psycopg_url(disposable_database), autocommit=True) as connection:
        replay_all(
            connection,
            database=database,
            **{f"{key.removesuffix('_role')}_password": password for key in roles},
            **roles,
        )

    def as_role(role: str) -> str:
        parts = urlsplit(_psycopg_url(disposable_database))
        host = parts.hostname or "127.0.0.1"
        port = f":{parts.port}" if parts.port else ""
        return f"postgresql://{role}:{password}@{host}{port}/{database}"

    try:
        yield RuntimeIdentities(
            owner_url=_psycopg_url(disposable_database),
            migrator_url=as_role(roles["migration_role"]),
            app_url=as_role(roles["app_role"]),
            worker_url=as_role(roles["worker_role"]),
            readonly_url=as_role(roles["readonly_role"]),
            backup_url=as_role(roles["backup_role"]),
            migrator_role=roles["migration_role"],
            app_role=roles["app_role"],
            worker_role=roles["worker_role"],
            readonly_role=roles["readonly_role"],
            backup_role=roles["backup_role"],
        )
    finally:
        # Roles are cluster-wide and outlive the database, so dropping the
        # database is not enough. They also cannot be dropped while grants or
        # default ACLs still reference them, and this fixture tears down before
        # the database does — so the dependencies go first, from inside it.
        with psycopg.connect(_psycopg_url(disposable_database), autocommit=True) as connection:
            for role in roles.values():
                connection.execute(f'DROP OWNED BY "{role}" CASCADE')
        with psycopg.connect(_psycopg_url(admin_url), autocommit=True) as connection:
            for role in roles.values():
                connection.execute(f'DROP ROLE IF EXISTS "{role}"')


@pytest.fixture(scope="module")
def migrated_database(admin_url: str) -> Iterator[str]:
    """One migrated database shared by a module's tests.

    Module scope rather than function scope because `alembic upgrade head` costs
    several seconds per run, and a constraint test that pays that to insert one
    bad row would make the suite slow enough that people stop running it.

    Sharing is safe here only because these tests assert rejections. A test that
    commits rows must clean up after itself; `migrated_connection` below does it
    unconditionally so forgetting is not possible.
    """

    name = f"itest_mig_{uuid.uuid4().hex[:12]}"
    suffix = uuid.uuid4().hex[:10]
    roles = _role_names(suffix)
    admin = _psycopg_url(admin_url)

    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(f'CREATE DATABASE "{name}"')

    url = _with_database(admin_url, name)

    def teardown() -> None:
        with psycopg.connect(_psycopg_url(url), autocommit=True) as connection:
            for role in roles.values():
                connection.execute(f'DROP OWNED BY "{role}" CASCADE')
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            connection.execute(f'DROP DATABASE IF EXISTS "{name}"')
            for role in roles.values():
                connection.execute(f'DROP ROLE IF EXISTS "{role}"')

    # Provisioned before migrating, in that order, because that is the order the
    # stack runs them in and migration 20260801_0005 grants against roles that
    # must already exist. A fixture that migrated an unprovisioned database would
    # be testing a sequence no deployment performs.
    with psycopg.connect(_psycopg_url(url), autocommit=True) as connection:
        replay_all(
            connection,
            database=name,
            **{f"{key.removesuffix('_role')}_password": ROLE_PASSWORD for key in roles},
            **roles,
        )

    result = run_alembic(
        url,
        "upgrade",
        "head",
        app_role=roles["app_role"],
        worker_role=roles["worker_role"],
    )
    if result.returncode != 0:
        teardown()
        pytest.fail(
            "alembic upgrade head failed while preparing the shared test database.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    try:
        yield url
    finally:
        teardown()


@pytest.fixture
def migrated_connection(migrated_database: str) -> Iterator[psycopg.Connection]:
    """A connection to the shared migrated database, emptied after every test.

    Cleanup is DELETE rather than TRUNCATE: the app runtime role holds no TRUNCATE
    privilege, and a fixture that only works as the owner would stop working the
    moment these tests run under the identity they are meant to exercise.
    """

    with psycopg.connect(_psycopg_url(migrated_database), autocommit=True) as connection:
        try:
            yield connection
        finally:
            connection.rollback()
            for table in ("audit_logs", "outbox_events", "idempotency_records", "center_profile"):
                connection.execute(f"DELETE FROM {table}")
