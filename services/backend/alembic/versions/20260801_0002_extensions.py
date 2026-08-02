"""Create the PostgreSQL extensions required by 04_Database_Schema.md section 3.1.

The revision is tolerant by design. The extensions may legitimately be provisioned
outside Alembic (the db-bootstrap Compose one-shot locally and in CI, a provider
allow-list on managed PostgreSQL), so this revision verifies first, creates only
where the connected role is permitted to, and fails with an actionable message
otherwise. It never requires CREATE ON DATABASE and never grants anything.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

revision: str = "20260801_0002"
down_revision: str | None = "20260720_0001"
branch_labels: str | None = None
depends_on: str | None = None

REQUIRED_EXTENSIONS: tuple[str, ...] = ("pgcrypto", "citext")
TARGET_SCHEMA = "public"
PRIVILEGE_SQLSTATE = "42501"
UNAVAILABLE_SQLSTATES = frozenset({"58P01", "0A000"})


def extension_statement(name: str) -> str:
    return f'CREATE EXTENSION IF NOT EXISTS "{name}" WITH SCHEMA {TARGET_SCHEMA};'


def connection_identity(bind) -> tuple[str, str]:
    row = bind.execute(text("SELECT current_database(), current_user")).one()
    return str(row[0]), str(row[1])


def installed_schema(bind, name: str) -> str | None:
    found = bind.execute(
        text(
            "SELECT n.nspname FROM pg_extension e "
            "JOIN pg_namespace n ON n.oid = e.extnamespace "
            "WHERE e.extname = :name"
        ),
        {"name": name},
    ).scalar()
    return None if found is None else str(found)


def remediation_message(name: str, database: str, role: str, sqlstate: str) -> str:
    lines = [
        f'Migration {revision} could not create the required extension "{name}" in '
        f'schema {TARGET_SCHEMA} of database "{database}" as role "{role}" '
        f"(SQLSTATE {sqlstate})."
    ]
    if sqlstate == PRIVILEGE_SQLSTATE:
        lines.append(
            f'The connected role has no CREATE privilege on database "{database}". '
            "A superuser or the database owner must run this once, against "
            f'database "{database}":'
        )
    elif sqlstate in UNAVAILABLE_SQLSTATES:
        lines.append(
            f'The extension "{name}" is not installed on this PostgreSQL instance or '
            "is not allow-listed by the provider. The platform operator must enable "
            "it on the instance, then a superuser or the database owner must run, "
            f'against database "{database}":'
        )
    else:
        lines.append(
            "The failure is neither a privilege nor an availability condition that "
            "this revision recognises. Resolve the reported SQLSTATE, then a "
            "superuser or the database owner must run, against database "
            f'"{database}":'
        )
    lines.append(f"    {extension_statement(name)}")
    lines.append(
        "Do not grant CREATE ON DATABASE to the migration role as a workaround. "
        "That privilege also confers CREATE SCHEMA, permanently, on the role that "
        "owns all DDL, and it is deliberately not the supported remedy."
    )
    return "\n".join(lines)


def create_extension(bind, name: str, database: str, role: str) -> None:
    try:
        bind.exec_driver_sql(extension_statement(name))
    except DBAPIError as error:
        sqlstate = getattr(error.orig, "sqlstate", None) or "unknown"
        raise RuntimeError(remediation_message(name, database, role, sqlstate)) from error


def upgrade() -> None:
    bind = op.get_bind()
    database, role = connection_identity(bind)
    for name in REQUIRED_EXTENSIONS:
        schema = installed_schema(bind, name)
        if schema == TARGET_SCHEMA:
            continue
        if schema is not None:
            raise RuntimeError(
                f'Extension "{name}" exists in schema "{schema}" of database '
                f'"{database}", not in "{TARGET_SCHEMA}". CREATE EXTENSION IF NOT '
                "EXISTS would silently skip it and the migration role's search_path "
                f'would not reach it. Move it with: ALTER EXTENSION "{name}" SET '
                f"SCHEMA {TARGET_SCHEMA};"
            )
        create_extension(bind, name, database, role)
        if installed_schema(bind, name) != TARGET_SCHEMA:
            raise RuntimeError(
                f'Extension "{name}" was not present in schema {TARGET_SCHEMA} of '
                f'database "{database}" after CREATE EXTENSION reported success.'
            )


def downgrade() -> None:
    # Forward-fix policy (M2_IMPLEMENTATION_PLAN.md slice 1): extensions are never
    # dropped. Later revisions declare columns and defaults that depend on them.
    pass
