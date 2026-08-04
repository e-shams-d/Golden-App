"""Per-connection limits must be enforced by the server, not merely configured.

A `SET` that never runs looks identical to one that does, from the application's
side. So these read the settings back from the connection PostgreSQL actually
gave us, and then make the limits bite: a real second session holds a real row
lock while a real statement waits for it.

The blocking case is the reason any of this exists. `task_acks_late` is on and
worker prefetch is 1, so a task blocked forever on a contended
`SELECT ... FOR UPDATE` is redelivered on top of the locks the first attempt
still holds. Each redelivery adds a waiter; the queue drains only when someone
kills a backend by hand.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.db.session import create_engine_and_session_factory  # noqa: E402

pytestmark = pytest.mark.integration

LOCK_TIMEOUT_MS = 400


def _sqlalchemy_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture
def settings(migrated_database: str, tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=_sqlalchemy_url(migrated_database),
        redis_url="redis://127.0.0.1:6379/0",
        local_storage_root=tmp_path / "storage",
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        # Short enough that a blocked statement fails inside a test rather than
        # holding the suite for thirty seconds.
        lock_timeout_ms=LOCK_TIMEOUT_MS,
        statement_timeout_ms=5_000,
        idle_in_transaction_timeout_ms=10_000,
    )


@pytest.fixture
def engine_and_factory(settings: Settings) -> Iterator[tuple[Engine, sessionmaker[Session]]]:
    engine, factory = create_engine_and_session_factory(settings)
    try:
        yield engine, factory
    finally:
        engine.dispose()


@pytest.fixture
def profile_id(migrated_database: str) -> Iterator[str]:
    url = migrated_database.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(url, autocommit=True) as connection:
        row = connection.execute(
            "INSERT INTO center_profile (name, status) VALUES ('Locked Center', 'active') "
            "RETURNING id"
        ).fetchone()
        assert row is not None
        identifier = str(row[0])
    yield identifier
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute("DELETE FROM center_profile")


class TestTheLimitsReachTheConnection:
    def test_every_limit_is_set_on_the_connection_postgresql_gave_us(
        self, engine_and_factory: tuple[Engine, sessionmaker[Session]]
    ) -> None:
        """Read back from the server, not from Settings.

        Asserting the configuration would only prove the value was typed
        correctly, which is not the thing that can go wrong.
        """

        _engine, factory = engine_and_factory
        with factory() as session:
            values = {
                name: session.execute(text(f"SHOW {name}")).scalar()
                for name in (
                    "statement_timeout",
                    "lock_timeout",
                    "idle_in_transaction_session_timeout",
                )
            }

        assert values["lock_timeout"] == f"{LOCK_TIMEOUT_MS}ms"
        assert values["statement_timeout"] == "5s"
        assert values["idle_in_transaction_session_timeout"] == "10s"

    def test_a_later_connection_gets_them_too(
        self, engine_and_factory: tuple[Engine, sessionmaker[Session]]
    ) -> None:
        """The pool opens connections long after startup.

        Applying these once at boot would leave every replacement connection
        unlimited, and the failure would appear only under the load that forced
        the pool to grow.
        """

        engine, factory = engine_and_factory
        with factory() as session:
            session.execute(text("SELECT 1"))
        # Discard every pooled connection; the next checkout is a fresh connect.
        engine.dispose()

        with factory() as session:
            value = session.execute(text("SHOW lock_timeout")).scalar()

        assert value == f"{LOCK_TIMEOUT_MS}ms"


class TestTheLimitsBite:
    def test_a_contended_row_lock_gives_up_instead_of_waiting_forever(
        self,
        engine_and_factory: tuple[Engine, sessionmaker[Session]],
        migrated_database: str,
        profile_id: str,
    ) -> None:
        """Run the blocked statement on a thread, so its absence fails rather than hangs.

        Learned by breaking it: with the limit removed the statement never
        returns, so a straightforward `pytest.raises` turns this test into an
        indefinite hang. A hang is the worst possible failure shape — CI reports
        a timeout with no cause, and the run has to be killed. Joining with a
        deadline converts that into an assertion that names what went wrong.
        """

        _engine, factory = engine_and_factory
        blocker_url = migrated_database.replace("postgresql+psycopg://", "postgresql://", 1)
        outcome: dict[str, object] = {}

        def attempt_locked_read() -> None:
            started = time.monotonic()
            try:
                with factory() as session:
                    session.execute(
                        text("SELECT id FROM center_profile WHERE id = :id FOR UPDATE"),
                        {"id": profile_id},
                    )
                outcome["result"] = "acquired"
            except DBAPIError as error:
                outcome["result"] = "refused"
                outcome["message"] = str(error)
            outcome["waited"] = time.monotonic() - started

        with psycopg.connect(blocker_url) as blocker:
            # A real lock, held for the duration of this block.
            blocker.execute(
                "SELECT id FROM center_profile WHERE id = %s FOR UPDATE", (profile_id,)
            )

            waiter = threading.Thread(target=attempt_locked_read, daemon=True)
            waiter.start()
            waiter.join(timeout=15)
            still_waiting = waiter.is_alive()

            blocker.rollback()

        assert not still_waiting, (
            "the blocked statement was still waiting after 15 seconds, so no lock "
            "timeout applied. In production Celery would redeliver the task on top "
            "of the locks this attempt still holds."
        )
        assert outcome["result"] == "refused", (
            f"the lock was acquired rather than refused: {outcome}"
        )

        # The bound is what makes this specific to `lock_timeout`. Found by
        # breaking it: with `lock_timeout` removed the statement is still
        # cancelled — by `statement_timeout`, five seconds later — so a generous
        # bound passed while the limit under test did nothing. The fixture sets
        # lock_timeout to 400ms and statement_timeout to 5s, and this window sits
        # between them, so only the lock timeout can satisfy it.
        waited = float(outcome["waited"])  # type: ignore[arg-type]
        assert waited < 2.0, (
            f"the statement was refused after {waited:.1f}s, which is the "
            "statement_timeout backstop rather than the lock timeout; lock waits "
            "are not being bounded"
        )
        assert "lock" in str(outcome["message"]).lower(), (
            f"the statement failed, but not on the lock timeout: {outcome['message']}"
        )

    def test_an_uncontended_lock_is_unaffected(
        self,
        engine_and_factory: tuple[Engine, sessionmaker[Session]],
        profile_id: str,
    ) -> None:
        """The limit must not break the ordinary path it exists to protect."""

        _engine, factory = engine_and_factory
        with factory() as session:
            row = session.execute(
                text("SELECT id FROM center_profile WHERE id = :id FOR UPDATE"),
                {"id": profile_id},
            ).fetchone()
            session.commit()

        assert row is not None

    def test_a_statement_that_runs_too_long_is_cancelled(
        self, migrated_database: str, tmp_path: Path
    ) -> None:
        """statement_timeout, proven with a sleep rather than a contrived query."""

        settings = Settings(
            _env_file=None,
            app_env="test",
            database_url=_sqlalchemy_url(migrated_database),
            redis_url="redis://127.0.0.1:6379/0",
            local_storage_root=tmp_path / "storage",
            release_commit="abcdef1234567",
            log_level="CRITICAL",
            statement_timeout_ms=300,
        )
        engine, factory = create_engine_and_session_factory(settings)
        try:
            with factory() as session, pytest.raises(OperationalError) as raised:
                session.execute(text("SELECT pg_sleep(5)"))
        finally:
            engine.dispose()

        assert "statement timeout" in str(raised.value).lower()


class TestThePoolDeadlineIsIndependent:
    def test_the_pool_timeout_does_not_follow_the_probe_deadline(
        self, migrated_database: str, tmp_path: Path
    ) -> None:
        """The correction itself.

        These were the same value. A background poller alongside request traffic
        then produced 500s at low concurrency, and the only available remedy —
        raising the number — loosened every health probe with it.
        """

        settings = Settings(
            _env_file=None,
            app_env="test",
            database_url=_sqlalchemy_url(migrated_database),
            redis_url="redis://127.0.0.1:6379/0",
            local_storage_root=tmp_path / "storage",
            release_commit="abcdef1234567",
            log_level="CRITICAL",
            dependency_timeout_seconds=0.2,
            db_pool_timeout_seconds=12.0,
        )
        engine, _factory = create_engine_and_session_factory(settings)
        try:
            assert engine.pool.timeout() == 12.0  # type: ignore[attr-defined]
        finally:
            engine.dispose()

        assert settings.dependency_timeout_seconds == 0.2, (
            "tightening the health probe must not tighten the pool with it"
        )

    def test_pool_size_and_overflow_are_deliberate(
        self, migrated_database: str, tmp_path: Path
    ) -> None:
        settings = Settings(
            _env_file=None,
            app_env="test",
            database_url=_sqlalchemy_url(migrated_database),
            redis_url="redis://127.0.0.1:6379/0",
            local_storage_root=tmp_path / "storage",
            release_commit="abcdef1234567",
            log_level="CRITICAL",
            db_pool_size=3,
            db_max_overflow=2,
        )
        engine, _factory = create_engine_and_session_factory(settings)
        try:
            assert engine.pool.size() == 3  # type: ignore[attr-defined]
        finally:
            engine.dispose()
