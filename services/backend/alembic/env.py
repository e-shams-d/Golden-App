"""Alembic environment using validated backend-only settings."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from app.core.config import load_settings
from app.db.base import Base
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Schemas this application does not own. `infra/scripts/verify-docker.sh` creates
# `m1_verification.persistence_probe` as a real table to prove data survives a
# container recreation, so autogenerate would otherwise propose dropping it and a
# reviewer could approve that without realising it deletes the acceptance evidence.
UNMANAGED_SCHEMAS = frozenset({"m1_verification"})


def database_url() -> str:
    return load_settings().database_url.get_secret_value()


def include_object(
    obj: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object | None,
) -> bool:
    """Keep autogenerate inside the schemas this application owns."""

    schema = getattr(obj, "schema", None)
    if schema in UNMANAGED_SCHEMAS:
        return False
    if type_ == "table" and getattr(obj, "schema", None) is None and reflected:
        # A reflected table with no schema is in the search path; still ours.
        return True
    return True


def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
    """Reject unmanaged schemas before their contents are ever reflected."""

    if type_ == "schema":
        return name not in UNMANAGED_SCHEMAS
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
        include_name=include_name,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_object=include_object,
            include_name=include_name,
            # One transaction per revision, not one around the whole run. A revision
            # that cannot run inside a transaction — CREATE INDEX CONCURRENTLY — is
            # then expressible, and a failure half way through a multi-revision
            # upgrade leaves the earlier revisions committed and recorded rather
            # than silently rolled back.
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
