"""Staff account administration: list, create, read, amend.

**The permissions are not the ones document 05 names, and that is deliberate.** Its
endpoint catalogue (`05_API_Specification.md:867-872`) declares `admin_user.read` and
`admin_user.manage`. The approved permission catalogue records both as **deprecated
aliases** — the second `deprecated_ambiguous`, with `resolution: select the
action-specific canonical permission per endpoint` — and resolves them to `user.read`,
`user.create`, `user.update` and `user.deactivate`. DOC-CONFLICT-013's approved direction
is that document 12's identifiers win.

So `declare("admin_user.manage")` would raise `UnknownPermission` at import, which is the
fail-closed design working: the alias is not a grantable row. And using one broad
permission for creation, amendment and deactivation would violate
`12_Security_RBAC_Audit.md:700` directly — "implementations may add narrower permissions
but must not merge unrelated high-risk actions into one broad permission". The mapping is
recorded in the catalogue's `endpoint_permission_discrepancies` so the substitution is
reviewable rather than invented here.

**What this family does not include yet.** Suspend and reactivate need a state guard and
the rule that the last account holding `user.*` cannot be deactivated — nothing today
stops one administrator stranding the deployment. The reset needs a recovery path. Both
are slice 8E's, recorded in the plan rather than half-built here.

Covers: API-ADMIN-001, API-ADMIN-002, API-ADMIN-003.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime, get_settings
from app.api.v1.auth import authenticated_actor, requires
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.commands.admin_user_lifecycle import (
    AdminUserAmendment,
    AdminUserResult,
    NewAdminUser,
    amend_admin_user,
    create_admin_user,
    list_admin_users,
    read_admin_user,
)
from app.core.config import Settings
from app.core.errors import ErrorEnvelope, PreconditionRequiredError
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.security.actor import ActorContext
from app.security.passwords import Argon2Parameters
from app.security.permissions import declare

router = APIRouter(prefix="/admin-users", tags=["admin-users"])

# Masking on, as every command's policy is, and stated at the call site because
# `RedactionPolicy` has no default.
ADMIN_USER_REDACTION = RedactionPolicy(mask_iban=True)

ADMIN_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "Permission denied."},
    404: {"model": ErrorEnvelope, "description": "No such account."},
    **VALIDATION_ERROR_RESPONSE,
}

WRITE_RESPONSES: dict[int | str, dict[str, object]] = {
    **ADMIN_RESPONSES,
    400: {"model": ErrorEnvelope, "description": "The request violates a business rule."},
    409: {
        "model": ErrorEnvelope,
        "description": "The idempotency key was reused with a different body.",
    },
    412: {"model": ErrorEnvelope, "description": "The If-Match value is stale."},
    428: {"model": ErrorEnvelope, "description": "If-Match or Idempotency-Key is missing."},
}


class AdminUserView(BaseModel):
    """Never `password_hash`, and never the lockout counters.

    `extra="forbid"` is what makes that structural rather than a habit: adding the hash to
    the command result without adding it here fails at serialisation, and
    `test_no_admin_user_response_carries_a_credential` fails if either changes.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    username: str
    full_name: str
    email: str | None
    phone_number: str | None
    status: str
    role_codes: list[str]
    record_version: int


class AdminUserListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admin_users: list[AdminUserView]


class CreateAdminUserRequest(BaseModel):
    """No `status` field: a new account's state is the command's decision, not the
    caller's, and accepting it would let a creation mint a `deactivated` account or one in
    `recovery_required` that nothing can recover."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1024)
    role_codes: list[str] = Field(min_length=1)
    email: str | None = Field(default=None, max_length=254)
    phone_number: str | None = Field(default=None, max_length=32)


class AmendAdminUserRequest(BaseModel):
    """Contact details only. See `amend_admin_user` for why the other four fields each
    belong to their own command."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    phone_number: str | None = Field(default=None, max_length=32)


def _view(result: AdminUserResult) -> AdminUserView:
    return AdminUserView(
        id=result.id,
        username=result.username,
        full_name=result.full_name,
        email=result.email,
        phone_number=result.phone_number,
        status=result.status,
        role_codes=list(result.role_codes),
        record_version=result.record_version,
    )


