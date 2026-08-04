"""Migrations against a database nothing has shaped yet.

Two requirements pull in opposite directions here, and the split below is how
both are kept.

The extension migration's *create* path is only exercised on a database with no
extensions. Everywhere else — Compose, CI, the provisioned fixtures — bootstrap
installs them first, so every other run takes the no-op path. Losing this would
mean the create path is written, reviewed, and never executed.

Migration `20260801_0005` grants to the runtime roles, so it genuinely cannot run
before provisioning. That is a real dependency and not an artificial one: there
is nothing to grant to.

So the virgin-database tests stop at the schema head (`20260801_0004`), and the
grant revision is exercised on a provisioned database. A third test pins what
happens when someone runs the full head without provisioning — it must fail with
a message naming the missing configuration, not skip the grant.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.db.migrations import EXPECTED_MIGRATION_HEADS  # noqa: E402

pytestmark = pytest.mark.integration

# The last revision that only creates schema. Everything up to here must apply to
# a database with nothing in it.
SCHEMA_HEAD = "20260801_0004"


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def test_upgrade_to_the_schema_head_succeeds_on_an_empty_database(
    disposable_database: str,
) -> None:
    result = run_alembic(disposable_database, "upgrade", SCHEMA_HEAD)

    assert result.returncode == 0, (
        "alembic could not build the schema from nothing.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_the_full_head_refuses_to_run_before_provisioning(
    disposable_database: str,
) -> None:
    """The guard in 20260801_0005, proven rather than assumed.

    Skipping the grant would be the dangerous alternative: migrations would report
    success and the runtime would discover, on its first write, that it holds no
    UPDATE on its own tables.
    """

    result = run_alembic(disposable_database, "upgrade", "head")

    assert result.returncode != 0, (
        "the grant revision ran without configured roles, so it granted to nobody "
        "and reported success"
    )
    assert "APP_DB_ROLE" in result.stderr, (
        "the failure does not name the missing configuration, so an operator has "
        f"nothing to act on:\n{result.stderr}"
    )


def test_the_full_head_succeeds_after_provisioning(
    provisioned_database: RuntimeIdentities,
) -> None:
    result = run_alembic(
        provisioned_database.migrator_url,
        "upgrade",
        "head",
        app_role=provisioned_database.app_role,
        worker_role=provisioned_database.worker_role,
    )

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    with psycopg.connect(_psycopg(provisioned_database.owner_url)) as connection:
        recorded = {
            row[0] for row in connection.execute("SELECT version_num FROM alembic_version")
        }
    assert recorded == EXPECTED_MIGRATION_HEADS, (
        "the head recorded in the database does not match the constant the "
        "readiness probe demands, so the application would report itself unready "
        "against a database it had just migrated correctly"
    )


def installed_extensions(database_url: str) -> set[str]:
    with psycopg.connect(_psycopg(database_url)) as connection:
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

    assert run_alembic(disposable_database, "upgrade", SCHEMA_HEAD).returncode == 0

    assert installed_extensions(disposable_database) == {"pgcrypto", "citext"}


def test_upgrade_is_idempotent(provisioned_database: RuntimeIdentities) -> None:
    """The migrate container runs on every stack start, full head included."""

    def upgrade() -> subprocess.CompletedProcess[str]:
        return run_alembic(
            provisioned_database.migrator_url,
            "upgrade",
            "head",
            app_role=provisioned_database.app_role,
            worker_role=provisioned_database.worker_role,
        )

    assert upgrade().returncode == 0
    second = upgrade()

    assert second.returncode == 0, (
        f"a second upgrade must be a clean no-op.\nstderr:\n{second.stderr}"
    )


def test_gen_random_uuid_and_citext_behave_after_upgrade(disposable_database: str) -> None:
    """The extensions are required for what they provide, not for being listed."""

    assert run_alembic(disposable_database, "upgrade", SCHEMA_HEAD).returncode == 0

    with psycopg.connect(_psycopg(disposable_database)) as connection:
        generated = connection.execute("SELECT gen_random_uuid()").fetchone()
        assert generated is not None and generated[0] is not None

        case_insensitive = connection.execute("SELECT 'AbC'::citext = 'abc'::citext").fetchone()
        assert case_insensitive is not None and case_insensitive[0] is True
