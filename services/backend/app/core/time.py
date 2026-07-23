"""Canonical time helpers.

Persistence and inter-service timestamps are always UTC.  Asia/Tehran is a
presentation/business-calendar concern and must be requested explicitly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

BUSINESS_TIMEZONE_NAME = "Asia/Tehran"
INTERNAL_TIMEZONE_NAME = "UTC"
BUSINESS_TIMEZONE = ZoneInfo(BUSINESS_TIMEZONE_NAME)
UTC = UTC


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(tz=UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalize an aware datetime to UTC and reject ambiguous naive values."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include an explicit timezone")
    return value.astimezone(UTC)


def to_business_time(value: datetime) -> datetime:
    """Convert an aware timestamp for Tehran business-calendar presentation."""

    return ensure_utc(value).astimezone(BUSINESS_TIMEZONE)
