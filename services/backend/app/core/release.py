"""Safe release metadata exposed to operators and health checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.config import Settings


@dataclass(frozen=True)
class ReleaseMetadata:
    service: str
    version: str
    commit: str
    built_at: datetime | None
    environment: str

    @classmethod
    def from_settings(cls, settings: Settings) -> ReleaseMetadata:
        return cls(
            service=settings.service_name,
            version=settings.release_version,
            commit=settings.release_commit,
            built_at=settings.release_built_at,
            environment=settings.app_env,
        )
