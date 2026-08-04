"""AUD-OUTBOX-004..007 and JOB-RETRY-001: what happens after the commit.

The properties here are all about failure, so every test drives a real one. A
dispatcher that only ever succeeds proves nothing about the case that matters —
a notification failing after money has moved.
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

from app.db.claiming import claim_jobs, new_job  # noqa: E402
from app.db.models.center_profile import CenterProfile  # noqa: E402
from app.db.models.outbox_event import OutboxEvent  # noqa: E402
from app.db.models.processing_job import ProcessingJob  # noqa: E402
from app.db.unit_of_work import UnitOfWorkFactory  # noqa: E402
from app.workers.dispatcher import (  # noqa: E402
    MAX_DELIVERY_ATTEMPTS,
    dispatch_once,
    outbox_lag,
)
from app.workers.execution import backoff_delay, decide_outcome, run_job  # noqa: E402

pytestmark = pytest.mark.integration

QUEUE = "notifications"


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


@pytest.fixture
def uow_factory(session_factory: sessionmaker[Session]) -> UnitOfWorkFactory:
    return UnitOfWorkFactory(session_factory)


@pytest.fixture(autouse=True)
def clean_tables(session_factory: sessionmaker[Session]) -> Iterator[None]:
    yield
    with session_factory() as session:
        for table in ("processing_jobs", "outbox_events", "center_profile"):
            session.execute(text(f"DELETE FROM {table}"))
        session.commit()


def seed_event(session_factory: sessionmaker[Session], count: int = 1) -> None:
    with session_factory() as session:
        for _ in range(count):
            session.add(
                OutboxEvent(
                    aggregate_type="center_profile",
                    aggregate_id=uuid.uuid4(),
                    aggregate_version=1,
                    event_type="CenterProfileRenamed",
                    payload={"name": "x"},
                    payload_version=1,
                )
            )
        session.commit()


class Handler:
    """A test double that declares its retry safety, as every handler must."""

    def __init__(self, *, retry_safe: bool, fail: bool = False) -> None:
        self.job_type = "scan"
        self.retry_safe = retry_safe
        self.fail = fail
        self.calls = 0

    def __call__(self, job: ProcessingJob) -> dict[str, object]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("handler failed")
        return {"ok": True}


class TestDispatch:
    def test_a_delivered_event_is_marked_published_with_a_timestamp(
        self, session_factory: sessionmaker[Session], uow_factory: UnitOfWorkFactory
    ) -> None:
        seed_event(session_factory)

        report = dispatch_once(uow_factory, lambda _event: None, worker_id="d1")

        assert report.published == 1
        with session_factory() as session:
            status, published_at, locked_by = session.execute(
                text("SELECT status, published_at, locked_by FROM outbox_events")
            ).one()
        assert status == "published"
        assert published_at is not None
        assert locked_by is None, "a published row still holding a lease looks claimed"

    def test_a_delivery_failure_does_not_lose_the_event(
        self, session_factory: sessionmaker[Session], uow_factory: UnitOfWorkFactory
    ) -> None:
        """AUD-OUTBOX-007's core: the business state already committed.

        Delivery failing afterwards must leave the event to be retried, not
        discard it and not reach back into anything.
        """

        seed_event(session_factory)

        def explode(_event: OutboxEvent) -> None:
            raise RuntimeError("broker down")

        report = dispatch_once(uow_factory, explode, worker_id="d1")

        assert report.failed == 1
        with session_factory() as session:
            status, available_at = session.execute(
                text("SELECT status, available_at FROM outbox_events")
            ).one()
        assert status == "failed"
        assert available_at is not None

    def test_a_failed_event_is_retried_later_not_immediately(
        self, session_factory: sessionmaker[Session], uow_factory: UnitOfWorkFactory
    ) -> None:
        """Immediate retry of a failing delivery is a tight loop against the broker."""

        seed_event(session_factory)

        def explode(_event: OutboxEvent) -> None:
            raise RuntimeError("broker down")

        dispatch_once(uow_factory, explode, worker_id="d1")
        second = dispatch_once(uow_factory, explode, worker_id="d1")

        assert second.claimed == 0, "the failed event was retried with no backoff"

    def test_a_poison_event_reaches_dead_letter(
        self, session_factory: sessionmaker[Session], uow_factory: UnitOfWorkFactory
    ) -> None:
        seed_event(session_factory)

        with session_factory() as session:
            session.execute(
                text("UPDATE outbox_events SET attempt_count = :n"),
                {"n": MAX_DELIVERY_ATTEMPTS},
            )
            session.commit()

        def explode(_event: OutboxEvent) -> None:
            raise RuntimeError("permanently undeliverable")

        report = dispatch_once(uow_factory, explode, worker_id="d1")

        assert report.dead_lettered == 1
        with session_factory() as session:
            status = session.execute(text("SELECT status FROM outbox_events")).scalar()
        assert status == "dead_lettered"

    def test_the_stored_error_does_not_carry_the_payload(
        self, session_factory: sessionmaker[Session], uow_factory: UnitOfWorkFactory
    ) -> None:
        """A client exception routinely quotes what it was sending."""

        seed_event(session_factory)

        def leaky(_event: OutboxEvent) -> None:
            raise RuntimeError("failed sending {'iban': 'IR820540102680020817909002'}")

        dispatch_once(uow_factory, leaky, worker_id="d1")

        with session_factory() as session:
            stored = session.execute(text("SELECT last_error FROM outbox_events")).scalar()

        assert "IR8205" not in (stored or "")
        assert stored == "RuntimeError"

    def test_delivery_is_at_least_once_and_the_event_id_is_the_dedup_key(
        self, session_factory: sessionmaker[Session], uow_factory: UnitOfWorkFactory
    ) -> None:
        """Stated as a test because no consumer can discover it downstream."""

        seed_event(session_factory)
        seen: list[uuid.UUID] = []

        dispatch_once(uow_factory, lambda event: seen.append(event.id), worker_id="d1")

        assert len(seen) == 1
        assert seen[0] is not None


class TestOutboxLag:
    def test_age_is_reported_not_only_a_count(
        self, session_factory: sessionmaker[Session], uow_factory: UnitOfWorkFactory
    ) -> None:
        """A count cannot tell a healthy burst from one event stuck for hours."""

        seed_event(session_factory, count=3)
        with session_factory() as session:
            session.execute(
                text("UPDATE outbox_events SET created_at = now() - interval '2 hours'")
            )
            session.commit()

        lag = outbox_lag(uow_factory)

        assert lag.pending == 3
        assert lag.oldest_pending_age_seconds is not None
        assert lag.oldest_pending_age_seconds > 3600

    def test_an_empty_outbox_has_no_age(self, uow_factory: UnitOfWorkFactory) -> None:
        lag = outbox_lag(uow_factory)

        assert lag.pending == 0
        assert lag.oldest_pending_age_seconds is None
        assert lag.has_dead_letters is False


class TestRetryPolicy:
    def test_a_handler_that_is_not_retry_safe_goes_to_manual_review(self) -> None:
        """The rule that stops a global retry decorator from resending money."""

        job = ProcessingJob(job_type="pay", queue_name=QUEUE, attempt_count=1, max_attempts=5)

        outcome = decide_outcome(job, handler_retry_safe=False)

        assert outcome.status == "fallback_to_manual"
        assert outcome.retry_in is None

    def test_a_retry_safe_handler_is_rescheduled(self) -> None:
        job = ProcessingJob(job_type="scan", queue_name=QUEUE, attempt_count=1, max_attempts=5)

        outcome = decide_outcome(job, handler_retry_safe=True)

        assert outcome.status == "retry_scheduled"
        assert outcome.retry_in is not None

    def test_exhaustion_dead_letters_rather_than_retrying_forever(self) -> None:
        job = ProcessingJob(job_type="scan", queue_name=QUEUE, attempt_count=5, max_attempts=5)

        outcome = decide_outcome(job, handler_retry_safe=True)

        assert outcome.status == "dead_lettered"

    def test_backoff_grows_and_is_capped(self) -> None:
        without_jitter = [backoff_delay(n, rand=lambda: 0.5) for n in (1, 2, 3, 10)]

        assert without_jitter[0] < without_jitter[1] < without_jitter[2]
        assert without_jitter[3] <= timedelta(hours=1)

    def test_jitter_spreads_retries(self) -> None:
        """Without it, jobs that failed together retry together and pile up again."""

        low = backoff_delay(3, rand=lambda: 0.0)
        high = backoff_delay(3, rand=lambda: 1.0)

        assert low < high, "the delay does not vary, so a failed batch resynchronises"

    def test_the_delay_is_never_zero(self) -> None:
        assert backoff_delay(1, rand=lambda: 0.0) >= timedelta(seconds=1)


class TestJobExecution:
    def test_a_successful_job_records_its_output(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with session_factory() as session:
            session.add(new_job(job_type="scan", queue_name=QUEUE))
            session.commit()

        handler = Handler(retry_safe=True)
        with session_factory() as session:
            job = claim_jobs(session, queue_name=QUEUE, worker_id="w1")[0]
            run_job(job, handler)
            session.commit()

        with session_factory() as session:
            status, output = session.execute(
                text("SELECT status, output_payload FROM processing_jobs")
            ).one()
        assert status == "succeeded"
        assert output == {"ok": True}
        assert handler.calls == 1

    def test_a_failing_retry_safe_job_is_rescheduled_and_keeps_its_input(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """A dead-lettered job that discarded its input cannot be replayed."""

        with session_factory() as session:
            session.add(
                new_job(job_type="scan", queue_name=QUEUE, input_payload={"file": "a.pdf"})
            )
            session.commit()

        with session_factory() as session:
            job = claim_jobs(session, queue_name=QUEUE, worker_id="w1")[0]
            run_job(job, Handler(retry_safe=True, fail=True))
            session.commit()

        with session_factory() as session:
            status, payload = session.execute(
                text("SELECT status, input_payload FROM processing_jobs")
            ).one()
        assert status == "retry_scheduled"
        assert payload == {"file": "a.pdf"}

    def test_a_failing_non_retry_safe_job_goes_straight_to_manual(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with session_factory() as session:
            session.add(new_job(job_type="pay", queue_name=QUEUE))
            session.commit()

        with session_factory() as session:
            job = claim_jobs(session, queue_name=QUEUE, worker_id="w1")[0]
            outcome = run_job(job, Handler(retry_safe=False, fail=True))
            session.commit()

        assert outcome.status == "fallback_to_manual"

    def test_the_stored_error_message_is_redacted(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with session_factory() as session:
            session.add(new_job(job_type="scan", queue_name=QUEUE))
            session.commit()

        class Leaky(Handler):
            def __call__(self, job: ProcessingJob) -> dict[str, object]:
                raise RuntimeError("token=secret-value-123")

        with session_factory() as session:
            job = claim_jobs(session, queue_name=QUEUE, worker_id="w1")[0]
            run_job(
                job,
                Leaky(retry_safe=True),
                redact=lambda message: message.replace("secret-value-123", "[REDACTED]"),
            )
            session.commit()

        with session_factory() as session:
            stored = session.execute(
                text("SELECT last_error_message FROM processing_jobs")
            ).scalar()

        assert "secret-value-123" not in (stored or "")
        assert "[REDACTED]" in (stored or "")

    def test_a_failed_job_does_not_touch_business_state(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """Job bookkeeping and business effect are separate concerns.

        run_job moves job state and nothing else; a retry must never be mistaken
        for a re-assertion that the work succeeded.
        """

        with session_factory() as session:
            session.add(CenterProfile(name="Untouched", status="active"))
            session.add(new_job(job_type="scan", queue_name=QUEUE))
            session.commit()

        with session_factory() as session:
            job = claim_jobs(session, queue_name=QUEUE, worker_id="w1")[0]
            run_job(job, Handler(retry_safe=True, fail=True))
            session.commit()

        with session_factory() as session:
            name = session.execute(text("SELECT name FROM center_profile")).scalar()
        assert name == "Untouched"
