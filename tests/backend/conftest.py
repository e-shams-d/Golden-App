from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))
# `tests/fixtures` is shared by both suites. Inserted here rather than relying on a
# parent conftest: rootdir is `services/backend`, which is not an ancestor of
# `tests/`, so pytest never collects a conftest above these directories.
sys.path.insert(0, str(REPOSITORY_ROOT / "tests" / "fixtures"))

from app.core.config import Settings  # noqa: E402
from app.core.release import ReleaseMetadata  # noqa: E402
from app.files.scanning import build_scan_policy  # noqa: E402
from app.main import create_app  # noqa: E402
from app.observability.health import (  # noqa: E402
    HealthService,
    ProbeResult,
    WorkerProbeResult,
)
from settings_environment import environment_without_settings_variables  # noqa: E402


class StaticProbe:
    def __init__(self, result: ProbeResult) -> None:
        self.name = result.name
        self.result = result
        self.calls = 0

    async def check(self) -> ProbeResult:
        self.calls += 1
        return self.result


class StaticWorkerProbe:
    def __init__(self, result: WorkerProbeResult) -> None:
        self.result = result
        self.calls = 0

    async def check(self) -> WorkerProbeResult:
        self.calls += 1
        return self.result


class FakeRuntime:
    def __init__(
        self,
        settings: Settings,
        results: dict[str, ProbeResult],
        worker_result: WorkerProbeResult,
    ) -> None:
        self.release = ReleaseMetadata.from_settings(settings)
        self.probes = {name: StaticProbe(result) for name, result in results.items()}
        self.health = HealthService(
            self.probes,
            required_for_readiness=frozenset({"database", "redis", "storage"}),
        )
        self.worker_health = StaticWorkerProbe(worker_result)
        # Built from the same factory the real runtime uses rather than stubbed, so a
        # test double cannot report a policy the application could not actually select.
        self.scan_policy = build_scan_policy(
            policy_name=settings.file_scan_policy, app_env=settings.app_env
        )
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture(scope="session", autouse=True)
def isolated_settings_environment() -> Iterator[None]:
    """Hide the ambient environment from every test in this directory.

    These tests assert what Settings does with values they supply, so reading
    the developer's shell makes the result depend on the machine. Worse, the
    failure is actively misleading: Settings declares `validation_alias` with
    `populate_by_name` and `extra="forbid"`, so when DATABASE_URL or REDIS_URL
    is exported, the environment fills the field through its alias, the value
    passed here by field name is left over, and pydantic reports it as an extra
    input. Nineteen tests then fail claiming `redis_url` is not permitted on a
    model that plainly declares it.

    A shell with DATABASE_URL set is entirely ordinary, and the CI job that
    provisions PostgreSQL sets these too, so this is not a hypothetical.

    Session scope, sharing one implementation with the integration suite. It was
    function-scoped, which covers a test but not a fixture built before it: pytest
    sets higher scopes up first, so any module- or session-scoped fixture that built
    a Settings saw the unmodified environment. The integration suite lost a CI run
    to exactly that, and nothing but the absence of such a fixture here kept this
    directory from the same failure.
    """

    with environment_without_settings_variables():
        yield


@pytest.fixture
def settings_factory(tmp_path: Path) -> Callable[..., Settings]:
    def build(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "app_env": "test",
            "release_version": "0.1.0-test",
            "release_commit": "abcdef1234567",
            "release_built_at": "2026-07-20T12:00:00Z",
            "database_url": "postgresql+psycopg://app:database-secret@127.0.0.1/test",
            "redis_url": "redis://:redis-secret@127.0.0.1:6379/0",
            "local_storage_root": tmp_path / "private-storage",
            "operations_health_token": "o" * 40,
            # Required whenever a test builds production settings. Supplied by
            # default rather than per-test so the production validator stays a
            # real gate: a test that needs to prove the requirement fires can
            # override this to None, and every other test is unaffected.
            "auth_rate_limit_key_secret": "r" * 40,
            "auth_csrf_key_secret": "c" * 40,
            # The same reasoning, for the POL-006 upload-limits refusal: supplied by
            # default so every test that happens to build production settings is
            # unaffected, and the one test that proves the refusal fires overrides it.
            "file_upload_limits_are_production_approved": True,
            "dependency_timeout_seconds": 0.2,
            "worker_probe_timeout_seconds": 0.2,
            "log_level": "CRITICAL",
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    return build


@pytest.fixture
def app_factory(settings_factory: Callable[..., Settings]):
    def build(
        *,
        settings_overrides: dict[str, Any] | None = None,
        dependency_statuses: dict[str, str] | None = None,
        dependency_errors: dict[str, str] | None = None,
        worker_result: WorkerProbeResult | None = None,
    ):
        settings = settings_factory(**(settings_overrides or {}))
        statuses = dependency_statuses or {
            "database": "ok",
            "redis": "ok",
            "storage": "ok",
        }
        errors = dependency_errors or {}
        results = {
            name: ProbeResult(
                name=name,
                status=status,
                latency_ms=1.25,
                last_success_at=None,
                error_code=errors.get(name),
            )
            for name, status in statuses.items()
        }
        runtime = FakeRuntime(
            settings,
            results,
            worker_result or WorkerProbeResult(True, ()),
        )
        app = create_app(settings, runtime_factory=lambda _settings: runtime)  # type: ignore[arg-type]
        return app, runtime, settings

    return build
