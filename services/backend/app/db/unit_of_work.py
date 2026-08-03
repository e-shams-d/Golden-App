"""Transaction ownership: one command, one session, one commit.

Three capabilities here are not conveniences. Each exists because without it a
specific correctness property of the integrity spine is unreachable.

**Savepoints.** PostgreSQL aborts the entire transaction on an integrity error.
Every subsequent statement then fails with "current transaction is aborted", so
catching a unique violation, mapping it to a typed conflict and still writing the
audit row is impossible on a bare transaction — the audit insert would fail too.
A savepoint scopes the failure so only the attempted statement is undone.

**After-commit hooks.** Work that must not happen unless the transaction actually
committed, and must not be able to undo it if it fails. Dispatch notification is
the motivating case. They run on a separate session, after the commit, and their
failures are logged rather than raised.

**Explicit flush.** `app/db/session.py` sets `autoflush=False`, so a read inside
a command sees neither its own pending rows nor a unique violation that has not
been sent to the server yet. A check-then-insert written without a flush is a
race with itself, not merely with other transactions.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import TracebackType
from typing import Protocol, TypeVar, runtime_checkable

from sqlalchemy.orm import Session

from app.core.logging import get_logger, log_event
from app.db.session import SessionFactory

ExcT = TypeVar("ExcT", bound=BaseException)

AfterCommitHook = Callable[[Session], None]

logger = get_logger("db.unit_of_work")


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

    def flush(self) -> None: ...

    def savepoint(self) -> object: ...

    def after_commit(self, hook: AfterCommitHook) -> None: ...


class SqlAlchemyUnitOfWork:
    """Concrete UoW. Repositories added later receive this single session."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self._finished = False
        self._after_commit: list[AfterCommitHook] = []

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
        self._after_commit = []
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

    def flush(self) -> None:
        """Send pending changes to the server without ending the transaction.

        Needed before any read that must see this command's own writes, and
        before any check that depends on a constraint having been evaluated.
        With `autoflush=False` neither happens on its own.
        """

        self.session.flush()

    @contextmanager
    def savepoint(self) -> Iterator[None]:
        """Scope a failure so the surrounding transaction survives it.

        The caller still sees the exception. What changes is that the outer
        transaction is left usable, so a handler can map the failure to a typed
        error and go on to write audit in the same commit.

        Delegating to `begin_nested()`'s own context manager rather than driving
        commit and rollback by hand, which was measured against SQLAlchemy 2.0.44
        and PostgreSQL 16 and does not work: once a flush inside the savepoint
        fails, both the nested transaction and the session report `is_active`
        False, so a rollback guarded on `is_active` is skipped and the session
        stays poisoned. Every later statement then raises PendingRollbackError —
        the exact failure the savepoint was added to prevent, wearing the
        appearance of handling it. The context manager restores the session and
        discards the rejected object's pending state.
        """

        with self.session.begin_nested():
            yield

    def after_commit(self, hook: AfterCommitHook) -> None:
        """Register work to run only if this transaction commits.

        Registering is not doing. Nothing here runs on a rollback, and nothing
        here can cause one.
        """

        if self._finished:
            raise RuntimeError("after-commit hooks cannot be registered after finalization")
        self._after_commit.append(hook)

    def commit(self) -> None:
        if self._finished:
            raise RuntimeError("UnitOfWork transaction is already finalized")
        self.session.commit()
        self._finished = True
        self._run_after_commit_hooks()

    def _run_after_commit_hooks(self) -> None:
        """Run every hook, on a fresh session, and let none of them fail the command.

        The transaction is already durable by the time this runs. Raising here
        would report failure for work that succeeded, and the caller would
        reasonably retry a command that has already taken effect. Each hook is
        isolated from the others for the same reason: the second must not be
        skipped because the first failed.
        """

        hooks, self._after_commit = self._after_commit, []
        for hook in hooks:
            hook_session = self._session_factory()
            try:
                hook(hook_session)
                hook_session.commit()
            except Exception:
                hook_session.rollback()
                log_event(
                    logger,
                    logging.ERROR,
                    "after_commit_hook_failed",
                    hook=getattr(hook, "__name__", repr(hook)),
                    # The business transaction is committed and stays committed.
                    # This is an operational problem, not a data-integrity one.
                    committed_state_retained=True,
                )
            finally:
                hook_session.close()

    def rollback(self) -> None:
        if self._finished:
            return
        self.session.rollback()
        self._finished = True
        # Discarded rather than run: these were registered by work that did not
        # take effect.
        self._after_commit = []


class UnitOfWorkFactory:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def __call__(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self._session_factory)
