"""Telling a trader something happened. `04_Database_Schema.md` §13.3.

M9 slice 7. The only table M9 needs that no earlier milestone built, and the plan's G-2.

**This is the consumer M2 said did not exist.** `app/workers/tasks/maintenance.py` has carried the
sentence since the outbox was built: "Delivery is a no-op for now: nothing consumes these events in
Phase 1A, and a dispatcher that invented a destination would publish somewhere no consumer agreed
to." That was the right call then and it is what this revision ends — the destination is a table
document 04 specifies, not one this milestone invented.

**Notifications are a projection, never truth.** §13.3: "Notifications are produced from outbox
events. They are not the source of workflow truth", and `audit_outbox_catalog.yaml` says the same
as a flag: `notifications_are_workflow_truth: false`. Nothing in this system may read a
notification to decide anything, and `OPS-NOTIFY-001` asserts that a notification failing leaves
committed financial state exactly as it was.

**The dedup index is the at-least-once contract made physical.** `04_Database_Schema.md:1339`
gives it verbatim, and `audit_outbox_catalog.yaml` names the key: `outbox_event_id`. Delivery is
at-least-once because a broker and a database cannot commit together, so the same event *will*
sometimes be handled twice — and the partial unique is what makes the second one harmless rather
than a duplicate message to a customer.

**No UPDATE grant.** `status` moves from `unread` when a recipient reads or dismisses, and nothing
in this slice does either: there is no read-marking route and ADR-009 has not settled a delivery
channel. Same reasoning as `20260831_0031` — a grant issued ahead of the command that needs it is a
capability with no caller. The CHECK still admits all three catalogued states, because
`status_catalog.yaml` names them and `test_status_catalogue_drift.py` holds every CHECK to its
aggregate exactly.

Revision ID: 20260902_0033
Revises: 20260901_0032
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260902_0033"
down_revision: str | Sequence[str] | None = "20260901_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `status_catalog.yaml`'s `notification` aggregate, all three. Only `unread` is written today; the
# other two are what the catalogue approves for a recipient's own action, and the drift gate
# requires the CHECK to match the aggregate exactly rather than only what this slice uses.
NOTIFICATION_STATUSES = ("unread", "read", "dismissed")

# What a notification is about. No catalogue enumerates these — §13.3 gives the column and no
# values — so the list is this implementation's, chosen by the same rule M8 used for
# `manual_review_tasks.entity_type`: a type nothing can navigate is worse than no type. Each one
# corresponds to exactly one outbox event, which is what keeps the mapping checkable.
NOTIFICATION_TYPES = (
    "payment_result_published",
    "payment_result_corrected",
    "payment_attempt_failed",
)

# The `entity_type` a notification points at, for the same reason. Both values are tables.
ENTITY_TYPES = ("payment_request", "payment_result_publication")

# `audit_log.ACTOR_TYPES`' two human values. A notification is delivered to a person, and
# `system_worker` has nobody to read it.
RECIPIENT_ACTOR_TYPES = ("trader_user", "admin_user")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("recipient_actor_type", sa.String(24), nullable=False),
        # **No foreign key**, deliberately, and for §13.1's reason one table along: the recipient
        # may be a trader user or an admin user, and a column that references both references
        # neither. The projection resolves the id from a real row before writing.
        sa.Column("recipient_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        # Nullable because §13.3's index is partial on exactly this. A notification raised by
        # something other than an outbox event would have no natural key, and the index says so
        # rather than forcing one to be invented.
        sa.Column("deduplication_key", sa.String(128), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            f"status IN ({_quoted(NOTIFICATION_STATUSES)})", name="status_value"
        ),
        sa.CheckConstraint(
            f"notification_type IN ({_quoted(NOTIFICATION_TYPES)})",
            name="notification_type_value",
        ),
        sa.CheckConstraint(
            f"entity_type IN ({_quoted(ENTITY_TYPES)})", name="entity_type_value"
        ),
        sa.CheckConstraint(
            f"recipient_actor_type IN ({_quoted(RECIPIENT_ACTOR_TYPES)})",
            name="recipient_actor_type_value",
        ),
        # A read timestamp on an unread notification is a contradiction the database can decide.
        sa.CheckConstraint(
            "(status = 'unread' AND read_at IS NULL) OR (status <> 'unread')",
            name="unread_has_no_read_time",
        ),
    )

    # `04_Database_Schema.md:1339`, verbatim. The at-least-once contract made physical: the same
    # outbox event handled twice produces one message rather than two.
    op.create_index(
        "uq_notification_dedup",
        "notifications",
        ["recipient_actor_type", "recipient_actor_id", "deduplication_key"],
        unique=True,
        postgresql_where=sa.text("deduplication_key IS NOT NULL"),
    )

    # A recipient's own list, newest first. The only query this table has.
    op.create_index(
        "idx_notifications_recipient",
        "notifications",
        ["recipient_actor_type", "recipient_actor_id", "created_at"],
    )

    # No GRANT. See the module docstring: nothing marks a notification read yet, and a grant
    # ahead of the command that needs it is a capability with no caller.


def downgrade() -> None:
    op.drop_index("idx_notifications_recipient", table_name="notifications")
    op.drop_index("uq_notification_dedup", table_name="notifications")
    op.drop_table("notifications")
