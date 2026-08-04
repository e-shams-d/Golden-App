"""Concurrency primitives, against real concurrent sessions.

None of this is observable with one connection. A compare-and-swap that loses
races still passes every single-session test, because there is nothing to lose a
race against. So each test here opens genuinely separate sessions and interleaves
them by hand.

The deadlock test is the reason slice 2 came first: with no `lock_timeout` a
lock-ordering regression hangs CI until someone kills it. With one, it fails in
seconds and says what happened.
"""

from __future__ import annotations

import sys
import threading
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.errors import NotFoundError, VersionConflictError  # noqa: E402
from app.db.concurrency import PROHIBITED_TOKENS, compare_and_swap  # noqa: E402
from app.db.locking import (  # noqa: E402
    ADVISORY_LOCK_NAMESPACE,
    LockScope,
    LockTarget,
    advisory_key,
    ordered,
)
from app.db.models.center_profile import CenterProfile  # noqa: E402

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


@pytest.fixture(autouse=True)
def clean_tables(session_factory: sessionmaker[Session]) -> Iterator[None]:
    yield
    with session_factory() as session:
        session.execute(text("DELETE FROM center_profile"))
        session.commit()


@pytest.fixture
def profile_id(session_factory: sessionmaker[Session]) -> uuid.UUID:
    with session_factory() as session:
        profile = CenterProfile(name="Original", status="active")
        session.add(profile)
        session.commit()
        return profile.id


