from __future__ import annotations

import pytest
from app.db.unit_of_work import SqlAlchemyUnitOfWork


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closes += 1


def test_uow_requires_context_entry() -> None:
    uow = SqlAlchemyUnitOfWork(lambda: FakeSession())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="entered"):
        _ = uow.session


def test_uow_rolls_back_uncommitted_scope_and_closes_session() -> None:
    session = FakeSession()
    uow = SqlAlchemyUnitOfWork(lambda: session)  # type: ignore[arg-type]

    with uow:
        assert uow.session is session

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closes == 1


def test_uow_commit_is_explicit_and_final() -> None:
    session = FakeSession()
    uow = SqlAlchemyUnitOfWork(lambda: session)  # type: ignore[arg-type]

    with uow:
        uow.commit()
        with pytest.raises(RuntimeError, match="finalized"):
            uow.commit()

    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closes == 1


def test_uow_rolls_back_when_command_raises() -> None:
    session = FakeSession()
    uow = SqlAlchemyUnitOfWork(lambda: session)  # type: ignore[arg-type]

    with pytest.raises(ValueError), uow:
        raise ValueError("command failed")

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closes == 1
