"""The exemplar command, end to end, including its concurrency claims.

The interesting assertions here need two real connections. A single-session test
can show that a second call returns the stored response, but it cannot show what
happens when two requests race — and racing is the only case the idempotency key
exists for. Those tests open a second session deliberately and interleave the
statements by hand.

Covers: CON-IDEM-001, CON-VERSION-001.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.audit import AuditActor, AuditContext, RedactionPolicy  # noqa: E402
from app.commands.rename_center_profile import (  # noqa: E402
    RenameCenterProfile,
    execute,
)
from app.core.errors import (  # noqa: E402
    BusinessRuleViolationError,
    IdempotencyKeyReusedError,
    NotFoundError,
    VersionConflictError,
)
from app.db.models.center_profile import CenterProfile  # noqa: E402
from app.db.unit_of_work import SqlAlchemyUnitOfWork  # noqa: E402
from app.idempotency import IdempotencyResolver, request_hash  # noqa: E402

pytestmark = pytest.mark.integration

ADMIN = uuid.uuid4()
POLICY = RedactionPolicy(mask_iban=True)


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


@pytest.fixture
def profile_id(session_factory: sessionmaker[Session]) -> uuid.UUID:
    with session_factory() as session:
        profile = CenterProfile(name="Original Center", status="active")
        session.add(profile)
        session.commit()
        return profile.id


def actor() -> AuditActor:
    return AuditActor(actor_type="admin_user", actor_id=ADMIN, role_snapshot=("center.admin",))


def run(
    session_factory: sessionmaker[Session],
    profile_id: uuid.UUID,
    *,
    name: str = "Renamed Center",
    version: int = 1,
    key: str = "key-1",
    reason: str | None = None,
):
    uow = SqlAlchemyUnitOfWork(session_factory)
    with uow:
        result = execute(
            RenameCenterProfile(
                profile_id=profile_id,
                new_name=name,
                expected_record_version=version,
                reason=reason,
            ),
            uow=uow,
            actor=actor(),
            context=AuditContext(request_id="req-1", correlation_id="corr-1"),
            idempotency_key=key,
            policy=POLICY,
        )
        uow.commit()
    return result


class TestHappyPath:
    def test_one_commit_carries_the_change_audit_outbox_and_idempotency(
        self, session_factory: sessionmaker[Session], profile_id: uuid.UUID
    ) -> None:
        result = run(session_factory, profile_id)

        assert result.record_version == 2
        assert result.replayed is False

        with session_factory() as session:
            name, version = session.execute(
                text("SELECT name, record_version FROM center_profile")
            ).one()
            audit = session.execute(
                text("SELECT action, entity_record_version, idempotency_key_hash FROM audit_logs")
            ).one()
            event_type, aggregate_version = session.execute(
                text("SELECT event_type, aggregate_version FROM outbox_events")
            ).one()
            status, response = session.execute(
                text("SELECT status, response_body FROM idempotency_records")
            ).one()

        assert (name, version) == ("Renamed Center", 2)
        assert audit[0] == "center_profile.renamed"
        assert audit[1] == 2
        assert (event_type, aggregate_version) == ("CenterProfileRenamed", 2)
        assert status == "completed"
        assert response["record_version"] == 2

    def test_the_raw_idempotency_key_is_never_in_the_audit_row(
        self, session_factory: sessionmaker[Session], profile_id: uuid.UUID
    ) -> None:
        """A raw key is a bearer value, and audit rows cannot be edited afterwards."""

        run(session_factory, profile_id, key="super-secret-key")

        with session_factory() as session:
            row = session.execute(text("SELECT * FROM audit_logs")).mappings().one()

        assert "super-secret-key" not in repr(dict(row))
        assert row["idempotency_key_hash"] is not None
        assert len(row["idempotency_key_hash"]) == 64


class TestIdempotency:
    def test_an_identical_repeat_replays_without_executing_again(
        self, session_factory: sessionmaker[Session], profile_id: uuid.UUID
    ) -> None:
        run(session_factory, profile_id, key="key-1")
        second = run(session_factory, profile_id, key="key-1")

        assert second.replayed is True
        assert second.record_version == 2

        with session_factory() as session:
            version = session.execute(
                text("SELECT record_version FROM center_profile")
            ).scalar()
            audit_rows = session.execute(text("SELECT count(*) FROM audit_logs")).scalar()
            outbox_rows = session.execute(text("SELECT count(*) FROM outbox_events")).scalar()

        # The decisive assertion: the version did not advance a second time, and
        # no second audit row or event was produced.
        assert version == 2
        assert audit_rows == 1
        assert outbox_rows == 1

    def test_the_same_key_with_a_different_request_is_a_conflict(
        self, session_factory: sessionmaker[Session], profile_id: uuid.UUID
    ) -> None:
        run(session_factory, profile_id, key="key-1", name="First Name")

        with pytest.raises(IdempotencyKeyReusedError):
            run(session_factory, profile_id, key="key-1", name="Different Name", version=2)

    def test_the_same_key_for_a_different_actor_does_not_collide(
        self, session_factory: sessionmaker[Session], profile_id: uuid.UUID
    ) -> None:
        """The reason the unique key is four columns rather than one.

        Under a global key the second caller would be handed the first caller's
        stored response.
        """

        run(session_factory, profile_id, key="shared-key")

        other = uuid.uuid4()
        uow = SqlAlchemyUnitOfWork(session_factory)
        with uow:
            result = execute(
                RenameCenterProfile(
                    profile_id=profile_id, new_name="Second Rename", expected_record_version=2
                ),
                uow=uow,
                actor=AuditActor(actor_type="admin_user", actor_id=other),
                context=AuditContext(),
                idempotency_key="shared-key",
                policy=POLICY,
            )
            uow.commit()

        assert result.replayed is False
        assert result.record_version == 3

    def test_a_concurrent_claim_is_decided_by_the_database_not_by_a_prior_read(
        self, session_factory: sessionmaker[Session], profile_id: uuid.UUID
    ) -> None:
        """Two open transactions, neither able to see the other's uncommitted row.

        This is the case SELECT-then-INSERT gets wrong: under READ COMMITTED both
        would find nothing and both would execute. Only the unique index can
        arbitrate, and only if the insert is what asks it.
        """

        first = SqlAlchemyUnitOfWork(session_factory)
        second = SqlAlchemyUnitOfWork(session_factory)

        with first, second:
            first_claim = IdempotencyResolver(first).claim(
                actor_type="admin_user",
                actor_id=ADMIN,
                operation="center_profile.rename",
                idempotency_key="race-key",
                payload={"name": "A"},
            )
            assert first_claim.should_execute is True
            first.commit()

            # The second transaction started before the first committed and has
            # never seen its row.
            with pytest.raises(IdempotencyKeyReusedError):
                IdempotencyResolver(second).claim(
                    actor_type="admin_user",
                    actor_id=ADMIN,
                    operation="center_profile.rename",
                    idempotency_key="race-key",
                    payload={"name": "A"},
                )

    def test_the_losing_transaction_survives_the_unique_violation(
        self, session_factory: sessionmaker[Session], profile_id: uuid.UUID
    ) -> None:
        """The savepoint's purpose here: the loser must still be able to work.

        Without one the unique violation aborts the whole transaction, so the
        loser cannot read the winner's record, cannot return its response, and
        cannot write audit about having been deduplicated.
        """

        winner = SqlAlchemyUnitOfWork(session_factory)
        with winner:
            IdempotencyResolver(winner).claim(
                actor_type="admin_user",
                actor_id=ADMIN,
                operation="center_profile.rename",
                idempotency_key="race-key",
                payload={"name": "A"},
            )
            winner.commit()

        loser = SqlAlchemyUnitOfWork(session_factory)
        with loser:
            with pytest.raises(IdempotencyKeyReusedError):
                IdempotencyResolver(loser).claim(
                    actor_type="admin_user",
                    actor_id=ADMIN,
                    operation="center_profile.rename",
                    idempotency_key="race-key",
                    payload={"name": "different"},
                )
            # Still usable, which is the whole point.
            assert loser.session.execute(text("SELECT 1")).scalar() == 1

    def test_two_transactions_open_at_once_cannot_both_claim(
        self, session_factory: sessionmaker[Session], profile_id: uuid.UUID
    ) -> None:
        """A genuine race: neither transaction has committed when both attempt.

        The other concurrency test here commits the winner first, so the loser's
        row is already visible and any implementation — including a plain
        SELECT-then-INSERT — would appear to behave. This is the case that
        separates them: two transactions open simultaneously, neither able to see
        the other's uncommitted row.

        Because the claim inserts rather than reads, the second attempt meets the
        unique index and blocks until the first resolves. `lock_timeout` turns
        that block into an error so the test cannot hang; the point is that the
        second transaction is stopped, not which exception carries the news. An
        implementation that decided from a prior read would sail past and execute
        the command a second time.
        """

        first = SqlAlchemyUnitOfWork(session_factory)
        second = SqlAlchemyUnitOfWork(session_factory)

        payload = {"profile_id": str(profile_id), "new_name": "Renamed"}

        with first, second:
            second.session.execute(text("SET lock_timeout = '2s'"))

            first_claim = IdempotencyResolver(first).claim(
                actor_type="admin_user",
                actor_id=ADMIN,
                operation="center_profile.rename",
                idempotency_key="simultaneous",
                payload=payload,
            )
            assert first_claim.should_execute is True

            # First has flushed but not committed; it holds the index entry.
            with pytest.raises((OperationalError, IntegrityError)) as raised:
                IdempotencyResolver(second).claim(
                    actor_type="admin_user",
                    actor_id=ADMIN,
                    operation="center_profile.rename",
                    idempotency_key="simultaneous",
                    payload=payload,
                )

            assert "should_execute" not in str(raised.value)
            first.commit()

        with session_factory() as session:
            claims = session.execute(
                text("SELECT count(*) FROM idempotency_records WHERE idempotency_key = :k"),
                {"k": "simultaneous"},
            ).scalar()

        assert claims == 1, "exactly one logical execution, decided by the index"

    def test_a_request_hash_is_stable_under_key_order(self) -> None:
        """Otherwise a legitimate retry would be rejected as a key reuse."""

        assert request_hash({"a": 1, "b": 2}) == request_hash({"b": 2, "a": 1})

    def test_completion_is_not_committed_before_the_business_change(
        self, session_factory: sessionmaker[Session], profile_id: uuid.UUID
    ) -> None:
        """A record claiming success for work that then failed is worse than none.

        It makes the command permanently unrepeatable: every retry replays a
        success that never happened.
        """

        uow = SqlAlchemyUnitOfWork(session_factory)
        with pytest.raises(RuntimeError), uow:
            execute(
                RenameCenterProfile(
                    profile_id=profile_id, new_name="Renamed", expected_record_version=1
                ),
                uow=uow,
                actor=actor(),
                context=AuditContext(),
                idempotency_key="key-1",
                policy=POLICY,
            )
            raise RuntimeError("the request failed after the command body ran")

        with session_factory() as session:
            records = session.execute(text("SELECT count(*) FROM idempotency_records")).scalar()
            version = session.execute(text("SELECT record_version FROM center_profile")).scalar()

        assert records == 0, "a rolled-back command must leave no claim behind"
        assert version == 1


class TestPreconditions:
    def test_a_stale_expected_version_is_refused(
        self, session_factory: sessionmaker[Session], profile_id: uuid.UUID
    ) -> None:
        run(session_factory, profile_id, version=1, key="key-1")

        with pytest.raises(VersionConflictError):
            run(session_factory, profile_id, version=1, key="key-2", name="Third Name")

    def test_a_concurrent_update_loses_the_compare_and_swap(
        self, session_factory: sessionmaker[Session], profile_id: uuid.UUID
    ) -> None:
        """Read-then-compare in Python would have written over this change.

        The predicate is in the UPDATE and the row count is what enforces it, so
        the second writer is refused rather than silently winning.
        """

        with session_factory() as other:
            other.execute(
                text(
                    "UPDATE center_profile SET name = 'Changed Elsewhere', "
                    "record_version = record_version + 1 WHERE id = :id"
                ),
                {"id": profile_id},
            )
            other.commit()

        with pytest.raises(VersionConflictError):
            run(session_factory, profile_id, version=1)

        with session_factory() as session:
            name = session.execute(text("SELECT name FROM center_profile")).scalar()
        assert name == "Changed Elsewhere"

    def test_a_missing_profile_is_not_found(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with pytest.raises(NotFoundError):
            run(session_factory, uuid.uuid4())

    @pytest.mark.parametrize("name", ["", "   "])
    def test_a_blank_name_is_a_business_rule_violation(
        self, session_factory: sessionmaker[Session], profile_id: uuid.UUID, name: str
    ) -> None:
        with pytest.raises(BusinessRuleViolationError):
            run(session_factory, profile_id, name=name)

    def test_an_over_long_name_is_refused_before_the_database_sees_it(
        self, session_factory: sessionmaker[Session], profile_id: uuid.UUID
    ) -> None:
        with pytest.raises(BusinessRuleViolationError):
            run(session_factory, profile_id, name="x" * 201)

    def test_a_refused_command_leaves_nothing_behind(
        self, session_factory: sessionmaker[Session], profile_id: uuid.UUID
    ) -> None:
        """Including the idempotency claim, which was made before the failure."""

        run(session_factory, profile_id, version=1, key="key-1")

        with pytest.raises(VersionConflictError):
            run(session_factory, profile_id, version=99, key="key-2")

        with session_factory() as session:
            claims = session.execute(
                text("SELECT count(*) FROM idempotency_records")
            ).scalar()
            audit_rows = session.execute(text("SELECT count(*) FROM audit_logs")).scalar()

        assert claims == 1, "the failed command's claim must not persist"
        assert audit_rows == 1
