"""Cross-cutting FastAPI dependencies."""

from __future__ import annotations

import hmac
from typing import Annotated, cast

from fastapi import Request, Security
from fastapi.security import APIKeyHeader

from app.core.config import Settings
from app.core.errors import DependencyUnavailableError, ForbiddenError
from app.core.runtime import RuntimeServices

OPERATIONS_TOKEN_HEADER = "X-Operations-Token"
OPERATIONS_SECURITY_SCHEME = "OperationsToken"

operations_token_header = APIKeyHeader(
    name=OPERATIONS_TOKEN_HEADER,
    scheme_name=OPERATIONS_SECURITY_SCHEME,
    description="Operations-only health access token.",
    auto_error=False,
)


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_runtime(request: Request) -> RuntimeServices:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise DependencyUnavailableError()
    return cast(RuntimeServices, runtime)


def require_operations_access(
    request: Request,
    provided: Annotated[str | None, Security(operations_token_header)],
) -> None:
    settings = get_settings(request)
    configured = settings.operations_health_token
    if configured is None or provided is None or len(provided) > 512:
        raise ForbiddenError()
    if not hmac.compare_digest(provided, configured.get_secret_value()):
        raise ForbiddenError()
