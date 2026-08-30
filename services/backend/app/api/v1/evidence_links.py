"""Confirmed evidence links. `05_API_Specification.md` §19.7-19.9.

M9 slice 2. Three routes, one permission each, and the paths are document 05's exactly.

**`/void` is the path and `revoked` is the stored status.** `:1857` names the route and §12.6's
column list spells the state `voided`; documents 06 and 08 say `revoked` and `status_catalog.yaml`
makes that canonical with `voided` a provisional alias. `command_catalog.yaml`'s revoke row carries
`status: blocked_by_voided_vs_revoked_status_conflict` — the catalogue flagged this before anybody
wrote code against it. The path stays because it is the contract and renaming it is a breaking
change the oasdiff gate refuses; the column takes the canonical spelling because the status-drift
gate holds every CHECK to its aggregate exactly. Documents 04 and 05 are owed an editorial fix.

**Three permissions, one per route**, all seeded to `accountant` alone (`20260801_0008:218-220`).
No role holds a proper subset of them, so a permission negative here cannot be as sharp as slice
1's — the live test says so rather than implying a sharpness it does not have.

**`Idempotency-Key` on all three**, which `command_catalog.yaml` requires of each. No `If-Match`:
§12.6 gives the table no `record_version`, and the concurrency the catalogue asks for is row
locking plus the two partial unique indexes, both of which happen inside the command.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor, requires
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.commands import confirmed_evidence_link as link_commands
from app.core.errors import ErrorEnvelope, ForbiddenError, PreconditionRequiredError
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.confirmed_evidence_link import (
    LINK_PRIMARY,
    ConfirmedEvidenceLink,
)
from app.security.actor import ActorContext
from app.security.permissions import declare

router = APIRouter(prefix="/evidence-links", tags=["evidence-links"])

# A link names an attempt and a segment and carries no payee data of its own. The policy is
# applied anyway: its audit rows sit beside rows that do carry an IBAN, and a policy chosen per
# module is one that drifts.
EVIDENCE_REDACTION = RedactionPolicy(mask_iban=True)

RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "The caller lacks the evidence permission."},
    404: {"model": ErrorEnvelope, "description": "No such link, attempt or segment."},
    409: {
        "model": ErrorEnvelope,
        "description": "An active primary link already exists for this attempt or segment.",
    },
    428: {"model": ErrorEnvelope, "description": "Idempotency-Key is required."},
    **VALIDATION_ERROR_RESPONSE,
}


class ConfirmRequest(BaseModel):
    """§19.7's body, verbatim in its field names."""

    model_config = ConfigDict(extra="forbid")

    payment_attempt_id: uuid.UUID
    receipt_segment_id: uuid.UUID
    link_type: str = Field(default=LINK_PRIMARY, min_length=1, max_length=24)
    confirmation_note: str | None = Field(default=None, max_length=4000)


class ReplaceRequest(BaseModel):
    """§19.8's body. The reason is required by the schema *and* by the command.

    Both, deliberately: `min_length=1` gives a client a 422 naming the field, and the command's
    check gives the same refusal to any caller that does not come through this schema — a worker,
    a test, a later route. `command_catalog.yaml` states `reason_required` as a precondition on
    the command, not on the request body.
    """

    model_config = ConfigDict(extra="forbid")

    new_receipt_segment_id: uuid.UUID
    replacement_reason: str = Field(min_length=1, max_length=4000)


class VoidRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=4000)


