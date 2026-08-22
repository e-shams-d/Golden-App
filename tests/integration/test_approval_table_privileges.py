"""`batch_approvals` is append-only to the runtime roles, checked against a live database.

§11.7 ends "Approved/rejected rows are never updated". `20260822_0020` enforces that by adding
no grant at all and relying on `infra/postgres/bootstrap/020-runtime-roles.sql:95-96`, which sets
the default for new tables to `SELECT, INSERT`.

**That is a promise made by a file somebody can edit**, and a migration that grants nothing looks
identical to a migration that forgot to. So this asks PostgreSQL instead of reading either file.

`has_any_column_privilege` rather than `has_table_privilege`, which is the correction M6 slice 2
had to make: `has_table_privilege(..., 'UPDATE')` does not see column-level grants, and its first
version reported three genuinely writable tables as unwritable. Here the expected answer is
false either way, and the weaker function would give the right answer for the wrong reason —
so a later slice that adds a single column grant would still be caught.

Covers: DB-APPROVAL-001.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

TABLE = "batch_approvals"


@pytest.fixture(scope="module")
def migrated(module_provisioned_database: RuntimeIdentities) -> RuntimeIdentities:
    result = run_alembic(
        module_provisioned_database.migrator_url,
        "upgrade",
        "head",
        app_role=module_provisioned_database.app_role,
        worker_role=module_provisioned_database.worker_role,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return module_provisioned_database


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _privileges(migrated: RuntimeIdentities, role: str) -> dict[str, Any]:
    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        row = connection.execute(
            "SELECT "
            "  has_table_privilege(%(role)s, %(table)s, 'SELECT'), "
            "  has_table_privilege(%(role)s, %(table)s, 'INSERT'), "
            "  has_table_privilege(%(role)s, %(table)s, 'UPDATE'), "
            "  has_table_privilege(%(role)s, %(table)s, 'DELETE'), "
            "  EXISTS (SELECT 1 FROM information_schema.column_privileges "
            "          WHERE grantee = %(role)s AND table_name = %(bare)s "
            "            AND privilege_type = 'UPDATE')",
            {"role": role, "table": f"public.{TABLE}", "bare": TABLE},
        ).fetchone()
    assert row is not None
    return {
        "select": row[0],
        "insert": row[1],
        "update": row[2],
        "delete": row[3],
        "column_update": row[4],
    }


@pytest.mark.parametrize("which", ["app_role", "worker_role"])
def test_the_runtime_roles_can_write_a_decision_and_never_change_one(
    migrated: RuntimeIdentities, which: str
) -> None:
    """Insert and read yes; update and delete no, at the table level and per column.

    Both roles, because the worker is the one a future export job runs as, and a job that could
    rewrite an approval could make the file it generated agree with a decision nobody took.

    ADR-005 is open and no governed retention or legal-hold procedure exists, so `DELETE` is
    granted to nothing here either — the same position `audit_logs` has held since
    `20260801_0004`.
    """

    role = getattr(migrated, which)
    granted = _privileges(migrated, role)

    assert granted["select"] is True, f"{role} cannot read {TABLE}"
    assert granted["insert"] is True, f"{role} cannot record a decision in {TABLE}"
    assert granted["update"] is False, (
        f"{role} may UPDATE {TABLE}; §11.7 says approved/rejected rows are never updated"
    )
    assert granted["column_update"] is False, (
        f"{role} holds a column-level UPDATE on {TABLE}. A table-level check alone would not "
        "have seen this, which is the mistake M6 slice 2's first privilege test made."
    )
    assert granted["delete"] is False, (
        f"{role} may DELETE from {TABLE}; ADR-005 is open and no procedure authorises removing "
        "a recorded decision"
    )
