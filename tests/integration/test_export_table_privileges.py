"""`bank_excel_exports` is insert-only to the runtime roles, checked against a live database.

M7 slice 2. `20260822_0021` adds no grant at all and relies on
`infra/postgres/bootstrap/020-runtime-roles.sql:95-96`, which gives new tables `SELECT, INSERT`.
That is the entire enforcement of `FINANCIAL_INTEGRITY_BASELINE.md` §1's "Preview output cannot be
promoted by mutating it into a final artifact" — promotion is not refused by a rule, it is
unavailable.

**A migration that grants nothing looks exactly like a migration that forgot to**, and the
bootstrap is a file somebody can edit. So this asks PostgreSQL rather than reading either.

`has_any_column_privilege` as well as `has_table_privilege`, which is the correction M6 slice 2
had to make: the table-level function does not see column-level grants. Here the expected answer
is false either way, and the weaker check would be right for the wrong reason — so a later slice
that grants a single column would still be caught by the column-level assertion below and would
have to update this file deliberately.

Covers: SVC-EXPORT-002.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

TABLE = "bank_excel_exports"

# The columns slices 3 and 4 will legitimately need to write, and which must therefore be granted
# **by name** when they arrive. Listed here so that the day one of them becomes writable, the
# grant is a deliberate edit to this file rather than a table-level shortcut nobody reviews.
COLUMNS_A_LATER_SLICE_MAY_GRANT: tuple[str, ...] = (
    "status",
    "downloaded_at",
    "sent_to_bank_marked_at",
    "sent_to_bank_marked_by_admin_user_id",
)

# The columns that must **never** become writable, because each of them is what the row claims
# about itself. Rewriting `export_type` promotes a preview; rewriting either hash makes the file
# on disk stop matching the record that describes it; rewriting `batch_approval_id` re-attributes
# a file to a decision nobody took about it.
COLUMNS_THAT_MUST_STAY_FROZEN: tuple[str, ...] = (
    "export_type",
    "batch_approval_id",
    "content_hash",
    "file_sha256_hash",
    "payment_batch_version_id",
    "file_id",
    "export_number",
    "row_count",
    "total_amount_irr",
    "generated_by_admin_user_id",
    "generated_at",
)


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


def _ask(migrated: RuntimeIdentities, sql: str, parameters: dict[str, Any]) -> Any:
    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        row = connection.execute(sql, parameters).fetchone()
    assert row is not None
    return row[0]


@pytest.mark.parametrize("which", ["app_role", "worker_role"])
def test_a_runtime_role_can_record_an_export_and_never_change_one(
    migrated: RuntimeIdentities, which: str
) -> None:
    """Select and insert yes; update and delete no, at the table level.

    Both roles, because the worker is what slice 3's asynchronous final export will run as, and a
    job that could rewrite an export could make the file it generated agree with a record nobody
    verified.
    """

    role = getattr(migrated, which)
    granted = {
        privilege: _ask(
            migrated,
            "SELECT has_table_privilege(%(role)s, %(table)s, %(privilege)s)",
            {"role": role, "table": f"public.{TABLE}", "privilege": privilege},
        )
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
    }

    assert granted["SELECT"] is True, f"{role} cannot read {TABLE}"
    assert granted["INSERT"] is True, f"{role} cannot record an export"
    assert granted["UPDATE"] is False, (
        f"{role} may UPDATE {TABLE}. Slice 2 grants nothing; a later slice must grant the "
        "columns it needs by name, not the table."
    )
    assert granted["DELETE"] is False, (
        f"{role} may DELETE from {TABLE}; ADR-005 is open and no procedure authorises removing "
        "the record of a file that went to a bank"
    )


@pytest.mark.parametrize("which", ["app_role", "worker_role"])
@pytest.mark.parametrize("column", COLUMNS_THAT_MUST_STAY_FROZEN)
def test_the_columns_that_define_the_artifact_are_not_writable(
    migrated: RuntimeIdentities, which: str, column: str
) -> None:
    """Per column, and `export_type` is the one §1 is about.

    `has_any_column_privilege` rather than the table-level check: a column-level grant is
    invisible to `has_table_privilege`, so a future migration could make exactly one of these
    writable and the test above would still pass. That is how a preview would quietly become
    promotable.
    """

    role = getattr(migrated, which)
    writable = _ask(
        migrated,
        "SELECT has_any_column_privilege(%(role)s, %(table)s, 'UPDATE')"
        " AND has_column_privilege(%(role)s, %(table)s, %(column)s, 'UPDATE')",
        {"role": role, "table": f"public.{TABLE}", "column": column},
    )

    assert writable is False, (
        f"{role} may write {TABLE}.{column}. That column is part of what the row claims about "
        "itself — for `export_type` in particular, writing it is precisely the promotion "
        "FINANCIAL_INTEGRITY_BASELINE.md §1 forbids."
    )


@pytest.mark.parametrize("column", COLUMNS_A_LATER_SLICE_MAY_GRANT)
def test_the_columns_a_later_slice_will_need_are_not_granted_yet(
    migrated: RuntimeIdentities, column: str
) -> None:
    """The withheld grants, asserted as an absence — M6 slice 2's pattern.

    These four are what slices 3 and 4 need for download and mark-sent. Granting them now would
    be a capability with no command behind it, which is how `payment_batch.cancel_draft` came to
    be an approved permission that authorises nothing (DOC-CONFLICT-056).

    This test is expected to be **deleted** by the slice that grants them, not amended — the same
    way `test_release_is_not_possible_yet` was deleted by `20260821_0019`. A test left passing
    against a narrower claim is worse than no test.
    """

    writable = _ask(
        migrated,
        "SELECT has_column_privilege(%(role)s, %(table)s, %(column)s, 'UPDATE')",
        {"role": migrated.app_role, "table": f"public.{TABLE}", "column": column},
    )

    assert writable is False, (
        f"{TABLE}.{column} is already writable, but no command in this milestone writes it yet"
    )
