"""Grant mutation per table, and repair volumes the old default already touched.

Two jobs, and the second is why this cannot be folded into 20260801_0004.

**Grant.** `020-runtime-roles.sql` no longer grants UPDATE or DELETE by default,
so a table is immutable to the runtime roles unless a migration says otherwise.
The three mutable tables say so here. `audit_logs` is absent, deliberately.

**Repair.** `ALTER DEFAULT PRIVILEGES` only affects tables created *afterwards*.
Every existing volume — the acceptance clone, every developer database, every CI
volume that survived a `compose down` — already has tables carrying the old
four-verb grant. Narrowing the default does nothing for them. So this revision
also revokes UPDATE and DELETE on `audit_logs` from every grantee that is not
the owner, on the database it runs against.

The roles are read from settings rather than hardcoded, because the identity the
application connects as is operator configuration. A revision that granted to a
literal `platform_app` would constrain a role nothing connects as, and the
evidence gate would pass while being false. A configured role that does not exist
fails this revision rather than being skipped.
"""

from __future__ import annotations

from alembic import op
from app.core.config import load_settings
from sqlalchemy import text

revision: str = "20260801_0005"
down_revision: str | None = "20260801_0004"
branch_labels: str | None = None
depends_on: str | None = None

# Tables whose rows legitimately change after they are written.
MUTABLE_TABLES: tuple[str, ...] = ("center_profile", "outbox_events", "idempotency_records")

# Append-only. Named here so the omission above is visibly deliberate rather
# than an oversight, and so the revoke below has an explicit subject.
APPEND_ONLY_TABLES: tuple[str, ...] = ("audit_logs",)

REVOKE_APPEND_ONLY_MUTATION = """
DO $$
DECLARE
    target text;
    relation text;
BEGIN
    FOREACH relation IN ARRAY %(tables)s LOOP
        FOR target IN
            SELECT DISTINCT grantee
            FROM information_schema.role_table_grants
            WHERE table_schema = 'public'
              AND table_name = relation
              AND privilege_type IN ('UPDATE', 'DELETE')
              AND grantee <> current_user
        LOOP
            IF target = 'PUBLIC' THEN
                EXECUTE format('REVOKE UPDATE, DELETE ON public.%%I FROM PUBLIC', relation);
            ELSE
                EXECUTE format(
                    'REVOKE UPDATE, DELETE ON public.%%I FROM %%I', relation, target
                );
            END IF;
        END LOOP;
    END LOOP;
END
$$;
"""


def mutation_roles() -> tuple[str, ...]:
    """The roles that write business data, from configuration.

    Failing here is the point. A revision that silently skipped an unset role
    would leave the runtime unable to update its own tables, and the first
    symptom would be a permission error in a request rather than a clear message
    at deploy time.
    """

    settings = load_settings()
    configured = {
        "APP_DB_ROLE (or APP_DB_USER)": settings.app_db_role,
        "WORKER_DB_ROLE (or WORKER_DB_USER)": settings.worker_db_role,
    }
    missing = sorted(name for name, value in configured.items() if not value)
    if missing:
        raise RuntimeError(
            f"Migration {revision} grants table privileges to the configured runtime "
            f"roles, and these are not set: {', '.join(missing)}. Set them to the "
            "same usernames the backend and worker connect as; the grant must name "
            "the identity that actually connects or it constrains nothing."
        )
    return tuple(value for value in configured.values() if value)


def assert_roles_exist(roles: tuple[str, ...]) -> None:
    """A configured name that is not a role means the grant would silently miss."""

    bind = op.get_bind()
    present = {
        row[0]
        for row in bind.execute(
            text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:names)"),
            {"names": list(roles)},
        )
    }
    absent = sorted(set(roles) - present)
    if absent:
        raise RuntimeError(
            f"Migration {revision} is configured to grant to roles that do not exist "
            f"in this database: {absent}. Provisioning (infra/postgres/bootstrap/"
            "020-runtime-roles.sql) must run before migrations."
        )


def upgrade() -> None:
    roles = mutation_roles()
    assert_roles_exist(roles)

    bind = op.get_bind()
    for table in MUTABLE_TABLES:
        for role in roles:
            bind.execute(text(f'GRANT UPDATE, DELETE ON public."{table}" TO "{role}"'))

    # Repair, not belt-and-braces: on an existing volume this is the only thing
    # that removes a grant the old default already materialised.
    bind.execute(
        text(REVOKE_APPEND_ONLY_MUTATION % {"tables": f"ARRAY{list(APPEND_ONLY_TABLES)}"})
    )


def downgrade() -> None:
    """Return the mutable tables to the fail-closed position.

    The append-only revoke is not undone. Restoring the ability to rewrite audit
    rows is not something a downgrade should offer, and no governed procedure
    authorises it.
    """

    roles = mutation_roles()
    bind = op.get_bind()
    for table in MUTABLE_TABLES:
        for role in roles:
            bind.execute(text(f'REVOKE UPDATE, DELETE ON public."{table}" FROM "{role}"'))
