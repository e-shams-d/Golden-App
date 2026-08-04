"""UT-RETRY-001: bounded retry on 40001, and a deadlock that is never retried.

The distinction is the point. Both arrive as a DBAPIError from a transaction that
was rolled back by the server, and treating them alike is the easy mistake.

A serialization failure is the isolation level saying "run it again" — nothing
was wrong with the work. A deadlock, in a system with one published lock ordering
rule, means two code paths locked overlapping rows in different orders. Retrying
that hides a reproducible bug behind an intermittent slowdown, and the next
person inherits a system that mostly works.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.db.models.center_profile import CenterProfile  # noqa: E402
from app.db.retry import (  # noqa: E402
    RetryPolicy,
    SerializationExhaustedError,
    is_deadlock,
    is_serialization_failure,
    run_with_serialization_retry,
)
from app.db.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWorkFactory  # noqa: E402

pytestmark = pytest.mark.integration


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
        session.execute(text("DELETE FROM center_profile"))
        session.commit()


class TestSqlstateClassification:
    """Pinned against the real driver, not assumed from the exception name."""

    def test_a_real_serialization_failure_is_recognised(
        self, migrated_database: str
    ) -> None:
        """Provoked with two genuinely SERIALIZABLE transactions.

        A hand-made exception would prove only that the helper reads an attribute
        somebody set.
        """

        url = migrated_database.replace("postgresql+psycopg://", "postgresql://", 1)
        identifier = uuid.uuid4()

        with psycopg.connect(url, autocommit=True) as setup:
            setup.execute(
                "INSERT INTO center_profile (id, name, status) VALUES (%s, 'A', 'retired')",
                (identifier,),
            )

        first = psycopg.connect(url)
        second = psycopg.connect(url)
        try:
            for connection in (first, second):
                connection.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                # Each reads what the other is about to write.
                connection.execute("SELECT count(*) FROM center_profile")

            first.execute(
                "INSERT INTO center_profile (name, status) VALUES ('B', 'retired')"
            )
            second.execute(
                "INSERT INTO center_profile (name, status) VALUES ('C', 'retired')"
            )
            first.commit()

            with pytest.raises(psycopg.errors.SerializationFailure) as raised:
                second.commit()
            assert raised.value.sqlstate == "40001"
        finally:
            for connection in (first, second):
                try:
                    connection.rollback()
                finally:
                    connection.close()

    def test_the_two_sqlstates_are_not_confused(self) -> None:
        serialization = psycopg.errors.SerializationFailure("x")
        deadlock = psycopg.errors.DeadlockDetected("x")

        assert serialization.sqlstate == "40001"
        assert deadlock.sqlstate == "40P01"
        assert serialization.sqlstate != deadlock.sqlstate


class FakeError(DBAPIError):
    """A DBAPIError carrying a chosen SQLSTATE, for the counting tests below."""

    def __init__(self, sqlstate: str) -> None:
        original = psycopg.errors.SerializationFailure("simulated")
        original.sqlstate = sqlstate  # type: ignore[misc]
        super().__init__("statement", {}, original)


class TestRetryBehaviour:
    def test_a_successful_operation_runs_once(self, uow_factory: UnitOfWorkFactory) -> None:
        calls: list[int] = []

        def operation(uow: SqlAlchemyUnitOfWork) -> str:
            calls.append(1)
            uow.session.add(CenterProfile(name="Once", status="retired"))
            return "done"

        assert run_with_serialization_retry(uow_factory, operation) == "done"
        assert len(calls) == 1

    def test_the_work_is_committed_by_the_wrapper(
        self, uow_factory: UnitOfWorkFactory, session_factory: sessionmaker[Session]
    ) -> None:
        """The retried unit is a whole transaction, so it owns the boundary."""

        run_with_serialization_retry(
            uow_factory,
            lambda uow: uow.session.add(CenterProfile(name="Committed", status="retired")),
        )

        with session_factory() as session:
            count = session.execute(text("SELECT count(*) FROM center_profile")).scalar()
        assert count == 1

    def test_a_serialization_failure_is_retried_and_can_succeed(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        attempts: list[int] = []

        def operation(uow: SqlAlchemyUnitOfWork) -> str:
            attempts.append(1)
            if len(attempts) < 3:
                raise FakeError("40001")
            return "eventually"

        result = run_with_serialization_retry(
            uow_factory, operation, policy=RetryPolicy(attempts=3), sleep=lambda _: None
        )

        assert result == "eventually"
        assert len(attempts) == 3

    def test_each_attempt_gets_a_fresh_transaction(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        """Retrying inside an aborted transaction would fail on the first statement.

        PostgreSQL discards everything after a failure, so a second attempt that
        reuses the session cannot execute at all.
        """

        sessions: list[int] = []

        def operation(uow: SqlAlchemyUnitOfWork) -> str:
            sessions.append(id(uow.session))
            if len(sessions) < 2:
                raise FakeError("40001")
            return "ok"

        run_with_serialization_retry(
            uow_factory, operation, policy=RetryPolicy(attempts=2), sleep=lambda _: None
        )

        assert len(set(sessions)) == 2, "the second attempt reused the aborted session"

    def test_exhaustion_raises_a_typed_conflict(self, uow_factory: UnitOfWorkFactory) -> None:
        """409, not 500. The request was never invalid, so retrying is sound advice."""

        def always_conflicts(_uow: SqlAlchemyUnitOfWork) -> None:
            raise FakeError("40001")

        with pytest.raises(SerializationExhaustedError) as raised:
            run_with_serialization_retry(
                uow_factory,
                always_conflicts,
                policy=RetryPolicy(attempts=2),
                sleep=lambda _: None,
            )

        assert raised.value.status_code == 409
        assert raised.value.__cause__ is not None, "the driver error must stay attached"

    def test_the_delay_grows_between_attempts(self) -> None:
        """So a burst of conflicting transactions does not resynchronise and collide again."""

        policy = RetryPolicy(attempts=3, initial_delay_seconds=0.01, multiplier=3.0)

        assert policy.delay_before(1) < policy.delay_before(2) < policy.delay_before(3)


class TestDeadlocksAreNotRetried:
    def test_a_deadlock_propagates_immediately(self, uow_factory: UnitOfWorkFactory) -> None:
        attempts: list[int] = []

        def deadlocks(_uow: SqlAlchemyUnitOfWork) -> None:
            attempts.append(1)
            raise FakeError("40P01")

        with pytest.raises(DBAPIError):
            run_with_serialization_retry(
                uow_factory, deadlocks, policy=RetryPolicy(attempts=5), sleep=lambda _: None
            )

        assert len(attempts) == 1, (
            "a deadlock was retried. With one published lock ordering it is an "
            "ordering violation, and retrying turns a reproducible bug into an "
            "intermittent slowdown that survives review."
        )

    def test_an_unrelated_database_error_is_not_retried_either(
        self, uow_factory: UnitOfWorkFactory
    ) -> None:
        attempts: list[int] = []

        def fails(_uow: SqlAlchemyUnitOfWork) -> None:
            attempts.append(1)
            raise FakeError("23505")  # unique_violation

        with pytest.raises(DBAPIError):
            run_with_serialization_retry(
                uow_factory, fails, policy=RetryPolicy(attempts=5), sleep=lambda _: None
            )

        assert len(attempts) == 1

    def test_the_classifiers_disagree_about_the_same_error(self) -> None:
        assert is_serialization_failure(FakeError("40001")) is True
        assert is_deadlock(FakeError("40001")) is False
        assert is_deadlock(FakeError("40P01")) is True
        assert is_serialization_failure(FakeError("40P01")) is False
