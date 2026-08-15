"""Public and restricted health response contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class LivenessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["alive"] = "alive"
    service: str
    version: str


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "not_ready"]
    checks: dict[str, Literal["ok", "unavailable"]]


class DependencyStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "unavailable"]
    required: bool
    latency_ms: float
    last_success_at: datetime | None = None
    error_code: str | None = None


class DependenciesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    dependencies: dict[str, DependencyStatus]
    # Which scan adapter is live. Reported because ADR-008 is open and the choice decides
    # whether an uploaded file can ever be used as evidence: `none` scans nothing and
    # every upload stays quarantined, `development_bypass` reports every file clean
    # without looking at it. An operator should read which one is running rather than
    # infer it from environment variables. This endpoint is behind the operations token,
    # so it discloses nothing to anyone else.
    scan_policy: str


class WorkerStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["running", "stale"]
    queues: list[str]
    last_heartbeat_at: datetime
    release_version: str
    active_job_count: int


class WorkersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workers: list[WorkerStatus]
