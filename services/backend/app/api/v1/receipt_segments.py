"""The evidence surface. `05_API_Specification.md` §19.1 and §19.3.

M8 slice 2. Two routes, and the third one the plan expected is **deliberately absent**.

**No `PATCH /receipt-segments/{id}`.** `05_API_Specification.md:1792` defines it and
`permission_catalog.yaml` refuses it in terms:

    receipt_segment.update:
      status: unresolved_no_exact_canonical_target
      canonical_targets: []
      resolution: deny until an explicitly scoped pre-finalization update permission is approved

with `m0_open_items` carrying `receipt_segment_update_permission` and
`conservative_effect: deny_update_until_action-specific_permission_is_approved`, citing the same
document 05 lines. That is an **approved conservative decision**, not a gap — unlike slice 1's
three, which were silences. Building the route would break a rule M0 has taken, and building it
behind an uncatalogued permission would be worse: a mutation on evidence, authorised by a name
nobody approved. Q-9 records what has to be approved first.

`tests/backend/test_segment_surface.py` asserts the absence over the whole route table, because the
next person to read document 05 will find the endpoint and wonder where it went.

**The crop route is slice 4's** and needs Q-4 answered. `04_Database_Schema.md:1259` makes both
`manual_in_panel_crop` and `manual_external_attachment` Phase 1A; this slice ships the one that
renders nothing, which is also `15_Agent_Implementation_Plan.md:1077`'s required fallback for a
bundle nothing can render.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor, requires
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.commands import receipt_crop as crop_commands
from app.commands import receipt_segment as segment_commands
from app.core.errors import (
    BusinessRuleViolationError,
    ErrorEnvelope,
    NotFoundError,
    PreconditionRequiredError,
)
from app.core.money import parse_integer_string
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.receipt_segment import ReceiptSegment
from app.exports.crop import Rectangle
from app.security.actor import ActorContext
from app.security.permissions import declare

router = APIRouter(tags=["receipt-segments"])

SEGMENT_REDACTION = RedactionPolicy(mask_iban=True)

RESPONSES: dict[int | str, dict[str, object]] = {
    # M8 slice 4 adds this, and it was missing rather than inapplicable: every domain refusal on
    # this router is a `BusinessRuleViolationError`, which carries 400. The generated TypeScript
    # client is built from this document, so an undeclared status has no branch in the panel.
    400: {
        "model": ErrorEnvelope,
        "description": (
            "The rectangle, rotation, page or client dimensions cannot produce a reproducible crop."
        ),
    },
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "The caller lacks the segment permission."},
    404: {"model": ErrorEnvelope, "description": "No such bundle, file or segment."},
    409: {
        "model": ErrorEnvelope,
        "description": "The bundle is closed, or the file is not usable as evidence.",
    },
    **VALIDATION_ERROR_RESPONSE,
}


class ManualFieldsRequest(BaseModel):
    """What a person read off the receipt. `05_API_Specification.md:1740`.

    `amount_irr` is a **string**. `MONEY_TIME_CONTRACT.md:17` makes base-10 integer strings the wire
    format for monetary values and rule 9 forbids JavaScript `Number` for them; document 05's
    example at `:1744` shows an unquoted number, which is DOC-CONFLICT-050 — the same disagreement
    M5 settled the same way, with the contract winning on encoding.
    """

    model_config = ConfigDict(extra="forbid")

    beneficiary_name: str | None = Field(default=None, max_length=255)
    destination_iban: str | None = Field(default=None, min_length=26, max_length=26)
    amount_irr: str | None = Field(default=None, max_length=32)
    tracking_number: str | None = Field(default=None, max_length=128)
    payment_at: datetime | None = None


class AttachExternalRequest(BaseModel):
    """`05_API_Specification.md:1733`."""

    model_config = ConfigDict(extra="forbid")

    source_file_id: uuid.UUID
    bank_result_bundle_file_id: uuid.UUID | None = None
    page_number: int | None = Field(default=None, ge=1)
    # `| None` rather than a defaulted instance. A nested model with a default emits
    # `{"$ref": ..., "default": {...}}`, and the TypeScript generator refuses sibling keywords
    # beside a `$ref` — so the shape that reads most naturally in Python breaks the client build.
    # It is also the honester type: evidence attached with nothing typed in yet is a real case, and
    # `None` says so where an empty object pretends somebody filled a form.
    manual_fields: ManualFieldsRequest | None = None


class BoundingBoxRequest(BaseModel):
    """`05_API_Specification.md:1763`, with the four values as strings.

    **Strings, exactly as document 05 writes them** — `"0.105000"`, not `0.105`. The column is
    `NUMERIC(10,6)` and these four numbers have to reproduce a crop; a JSON float would arrive as a
    binary approximation of a decimal the database never held. The same reasoning
    `MONEY_TIME_CONTRACT.md` applies to money, applied to the other kind of value in this system
    where the exact digits are the point.
    """

    model_config = ConfigDict(extra="forbid")

    x: str = Field(max_length=12)
    y: str = Field(max_length=12)
    width: str = Field(max_length=12)
    height: str = Field(max_length=12)


class ClientDimensionsRequest(BaseModel):
    """`05_API_Specification.md:1770`. What the operator's screen was showing.

    Sent so the server can disagree. Coordinates normalised against one raster and applied to
    another describe a different region of the page while staying perfectly in range — the one
    error a bounds check cannot see.
    """

    model_config = ConfigDict(extra="forbid")

    width: int = Field(ge=1, le=100_000)
    height: int = Field(ge=1, le=100_000)


class CreateCropRequest(BaseModel):
    """`05_API_Specification.md:1759`, plus the rotation.

    **`rotation_degrees` is not in document 05's request body, and it is here.** DOC-CONFLICT-057
    argued for it; `command_catalog.yaml:277` settles it — the approved command row lists the
    preconditions of `receipt_segment.create_crop` as "normalized_rectangle, page, **rotation**,
    renderer_version, derived_checksum" and marks the row
    `status: blocked_by_coordinate_rotation_contract`. So M0 requires the angle and names its
    absence from this schema as the blocker. Accepting it is what unblocks the row rather than a
    liberty taken with the contract.

    Defaulted to 0 so an unrotated crop — the common case — sends what document 05 shows.
    """

    model_config = ConfigDict(extra="forbid")

    bank_result_bundle_file_id: uuid.UUID
    source_file_id: uuid.UUID
    page_number: int = Field(ge=1)
    bbox: BoundingBoxRequest
    client_source_dimensions: ClientDimensionsRequest
    rotation_degrees: int = 0
    manual_fields: ManualFieldsRequest | None = None


class SegmentDetail(BaseModel):
    """One piece of evidence, and everything needed to say where it came from.

    **The provenance fields are read-only for the whole life of the row** — no route writes them,
    and `20260824_0024` grants UPDATE on none of them. They are returned because reproduction is
    the point: a reader who cannot see the rectangle, the rotation and the source dimensions cannot
    check that the crop is what it claims to be.

    `rotation_degrees` is here because of DOC-CONFLICT-057. Document 05's own response shape does
    not list it; returning it is the same decision as storing it, for the same reason.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    bank_result_bundle_id: uuid.UUID | None
    bank_result_bundle_file_id: uuid.UUID | None
    source_file_id: uuid.UUID
    segment_file_id: uuid.UUID | None
    creation_method: str
    status: str
    page_number: int | None
    bbox_x: str | None
    bbox_y: str | None
    bbox_width: str | None
    bbox_height: str | None
    rotation_degrees: int
    source_pixel_width: int | None
    source_pixel_height: int | None
    renderer_version: str | None
    extracted_beneficiary_name: str | None
    extracted_destination_iban: str | None
    extracted_amount_irr: str | None
    extracted_tracking_number: str | None
    extracted_payment_at: datetime | None
    extraction_confidence: str | None
    created_by_actor_type: str
    record_version: int
    created_at: datetime
    updated_at: datetime


