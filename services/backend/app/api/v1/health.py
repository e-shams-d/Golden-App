"""Canonical M1 health endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime, require_operations_access
from app.core.errors import BackgroundProcessingUnavailableError, ErrorEnvelope
from app.core.runtime import RuntimeServices
from app.observability.schemas import (
    DependenciesResponse,
    DependencyStatus,
    LivenessResponse,
    ReadinessResponse,
    WorkersResponse,
    WorkerStatus,
)

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "/live",
    response_model=LivenessResponse,
    operation_id="getHealthLiveness",
)
def live(runtime: Annotated[RuntimeServices, Depends(get_runtime)]) -> LivenessResponse:
    return LivenessResponse(
        service=runtime.release.service,
        version=runtime.release.version,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
    operation_id="getHealthReadiness",
)
async def ready(
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> ReadinessResponse | JSONResponse:
    is_ready, results = await runtime.health.check_readiness()
    payload = ReadinessResponse(
        status="ready" if is_ready else "not_ready",
        checks={name: result.status for name, result in results.items()},
    )
    if not is_ready:
        return JSONResponse(status_code=503, content=payload.model_dump(mode="json"))
    return payload


@router.get(
    "/dependencies",
    response_model=DependenciesResponse,
    responses={
        403: {"model": ErrorEnvelope, "description": "Operations access is denied."},
        **VALIDATION_ERROR_RESPONSE,
    },
    operation_id="getHealthDependencies",
    dependencies=[Depends(require_operations_access)],
)
async def dependencies(
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> DependenciesResponse:
    results = await runtime.health.check_dependencies()
    required = runtime.health.required_for_readiness
    return DependenciesResponse(
        status="ok" if all(result.status == "ok" for result in results.values()) else "degraded",
        dependencies={
            name: DependencyStatus(
                status=result.status,
                required=name in required,
                latency_ms=result.latency_ms,
                last_success_at=result.last_success_at,
                error_code=result.error_code,
            )
            for name, result in results.items()
        },
        scan_policy=runtime.scan_policy.name,
    )


@router.get(
    "/workers",
    response_model=WorkersResponse,
    responses={
        403: {"model": ErrorEnvelope, "description": "Operations access is denied."},
        503: {
            "model": ErrorEnvelope,
            "description": "Background processing is unavailable.",
        },
        **VALIDATION_ERROR_RESPONSE,
    },
    operation_id="getHealthWorkers",
    dependencies=[Depends(require_operations_access)],
)
async def workers(runtime: Annotated[RuntimeServices, Depends(get_runtime)]) -> WorkersResponse:
    result = await runtime.worker_health.check()
    if not result.available:
        raise BackgroundProcessingUnavailableError()
    return WorkersResponse(
        workers=[
            WorkerStatus(
                name=worker.name,
                status=worker.status,
                queues=list(worker.queues),
                last_heartbeat_at=worker.last_heartbeat_at,
                release_version=worker.release_version,
                active_job_count=worker.active_job_count,
            )
            for worker in result.workers
        ]
    )
