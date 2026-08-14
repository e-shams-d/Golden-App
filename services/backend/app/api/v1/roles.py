"""Roles and their permissions.

Two routes. The read is ordinary; the write is the most dangerous request this API
accepts, because it is the one that changes what everything else is allowed to do.

**`role.read` and `role.manage`**, the catalogue's own codes — no alias substitution is
needed here, unlike `/admin-users`, because document 05 and document 12 agree on these
two.

**The write requires `X-Recent-Auth`.** `12_Security_RBAC_Audit.md:642` names recent
authentication among what a high-risk grant must carry, and this is the first route in the
platform to consume a step-up context. `app/commands/role_permissions.py` explains why
that mattered: the machinery has been complete since slice 7 with no caller at all.

**`If-Match` carries a digest of the permission set, not `rv-N`.** `roles` has no
`record_version` column and adding one would be a migration in a slice about
authorisation. The ETag published by the read is what the write must echo.

Covers: API-ROLE-001, SEC-ROLECHANGE-001.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import RecentAuthRequiredError, authenticated_actor, requires
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.commands import role_permissions
from app.core.errors import ErrorEnvelope, PreconditionRequiredError, VersionConflictError
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.rbac import Role
from app.security.actor import ActorContext
from app.security.permissions import declare

router = APIRouter(prefix="/roles", tags=["roles"])

ROLE_REDACTION = RedactionPolicy(mask_iban=True)

ROLE_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "Permission denied."},
    404: {"model": ErrorEnvelope, "description": "No such role."},
    **VALIDATION_ERROR_RESPONSE,
}

UPDATE_RESPONSES: dict[int | str, dict[str, object]] = {
    **ROLE_RESPONSES,
    400: {"model": ErrorEnvelope, "description": "The request violates a business rule."},
    412: {"model": ErrorEnvelope, "description": "The If-Match digest is stale."},
    428: {
        "model": ErrorEnvelope,
        "description": "If-Match or X-Recent-Auth is missing.",
    },
    440: {
        "model": ErrorEnvelope,
        "description": "Recent authentication is required, or the one presented does not "
        "authorise this change.",
    },
}


class RoleView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    code: str
    description: str | None
    is_system: bool
    is_enabled: bool
    permission_codes: list[str]


class RoleListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roles: list[RoleView]


class UpdateRolePermissionsRequest(BaseModel):
    """The complete desired set, not a diff.

    A PUT of the whole set is what makes the `If-Match` digest meaningful: a diff applied
    to a set somebody else has changed produces a result neither caller asked for, and no
    precondition can detect it. `reason` is required because `:642` lists it among what a
    role change must produce.
    """

    model_config = ConfigDict(extra="forbid")

    permission_codes: list[str] = Field(min_length=0)
    reason: str = Field(min_length=1, max_length=1000)


def _view(role: Role, codes: tuple[str, ...]) -> RoleView:
    return RoleView(
        id=role.id,
        code=role.code,
        description=role.description,
        is_system=role.is_system,
        is_enabled=role.is_enabled,
        permission_codes=list(codes),
    )


@router.get(
    "",
    response_model=RoleListResponse,
    operation_id="listRoles",
    summary="List roles and the permissions each carries.",
    responses=ROLE_RESPONSES,
    dependencies=[requires(declare("role.read"))],
)
def list_roles(
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> RoleListResponse:
    del actor
    with runtime.uow_factory() as uow:
        roles = list(uow.session.scalars(select(Role).order_by(Role.code)))
        views = [
            _view(role, role_permissions.current_codes(uow.session, role.id)) for role in roles
        ]
        uow.rollback()
    return RoleListResponse(roles=views)


@router.get(
    "/{role_id}",
    response_model=RoleView,
    operation_id="getRole",
    summary="Read one role. Publishes the ETag the update must echo.",
    responses=ROLE_RESPONSES,
    dependencies=[requires(declare("role.read"))],
)
def get_role(
    role_id: uuid.UUID,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> RoleView:
    del actor
    with runtime.uow_factory() as uow:
        # Bound first, like `traders.py` does. `test_no_io_under_lock` matches a call's
        # name against a safe-receiver list, and `session` is on it while the attribute
        # chain `uow.session` is not resolvable to a name — so the ORM lookup reads as an
        # unidentified `get()` and is reported as network I/O held under a lock.
        session = uow.session
        role = session.get(Role, role_id)
        if role is None:
            from app.core.errors import NotFoundError

            raise NotFoundError()
        codes = role_permissions.current_codes(session, role_id)
        view = _view(role, codes)
        uow.rollback()

    # The digest of the set, which is what `If-Match` on the update compares against.
    response.headers["ETag"] = f'"{role_permissions.permission_etag(codes)}"'
    return view


@router.put(
    "/{role_id}/permissions",
    response_model=RoleView,
    operation_id="updateRolePermissions",
    summary="Replace a role's permission set. Requires recent authentication.",
    responses=UPDATE_RESPONSES,
    dependencies=[requires(declare("role.manage"))],
)
def update_role_permissions(
    role_id: uuid.UUID,
    payload: UpdateRolePermissionsRequest,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    recent_auth: Annotated[str | None, Header(alias="X-Recent-Auth")] = None,
) -> RoleView:
    """Both preconditions, and they answer different questions.

    `If-Match` stops this landing on a permission set somebody else has changed.
    `X-Recent-Auth` proves the person holding the session was present a moment ago. Neither
    substitutes for the other: a fresh step-up does not make a stale write safe, and an
    up-to-date digest says nothing about who is holding the browser.

    The step-up must have been issued for **this role** — purpose `role.permissions.update`,
    resource type `role`, resource id this one. A context obtained to edit `accountant`
    presented here is refused as `WRONG_RESOURCE`, which is the binding the whole step-up
    design exists for.
    """

    if if_match is None:
        raise PreconditionRequiredError("If-Match")
    if recent_auth is None:
        # 428 rather than 440: the caller did not present a context at all, which is a
        # missing precondition. 440 is reserved for a context that was presented and did
        # not authorise this — the difference tells a client whether to obtain one or to
        # obtain a different one.
        raise PreconditionRequiredError("X-Recent-Auth")

    now = utc_now()
    audit_actor = AuditActor(
        actor_type=actor.actor_type.value,
        actor_id=actor.actor_id,
        role_snapshot=tuple(sorted(actor.roles)),
        session_id=actor.session_id,
        authentication_assurance=actor.auth_level,
    )
    context = AuditContext(request_id=get_request_id())

    with runtime.uow_factory() as uow:
        session = uow.session
        try:
            result = role_permissions.update_role_permissions(
                role_permissions.RolePermissionUpdate(
                    role_id=role_id,
                    permission_codes=tuple(payload.permission_codes),
                    expected_etag=if_match,
                    recent_auth_reference=recent_auth,
                    reason=payload.reason,
                ),
                session=session,
                actor=actor,
                audit_actor=audit_actor,
                context=context,
                policy=ROLE_REDACTION,
                now=now,
            )
        except role_permissions.StaleRolePermissions:
            uow.rollback()
            raise VersionConflictError() from None
        except role_permissions.StepUpRefused:
            # Committed on purpose. The command wrote a `step_up.rejected` security event
            # before raising, and rolling back would discard the record of the refusal —
            # which is the one thing an investigator needs when somebody is presenting
            # contexts that do not authorise what they are trying to do.
            uow.commit()
            # The nine reasons `StepUpRejection` distinguishes stay in `auth_events`. The
            # client is told one thing, exactly as login is.
            raise RecentAuthRequiredError() from None

        role = session.get(Role, role_id)
        assert role is not None  # the command raised NotFoundError if it were absent
        view = _view(role, result.permission_codes)
        uow.commit()

    response.headers["ETag"] = f'"{result.etag}"'
    return view
