"""AUD-OUTBOX-003 and JOB-LEASE-001: claiming is atomic, and dead claimants recover.

The whole point is unobservable with one connection. A SELECT-then-UPDATE poller
passes every single-session test and double-delivers in production, because the
window it loses is between two statements in two different transactions.

So the claim tests hold a real transaction open in one session while a second
session runs the identical statement, which is exactly the interleaving that
breaks the naive version.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.time import utc_now  # noqa: E402
from app.db.claiming import (  # noqa: E402
    claim_jobs,
    claim_outbox_events,
    heartbeat,
    new_job,
    release_job,
)
from app.db.models.outbox_event import OutboxEvent  # noqa: E402

pytestmark = pytest.mark.integration

QUEUE = "files"


def _sqlalchemy_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture
def session_factory(migrated_database: str) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(_sqlalchemy_url(migrated_database))
    try:
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(session_factory: sessionmaker[Session]) -> Iterator[None]:
    yield
    with session_factory() as session:
        session.execute(text("DELETE FROM processing_jobs"))
        session.execute(text("DELETE FROM outbox_events"))
        session.commit()


def seed_jobs(session_factory: sessionmaker[Session], count: int) -> list[uuid.UUID]:
    with session_factory() as session:
        jobs = [new_job(job_type="scan", queue_name=QUEUE) for _ in range(count)]
        session.add_all(jobs)
        session.commit()
        return [job.id for job in jobs]


def seed_outbox(session_factory: sessionmaker[Session], count: int) -> None:
    with session_factory() as session:
        for _ in range(count):
            session.add(
                OutboxEvent(
                    aggregate_type="center_profile",
                    aggregate_id=uuid.uuid4(),
                    aggregate_version=1,
                    event_type="CenterProfileRenamed",
                    payload={},
                    payload_version=1,
                )
            )
        session.commit()


class TestClaimingIsAtomic:
    def test_two_workers_never_claim_the_same_job(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """The race a SELECT-then-UPDATE poller loses.

        The first transaction stays open while the second runs, which is the
        interleaving that produces a double claim without SKIP LOCKED.
        """

        seed_jobs(session_factory, 1)

        first = session_factory()
        second = session_factory()
        try:
            claimed_first = claim_jobs(first, queue_name=QUEUE, worker_id="a", limit=5)
            assert len(claimed_first) == 1, "the seeded job was not claimable"

            # First transaction deliberately still open, holding the row lock.
            claimed_second = claim_jobs(second, queue_name=QUEUE, worker_id="b", limit=5)

            assert claimed_second == [], (
                "a second worker claimed a job the first is holding, so the same "
                "work would run twice"
            )
            first.commit()
        finally:
            first.close()
            second.rollback()
            second.close()

    def test_a_locked_row_is_skipped_rather_than_waited_for(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """SKIP LOCKED, not just FOR UPDATE.

        Without SKIP the second worker blocks until the first commits, so adding
        workers adds queueing instead of throughput.
        """

        seed_jobs(session_factory, 2)

        first = session_factory()
        second = session_factory()
        try:
            taken_first = claim_jobs(first, queue_name=QUEUE, worker_id="a", limit=1)
            taken_second = claim_jobs(second, queue_name=QUEUE, worker_id="b", limit=1)

            assert len(taken_first) == 1
            assert len(taken_second) == 1, (
                "the second worker got nothing while another job was free, so it "
                "waited on the locked row instead of skipping it"
            )
            assert taken_first[0].id != taken_second[0].id
            first.commit()
            second.commit()
        finally:
            first.close()
            second.close()

    def test_two_dispatchers_never_claim_the_same_outbox_event(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """At-least-once delivery is the contract; twice-every-time is not."""

        seed_outbox(session_factory, 1)

        first = session_factory()
        second = session_factory()
        try:
            claimed_first = claim_outbox_events(first, worker_id="a", limit=10)
            claimed_second = claim_outbox_events(second, worker_id="b", limit=10)

            assert len(claimed_first) == 1
            assert claimed_second == []
            first.commit()
        finally:
            first.close()
            second.rollback()
            second.close()

    def test_a_claim_that_rolls_back_returns_the_work(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """A crashed claimant before commit must not consume the job."""

        seed_jobs(session_factory, 1)

        rolled_back = session_factory()
        try:
            assert len(claim_jobs(rolled_back, queue_name=QUEUE, worker_id="a")) == 1
            rolled_back.rollback()
        finally:
            rolled_back.close()

        with session_factory() as session:
            again = claim_jobs(session, queue_name=QUEUE, worker_id="b")
            session.commit()

        assert len(again) == 1, "a rolled-back claim consumed the job"


class TestLeases:
    def test_a_job_still_being_worked_on_is_not_stolen(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        seed_jobs(session_factory, 1)

        with session_factory() as session:
            claim_jobs(session, queue_name=QUEUE, worker_id="a")
            session.commit()

        with session_factory() as session:
            stolen = claim_jobs(session, queue_name=QUEUE, worker_id="b")
            session.commit()

        assert stolen == [], "a live claim was taken by another worker"

    def test_a_stale_lease_is_reclaimed(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """The only path by which a crashed worker's job is ever picked up again.

        Excluding `running` from the claimable set would strand it forever;
        including it without a lease would let two workers run it at once.
        """

        seed_jobs(session_factory, 1)

        with session_factory() as session:
            claim_jobs(session, queue_name=QUEUE, worker_id="dead-worker")
            session.commit()

        # The claimant stopped heartbeating ten minutes ago.
        with session_factory() as session:
            session.execute(
                text("UPDATE processing_jobs SET heartbeat_at = now() - interval '10 minutes'")
            )
            session.commit()

        with session_factory() as session:
            reclaimed = claim_jobs(
                session, queue_name=QUEUE, worker_id="live-worker", lease=timedelta(minutes=5)
            )
            session.commit()

        assert len(reclaimed) == 1
        assert reclaimed[0].locked_by == "live-worker"
        assert reclaimed[0].attempt_count == 2, (
            "the reclaim did not consume an attempt, so a job that crashes its "
            "worker every time would be retried forever"
        )

    def test_a_worker_that_lost_its_lease_cannot_finish_the_job(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """Otherwise the second completion overwrites the first."""

        seed_jobs(session_factory, 1)

        with session_factory() as session:
            claimed = claim_jobs(session, queue_name=QUEUE, worker_id="a")
            session.commit()
            job = claimed[0]

        job.locked_by = "b"  # reclaimed by somebody else

        with pytest.raises(RuntimeError, match="reclaimed"):
            heartbeat(job, "a")

    def test_releasing_clears_the_lease(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """A finished row that keeps `locked_by` looks like a stale claim forever."""

        seed_jobs(session_factory, 1)

        with session_factory() as session:
            claimed = claim_jobs(session, queue_name=QUEUE, worker_id="a")
            release_job(claimed[0], status="succeeded", output={"ok": True})
            session.commit()

        with session_factory() as session:
            row = session.execute(
                text("SELECT status, locked_by, heartbeat_at, finished_at FROM processing_jobs")
            ).one()

        assert row[0] == "succeeded"
        assert row[1] is None
        assert row[2] is None
        assert row[3] is not None


class TestSchedulingRules:
    def test_a_job_scheduled_for_later_is_not_claimed_yet(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with session_factory() as session:
            job = new_job(job_type="scan", queue_name=QUEUE)
            job.available_at = utc_now() + timedelta(hours=1)
            session.add(job)
            session.commit()

        with session_factory() as session:
            assert claim_jobs(session, queue_name=QUEUE, worker_id="a") == []
            session.commit()

    def test_a_retry_is_scheduled_into_the_future(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """Immediate retry of a failing job is a tight loop against the database."""

        seed_jobs(session_factory, 1)

        with session_factory() as session:
            claimed = claim_jobs(session, queue_name=QUEUE, worker_id="a")
            release_job(
                claimed[0],
                status="retry_scheduled",
                error_code="TRANSIENT",
                retry_delay=timedelta(minutes=2),
            )
            session.commit()

        with session_factory() as session:
            assert claim_jobs(session, queue_name=QUEUE, worker_id="b") == []
            session.commit()

    def test_another_queue_does_not_take_this_queues_work(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        seed_jobs(session_factory, 2)

        with session_factory() as session:
            assert claim_jobs(session, queue_name="exports", worker_id="a") == []
            session.commit()

    def test_the_idempotency_key_is_unique_per_job_type_only_where_present(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """Partial, as doc 04 instructs: many jobs may have no key at all."""

        with session_factory() as session:
            session.add_all(
                [
                    new_job(job_type="scan", queue_name=QUEUE),
                    new_job(job_type="scan", queue_name=QUEUE),
                    new_job(job_type="scan", queue_name=QUEUE, idempotency_key="k"),
                    new_job(job_type="render", queue_name=QUEUE, idempotency_key="k"),
                ]
            )
            session.commit()

        from sqlalchemy.exc import IntegrityError

        with session_factory() as session, pytest.raises(IntegrityError):
            session.add(new_job(job_type="scan", queue_name=QUEUE, idempotency_key="k"))
            session.commit()


class TestAttemptAccounting:
    def test_the_attempt_is_consumed_at_claim_not_at_completion(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """A worker that crashes mid-run must still have used an attempt.

        Counting at completion means a job that kills its worker every time is
        retried forever and never reaches dead-letter.
        """

        seed_jobs(session_factory, 1)

        with session_factory() as session:
            claimed = claim_jobs(session, queue_name=QUEUE, worker_id="a")
            assert claimed[0].attempt_count == 1
            session.commit()

    def test_attempts_cannot_exceed_the_maximum(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """Enforced by the database, so no code path can quietly over-retry."""

        from sqlalchemy.exc import IntegrityError

        with session_factory() as session, pytest.raises(IntegrityError):
            job = new_job(job_type="scan", queue_name=QUEUE, max_attempts=2)
            job.attempt_count = 3
            session.add(job)
            session.commit()


class TestClaimIndexes:
    def test_the_claim_and_reclaim_indexes_exist(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """Doc 04 writes neither down, and the worker pattern cannot run without them."""

        with session_factory() as session:
            names = {
                row[0]
                for row in session.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename = 'processing_jobs'")
                )
            }

        assert "idx_processing_jobs_claim" in names
        assert "idx_processing_jobs_stale_lease" in names

    def test_the_claim_query_uses_the_claim_index(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """A plan assertion at representative volume, not an existence check.

        Volume is the whole point, and the first version of this test got it
        wrong: at two hundred rows PostgreSQL correctly prefers a sequential
        scan, because reading the table is cheaper than the index. The assertion
        failed against a schema that was perfectly fine.

        Seeded here through generate_series rather than the ORM — twenty thousand
        round trips would make this the slowest test in the suite, and the point
        is the planner's choice, not the insert path.
        """

        with session_factory() as session:
            # Every seeded row is claimable. Mixing in terminal rows would need
            # `finished_at` set to satisfy `ck_processing_jobs_finished_at_matches_status`,
            # and the constraint would reject the batch — which is what the first
            # version of this seed did. Selectivity here comes from `queue_name`,
            # which is what the index leads on.
            session.execute(
                text(
                    "INSERT INTO processing_jobs "
                    "(job_type, queue_name, status, available_at) "
                    "SELECT 'scan', "
                    # mod() rather than the % operator: psycopg treats % as
                    # parameter syntax, and escaping it through two layers is a
                    # detail nobody should have to remember when reading this.
                    "CASE WHEN mod(i, 4) = 0 THEN 'files' ELSE 'exports' END, "
                    "'queued', "
                    "now() - (i || ' seconds')::interval "
                    "FROM generate_series(1, 20000) AS i"
                )
            )
            session.commit()
            session.execute(text("ANALYZE processing_jobs"))
            session.commit()

        with session_factory() as session:
            plan = "\n".join(
                row[0]
                for row in session.execute(
                    text(
                        "EXPLAIN SELECT id FROM processing_jobs "
                        "WHERE queue_name = 'files' AND status IN ('queued', 'retry_scheduled') "
                        "AND available_at <= now() ORDER BY available_at LIMIT 1"
                    )
                )
            )

        assert "idx_processing_jobs_claim" in plan, (
            f"the claim query does not use the claim index:\n{plan}"
        )