class CropAccepted(BaseModel):
    """`202`, and what the caller can do with it.

    Document 05 at `:1786`: "Crop generation may return `202` with a processing job." The segment
    comes back as well as the job, because the segment id is what the operator's panel needs in
    order to show a placeholder that later becomes a picture — and `segment_file_id` being null is
    the honest answer to "is it ready yet", which is why the whole detail is returned rather than a
    summary.

    Declared after `SegmentDetail` rather than beside its siblings: Pydantic resolves the nested
    model at class creation, so a forward reference here would need an explicit rebuild for no gain.
    """

    model_config = ConfigDict(extra="forbid")

    segment: SegmentDetail
    processing_job_id: uuid.UUID
    processing_job_status: str


def _normalized(value: str, field: str) -> Decimal:
    """One bbox string as the exact `Decimal` it spells.

    **`Decimal(str)` and never `float(str)`.** `Decimal("0.105000")` is the value the
    `NUMERIC(10,6)` column holds; `Decimal(float("0.105000"))` is
    `0.10500000000000000610622663543836...`, which reproduces a slightly different rectangle every
    time somebody re-renders from the row.

    Rejected rather than coerced when it is not a number: an unparseable coordinate is a client bug,
    and a silent 0 would crop the top-left corner of the page and call it evidence.
    """

    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise BusinessRuleViolationError(
            f"{field} must be a decimal number between 0 and 1; received {value!r}"
        ) from error
    if not parsed.is_finite():
        raise BusinessRuleViolationError(
            f"{field} must be a finite decimal; received {value!r}"
        )
    return parsed


