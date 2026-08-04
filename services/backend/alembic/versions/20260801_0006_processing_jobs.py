"""Create processing_jobs, with the claim and reclaim indexes it cannot run without.

Celery's queue is transport. It knows a message was delivered; it does not know
whether the work succeeded, how many times it has been attempted, or what it
produced. This table is the authoritative record, so losing Redis loses the
wake-up and not the truth.

Two indexes here appear in no document. The claim path filters on exactly
`(queue_name, status, available_at)` on every poll, and the reclaim path scans
`heartbeat_at` to find rows whose claimant died. Adding either afterwards means
building an index on a live queue while workers hold rows in it.

The status CHECK is written because `processing_job` is an approved aggregate
with eight canonical values in `status_catalog.yaml`. Its neighbour
`idempotency_records` deliberately has none, and the difference is governance
rather than inconsistency.

CHECK constraints carry bare names: `op.create_table` applies the metadata naming
convention, so a full `ck_processing_jobs_...` here would be doubled.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260801_0006"
down_revision: str | None = "20260801_0005"
branch_labels: str | None = None
depends_on: str | None = None

STATUSES_SQL = (
    "'queued', 'running', 'succeeded', 'failed', 'retry_scheduled', "
    "'cancelled', 'dead_lettered', 'fallback_to_manual'"
)
TERMINAL_SQL = "'succeeded', 'cancelled', 'dead_lettered', 'fallback_to_manual'"
CLAIMABLE_SQL = "'queued', 'retry_scheduled', 'running'"

# The table is mutable: a worker moves a job through its lifecycle. Granted here
# because the provisioning default is fail-closed from 20260801_0005 onward.
MUTABLE_GRANT = 'GRANT UPDATE, DELETE ON public."processing_jobs" TO "{role}"'


def _runtime_roles() -> tuple[str, ...]:
    from app.core.config import load_settings

    settings = load_settings()
    configured = {
        "APP_DB_ROLE (or APP_DB_USER)": settings.app_db_role,
        "WORKER_DB_ROLE (or WORKER_DB_USER)": settings.worker_db_role,
    }
    missing = sorted(name for name, value in configured.items() if not value)
    if missing:
        raise RuntimeError(
            f"Migration {revision} grants on a mutable table and these roles are "
            f"not set: {', '.join(missing)}."
        )
    return tuple(value for value in configured.values() if value)


def upgrade() -> None:
    op.create_table(
        "processing_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("job_type", sa.String(length=120), nullable=False),
        sa.Column("queue_name", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default=sa.text("'queued'"), nullable=False
        ),
        sa.Column("input_entity_type", sa.String(length=80), nullable=True),
        sa.Column("input_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("provider_version", sa.String(length=40), nullable=True),
        sa.Column(
            "input_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("output_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=120), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("record_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(f"status IN ({STATUSES_SQL})", name="status"),
        sa.CheckConstraint("attempt_count >= 0", name="attempt_count_not_negative"),
        sa.CheckConstraint("max_attempts >= 1", name="max_attempts_positive"),
        sa.CheckConstraint("attempt_count <= max_attempts", name="attempts_within_maximum"),
        sa.CheckConstraint(
            f"(status IN ({TERMINAL_SQL}) AND finished_at IS NOT NULL) "
            f"OR (status NOT IN ({TERMINAL_SQL}) AND finished_at IS NULL)",
            name="finished_at_matches_status",
        ),
        sa.CheckConstraint(
            "(locked_by IS NULL AND heartbeat_at IS NULL) "
            "OR (locked_by IS NOT NULL AND heartbeat_at IS NOT NULL)",
            name="lease_fields_move_together",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_processing_jobs"),
    )

    op.create_index(
        "uq_processing_jobs_type_idempotency_key",
        "processing_jobs",
        ["job_type", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "idx_processing_jobs_claim",
        "processing_jobs",
        ["queue_name", "status", "available_at"],
        postgresql_where=sa.text(f"status IN ({CLAIMABLE_SQL})"),
    )
    op.create_index(
        "idx_processing_jobs_stale_lease",
        "processing_jobs",
        ["heartbeat_at"],
        postgresql_where=sa.text("heartbeat_at IS NOT NULL"),
    )
    op.create_index(
        "idx_processing_jobs_input_entity",
        "processing_jobs",
        ["input_entity_type", "input_entity_id"],
    )

    bind = op.get_bind()
    for role in _runtime_roles():
        bind.execute(sa.text(MUTABLE_GRANT.format(role=role)))


def downgrade() -> None:
    op.drop_table("processing_jobs")
