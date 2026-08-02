from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.core.release import ReleaseMetadata  # noqa: E402
from app.main import create_app  # noqa: E402
from app.observability.health import (  # noqa: E402
    HealthService,
    ProbeResult,
    WorkerProbeResult,
)
from settings_environment import settings_environment_names  # noqa: E402


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
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def isolated_settings_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
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
    """

    for name in list(os.environ):
        if name.upper() in settings_environment_names():
            monkeypatch.delenv(name, raising=False)
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
