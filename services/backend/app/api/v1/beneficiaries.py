"""The beneficiary API, for two audiences that are authorised differently.

`05_API_Specification.md:929-960`. Every route here serves both a trader acting for
itself and internal staff acting for a trader, and the two are authorised by
different mechanisms — which is why none of these routes carries a route-level
`requires(...)` guard.

**A trader actor holds no permissions at all.** `ActorContext.__post_init__`
enforces it, citing `04_Database_Schema.md:405`: trader access is identity and
ownership scope, and grants would make a trader authorisable through the internal
RBAC path. So `dependencies=[requires(declare("beneficiary.read"))]` on a route a
trader must reach would deny every trader, always. The permission catalogue lists
`beneficiary.read`, `beneficiary.create_own` and `beneficiary.update_future` under
`trader_owner`, and those rows describe intent rather than a runtime mechanism —
`trader_self_service.py` and `traders.py` already work this way.

So authorisation is `_scope_for`, and it returns the trader id to filter by. For a
trader that is their own id and nothing the caller sends can change it; for staff
it is `None`, meaning unfiltered, and only after the internal permission was
checked. A route that forgot to apply the returned scope would be an IDOR, so the
helper returns the scope rather than merely approving — the value has to be used
for the query to compile.

**A beneficiary belonging to another trader answers exactly as a missing one.** The
pattern M4 slice 5 established for files: a `403` here would confirm the id is
real, which is a membership oracle over other traders' address books.

Covers: SEC-BEN-001, SEC-BEN-002.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.commands import beneficiary as commands
from app.core.errors import (
    ErrorEnvelope,
    ForbiddenError,
    NotFoundError,
    PreconditionRequiredError,
    VersionConflictError,
)
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.beneficiary import Beneficiary
from app.security.actor import ActorContext
from app.security.ownership import require_owned, scoped
from app.security.permissions import declare

router = APIRouter(prefix="/beneficiaries", tags=["beneficiaries"])

# POL-003 is open and `RedactionPolicy` deliberately has no default, so the choice
# is made here and visibly. `traders.py` chose `True` on the grounds that nothing in
# the trader lifecycle carries an IBAN at all; this is the first aggregate where the
# decision actually bites, so the reason has to be a real one.
#
# `True`, and the mask is what makes it cost nothing: `mask_iban_value` keeps the
# country prefix and the last four digits — "enough to reconcile a record against a
# statement, not enough to originate a transfer from the audit trail". An audit row
# recording a corrected IBAN still shows which account it was and which it became.
# Storing the full number would put an originatable payment destination in an
# append-only table that no runtime role may ever UPDATE, so a mistake there could
# only be undone by deleting evidence.
BENEFICIARY_REDACTION = RedactionPolicy(mask_iban=True)

COMMON_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "Internal caller lacks the permission."},
    404: {"model": ErrorEnvelope, "description": "Missing, or not the caller's."},
    **VALIDATION_ERROR_RESPONSE,
}

WRITE_RESPONSES: dict[int | str, dict[str, object]] = {
    **COMMON_RESPONSES,
    412: {"model": ErrorEnvelope, "description": "The If-Match value is stale."},
    428: {"model": ErrorEnvelope, "description": "If-Match is required."},
}


class DuplicateWarningResponse(BaseModel):
    """Advice attached to a successful create.

    It is in the response body rather than a header because it is about the
    request's meaning, and because a header is the first thing a client drops.
    """

    model_config = ConfigDict(extra="forbid")

    beneficiary_id: uuid.UUID
    matched_on: str
    full_name: str


class BeneficiaryResponse(BaseModel):
    """Deliberately not the whole row.

    `notes_internal` is internal, as it is on `traders`. Listing fields explicitly
    rather than serialising the model is what keeps a column added later from
    becoming trader-visible by default.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    trader_id: uuid.UUID
    full_name: str
    iban: str
    national_id: str | None
    phone_number: str | None
    status: str
    verification_status: str
    record_version: int


class BeneficiaryCreated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beneficiary: BeneficiaryResponse
    duplicate_warnings: list[DuplicateWarningResponse]


class BeneficiaryList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[BeneficiaryResponse]


class CreateBeneficiaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=255)
    iban: str = Field(min_length=1, max_length=64)
    national_id: str | None = Field(default=None, max_length=16)
    phone_number: str | None = Field(default=None, max_length=32)
    notes_internal: str | None = Field(default=None)
    # Read only for an internal actor, per `05_API_Specification.md:947`. For a
    # trader it is ignored rather than rejected: the field is part of one documented
    # request shape, and a trader's own scope is never taken from a body.
    trader_id: uuid.UUID | None = None


