"""Strict-timeout, fail-closed dependency and worker health probes."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Any, Protocol, runtime_checkable

from celery import Celery
from redis import Redis
from sqlalchemy import Engine, text

from app.core.time import utc_now
from app.db.migrations import EXPECTED_MIGRATION_HEADS
from app.storage.interface import StorageBackend


class SafeProbeFailure(RuntimeError):
    """Internal probe failure carrying only an allow-listed operational code."""

    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


@dataclass(frozen=True)
class ProbeResult:
    name: str
    status: str
    latency_ms: float
    last_success_at: datetime | None
    error_code: str | None = None


@runtime_checkable
class DependencyProbe(Protocol):
    name: str

    async def check(self) -> ProbeResult: ...


class SafeDependencyProbe:
    """Runs a bounded sync check off-loop and never returns raw exceptions."""

    def __init__(self, name: str, timeout_seconds: float, callback: Callable[[], None]) -> None:
        self.name = name
        self._timeout_seconds = timeout_seconds
        self._callback = callback
        self._last_success_at: datetime | None = None
        self._state_lock = Lock()

    async def check(self) -> ProbeResult:
        started = time.perf_counter()
        error_code: str | None = None
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._callback),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            status = "unavailable"
            error_code = "DEPENDENCY_TIMEOUT"
        except SafeProbeFailure as exc:
            status = "unavailable"
            error_code = exc.safe_code
        except Exception:
            status = "unavailable"
            error_code = f"{self.name.upper()}_UNAVAILABLE"
        else:
            status = "ok"
            with self._state_lock:
                self._last_success_at = utc_now()

        with self._state_lock:
            last_success_at = self._last_success_at
        return ProbeResult(
            name=self.name,
            status=status,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
            last_success_at=last_success_at,
            error_code=error_code,
        )


def database_probe(
    engine: Engine,
    *,
    timeout_seconds: float,
    expected_heads: frozenset[str] = EXPECTED_MIGRATION_HEADS,
) -> SafeDependencyProbe:
    def check_database() -> None:
        with engine.connect() as connection:
            if connection.scalar(text("SELECT 1")) != 1:
                raise SafeProbeFailure("DATABASE_QUERY_FAILED")
            marker = connection.scalar(text("SELECT to_regclass('public.alembic_version')"))
            if marker is None:
                raise SafeProbeFailure("DATABASE_SCHEMA_INCOMPATIBLE")
            rows = connection.execute(text("SELECT version_num FROM alembic_version"))
            actual_heads = frozenset(
                str(row[0]) for row in rows
            )
            if actual_heads != expected_heads:
                raise SafeProbeFailure("DATABASE_SCHEMA_INCOMPATIBLE")

    return SafeDependencyProbe("database", timeout_seconds, check_database)


def redis_probe(client: Redis, *, timeout_seconds: float) -> SafeDependencyProbe:
    def check_redis() -> None:
        if client.ping() is not True:
            raise SafeProbeFailure("REDIS_PING_FAILED")

    return SafeDependencyProbe("redis", timeout_seconds, check_redis)


def storage_probe(
    storage: StorageBackend, *, timeout_seconds: float
) -> SafeDependencyProbe:
    return SafeDependencyProbe("storage", timeout_seconds, storage.check_available)


class HealthService:
    def __init__(
        self,
        probes: Mapping[str, DependencyProbe],
        *,
        required_for_readiness: frozenset[str],
    ) -> None:
        self._probes = dict(probes)
        missing = required_for_readiness.difference(self._probes)
        if missing:
            raise ValueError("required readiness probe is not registered")
        self._required_for_readiness = required_for_readiness

    @property
    def required_for_readiness(self) -> frozenset[str]:
        return self._required_for_readiness

    async def check_dependencies(self) -> dict[str, ProbeResult]:
        ordered = sorted(self._probes)
        results = await asyncio.gather(*(self._probes[name].check() for name in ordered))
        return dict(zip(ordered, results, strict=True))

    async def check_readiness(self) -> tuple[bool, dict[str, ProbeResult]]:
        results = await self.check_dependencies()
        ready = all(
            results[name].status == "ok" for name in self._required_for_readiness
        )
        return ready, results


@dataclass(frozen=True)
class WorkerSnapshot:
    name: str
    status: str
    queues: tuple[str, ...]
    last_heartbeat_at: datetime
    release_version: str
    active_job_count: int


@dataclass(frozen=True)
class WorkerProbeResult:
    available: bool
    workers: tuple[WorkerSnapshot, ...]
    error_code: str | None = None


@runtime_checkable
class WorkerHealthProbe(Protocol):
    async def check(self) -> WorkerProbeResult: ...


class CeleryWorkerHealthProbe:
    """Uses Celery control replies; no result backend is treated as authority."""

    def __init__(self, app: Celery, *, timeout_seconds: float, release_version: str) -> None:
        self._app = app
        self._timeout_seconds = timeout_seconds
        self._release_version = release_version

    def _inspect(self) -> tuple[WorkerSnapshot, ...]:
        inspector = self._app.control.inspect(timeout=self._timeout_seconds)
        ping: Mapping[str, Any] = inspector.ping() or {}
        if not ping:
            raise SafeProbeFailure("WORKERS_UNAVAILABLE")
        queues: Mapping[str, Any] = inspector.active_queues() or {}
        active: Mapping[str, Any] = inspector.active() or {}
        checked_at = utc_now()
        snapshots: list[WorkerSnapshot] = []
        for name in sorted(ping):
            worker_queues = tuple(
                sorted(
                    str(item.get("name"))
                    for item in queues.get(name, [])
                    if isinstance(item, Mapping) and item.get("name")
                )
            )
            snapshots.append(
                WorkerSnapshot(
                    name=name,
                    status="running",
                    queues=worker_queues,
                    last_heartbeat_at=checked_at,
                    release_version=self._release_version,
                    active_job_count=len(active.get(name, [])),
                )
            )
        return tuple(snapshots)

    async def check(self) -> WorkerProbeResult:
        try:
            workers = await asyncio.wait_for(
                asyncio.to_thread(self._inspect),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            return WorkerProbeResult(False, (), "WORKER_PROBE_TIMEOUT")
        except SafeProbeFailure as exc:
            return WorkerProbeResult(False, (), exc.safe_code)
        except Exception:
            return WorkerProbeResult(False, (), "WORKERS_UNAVAILABLE")
        return WorkerProbeResult(True, workers)
