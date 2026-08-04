"""JOB-EAGER-001: a dispatched task must never observe uncommitted rows.

`celery_task_always_eager` is a real setting and tests use it. Under it `.delay()`
does not enqueue — it runs the task **inline, immediately**, inside the caller's
transaction. A task that opens its own session then sees the database as it was
before the command, so it either fails on a row that does not exist yet or, worse,
acts on stale state and reports success.

The trap is that it looks fine in development, where eager mode is on and the
task happens to use the caller's session, and breaks in production, where the
task runs in another process minutes later.

So dispatch goes through the after-commit hook registry. These tests drive both
orders against a real database and assert what each one can see.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.db.models.center_profile import CenterProfile  # noqa: E402
from app.db.unit_of_work import UnitOfWorkFactory  # noqa: E402
from app.workers.base import enqueue_after_commit  # noqa: E402

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


def count_from_a_separate_session(session_factory: sessionmaker[Session]) -> int:
    """What a task in another process would see: only committed rows."""

    with session_factory() as session:
        return session.execute(text("SELECT count(*) FROM center_profile")).scalar() or 0


def test_a_task_dispatched_before_the_commit_cannot_see_the_work(
    session_factory: sessionmaker[Session], uow_factory: UnitOfWorkFactory
) -> None:
    """The bug, demonstrated rather than described.

    Dispatching inline mid-transaction is what `.delay()` does under eager mode.
    A task opening its own session finds nothing, because nothing is committed.
    """

    observed: list[int] = []

    with uow_factory() as uow:
        uow.session.add(CenterProfile(name="Pending", status="active"))
        uow.flush()

        # Dispatched here, as an eager `.delay()` would be.
        observed.append(count_from_a_separate_session(session_factory))

        uow.commit()

    assert observed == [0], (
        "the separate session saw uncommitted rows, so this test cannot "
        "demonstrate the hazard it exists for"
    )


def test_a_task_dispatched_after_commit_sees_the_work(
    session_factory: sessionmaker[Session], uow_factory: UnitOfWorkFactory
) -> None:
    observed: list[int] = []

    with uow_factory() as uow:
        uow.session.add(CenterProfile(name="Committed", status="active"))
        enqueue_after_commit(
            uow,
            lambda: observed.append(count_from_a_separate_session(session_factory)),
            task_name="observe",
        )
        uow.commit()

    assert observed == [1], (
        "the after-commit dispatch did not see the committed row, so the hook "
        "ran too early"
    )


def test_a_rolled_back_command_dispatches_nothing(
    uow_factory: UnitOfWorkFactory,
) -> None:
    """A dispatch for work that did not happen is worse than a missed one.

    The consumer would act on a change no row records.
    """

    dispatched: list[str] = []

    with uow_factory() as uow:
        uow.session.add(CenterProfile(name="Discarded", status="active"))
        enqueue_after_commit(uow, lambda: dispatched.append("sent"), task_name="observe")
        uow.rollback()

    assert dispatched == []


def test_a_failing_dispatch_does_not_undo_the_commit(
    session_factory: sessionmaker[Session], uow_factory: UnitOfWorkFactory
) -> None:
    """AUD-OUTBOX-007: notification failure must not roll back financial state.

    By the time the hook runs the transaction is durable. Raising would report
    failure for work that succeeded, and a caller told the command failed would
    reasonably retry something that already took effect.
    """

    def explode() -> None:
        raise RuntimeError("broker unreachable")

    with uow_factory() as uow:
        uow.session.add(CenterProfile(name="Survives", status="active"))
        enqueue_after_commit(uow, explode, task_name="observe")
        uow.commit()

    assert count_from_a_separate_session(session_factory) == 1


def test_dispatch_order_follows_registration_order(
    uow_factory: UnitOfWorkFactory,
) -> None:
    """Two events from one command arrive in the order the command produced them."""

    order: list[str] = []

    with uow_factory() as uow:
        uow.session.add(CenterProfile(name="Ordered", status="active"))
        enqueue_after_commit(uow, lambda: order.append("first"), task_name="a")
        enqueue_after_commit(uow, lambda: order.append("second"), task_name="b")
        uow.commit()

    assert order == ["first", "second"]


def test_the_identifier_a_task_receives_is_readable_after_commit(
    session_factory: sessionmaker[Session], uow_factory: UnitOfWorkFactory
) -> None:
    """A task is given an id, never an ORM instance.

    The instance belongs to a session that is closing; a task in another process
    has no access to it, and one in the same process would be reading an object
    whose session is gone.
    """

    captured: list[uuid.UUID] = []

    with uow_factory() as uow:
        profile = CenterProfile(name="Identified", status="active")
        uow.session.add(profile)
        uow.flush()
        identifier = profile.id
        enqueue_after_commit(uow, lambda: captured.append(identifier), task_name="observe")
        uow.commit()

    assert len(captured) == 1
    with session_factory() as session:
        found = session.execute(
            text("SELECT name FROM center_profile WHERE id = :id"), {"id": captured[0]}
        ).scalar()
    assert found == "Identified"
