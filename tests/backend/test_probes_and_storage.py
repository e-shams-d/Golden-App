from __future__ import annotations

import asyncio
import time
from pathlib import Path

from app.observability.health import SafeDependencyProbe, SafeProbeFailure
from app.storage.local import LocalStorageBackend


def test_probe_success_records_safe_status_and_last_success() -> None:
    probe = SafeDependencyProbe("example", 0.2, lambda: None)

    result = asyncio.run(probe.check())

    assert result.status == "ok"
    assert result.error_code is None
    assert result.last_success_at is not None
    assert result.last_success_at.utcoffset().total_seconds() == 0


def test_probe_failure_exposes_only_allow_listed_code() -> None:
    def fail() -> None:
        raise SafeProbeFailure("DATABASE_SCHEMA_INCOMPATIBLE")

    result = asyncio.run(SafeDependencyProbe("database", 0.2, fail).check())

    assert result.status == "unavailable"
    assert result.error_code == "DATABASE_SCHEMA_INCOMPATIBLE"


def test_unexpected_probe_failure_never_exposes_exception_text() -> None:
    def fail() -> None:
        raise RuntimeError("postgresql://user:database-secret@internal-host/golden")

    result = asyncio.run(SafeDependencyProbe("database", 0.2, fail).check())

    assert result.status == "unavailable"
    assert result.error_code == "DATABASE_UNAVAILABLE"
    assert "database-secret" not in repr(result)
    assert "internal-host" not in repr(result)


def test_probe_timeout_returns_promptly_and_fails_closed() -> None:
    def slow() -> None:
        time.sleep(0.08)

    async def run_and_measure() -> tuple[object, float]:
        # Measure the probe coroutine itself. ``asyncio.run`` waits for its
        # default executor to shut down after the coroutine returns, which is
        # lifecycle cleanup rather than request-path latency.
        started = time.perf_counter()
        result = await SafeDependencyProbe("redis", 0.01, slow).check()
        return result, time.perf_counter() - started

    result, duration = asyncio.run(run_and_measure())

    assert result.status == "unavailable"
    assert result.error_code == "DEPENDENCY_TIMEOUT"
    assert duration < 0.06


def test_local_storage_probe_writes_and_cleans_private_sentinel(tmp_path: Path) -> None:
    root = tmp_path / "private"
    storage = LocalStorageBackend(root)

    storage.check_available()

    assert root.is_dir()
    assert list(root.iterdir()) == []
