"""Per-request identifiers propagated through context variables and responses."""

from __future__ import annotations

import logging
import time
from contextvars import ContextVar
from uuid import UUID, uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger, log_event

REQUEST_ID_HEADER = "X-Request-ID"
CORRELATION_ID_HEADER = "X-Correlation-ID"

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_request_id() -> str:
    return str(uuid4())


def normalize_external_id(value: str | None) -> str | None:
    if value is None or len(value) > 64:
        return None
    try:
        return str(UUID(value.strip()))
    except (ValueError, AttributeError):
        return None


def get_request_id() -> str:
    return _request_id.get() or new_request_id()


def get_correlation_id() -> str:
    return _correlation_id.get() or get_request_id()


class RequestContextMiddleware:
    """Validate/replace inbound IDs and add safe structured request logging."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.logger = get_logger("http")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = normalize_external_id(headers.get(REQUEST_ID_HEADER)) or new_request_id()
        correlation_id = (
            normalize_external_id(headers.get(CORRELATION_ID_HEADER)) or request_id
        )
        request_token = _request_id.set(request_id)
        correlation_token = _correlation_id.set(correlation_id)
        started = time.perf_counter()
        response_status = 500

        async def send_with_context(message: Message) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = int(message["status"])
                mutable_headers = MutableHeaders(scope=message)
                mutable_headers[REQUEST_ID_HEADER] = request_id
                mutable_headers[CORRELATION_ID_HEADER] = correlation_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        finally:
            route = scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            log_event(
                self.logger,
                logging.INFO,
                "http_request_completed",
                request_id=request_id,
                correlation_id=correlation_id,
                method=scope.get("method"),
                route=route_path,
                status_code=response_status,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            _request_id.reset(request_token)
            _correlation_id.reset(correlation_token)
