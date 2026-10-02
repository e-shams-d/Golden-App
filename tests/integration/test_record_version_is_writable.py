"""Every table that carries `record_version` must let the runtime write it.

**This omission has now been made twice and corrected twice.** `20260830_0030` exists for
no other reason, and its docstring says it outright: *"`record_version` is in the grant
because `compare_and_swap` writes it."* Nine months later `20260909_0040` enumerated nine
columns for `incoming_payment_matches` and left the same one out, `20260910_0041` added a
tenth without noticing, and every confirmation and rejection of a match was refused by
PostgreSQL in any deployment with the runtime roles in force.

A fact learned twice and forgotten twice is not something to remember harder.

**Derived, not listed, and that is the whole point.** The sibling privilege suites write
their matrices out by hand, deliberately, so that adding a table is a conscious edit.
That is right for *which* columns a table exposes, because every one of those is a
decision. It is wrong here: `record_version` is not a decision. A table either
participates in optimistic concurrency or it does not, and if it does then
`compare_and_swap` writes that column on every single mutation. A hand-written list would
need the same edit the migration needs, from the same person, in the same moment they
already forgot.

So this reads the live catalogue both ways round: every `record_version` column there is,
against every grant there is. A table added tomorrow is covered the day it exists.

**Why no behavioural test caught it.** All sixty-two integration suites built the
application with `owner_url`, and the owner holds everything. F-21 is that finding; this
is the narrowest durable piece of it.

Covers: F-21, and the defect it exposed.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def migrated(module_provisioned_database: RuntimeIdentities) -> Iterator[RuntimeIdentities]:
    result = run_alembic(
        module_provisioned_database.migrator_url,
        "upgrade",
        "head",
        app_role=module_provisioned_database.app_role,
        worker_role=module_provisioned_database.worker_role,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    yield module_provisioned_database


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _tables_with_record_version(url: str) -> list[str]:
    with psycopg.connect(_psycopg(url)) as connection:
        rows = connection.execute(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'record_version' "
            "ORDER BY table_name"
        ).fetchall()
    return [row[0] for row in rows]


def _may_update(url: str, role: str, table: str) -> bool:
    """Asked per column, because these grants are per column.

    `has_table_privilege(role, table, 'UPDATE')` cannot see a column-level grant and
    answers `False` for tables the application writes every day — the sibling suite
    records that same trap costing it a false finding.
    """

    with psycopg.connect(_psycopg(url)) as connection:
        row = connection.execute(
            "SELECT has_column_privilege(%(r)s, %(t)s, 'record_version', 'UPDATE')",
            {"r": role, "t": table},
        ).fetchone()
    assert row is not None
    return bool(row[0])


def test_there_are_tables_to_check(migrated: RuntimeIdentities) -> None:
    """The guard that stops this file passing by finding nothing.

    A derived assertion over an empty set is green and means nothing. If a rename ever
    makes this query return zero rows, that is a failure here rather than silence.
    """

    tables = _tables_with_record_version(migrated.owner_url)
    assert len(tables) >= 20, f"only {len(tables)} tables carry record_version: {tables}"


def test_the_application_may_write_every_record_version(migrated: RuntimeIdentities) -> None:
    """`compare_and_swap` writes this column in the same statement as the status.

    So a table that carries it and does not grant it is not partially usable — every
    state-changing command against that table fails, and it fails as a 500 from
    PostgreSQL rather than as anything a caller can act on.
    """

    denied = [
        table
        for table in _tables_with_record_version(migrated.owner_url)
        if not _may_update(migrated.owner_url, migrated.app_role, table)
    ]
    assert not denied, (
        "these tables carry `record_version` and the application role cannot write it, "
        f"so every optimistic-concurrency update against them fails: {denied}"
    )


def test_the_worker_may_write_every_record_version(migrated: RuntimeIdentities) -> None:
    """The worker runs the same commands from the queue side.

    Checked separately rather than folded into the loop above so that a grant made to one
    role and not the other names which one.
    """

    denied = [
        table
        for table in _tables_with_record_version(migrated.owner_url)
        if not _may_update(migrated.owner_url, migrated.worker_role, table)
    ]
    assert not denied, (
        "these tables carry `record_version` and the worker role cannot write it: "
        f"{denied}"
    )


def test_the_read_only_role_may_write_none_of_them(migrated: RuntimeIdentities) -> None:
    """The negative half, without which the two above would pass on a blanket grant.

    If somebody ever fixes a denial by granting the column to everything, these
    assertions must notice. A gate that only checks the permissive direction cannot tell
    a correct grant from an absent restriction.
    """

    allowed = [
        table
        for table in _tables_with_record_version(migrated.owner_url)
        if _may_update(migrated.owner_url, migrated.readonly_role, table)
    ]
    assert not allowed, f"the read-only role can write record_version on: {allowed}"
