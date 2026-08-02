"""Migrations must reach head on a genuinely empty database.

The Compose stack provisions the extensions before Alembic runs, so every
pipeline run exercises the migration's no-op path. This is the only place the
create path is exercised, and the only check that `alembic upgrade head` works
somewhere other than a database an earlier run already shaped.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.db.migrations import EXPECTED_MIGRATION_HEADS  # noqa: E402

pytestmark = pytest.mark.integration


def run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Invoke Alembic the way the migrate container does.

    Settings resolve `env_file` against the working directory, so a repository-root
    .env is invisible from services/backend. Everything required is passed as real
    environment variables instead, which is how the container and CI supply them.
    """

    environment = {
        **os.environ,
        "DATABASE_URL": database_url,
        "REDIS_URL": os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
        # Settings requires this to exist; the migration never writes to it.
        # Derived from the platform temporary directory so the suite runs on
        # Windows as well as on the Linux runner.
        "LOCAL_STORAGE_ROOT": os.environ.get(
            "LOCAL_STORAGE_ROOT", str(Path(tempfile.gettempdir()) / "itest-storage")
        ),
        "RELEASE_COMMIT": os.environ.get("RELEASE_COMMIT", "0" * 40),
    }
    Path(environment["LOCAL_STORAGE_ROOT"]).mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_upgrade_head_succeeds_on_an_empty_database(disposable_database: str) -> None:
    result = run_alembic(disposable_database, "upgrade", "head")

    assert result.returncode == 0, (
        "alembic upgrade head failed on an empty database.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    with psycopg.connect(
        disposable_database.replace("postgresql+psycopg://", "postgresql://", 1)
    ) as connection:
        recorded = {row[0] for row in connection.execute("SELECT version_num FROM alembic_version")}
    assert recorded == EXPECTED_MIGRATION_HEADS, (
        "the head recorded in the database does not match the constant the "
        "readiness probe demands, so the application would report itself unready "
        "against a database it had just migrated correctly"
    )


def installed_extensions(database_url: str) -> set[str]:
    with psycopg.connect(
        database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    ) as connection:
        rows = connection.execute(
            "SELECT e.extname FROM pg_extension e "
            "JOIN pg_namespace n ON n.oid = e.extnamespace "
            "WHERE n.nspname = 'public' AND e.extname IN ('pgcrypto', 'citext')"
        ).fetchall()
    return {row[0] for row in rows}


def test_required_extensions_exist_in_public_after_upgrade(disposable_database: str) -> None:
    # CREATE DATABASE clones template1. If a template ever carried these, the
    # assertion below would pass without the migration having created anything,
    # and the create path would be untested while looking covered.
    assert installed_extensions(disposable_database) == set(), (
        "the fixture database is not empty of the extensions under test, so this "
        "test cannot distinguish the migration creating them from template1 "
        "already carrying them"
    )

    assert run_alembic(disposable_database, "upgrade", "head").returncode == 0

    assert installed_extensions(disposable_database) == {"pgcrypto", "citext"}


def test_upgrade_is_idempotent(disposable_database: str) -> None:
    assert run_alembic(disposable_database, "upgrade", "head").returncode == 0
    second = run_alembic(disposable_database, "upgrade", "head")

    assert second.returncode == 0, (
        "a second upgrade must be a clean no-op; the migrate container runs on "
        f"every stack start.\nstderr:\n{second.stderr}"
    )


def test_gen_random_uuid_and_citext_behave_after_upgrade(disposable_database: str) -> None:
    """The extensions are required for what they provide, not for being listed."""

    assert run_alembic(disposable_database, "upgrade", "head").returncode == 0

    with psycopg.connect(
        disposable_database.replace("postgresql+psycopg://", "postgresql://", 1)
    ) as connection:
        generated = connection.execute("SELECT gen_random_uuid()").fetchone()
        assert generated is not None and generated[0] is not None

        case_insensitive = connection.execute(
            "SELECT 'AbC'::citext = 'abc'::citext"
        ).fetchone()
        assert case_insensitive is not None and case_insensitive[0] is True
