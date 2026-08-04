"""The restricted background-processing path, against real rows.

Counts and ages are only meaningful against a database, so every case here seeds
the state it describes. A test that asserted an empty response would pass against
an endpoint that queried nothing.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.db.claiming import claim_jobs, new_job  # noqa: E402
from app.db.models.outbox_event import OutboxEvent  # noqa: E402
from app.main import create_app  # noqa: E402

pytestmark = pytest.mark.integration

OPERATIONS_TOKEN = "o" * 48
ENDPOINT = "/api/v1/operations/background-processing"
QUEUE = "files"


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
        session.execute(text("DELETE FROM processing_jobs"))
        session.execute(text("DELETE FROM outbox_events"))
        session.commit()


@pytest.fixture
def client(migrated_database: str, tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=_sqlalchemy_url(migrated_database),
        redis_url="redis://127.0.0.1:6379/0",
        local_storage_root=tmp_path / "storage",
        operations_health_token=OPERATIONS_TOKEN,
        release_commit="abcdef1234567",
        log_level="CRITICAL",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def headers() -> dict[str, str]:
    return {"X-Operations-Token": OPERATIONS_TOKEN}


class TestAccess:
    def test_without_the_token_it_is_forbidden(self, client: TestClient) -> None:
        """Queue depth and failure ages describe internal state precisely."""

        assert client.get(ENDPOINT).status_code == 403

    def test_with_the_token_it_answers(self, client: TestClient) -> None:
        assert client.get(ENDPOINT, headers=headers()).status_code == 200


class TestOutboxReporting:
    def test_a_quiet_outbox_reports_no_age(self, client: TestClient) -> None:
        body = client.get(ENDPOINT, headers=headers()).json()

        assert body["outbox"]["pending"] == 0
        assert body["outbox"]["oldest_pending_age_seconds"] is None
        assert body["needs_attention"] is False

    def test_a_stuck_event_reports_its_age(
        self, client: TestClient, session_factory: sessionmaker[Session]
    ) -> None:
        """A count alone cannot separate a healthy burst from a stuck event."""

        with session_factory() as session:
            session.add(
                OutboxEvent(
                    aggregate_type="center_profile",
                    aggregate_id=uuid.uuid4(),
                    aggregate_version=1,
                    event_type="CenterProfileRenamed",
                    payload={},
                    payload_version=1,
                )
            )
            session.commit()
            session.execute(
                text("UPDATE outbox_events SET created_at = now() - interval '3 hours'")
            )
            session.commit()

        body = client.get(ENDPOINT, headers=headers()).json()

        assert body["outbox"]["pending"] == 1
        assert body["outbox"]["oldest_pending_age_seconds"] > 10_000

    def test_a_dead_lettered_event_needs_attention(
        self, client: TestClient, session_factory: sessionmaker[Session]
    ) -> None:
        with session_factory() as session:
            session.add(
                OutboxEvent(
                    aggregate_type="center_profile",
                    aggregate_id=uuid.uuid4(),
                    aggregate_version=1,
                    event_type="X",
                    payload={},
                    payload_version=1,
                    status="dead_lettered",
                )
            )
            session.commit()

        body = client.get(ENDPOINT, headers=headers()).json()

        assert body["outbox"]["dead_lettered"] == 1
        assert body["needs_attention"] is True


class TestJobReporting:
    def test_queued_jobs_are_counted_and_aged(
        self, client: TestClient, session_factory: sessionmaker[Session]
    ) -> None:
        with session_factory() as session:
            session.add_all([new_job(job_type="scan", queue_name=QUEUE) for _ in range(3)])
            session.commit()

        body = client.get(ENDPOINT, headers=headers()).json()

        assert body["jobs"]["queued"] == 3
        assert body["jobs"]["oldest_queued_age_seconds"] is not None

    def test_a_stale_lease_is_surfaced(
        self, client: TestClient, session_factory: sessionmaker[Session]
    ) -> None:
        """A rising number here means workers are dying, not that jobs are slow."""

        with session_factory() as session:
            session.add(new_job(job_type="scan", queue_name=QUEUE))
            session.commit()
        with session_factory() as session:
            claim_jobs(session, queue_name=QUEUE, worker_id="dead")
            session.commit()
        with session_factory() as session:
            session.execute(
                text("UPDATE processing_jobs SET heartbeat_at = now() - interval '30 minutes'")
            )
            session.commit()

        body = client.get(ENDPOINT, headers=headers()).json()

        assert body["jobs"]["stale_leases"] == 1
        assert body["needs_attention"] is True

    def test_manual_fallback_needs_attention(
        self, client: TestClient, session_factory: sessionmaker[Session]
    ) -> None:
        """A job whose handler is not retry-safe is waiting on a person."""

        with session_factory() as session:
            job = new_job(job_type="pay", queue_name=QUEUE)
            job.status = "fallback_to_manual"
            job.finished_at = text("now()")  # type: ignore[assignment]
            session.add(job)
            session.commit()

        body = client.get(ENDPOINT, headers=headers()).json()

        assert body["jobs"]["fallback_to_manual"] == 1
        assert body["needs_attention"] is True

    def test_a_healthy_backlog_alone_does_not_need_attention(
        self, client: TestClient, session_factory: sessionmaker[Session]
    ) -> None:
        """A queue draining normally is not a fault.

        Alerting on depth alone produces the alert everyone learns to dismiss.
        """

        with session_factory() as session:
            session.add_all([new_job(job_type="scan", queue_name=QUEUE) for _ in range(50)])
            session.commit()

        body = client.get(ENDPOINT, headers=headers()).json()

        assert body["jobs"]["queued"] == 50
        assert body["needs_attention"] is False


class TestTheReadPathDoesNotMutate:
    def test_repeated_reads_change_nothing(
        self, client: TestClient, session_factory: sessionmaker[Session]
    ) -> None:
        """Queries never mutate domain state — asserted, not assumed."""

        with session_factory() as session:
            session.add(new_job(job_type="scan", queue_name=QUEUE))
            session.commit()

        with session_factory() as session:
            before = session.execute(
                text("SELECT status, attempt_count, locked_by FROM processing_jobs")
            ).one()

        for _ in range(3):
            client.get(ENDPOINT, headers=headers())

        with session_factory() as session:
            after = session.execute(
                text("SELECT status, attempt_count, locked_by FROM processing_jobs")
            ).one()

        assert tuple(before) == tuple(after)
