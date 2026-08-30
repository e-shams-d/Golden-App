"""What the runtime roles may actually do to the batching tables, bit by bit.

M6 slice 3. `DB-FINAL-001` says a finalized version's rows cannot be updated, "enforced by the
migration's grants rather than by a trigger". Slice 2 claimed that and asserted the `UPDATE` half
only — through one statement, against one table.

This file exists because a test that tried to *delete* a batch item got a foreign-key violation
instead of an insufficient-privilege error, which looked exactly like a missing `DELETE` grant.
It was not: `SET ROLE` does not survive a `ROLLBACK`, so the statement ran as the database owner,
who may do anything. **The matrix below is what settled it — `DELETE` is granted to neither
runtime role on any batching table** — and the point is that it took a direct reading of
`information_schema` to know, because a behavioural test can only ever say "the one statement I
tried was refused" and says even less when something else refuses it first.

The distinction is worth keeping: a foreign key is not a permission.
`payment_attempt_allocations` references `payment_batch_items`, so deleting an item is refused
twice over today — but the moment slice 4 releases an allocation, one of those two reasons goes
away. Immutability that rests on another table still holding a pointer is not immutability, and
only the grant tells you which one you have.

`tests/integration/test_runtime_role_privileges.py` established this pattern for M2's tables and
never grew to cover M5's or M6's. The matrix here is written out rather than derived, so adding a
table is a deliberate edit and a table nobody thought about fails the completeness test at the
bottom.

Covers: DB-FINAL-001.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

# `(SELECT, INSERT, UPDATE, DELETE)` for each table, as the migrations intend it.
#
# Every `False` is a decision. `payment_batch_items` and `payment_attempt_allocations` are
# insert-only in M6: the rows are the exact content a manager approves and a bank is paid from,
# and `04_Database_Schema.md` §17.9 lists them among the immutable source records. Slice 4 widens
# the allocation to `UPDATE (released_at, release_reason)` — column-level, so a release can never
# rewrite which item was allocated — and this table's row is what will have to change to say so.
EXPECTED: dict[str, tuple[bool, bool, bool, bool]] = {
    # SELECT, INSERT, UPDATE, DELETE
    "payment_attempts": (True, True, True, False),
    "payment_batches": (True, True, True, False),
    "payment_batch_versions": (True, True, True, False),
    "payment_batch_items": (True, True, False, False),
    # `20260821_0019` grants `(released_at, release_reason)` — slice 4's release path.
    # Slice 2 withheld it on purpose so that release provably did not exist yet, and
    # the test that proved it is deleted in the same commit rather than left passing
    # against a narrower claim.
    "payment_attempt_allocations": (True, True, True, False),
}

# The column-level UPDATE grants, for the tables whose `UPDATE` bit is True above. A table-level
# `UPDATE` on any of these would also permit rewriting a frozen snapshot or a content hash, so
# the grants are per column and this is what says which.
EXPECTED_UPDATABLE_COLUMNS: dict[str, set[str]] = {
    # **Widened from three to nine by M9's `20260830_0030`, and the six additions are the whole
    # point of that revision.** M6 created the result columns and granted nothing on them, which
    # is what let M9 slice 1 make "accepting a candidate does not mark an attempt paid" a
    # privilege the runtime did not hold rather than a branch somebody could delete. Slice 3's
    # confirmation is the first thing entitled to write them.
    #
    # What is still absent is what matters: `amount_irr`, both beneficiary snapshots,
    # `bank_profile_version_id`, `attempt_number`, `attempt_type`, both lineage pointers and
    # `split_rule_snapshot`. A confirmation records what the bank did; it cannot restate what was
    # sent. This gate caught the widening on the very run that introduced it, which is the
    # behaviour to keep.
    "payment_attempts": {
        "status",
        "record_version",
        "updated_at",
        "bank_tracking_number",
        "bank_result_at",
        "failure_code",
        "failure_reason",
        "confirmed_by_admin_user_id",
        "confirmed_at",
    },
    "payment_batches": {
        "status",
        "current_version_id",
        "sent_to_bank_at",
        "sent_to_bank_by_admin_user_id",
        "cancelled_at",
        "cancelled_reason",
        "record_version",
        "updated_at",
    },
    # `finalized_by_admin_user_id` was added by `20260821_0018`; DOC-CONFLICT-055 explains why
    # the column exists at all.
    "payment_batch_versions": {"status", "superseded_at", "finalized_by_admin_user_id"},
    # Exactly two, so a release can never rewrite *which* allocation the row is —
    # a table-level grant would permit retargeting it at another attempt after the
    # fact, which is the one edit that could turn evidence into a fiction.
    "payment_attempt_allocations": {"released_at", "release_reason"},
}


@pytest.fixture(scope="module")
def migrated(module_provisioned_database: RuntimeIdentities) -> Iterator[RuntimeIdentities]:
    result = run_alembic(
        module_provisioned_database.migrator_url,
        "upgrade",
        "head",
        app_role=module_provisioned_database.app_role,
        worker_role=module_provisioned_database.worker_role,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    yield module_provisioned_database


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _bits(url: str, role: str, table: str) -> tuple[bool, bool, bool, bool]:
    """The four verbs, with `UPDATE` asked the way column-level grants require.

    **`has_table_privilege(role, table, 'UPDATE')` does not see a column-level grant.** It answers
    "may this role update the table", and every mutable table here is granted per column — so the
    first version of this test read `False` for three tables that are updated by the application
    every day, and reported it as a missing privilege.

    `has_any_column_privilege` is the question that matches the grant, and the two together are
    more informative than either: table-level `UPDATE` on any of these would be a widening, and
    no column-level `UPDATE` at all would be an insert-only table. The distinction is asserted
    explicitly in `test_no_table_level_update_was_granted` below.
    """

    with psycopg.connect(_psycopg(url)) as connection:
        row = connection.execute(
            "SELECT has_table_privilege(%(r)s, %(t)s, 'SELECT'), "
            "has_table_privilege(%(r)s, %(t)s, 'INSERT'), "
            "has_any_column_privilege(%(r)s, %(t)s, 'UPDATE'), "
            "has_table_privilege(%(r)s, %(t)s, 'DELETE')",
            {"r": role, "t": table},
        ).fetchone()
    assert row is not None
    return (bool(row[0]), bool(row[1]), bool(row[2]), bool(row[3]))


NAMES = ("SELECT", "INSERT", "UPDATE", "DELETE")


def test_every_batching_table_holds_exactly_the_privileges_intended(
    migrated: RuntimeIdentities,
) -> None:
    """Both runtime roles, all five tables, all four verbs, reported together.

    Collected before asserting so one run states the whole matrix. A per-table parametrised test
    would report the alphabetically first mismatch and hide the rest, and the interesting failures
    here come in pairs — a table that gained `DELETE` usually gained it alongside a sibling.
    """

    problems: list[str] = []
    for role in (migrated.app_role, migrated.worker_role):
        assert role, "a runtime role is unset, so this test would prove nothing"
        for table, expected in sorted(EXPECTED.items()):
            actual = _bits(migrated.owner_url, role, table)
            if actual != expected:
                differences = [
                    f"{name}: expected {want}, got {got}"
                    for name, want, got in zip(NAMES, expected, actual, strict=True)
                    if want != got
                ]
                problems.append(f"{role} on {table}: " + "; ".join(differences))

    assert problems == [], (
        "the runtime roles hold privileges the migrations did not intend. A `DELETE` on an "
        "insert-only table is as destructive as an `UPDATE`, and a foreign key from another "
        "table is not a substitute — it stops being a barrier the moment the referencing row "
        "goes away:\n" + "\n".join(f"  {problem}" for problem in problems)
    )


def test_the_updatable_columns_are_exactly_the_mutable_ones(
    migrated: RuntimeIdentities,
) -> None:
    """Column-level `UPDATE`, so a status change cannot also rewrite a frozen snapshot.

    `payment_attempts` is the table where this matters most: it carries the beneficiary name and
    IBAN a bank will be instructed with, and a table-level `UPDATE` granted for the sake of
    moving `status` would also permit rewriting those.

    **The set is not fixed for ever, and the point is that widening it is visible.** M6 granted
    three columns; M9's `20260830_0030` added the six a payment result writes, and this gate
    failed on the run that introduced them. Editing the expectation is the deliberate half of
    that change — what must never happen is a snapshot column joining the list quietly.
    """

    problems: list[str] = []
    for role in (migrated.app_role, migrated.worker_role):
        for table, expected in sorted(EXPECTED_UPDATABLE_COLUMNS.items()):
            with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
                granted = {
                    row[0]
                    for row in connection.execute(
                        "SELECT column_name FROM information_schema.column_privileges "
                        "WHERE table_name = %s AND grantee = %s AND privilege_type = 'UPDATE'",
                        (table, role),
                    ).fetchall()
                }
            if granted != expected:
                problems.append(
                    f"{role} on {table}: extra {sorted(granted - expected)}, "
                    f"missing {sorted(expected - granted)}"
                )

    assert problems == [], "\n".join(problems)


def test_no_table_level_update_was_granted(migrated: RuntimeIdentities) -> None:
    """Every `UPDATE` on these tables is per column, never on the table.

    The two questions differ and both matter. A table-level `UPDATE` would let a status change
    also rewrite `payment_attempts.beneficiary_iban_snapshot` — the value a bank is instructed
    with — or `payment_batch_versions.content_hash`, the value an approval is bound to. So this
    asserts the *absence* of the broader grant, which `has_any_column_privilege` above cannot
    distinguish from the narrow one.
    """

    problems: list[str] = []
    for role in (migrated.app_role, migrated.worker_role):
        for table in sorted(EXPECTED):
            with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
                row = connection.execute(
                    "SELECT has_table_privilege(%s, %s, 'UPDATE')", (role, table)
                ).fetchone()
            assert row is not None
            if row[0]:
                problems.append(
                    f"{role} holds table-level UPDATE on {table}, which also permits rewriting "
                    "every frozen snapshot and hash on it"
                )

    assert problems == [], "\n".join(problems)


def test_no_batching_table_is_missing_from_the_matrix(migrated: RuntimeIdentities) -> None:
    """A table nobody thought about fails here rather than shipping unasserted.

    Derived from the database rather than from the models, because the question is what exists in
    the schema — and a table created by a migration but never mapped would be invisible to a
    metadata-driven check while being perfectly writable.
    """

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        present = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' "
                "AND (table_name LIKE 'payment_batch%' OR table_name LIKE 'payment_attempt%')"
            ).fetchall()
        }

    assert present == set(EXPECTED), (
        "the batching tables and this file's matrix have diverged.\n"
        f"  in the database, not in EXPECTED: {sorted(present - set(EXPECTED))}\n"
        f"  in EXPECTED, not in the database: {sorted(set(EXPECTED) - present)}"
    )
