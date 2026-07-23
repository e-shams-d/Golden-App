"""Typed application errors and the canonical API error envelope."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger, log_event
from app.core.request_context import get_request_id


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str | None = None
    reason: str


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: list[ErrorDetail]
    request_id: str


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorBody


@dataclass(frozen=True)
class AppError(Exception):
    code: str
    message: str
    status_code: int
    details: tuple[ErrorDetail, ...] = ()


class ForbiddenError(AppError):
    def __init__(self) -> None:
        super().__init__("FORBIDDEN", "Permission denied.", 403)


class DependencyUnavailableError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "DEPENDENCY_UNAVAILABLE",
            "A required service dependency is unavailable.",
            503,
        )


class BackgroundProcessingUnavailableError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "BACKGROUND_PROCESSING_UNAVAILABLE",
            "Background processing is unavailable.",
            503,
        )


def _response(error: AppError) -> JSONResponse:
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code=error.code,
            message=error.message,
            details=list(error.details),
            request_id=get_request_id(),
        )
    )
    return JSONResponse(status_code=error.status_code, content=envelope.model_dump(mode="json"))


def _http_error(status_code: int) -> AppError:
    mapping: dict[int, tuple[str, str]] = {
        400: ("BAD_REQUEST", "The request is invalid."),
        401: ("UNAUTHENTICATED", "Authentication is required."),
        403: ("FORBIDDEN", "Permission denied."),
        404: ("NOT_FOUND", "The requested resource was not found."),
        405: ("BAD_REQUEST", "The HTTP method is not allowed."),
        409: ("CONFLICT", "The request conflicts with current state."),
        412: ("VERSION_CONFLICT", "The record changed after it was loaded."),
        413: ("FILE_TOO_LARGE", "The uploaded file is too large."),
        415: ("UNSUPPORTED_FILE_TYPE", "The file type is not supported."),
        428: ("PRECONDITION_REQUIRED", "A required request precondition is missing."),
        429: ("RATE_LIMITED", "Too many requests."),
        503: ("DEPENDENCY_UNAVAILABLE", "A required service dependency is unavailable."),
    }
    code, message = mapping.get(
        status_code,
        ("INTERNAL_ERROR", "An unexpected error occurred.")
        if status_code >= 500
        else ("BAD_REQUEST", "The request could not be processed."),
    )
    return AppError(code, message, status_code)


def install_exception_handlers(app: FastAPI) -> None:
    logger = get_logger("errors")

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        log_event(logger, logging.WARNING, "expected_request_error", error_code=exc.code)
        return _response(exc)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details: list[ErrorDetail] = []
        for item in exc.errors():
            location = [str(part) for part in item.get("loc", ()) if part != "body"]
            details.append(
                ErrorDetail(
                    field=".".join(location) or None,
                    reason=str(item.get("msg", "Invalid value"))[:256],
                )
            )
        return _response(
            AppError(
                "VALIDATION_ERROR",
                "One or more fields are invalid.",
                422,
                tuple(details),
            )
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return _response(_http_error(exc.status_code))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        log_event(
            logger,
            logging.ERROR,
            "unexpected_request_error",
            error_code="INTERNAL_ERROR",
            exception_type=type(exc).__name__,
        )
        return _response(AppError("INTERNAL_ERROR", "An unexpected error occurred.", 500))
