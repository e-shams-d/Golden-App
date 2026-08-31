"""A message to a person, projected from an outbox event. `04_Database_Schema.md` §13.3.

M9 slice 7. **Never workflow truth**, which is the sentence §13.3 ends on and
`audit_outbox_catalog.yaml` repeats as a flag: `notifications_are_workflow_truth: false`.

That is not a caveat, it is the design. Nothing in this system may read a notification to decide
anything, so a notification that fails to be created, or is created twice, or is never read, cannot
change what a bank did or what a trader is owed. `OPS-NOTIFY-001` is the test that says so — the
projection is made to fail and the financial rows are read back unchanged.

**The dedup key is the outbox event id**, which is what `audit_outbox_catalog.yaml` names as the
consumer deduplication key. Delivery is at-least-once because a broker and a database cannot commit
together; the partial unique index is what turns "this event arrived twice" from a duplicate
message to a customer into a no-op.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, named_check, uuid_primary_key

# `status_catalog.yaml`'s `notification` aggregate. Only `unread` is written in this slice; the
# other two belong to a recipient's own action, which has no route yet.
NOTIFICATION_STATUSES: tuple[str, ...] = ("unread", "read", "dismissed")

NOTIFICATION_UNREAD = "unread"

# One value per outbox event this projection consumes. Enumerated for the reason M8 gave for
# `manual_review_tasks.entity_type`: a type nothing can navigate is worse than no type.
NOTIFICATION_TYPES: tuple[str, ...] = (
    "payment_result_published",
    "payment_result_corrected",
    # G-5. `PaymentAttemptFailed` has been enqueued since M9 slice 3 with no consumer, and the
    # plan's decision that a failure is *told* rather than published is only honest if something
    # reads it. This is that something.
    "payment_attempt_failed",
)

TYPE_RESULT_PUBLISHED = "payment_result_published"
TYPE_RESULT_CORRECTED = "payment_result_corrected"
TYPE_ATTEMPT_FAILED = "payment_attempt_failed"

ENTITY_TYPES: tuple[str, ...] = ("payment_request", "payment_result_publication")

ENTITY_PAYMENT_REQUEST = "payment_request"
ENTITY_PAYMENT_PUBLICATION = "payment_result_publication"

# `audit_log.ACTOR_TYPES`' two human values. `system_worker` has nobody to read a message.
RECIPIENT_ACTOR_TYPES: tuple[str, ...] = ("trader_user", "admin_user")

RECIPIENT_TRADER_USER = "trader_user"


class Notification(Base):
    """One message. §13.3."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    recipient_actor_type: Mapped[str] = mapped_column(String(24), nullable=False)
    # No foreign key: the recipient may be a trader user or an admin user, and a column that
    # references both references neither. The projection resolves a real row before writing.
    recipient_actor_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=False
    )

    notification_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)

    status: Mapped[str] = mapped_column(String(24), nullable=False)

    deduplication_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        named_check(
            "status IN (" + ", ".join(f"'{v}'" for v in NOTIFICATION_STATUSES) + ")",
            name="status_value",
        ),
        named_check(
            "notification_type IN (" + ", ".join(f"'{v}'" for v in NOTIFICATION_TYPES) + ")",
            name="notification_type_value",
        ),
        named_check(
            "entity_type IN (" + ", ".join(f"'{v}'" for v in ENTITY_TYPES) + ")",
            name="entity_type_value",
        ),
        named_check(
            "recipient_actor_type IN ("
            + ", ".join(f"'{v}'" for v in RECIPIENT_ACTOR_TYPES)
            + ")",
            name="recipient_actor_type_value",
        ),
        named_check(
            "(status = 'unread' AND read_at IS NULL) OR (status <> 'unread')",
            name="unread_has_no_read_time",
        ),
        # §13.3 at `:1339`, verbatim.
        Index(
            "uq_notification_dedup",
            "recipient_actor_type",
            "recipient_actor_id",
            "deduplication_key",
            unique=True,
            postgresql_where="deduplication_key IS NOT NULL",
        ),
        Index(
            "idx_notifications_recipient",
            "recipient_actor_type",
            "recipient_actor_id",
            "created_at",
        ),
    )
