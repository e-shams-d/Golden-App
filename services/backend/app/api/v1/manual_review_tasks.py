"""The review queue. `05_API_Specification.md` §22.1.

M8 slice 3. Six routes — the two reads and the four transitions document 05 defines.

**Three permissions cover six routes, and that is the catalogue's shape rather than a shortcut.**
`permission_catalog.yaml` approves `manual_review.read`, `.assign` and `.resolve`. There is no
`.start` and no `.cancel`, so `start` takes `.assign` — beginning work is the same authority as
deciding who does it — and `cancel` takes `.resolve`, because both end a queue item. Mapping them
this way rather than inventing two permissions follows the rule slice 1 and 2 followed: a permission
is a grant, grants are seeded and audited, and inventing one is not an implementer's decision.

**Every transition requires `If-Match`.** `:2065` says so, and a shared queue is where it earns its
keep: two people opening the same item is the normal case.

**`Idempotency-Key` on resolve and cancel only.** `:2065`: "sensitive resolution commands require
idempotency". Assign and start are safely repeatable — assigning to the same person twice is the
same state — and requiring a key for them would be ceremony rather than protection.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor, requires
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.commands import manual_review_task as task_commands
from app.core.errors import (
    BusinessRuleViolationError,
    ErrorEnvelope,
    NotFoundError,
    PreconditionRequiredError,
)
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.identity import AdminUser
from app.db.models.manual_review_task import (
    OPEN_STATUSES,
    RESOLUTION_CODES,
    ManualReviewTask,
)
from app.security.actor import ActorContext
from app.security.permissions import declare

router = APIRouter(prefix="/manual-review-tasks", tags=["manual-review-tasks"])

TASK_REDACTION = RedactionPolicy(mask_iban=True)

RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "The caller lacks the review permission."},
    404: {"model": ErrorEnvelope, "description": "No such task or assignee."},
    409: {
        "model": ErrorEnvelope,
        "description": "The task moved first, or the transition is not permitted.",
    },
    428: {"model": ErrorEnvelope, "description": "If-Match or Idempotency-Key is required."},
    **VALIDATION_ERROR_RESPONSE,
}


class AssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee_admin_user_id: uuid.UUID


class ResolveRequest(BaseModel):
    """`:2065`'s explicit disposition.

    `resolution_code` is required and constrained to the catalogue of codes: a free-text resolution
    is one nothing can group, and the whole value of a queue is being able to ask what happened to
    the items in it.
    """

    model_config = ConfigDict(extra="forbid")

    resolution_code: str = Field(min_length=1, max_length=64)
    resolution_note: str | None = Field(default=None, max_length=4000)


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=4000)


class TaskDetail(BaseModel):
    """One queue item.

    **`entity_type`/`entity_id` are returned for navigation and nothing else** — §13.1 at `:1324`.
    A screen uses them to open the subject; no read here joins through them, and
    `SVC-TASK-002` asserts that over the query surface.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    task_type: str
    priority: int
    status: str
    entity_type: str
    entity_id: uuid.UUID
    assigned_to: str | None
    title: str
    description: str | None
    due_at: datetime | None
    resolved_by: str | None
    resolved_at: datetime | None
    resolution_code: str | None
    resolution_note: str | None
    record_version: int
    created_at: datetime
    updated_at: datetime
    # The codes a caller may send, so a screen offers choices the server accepts rather than
    # keeping its own copy — the reason slice 1's bundle detail sends its three vocabularies.
    accepted_resolution_codes: list[str]


def _username(session: object, admin_user_id: uuid.UUID | None) -> str | None:
    if admin_user_id is None:
        return None
    found = session.get(AdminUser, admin_user_id)  # type: ignore[attr-defined]
    return found.username if found is not None else None


