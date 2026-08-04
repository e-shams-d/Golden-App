"""Synchronous SQLAlchemy engine/session construction.

Two things here are corrections rather than configuration.

**The pool deadline is its own setting.** It used to be
`dependency_timeout_seconds`, which is how long a health probe waits before
calling a dependency down — a value with a reason to be short. Bound together,
adding a background poller alongside request traffic produced 500s at low
concurrency, and the only fix available was to raise a number that simultaneously
loosened every health probe.

**Per-connection timeouts are set on every connection.** PostgreSQL enforces
them; the application cannot be relied on to notice it has been waiting. Without
them a task blocked on a contended row waits forever while Celery — `task_acks_late`
with prefetch 1 — redelivers it on top of the locks the first attempt still
holds, so each redelivery adds a waiter and the queue drains only by hand.

They are applied through a `connect` event rather than the URL's `options`
parameter, because a URL carrying `-c statement_timeout=...` is easy to lose when
a connection string is rebuilt, and impossible to see in a driver-level trace.
"""

from __future__ import annotations

import math

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings

SessionFactory = sessionmaker[Session]


def _session_settings(settings: Settings) -> tuple[tuple[str, int], ...]:
    """The per-connection limits, as (parameter, milliseconds) pairs.

    Zero means unlimited in PostgreSQL. It is allowed here so an operator can
    disable one deliberately for a maintenance session, and the pair is simply
    skipped rather than sent as `SET x = 0`, which reads as a mistake in a log.
    """

    return (
        ("statement_timeout", settings.statement_timeout_ms),
        ("lock_timeout", settings.lock_timeout_ms),
        ("idle_in_transaction_session_timeout", settings.idle_in_transaction_timeout_ms),
    )


def create_engine_and_session_factory(settings: Settings) -> tuple[Engine, SessionFactory]:
    engine = create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        connect_args={
            "connect_timeout": max(1, math.ceil(settings.dependency_timeout_seconds)),
            "application_name": f"{settings.service_name}:{settings.release_version}",
        },
    )

    limits = tuple((name, value) for name, value in _session_settings(settings) if value > 0)

    @event.listens_for(engine, "connect")
    def _apply_session_limits(dbapi_connection: object, _record: object) -> None:
        # Runs on every physical connection, including one the pool opens hours
        # later to replace a recycled member. Setting these once at startup would
        # leave every later connection unlimited.
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            for name, value in limits:
                # Identifiers are from the fixed tuple above, never from input.
                cursor.execute(f"SET {name} = {int(value)}")
        finally:
            cursor.close()

    factory = sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )
    return engine, factory
