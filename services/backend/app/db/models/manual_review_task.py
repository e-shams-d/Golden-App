"""Work that needs a person. `04_Database_Schema.md` §13.1.

M8 slice 3. The queue M7 said did not exist.

**`entity_type`/`entity_id` navigate; they do not relate.** §13.1 at `:1324`: "Use generic entity
references only for queue navigation. Financial relationship truth remains in explicit tables."
There is no foreign key on the pair — a pointer that can name four tables cannot have one — and no
financial read joins through it. That is why there is also no `bank_excel_export_id` column even
though slice 3's own quarantine path would find one convenient: whether an export is quarantined is
`bank_excel_exports.status`, and this row is a note that somebody should look at it.

**A resolved task carries its disposition, enforced by the table.**
`05_API_Specification.md:2065` says the API "cannot resolve a task without an explicit
disposition/reason". A rule in a command is one a second command can forget, so the CHECK is where
it lives — the shape M7 slice 1 established for `batch_approvals` and slice 1 of this milestone used
for a closed bundle.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, named_check, uuid_primary_key

# `status_catalog.yaml`'s `manual_review_task` aggregate, all four, in its order. The only M8
# aggregate the catalogue settles completely — no unresolved aliases at all.
TASK_STATUSES: tuple[str, ...] = ("open", "in_progress", "resolved", "cancelled")

TASK_OPEN = "open"
TASK_IN_PROGRESS = "in_progress"
TASK_RESOLVED = "resolved"
TASK_CANCELLED = "cancelled"

# Where work is outstanding. The partial index's predicate, and what `close_bundle`-style checks
# mean by "still needs a person".
OPEN_STATUSES: tuple[str, ...] = (TASK_OPEN, TASK_IN_PROGRESS)

# Why a person is being asked to look. Not a priority and not a lifecycle — the kind of attention
# needed, which is what lets a queue be filtered by skill rather than only by age.
TASK_TYPES: tuple[str, ...] = (
    "bank_export_integrity",
    "bundle_unresolved_segment",
    "segment_privacy_review",
    "payment_result_discrepancy",
)

TASK_TYPE_EXPORT_INTEGRITY = "bank_export_integrity"
# M8 slice 4. Naming a value the tuple above already holds rather than adding one. A crop that
# cannot be rendered leaves a segment in a bundle with no file, which is precisely what
# `bundle_unresolved_segment` describes — and it is the accurate type as well as the permitted one,
# because what a person is left to deal with is an unresolved segment whatever made the render fail.
# A `crop_failed` type would have been an invention, and the column's CHECK would have refused it.
TASK_TYPE_UNRESOLVED_SEGMENT = "bundle_unresolved_segment"

# How a task ended. `unresolved_with_reason` is the honest close for a task whose subject is still
# not fixed, and the table requires it to carry prose — otherwise the honest option would also be
# the cheapest one.
RESOLUTION_CODES: tuple[str, ...] = (
    "corrected",
    "regenerated",
    "no_action_required",
    "unresolved_with_reason",
    "duplicate",
)

RESOLUTION_UNRESOLVED = "unresolved_with_reason"

# The entity kinds a task may point at. Enumerated rather than free text: a generic reference whose
# type is unconstrained is one nothing can navigate, and each of these is a table that exists.
ENTITY_TYPES: tuple[str, ...] = (
    "bank_excel_export",
    "bank_result_bundle",
    "receipt_segment",
    "payment_attempt",
)

ENTITY_BANK_EXPORT = "bank_excel_export"
ENTITY_RECEIPT_SEGMENT = "receipt_segment"


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class ManualReviewTask(Base):
    """One item of work in front of one person. §13.1."""

    __tablename__ = "manual_review_tasks"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # An integer so the queue index can order by it. §13.1 names the column and not its range;
    # 1..5 is chosen here and constrained, because an unbounded priority is one every caller
    # inflates until the ordering means nothing.
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    # The generic reference. No foreign key, by design and by necessity.
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)

    assigned_to_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_review_tasks_assignee"),
        nullable=True,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    resolved_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_review_tasks_resolved_by"),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text(), nullable=True)

    record_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        named_check(f"status IN ({_quoted(TASK_STATUSES)})", name="status_value"),
        named_check(f"task_type IN ({_quoted(TASK_TYPES)})", name="task_type_value"),
        named_check(f"entity_type IN ({_quoted(ENTITY_TYPES)})", name="entity_type_value"),
        named_check("priority BETWEEN 1 AND 5", name="priority_in_range"),
        named_check(
            f"resolution_code IS NULL OR resolution_code IN ({_quoted(RESOLUTION_CODES)})",
            name="resolution_code_value",
        ),
        # A resolved task has all three resolution facts; nothing else has any of them.
        # `05_API_Specification.md:2065` requires an explicit disposition, and a CHECK is where a
        # requirement lives when two commands could otherwise forget it differently.
        named_check(
            "(status = 'resolved' AND resolved_at IS NOT NULL"
            " AND resolved_by_admin_user_id IS NOT NULL AND resolution_code IS NOT NULL)"
            " OR "
            "(status <> 'resolved' AND resolved_at IS NULL"
            " AND resolved_by_admin_user_id IS NULL AND resolution_code IS NULL)",
            name="resolved_requires_a_disposition",
        ),
        named_check(
            "resolution_code <> 'unresolved_with_reason'"
            " OR (resolution_note IS NOT NULL AND length(btrim(resolution_note)) > 0)",
            name="unresolved_requires_a_reason",
        ),
        named_check(
            "status <> 'in_progress' OR assigned_to_admin_user_id IS NOT NULL",
            name="in_progress_requires_an_assignee",
        ),
        # §13.1's two indexes at `:1317-1321`, verbatim.
        Index(
            "idx_manual_review_open_queue",
            "status",
            text("priority DESC"),
            "created_at",
            postgresql_where=f"status IN ({_quoted(OPEN_STATUSES)})",
        ),
        Index(
            "idx_manual_review_assignee",
            "assigned_to_admin_user_id",
            "status",
            "created_at",
        ),
        # Not in §13.1. One open task per (entity, type), so a path that runs twice does not put
        # two identical items in front of a person. Partial, so a resolved task never blocks a
        # genuinely new one about the same thing.
        Index(
            "uq_review_task_open_per_entity",
            "entity_type",
            "entity_id",
            "task_type",
            unique=True,
            postgresql_where=f"status IN ({_quoted(OPEN_STATUSES)})",
        ),
    )