def _decimal(value: Decimal | None) -> str | None:
    """A `NUMERIC` as its exact decimal string.

    Never a float. These four numbers have to reproduce a rectangle, and `str(Decimal)` preserves
    the stored scale where `float()` would introduce a representation the database never held —
    the same reasoning `MONEY_TIME_CONTRACT.md` applies to money, for the same kind of value.
    """

    return None if value is None else str(value)


def _detail(segment: ReceiptSegment) -> SegmentDetail:
    return SegmentDetail(
        id=segment.id,
        bank_result_bundle_id=segment.bank_result_bundle_id,
        bank_result_bundle_file_id=segment.bank_result_bundle_file_id,
        source_file_id=segment.source_file_id,
        segment_file_id=segment.segment_file_id,
        creation_method=segment.creation_method,
        status=segment.status,
        page_number=segment.page_number,
        bbox_x=_decimal(segment.bbox_x),
        bbox_y=_decimal(segment.bbox_y),
        bbox_width=_decimal(segment.bbox_width),
        bbox_height=_decimal(segment.bbox_height),
        rotation_degrees=segment.rotation_degrees,
        source_pixel_width=segment.source_pixel_width,
        source_pixel_height=segment.source_pixel_height,
        renderer_version=segment.renderer_version,
        extracted_beneficiary_name=segment.extracted_beneficiary_name,
        extracted_destination_iban=segment.extracted_destination_iban,
        # A string on the wire, for `ManualFieldsRequest`'s reason: an IRR amount above
        # `Number.MAX_SAFE_INTEGER` would be silently rounded by a browser before anybody saw it.
        extracted_amount_irr=(
            str(segment.extracted_amount_irr)
            if segment.extracted_amount_irr is not None
            else None
        ),
        extracted_tracking_number=segment.extracted_tracking_number,
        extracted_payment_at=segment.extracted_payment_at,
        extraction_confidence=_decimal(segment.extraction_confidence),
        created_by_actor_type=segment.created_by_actor_type,
        record_version=segment.record_version,
        created_at=segment.created_at,
        updated_at=segment.updated_at,
    )


def _audit_actor(actor: ActorContext) -> AuditActor:
    return AuditActor(
        actor_type=actor.actor_type.value,
        actor_id=actor.actor_id,
        role_snapshot=tuple(sorted(actor.roles)),
        session_id=actor.session_id,
        authentication_assurance=actor.auth_level,
    )


