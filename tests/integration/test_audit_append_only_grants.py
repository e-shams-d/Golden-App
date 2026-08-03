"""The runtime role must not be able to change or remove an audit row.

`infra/postgres/bootstrap/020-runtime-roles.sql` sets default privileges granting
SELECT, INSERT, UPDATE and DELETE on every table the migrator creates to the
application role. That is right for ordinary tables and wrong for audit
evidence: an audit row that the writing process can edit afterwards records only
what that process last wanted it to say.

So this reproduces the bootstrap's default-privilege rule before migrating, then
checks what the role is actually left holding. Setting up the grant first is the
whole point — a role created after the migration would have no privileges to
revoke, and the test would pass while proving nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from alembic_runner import run_alembic

pytestmark = pytest.mark.integration


def _psycopg_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture
def runtime_role(disposable_database: str) -> Iterator[str]:
    """A stand-in for the deployment's application role, granted the same way.

    Roles are cluster-wide rather than per-database, so the name is unique and
    the teardown runs even when the test fails; a leaked role would make the next
    run fail on a name collision that says nothing about the code.
    """

    role = f"itest_app_{uuid.uuid4().hex[:12]}"
    url = _psycopg_url(disposable_database)

    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(f'CREATE ROLE "{role}" NOLOGIN')
        connection.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
        # The exact rule from 020-runtime-roles.sql.
        connection.execute(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{role}"'
        )
    try:
        yield role
    finally:
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM "{role}"'
            )
            connection.execute(f'DROP OWNED BY "{role}"')
            connection.execute(f'DROP ROLE IF EXISTS "{role}"')


def privileges(connection: psycopg.Connection, role: str, table: str) -> dict[str, bool]:
    row = connection.execute(
        "SELECT has_table_privilege(%(role)s, %(table)s, 'SELECT'), "
        "has_table_privilege(%(role)s, %(table)s, 'INSERT'), "
        "has_table_privilege(%(role)s, %(table)s, 'UPDATE'), "
        "has_table_privilege(%(role)s, %(table)s, 'DELETE')",
        {"role": role, "table": table},
    ).fetchone()
    assert row is not None
    return dict(zip(("SELECT", "INSERT", "UPDATE", "DELETE"), row, strict=True))


def test_the_default_privilege_rule_really_would_grant_mutation(
    disposable_database: str, runtime_role: str
) -> None:
    """Confirm the hazard exists before checking that the migration removes it.

    Without this, a change to the bootstrap that stopped granting UPDATE would
    make the test below pass for a completely different reason.
    """

    with psycopg.connect(_psycopg_url(disposable_database), autocommit=True) as connection:
        connection.execute("CREATE TABLE grant_probe (id integer)")
        held = privileges(connection, runtime_role, "grant_probe")
        connection.execute("DROP TABLE grant_probe")

    assert held["UPDATE"] is True
    assert held["DELETE"] is True


def test_the_runtime_role_cannot_update_or_delete_audit_rows(
    disposable_database: str, runtime_role: str
) -> None:
    assert run_alembic(disposable_database, "upgrade", "head").returncode == 0

    with psycopg.connect(_psycopg_url(disposable_database), autocommit=True) as connection:
        held = privileges(connection, runtime_role, "audit_logs")

    assert held["INSERT"] is True, "the runtime role must still be able to write audit rows"
    assert held["SELECT"] is True
    assert held["UPDATE"] is False, "an audit row the writer can edit is not evidence"
    assert held["DELETE"] is False, "an audit row the writer can remove is not evidence"


def test_the_revoke_is_targeted_and_not_a_blanket_lockdown(
    disposable_database: str, runtime_role: str
) -> None:
    """Only audit_logs is append-only.

    A dispatcher has to move an outbox event through its lifecycle and an
    idempotency record has to be completed, so revoking everywhere would break
    both while looking like extra safety.
    """

    assert run_alembic(disposable_database, "upgrade", "head").returncode == 0

    with psycopg.connect(_psycopg_url(disposable_database), autocommit=True) as connection:
        outbox = privileges(connection, runtime_role, "outbox_events")
        idempotency = privileges(connection, runtime_role, "idempotency_records")

    assert outbox["UPDATE"] is True
    assert idempotency["UPDATE"] is True
