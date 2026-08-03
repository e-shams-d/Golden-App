"""The audit row, the outbox event and the business change share one fate.

This is the property the whole slice exists for, and it is not observable
without a real transaction: a stubbed session would let all three "succeed"
independently. So each test drives a real commit or a real rollback and then
reconnects on a different session to see what actually became durable.
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

from app.audit import (  # noqa: E402
    AuditActor,
    AuditContext,
    AuditEntry,
    AuditWriter,
    OutboxMessage,
    OutboxWriter,
    RedactionPolicy,
)
from app.audit.redaction import REDACTED  # noqa: E402
from app.db.models.center_profile import CenterProfile  # noqa: E402
from app.db.unit_of_work import SqlAlchemyUnitOfWork  # noqa: E402

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


def actor() -> AuditActor:
    return AuditActor(actor_type="admin_user", actor_id=ADMIN, role_snapshot=("center.admin",))


def entry(**overrides: object) -> AuditEntry:
    values: dict[str, object] = {
        "action": "center_profile.renamed",
        "outcome": "success",
        "metadata_schema": "audit.center_profile",
        "metadata_version": 1,
        **overrides,
    }
    return AuditEntry(**values)  # type: ignore[arg-type]


def message(aggregate_id: uuid.UUID, **overrides: object) -> OutboxMessage:
    values: dict[str, object] = {
        "aggregate_type": "center_profile",
        "aggregate_id": aggregate_id,
        "aggregate_version": 1,
        "event_type": "CenterProfileRenamed",
        "payload": {"name": "Golden Center"},
        "payload_version": 1,
        **overrides,
    }
    return OutboxMessage(**values)  # type: ignore[arg-type]


def counts(session_factory: sessionmaker[Session]) -> tuple[int, int, int]:
    with session_factory() as session:
        return (
            session.execute(text("SELECT count(*) FROM center_profile")).scalar() or 0,
            session.execute(text("SELECT count(*) FROM audit_logs")).scalar() or 0,
            session.execute(text("SELECT count(*) FROM outbox_events")).scalar() or 0,
        )


def test_all_three_become_durable_in_one_commit(
    session_factory: sessionmaker[Session],
) -> None:
    uow = SqlAlchemyUnitOfWork(session_factory)
    with uow:
        profile = CenterProfile(name="Golden Center", status="active")
        uow.session.add(profile)
        uow.flush()

        AuditWriter(uow.session, POLICY).record(
            entry(entity_type="center_profile", entity_id=profile.id),
            actor=actor(),
            context=AuditContext(request_id="req-1", correlation_id="corr-1"),
        )
        OutboxWriter(uow.session, POLICY).enqueue(message(profile.id))
        uow.commit()

    assert counts(session_factory) == (1, 1, 1)


def test_a_rollback_discards_all_three(session_factory: sessionmaker[Session]) -> None:
    """The audit row must not survive a change that did not happen.

    An audit trail recording commands that were rolled back is worse than none:
    it asserts events that never occurred.
    """

    uow = SqlAlchemyUnitOfWork(session_factory)
    with uow:
        profile = CenterProfile(name="Golden Center", status="active")
        uow.session.add(profile)
        uow.flush()
        AuditWriter(uow.session, POLICY).record(
            entry(entity_id=profile.id), actor=actor(), context=AuditContext()
        )
        OutboxWriter(uow.session, POLICY).enqueue(message(profile.id))
        uow.rollback()

    assert counts(session_factory) == (0, 0, 0)


def test_an_exception_leaves_nothing_behind(session_factory: sessionmaker[Session]) -> None:
    uow = SqlAlchemyUnitOfWork(session_factory)
    with pytest.raises(RuntimeError), uow:
        profile = CenterProfile(name="Golden Center", status="active")
        uow.session.add(profile)
        uow.flush()
        AuditWriter(uow.session, POLICY).record(
            entry(entity_id=profile.id), actor=actor(), context=AuditContext()
        )
        raise RuntimeError("command failed after writing audit")

    assert counts(session_factory) == (0, 0, 0)


def test_a_conflict_can_be_caught_and_still_audited_in_the_same_commit(
    session_factory: sessionmaker[Session],
) -> None:
    """The motivating case for savepoints, end to end.

    A denied command still has to be recorded. Without a savepoint the integrity
    error would abort the transaction and the audit insert would fail too, so the
    only trace of the refusal would be in a log nobody treats as evidence.
    """

    with session_factory() as setup:
        setup.add(CenterProfile(name="Existing Center", status="active"))
        setup.commit()

    uow = SqlAlchemyUnitOfWork(session_factory)
    with uow:
        from sqlalchemy.exc import IntegrityError

        try:
            with uow.savepoint():
                uow.session.add(CenterProfile(name="Second Center", status="active"))
                uow.flush()
        except IntegrityError:
            AuditWriter(uow.session, POLICY).record(
                entry(action="center_profile.create_denied", outcome="conflict"),
                actor=actor(),
                context=AuditContext(request_id="req-2"),
            )
        uow.commit()

    with session_factory() as session:
        profiles = session.execute(text("SELECT count(*) FROM center_profile")).scalar()
        recorded = session.execute(
            text("SELECT action, outcome FROM audit_logs")
        ).fetchall()

    assert profiles == 1, "the rejected profile must not have been created"
    assert [tuple(row) for row in recorded] == [("center_profile.create_denied", "conflict")]


def test_secrets_are_redacted_before_they_reach_either_table(
    session_factory: sessionmaker[Session],
) -> None:
    """Read the stored rows back, not the objects that were staged.

    Asserting on the in-memory model would pass even if the value were written
    unredacted, which is the failure that matters.
    """

    identifier = uuid.uuid4()

    uow = SqlAlchemyUnitOfWork(session_factory)
    with uow:
        AuditWriter(uow.session, POLICY).record(
            entry(
                entity_id=identifier,
                new_values={"name": "Golden", "api_token": "live-token-value"},
                reason="Updated after IR820540102680020817909002 was verified",
            ),
            actor=actor(),
            context=AuditContext(),
        )
        OutboxWriter(uow.session, POLICY).enqueue(
            message(identifier, payload={"name": "Golden", "password": "hunter2"})
        )
        uow.commit()

    with session_factory() as session:
        audit_new_values, audit_reason = session.execute(
            text("SELECT new_values, reason FROM audit_logs")
        ).one()
        outbox_payload = session.execute(text("SELECT payload FROM outbox_events")).scalar()

    assert audit_new_values == {"name": "Golden", "api_token": REDACTED}
    assert "IR820540102680020817909002" not in audit_reason
    assert outbox_payload == {"name": "Golden", "password": REDACTED}


def test_the_writers_never_commit_on_their_own(
    session_factory: sessionmaker[Session],
) -> None:
    """Nothing is durable until the command says so.

    A writer that committed would make the audit row survive a business failure,
    which is the inverse of the guarantee.
    """

    uow = SqlAlchemyUnitOfWork(session_factory)
    with uow:
        AuditWriter(uow.session, POLICY).record(
            entry(), actor=actor(), context=AuditContext()
        )
        OutboxWriter(uow.session, POLICY).enqueue(message(uuid.uuid4()))
        uow.flush()

        assert counts(session_factory) == (0, 0, 0), (
            "a separate connection can see the rows before the command committed"
        )
        uow.commit()

    assert counts(session_factory) == (0, 1, 1)


class TestActorValidation:
    """Reject in Python what the database CHECK would reject at commit.

    Failing at construction names the offending field; failing at commit surfaces
    a constraint violation after the command has already done its work.
    """

    def test_a_human_actor_needs_an_id(self) -> None:
        with pytest.raises(ValueError, match="must carry an actor_id"):
            AuditActor(actor_type="admin_user", actor_id=None)

    def test_a_system_actor_must_not_have_one(self) -> None:
        with pytest.raises(ValueError, match="must not carry an actor_id"):
            AuditActor(actor_type="system_worker", actor_id=uuid.uuid4())

    def test_an_unknown_actor_type_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unknown actor_type"):
            AuditActor(actor_type="root", actor_id=uuid.uuid4())

    def test_a_system_actor_writes_successfully(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        uow = SqlAlchemyUnitOfWork(session_factory)
        with uow:
            AuditWriter(uow.session, POLICY).record(
                entry(action="maintenance.outbox_swept"),
                actor=AuditActor(actor_type="system_maintenance"),
                context=AuditContext(),
            )
            uow.commit()

        with session_factory() as session:
            actor_type, actor_id = session.execute(
                text("SELECT actor_type, actor_id FROM audit_logs")
            ).one()

        assert actor_type == "system_maintenance"
        assert actor_id is None
