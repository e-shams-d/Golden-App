"""Savepoints against a real PostgreSQL, because the behaviour under test is its own.

The premise of the savepoint support is a PostgreSQL rule that no fake session
reproduces: after an integrity error, the *entire* transaction is aborted and
every later statement fails with "current transaction is aborted, commands
ignored until end of transaction block". A unit test with a stubbed session would
happily let the audit insert follow a failed insert and prove nothing at all.

So the first test here establishes the hazard, and the rest show the savepoint
removing it. If PostgreSQL ever stopped behaving that way, the first test fails
and says the machinery may no longer be needed — rather than the machinery
quietly becoming decoration.

Covers: SVC-PARTIAL-001.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, PendingRollbackError
from sqlalchemy.orm import Session, sessionmaker

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.db.models.center_profile import CenterProfile  # noqa: E402
from app.db.unit_of_work import SqlAlchemyUnitOfWork  # noqa: E402

pytestmark = pytest.mark.integration


@pytest.fixture
def session_factory(migrated_database: str) -> Iterator[sessionmaker[Session]]:
    url = migrated_database
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url)
    try:
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(session_factory: sessionmaker[Session]) -> Iterator[None]:
    yield
    with session_factory() as session:
        for table in ("audit_logs", "outbox_events", "idempotency_records", "center_profile"):
            session.execute(text(f"DELETE FROM {table}"))
        session.commit()


def profile(name: str = "Golden Center", status: str = "active") -> CenterProfile:
    return CenterProfile(name=name, status=status)


def test_an_integrity_error_poisons_the_whole_transaction_without_a_savepoint(
    session_factory: sessionmaker[Session],
) -> None:
    """Establish the hazard the savepoint exists for.

    Without this, the tests below would look like they were proving that
    inserting a row works.
    """

    uow = SqlAlchemyUnitOfWork(session_factory)
    with uow:
        uow.session.add(profile())
        uow.flush()

        with pytest.raises(IntegrityError):
            uow.session.add(profile(name="Second Center"))
            uow.flush()

        # The transaction is now aborted. Any further work fails, including the
        # audit row a handler would want to write about the conflict.
        with pytest.raises(PendingRollbackError):
            uow.session.execute(text("SELECT 1"))


def test_a_savepoint_confines_the_failure_and_leaves_the_transaction_usable(
    session_factory: sessionmaker[Session],
) -> None:
    uow = SqlAlchemyUnitOfWork(session_factory)
    with uow:
        uow.session.add(profile())
        uow.flush()

        with pytest.raises(IntegrityError), uow.savepoint():
            uow.session.add(profile(name="Second Center"))
            uow.flush()

        # The whole point: work continues after a caught integrity error.
        survived = uow.session.execute(text("SELECT 1")).scalar()
        assert survived == 1

        uow.session.add(profile(name="Archived Center", status="retired"))
        uow.commit()

    with session_factory() as session:
        names = sorted(
            row[0] for row in session.execute(text("SELECT name FROM center_profile"))
        )
    assert names == ["Archived Center", "Golden Center"]


def test_the_rejected_row_is_not_committed_by_the_surrounding_transaction(
    session_factory: sessionmaker[Session],
) -> None:
    """A savepoint must undo the attempt, not merely tolerate it."""

    uow = SqlAlchemyUnitOfWork(session_factory)
    with uow:
        uow.session.add(profile())
        uow.flush()
        with pytest.raises(IntegrityError), uow.savepoint():
            uow.session.add(profile(name="Second Center"))
            uow.flush()
        uow.commit()

    with session_factory() as session:
        count = session.execute(text("SELECT count(*) FROM center_profile")).scalar()
    assert count == 1


def test_a_successful_savepoint_keeps_its_work(
    session_factory: sessionmaker[Session],
) -> None:
    uow = SqlAlchemyUnitOfWork(session_factory)
    with uow:
        with uow.savepoint():
            uow.session.add(profile())
        uow.commit()

    with session_factory() as session:
        count = session.execute(text("SELECT count(*) FROM center_profile")).scalar()
    assert count == 1


def test_savepoints_nest(session_factory: sessionmaker[Session]) -> None:
    """An inner failure must not discard the outer savepoint's work."""

    uow = SqlAlchemyUnitOfWork(session_factory)
    with uow:
        with uow.savepoint():
            uow.session.add(profile())
            uow.flush()
            with pytest.raises(IntegrityError), uow.savepoint():
                uow.session.add(profile(name="Second Center"))
                uow.flush()
        uow.commit()

    with session_factory() as session:
        names = [row[0] for row in session.execute(text("SELECT name FROM center_profile"))]
    assert names == ["Golden Center"]


class TestAfterCommitHooks:
    def test_hooks_run_only_after_a_successful_commit(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        ran: list[str] = []

        uow = SqlAlchemyUnitOfWork(session_factory)
        with uow:
            uow.after_commit(lambda _session: ran.append("first"))
            uow.after_commit(lambda _session: ran.append("second"))
            assert ran == [], "a registered hook must not run before the commit"
            uow.session.add(profile())
            uow.commit()

        assert ran == ["first", "second"]

    def test_hooks_are_discarded_on_rollback(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        ran: list[str] = []

        uow = SqlAlchemyUnitOfWork(session_factory)
        with uow:
            uow.after_commit(lambda _session: ran.append("must not run"))
            uow.session.add(profile())
            uow.rollback()

        assert ran == []

    def test_a_failing_hook_cannot_undo_the_commit(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """The transaction is already durable; raising here would report a lie.

        A caller told the command failed would reasonably retry work that has
        already taken effect.
        """

        def explode(_session: Session) -> None:
            raise RuntimeError("dispatch notification failed")

        uow = SqlAlchemyUnitOfWork(session_factory)
        with uow:
            uow.after_commit(explode)
            uow.session.add(profile())
            uow.commit()

        with session_factory() as session:
            count = session.execute(text("SELECT count(*) FROM center_profile")).scalar()
        assert count == 1

    def test_one_failing_hook_does_not_skip_the_others(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        ran: list[str] = []

        def explode(_session: Session) -> None:
            raise RuntimeError("first hook failed")

        uow = SqlAlchemyUnitOfWork(session_factory)
        with uow:
            uow.after_commit(explode)
            uow.after_commit(lambda _session: ran.append("second"))
            uow.session.add(profile())
            uow.commit()

        assert ran == ["second"]

    def test_a_hook_gets_its_own_session_and_can_write(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """A separate session, because the command's is committed and closing."""

        identifier = uuid.uuid4()

        def write_marker(session: Session) -> None:
            session.execute(
                text(
                    "INSERT INTO outbox_events (id, aggregate_type, aggregate_id, "
                    "aggregate_version, event_type, payload, payload_version) VALUES "
                    "(:id, 'center_profile', :id, 1, 'HookRan', '{}', 1)"
                ),
                {"id": identifier},
            )

        uow = SqlAlchemyUnitOfWork(session_factory)
        with uow:
            uow.after_commit(write_marker)
            uow.session.add(profile())
            uow.commit()

        with session_factory() as session:
            found = session.execute(
                text("SELECT event_type FROM outbox_events WHERE id = :id"), {"id": identifier}
            ).scalar()
        assert found == "HookRan"
