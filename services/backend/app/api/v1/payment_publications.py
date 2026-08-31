"""Preview and publish a payment result. `05_API_Specification.md` §20.1-20.2.

M9 slice 5. Two routes under the request, because document 05 puts them there
(`/payment-requests/{request_id}/publications/preview` and `.../publications`) rather than under a
publication prefix of their own — a publication does not exist until one of them creates it.

**Neither body carries a financial value.** §20.2: "The server derives amount, beneficiary,
attempts, status, bank, tracking, and dates from authoritative records. The client cannot submit
arbitrary financial summary values." The enforcement is the absence of the fields, which is the
third time this milestone has used it — slice 3 for the amount, slice 3B for the beneficiary, and
here for the whole snapshot. `SVC-PUBLICATION-003` asserts it over the models.

**`include_share_file` and `share_format` are absent too**, and that is not the same kind of
absence: §20.2 does show them. Slice 5B builds the renderer, and until it does, a flag a caller may
set that changes nothing would read as a working feature. Nothing to ask for, so nothing to
mislead.

**`manager` is the negative actor.** `20260801_0008:250-251` gives `payment_publication.preview`
and `.publish` to the accountant alone, so a manager holding every batch approval permission is
refused here — which proves the routes want *these* permissions rather than seniority.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor, requires
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.commands import payment_publication as publication_commands
from app.core.errors import (
    ErrorEnvelope,
    ForbiddenError,
    PreconditionRequiredError,
    VersionConflictError,
)
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.security.actor import ActorContext
from app.security.permissions import declare

router = APIRouter(prefix="/payment-requests", tags=["payment-publications"])

# The snapshot masks the beneficiary IBAN before it is stored, so nothing unmasked reaches this
# router. The policy is still explicit rather than defaulted: `RedactionPolicy` takes `mask_iban`
# per call site precisely so an open decision stays visible at every point that depends on it.
PUBLICATION_REDACTION = RedactionPolicy(mask_iban=True)

RESPONSES: dict[int | str, dict[str, object]] = {
    400: {"model": ErrorEnvelope, "description": "The request or its evidence is not publishable."},
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "The caller lacks the publication permission."},
    404: {"model": ErrorEnvelope, "description": "No such request or evidence link."},
    409: {"model": ErrorEnvelope, "description": "This request already says exactly this."},
    412: {"model": ErrorEnvelope, "description": "If-Match is stale or unreadable."},
    428: {"model": ErrorEnvelope, "description": "If-Match and Idempotency-Key are required."},
    **VALIDATION_ERROR_RESPONSE,
}


class PreviewRequest(BaseModel):
    """§20.1's body. The evidence to propose, and nothing else."""

    model_config = ConfigDict(extra="forbid")

    primary_evidence_link_id: uuid.UUID | None = None


class PublishRequest(BaseModel):
    """§20.2's body, minus the two share-file fields slice 5B owns."""

    model_config = ConfigDict(extra="forbid")

    primary_evidence_link_id: uuid.UUID | None = None
    message_to_trader: str | None = Field(default=None, max_length=4000)


class PublicationPreviewResponse(BaseModel):
    """What a publisher sees before committing. Persisted only as a request status change."""

    model_config = ConfigDict(extra="forbid")

    payment_request_id: uuid.UUID
    next_publication_version: int
    content_hash: str
    summary_payload: dict[str, Any]
    request_status: str


