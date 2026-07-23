"""FastAPI application factory and graceful process lifecycle."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.contract import API_CONTRACT_VERSION
from app.api.router import api_v1_router
from app.core.config import Settings, load_settings
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging, get_logger, log_event
from app.core.request_context import RequestContextMiddleware
from app.core.runtime import RuntimeServices

RuntimeFactory = Callable[[Settings], RuntimeServices]


def create_app(
    settings: Settings | None = None,
    runtime_factory: RuntimeFactory | None = None,
) -> FastAPI:
    """Build an application without opening database, Redis, or storage connections."""

    resolved_settings = settings or load_settings()
    configure_logging(
        level=resolved_settings.log_level,
        service=resolved_settings.service_name,
        environment=resolved_settings.app_env,
        release_version=resolved_settings.release_version,
    )
    logger = get_logger("lifecycle")
    build_runtime = runtime_factory or RuntimeServices.from_settings

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = build_runtime(resolved_settings)
        app.state.runtime = runtime
        app.state.accepting_traffic = True
        log_event(
            logger,
            logging.INFO,
            "backend_started",
            release_version=resolved_settings.release_version,
            release_commit=resolved_settings.release_commit,
        )
        try:
            yield
        finally:
            app.state.accepting_traffic = False
            runtime.close()
            log_event(logger, logging.INFO, "backend_stopped")

    contract_discovery_enabled = resolved_settings.app_env != "production"
    app = FastAPI(
        title="Gold Trade Settlement Backend API",
        summary="Manual-first settlement platform backend",
        description=(
            "Versioned operational API. Financial workflow modules are intentionally "
            "not part of the M1 runtime foundation."
        ),
        # The HTTP contract version is intentionally independent of the deploy
        # release. Deployment identity is exposed by /api/v1/meta/release.
        version=API_CONTRACT_VERSION,
        # Production intentionally does not publish either the interactive
        # documentation or its discovery document. The deterministic exporter
        # builds the canonical contract with an isolated test configuration.
        openapi_url="/api/v1/openapi.json" if contract_discovery_enabled else None,
        docs_url="/api/v1/docs" if contract_discovery_enabled else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.accepting_traffic = False
    app.add_middleware(RequestContextMiddleware)
    install_exception_handlers(app)
    app.include_router(api_v1_router)
    return app
