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


# The five below were reachable only by raising a bare StarletteHTTPException and
# letting `_http_error` map the status. That works for the status code and loses
# everything else: a command could not distinguish a stale version from a missing
# precondition, and no handler could attach a field-level detail. Codes and
# statuses match `docs/governance/api_error_catalog.yaml`.


class IdempotencyKeyReusedError(AppError):
    """Same key, different request. Never the same key with the same request.

    Replaying an identical request is the feature; this is the case where a
    client reused a key for different content, which would otherwise return the
    first request's response for the second request's parameters.
    """

    DEFAULT_MESSAGE = "The idempotency key was used for a different request."

    def __init__(self, message: str = DEFAULT_MESSAGE) -> None:
        super().__init__("IDEMPOTENCY_KEY_REUSED", message, 409)


class VersionConflictError(AppError):
    """The caller's expected version is not the current one."""

    def __init__(self, message: str = "The record changed after it was loaded.") -> None:
        super().__init__("VERSION_CONFLICT", message, 412)


class PreconditionRequiredError(AppError):
    """A required If-Match or Idempotency-Key was absent.

    Distinct from a stale precondition on purpose: 412 tells a client to reload
    and retry, while 428 tells it that its request was never safe to begin with.
    Collapsing them would have clients retrying a request that can only fail
    again.
    """

    def __init__(self, header: str) -> None:
        super().__init__(
            "PRECONDITION_REQUIRED",
            f"The {header} header is required for this command.",
            428,
            (ErrorDetail(field=header, reason="required"),),
        )


class InvalidStateTransitionError(AppError):
    """The command is not permitted from the aggregate's current state."""

    def __init__(self, message: str = "The command is not allowed from the current state.") -> None:
        super().__init__("INVALID_STATE_TRANSITION", message, 400)


class BusinessRuleViolationError(AppError):
    """A domain rule refused the command."""

    def __init__(self, message: str) -> None:
        super().__init__("BUSINESS_RULE_VIOLATION", message, 400)


class NotFoundError(AppError):
    """Missing, or deliberately hidden from this caller.

    A sixth alongside the five the plan named, because the exemplar command needs
    to distinguish a missing aggregate from a stale version and raising a bare
    StarletteHTTPException would leave it unable to. The code and status are the
    catalogue's.

    The message never says which of the two it is: telling an unauthorised caller
    that a resource exists is itself a disclosure.
    """

    def __init__(self) -> None:
        super().__init__("NOT_FOUND", "The requested resource was not found.", 404)


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
