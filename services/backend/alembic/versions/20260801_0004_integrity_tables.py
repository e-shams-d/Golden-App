"""Create audit_logs, outbox_events and idempotency_records.

These three are the integrity spine: what happened, what must be told to the
outside world, and what must not happen twice. They arrive together because the
exemplar command writes all three in one transaction, and a slice that delivered
one without the others could not prove that.

CHECK constraints carry the **bare** name, exactly as the models pass it to
`named_check`. `op.create_table` applies `Base.metadata`'s naming convention, and
the `ck` rule interpolates `%(constraint_name)s`, so writing the full
`ck_audit_logs_...` here produces `ck_audit_logs_ck_audit_logs_...` — which then
silently truncates at 63 bytes with a hash suffix. Indexes, primary keys and
unique constraints do take their full names, because those convention rules do
not interpolate the given name.

`tests/integration/test_constraint_names.py` compares what the database ends up
with against what the models declare, because Alembic's autogenerate comparison
does not look at CHECK constraints at all.

Forward-fix policy: `audit_logs` is append-only evidence. `downgrade()` therefore
drops only what this revision created in a database that has not yet been used,
which is the honest limit of what a downgrade can offer — recovering audit rows
after a drop is not something a migration can promise, and no downgrade here
should read as if it could.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260801_0004"
down_revision: str | None = "20260801_0003"
branch_labels: str | None = None
depends_on: str | None = None

ACTOR_TYPES_SQL = "'trader_user', 'admin_user', 'system_worker', 'system_maintenance'"
OUTBOX_STATUSES_SQL = "'pending', 'processing', 'published', 'failed', 'dead_lettered'"
OUTBOX_CLAIMABLE_SQL = "'pending', 'processing', 'failed'"


def _create_audit_logs() -> None:
    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # Identity rather than a bare sequence default, so the ordering key cannot
        # be supplied by a caller that thinks it knows better.
        sa.Column(
            "sequence_number",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column(
            "audit_schema_version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "actor_role_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recent_auth_context_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("authentication_assurance", sa.String(length=48), nullable=True),
        sa.Column("entity_type", sa.String(length=80), nullable=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("parent_entity_type", sa.String(length=80), nullable=True),
        sa.Column("parent_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entity_record_version", sa.BigInteger(), nullable=True),
        sa.Column("immutable_snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("previous_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("reason_code", sa.String(length=80), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("causation_id", sa.String(length=64), nullable=True),
        sa.Column("idempotency_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("previous_event_hash", sa.String(length=64), nullable=True),
        sa.Column("event_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("metadata_schema", sa.String(length=120), nullable=False),
        sa.Column("metadata_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"actor_type IN ({ACTOR_TYPES_SQL})", name="actor_type"
        ),
        sa.CheckConstraint(
            "audit_schema_version > 0", name="audit_schema_version_positive"
        ),
        sa.CheckConstraint("metadata_version > 0", name="metadata_version_positive"),
        sa.CheckConstraint("length(btrim(action)) > 0", name="action_not_blank"),
        sa.CheckConstraint("length(btrim(outcome)) > 0", name="outcome_not_blank"),
        sa.CheckConstraint(
            "length(btrim(metadata_schema)) > 0", name="metadata_schema_not_blank"
        ),
        sa.CheckConstraint(
            "(actor_type IN ('system_worker', 'system_maintenance') AND actor_id IS NULL) "
            "OR (actor_type IN ('trader_user', 'admin_user') AND actor_id IS NOT NULL)",
            name="human_actor_is_identified",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
    )
    op.create_index(
        "idx_audit_entity_time", "audit_logs", ["entity_type", "entity_id", "occurred_at"]
    )
    op.create_index(
        "idx_audit_actor_time", "audit_logs", ["actor_type", "actor_id", "occurred_at"]
    )
    op.create_index("idx_audit_action_time", "audit_logs", ["action", "occurred_at"])
    op.create_index("idx_audit_occurred_at", "audit_logs", ["occurred_at"])
    op.create_index("idx_audit_request_id", "audit_logs", ["request_id"])
    op.create_index("idx_audit_correlation_id", "audit_logs", ["correlation_id"])
    op.create_index(
        "idx_audit_security_events",
        "audit_logs",
        ["occurred_at"],
        postgresql_where=sa.text("action LIKE 'security.%'"),
    )
    op.create_index(
        "uq_audit_logs_sequence_number", "audit_logs", ["sequence_number"], unique=True
    )


def _create_outbox_events() -> None:
    op.create_table(
        "outbox_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("aggregate_type", sa.String(length=80), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aggregate_version", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_version", sa.Integer(), nullable=False),
        sa.Column(
            "headers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("causation_id", sa.String(length=64), nullable=True),
        sa.Column(
            "status", sa.String(length=24), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=120), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(f"status IN ({OUTBOX_STATUSES_SQL})", name="status"),
        sa.CheckConstraint(
            "attempt_count >= 0", name="attempt_count_not_negative"
        ),
        sa.CheckConstraint(
            "aggregate_version > 0", name="aggregate_version_positive"
        ),
        sa.CheckConstraint(
            "payload_version > 0", name="payload_version_positive"
        ),
        sa.CheckConstraint(
            "(status = 'published' AND published_at IS NOT NULL) "
            "OR (status <> 'published' AND published_at IS NULL)",
            name="published_at_matches_status",
        ),
        sa.CheckConstraint(
            "(locked_at IS NULL AND locked_by IS NULL) "
            "OR (locked_at IS NOT NULL AND locked_by IS NOT NULL)",
            name="lock_fields_move_together",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
    )
    op.create_index(
        "idx_outbox_dispatch",
        "outbox_events",
        ["available_at", "created_at"],
        postgresql_where=sa.text(f"status IN ({OUTBOX_CLAIMABLE_SQL})"),
    )
    op.create_index(
        "idx_outbox_aggregate",
        "outbox_events",
        ["aggregate_type", "aggregate_id", "aggregate_version"],
    )
    op.create_index("idx_outbox_correlation_id", "outbox_events", ["correlation_id"])


def _create_idempotency_records() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"actor_type IN ({ACTOR_TYPES_SQL})", name="actor_type"
        ),
        sa.CheckConstraint(
            "length(request_hash) = 64", name="request_hash_length"
        ),
        sa.CheckConstraint(
            "request_hash = lower(request_hash)",
            name="request_hash_lowercase",
        ),
        sa.CheckConstraint(
            "length(btrim(idempotency_key)) > 0",
            name="idempotency_key_not_blank",
        ),
        sa.CheckConstraint(
            "response_code IS NULL OR response_code BETWEEN 100 AND 599",
            name="response_code_range",
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name="expires_after_creation"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_idempotency_records"),
        # Four columns, not a global key: one caller's key must never collide with
        # another's, or the second caller receives the first caller's response.
        sa.UniqueConstraint(
            "actor_type",
            "actor_id",
            "operation",
            "idempotency_key",
            name="uq_idempotency_records_actor_operation_key",
        ),
    )
    op.create_index("idx_idempotency_expiry", "idempotency_records", ["expires_at"])


# Measured, not assumed: `infra/postgres/bootstrap/020-runtime-roles.sql` issues
# ALTER DEFAULT PRIVILEGES FOR ROLE <migrator> IN SCHEMA public GRANT SELECT,
# INSERT, UPDATE, DELETE ON TABLES TO <app>. Every table this revision creates
# therefore arrives with UPDATE and DELETE already granted to the runtime role —
# including audit_logs, which is append-only evidence.
#
# ADR-005 is open, and the governed retention and legal-hold procedures that
# would justify a mutation path do not exist, so no append-only UPDATE or DELETE
# may be granted at all. Waiting for the role slice would mean shipping a period
# in which audit rows are editable by the process that writes them, which is the
# one property the table exists to deny.
#
# Revoking by discovered grantee rather than by a hardcoded role name, because
# the runtime role is named by deployment configuration and this revision has no
# access to it. Grants made *after* this runs are not covered; the durable
# role-level answer belongs to the roles slice, and this is the part that must
# not wait for it.
REVOKE_APPEND_ONLY_MUTATION = """
DO $$
DECLARE
    target text;
BEGIN
    FOR target IN
        SELECT DISTINCT grantee
        FROM information_schema.role_table_grants
        WHERE table_schema = 'public'
          AND table_name = 'audit_logs'
          AND privilege_type IN ('UPDATE', 'DELETE')
          AND grantee <> current_user
    LOOP
        IF target = 'PUBLIC' THEN
            EXECUTE 'REVOKE UPDATE, DELETE ON public.audit_logs FROM PUBLIC';
        ELSE
            EXECUTE format('REVOKE UPDATE, DELETE ON public.audit_logs FROM %I', target);
        END IF;
    END LOOP;
END
$$;
"""


def upgrade() -> None:
    _create_audit_logs()
    _create_outbox_events()
    _create_idempotency_records()
    # Deliberately not applied to outbox_events or idempotency_records: a
    # dispatcher must move an event through its lifecycle, and an idempotency
    # record must be completed. Only the audit table is append-only.
    op.execute(REVOKE_APPEND_ONLY_MUTATION)


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_table("outbox_events")
    op.drop_table("audit_logs")