class UpdateBeneficiaryRequest(BaseModel):
    """Absent on purpose: `status`, which moves through its own endpoint, and
    `verification_status`, which no actor sets by hand."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    iban: str | None = Field(default=None, min_length=1, max_length=64)
    national_id: str | None = Field(default=None, max_length=16)
    phone_number: str | None = Field(default=None, max_length=32)


class DeactivateBeneficiaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


def owned_or_permitted(permission: str) -> Any:
    """Authorise both audiences in one dependency, and hand back the scope.

    A route-level `requires(...)` cannot serve these endpoints: a trader actor
    carries no permissions at all, so it would deny every trader. But moving the
    check into the handler would make it invisible to
    `tests/backend/test_permission_guards.py`, which reads permissions out of the
    route's **dependency graph** — the route would then have to be added to
    `UNGUARDED_ROUTES`, which is for routes that need no permission, and these
    need one from half their callers.

    So it stays a dependency. The permission is still declared at import, the gate
    still finds it in the closure, and the value it returns is the trader id the
    handler must filter by — `None` for an internal caller, meaning unfiltered and
    only after the permission was checked.

    Returning the scope rather than approving silently is the second half. A
    handler cannot use this without receiving the value it has to apply, so
    "authorised, then forgot to filter" is harder to write than the correct
    version.
    """

    declared = declare(permission)

    def guard(
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> uuid.UUID | None:
        if actor.is_trader:
            return actor.trader_id
        if declared not in actor.permissions:
            raise ForbiddenError()
        return None

    return Depends(guard)


@router.get(
    "",
    response_model=BeneficiaryList,
    operation_id="listBeneficiaries",
    summary="Beneficiaries the caller may see.",
    responses=COMMON_RESPONSES,
)
def list_beneficiaries(
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    scope: Annotated[uuid.UUID | None, owned_or_permitted("beneficiary.read")],
    trader_id: Annotated[uuid.UUID | None, Query()] = None,
) -> BeneficiaryList:
    """A trader sees their own; internal staff may filter by trader (`:938`).

    The `trader_id` query parameter is applied **only** for an internal caller. A
    trader's rows come from `scoped()`, which takes the actor and has no parameter
    a caller's value could be passed into — so a trader sending another trader's
    id gets their own list back rather than an error, because the parameter is
    never consulted on that path.
    """

    query = select(Beneficiary).order_by(Beneficiary.created_at)
    with runtime.uow_factory() as uow:
        if scope is not None:
            query = scoped(query, Beneficiary.trader_id, actor)
        elif trader_id is not None:
            query = query.where(Beneficiary.trader_id == trader_id)
        rows = list(uow.session.scalars(query))
        response = BeneficiaryList(items=[_render(row) for row in rows])
        uow.rollback()
    return response


@router.post(
    "",
    response_model=BeneficiaryCreated,
    status_code=201,
    operation_id="createBeneficiary",
    summary="Create a beneficiary, warning about duplicates without refusing them.",
    responses=COMMON_RESPONSES,
)
def create_beneficiary(
    payload: CreateBeneficiaryRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    scope: Annotated[uuid.UUID | None, owned_or_permitted("beneficiary.create")],
) -> BeneficiaryCreated:
    """A duplicate IBAN succeeds and returns a warning naming the match.

    Three documents say so and the reflex says otherwise, which is why
    `SVC-BEN-001` exists.
    """

    owner = scope if scope is not None else payload.trader_id
    if owner is None:
        raise NotFoundError()

    now = utc_now()
    with runtime.uow_factory() as uow:
        result = commands.create_beneficiary(
            commands.CreateBeneficiary(
                trader_id=owner,
                full_name=payload.full_name,
                iban=payload.iban,
                national_id=payload.national_id,
                phone_number=payload.phone_number,
                notes_internal=payload.notes_internal,
            ),
            acting=actor,
            session=uow.session,
            policy=BENEFICIARY_REDACTION,
            actor=_audit_actor(actor),
            context=_audit_context(actor),
            now=now,
        )
        rendered = BeneficiaryCreated(
            beneficiary=_render(result.beneficiary),
            duplicate_warnings=[
                DuplicateWarningResponse(
                    beneficiary_id=warning.beneficiary_id,
                    matched_on=warning.matched_on,
                    full_name=warning.full_name,
                )
                for warning in result.warnings
            ],
        )
        uow.commit()
    return rendered


@router.get(
    "/{beneficiary_id}",
    response_model=BeneficiaryResponse,
    operation_id="getBeneficiary",
    summary="One beneficiary the caller may see.",
    responses=COMMON_RESPONSES,
)
def get_beneficiary(
    beneficiary_id: uuid.UUID,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    scope: Annotated[uuid.UUID | None, owned_or_permitted("beneficiary.read")],
) -> BeneficiaryResponse:
    with runtime.uow_factory() as uow:
        record = _reachable(uow.session, beneficiary_id, scope, actor)
        response = _render(record)
        uow.rollback()
    return response


@router.patch(
    "/{beneficiary_id}",
    response_model=BeneficiaryResponse,
    operation_id="updateBeneficiary",
    summary="Correct a beneficiary. Historical snapshots are unaffected.",
    responses=WRITE_RESPONSES,
)
def update_beneficiary(
    beneficiary_id: uuid.UUID,
    payload: UpdateBeneficiaryRequest,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    scope: Annotated[uuid.UUID | None, owned_or_permitted("beneficiary.update_future")],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> BeneficiaryResponse:
    """`If-Match` is required (`:940`), for the stale-tab case."""

    if if_match is None:
        raise PreconditionRequiredError("If-Match")
    expected = _parse_record_version(if_match)

    now = utc_now()
    with runtime.uow_factory() as uow:
        _reachable(uow.session, beneficiary_id, scope, actor)
        result = commands.update_beneficiary(
            commands.UpdateBeneficiary(
                beneficiary_id=beneficiary_id,
                expected_record_version=expected,
                full_name=payload.full_name,
                iban=payload.iban,
                national_id=payload.national_id,
                phone_number=payload.phone_number,
            ),
            session=uow.session,
            policy=BENEFICIARY_REDACTION,
            actor=_audit_actor(actor),
            context=_audit_context(actor),
            now=now,
        )
        rendered = _render(result.beneficiary)
        uow.commit()

    response.headers["ETag"] = f'"rv-{rendered.record_version}"'
    return rendered


@router.post(
    "/{beneficiary_id}/deactivate",
    response_model=BeneficiaryResponse,
    operation_id="deactivateBeneficiary",
    summary="Retire a beneficiary. The row stays and nothing is deleted.",
    responses=WRITE_RESPONSES,
)
def deactivate_beneficiary(
    beneficiary_id: uuid.UUID,
    payload: DeactivateBeneficiaryRequest,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    scope: Annotated[uuid.UUID | None, owned_or_permitted("beneficiary.deactivate")],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> BeneficiaryResponse:
    """`active -> inactive`, per document 06's transition table.

    Document 05's endpoint table names `block` and `reactivate` here and not
    `deactivate`, while the permission catalogue has `beneficiary.deactivate` and
    neither of the other two. Only this one has both a catalogued permission and a
    document 06 transition, so it is the only one built — see DOC-CONFLICT-049.
    """

    if if_match is None:
        raise PreconditionRequiredError("If-Match")
    expected = _parse_record_version(if_match)

    now = utc_now()
    with runtime.uow_factory() as uow:
        _reachable(uow.session, beneficiary_id, scope, actor)
        result = commands.deactivate_beneficiary(
            commands.DeactivateBeneficiary(
                beneficiary_id=beneficiary_id,
                expected_record_version=expected,
                reason=payload.reason,
            ),
            session=uow.session,
            policy=BENEFICIARY_REDACTION,
            actor=_audit_actor(actor),
            context=_audit_context(actor),
            now=now,
        )
        rendered = _render(result.beneficiary)
        uow.commit()

    response.headers["ETag"] = f'"rv-{rendered.record_version}"'
    return rendered


def _audit_actor(actor: ActorContext) -> AuditActor:
    """Every caller here is authenticated, so there is no system-actor branch.

    `traders.py` needs one because registration is public. A beneficiary is always
    created by somebody with a session, and inventing a fallback identity for a
    case that cannot arise would put a fictional person in an append-only table the
    first time an unrelated bug reached it.
    """

    return AuditActor(
        actor_type=actor.actor_type.value,
        actor_id=actor.actor_id,
        role_snapshot=tuple(sorted(actor.roles)),
        session_id=actor.session_id,
        authentication_assurance=actor.auth_level,
    )


def _audit_context(actor: ActorContext) -> AuditContext:
    del actor
    return AuditContext(request_id=get_request_id())


def _reachable(
    session: Session,
    beneficiary_id: uuid.UUID,
    scope: uuid.UUID | None,
    actor: ActorContext,
) -> Beneficiary:
    """The row, or `NotFoundError` for both "missing" and "not yours".

    One function for both so the two cannot drift apart. A `403` for the second
    would confirm the id names a real beneficiary belonging to somebody, which is
    a membership oracle over other traders' address books.

    The trader path goes through `require_owned`, which compares against
    `ActorContext.trader_id` rather than against `scope`. They hold the same value
    — `owned_or_permitted` returned it from the same actor — and using the actor
    keeps the comparison anchored to the session even if a later edit changed
    where `scope` came from.
    """

    record = session.get(Beneficiary, beneficiary_id)
    if scope is None:
        # Internal caller: the permission was checked by the dependency, and
        # `12_Security_RBAC_Audit.md:316` says staff reach trader records through
        # permissions rather than ownership. There is nothing to own here.
        if record is None:
            raise NotFoundError()
        return record

    owner = record.trader_id if record is not None else None
    found = require_owned(record, owner, actor)
    assert isinstance(found, Beneficiary)
    return found


def _render(record: Beneficiary) -> BeneficiaryResponse:
    return BeneficiaryResponse(
        id=record.id,
        trader_id=record.trader_id,
        full_name=record.full_name,
        iban=record.iban,
        national_id=record.national_id,
        phone_number=record.phone_number,
        status=record.status,
        verification_status=record.verification_status,
        record_version=record.record_version,
    )


def _parse_record_version(value: str) -> int:
    cleaned = value.strip().strip('"')
    if not cleaned.startswith("rv-") or not cleaned[3:].isdigit():
        raise VersionConflictError()
    return int(cleaned[3:])
