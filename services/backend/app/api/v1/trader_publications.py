"""What a trader sees and says about their own result. `05_API_Specification.md` §20.4-20.6.

M9 slice 6. Three routes under `/me/trader`, and the first surface in this project where the
person on the other end is a customer rather than staff.

**A second trader gets 404, not 403.** §17 `:1185`: "trader sees only own active publication". An
authorisation error would tell them the publication exists, which over guessable identifiers is an
enumeration oracle — `app/security/ownership.py` records the rule and `require_owned` is what
applies it, so the refusal is indistinguishable from the row not existing.

**Ownership never arrives in the request.** `ActorContext.trader_id` comes from the session cookie
by way of `trader_users.trader_id`. `14_Testing_QA_Acceptance.md:1274` names the attack — "trader A
submits `trader_id` belonging to B" — and the defence is not to validate that field but never to
read one.

**The share-file download (§20.4's second route) is not here.** Slice 5B builds the renderer, and
`payment_result_publications.share_file_id` is null on every row until it does. A route that can
only ever 404 is a promise a client would write code against; the plan carries it with the slice
that can keep it.

**What a trader is shown is `summary_payload` and nothing else.** Not the row: the payload is the
part that was hashed and reviewed, and the columns beside it — who published, what it supersedes —
are the centre's record of its own act.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.commands import trader_result as trader_commands
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
from app.db.models.payment_request import PaymentRequest
from app.db.models.payment_result_publication import (
    PUBLICATION_ACTIVE,
    PaymentResultPublication,
)
from app.security.actor import ActorContext
from app.security.ownership import require_owned
from app.security.permissions import declare

router = APIRouter(prefix="/me/trader", tags=["trader-publications"])

# The payload was masked before it was stored, so nothing unmasked can reach this router. The
# policy is still passed explicitly: `RedactionPolicy` takes `mask_iban` per call site precisely so
# that POL-003 stays visible at every point that depends on it.
TRADER_REDACTION = RedactionPolicy(mask_iban=True)

RESPONSES: dict[int | str, dict[str, object]] = {
    400: {"model": ErrorEnvelope, "description": "There is no published result to respond to."},
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "The caller is not an active trader."},
    404: {
        "model": ErrorEnvelope,
        "description": "No such request, or it belongs to somebody else. The two are "
        "deliberately indistinguishable.",
    },
    412: {"model": ErrorEnvelope, "description": "If-Match is stale or unreadable."},
    428: {"model": ErrorEnvelope, "description": "If-Match and Idempotency-Key are required."},
    **VALIDATION_ERROR_RESPONSE,
}


class TraderPublicationResponse(BaseModel):
    """The active publication, as its owner sees it.

    No `published_by_admin_user_id` and no `supersedes_publication_id`: who at the centre pressed
    the button is the centre's record of its own act, and a trader who needs to raise something
    does it by request number. `publication_version` **is** here — §17 `:1153` lists it, and a
    trader who disputes needs to be able to say which version they are talking about.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    payment_request_id: uuid.UUID
    publication_version: int
    status: str
    content_hash: str
    summary_payload: dict[str, Any]
    published_at: datetime
    request_status: str
    acknowledged_at: datetime | None
    disputed_at: datetime | None


class DisputeRequest(BaseModel):
    """§20.6's body, minus `attachment_file_ids`.

    Document 05 shows that field. Accepting a file id here would let a trader name a file this
    command never checks the ownership of — the IDOR case `14_Testing_QA_Acceptance.md:1274`
    describes, arriving through a field that looks helpful. M4's upload path is where a trader's
    file gets an owner; linking one to a dispute needs that path, not this one.
    """

    model_config = ConfigDict(extra="forbid")

    reason_code: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=4000)


