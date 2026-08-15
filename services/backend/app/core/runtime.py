"""Gracefully-owned process resources and dependency adapters."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from celery import Celery
from redis import Redis
from sqlalchemy import Engine

from app.core.config import Settings
from app.core.logging import get_logger, log_event
from app.core.release import ReleaseMetadata
from app.db.session import SessionFactory, create_engine_and_session_factory
from app.db.unit_of_work import UnitOfWorkFactory
from app.files.scanning import ScanPolicy, build_scan_policy
from app.observability.health import (
    CeleryWorkerHealthProbe,
    HealthService,
    WorkerHealthProbe,
    database_probe,
    redis_probe,
    storage_probe,
)
from app.storage.interface import StorageBackend
from app.storage.local import LocalStorageBackend
from app.workers.celery_app import create_celery_app


@dataclass
class RuntimeServices:
    release: ReleaseMetadata
    engine: Engine
    session_factory: SessionFactory
    uow_factory: UnitOfWorkFactory
    redis: Redis
    storage: StorageBackend
    scan_policy: ScanPolicy
    celery: Celery
    health: HealthService
    worker_health: WorkerHealthProbe

    @classmethod
    def from_settings(cls, settings: Settings) -> RuntimeServices:
        engine, session_factory = create_engine_and_session_factory(settings)
        redis_client = Redis.from_url(
            settings.redis_url.get_secret_value(),
            decode_responses=True,
            socket_connect_timeout=settings.dependency_timeout_seconds,
            socket_timeout=settings.dependency_timeout_seconds,
            health_check_interval=30,
        )
        storage = LocalStorageBackend(settings.local_storage_root)
        # Built here rather than inside the command so that an unknown or
        # production-forbidden policy fails at startup, not on the first upload.
        scan_policy = build_scan_policy(
            policy_name=settings.file_scan_policy, app_env=settings.app_env
        )
        celery = create_celery_app(settings)
        probes = {
            "database": database_probe(
                engine,
                timeout_seconds=settings.dependency_timeout_seconds,
            ),
            "redis": redis_probe(
                redis_client,
                timeout_seconds=settings.dependency_timeout_seconds,
            ),
            "storage": storage_probe(
                storage,
                timeout_seconds=settings.dependency_timeout_seconds,
            ),
        }
        required = {"database", "storage"}
        if settings.redis_required_for_readiness:
            required.add("redis")
        return cls(
            release=ReleaseMetadata.from_settings(settings),
            engine=engine,
            session_factory=session_factory,
            uow_factory=UnitOfWorkFactory(session_factory),
            redis=redis_client,
            storage=storage,
            scan_policy=scan_policy,
            celery=celery,
            health=HealthService(probes, required_for_readiness=frozenset(required)),
            worker_health=CeleryWorkerHealthProbe(
                celery,
                timeout_seconds=settings.worker_probe_timeout_seconds,
                release_version=settings.release_version,
            ),
        )

    def close(self) -> None:
        logger = get_logger("lifecycle")
        closers = (
            ("storage", self.storage.close),
            ("redis", self.redis.connection_pool.disconnect),
            ("celery", self.celery.close),
            ("database", self.engine.dispose),
        )
        for name, close in closers:
            try:
                close()
            except Exception as exc:
                log_event(
                    logger,
                    logging.ERROR,
                    "runtime_resource_close_failed",
                    dependency=name,
                    exception_type=type(exc).__name__,
                )
