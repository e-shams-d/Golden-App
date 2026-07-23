"""Transaction ownership contract without premature business repositories."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, TypeVar, runtime_checkable

from sqlalchemy.orm import Session

from app.db.session import SessionFactory

ExcT = TypeVar("ExcT", bound=BaseException)


@runtime_checkable
class UnitOfWork(Protocol):
    """One command owns one session and explicit final commit/rollback."""

    session: Session

    def __enter__(self) -> UnitOfWork: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class SqlAlchemyUnitOfWork:
    """Concrete UoW. Repositories added later receive this single session."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self._finished = False

    @property
    def session(self) -> Session:
        if self._session is None:
            raise RuntimeError("UnitOfWork must be entered before its session is used")
        return self._session

    def __enter__(self) -> SqlAlchemyUnitOfWork:
        if self._session is not None:
            raise RuntimeError("UnitOfWork instances cannot be re-entered")
        self._session = self._session_factory()
        self._finished = False
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if not self._finished:
                self.rollback()
        finally:
            self.session.close()

    def commit(self) -> None:
        if self._finished:
            raise RuntimeError("UnitOfWork transaction is already finalized")
        self.session.commit()
        self._finished = True

    def rollback(self) -> None:
        if self._finished:
            return
        self.session.rollback()
        self._finished = True


class UnitOfWorkFactory:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def __call__(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self._session_factory)
