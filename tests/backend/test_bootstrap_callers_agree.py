"""Every caller of the bootstrap SQL must pass every variable it requires.

This exists because of a failure that only appears on a virgin data directory.
`020-runtime-roles.sql` gained `readonly_role` and `backup_role`; the Compose
one-shot was updated and `infra/postgres/init/010-create-runtime-roles.sh` was
not. That script runs only through `docker-entrypoint-initdb.d`, which executes
exactly once, when PostgreSQL initialises an empty data directory.

So every developer and every existing volume kept working. A fresh CI runner
initialised a new cluster, psql hit an unset `:'readonly_role'` under
`ON_ERROR_STOP`, initdb failed, and the only symptom was `container
postgres-1 is unhealthy` — before the bootstrap one-shot that would have
succeeded ever ran.

The two callers are one file apart and easy to update singly. This compares them
against the SQL by parsing, so the next divergence fails in a unit test instead
of on someone's first clean checkout.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_DIR = REPOSITORY_ROOT / "infra" / "postgres" / "bootstrap"
INIT_SCRIPT = REPOSITORY_ROOT / "infra" / "postgres" / "init" / "010-create-runtime-roles.sh"
COMPOSE_FILE = REPOSITORY_ROOT / "infra" / "compose" / "compose.local.yml"

# psql interpolations: :'name' for a literal, :"name" for an identifier.
_REQUIRED = re.compile(r":['\"](\w+)['\"]")
_PROVIDED = re.compile(r"--set=(\w+)=")

# Set by psql itself, never passed by a caller.
_BUILTIN = frozenset({"ON_ERROR_STOP"})


def required_variables(path: Path) -> frozenset[str]:
    text = "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("--")
    )
    return frozenset(_REQUIRED.findall(text)) - _BUILTIN


def provided_variables(path: Path, *, within: str | None = None) -> frozenset[str]:
    text = path.read_text(encoding="utf-8")
    if within is not None:
        start = text.index(within)
        text = text[start:]
    return frozenset(_PROVIDED.findall(text)) - _BUILTIN


@pytest.fixture(scope="module")
def runtime_roles_sql() -> Path:
    path = BOOTSTRAP_DIR / "020-runtime-roles.sql"
    assert path.exists(), f"{path} is missing; the callers below would have nothing to satisfy"
    return path


def test_the_sql_actually_requires_variables(runtime_roles_sql: Path) -> None:
    """Guard the guard: an empty requirement set makes every check below vacuous."""

    required = required_variables(runtime_roles_sql)

    assert len(required) >= 6, (
        f"only {sorted(required)} parsed out of {runtime_roles_sql.name}; the "
        "comparison below would pass against a caller that provides nothing"
    )
    assert "database" in required


def test_the_initdb_script_passes_every_required_variable(runtime_roles_sql: Path) -> None:
    """The one that runs once, on a virgin data directory, and nowhere else."""

    required = required_variables(runtime_roles_sql)
    provided = provided_variables(INIT_SCRIPT)

    missing = sorted(required - provided)
    assert not missing, (
        f"{INIT_SCRIPT.name} does not pass {missing}. It runs only when PostgreSQL "
        "initialises an empty data directory, so this breaks nothing on an existing "
        "volume and fails every fresh cluster with an unhealthy container and no "
        "clear cause."
    )


def test_the_compose_one_shot_passes_every_required_variable(
    runtime_roles_sql: Path,
) -> None:
    """The one that replays on every stack start."""

    required = required_variables(runtime_roles_sql)
    provided = provided_variables(COMPOSE_FILE, within="db-bootstrap:")

    missing = sorted(required - provided)
    assert not missing, f"the db-bootstrap service does not pass {missing}"


def test_the_initdb_script_guards_every_environment_variable_it_reads() -> None:
    """`set -eu` alone would substitute an empty string for an unset password.

    A role created with an empty password looks provisioned and cannot be used,
    which is a worse failure than not creating it at all.
    """

    text = INIT_SCRIPT.read_text(encoding="utf-8")
    read = set(re.findall(r'--set=\w+="\$(\w+)"', text))
    guarded = set(re.findall(r': "\$\{(\w+):\?', text))

    unguarded = sorted(read - guarded - {"POSTGRES_USER"})
    assert not unguarded, f"{INIT_SCRIPT.name} uses {unguarded} without a :? guard"


def test_the_postgres_service_supplies_what_the_initdb_script_needs() -> None:
    """The script runs inside the postgres container, not the bootstrap one.

    Passing a variable to `db-bootstrap` and not to `postgres` reproduces exactly
    the failure this file was written for.
    """

    script = INIT_SCRIPT.read_text(encoding="utf-8")
    needed = set(re.findall(r': "\$\{(\w+):\?', script))

    compose = COMPOSE_FILE.read_text(encoding="utf-8")
    postgres_block = compose[compose.index("\n  postgres:") :]
    postgres_block = postgres_block[: postgres_block.index("\n    volumes:")]

    missing = sorted(name for name in needed if name not in postgres_block)
    assert not missing, (
        f"the postgres service does not receive {missing}, so the initdb script "
        "cannot read them when it runs on a fresh cluster"
    )