class EvidenceLinkDetail(BaseModel):
    """What a confirmed link is.

    No `payment_status` and no `paid` field: a link says a segment is evidence for an attempt and
    says nothing about whether that attempt was paid. Slice 3's command decides that, and a
    response carrying both would invite a screen to read one as the other.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    payment_attempt_id: uuid.UUID
    receipt_segment_id: uuid.UUID
    link_type: str
    status: str
    confirmed_by_admin_user_id: uuid.UUID
    confirmed_at: datetime
    replaces_link_id: uuid.UUID | None
    replacement_reason: str | None
    published_to_trader_at: datetime | None
    created_at: datetime


def _detail(link: ConfirmedEvidenceLink) -> EvidenceLinkDetail:
    return EvidenceLinkDetail(
        id=link.id,
        payment_attempt_id=link.payment_attempt_id,
        receipt_segment_id=link.receipt_segment_id,
        link_type=link.link_type,
        status=link.status,
        confirmed_by_admin_user_id=link.confirmed_by_admin_user_id,
        confirmed_at=link.confirmed_at,
        replaces_link_id=link.replaces_link_id,
        replacement_reason=link.replacement_reason,
        published_to_trader_at=link.published_to_trader_at,
        created_at=link.created_at,
    )


def _audit_actor(actor: ActorContext) -> AuditActor:
    return AuditActor(
        actor_type=actor.actor_type.value,
        actor_id=actor.actor_id,
        role_snapshot=tuple(sorted(actor.roles)),
        session_id=actor.session_id,
        authentication_assurance=actor.auth_level,
    )


def _confirming_admin(actor: ActorContext) -> uuid.UUID:
    """§12.6's `confirmed_by_admin_user_id` is NOT NULL and names a *human*.

    A trader session cannot reach these routes — the permissions are seeded to `accountant` — but
    the column is written from the actor rather than from the request body, so there is no field a
    client could use to attribute a confirmation to somebody else.
    """

    if actor.actor_id is None:
        raise ForbiddenError()
    return actor.actor_id


def _require_key(idempotency_key: str | None) -> str:
    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")
    return idempotency_key


@router.post(
    "",
    response_model=EvidenceLinkDetail,
    status_code=201,
    operation_id="confirmEvidenceLink",
    summary="Confirm that a receipt segment is evidence for a payment attempt.",
    responses=RESPONSES,
    dependencies=[requires(declare("evidence_link.confirm"))],
)
def confirm_evidence_link(
    payload: ConfirmRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> EvidenceLinkDetail:
    """`POST /api/v1/evidence-links`, per `:1824`.

    **"The command enforces one active primary link per attempt and one active primary attempt per
    segment"** (`:1836`) — and it is enforced by two partial unique indexes rather than by a read
    in the handler, because two accountants on two screens would both pass a read.
    """

    key = _require_key(idempotency_key)
    now = utc_now()
    with runtime.uow_factory() as uow:
        result = link_commands.confirm_evidence_link(
            link_commands.ConfirmEvidenceLink(
                payment_attempt_id=payload.payment_attempt_id,
                receipt_segment_id=payload.receipt_segment_id,
                link_type=payload.link_type,
                confirmed_by_admin_user_id=_confirming_admin(actor),
                confirmation_note=payload.confirmation_note,
            ),
            uow=uow,
            policy=EVIDENCE_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=key,
            now=now,
        )
        rendered = _detail(result.link)
        uow.commit()

    return rendered


@router.post(
    "/{link_id}/replace",
    response_model=EvidenceLinkDetail,
    status_code=201,
    operation_id="replaceEvidenceLink",
    summary="Retire a link and put another in its place, in one transaction.",
    responses=RESPONSES,
    dependencies=[requires(declare("evidence_link.replace"))],
)
def replace_evidence_link(
    link_id: uuid.UUID,
    payload: ReplaceRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> EvidenceLinkDetail:
    """`POST /api/v1/evidence-links/{link_id}/replace`, per `:1844`.

    **201, because the response is the new link.** `:1848` describes the old link becoming
    `replaced` and the new one becoming active in one transaction; the resource a client should
    hold afterwards is the replacement, and returning the retired row would hand back something
    already historical.
    """

    key = _require_key(idempotency_key)
    now = utc_now()
    with runtime.uow_factory() as uow:
        result = link_commands.replace_evidence_link(
            link_commands.ReplaceEvidenceLink(
                link_id=link_id,
                new_receipt_segment_id=payload.new_receipt_segment_id,
                replacement_reason=payload.replacement_reason,
                confirmed_by_admin_user_id=_confirming_admin(actor),
            ),
            uow=uow,
            policy=EVIDENCE_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=key,
            now=now,
        )
        rendered = _detail(result.link)
        uow.commit()

    return rendered


@router.post(
    "/{link_id}/void",
    response_model=EvidenceLinkDetail,
    operation_id="voidEvidenceLink",
    summary="Withdraw a supplementary link, with a reason.",
    responses=RESPONSES,
    dependencies=[requires(declare("evidence_link.revoke"))],
)
def void_evidence_link(
    link_id: uuid.UUID,
    payload: VoidRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> EvidenceLinkDetail:
    """`POST /api/v1/evidence-links/{link_id}/void`, per `:1860`.

    **Supplementary only.** `:1864`: "Primary links use the replacement/correction workflow unless
    the entire result is formally revoked." The command refuses a primary link and its message
    names the workflow to use instead — the exception is the correction command M9's last slice
    builds, not this route.

    **The path says `void` and the stored status is `revoked`**, which is the conflict the module
    docstring and `20260830_0029` record.
    """

    key = _require_key(idempotency_key)
    now = utc_now()
    with runtime.uow_factory() as uow:
        result = link_commands.revoke_evidence_link(
            link_commands.RevokeEvidenceLink(link_id=link_id, reason=payload.reason),
            uow=uow,
            policy=EVIDENCE_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=key,
            now=now,
        )
        rendered = _detail(result.link)
        uow.commit()

    return rendered
