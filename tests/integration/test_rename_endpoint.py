"""The command over HTTP, against a real database.

The command's own tests prove the transaction. These prove the layer above it:
that a missing header is refused before anything runs, that each typed error
reaches the client as the right status with the right code, and that a retried
request returns the first response rather than executing twice.

Run against real PostgreSQL rather than a stubbed session, because the
interesting answers — 409 on a reused key, 412 on a stale version — are produced
by the database, not by the route.
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
from app.db.models.center_profile import CenterProfile  # noqa: E402
from app.main import create_app  # noqa: E402

pytestmark = pytest.mark.integration

OPERATIONS_TOKEN = "o" * 48
ENDPOINT = "/api/v1/center-profile/rename"


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
        operations_health_token=OPERATIONS_TOKEN,
        release_commit="abcdef1234567",
        log_level="CRITICAL",
    )


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
        for table in ("audit_logs", "outbox_events", "idempotency_records", "center_profile"):
            session.execute(text(f"DELETE FROM {table}"))
        session.commit()


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def profile_id(session_factory: sessionmaker[Session]) -> uuid.UUID:
    with session_factory() as session:
        profile = CenterProfile(name="Original Center", status="active")
        session.add(profile)
        session.commit()
        return profile.id


def headers(*, key: str = "key-1", if_match: str | None = '"1"') -> dict[str, str]:
    values = {"X-Operations-Token": OPERATIONS_TOKEN, "Idempotency-Key": key}
    if if_match is not None:
        values["If-Match"] = if_match
    return values


def body(profile_id: uuid.UUID, name: str = "Renamed Center") -> dict[str, object]:
    return {"profile_id": str(profile_id), "new_name": name}


class TestHappyPath:
    def test_a_valid_request_renames_and_returns_the_new_version(
        self, client: TestClient, profile_id: uuid.UUID
    ) -> None:
        response = client.post(ENDPOINT, json=body(profile_id), headers=headers())

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["name"] == "Renamed Center"
        assert payload["record_version"] == 2
        assert payload["replayed"] is False
        # The version a conditional follow-up has to send back.
        assert response.headers["ETag"] == '"2"'

    def test_the_change_audit_and_event_are_all_durable(
        self, client: TestClient, profile_id: uuid.UUID, session_factory: sessionmaker[Session]
    ) -> None:
        client.post(ENDPOINT, json=body(profile_id), headers=headers())

        with session_factory() as session:
            name = session.execute(text("SELECT name FROM center_profile")).scalar()
            action, actor_type, actor_id = session.execute(
                text("SELECT action, actor_type, actor_id FROM audit_logs")
            ).one()
            event = session.execute(text("SELECT event_type FROM outbox_events")).scalar()

        assert name == "Renamed Center"
        assert action == "center_profile.renamed"
        assert event == "CenterProfileRenamed"
        # No authentication exists until M3, so the row says maintenance rather
        # than naming a person who was never there.
        assert actor_type == "system_maintenance"
        assert actor_id is None


class TestPreconditions:
    def test_a_missing_idempotency_key_is_428_not_412(
        self, client: TestClient, profile_id: uuid.UUID
    ) -> None:
        """412 would have the client reload and retry a request that cannot succeed."""

        response = client.post(
            ENDPOINT,
            json=body(profile_id),
            headers={"X-Operations-Token": OPERATIONS_TOKEN, "If-Match": '"1"'},
        )

        assert response.status_code == 428
        error = response.json()["error"]
        assert error["code"] == "PRECONDITION_REQUIRED"
        assert error["details"][0]["field"] == "Idempotency-Key"

    def test_a_missing_if_match_names_that_header(
        self, client: TestClient, profile_id: uuid.UUID
    ) -> None:
        response = client.post(
            ENDPOINT, json=body(profile_id), headers=headers(if_match=None)
        )

        assert response.status_code == 428
        assert response.json()["error"]["details"][0]["field"] == "If-Match"

    @pytest.mark.parametrize("value", ["", "not-a-number", '"abc"', "0", "-1"])
    def test_an_unparsable_if_match_is_refused(
        self, client: TestClient, profile_id: uuid.UUID, value: str
    ) -> None:
        response = client.post(
            ENDPOINT, json=body(profile_id), headers=headers(if_match=value)
        )

        assert response.status_code == 428

    def test_a_quoted_and_weak_etag_are_both_accepted(
        self, client: TestClient, profile_id: uuid.UUID
    ) -> None:
        """Clients and proxies quote ETags, and some mark them weak.

        Refusing the quoted form would reject the value this endpoint itself
        returned a moment earlier.
        """

        assert (
            client.post(
                ENDPOINT, json=body(profile_id), headers=headers(if_match='W/"1"')
            ).status_code
            == 200
        )

    def test_a_stale_if_match_is_412(
        self, client: TestClient, profile_id: uuid.UUID
    ) -> None:
        client.post(ENDPOINT, json=body(profile_id), headers=headers())

        response = client.post(
            ENDPOINT, json=body(profile_id, "Third Name"), headers=headers(key="key-2")
        )

        assert response.status_code == 412
        assert response.json()["error"]["code"] == "VERSION_CONFLICT"


class TestIdempotencyOverHttp:
    def test_a_retried_request_returns_the_first_response(
        self, client: TestClient, profile_id: uuid.UUID, session_factory: sessionmaker[Session]
    ) -> None:
        first = client.post(ENDPOINT, json=body(profile_id), headers=headers())
        second = client.post(ENDPOINT, json=body(profile_id), headers=headers())

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["replayed"] is True
        assert second.json()["record_version"] == first.json()["record_version"]

        with session_factory() as session:
            audit_rows = session.execute(text("SELECT count(*) FROM audit_logs")).scalar()
            version = session.execute(
                text("SELECT record_version FROM center_profile")
            ).scalar()

        assert audit_rows == 1, "a replay must not write a second audit row"
        assert version == 2, "a replay must not advance the version again"

    def test_the_same_key_with_a_different_body_is_409(
        self, client: TestClient, profile_id: uuid.UUID
    ) -> None:
        client.post(ENDPOINT, json=body(profile_id), headers=headers())

        response = client.post(
            ENDPOINT, json=body(profile_id, "Different Name"), headers=headers()
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


class TestAccessAndValidation:
    def test_without_the_operations_token_the_endpoint_is_forbidden(
        self, client: TestClient, profile_id: uuid.UUID
    ) -> None:
        response = client.post(
            ENDPOINT,
            json=body(profile_id),
            headers={"Idempotency-Key": "key-1", "If-Match": '"1"'},
        )

        assert response.status_code == 403

    def test_a_rejected_request_changes_nothing(
        self, client: TestClient, profile_id: uuid.UUID, session_factory: sessionmaker[Session]
    ) -> None:
        client.post(
            ENDPOINT,
            json=body(profile_id),
            headers={"Idempotency-Key": "key-1", "If-Match": '"1"'},
        )

        with session_factory() as session:
            name = session.execute(text("SELECT name FROM center_profile")).scalar()
            rows = session.execute(text("SELECT count(*) FROM audit_logs")).scalar()

        assert name == "Original Center"
        assert rows == 0

    def test_an_unknown_profile_is_404(self, client: TestClient) -> None:
        response = client.post(ENDPOINT, json=body(uuid.uuid4()), headers=headers())

        assert response.status_code == 404

    def test_an_unexpected_field_is_rejected(
        self, client: TestClient, profile_id: uuid.UUID
    ) -> None:
        """extra="forbid" on the request model, so a typo is not silently ignored."""

        response = client.post(
            ENDPOINT,
            json={**body(profile_id), "statu": "active"},
            headers=headers(),
        )

        assert response.status_code == 422

    def test_the_error_envelope_carries_a_request_id(
        self, client: TestClient, profile_id: uuid.UUID
    ) -> None:
        response = client.post(ENDPOINT, json=body(profile_id), headers=headers(if_match=None))

        assert response.json()["error"]["request_id"]
