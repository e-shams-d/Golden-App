# Backend runtime (M1)

This directory contains the buildable M1 foundation only. It intentionally has
no financial workflow logic or business tables.

## Runtime and reproducible dependencies

Python 3.12.x is required; CI and containers use the exact patch recorded in the
repository `.python-version`. Direct dependencies are exactly pinned in
`pyproject.toml`; all transitive artifacts are locked in `uv.lock`. The lock is
managed with `uv==0.8.22` and CI/developers must use frozen synchronization:

```bash
uv sync --frozen --group dev
```

Change dependencies through `pyproject.toml`, run `uv lock --upgrade-package
<explicit-package>`, review the lock diff, and never use an unlocked install in
CI or a release image.

## Local commands

From `services/backend`, create a private `.env` from `.env.example`, replace every
placeholder, and point the dependency URLs at non-production services that are
reachable from the native process. The default Compose topology deliberately does not
publish PostgreSQL or Redis to the host; use the root Compose workflow when you want
the complete local stack. Then run:

```bash
uv run alembic upgrade head
uv run uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --no-access-log
uv run celery -A app.workers.entrypoint:celery_app worker --loglevel=INFO \
  --queues=files,exports,notifications,reports,maintenance,ai
uv run pytest ../../tests/backend
uv run ruff check app ../../tests/backend
uv run mypy app
```

The application-owned request log replaces Uvicorn access logs so query-string
values are not emitted accidentally.

## API and operational access

All routes use `/api/v1`. The canonical health routes are:

- `/api/v1/health/live` (minimal and public/infrastructure-facing)
- `/api/v1/health/ready` (minimal readiness with bounded probes)
- `/api/v1/health/dependencies` (requires `X-Operations-Token`)
- `/api/v1/health/workers` (requires `X-Operations-Token`)

Safe release metadata is available at `/api/v1/meta/release`. Dependency URLs,
credentials, storage paths, exception messages, and provider payloads are never
included in health responses.

The Compose aliases `APP_VERSION` and `STORAGE_ROOT` are accepted, while
`RELEASE_VERSION` and `LOCAL_STORAGE_ROOT` are the canonical backend names.
