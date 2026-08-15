"""Typed, fail-closed service configuration."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__
from app.core.time import (
    BUSINESS_TIMEZONE_NAME,
    INTERNAL_TIMEZONE_NAME,
    ensure_utc,
)

_COMMIT_PATTERN = re.compile(r"^(?:unknown|(?:sha256:)?[0-9a-f]{7,64})$")


class Settings(BaseSettings):
    """Backend-only settings loaded from environment variables.

    Secrets remain ``SecretStr`` instances so repr/traceback output does not
    reveal connection credentials.  Business rules do not belong here.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="forbid",
        populate_by_name=True,
        validate_default=True,
    )

    app_env: Literal["local", "test", "staging", "production"] = Field(
        default="local", validation_alias="APP_ENV"
    )
    service_name: str = Field(
        default="backend-api",
        min_length=1,
        max_length=64,
        validation_alias="SERVICE_NAME",
    )
    # Keep the field name distinct from the common process-level DEBUG
    # variable. With populate_by_name enabled, a field named ``debug`` could
    # otherwise consume an unrelated host setting such as DEBUG=release.
    app_debug: bool = Field(default=False, validation_alias="APP_DEBUG")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", validation_alias="LOG_LEVEL"
    )

    release_version: str = Field(
        default=__version__,
        min_length=1,
        max_length=64,
        validation_alias=AliasChoices("RELEASE_VERSION", "APP_VERSION"),
    )
    release_commit: str = Field(
        default="unknown", min_length=7, max_length=71, validation_alias="RELEASE_COMMIT"
    )
    release_built_at: datetime | None = Field(default=None, validation_alias="RELEASE_BUILT_AT")

    business_timezone: str = Field(
        default=BUSINESS_TIMEZONE_NAME, validation_alias="BUSINESS_TIMEZONE"
    )
    internal_timezone: str = Field(
        default=INTERNAL_TIMEZONE_NAME, validation_alias="INTERNAL_TIMEZONE"
    )

    database_url: SecretStr = Field(validation_alias="DATABASE_URL")
    redis_url: SecretStr = Field(validation_alias="REDIS_URL")

    # Role names the *migrations* grant against. Read from the same variables the
    # Compose stack already uses to build each service's connection string, via
    # AliasChoices, so there is one source of truth per role rather than a second
    # variable that can drift from the one the application actually connects as —
    # which is the exact failure SEC-ROLE-000 exists to catch.
    #
    # Optional because the API and worker never need them; only a migration does.
    # A migration that finds one unset fails loudly and names it, rather than
    # skipping a grant and leaving the runtime to discover it.
    app_db_role: str | None = Field(
        default=None, validation_alias=AliasChoices("APP_DB_ROLE", "APP_DB_USER")
    )
    worker_db_role: str | None = Field(
        default=None, validation_alias=AliasChoices("WORKER_DB_ROLE", "WORKER_DB_USER")
    )
    readonly_db_role: str | None = Field(
        default=None, validation_alias=AliasChoices("READONLY_DB_ROLE", "READONLY_DB_USER")
    )
    backup_db_role: str | None = Field(
        default=None, validation_alias=AliasChoices("BACKUP_DB_ROLE", "BACKUP_DB_USER")
    )
    storage_backend: Literal["local"] = Field(default="local", validation_alias="STORAGE_BACKEND")
    local_storage_root: Path = Field(
        validation_alias=AliasChoices("LOCAL_STORAGE_ROOT", "STORAGE_ROOT")
    )

    # POL-006 is open. `docs/governance/file_purpose_catalog.yaml` carries conservative
    # development-only size limits, each marked `blocked_by_POL_006`, and the safe
    # default the register records is "no guessed production values ... and block
    # production acceptance/load sign-off".
    #
    # A marker in a YAML file blocks nothing on its own, so this is what makes it real:
    # production refuses to start while the limits are still the guessed ones. Declaring
    # them approved is a deliberate act by whoever holds POL-006, not a default somebody
    # inherits by deploying.
    file_upload_limits_are_production_approved: bool = Field(
        default=False, validation_alias="FILE_UPLOAD_LIMITS_ARE_PRODUCTION_APPROVED"
    )

    dependency_timeout_seconds: float = Field(
        default=1.5, gt=0.05, le=10.0, validation_alias="DEPENDENCY_TIMEOUT_SECONDS"
    )

    # How long a caller waits for a connection from the pool. Deliberately its own
    # setting rather than reusing `dependency_timeout_seconds`, which is a health
    # probe's patience. Binding the two meant adding an outbox poller alongside
    # request traffic produced 500s at low concurrency, and the only remedy —
    # raising the number — loosened every health probe at the same time.
    db_pool_timeout_seconds: float = Field(
        default=10.0, gt=0.1, le=60.0, validation_alias="DB_POOL_TIMEOUT_SECONDS"
    )
    db_pool_size: int = Field(default=5, ge=1, le=100, validation_alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=5, ge=0, le=100, validation_alias="DB_MAX_OVERFLOW")

    # Per-connection limits, applied by the server rather than by the caller.
    #
    # None exist today, and their absence is not theoretical: `task_acks_late` is
    # on and the worker prefetch is 1, so a task blocked forever on a contended
    # `SELECT ... FOR UPDATE` is redelivered on top of locks the first attempt
    # still holds. Each redelivery adds a waiter, and the queue drains only when
    # something is killed by hand.
    #
    # `lock_timeout` is much shorter than `statement_timeout` on purpose: waiting
    # on a lock is contention, which retrying resolves, while a long-running
    # statement is usually a query that needs fixing rather than more patience.
    statement_timeout_ms: int = Field(
        default=30_000, ge=0, le=600_000, validation_alias="STATEMENT_TIMEOUT_MS"
    )
    lock_timeout_ms: int = Field(
        default=5_000, ge=0, le=600_000, validation_alias="LOCK_TIMEOUT_MS"
    )
    idle_in_transaction_timeout_ms: int = Field(
        default=60_000, ge=0, le=3_600_000, validation_alias="IDLE_IN_TRANSACTION_TIMEOUT_MS"
    )
    worker_probe_timeout_seconds: float = Field(
        default=1.5, gt=0.05, le=10.0, validation_alias="WORKER_PROBE_TIMEOUT_SECONDS"
    )
    redis_required_for_readiness: bool = Field(
        default=True, validation_alias="REDIS_REQUIRED_FOR_READINESS"
    )

    operations_health_token: SecretStr | None = Field(
        default=None, validation_alias="OPERATIONS_HEALTH_TOKEN"
    )

    # Argon2id, per `12_Security_RBAC_Audit.md:381`. Every bound below is a floor
    # with a security argument, not a preference, which is why none of them is
    # zero-able: `validate_default=True` means a default beneath its own floor
    # fails at construction rather than at the first login.
    #
    # The defaults were measured on the development host (8 cores) rather than
    # copied: at t=3, m=64 MiB, p=4 a verification takes ~80-110 ms. The number
    # that matters more is the degraded one — `parallelism` is a property of the
    # hash, not a runtime knob, so on a single-core container the same hash costs
    # the full serial ~350 ms. That is still acceptable for a login and is the
    # figure to plan capacity against, because assuming the parallel number would
    # under-provision by 4x.
    #
    # Memory is the parameter that resists GPU and ASIC cracking, so the floor is
    # 64 MiB rather than OWASP's 47 MiB minimum: the threat here is an offline
    # attack on a stolen dump of a settlement platform's credentials. It is also
    # a denial-of-service lever against us — concurrent logins multiply it — which
    # is why authentication rate limiting is a required part of this milestone
    # rather than an optimisation.
    argon2_time_cost: int = Field(default=3, ge=2, le=10, validation_alias="ARGON2_TIME_COST")
    argon2_memory_cost_kib: int = Field(
        default=65_536, ge=65_536, le=1_048_576, validation_alias="ARGON2_MEMORY_COST_KIB"
    )
    argon2_parallelism: int = Field(default=4, ge=1, le=16, validation_alias="ARGON2_PARALLELISM")

    # A ceiling, not a policy. `12_Security_RBAC_Audit.md:394` requires a maximum
    # so a very long input cannot be a denial-of-service vector, and Argon2 hashes
    # its input in one pass, so the cost is real but bounded. The *minimum* length
    # and the compromised-password rule are production policy (`:390-397`) and are
    # not decided here.
    password_max_length: int = Field(
        default=128, ge=64, le=1024, validation_alias="PASSWORD_MAX_LENGTH"
    )

    # Bytes of CSPRNG entropy behind each session secret. The floor is the
    # security property rather than a preference: the stored digest is a fast,
    # unsalted SHA-256, which is only sound because the input is uniform and
    # large. Below 32 bytes that argument stops holding and the column stops
    # being a credential. The ceiling only keeps the cookie small.
    #
    # No session *lifetime* setting is added here. Idle and absolute timeouts are
    # ADR-SEC-002, which is Open, and a default would decide it silently.
    session_secret_bytes: int = Field(
        default=32, ge=32, le=64, validation_alias="SESSION_SECRET_BYTES"
    )

    # Durable failed-login lockout, held in PostgreSQL because
    # `infra/redis/redis.conf` sets `appendonly no` and `save ""` and a counter
    # that resets on restart is one an attacker can reset (`:488`).
    #
    # The threshold is never told to the client (`:486`): "3 attempts remaining"
    # tells an attacker their exact budget and when to pause.
    auth_lockout_threshold: int = Field(
        default=5, ge=3, le=50, validation_alias="AUTH_LOCKOUT_THRESHOLD"
    )
    auth_lockout_seconds: int = Field(
        default=900, ge=60, le=86_400, validation_alias="AUTH_LOCKOUT_SECONDS"
    )

    # Authentication rate limiting. The two ceilings are deliberately far apart.
    #
    # This platform is deployed only in Iran, where carrier-grade NAT is normal on
    # mobile networks: hundreds of unrelated subscribers share one public address.
    # A network ceiling tight enough to stop one attacker would lock out an entire
    # carrier's customers, while the attacker rotates address or waits. So the
    # identifier ceiling is the control and the network ceiling is a coarse
    # backstop for the one case the identifier axis cannot see — a single source
    # spraying many different usernames.
    auth_rate_limit_window_seconds: int = Field(
        default=300, ge=30, le=3_600, validation_alias="AUTH_RATE_LIMIT_WINDOW_SECONDS"
    )
    auth_rate_limit_identifier_max: int = Field(
        default=10, ge=3, le=1_000, validation_alias="AUTH_RATE_LIMIT_IDENTIFIER_MAX"
    )
    auth_rate_limit_network_max: int = Field(
        default=300, ge=10, le=100_000, validation_alias="AUTH_RATE_LIMIT_NETWORK_MAX"
    )

    # Keys the limiter writes to Redis are HMACs, not raw identifiers: a plain
    # hash of an Iranian mobile number is reversible by enumerating ~10^9
    # candidates, so unkeyed hashing would put a directory of who uses the
    # platform, and from where, into a datastore with no persistence and no
    # encryption. Required in production; absent elsewhere the limiter refuses to
    # build rather than silently hashing without a key.
    auth_rate_limit_key_secret: SecretStr | None = Field(
        default=None, validation_alias="AUTH_RATE_LIMIT_KEY_SECRET"
    )

    # Separate from the rate-limit key rather than derived from it. One secret
    # doing two jobs means rotating it for one reason has a consequence for the
    # other, and the two have different blast radii: a leaked rate-limit key
    # de-anonymises Redis keys, a leaked CSRF key lets an attacker forge tokens
    # for sessions they can name. Keeping them apart makes each rotation a local
    # decision.
    auth_csrf_key_secret: SecretStr | None = Field(
        default=None, validation_alias="AUTH_CSRF_KEY_SECRET"
    )

    # ADR-SEC-002 owns the real numbers and is Open, so these are **provisional**
    # and no test asserts either value. What the tests assert is what
    # `12_Security_RBAC_Audit.md` does state without an ADR: a session cannot
    # outlive deactivation or a security-stamp change (`:461`), expiry is
    # enforced server-side (`:462`), and an expired session gets a clear 401
    # (`:464`).
    #
    # The admin default is shorter than the trader default because `:460`
    # requires the stricter policy for internal sessions where operationally
    # reasonable — staff sit at shared desks inside an office; a trader is on
    # their own phone. Bounds rather than a free integer so a deployment cannot
    # set an effectively infinite session by typing an extra zero.
    admin_session_lifetime_seconds: int = Field(
        default=28_800, ge=300, le=86_400, validation_alias="ADMIN_SESSION_LIFETIME_SECONDS"
    )
    trader_session_lifetime_seconds: int = Field(
        default=86_400, ge=300, le=604_800, validation_alias="TRADER_SESSION_LIFETIME_SECONDS"
    )

    # How long a recent-auth context stays presentable. ADR-009 owns the real
    # number and is Open, so this is **provisional** and no test asserts it;
    # `12_Security_RBAC_Audit.md:554` gives only the shape of the requirement —
    # "short enough for high-risk financial use". The ceiling is deliberately low:
    # a step-up that lasts an hour is a step-up that outlives the reason someone
    # was standing at the keyboard.
    step_up_lifetime_seconds: int = Field(
        default=300, ge=30, le=900, validation_alias="STEP_UP_LIFETIME_SECONDS"
    )

    celery_queues: str = Field(
        default="files,exports,notifications,reports,maintenance,ai",
        validation_alias="CELERY_QUEUES",
    )
    celery_task_always_eager: bool = Field(
        default=False, validation_alias="CELERY_TASK_ALWAYS_EAGER"
    )

    @field_validator("release_commit")
    @classmethod
    def validate_release_commit(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _COMMIT_PATTERN.fullmatch(normalized):
            raise ValueError("RELEASE_COMMIT must be 'unknown' or a hexadecimal digest")
        return normalized

    @field_validator("release_built_at")
    @classmethod
    def validate_release_built_at(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)

    @field_validator("business_timezone")
    @classmethod
    def validate_business_timezone(cls, value: str) -> str:
        if value != BUSINESS_TIMEZONE_NAME:
            raise ValueError("BUSINESS_TIMEZONE must be Asia/Tehran")
        return value

    @field_validator("internal_timezone")
    @classmethod
    def validate_internal_timezone(cls, value: str) -> str:
        if value != INTERNAL_TIMEZONE_NAME:
            raise ValueError("INTERNAL_TIMEZONE must be UTC")
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        raw_value = value.get_secret_value()
        scheme = urlsplit(raw_value).scheme.lower()
        if scheme not in {"postgres", "postgresql", "postgresql+psycopg"}:
            raise ValueError("DATABASE_URL must use PostgreSQL with the psycopg driver")
        if scheme != "postgresql+psycopg":
            raw_value = "postgresql+psycopg://" + raw_value.split("://", 1)[1]
        return SecretStr(raw_value)

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr) -> SecretStr:
        if urlsplit(value.get_secret_value()).scheme.lower() not in {"redis", "rediss"}:
            raise ValueError("REDIS_URL must use redis:// or rediss://")
        return value

    @field_validator("local_storage_root")
    @classmethod
    def validate_storage_root(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("LOCAL_STORAGE_ROOT must be an absolute path")
        return value

    @field_validator("celery_queues")
    @classmethod
    def validate_celery_queues(cls, value: str) -> str:
        names = [part.strip() for part in value.split(",") if part.strip()]
        if not names or len(names) != len(set(names)):
            raise ValueError("CELERY_QUEUES must contain unique comma-separated names")
        invalid = [name for name in names if not re.fullmatch(r"[a-z][a-z0-9_-]{0,62}", name)]
        if invalid:
            raise ValueError("CELERY_QUEUES contains an invalid queue name")
        return ",".join(names)

    @model_validator(mode="after")
    def validate_environment_safety(self) -> Self:
        if self.app_debug and self.app_env in {"staging", "production"}:
            raise ValueError("APP_DEBUG must be disabled outside local/test environments")

        token = (
            self.operations_health_token.get_secret_value()
            if self.operations_health_token is not None
            else ""
        )
        if token and len(token) < 32:
            raise ValueError("OPERATIONS_HEALTH_TOKEN must contain at least 32 characters")

        if self.app_env == "production":
            if not token:
                raise ValueError("OPERATIONS_HEALTH_TOKEN is required in production")
            if self.release_commit == "unknown" or self.release_built_at is None:
                raise ValueError("production requires immutable release commit and build time")
            if not self.redis_required_for_readiness:
                raise ValueError("Redis readiness cannot be disabled in production")
            rate_limit_secret = (
                self.auth_rate_limit_key_secret.get_secret_value()
                if self.auth_rate_limit_key_secret is not None
                else ""
            )
            if len(rate_limit_secret) < 32:
                raise ValueError(
                    "AUTH_RATE_LIMIT_KEY_SECRET must contain at least 32 characters in "
                    "production; without it the limiter's Redis keys are a plain hash of a "
                    "phone number, which is reversible by enumeration"
                )
            csrf_secret = (
                self.auth_csrf_key_secret.get_secret_value()
                if self.auth_csrf_key_secret is not None
                else ""
            )
            if len(csrf_secret) < 32:
                raise ValueError(
                    "AUTH_CSRF_KEY_SECRET must contain at least 32 characters in "
                    "production; the CSRF token is an HMAC under this key, so without it "
                    "the token is forgeable by anyone who learns a session's stored digest"
                )
            if not self.file_upload_limits_are_production_approved:
                raise ValueError(
                    "FILE_UPLOAD_LIMITS_ARE_PRODUCTION_APPROVED must be set in production. "
                    "The size limits in docs/governance/file_purpose_catalog.yaml are "
                    "development-only values marked blocked_by_POL_006, and POL-006 — "
                    "production file size/type limits — is open. Accepting uploads under "
                    "guessed limits is the failure its safe default names"
                )
        return self

    @property
    def queue_names(self) -> tuple[str, ...]:
        return tuple(self.celery_queues.split(","))


def load_settings() -> Settings:
    """Load and validate backend configuration from the process environment."""

    return Settings()
