"""Safe release metadata endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.api.dependencies import get_runtime
from app.core.runtime import RuntimeServices

router = APIRouter(prefix="/meta", tags=["metadata"])


class ReleaseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str
    version: str
    commit: str
    built_at: datetime | None
    environment: str


@router.get(
    "/release",
    response_model=ReleaseResponse,
    operation_id="getReleaseMetadata",
)
def release(runtime: Annotated[RuntimeServices, Depends(get_runtime)]) -> ReleaseResponse:
    return ReleaseResponse(**runtime.release.__dict__)
