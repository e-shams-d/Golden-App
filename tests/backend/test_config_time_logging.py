from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import pytest
from app.core.config import Settings
from app.core.logging import JsonFormatter, sanitize_log_value
from app.core.time import BUSINESS_TIMEZONE_NAME, UTC, ensure_utc, to_business_time
from pydantic import ValidationError


def test_settings_enforce_time_contract_and_normalize_postgres_driver(settings_factory) -> None:
    settings = settings_factory(database_url="postgresql://app:secret@db/golden")

    assert settings.business_timezone == "Asia/Tehran"
    assert settings.internal_timezone == "UTC"
    assert settings.database_url.get_secret_value().startswith("postgresql+psycopg://")
    assert settings.queue_names == (
        "files",
        "exports",
        "notifications",
        "reports",
        "maintenance",
        "ai",
    )


def test_compose_aliases_are_accepted(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        APP_VERSION="2.3.4",
        RELEASE_COMMIT="abcdef1",
        RELEASE_BUILT_AT="2026-07-20T12:00:00Z",
        DATABASE_URL="postgresql+psycopg://app:secret@db/golden",
        REDIS_URL="redis://redis:6379/0",
        STORAGE_ROOT=tmp_path / "storage",
        OPERATIONS_HEALTH_TOKEN="x" * 32,
    )

    assert settings.release_version == "2.3.4"
    assert settings.local_storage_root == tmp_path / "storage"


def test_unrelated_host_debug_variable_is_not_consumed(
    settings_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEBUG", "release")

    settings = settings_factory()

    assert settings.app_debug is False


@pytest.mark.parametrize(
    ("override", "expected_fragment"),
    [
        ({"business_timezone": "UTC"}, "Asia/Tehran"),
        ({"internal_timezone": "Asia/Tehran"}, "UTC"),
        ({"database_url": "sqlite:///tmp.db"}, "PostgreSQL"),
        ({"redis_url": "http://redis"}, "redis://"),
        ({"local_storage_root": Path("relative")}, "absolute"),
        ({"release_built_at": "2026-07-20T12:00:00"}, "explicit timezone"),
    ],
)
def test_unsafe_settings_are_rejected(settings_factory, override, expected_fragment) -> None:
    with pytest.raises(ValidationError) as exc_info:
        settings_factory(**override)

    assert expected_fragment in str(exc_info.value)


def test_production_requires_operator_token_and_immutable_release(settings_factory) -> None:
    with pytest.raises(ValidationError):
        settings_factory(
            app_env="production",
            operations_health_token=None,
            release_commit="unknown",
            release_built_at=None,
        )


def test_production_requires_a_rate_limit_key_secret(settings_factory) -> None:
    """The limiter's Redis keys must be keyed, not merely hashed.

    Worth its own test because `settings_factory` supplies the secret by default
    so every other test can build production settings — and a requirement that
    every fixture satisfies is one nothing proves is enforced.

    A plain SHA-256 of an Iranian mobile number is reversible by enumerating
    about 10^9 candidates, so an unkeyed digest would put a directory of who uses
    the platform into a datastore with no persistence and no encryption.
    """

    with pytest.raises(ValidationError, match="AUTH_RATE_LIMIT_KEY_SECRET"):
        settings_factory(app_env="production", auth_rate_limit_key_secret=None)

    with pytest.raises(ValidationError, match="at least 32 characters"):
        settings_factory(app_env="production", auth_rate_limit_key_secret="too-short")

    # Outside production it is optional: local and test runs have no directory
    # worth protecting, and requiring it there would make the template a place
    # people paste a real secret.
    assert settings_factory(app_env="local", auth_rate_limit_key_secret=None) is not None


def test_production_requires_a_csrf_key_secret(settings_factory) -> None:
    """The CSRF token is an HMAC under this key, so an absent key makes it forgeable.

    Its own test for the same reason as the rate-limit key: `settings_factory`
    supplies it by default so every other test can build production settings, and
    a requirement every fixture satisfies is one nothing proves is enforced.
    """

    with pytest.raises(ValidationError, match="AUTH_CSRF_KEY_SECRET"):
        settings_factory(app_env="production", auth_csrf_key_secret=None)

    with pytest.raises(ValidationError, match="at least 32 characters"):
        settings_factory(app_env="production", auth_csrf_key_secret="too-short")


def test_settings_repr_masks_dependency_credentials(settings_factory) -> None:
    rendered = repr(settings_factory())

    assert "database-secret" not in rendered
    assert "redis-secret" not in rendered
    assert "**********" in rendered


def test_internal_time_is_utc_and_business_conversion_is_explicit() -> None:
    source = datetime.fromisoformat("2026-07-20T12:00:00+00:00")

    assert ensure_utc(source).tzinfo is UTC
    converted = to_business_time(source)
    assert converted.tzinfo is not None
    assert getattr(converted.tzinfo, "key", None) == BUSINESS_TIMEZONE_NAME
    with pytest.raises(ValueError):
        ensure_utc(datetime(2026, 7, 20, 12, 0, 0))


def test_structured_logging_recursively_redacts_sensitive_values() -> None:
    sanitized = sanitize_log_value(
        {
            "password": "plain",
            "nested": {"session_token": "token-value"},
            "message": "Bearer abc.def and IR820540102680020817909002",
            "binary": b"receipt-content",
        }
    )

    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["nested"]["session_token"] == "[REDACTED]"
    assert "abc.def" not in sanitized["message"]
    assert "IR820540102680020817909002" not in sanitized["message"]
    assert sanitized["binary"] == "[BINARY REDACTED]"


def test_json_formatter_emits_utc_structured_record_without_secret() -> None:
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "connected with postgresql://user:password@db/golden",
        (),
        None,
    )
    record.service = "backend-api"
    record.environment = "test"
    record.release_version = "0.1.0"
    record.event_data = {"authorization": "Bearer raw-token", "request_id": "request"}

    payload = json.loads(JsonFormatter().format(record))

    assert payload["timestamp"].endswith("Z")
    assert payload["authorization"] == "[REDACTED]"
    assert "password" not in payload["message"]
    assert payload["request_id"] == "request"