@router.post(
    "/bank-result-bundles/{bundle_id}/receipt-segments/external",
    response_model=SegmentDetail,
    status_code=201,
    operation_id="attachExternalEvidence",
    summary="Attach an already-uploaded file as evidence, whole.",
    responses=RESPONSES,
    dependencies=[requires(declare("receipt_segment.create_external"))],
)
def attach_external_evidence(
    bundle_id: uuid.UUID,
    payload: AttachExternalRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> SegmentDetail:
    """`POST /api/v1/bank-result-bundles/{bundle_id}/receipt-segments/external`. `:1733`.

    **No rectangle and no rotation.** §12.4's bbox CHECK has an all-null branch for exactly this
    method: the evidence is the whole file. A segment with no coordinates is a complete record here,
    not a partial one, and the `rotation_needs_a_rectangle` CHECK is what stops an angle being
    stored beside nothing.

    **`Idempotency-Key` required.** `:1734` shows one, and a retried attachment must not produce
    two segments claiming the same evidence — which would also double the bundle's segment count and
    put a bundle in the review queue for work that does not exist.
    """

    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")

    supplied = payload.manual_fields or ManualFieldsRequest()
    fields = segment_commands.ManualFields(
        beneficiary_name=supplied.beneficiary_name,
        destination_iban=supplied.destination_iban,
        amount_irr=(
            parse_integer_string(supplied.amount_irr, field="amount_irr")
            if supplied.amount_irr is not None
            else None
        ),
        tracking_number=supplied.tracking_number,
        payment_at=supplied.payment_at,
    )

    now = utc_now()
    with runtime.uow_factory() as uow:
        segment = segment_commands.attach_external(
            segment_commands.AttachExternalEvidence(
                bank_result_bundle_id=bundle_id,
                source_file_id=payload.source_file_id,
                fields=fields,
                bank_result_bundle_file_id=payload.bank_result_bundle_file_id,
                page_number=payload.page_number,
            ),
            uow=uow,
            policy=SEGMENT_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            now=now,
        )
        rendered = _detail(segment)
        uow.commit()

    return rendered


@router.post(
    "/bank-result-bundles/{bundle_id}/receipt-segments/crop",
    response_model=CropAccepted,
    # 202, not 201. The segment row exists when this returns and its image does not, so the honest
    # status is "accepted" — and `08_Bank_File_and_Result_Processing.md:1031` is explicit that the
    # request is saved, then rendered, then verified. A 201 would tell the caller a thing was
    # created that they cannot yet look at.
    status_code=202,
    operation_id="createReceiptCrop",
    summary="Cut a rectangle out of a bundle page as evidence.",
    responses=RESPONSES,
    dependencies=[requires(declare("receipt_segment.create_crop"))],
)
def create_receipt_crop(
    bundle_id: uuid.UUID,
    payload: CreateCropRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CropAccepted:
    """`POST /api/v1/bank-result-bundles/{bundle_id}/receipt-segments/crop`. §19.2 at `:1753`.

    **`Idempotency-Key` required, and `command_catalog.yaml:277` says so** — `idempotency:
    required`, not "recommended". A retried crop would otherwise produce a second segment claiming
    the same rectangle, a second render job, and a bundle whose segment count double-counts one
    piece of evidence.

    **The rectangle is parsed here and validated in the command.** Turning `"0.105000"` into a
    `Decimal` is transport; deciding whether the rectangle can be reproduced is a rule, and it
    belongs where the renderer can be asked the same question.
    """

    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")

    supplied = payload.manual_fields or ManualFieldsRequest()
    now = utc_now()
    with runtime.uow_factory() as uow:
        accepted = crop_commands.request_crop(
            crop_commands.RequestCrop(
                bank_result_bundle_id=bundle_id,
                bank_result_bundle_file_id=payload.bank_result_bundle_file_id,
                source_file_id=payload.source_file_id,
                page_number=payload.page_number,
                rectangle=Rectangle(
                    x=_normalized(payload.bbox.x, "bbox.x"),
                    y=_normalized(payload.bbox.y, "bbox.y"),
                    width=_normalized(payload.bbox.width, "bbox.width"),
                    height=_normalized(payload.bbox.height, "bbox.height"),
                ),
                rotation_degrees=payload.rotation_degrees,
                client_source_width=payload.client_source_dimensions.width,
                client_source_height=payload.client_source_dimensions.height,
                fields=segment_commands.ManualFields(
                    beneficiary_name=supplied.beneficiary_name,
                    destination_iban=supplied.destination_iban,
                    amount_irr=(
                        parse_integer_string(supplied.amount_irr, field="amount_irr")
                        if supplied.amount_irr is not None
                        else None
                    ),
                    tracking_number=supplied.tracking_number,
                    payment_at=supplied.payment_at,
                ),
            ),
            uow=uow,
            storage=runtime.storage,
            policy=SEGMENT_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            now=now,
        )
        rendered = CropAccepted(
            segment=_detail(accepted.segment),
            processing_job_id=accepted.job.id,
            processing_job_status=accepted.job.status,
        )
        uow.commit()

    return rendered


@router.get(
    "/receipt-segments/{segment_id}",
    response_model=SegmentDetail,
    operation_id="getReceiptSegment",
    summary="One piece of evidence, with the provenance that lets it be checked.",
    responses=RESPONSES,
    dependencies=[requires(declare("receipt_segment.read"))],
)
def get_receipt_segment(
    segment_id: uuid.UUID,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> SegmentDetail:
    """`GET /api/v1/receipt-segments/{segment_id}`. `05_API_Specification.md:1791`.

    `receipt_segment.read` goes to `accountant` and `manager`
    (`permission_catalog.yaml:540`), with `read_only_auditor` by explicit sensitive-read grant. A
    trader reaches none of it: this is the bank's account of the centre's payments, and
    `15_Agent_Implementation_Plan.md:1069` lists "trader cannot access bundle or internal segment"
    among the milestone's own tests.
    """

    del actor
    with runtime.uow_factory() as uow:
        segment = uow.session.get(ReceiptSegment, segment_id)
        if segment is None:
            raise NotFoundError()
        return _detail(segment)