def trader_only(permission: str) -> Any:
    """Declare the catalogue's permission, and enforce ownership instead of checking it.

    **A `requires(...)` here would deny every trader.** `04_Database_Schema.md:405` makes trader
    access ownership-scoped and `app/security/actor.py` gives a trader session no permissions at
    all, so the route-level guard M5's internal routes use returns 403 for the only audience these
    routes have. That is not a theory: the first version of this module used `requires(...)` and
    every trader test failed with `Permission denied`.

    The permission name is still **named in the closure**, because
    `tests/backend/test_permission_guards.py` finds a route's permissions by walking it for
    approved codes — a route whose guard does not carry the string is a route that gate cannot
    see. M5's `payment_requests.py` records the same reasoning, including the version that wrote
    `del declared` to mark it unused and turned a closure variable into a local.

    So: `payment_publication.read_own` and its two siblings are what the catalogue says these
    routes are, `trader_owner` is the role that holds them, and the enforcement is
    `require_owned` on the request itself.
    """

    declared = declare(permission)

    def guard(
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> uuid.UUID | None:
        # `declared` is read so it is a closure variable rather than a free name. See above.
        _ = declared
        if not actor.is_trader:
            # An internal session is not an owner. `12_Security_RBAC_Audit.md:316` forbids
            # treating one as ownership of a trader account without an authorised support
            # workflow, and Phase 1A has none — so an accountant reaching these paths is refused
            # rather than silently shown somebody's result.
            raise ForbiddenError()
        return actor.trader_id

    return Depends(guard)


def _audit_actor(actor: ActorContext) -> AuditActor:
    return AuditActor(
        actor_type=actor.actor_type.value,
        actor_id=actor.actor_id,
        role_snapshot=tuple(sorted(actor.roles)),
        session_id=actor.session_id,
        authentication_assurance=actor.auth_level,
    )


def _parse_record_version(if_match: str | None) -> int:
    if if_match is None:
        raise PreconditionRequiredError("If-Match")
    cleaned = if_match.strip().strip('"')
    if not cleaned.startswith("rv-"):
        raise VersionConflictError()
    try:
        return int(cleaned.removeprefix("rv-"))
    except ValueError as exc:
        raise VersionConflictError() from exc


def _require_key(idempotency_key: str | None) -> str:
    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")
    return idempotency_key


def _owned_request(session: Any, request_id: uuid.UUID, actor: ActorContext) -> PaymentRequest:
    """The caller's own request, or a 404 that says nothing about which failure it was."""

    request = session.get(PaymentRequest, request_id)
    return require_owned(request, request.trader_id if request else None, actor)  # type: ignore[return-value]


def _rendered(
    publication: PaymentResultPublication, request: PaymentRequest
) -> TraderPublicationResponse:
    return TraderPublicationResponse(
        id=publication.id,
        payment_request_id=publication.payment_request_id,
        publication_version=publication.publication_version,
        status=publication.status,
        content_hash=publication.content_hash,
        summary_payload=dict(publication.summary_payload),
        published_at=publication.published_at,
        request_status=request.status,
        acknowledged_at=request.trader_acknowledged_at,
        disputed_at=request.trader_disputed_at,
    )


@router.get(
    "/payment-requests/{request_id}/publication",
    response_model=TraderPublicationResponse,
    operation_id="getOwnPaymentResultPublication",
    summary="The caller's own current published result for this request.",
    responses=RESPONSES,
    dependencies=[trader_only("payment_publication.read_own")],
)
def own_publication(
    request_id: uuid.UUID,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> TraderPublicationResponse:
    """`GET /api/v1/me/trader/payment-requests/{request_id}/publication`, per `:1913`.

    **Active only.** §20.3: "Trader endpoints expose only own active publication and allowed
    historical correction notices." The history is the centre's, and slice 7 decides what a
    correction notice says — a route that returned superseded versions today would be answering a
    question nobody has settled.
    """

    with runtime.uow_factory() as uow:
        session = uow.session
        request = _owned_request(session, request_id, actor)
        publication = session.scalar(
            select(PaymentResultPublication).where(
                PaymentResultPublication.payment_request_id == request.id,
                PaymentResultPublication.status == PUBLICATION_ACTIVE,
            )
        )
        if publication is None:
            uow.rollback()
            raise NotFoundError()
        response = _rendered(publication, request)
        uow.rollback()

    return response


@router.post(
    "/payment-requests/{request_id}/acknowledge-result",
    response_model=TraderPublicationResponse,
    operation_id="acknowledgeOwnPaymentResult",
    summary="Confirm to the centre that the published result is correct.",
    responses=RESPONSES,
    dependencies=[trader_only("payment_publication.acknowledge_own")],
)
def acknowledge_result(
    request_id: uuid.UUID,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TraderPublicationResponse:
    """`POST .../acknowledge-result`, per `:1921`. **No request body** — agreeing needs no fields.

    Both headers, which is `command_catalog.yaml`'s `idempotency: required` plus
    `current_publication_identity_revalidated`: the version is the request's, and a stale one means
    a correction replaced the result while the trader was reading it.
    """

    expected = _parse_record_version(if_match)
    key = _require_key(idempotency_key)
    now = utc_now()

    with runtime.uow_factory() as uow:
        _owned_request(uow.session, request_id, actor)
        result = trader_commands.acknowledge_result(
            trader_commands.AcknowledgeResult(
                payment_request_id=request_id, expected_record_version=expected
            ),
            uow=uow,
            policy=TRADER_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=key,
            now=now,
        )
        response = _rendered(result.publication, result.request)
        uow.commit()

    return response


@router.post(
    "/payment-requests/{request_id}/dispute-result",
    response_model=TraderPublicationResponse,
    operation_id="disputeOwnPaymentResult",
    summary="Tell the centre the published result is wrong, and why.",
    responses=RESPONSES,
    dependencies=[trader_only("payment_publication.dispute_own")],
)
def dispute_result(
    request_id: uuid.UUID,
    payload: DisputeRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TraderPublicationResponse:
    """`POST .../dispute-result`, per `:1942`.

    **This reverses nothing.** Doc 05 in its own words: "A dispute creates a visible manual review
    task and does not automatically reverse bank facts." The command imports no attempt model and
    performs no recalculation, and `SVC-DISPUTE-001` reads the financial rows back rather than
    trusting that.
    """

    expected = _parse_record_version(if_match)
    key = _require_key(idempotency_key)
    now = utc_now()

    with runtime.uow_factory() as uow:
        _owned_request(uow.session, request_id, actor)
        result = trader_commands.dispute_result(
            trader_commands.DisputeResult(
                payment_request_id=request_id,
                expected_record_version=expected,
                reason_code=payload.reason_code,
                description=payload.description,
            ),
            uow=uow,
            policy=TRADER_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=key,
            now=now,
        )
        response = _rendered(result.publication, result.request)
        uow.commit()

    return response


__all__ = ["router"]