def _detail(session: object, task: ManualReviewTask) -> TaskDetail:
    return TaskDetail(
        id=task.id,
        task_type=task.task_type,
        priority=task.priority,
        status=task.status,
        entity_type=task.entity_type,
        entity_id=task.entity_id,
        assigned_to=_username(session, task.assigned_to_admin_user_id),
        title=task.title,
        description=task.description,
        due_at=task.due_at,
        resolved_by=_username(session, task.resolved_by_admin_user_id),
        resolved_at=task.resolved_at,
        resolution_code=task.resolution_code,
        resolution_note=task.resolution_note,
        record_version=task.record_version,
        created_at=task.created_at,
        updated_at=task.updated_at,
        accepted_resolution_codes=list(RESOLUTION_CODES),
    )


def _audit_actor(actor: ActorContext) -> AuditActor:
    return AuditActor(
        actor_type=actor.actor_type.value,
        actor_id=actor.actor_id,
        role_snapshot=tuple(sorted(actor.roles)),
        session_id=actor.session_id,
        authentication_assurance=actor.auth_level,
    )


def _if_match(header: str | None) -> int:
    """`rv-<n>` to an int, or a 428 naming what was missing.

    `:2065` requires `If-Match` on all four transitions. Parsed here rather than in the command so
    the command takes an integer and can be called from a test without inventing a header.
    """

    if header is None:
        raise PreconditionRequiredError("If-Match")
    token = header.strip().strip('"')
    if not token.startswith("rv-") or not token[3:].isdigit():
        raise BusinessRuleViolationError(
            f'If-Match must be of the form "rv-<n>"; received {header!r}'
        )
    return int(token[3:])


@router.get(
    "",
    response_model=list[TaskDetail],
    operation_id="listManualReviewTasks",
    summary="The open queue, in the order a person works it.",
    responses=RESPONSES,
    dependencies=[requires(declare("manual_review.read"))],
)
def list_manual_review_tasks(
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    open_only: Annotated[bool, Query()] = True,
    assigned_to_me: Annotated[bool, Query()] = False,
) -> list[TaskDetail]:
    """`GET /api/v1/manual-review-tasks`. `05_API_Specification.md:2058`.

    **The default ordering is the index's**: priority descending, then oldest first. §13.1 specifies
    that index and a query that ordered differently would either not use it or would present the
    queue in an order nobody chose.

    `open_only` defaults to true for M7 slice 1's reason — a queue shows what is waiting — and the
    unfiltered list stays available: a history nobody can read is a history nobody can audit.
    """

    with runtime.uow_factory() as uow:
        statement = select(ManualReviewTask)
        if open_only:
            statement = statement.where(ManualReviewTask.status.in_(OPEN_STATUSES))
        if assigned_to_me:
            statement = statement.where(
                ManualReviewTask.assigned_to_admin_user_id == actor.actor_id
            )
        rows = uow.session.scalars(
            statement.order_by(
                ManualReviewTask.priority.desc(), ManualReviewTask.created_at
            )
        ).all()
        return [_detail(uow.session, task) for task in rows]


