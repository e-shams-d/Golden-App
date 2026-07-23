FROM python:3.12.13-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy

RUN python -m pip install uv==0.8.22

WORKDIR /app
COPY services/backend/pyproject.toml services/backend/uv.lock services/backend/README.md ./
COPY services/backend/app ./app
COPY services/backend/alembic ./alembic
COPY services/backend/alembic.ini ./alembic.ini

RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12.13-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/storage \
    && chown -R app:app /app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app services/backend/app ./app
COPY --chown=app:app services/backend/alembic ./alembic
COPY --chown=app:app services/backend/alembic.ini services/backend/pyproject.toml ./

USER app
EXPOSE 8000
STOPSIGNAL SIGTERM
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
