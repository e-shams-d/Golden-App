"""The four things that happen to a task, and the one that creates it.
`05_API_Specification.md` §22.1.

M8 slice 3.

**Four transitions and no others.** `open → in_progress → resolved`, and `cancelled` from either
open state. Not from `resolved`: a resolved task is a record of a decision, and un-resolving one
would erase the disposition `:2065` requires it to carry. There is no reopen — a thing that needs
looking at again is a new task, which is also what keeps the "one open task per entity" index
meaningful.

**`open_task` is idempotent on the queue, not on a key.** `uq_review_task_open_per_entity` permits
one open task per (entity, type), so a path that runs twice — a re-download revalidating and
quarantining an export again — finds the existing task instead of adding a second identical item in
front of a person. That is why it returns the existing row rather than raising: the caller is a
failure path, and a failure path that raises because it already reported the failure is worse than
one that says nothing new.

**Every transition takes `If-Match`.** `:2065`: "Assignment/start/resolve/cancel require
`If-Match`". Two people working one queue is the normal case, not the edge case.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import (
    ASSIGN_REVIEW_TASK,
    CANCEL_REVIEW_TASK,
    OPEN_REVIEW_TASK,
    RESOLVE_REVIEW_TASK,
    START_REVIEW_TASK,
)
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.core.errors import BusinessRuleViolationError, ConflictError, NotFoundError
from app.db.models.identity import AdminUser
from app.db.models.manual_review_task import (
    OPEN_STATUSES,
    RESOLUTION_UNRESOLVED,
    TASK_CANCELLED,
    TASK_IN_PROGRESS,
    TASK_OPEN,
    TASK_RESOLVED,
    ManualReviewTask,
)
from app.db.unit_of_work import SqlAlchemyUnitOfWork

METADATA_SCHEMA = "audit.manual_review_task"
METADATA_VERSION = 1

# The transitions this module permits, as (from, to). Written as data so
# `SVC-TASK-001` can assert the set rather than trusting four separate functions to
# agree about what they refuse.
PERMITTED_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        (TASK_OPEN, TASK_IN_PROGRESS),
        (TASK_OPEN, TASK_RESOLVED),
        (TASK_IN_PROGRESS, TASK_RESOLVED),
        (TASK_OPEN, TASK_CANCELLED),
        (TASK_IN_PROGRESS, TASK_CANCELLED),
    }
)


@dataclass(frozen=True, slots=True)
class OpenTask:
    task_type: str
    entity_type: str
    entity_id: uuid.UUID
    title: str
    priority: int
    description: str | None = None
    due_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AssignTask:
    manual_review_task_id: uuid.UUID
    assignee_admin_user_id: uuid.UUID
    expected_record_version: int


@dataclass(frozen=True, slots=True)
class StartTask:
    manual_review_task_id: uuid.UUID
    expected_record_version: int


@dataclass(frozen=True, slots=True)
class ResolveTask:
    manual_review_task_id: uuid.UUID
    resolution_code: str
    expected_record_version: int
    resolution_note: str | None = None


@dataclass(frozen=True, slots=True)
class CancelTask:
    manual_review_task_id: uuid.UUID
    reason: str
    expected_record_version: int


def open_task(
    command: OpenTask,
    *,
    session: Session,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> ManualReviewTask:
    """Create a task, or return the open one that already covers this.

    **Takes a `Session` rather than a unit of work**, because its first caller is M7's quarantine
    path, which is already inside one and commits deliberately on a failure path. A function that
    opened its own transaction there would either nest or discard the quarantine it was reporting.
    """

    existing = session.scalar(
        select(ManualReviewTask).where(
            ManualReviewTask.entity_type == command.entity_type,
            ManualReviewTask.entity_id == command.entity_id,
            ManualReviewTask.task_type == command.task_type,
            ManualReviewTask.status.in_(OPEN_STATUSES),
        )
    )
    if existing is not None:
        # Already in front of somebody. Saying it twice does not make it more urgent.
        return existing

    task = ManualReviewTask(
        task_type=command.task_type,
        priority=command.priority,
        status=TASK_OPEN,
        entity_type=command.entity_type,
        entity_id=command.entity_id,
        assigned_to_admin_user_id=None,
        title=command.title,
        description=command.description,
        due_at=command.due_at,
        record_version=1,
        created_at=now,
        updated_at=now,
    )
    session.add(task)
    session.flush()

    AuditWriter(session, policy).record(
        AuditEntry(
            action=OPEN_REVIEW_TASK.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="manual_review_task",
            entity_id=task.id,
            entity_record_version=task.record_version,
            previous_values=None,
            new_values={
                "task_type": task.task_type,
                "status": task.status,
                "priority": task.priority,
                "subject_type": task.entity_type,
                "subject_id": str(task.entity_id),
            },
            reason=command.title,
            occurred_at=now,
            metadata={"operation": OPEN_REVIEW_TASK.audit_action},
        ),
        actor=actor,
        context=context,
    )
    return task


def assign(
    command: AssignTask,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> ManualReviewTask:
    """`POST /manual-review-tasks/{id}/assign`.

    Assignment does not change the status. A task can be assigned while `open` and picked up later,
    and `start` is the separate act of somebody saying they have begun — which is what makes
    `in_progress` mean "being worked on" rather than "allocated to a name".
    """

    session = uow.session
    task = _live(session, command.manual_review_task_id, command.expected_record_version)

    if task.status not in OPEN_STATUSES:
        raise BusinessRuleViolationError(
            f"task {task.id} is {task.status} and cannot be assigned; a finished task is a record"
        )

    assignee = session.get(AdminUser, command.assignee_admin_user_id)
    if assignee is None:
        raise NotFoundError()

    previous = task.assigned_to_admin_user_id
    task.assigned_to_admin_user_id = assignee.id
    _touch(task, now)

    _record(
        session,
        policy,
        task,
        action=ASSIGN_REVIEW_TASK.audit_action,
        previous={"assigned_to": str(previous) if previous else None},
        new={"assigned_to": assignee.username},
        reason="queue item assigned",
        actor=actor,
        context=context,
        now=now,
    )
    return task


def start(
    command: StartTask,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> ManualReviewTask:
    """`POST /manual-review-tasks/{id}/start`.

    **Starting assigns to the caller if nobody holds it.** `in_progress_requires_an_assignee` is a
    CHECK, so a start with no assignee would be refused by the database — and the useful behaviour
    is not to refuse but to record that the person who started it is the person doing it.
    """

    session = uow.session
    task = _live(session, command.manual_review_task_id, command.expected_record_version)
    _require_transition(task.status, TASK_IN_PROGRESS, task.id)

    if task.assigned_to_admin_user_id is None:
        task.assigned_to_admin_user_id = actor.actor_id

    previous = task.status
    task.status = TASK_IN_PROGRESS
    _touch(task, now)

    _record(
        session,
        policy,
        task,
        action=START_REVIEW_TASK.audit_action,
        previous={"status": previous},
        new={"status": task.status, "assigned_to": str(task.assigned_to_admin_user_id)},
        reason="work begun",
        actor=actor,
        context=context,
        now=now,
    )
    return task


def resolve(
    command: ResolveTask,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> ManualReviewTask:
    """`POST /manual-review-tasks/{id}/resolve`.

    **The disposition is required and the table enforces it too.**
    `05_API_Specification.md:2065`: the API "cannot resolve a task without an explicit
    disposition/reason when the underlying item remains unresolved". That code is
    case, and it is the one code that must carry prose — checked here so the message names the
    field, and checked again by `ck_manual_review_tasks_unresolved_requires_a_reason` so no second
    writer can forget.

    **Resolving does not touch the subject.** A task about a quarantined export does not free
    it: §13.1 keeps financial truth in explicit tables, and the export's status is one of them. What
    this records is that a person looked.
    """

    session = uow.session
    task = _live(session, command.manual_review_task_id, command.expected_record_version)
    _require_transition(task.status, TASK_RESOLVED, task.id)

    note = (command.resolution_note or "").strip()
    if command.resolution_code == RESOLUTION_UNRESOLVED and not note:
        raise BusinessRuleViolationError(
            "resolving a task as still unresolved requires a reason: this is the disposition that "
            "says the underlying item was not fixed, and without prose it says nothing"
        )

    previous = task.status
    task.status = TASK_RESOLVED
    task.resolved_at = now
    task.resolved_by_admin_user_id = actor.actor_id
    task.resolution_code = command.resolution_code
    task.resolution_note = note or None
    _touch(task, now)

    _record(
        session,
        policy,
        task,
        action=RESOLVE_REVIEW_TASK.audit_action,
        previous={"status": previous},
        new={"status": task.status, "resolution_code": task.resolution_code},
        reason=note or command.resolution_code,
        actor=actor,
        context=context,
        now=now,
    )
    return task


def cancel(
    command: CancelTask,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> ManualReviewTask:
    """`POST /manual-review-tasks/{id}/cancel`.

    Cancellation is for a task that should not have existed — a duplicate, or one whose subject
    turned out to be something else. It is **not** resolution: nothing was decided about the
    subject, which is why it writes no `resolution_code` and the CHECK refuses one.
    """

    session = uow.session
    task = _live(session, command.manual_review_task_id, command.expected_record_version)
    _require_transition(task.status, TASK_CANCELLED, task.id)

    if not command.reason.strip():
        raise BusinessRuleViolationError(
            "cancelling a task requires a reason; a queue item that vanishes without one is "
            "indistinguishable from work nobody did"
        )

    previous = task.status
    task.status = TASK_CANCELLED
    _touch(task, now)

    _record(
        session,
        policy,
        task,
        action=CANCEL_REVIEW_TASK.audit_action,
        previous={"status": previous},
        new={"status": task.status},
        reason=command.reason.strip(),
        actor=actor,
        context=context,
        now=now,
    )
    return task


def _live(session: Session, task_id: uuid.UUID, expected: int) -> ManualReviewTask:
    task = session.get(ManualReviewTask, task_id)
    if task is None:
        raise NotFoundError()
    if task.record_version != expected:
        raise ConflictError(
            f"task {task.id} is at version {task.record_version} and the caller expected "
            f"{expected}; somebody else in the queue moved it first"
        )
    return task


def _require_transition(current: str, target: str, task_id: uuid.UUID) -> None:
    """Refuse anything outside `PERMITTED_TRANSITIONS`, naming both ends.

    One place rather than four, so the four commands cannot disagree about what is allowed — and so
    `SVC-TASK-001` can assert the whole set from the data rather than by calling every combination.
    """

    if (current, target) not in PERMITTED_TRANSITIONS:
        raise BusinessRuleViolationError(
            f"task {task_id} cannot move from {current!r} to {target!r}. A resolved task is a "
            "record of a decision and is never reopened; something that needs looking at again is "
            "a new task."
        )


def _touch(task: ManualReviewTask, now: datetime) -> None:
    task.record_version += 1
    task.updated_at = now


def _record(
    session: Session,
    policy: RedactionPolicy,
    task: ManualReviewTask,
    *,
    action: str,
    previous: dict[str, object],
    new: dict[str, object],
    reason: str,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> None:
    AuditWriter(session, policy).record(
        AuditEntry(
            action=action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="manual_review_task",
            entity_id=task.id,
            entity_record_version=task.record_version,
            previous_values=previous,
            new_values=new,
            reason=reason,
            occurred_at=now,
            metadata={"operation": action},
        ),
        actor=actor,
        context=context,
    )