@router.get(
    "/{task_id}",
    response_model=TaskDetail,
    operation_id="getManualReviewTask",
    summary="One queue item.",
    responses=RESPONSES,
    dependencies=[requires(declare("manual_review.read"))],
)
def get_manual_review_task(
    task_id: uuid.UUID,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> TaskDetail:
    """`GET /api/v1/manual-review-tasks/{task_id}`."""

    del actor
    with runtime.uow_factory() as uow:
        task = uow.session.get(ManualReviewTask, task_id)
        if task is None:
            raise NotFoundError()
        return _detail(uow.session, task)


@router.post(
    "/{task_id}/assign",
    response_model=TaskDetail,
    operation_id="assignManualReviewTask",
    summary="Say who is responsible for this item.",
    responses=RESPONSES,
    dependencies=[requires(declare("manual_review.assign"))],
)
def assign_manual_review_task(
    task_id: uuid.UUID,
    payload: AssignRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> TaskDetail:
    """`POST /api/v1/manual-review-tasks/{task_id}/assign`."""

    expected = _if_match(if_match)
    now = utc_now()
    with runtime.uow_factory() as uow:
        task = task_commands.assign(
            task_commands.AssignTask(
                manual_review_task_id=task_id,
                assignee_admin_user_id=payload.assignee_admin_user_id,
                expected_record_version=expected,
            ),
            uow=uow,
            policy=TASK_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            now=now,
        )
        rendered = _detail(uow.session, task)
        uow.commit()

    return rendered


@router.post(
    "/{task_id}/start",
    response_model=TaskDetail,
    operation_id="startManualReviewTask",
    summary="Record that work has begun.",
    responses=RESPONSES,
    dependencies=[requires(declare("manual_review.assign"))],
)
def start_manual_review_task(
    task_id: uuid.UUID,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> TaskDetail:
    """`POST /api/v1/manual-review-tasks/{task_id}/start`.

    **Guarded by `manual_review.assign`**, because the catalogue has no `.start` and beginning work
    is the same authority as deciding who does it. Recorded here rather than resolved by inventing a
    permission.
    """

    expected = _if_match(if_match)
    now = utc_now()
    with runtime.uow_factory() as uow:
        task = task_commands.start(
            task_commands.StartTask(
                manual_review_task_id=task_id, expected_record_version=expected
            ),
            uow=uow,
            policy=TASK_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            now=now,
        )
        rendered = _detail(uow.session, task)
        uow.commit()

    return rendered


@router.post(
    "/{task_id}/resolve",
    response_model=TaskDetail,
    operation_id="resolveManualReviewTask",
    summary="Record what was decided about this item.",
    responses=RESPONSES,
    dependencies=[requires(declare("manual_review.resolve"))],
)
def resolve_manual_review_task(
    task_id: uuid.UUID,
    payload: ResolveRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TaskDetail:
    """`POST /api/v1/manual-review-tasks/{task_id}/resolve`.

    **Both preconditions.** `:2065` requires `If-Match` on the transition and idempotency on
    "sensitive resolution commands" — this is one, because a resolution is the record that a person
    looked and decided, and a retry must not produce two of them.

    Resolving changes nothing about the subject. A task about a quarantined export does not
    un-quarantine it: §13.1 keeps financial truth in explicit tables.
    """

    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")
    expected = _if_match(if_match)

    now = utc_now()
    with runtime.uow_factory() as uow:
        task = task_commands.resolve(
            task_commands.ResolveTask(
                manual_review_task_id=task_id,
                resolution_code=payload.resolution_code,
                resolution_note=payload.resolution_note,
                expected_record_version=expected,
            ),
            uow=uow,
            policy=TASK_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            now=now,
        )
        rendered = _detail(uow.session, task)
        uow.commit()

    return rendered


@router.post(
    "/{task_id}/cancel",
    response_model=TaskDetail,
    operation_id="cancelManualReviewTask",
    summary="Withdraw an item that should not have been raised.",
    responses=RESPONSES,
    dependencies=[requires(declare("manual_review.resolve"))],
)
def cancel_manual_review_task(
    task_id: uuid.UUID,
    payload: CancelRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TaskDetail:
    """`POST /api/v1/manual-review-tasks/{task_id}/cancel`.

    **Guarded by `manual_review.resolve`**, because the catalogue has no `.cancel` and both commands
    end a queue item. **Not** resolution though: nothing is decided about the subject, so no
    `resolution_code` is written and the table refuses one.
    """

    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")
    expected = _if_match(if_match)

    now = utc_now()
    with runtime.uow_factory() as uow:
        task = task_commands.cancel(
            task_commands.CancelTask(
                manual_review_task_id=task_id,
                reason=payload.reason,
                expected_record_version=expected,
            ),
            uow=uow,
            policy=TASK_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            now=now,
        )
        rendered = _detail(uow.session, task)
        uow.commit()

    return rendered