def _audit_pair(actor: ActorContext) -> tuple[AuditActor, AuditContext]:
    return (
        AuditActor(
            actor_type=actor.actor_type.value,
            actor_id=actor.actor_id,
            role_snapshot=tuple(sorted(actor.roles)),
        ),
        AuditContext(request_id=get_request_id()),
    )


def _parse_record_version(value: str) -> int:
    """`If-Match: "rv-7"`, the same shape the trader routes publish.

    One spelling across the API, because a client that learned the format from one
    endpoint should not have to relearn it at the next.
    """

    from app.core.errors import VersionConflictError

    text = value.strip().strip('"')
    if not text.startswith("rv-") or not text[3:].isdigit():
        raise VersionConflictError()
    return int(text[3:])


@router.get(
    "",
    response_model=AdminUserListResponse,
    operation_id="listAdminUsers",
    summary="List staff accounts.",
    responses=ADMIN_RESPONSES,
    dependencies=[requires(declare("user.read"))],
)
def list_accounts(
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> AdminUserListResponse:
    del actor
    with runtime.uow_factory() as uow:
        results = list_admin_users(uow)
        uow.rollback()
    return AdminUserListResponse(admin_users=[_view(result) for result in results])


@router.get(
    "/{admin_user_id}",
    response_model=AdminUserView,
    operation_id="getAdminUser",
    summary="Read one staff account.",
    responses=ADMIN_RESPONSES,
    dependencies=[requires(declare("user.read"))],
)
def get_account(
    admin_user_id: uuid.UUID,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> AdminUserView:
    del actor
    with runtime.uow_factory() as uow:
        result = read_admin_user(uow, admin_user_id)
        uow.rollback()
    rendered = _view(result)
    response.headers["ETag"] = f'"rv-{rendered.record_version}"'
    return rendered


@router.post(
    "",
    response_model=AdminUserView,
    operation_id="createAdminUser",
    summary="Create a staff account.",
    responses=WRITE_RESPONSES,
    dependencies=[requires(declare("user.create"))],
)
def create_account(
    payload: CreateAdminUserRequest,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AdminUserView:
    """`Idempotency-Key` is required **and used**.

    Doc 05:868 requires the header. `12_Security_RBAC_Audit.md` §12 additionally requires
    the record to be resolved and its completion persisted, which the four trader decision
    routes do not do — they require the header and discard it. This one claims through
    `IdempotencyResolver`, so a retried creation returns the first account instead of a
    second person with the same name.
    """

    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")

    audit_actor, context = _audit_pair(actor)
    with runtime.uow_factory() as uow:
        result = create_admin_user(
            NewAdminUser(
                username=payload.username,
                full_name=payload.full_name,
                password=payload.password,
                role_codes=tuple(payload.role_codes),
                email=payload.email,
                phone_number=payload.phone_number,
            ),
            uow=uow,
            actor=audit_actor,
            context=context,
            idempotency_key=idempotency_key,
            policy=ADMIN_USER_REDACTION,
            parameters=Argon2Parameters.from_settings(settings),
            password_max_length=settings.password_max_length,
            now=utc_now(),
        )
        uow.commit()

    rendered = _view(result)
    response.headers["ETag"] = f'"rv-{rendered.record_version}"'
    return rendered


@router.patch(
    "/{admin_user_id}",
    response_model=AdminUserView,
    operation_id="updateAdminUser",
    summary="Amend a staff account's contact details.",
    responses=WRITE_RESPONSES,
    dependencies=[requires(declare("user.update"))],
)
def update_account(
    admin_user_id: uuid.UUID,
    payload: AmendAdminUserRequest,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> AdminUserView:
    """`If-Match` required, per doc 05:870."""

    if if_match is None:
        raise PreconditionRequiredError("If-Match")

    audit_actor, context = _audit_pair(actor)
    with runtime.uow_factory() as uow:
        result = amend_admin_user(
            AdminUserAmendment(
                admin_user_id=admin_user_id,
                expected_record_version=_parse_record_version(if_match),
                full_name=payload.full_name,
                email=payload.email,
                phone_number=payload.phone_number,
            ),
            uow=uow,
            actor=audit_actor,
            context=context,
            policy=ADMIN_USER_REDACTION,
            now=utc_now(),
        )
        uow.commit()

    rendered = _view(result)
    response.headers["ETag"] = f'"rv-{rendered.record_version}"'
    return rendered
