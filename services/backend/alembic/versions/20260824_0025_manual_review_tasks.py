"""Work that needs a person. `04_Database_Schema.md` §13.1.

M8 slice 3, and this table closes something M7 recorded wrongly.

**M7's G-10 said "there is no task table in Phase 1A".** §13.1 at `:1314` specifies
`manual_review_tasks` with a field list and two indexes and carries no later-phase marker, and
`05_API_Specification.md:2058` gives it six routes. The table was never a design gap — it was
unbuilt work, and M7 used its absence to excuse not creating a task when a bank export is
quarantined. That excuse expires here, and slice 3 removes the `RECORDED_GAPS` entry in the same
commit it becomes buildable.

**`entity_type`/`entity_id` are a generic reference and §13.1 says what they may be used for:**
"Use generic entity references only for queue navigation. Financial relationship truth remains in
explicit tables." So there is no foreign key on them — deliberately, because a generic pointer
cannot have one — and no financial read may join through them. `SVC-TASK-002` asserts the second
half over the query surface; the first half is visible here as the absence of a constraint that
could not exist anyway.

**No `bank_excel_export_id` column, and that is the same rule applied to this slice's own need.**
M7's quarantine path creates a task naming the export through `entity_type='bank_excel_export'`. A
typed column would be more comfortable and would be exactly the "financial relationship truth" §13.1
puts elsewhere: whether an export is quarantined is `bank_excel_exports.status`, and a task is a
note that somebody should look.

**The partial index is the queue.** §13.1 gives it verbatim, covering `open` and `in_progress` — the
two states where work is outstanding — ordered by priority descending then age, which is the order a
person works in. `resolved` and `cancelled` are outside it, so a queue read never touches finished
work.

Revision ID: 20260824_0025
Revises: 20260824_0024
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0025"
down_revision: str | Sequence[str] | None = "20260824_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `status_catalog.yaml`'s `manual_review_task` aggregate, all four, in its order. No unresolved
# aliases on this one — the only aggregate in M8 whose states the catalogue settles completely.
TASK_STATUSES = ("open", "in_progress", "resolved", "cancelled")

# The two the partial index covers: work that is outstanding.
OPEN_STATUSES = ("open", "in_progress")

# What kind of attention the task needs. Not a lifecycle and not a priority — the *reason* a person
# is being asked to look, which is what lets a queue be filtered by skill rather than only by age.
TASK_TYPES = (
    "bank_export_integrity",
    "bundle_unresolved_segment",
    "segment_privacy_review",
    "payment_result_discrepancy",
)

# How a task ended. `05_API_Specification.md:2065` requires an explicit disposition when the
# underlying item is still unresolved, which is what `unresolved_with_reason` is for: closing the
# task without pretending the thing it was about is fixed.
RESOLUTION_CODES = (
    "corrected",
    "regenerated",
    "no_action_required",
    "unresolved_with_reason",
    "duplicate",
)

# The entity kinds a task may point at. Enumerated rather than free text: a generic reference whose
# type is unconstrained is one nothing can navigate, and `SVC-TASK-002` needs the set to be
# checkable. Each is a table that exists.
ENTITY_TYPES = ("bank_excel_export", "bank_result_bundle", "receipt_segment", "payment_attempt")

GRANTED_COLUMNS = (
    "status",
    "priority",
    "assigned_to_admin_user_id",
    "due_at",
    "resolved_by_admin_user_id",
    "resolved_at",
    "resolution_code",
    "resolution_note",
    "record_version",
    "updated_at",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _runtime_roles() -> tuple[str, ...]:
    from app.core.config import load_settings

    settings = load_settings()
    configured = {
        "APP_DB_ROLE": settings.app_db_role,
        "WORKER_DB_ROLE": settings.worker_db_role,
    }
    missing = sorted(name for name, value in configured.items() if not value)
    if missing:
        raise RuntimeError(
            f"Migration {revision} grants on mutable columns and these roles are "
            f"not set: {', '.join(missing)}."
        )
    return tuple(str(value) for value in configured.values())


def upgrade() -> None:
    op.create_table(
        "manual_review_tasks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("task_type", sa.String(64), nullable=False),
        # An integer, so the index can order by it. §13.1 names the column and not its range;
        # 1..5 is chosen here and constrained, because an unbounded priority is one every caller
        # inflates.
        sa.Column("priority", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        # The generic reference. No foreign key: a pointer that can name four tables cannot have
        # one, which is precisely why §13.1 limits it to navigation.
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "assigned_to_admin_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", name="fk_review_tasks_assignee"),
            nullable=True,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolved_by_admin_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", name="fk_review_tasks_resolved_by"),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_code", sa.String(64), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("record_version", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(f"status IN ({_quoted(TASK_STATUSES)})", name="status_value"),
        sa.CheckConstraint(f"task_type IN ({_quoted(TASK_TYPES)})", name="task_type_value"),
        sa.CheckConstraint(f"entity_type IN ({_quoted(ENTITY_TYPES)})", name="entity_type_value"),
        sa.CheckConstraint("priority BETWEEN 1 AND 5", name="priority_in_range"),
        sa.CheckConstraint(
            f"resolution_code IS NULL OR resolution_code IN ({_quoted(RESOLUTION_CODES)})",
            name="resolution_code_value",
        ),
        # A resolved task has all three resolution facts and nothing else has any of them. The
        # separation shape M7 slice 1 used for `batch_approvals` and slice 1 of this milestone used
        # for a closed bundle: a terminal status carries its terminal evidence, and a task that is
        # still open cannot be holding a resolution.
        #
        # `05_API_Specification.md:2065`: the API "cannot resolve a task without an explicit
        # disposition/reason". The code is that disposition, and requiring it here means no command
        # can forget.
        sa.CheckConstraint(
            "(status = 'resolved' AND resolved_at IS NOT NULL"
            " AND resolved_by_admin_user_id IS NOT NULL AND resolution_code IS NOT NULL)"
            " OR "
            "(status <> 'resolved' AND resolved_at IS NULL"
            " AND resolved_by_admin_user_id IS NULL AND resolution_code IS NULL)",
            name="resolved_requires_a_disposition",
        ),
        # `unresolved_with_reason` is the code for closing a task whose subject is still not fixed,
        # so it is the one that must carry prose. Without this the honest option would be the
        # cheapest one, and the queue would fill with resolutions that explain nothing.
        sa.CheckConstraint(
            "resolution_code <> 'unresolved_with_reason'"
            " OR (resolution_note IS NOT NULL AND length(btrim(resolution_note)) > 0)",
            name="unresolved_requires_a_reason",
        ),
        # `in_progress` means somebody is doing it, so somebody has to be named.
        sa.CheckConstraint(
            "status <> 'in_progress' OR assigned_to_admin_user_id IS NOT NULL",
            name="in_progress_requires_an_assignee",
        ),
    )

    # §13.1's two indexes, verbatim at `:1317-1321`.
    op.create_index(
        "idx_manual_review_open_queue",
        "manual_review_tasks",
        ["status", sa.text("priority DESC"), "created_at"],
        postgresql_where=sa.text(f"status IN ({_quoted(OPEN_STATUSES)})"),
    )
    op.create_index(
        "idx_manual_review_assignee",
        "manual_review_tasks",
        ["assigned_to_admin_user_id", "status", "created_at"],
    )
    # Not in §13.1. One open task per (entity, type), so a path that runs twice — a re-download
    # revalidating and quarantining again — does not put two identical items in front of a person.
    # Partial, so a resolved task never blocks a genuinely new one about the same thing.
    op.create_index(
        "uq_review_task_open_per_entity",
        "manual_review_tasks",
        ["entity_type", "entity_id", "task_type"],
        unique=True,
        postgresql_where=sa.text(f"status IN ({_quoted(OPEN_STATUSES)})"),
    )

    bind = op.get_bind()
    columns = ", ".join(GRANTED_COLUMNS)
    for role in _runtime_roles():
        bind.execute(
            sa.text(f'GRANT UPDATE ({columns}) ON public."manual_review_tasks" TO "{role}"')
        )


def downgrade() -> None:
    op.drop_index("uq_review_task_open_per_entity", table_name="manual_review_tasks")
    op.drop_index("idx_manual_review_assignee", table_name="manual_review_tasks")
    op.drop_index("idx_manual_review_open_queue", table_name="manual_review_tasks")
    op.drop_table("manual_review_tasks")
