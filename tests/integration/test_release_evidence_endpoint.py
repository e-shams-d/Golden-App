"""The other half of OPS-EVIDENCE-001: a real instance reports its own schema.

The unit tests drive the emitter against a stubbed response, so they prove the
artifact's shape and its refusals. They cannot prove the thing the field exists for —
that the number comes from the database the process is actually connected to.

That is what this file does. It migrates a real database, points a real application at
it, and reads the endpoint. Then it does the harder half: it points the application at
a database migrated to an **earlier** revision and requires the endpoint to say so.
Without that second case, `matches: true` would be indistinguishable from a function
that returns `true`.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from alembic_runner import run_alembic
from app.core.config import Settings
from app.core.runtime import RuntimeServices
from app.db.migrations import EXPECTED_MIGRATION_HEADS
from app.main import create_app
from bootstrap_replay import RuntimeIdentities
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

# `Settings` enforces a 32-character minimum, so a short token fails validation
# before any request is made. That minimum is the point: an operations token short
# enough to be guessed is not a control.
OPERATIONS_TOKEN = "operations-token-for-tests-padded-to-length"


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _sqlalchemy(url: str) -> str:
    """Force the psycopg 3 driver; a bare `postgresql://` reaches for psycopg2."""

    if url.startswith("postgresql+"):
        return url
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture
def instance(
    migrated_database: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[TestClient]:
    """A real application, wired to a real migrated database.

    Built through `Settings` and `create_app` rather than by stubbing the runtime, so
    the endpoint reads through the same engine a deployed process would.
    """

    storage_root = tmp_path_factory.mktemp("evidence-storage")
    settings = Settings(
        # `_env_file=None` is load-bearing: without it pydantic-settings reads the
        # developer's `.env`, and a by-name keyword whose validation alias is already
        # populated from the environment is rejected as an extra input.
        _env_file=None,
        app_env="test",
        log_level="CRITICAL",
        database_url=_sqlalchemy(migrated_database),
        redis_url="redis://127.0.0.1:6379/0",
        local_storage_root=storage_root,
        release_commit="c" * 40,
        operations_health_token=OPERATIONS_TOKEN,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


def read_evidence(client: TestClient) -> dict[str, object]:
    response = client.get(
        "/api/v1/operations/release-evidence",
        headers={"X-Operations-Token": OPERATIONS_TOKEN},
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestTheInstanceReportsItsOwnSchema:
    def test_the_applied_revision_is_the_one_in_the_database(
        self, instance: TestClient, migrated_database: str
    ) -> None:
        """Read from the endpoint, compared against `alembic_version` directly.

        Two independent reads of the same fact. If the endpoint returned the expected
        set instead of the applied one, this still passes — which is why the
        earlier-revision test below exists.
        """

        with psycopg.connect(_psycopg(migrated_database), autocommit=True) as connection:
            rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
        in_database = sorted(str(row[0]) for row in rows)

        evidence = read_evidence(instance)

        assert evidence["schema_state"]["applied_revisions"] == in_database
        assert evidence["schema_state"]["expected_revisions"] == sorted(EXPECTED_MIGRATION_HEADS)
        assert evidence["schema_state"]["matches"] is True

    def test_the_flag_snapshot_is_the_seeded_phase_1a_set(self, instance: TestClient) -> None:
        """The evidence field that shows AI is disabled, read from the database rather
        than from a constant in the emitter."""

        evidence = read_evidence(instance)
        flags = {entry["flag_key"]: entry["is_enabled"] for entry in evidence["feature_flags"]}

        assert flags == {
            "manual_crop.enabled": True,
            "auto_segmentation.enabled": False,
            "ocr.enabled": False,
            "ai_matching.enabled": False,
            "bank_api.enabled": False,
        }

    def test_the_release_identity_comes_from_the_running_settings(
        self, instance: TestClient
    ) -> None:
        evidence = read_evidence(instance)

        assert evidence["commit"] == "c" * 40
        assert evidence["service"]
        assert evidence["environment"]

    def test_the_endpoint_is_restricted(self, instance: TestClient) -> None:
        """Release identity, schema revision and flag state describe the deployment
        precisely enough to be worth withholding from an anonymous caller."""

        assert instance.get("/api/v1/operations/release-evidence").status_code == 403
        assert (
            instance.get(
                "/api/v1/operations/release-evidence",
                headers={"X-Operations-Token": "wrong"},
            ).status_code
            == 403
        )


class TestAnEarlierSchemaIsReportedAsAMismatch:
    """The case that makes `matches: true` mean something.

    A database migrated to the revision before head, with an application built against
    head. This is the deployment mismatch the field exists to catch, and without it the
    test above would pass against a function that always returns true.
    """

    @pytest.fixture
    def one_revision_behind(
        self, provisioned_database: RuntimeIdentities, tmp_path_factory: pytest.TempPathFactory
    ) -> Iterator[TestClient]:
        result = run_alembic(
            provisioned_database.migrator_url,
            "upgrade",
            # The revision immediately before the current head.
            "20260801_0011",
            app_role=provisioned_database.app_role,
            worker_role=provisioned_database.worker_role,
        )
        assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

        settings = Settings(
            _env_file=None,
            app_env="test",
            log_level="CRITICAL",
            database_url=_sqlalchemy(provisioned_database.owner_url),
            redis_url="redis://127.0.0.1:6379/0",
            local_storage_root=tmp_path_factory.mktemp("behind-storage"),
            release_commit="d" * 40,
            operations_health_token=OPERATIONS_TOKEN,
        )
        with TestClient(create_app(settings)) as client:
            yield client

    def test_the_mismatch_is_reported_rather_than_hidden(
        self, one_revision_behind: TestClient
    ) -> None:
        evidence = read_evidence(one_revision_behind)
        state = evidence["schema_state"]

        assert state["applied_revisions"] == ["20260801_0011"]
        assert state["expected_revisions"] == sorted(EXPECTED_MIGRATION_HEADS)
        assert state["matches"] is False

    def test_the_endpoint_still_answers_when_the_schema_does_not_match(
        self, one_revision_behind: TestClient
    ) -> None:
        """Deliberate: an instance on the wrong schema is exactly when an operator
        needs to be told which schema it is on.

        Readiness already refuses traffic in this state. If this path refused too, the
        only way to find out why would be to read the database by hand.
        """

        response = one_revision_behind.get(
            "/api/v1/operations/release-evidence",
            headers={"X-Operations-Token": OPERATIONS_TOKEN},
        )

        assert response.status_code == 200


def test_the_runtime_type_exposes_the_engine_the_endpoint_reads(
    migrated_database: str, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Guard the guard: the endpoint reads `runtime.engine`.

    If a refactor moved that attribute, the tests above would fail with an
    AttributeError that reads like a broken test rather than a broken contract.
    """

    settings = Settings(
        _env_file=None,
        app_env="test",
        log_level="CRITICAL",
        database_url=_sqlalchemy(migrated_database),
        redis_url="redis://127.0.0.1:6379/0",
        local_storage_root=tmp_path_factory.mktemp("engine-storage"),
        release_commit="e" * 40,
        operations_health_token=OPERATIONS_TOKEN,
    )
    runtime = RuntimeServices.from_settings(settings)
    try:
        with runtime.engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
    finally:
        runtime.close()
