"""Structured JSON logging with centralized redaction."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SENSITIVE_KEY_PARTS = {
    "authorization",
    "cookie",
    "csrf",
    "database_url",
    "iban",
    "national_id",
    "password",
    "redis_url",
    "secret",
    "session",
    "signed_url",
    "token",
}
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_IBAN_PATTERN = re.compile(r"(?i)\bIR\d{24}\b")
_URL_CREDENTIAL_PATTERN = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@", re.I)
_MAX_DEPTH = 8


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def redact_text(value: str) -> str:
    """Mask common secret/financial patterns in otherwise-safe log text."""

    value = _BEARER_PATTERN.sub("Bearer [REDACTED]", value)
    value = _IBAN_PATTERN.sub("IR********************[REDACTED]", value)
    return _URL_CREDENTIAL_PATTERN.sub(r"\g<scheme>[REDACTED]@", value)


def sanitize_log_value(value: Any, *, _depth: int = 0) -> Any:
    """Recursively produce a bounded, JSON-safe, redacted value."""

    if _depth >= _MAX_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]"
            if _is_sensitive_key(key)
            else sanitize_log_value(item, _depth=_depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_log_value(item, _depth=_depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return redact_text(value[:4096])
    if isinstance(value, (bytes, bytearray)):
        return "[BINARY REDACTED]"
    if isinstance(value, Path):
        return value.name
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(str(value)[:4096])


class JsonFormatter(logging.Formatter):
    """Small deterministic JSON formatter; exception payloads stay out of logs."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).isoformat().replace(
            "+00:00", "Z"
        )
        payload: dict[str, Any] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "service": getattr(record, "service", "backend-api"),
            "environment": getattr(record, "environment", "unknown"),
            "release_version": getattr(record, "release_version", "unknown"),
            "message": redact_text(record.getMessage()),
        }
        event_data = getattr(record, "event_data", None)
        if isinstance(event_data, Mapping):
            payload.update(sanitize_log_value(event_data))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


class ServiceContextFilter(logging.Filter):
    def __init__(self, *, service: str, environment: str, release_version: str) -> None:
        super().__init__()
        self.service = service
        self.environment = environment
        self.release_version = release_version

    def filter(self, record: logging.LogRecord) -> bool:
        record.service = self.service
        record.environment = self.environment
        record.release_version = self.release_version
        return True


def configure_logging(*, level: str, service: str, environment: str, release_version: str) -> None:
    """Configure only application loggers and leave the host process in control."""

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(
        ServiceContextFilter(
            service=service,
            environment=environment,
            release_version=release_version,
        )
    )
    logger = logging.getLogger("golden_backend")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"golden_backend.{name}")


def log_event(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    logger.log(level, message, extra={"event_data": sanitize_log_value(fields)})
