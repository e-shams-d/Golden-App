"""Synchronous SQLAlchemy engine/session construction."""

from __future__ import annotations

import math

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings

SessionFactory = sessionmaker[Session]


def create_engine_and_session_factory(settings: Settings) -> tuple[Engine, SessionFactory]:
    engine = create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_recycle=300,
        pool_timeout=settings.dependency_timeout_seconds,
        connect_args={
            "connect_timeout": max(1, math.ceil(settings.dependency_timeout_seconds)),
            "application_name": f"{settings.service_name}:{settings.release_version}",
        },
    )
    factory = sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )
    return engine, factory