class PublicationResponse(BaseModel):
    """The created publication.

    `summary_payload` and the three columns beside it are returned together, which is what makes
    §17 `:1153`'s ten items complete for a reader while the hash still covers only the nine that
    are content. See `app/commands/payment_publication.py` for why the split exists.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    payment_request_id: uuid.UUID
    publication_version: int
    status: str
    content_hash: str
    summary_payload: dict[str, Any]
    primary_evidence_link_id: uuid.UUID | None
    # Always null in this slice. Declared anyway because §11.9 gives the column and a response
    # that omitted it would have to change shape when slice 5B fills it — which the oasdiff gate
    # would read as a breaking change to a contract that was merely incomplete.
    share_file_id: uuid.UUID | None
    published_at: datetime
    request_status: str


def _audit_actor(actor: ActorContext) -> AuditActor:
    return AuditActor(
        actor_type=actor.actor_type.value,
        actor_id=actor.actor_id,
        role_snapshot=tuple(sorted(actor.roles)),
        session_id=actor.session_id,
        authentication_assurance=actor.auth_level,
    )


def _publishing_admin(actor: ActorContext) -> uuid.UUID:
    """`published_by_admin_user_id` comes from the session, never from the body.

    §11.9 makes it NOT NULL and a trader is shown this row as proof. Taking it from a request
    field would let a client attribute a publication to somebody who never made one.
    """

    if actor.actor_id is None:
        raise ForbiddenError()
    return actor.actor_id


def _require_key(idempotency_key: str | None) -> str:
    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")
    return idempotency_key


def _parse_record_version(if_match: str | None) -> int:
    """`"rv-9"` -> `9`. The M5 shape, and a 412 for anything unreadable.

    412 rather than 400 because `api_error_catalog.yaml` gives 412 the meaning "If-Match value is
    stale", and a value this cannot read is a caller who cannot be told their precondition held.
    """

    if if_match is None:
        raise PreconditionRequiredError("If-Match")
    cleaned = if_match.strip().strip('"')
    if not cleaned.startswith("rv-"):
        raise VersionConflictError()
    try:
        return int(cleaned.removeprefix("rv-"))
    except ValueError as exc:
        raise VersionConflictError() from exc


@router.post(
    "/{request_id}/publications/preview",
    response_model=PublicationPreviewResponse,
    operation_id="previewPaymentResultPublication",
    summary="Show the exact trader-safe snapshot this request would publish.",
    responses=RESPONSES,
    dependencies=[requires(declare("payment_publication.preview"))],
)
def preview_payment_result_publication(
    request_id: uuid.UUID,
    payload: PreviewRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> PublicationPreviewResponse:
    """`POST /api/v1/payment-requests/{request_id}/publications/preview`, per `:1874`.

    **No `Idempotency-Key`.** `command_catalog.yaml` requires one for `payment_publication.publish`
    and has no row for the preview, and the preview creates nothing to replay — it validates a
    snapshot and moves the request to `result_ready_for_trader`, which running twice leaves where
    running once did.
    """

    with runtime.uow_factory() as uow:
        preview = publication_commands.preview_publication(
            publication_commands.PreviewPublication(
                payment_request_id=request_id,
                primary_evidence_link_id=payload.primary_evidence_link_id,
            ),
            uow=uow,
        )
        response = PublicationPreviewResponse(
            payment_request_id=preview.payment_request_id,
            next_publication_version=preview.next_publication_version,
            content_hash=preview.content_hash,
            summary_payload=preview.summary_payload,
            request_status=preview.request_status,
        )
        uow.commit()

    return response


@router.post(
    "/{request_id}/publications",
    response_model=PublicationResponse,
    status_code=201,
    operation_id="publishPaymentResult",
    summary="Create the immutable publication a trader is shown.",
    responses=RESPONSES,
    dependencies=[requires(declare("payment_publication.publish"))],
)
def publish_payment_result(
    request_id: uuid.UUID,
    payload: PublishRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> PublicationResponse:
    """`POST /api/v1/payment-requests/{request_id}/publications`, per `:1879`.

    **201, never 202.** Doc 05 allows 202 "if share-file generation is asynchronous"; nothing here
    is asynchronous because nothing here renders a file, so the row exists by the time this
    returns. Slice 5B is what may make 202 true, and it will be a deliberate change with the
    oasdiff gate to answer to.

    **`If-Match` against the request, not the publication.** The first draft of this route had
    none, reasoning that a publication has no prior version to be stale against — which is true and
    was the wrong question. `08_Bank_File_and_Result_Processing.md:1316` lists "idempotency key and
    expected version are valid" among §19.3's eight publication guards, and doc 05 shows the header
    at `:1885`. The version that can be stale is the **request's**: an accountant who read it at
    `rv-9`, went to make tea, and published while somebody else corrected the result would publish
    a snapshot of something that had moved.
    """

    expected = _parse_record_version(if_match)
    key = _require_key(idempotency_key)
    now = utc_now()

    with runtime.uow_factory() as uow:
        result = publication_commands.publish_result(
            publication_commands.PublishResult(
                payment_request_id=request_id,
                expected_record_version=expected,
                published_by_admin_user_id=_publishing_admin(actor),
                primary_evidence_link_id=payload.primary_evidence_link_id,
                message_to_trader=payload.message_to_trader,
            ),
            uow=uow,
            policy=PUBLICATION_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=key,
            now=now,
        )
        publication = result.publication
        response = PublicationResponse(
            id=publication.id,
            payment_request_id=publication.payment_request_id,
            publication_version=publication.publication_version,
            status=publication.status,
            content_hash=publication.content_hash,
            summary_payload=dict(publication.summary_payload),
            primary_evidence_link_id=publication.primary_evidence_link_id,
            share_file_id=publication.share_file_id,
            published_at=publication.published_at,
            request_status=result.request_status,
        )
        uow.commit()

    return response


__all__ = ["router"]