class TestCompareAndSwap:
    """CON-001 shape."""

    def test_two_concurrent_writers_leave_exactly_one_winner(
        self, session_factory: sessionmaker[Session], profile_id: uuid.UUID
    ) -> None:
        """Both read the same version, both try to write it.

        This is the case a Python-side check gets wrong: both reads see version 1,
        both comparisons pass, and the second write silently overwrites the first.
        """

        first = session_factory()
        second = session_factory()
        try:
            compare_and_swap(
                first,
                CenterProfile,
                entity_id=profile_id,
                expected_version=1,
                values={"name": "Winner"},
            )
            first.commit()

            with pytest.raises(VersionConflictError):
                compare_and_swap(
                    second,
                    CenterProfile,
                    entity_id=profile_id,
                    expected_version=1,
                    values={"name": "Loser"},
                )
            second.rollback()
        finally:
            first.close()
            second.close()

        with session_factory() as session:
            name, version = session.execute(
                text("SELECT name, record_version FROM center_profile")
            ).one()

        assert name == "Winner", "the stale writer overwrote the winner"
        assert version == 2, "the version moved by more or less than one"

    def test_a_missing_row_is_not_reported_as_a_conflict(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """404 and 412 ask the client for different things.

        "Reload and retry" is useless advice about a row that does not exist, and
        a client told to retry will keep retrying.
        """

        with session_factory() as session, pytest.raises(NotFoundError):
            compare_and_swap(
                session,
                CenterProfile,
                entity_id=uuid.uuid4(),
                expected_version=1,
                values={"name": "x"},
            )

    def test_the_version_advances_by_exactly_one(
        self, session_factory: sessionmaker[Session], profile_id: uuid.UUID
    ) -> None:
        with session_factory() as session:
            for expected in (1, 2, 3):
                outcome = compare_and_swap(
                    session,
                    CenterProfile,
                    entity_id=profile_id,
                    expected_version=expected,
                    values={"name": f"Name {expected}"},
                )
                assert outcome.new_version == expected + 1
            session.commit()

        with session_factory() as session:
            version = session.execute(text("SELECT record_version FROM center_profile")).scalar()
        assert version == 4

    @pytest.mark.parametrize("token", sorted(PROHIBITED_TOKENS))
    def test_a_prohibited_token_is_refused(
        self, session_factory: sessionmaker[Session], profile_id: uuid.UUID, token: str
    ) -> None:
        """Refused in code, not discouraged in a comment.

        `xmin` wraps and does not survive a restore; `updated_at` cannot separate
        two updates in one clock tick; a content hash can be rewritten to the same
        value, which makes a lost update invisible rather than detected.
        """

        with session_factory() as session, pytest.raises(ValueError, match="concurrency token"):
            compare_and_swap(
                session,
                CenterProfile,
                entity_id=profile_id,
                expected_version=1,
                values={"name": "x"},
                version_column=token,
            )


class TestGlobalLockOrdering:
    """CON-LOCKORDER-001."""

    def test_the_ordering_is_scope_then_table_then_key(self) -> None:
        early = LockTarget.of(LockScope.TRADER_STATUS, CenterProfile, uuid.UUID(int=2))
        late = LockTarget.of(LockScope.RESULT_PUBLISH, CenterProfile, uuid.UUID(int=1))

        # Scope wins over primary key: a cross-table cycle is exactly what a
        # per-table sort cannot fix.
        assert ordered([late, early]) == [early, late]

    def test_ordering_is_stable_regardless_of_input_order(self) -> None:
        targets = [
            LockTarget.of(LockScope.EXPORT_MARK_SENT, CenterProfile, uuid.UUID(int=3)),
            LockTarget.of(LockScope.TRADER_STATUS, CenterProfile, uuid.UUID(int=9)),
            LockTarget.of(LockScope.TRADER_STATUS, CenterProfile, uuid.UUID(int=1)),
        ]

        assert ordered(targets) == ordered(list(reversed(targets)))

    def test_duplicates_collapse(self) -> None:
        one = LockTarget.of(LockScope.TRADER_STATUS, CenterProfile, uuid.UUID(int=1))

        assert ordered([one, one]) == [one]

    def test_opposing_orders_deadlock_and_the_helper_serialises(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """The regression this rule exists to prevent, demonstrated both ways.

        First: two sessions locking the same two rows in opposite orders. One is
        killed by PostgreSQL's deadlock detector, or gives up on `lock_timeout`.
        Second: the same two sessions, both ordering through the helper, both
        succeed.

        Without the first half the second proves nothing — two sessions that never
        actually contend also "both succeed".
        """

        with session_factory() as session:
            left = CenterProfile(name="Left", status="retired")
            right = CenterProfile(name="Right", status="archived")
            session.add_all([left, right])
            session.commit()
            first_id, second_id = sorted([left.id, right.id], key=str)

        def lock_in_order(
            order: list[uuid.UUID],
            results: list[str],
            label: str,
            gate: threading.Barrier | None,
        ) -> None:
            try:
                with session_factory() as session:
                    for identifier in order:
                        session.execute(
                            text("SELECT id FROM center_profile WHERE id = :id FOR UPDATE"),
                            {"id": identifier},
                        )
                        if gate is not None:
                            # Only for the clashing phase: hold the first lock
                            # until the other session holds its first, which is
                            # what makes the crossing inevitable rather than
                            # occasional.
                            gate.wait(timeout=10)
                    session.commit()
                results.append(f"{label}:ok")
            except Exception as error:
                # The failure mode is the subject here, so every exception type is
                # recorded rather than any being allowed to escape the thread.
                results.append(f"{label}:{type(error).__name__}")

        def run(
            pairs: list[tuple[list[uuid.UUID], str]], gate: threading.Barrier | None
        ) -> list[str]:
            results: list[str] = []
            threads = [
                threading.Thread(target=lock_in_order, args=(order, results, label, gate))
                for order, label in pairs
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
            assert not any(thread.is_alive() for thread in threads), (
                "a session was still blocked after 30s, so neither the deadlock "
                "detector nor lock_timeout intervened"
            )
            return sorted(results)

        # --- opposing orders: contention is real ---
        clashing = run(
            [([first_id, second_id], "a"), ([second_id, first_id], "b")],
            threading.Barrier(2, timeout=10),
        )
        assert any(not outcome.endswith(":ok") for outcome in clashing), (
            f"opposing lock orders did not contend, so the check below is vacuous: {clashing}"
        )

        # --- both ordered through the helper ---
        # No barrier here, and that is not a simplification: correct serialisation
        # means the second session *blocks* on the first lock and never reaches a
        # rendezvous. A barrier would time out and report a failure caused by the
        # test rather than by the code. Found by writing it the other way first.
        canonical = [
            target.primary_key
            for target in ordered(
                [
                    LockTarget.of(LockScope.TRADER_STATUS, CenterProfile, first_id),
                    LockTarget.of(LockScope.TRADER_STATUS, CenterProfile, second_id),
                ]
            )
        ]
        serialised = run([(canonical, "a"), (list(canonical), "b")], None)

        assert serialised == ["a:ok", "b:ok"], (
            f"both sessions ordered by the global rule and still failed: {serialised}"
        )


class TestAdvisoryLocks:
    def test_keys_are_stable_and_namespaced(self) -> None:
        namespace, key = advisory_key(LockScope.EXPORT_MARK_SENT, "batch-7")

        assert namespace == ADVISORY_LOCK_NAMESPACE
        assert advisory_key(LockScope.EXPORT_MARK_SENT, "batch-7") == (namespace, key)

    def test_different_scopes_do_not_collide_on_one_discriminator(self) -> None:
        first = advisory_key(LockScope.EXPORT_MARK_SENT, "batch-7")
        second = advisory_key(LockScope.RESULT_PUBLISH, "batch-7")

        assert first != second, (
            "two coordination points would serialise against each other for no "
            "reason, and an operator reading pg_locks could not tell them apart"
        )

    def test_the_key_fits_a_signed_32_bit_argument(self) -> None:
        """pg_advisory_xact_lock(int, int) rejects anything wider."""

        _namespace, key = advisory_key(LockScope.PAYMENT_ATTEMPT_CONFIRM, "x" * 200)

        assert -(2**31) <= key < 2**31
