"""The queue read at a realistic volume. M12 slice 5.

**This file exists to expire a recorded gap.** `PERF-QUEUE-001` and the evidence emitter's
`performance_p95` say the same thing in different words: a latency figure without a data volume and
an environment is not acceptable evidence, and M2 had neither. M12 slice 3 built the
production-shaped environment; this builds the volume. The obligation's own wording is "recorded
p95 and queue timings with volume and environment captured alongside"
(`M2_IMPLEMENTATION_PLAN.md:1365`) — a *recording*, which is why most of this file records and only
part of it asserts.

## What is asserted, and what is only recorded

**No wall-clock threshold is asserted.** A millisecond bound measured on a developer's laptop or a
shared CI runner is a flake generator, and a flaky gate gets its threshold raised until it asserts
nothing — which is worse than no gate, because it is still cited as coverage. So the two halves are
kept apart:

- **asserted**: how many rows the database actually touches to return one page. That is a property
  of the plan, not of the machine, and it is what changes when somebody drops an index or adds a
  predicate on a column no index covers.
- **recorded**: the latency, with the row count and the environment beside it.

## `Actual Rows` is not the number to bound

**A sequential scan of fifty thousand rows that returns none reports `Actual Rows: 0`.** A bound
written against that field would pass against the exact plan it exists to refuse. `_rows_touched`
adds `Rows Removed by Filter` and `Rows Removed by Index Recheck` back in, which is how the
`trader-disputes` finding below became visible at all — it reported zero rows until the fixture
gave it something to return.

## What the measurement found

Three of the four accountant queues cost their own **depth**; one costs the whole **table**.

| queue | plan | rows touched | p95 |
|---|---|---|---|
| `new-requests` | bitmap index scan, then sort | 5,000 — the queue | 4.3 ms |
| `correction-responses` | bitmap index scan, then sort | 5,000 — the queue | 1.6 ms |
| `eligible-for-batching` | index scan | 0 — the queue was empty | 0.6 ms |
| `trader-disputes` | **sequential scan** | **50,000 — the table** | 8.9 ms |

`trader_disputed_at IS NOT NULL` is covered by no index. `app/db/pagination.py:17-20` states this
exact failure mode as the reason sort and filter fields are allowlisted — "a filter on it turns a
page request into a sequential scan of the whole table" — and here it is the queue's own predicate
rather than a caller's filter, so the allowlist cannot see it.

**It is recorded rather than fixed, and the measurement is the reason.** 8.9 ms at fifty thousand
rows projects to roughly 90 ms at half a million, which is a decade of this platform's traffic.
Against that, an index is paid for on every insert and every status change of the busiest table in
the system. What makes it worth recording anyway is the *shape*: every other queue is bounded by
its own depth and drains, while this one is bounded by all history and — per
`app/queues/payment_requests.py:118` — nothing ever clears a dispute, because no command resolves
one. So it is the single read whose cost only ever rises.

The fix, for whoever decides it is time:
`CREATE INDEX idx_payment_requests_disputed ON payment_requests (created_at, id)
WHERE trader_disputed_at IS NOT NULL`. Document 04 specifies no index here — it predates M9's
decision to record a dispute as a timestamp — so adding one is new schema rather than a deviation
from stated schema. `test_schema_matches_the_specification.py` checks document 04's indexes exist,
not that no others do, so nothing would object. The decision is the owner's because it is a
migration, not because a gate blocks it.

**Also measured: the "redundant" third index is not redundant.**
`app/db/models/payment_request.py:211` and `alembic/versions/20260820_0017:564` both record that
`idx_payment_request_accountant_queue` looks like it answers nothing
`idx_payment_requests_queue` does not, and both decline to drop it for want of a measurement. The
planner chose it for `eligible-for-batching` and for the deep-cursor read, and chose the other for
`new-requests`. Both are used. That question is now answered and the comments can stop deferring
it.

Covers: PERF-QUEUE-001.
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities
from scripts.emit_evidence import QUEUE_PERFORMANCE_MEASUREMENT

pytestmark = pytest.mark.integration

# A number pulled from nowhere would make this file theatre, so the business reading is stated and
# a later reader can disagree with the assumption rather than with the number. The queue depth is
# deliberately pessimistic: 5,000 unworked submissions is a month of intake with nobody reviewing —
# a backlog after an outage, not a normal Tuesday. A read that holds at a depth nobody should reach
# holds at the depth they will.
VOLUME_ASSUMPTION = (
    "200 submissions a day for a year is 50,000 payment requests. 5,000 of them sit unworked in "
    "the accountant's first queue, which is a month of intake with nobody reviewing."
)
TOTAL_REQUESTS = 50_000
QUEUE_DEPTH = 5_000
DISPUTED = 300

PAGE_SIZE = 50

# The one queue whose cost tracks the table rather than its own depth. Named here so the gate below
# can assert that it is the *only* one — a second one appearing fails, and this one being fixed
# fails too, which is what stops the exemption outliving its reason.
UNBOUNDED_QUEUE = "trader-disputes"
BOUNDED_QUEUES = ("new-requests", "correction-responses", "eligible-for-batching")

TRADER_PHONE = "+989120079001"
IBAN = "IR060120000000000000000701"


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


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


@pytest.fixture(scope="module")
def session(migrated: RuntimeIdentities) -> Iterator[Any]:
    """A real ORM session, because the statements measured here come out of `read_queue_page`.

    Read-only throughout — it is rolled back rather than committed, and the rows it reads are the
    ones `loaded` inserted over a separate connection.
    """

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    # `+psycopg` named explicitly. `owner_url` is the plain form, and SQLAlchemy's default for it
    # is psycopg2 — which this venv does not have, and which is not the driver the application
    # runs on. A measurement taken through a different driver would be a measurement of something
    # else.
    engine = create_engine(
        migrated.owner_url.replace("postgresql://", "postgresql+psycopg://", 1)
    )
    with Session(engine) as opened:
        yield opened
        opened.rollback()
    engine.dispose()


@pytest.fixture(scope="module")
def loaded(migrated: RuntimeIdentities) -> Iterator[psycopg.Connection]:
    """One trader, one beneficiary, and `TOTAL_REQUESTS` rows.

    The rows go in with `generate_series` rather than through the command path. Fifty thousand
    requests submitted properly would take an hour and would prove something about the command
    path, which other suites already cover; what this file needs is a table of the right size with
    the right distribution.

    **The distribution is the point.** The first `QUEUE_DEPTH` rows are the unworked submissions an
    accountant sees and the rest are finished work that still sits in the table. A fixture where
    every row is in the queue cannot tell a read that scales with the queue from one that scales
    with the table, which is the single distinction this file exists to draw.

    `ANALYZE` is not decoration. Without statistics the planner assumes a default selectivity and
    picks a plan it would not pick in production, so every measurement below would describe a
    database nobody runs.
    """

    with psycopg.connect(_psycopg(migrated.owner_url), autocommit=True) as connection:
        trader_id = uuid.uuid4()
        beneficiary_id = uuid.uuid4()
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'Volume Trader', %s, 'active', 'approved')",
            (trader_id, TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'Volume Payee', %s, %s, 'active', "
            "'not_checked')",
            (beneficiary_id, trader_id, IBAN, IBAN),
        )
        connection.execute(
            "INSERT INTO payment_requests "
            "(id, trader_id, beneficiary_id, request_number, status, submitted_at, "
            " review_note, created_at, updated_at) "
            "SELECT gen_random_uuid(), %s, %s, "
            "       'PR-PERF-' || lpad(n::text, 9, '0'), "
            "       CASE WHEN n <= %s THEN 'submitted_to_center' ELSE 'closed' END, "
            "       now() - (n * interval '1 second'), "
            "       NULL, "
            "       now() - (n * interval '1 second'), "
            "       now() "
            "FROM generate_series(1, %s) AS n",
            (trader_id, beneficiary_id, QUEUE_DEPTH, TOTAL_REQUESTS),
        )
        # Disputes, on finished work — a trader disputes a *result*, so these are rows that have
        # left the queue. Without them the disputes queue returns nothing and its sequential scan
        # reports zero rows read, which is the trap `_rows_touched` exists to avoid.
        connection.execute(
            "UPDATE payment_requests SET trader_disputed_at = now() WHERE request_number IN "
            "(SELECT request_number FROM payment_requests WHERE status = 'closed' LIMIT %s)",
            (DISPUTED,),
        )
        connection.execute("ANALYZE payment_requests")

        for column, predicate, expected in (
            ("queue", "status = 'submitted_to_center'", QUEUE_DEPTH),
            ("disputes", "trader_disputed_at IS NOT NULL", DISPUTED),
            ("total", "TRUE", TOTAL_REQUESTS),
        ):
            row = connection.execute(
                f"SELECT count(*) FROM payment_requests WHERE {predicate}"
            ).fetchone()
            assert row is not None and row[0] == expected, (
                f"the fixture seeded {row} rows for {column}, not {expected}; every measurement "
                "below would describe a volume that is not the one this file claims"
            )
        yield connection


def _an_accountant() -> Any:
    from app.security.actor import ActorContext

    return ActorContext(
        actor_type="admin",
        actor_id=uuid.uuid4(),
        audience="admin",
        session_id=uuid.uuid4(),
        security_stamp_version=1,
        permissions=frozenset({"payment_request.read"}),
        roles=frozenset({"accountant"}),
    )


def _definition(queue_name: str) -> Any:
    from app.queues.registry import BUILT

    return BUILT[queue_name]


Statement = tuple[str, Any]


def _what_read_queue_page_actually_runs(
    session: Any, queue_name: str, *, cursor: str | None = None
) -> tuple[Statement, Statement]:
    """The two statements `read_queue_page` emits, captured as it emits them.

    **An earlier version of this file rebuilt them instead**, composing `apply_pagination` and a
    `select(count())` the same way `read_queue_page` does. Every number it produced was right and a
    negative control walked straight through it: replacing the count's subquery with a count of the
    whole table changed nothing this file measured, because this file was not measuring that code.
    A performance test that reconstructs its own query is measuring a query nobody runs, which is
    the same defect as a gate reading another gate's artefact.

    So the page and the count come out of the production call, through the engine event that sees
    what is sent to the server. The exact-two assertion matters: picking "the count" out of a list
    by prefix is only safe if there is nothing else there to confuse it with.
    """

    from app.db.models.payment_request import PaymentRequest
    from app.queues.contract import read_queue_page
    from sqlalchemy import event, select

    captured: list[Statement] = []

    def watch(conn: Any, cursor_: Any, statement: str, parameters: Any, *rest: Any) -> None:
        del conn, cursor_, rest
        captured.append((statement, parameters))

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", watch)
    try:
        read_queue_page(
            session,
            _definition(queue_name),
            select(PaymentRequest),
            actor=_an_accountant(),
            sort=None,
            descending=False,
            limit=PAGE_SIZE,
            cursor=cursor,
        )
    finally:
        event.remove(bind, "before_cursor_execute", watch)

    assert len(captured) == 2, (
        f"read_queue_page emitted {len(captured)} statements, not the page and the count this "
        "file knows how to attribute. Whatever changed, the attribution below is now guesswork."
    )
    counts = [entry for entry in captured if entry[0].lstrip().upper().startswith("SELECT COUNT")]
    assert len(counts) == 1, f"expected exactly one count statement, found {len(counts)}"
    count = counts[0]
    page = next(entry for entry in captured if entry is not count)
    return page, count


def _plan(connection: psycopg.Connection, statement: Statement) -> dict[str, Any]:
    sql, parameters = statement
    row = connection.execute(
        f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}",
        parameters,
    ).fetchone()
    assert row is not None
    return row[0][0]["Plan"]


def _walk(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield node
    for child in node.get("Plans", []):
        yield from _walk(child)


def _rows_touched(plan: dict[str, Any]) -> int:
    """Rows the database actually looked at, which is **not** `Actual Rows`.

    `Actual Rows` is what survived the filter. The maximum is taken rather than the sum because a
    bitmap scan reports the same rows at two nodes, and adding them would double every figure.
    """

    return max(
        (node.get("Actual Rows") or 0)
        + (node.get("Rows Removed by Filter") or 0)
        + (node.get("Rows Removed by Index Recheck") or 0)
        for node in _walk(plan)
    )


def _latency_milliseconds(
    connection: psycopg.Connection, statement: Statement
) -> dict[str, float]:
    sql, parameters = statement
    samples: list[float] = []
    for _ in range(30):
        started = time.perf_counter()
        connection.execute(sql, parameters).fetchall()
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    return {
        "p95": round(samples[int(len(samples) * 0.95) - 1], 3),
        "median": round(statistics.median(samples), 3),
        "max": round(samples[-1], 3),
    }


# --- the assertions ------------------------------------------------------------------------


@pytest.mark.parametrize("queue_name", BOUNDED_QUEUES)
def test_a_queue_page_reads_its_queue_and_not_the_table(
    loaded: psycopg.Connection, session: Any, queue_name: str
) -> None:
    """The bound that matters, and it is sharp because the table is ten times the queue.

    A queue read whose cost tracks the table gets slower every day the platform runs, and nothing
    about the screen changes to say so. This is the assertion that notices — the failure it catches
    is an index dropped, renamed, or defeated by a new predicate.
    """

    page, _ = _what_read_queue_page_actually_runs(session, queue_name)
    touched = _rows_touched(_plan(loaded, page))

    assert touched <= QUEUE_DEPTH, (
        f"{queue_name} touched {touched} rows to return {PAGE_SIZE}, and the queue holds only "
        f"{QUEUE_DEPTH} of the table's {TOTAL_REQUESTS}. The read is now scaling with the table "
        "rather than with the queue, which means an index no longer covers its predicate."
    )


def test_the_only_queue_that_reads_the_whole_table_is_the_one_recorded(
    loaded: psycopg.Connection, session: Any
) -> None:
    """The exemption, written so that it expires.

    **This fails if somebody fixes `trader-disputes`**, which is deliberate: an exemption that
    survives its own reason is how a stale excuse gets cited as a decision. It also fails if the
    queue gets *worse* in some new way, and the parametrised test above fails if a second queue
    joins it — so the three together say "exactly one, and it is this one".
    """

    page, _ = _what_read_queue_page_actually_runs(session, UNBOUNDED_QUEUE)
    touched = _rows_touched(_plan(loaded, page))

    assert touched >= TOTAL_REQUESTS, (
        f"{UNBOUNDED_QUEUE} touched {touched} rows rather than the whole table. If an index now "
        "covers `trader_disputed_at IS NOT NULL`, that is good news and this test is the thing "
        f"to delete: move {UNBOUNDED_QUEUE!r} into BOUNDED_QUEUES and rewrite this module's "
        "docstring, which still describes it as the one read whose cost only ever rises."
    )


def test_the_total_count_reads_the_queue_and_not_the_table(
    loaded: psycopg.Connection, session: Any
) -> None:
    """`read_queue_page` takes an exact count on **every** page request.

    `app/db/pagination.py:26-28` argues counts do not belong in a list response for this reason,
    and §19 `:1298` requires one anyway — so the count is a decision, not an oversight, and what
    matters is that it is a second pass over the *queue* rather than over the table.

    **This is the assertion a negative control walked through**, back when this file composed the
    count itself instead of taking the one `read_queue_page` emits. Counting the table instead of
    the queue changed nothing that was being measured. It is measured from the production call now.
    """

    _, count = _what_read_queue_page_actually_runs(session, "new-requests")
    touched = _rows_touched(_plan(loaded, count))

    assert touched <= QUEUE_DEPTH, (
        f"the queue total scanned {touched} rows. A count that reads the table makes every page "
        "request cost the whole history, and the page itself would still look fast."
    )


def test_a_deep_cursor_is_not_more_expensive_than_the_first_page(
    loaded: psycopg.Connection, session: Any
) -> None:
    """The promise cursor pagination makes, measured rather than assumed.

    `app/db/pagination.py:21-24` rejects `OFFSET` because "the last page of a large table is the
    most expensive one". A keyset cursor should make deep pages **cheaper**, because the predicate
    narrows what is left. This asserts that direction, which is the one an accidental reintroduction
    of offset semantics would reverse.
    """

    from app.db.pagination import encode_cursor

    deep = loaded.execute(
        "SELECT created_at, id FROM payment_requests "
        "WHERE status = 'submitted_to_center' AND review_note IS NULL "
        "ORDER BY created_at ASC, id ASC OFFSET %s LIMIT 1",
        (QUEUE_DEPTH - 1000,),
    ).fetchone()
    assert deep is not None, "the fixture has no row that deep; the volume constants disagree"

    first_page, _ = _what_read_queue_page_actually_runs(session, "new-requests")
    first = _rows_touched(_plan(loaded, first_page))

    cursor = encode_cursor({"created_at": deep[0], "id": deep[1]})
    later_page, _ = _what_read_queue_page_actually_runs(session, "new-requests", cursor=cursor)
    later = _rows_touched(_plan(loaded, later_page))

    assert later < first, (
        f"a page {QUEUE_DEPTH - 1000} rows in touched {later} rows where the first page touched "
        f"{first}. A keyset cursor narrows what is left, so deep pages get cheaper; a deep page "
        "that costs more than a shallow one is offset semantics by another name."
    )


def test_the_measurement_is_recorded_with_its_volume_and_environment(
    loaded: psycopg.Connection, session: Any
) -> None:
    """The obligation itself: "recorded p95 and queue timings with volume and environment".

    The record is written where `emit_evidence.py` reads it. A latency figure alone is what
    `PERF-QUEUE-001` refuses, so the assertions here are about **completeness of the record**
    rather than about the numbers — a p95 nobody can place is the thing the gap was recorded to
    prevent.
    """

    version = loaded.execute("SELECT version()").fetchone()
    assert version is not None

    record = {
        "measured_at": datetime.now(UTC).isoformat(),
        "volume": {
            "payment_requests": TOTAL_REQUESTS,
            "accountant_queue_depth": QUEUE_DEPTH,
            "disputed": DISPUTED,
            "assumption": VOLUME_ASSUMPTION,
        },
        "environment": {
            "postgres_version": version[0],
            "system": platform.system(),
            "machine": platform.machine(),
            "ci": bool(os.environ.get("CI")),
            "note": (
                "A developer machine and a CI runner are not the production host. These figures "
                "bound the shape of the work, not the latency a trader will see."
            ),
        },
        "queues": {},
    }

    for queue_name in (*BOUNDED_QUEUES, UNBOUNDED_QUEUE):
        page, _ = _what_read_queue_page_actually_runs(session, queue_name)
        plan = _plan(loaded, page)
        record["queues"][queue_name] = {
            "milliseconds": _latency_milliseconds(loaded, page),
            "rows_touched": _rows_touched(plan),
            "plan": [node["Node Type"] for node in _walk(plan)],
            "indexes": sorted(
                {node["Index Name"] for node in _walk(plan) if node.get("Index Name")}
            ),
        }

    QUEUE_PERFORMANCE_MEASUREMENT.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_PERFORMANCE_MEASUREMENT.write_text(
        json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
    )

    written = json.loads(QUEUE_PERFORMANCE_MEASUREMENT.read_text(encoding="utf-8"))
    assert written["volume"]["payment_requests"] == TOTAL_REQUESTS
    assert written["volume"]["assumption"], "a volume with no stated assumption is a bare number"
    assert "PostgreSQL" in written["environment"]["postgres_version"]
    assert set(written["queues"]) == {*BOUNDED_QUEUES, UNBOUNDED_QUEUE}, (
        "a record covering some of the queues would report a p95 for the fast ones and omit the "
        "slow one, which is the evidence set reading as complete while being selective"
    )
    for queue_name, measured in written["queues"].items():
        assert measured["milliseconds"]["p95"] > 0, f"{queue_name} recorded no p95"
