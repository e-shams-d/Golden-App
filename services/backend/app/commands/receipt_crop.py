"""Turning a drawn rectangle into evidence. `15_Agent_Implementation_Plan.md` §16.4.

M8 slice 4, and the slice with the longest list of things it must not do.

**§16.4's ten requirements, and where each lives.** Worth writing out because `SVC-CROP-001`
asserts them one at a time, and a single "crop works" test passes with most of them removed:

1.  authorize source file and page — the route's permission, plus `_usable_source`
2.  validate file lifecycle state — `_usable_source`
3.  validate normalized rectangle and rotation — `app/exports/crop.py`, before any render
4.  create pending segment/job records — `request_crop`, one transaction
5.  process asynchronously when appropriate — `new_job` onto the `files` queue
6.  preserve source file — measured before and after in `render_pending_crop`
7.  create a derived file and checksum — `record_derivation`, storage's own digest
8.  record renderer/version/source dimensions — `request_crop` writes them, the worker confirms
    them; slice 2 granted the runtime no UPDATE on any of the three, so provenance is recorded once
9.  be idempotent — one job per segment here, `Idempotency-Key` at the route
10. create audit/outbox records — `AUD-CROP-001`

**§16.5's three prohibitions are absences of code, not of calls.** Crop creation must not confirm
evidence, mark an attempt paid, or publish to a trader. This module imports nothing that could:
no `evidence_link`, no `payment_attempt`, no publication. `SVC-CROP-002` asserts that over the
module's imports rather than over a test run, because an import added later is findable and a
behaviour never exercised is not.

**Almost nothing here is new machinery.** M4 built `app/files/derivation.py` for this slice — its
own test says a preview "is rendered in M8, and when the renderer arrives it will record its output
through `record_derivation`". That is this. So the derived `file_objects` row, the
`file_derivations` row, the versioned `parameters_hash` and the inheritance of category and
visibility from the source are all M4's decisions, reused rather than re-made. `new_job` is M2's.
What slice 4 adds is the renderer, the segment, and the first row ever written to
`file_derivations.created_by_job_id`.

**The segment exists before its file**, which is `08_Bank_File_and_Result_Processing.md:1031`'s
workflow: save segment request → worker renders → verify checksum → available. So `request_crop`
writes a row with `segment_file_id` NULL plus a job, and `render_pending_crop` fills it. Q-2 records
why the segment stays in `created` throughout and the *job* carries progress: `processing` is not a
canonical segment state.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import CREATE_RECEIPT_CROP
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.commands.receipt_segment import ManualFields
from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.db.claiming import new_job
from app.db.models.bank_result_bundle import BUNDLE_CLOSED, BankResultBundle, BankResultBundleFile
from app.db.models.file_object import CLEAN_SCAN_STATUS, FileObject
from app.db.models.processing_job import ProcessingJob
from app.db.models.receipt_segment import METHOD_CROP, SEGMENT_CREATED, ReceiptSegment
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.exports.crop import (
    CROP_MEDIA_TYPE,
    PERMITTED_ROTATIONS,
    RENDER_SCALE_TEXT,
    RENDERER_NAME,
    RENDERER_VERSION,
    CropRefused,
    Rectangle,
    page_count,
    page_size,
    render_crop,
)
from app.files.derivation import CROP, DerivationRequest, record_derivation
from app.files.download import measure_now, open_stream
from app.files.states import AVAILABLE
from app.storage.interface import StorageBackend

METADATA_SCHEMA = "audit.receipt_segment"
METADATA_VERSION = 1

# `app/workers/tasks/files.py`'s first task. That module has existed since M2 holding nothing but a
# docstring explaining that it exists so the first file task routes to the `files` queue instead of
# landing silently on `maintenance`. This is the first task it routes.
CROP_JOB_TYPE = "receipt_segment.render_crop"
CROP_QUEUE = "files"


@dataclass(frozen=True, slots=True)
class RequestCrop:
    """`05_API_Specification.md:1756`, plus the rotation DOC-CONFLICT-057 argued for.

    The rotation is not an invention of this slice. `command_catalog.yaml:277` lists the
    preconditions of `receipt_segment.create_crop` as "normalized_rectangle, page, **rotation**,
    renderer_version, derived_checksum" and marks the row
    `status: blocked_by_coordinate_rotation_contract`. So M0's own catalogue requires the angle and
    names its absence from the request schema as the blocker — which settles DOC-CONFLICT-057 in
    favour of accepting it, rather than leaving it to this slice's judgement.
    """

    bank_result_bundle_id: uuid.UUID
    bank_result_bundle_file_id: uuid.UUID
    source_file_id: uuid.UUID
    page_number: int
    rectangle: Rectangle
    rotation_degrees: int
    client_source_width: int
    client_source_height: int
    # `05_API_Specification.md:1779` carries these on the crop request too. Slice 2's type, not a
    # second one: the same five values read off the same kind of receipt, and two dataclasses would
    # drift the moment one of them gained a field.
    fields: ManualFields = field(default_factory=ManualFields)


@dataclass(frozen=True, slots=True)
class CropRequested:
    segment: ReceiptSegment
    job: ProcessingJob


def request_crop(
    command: RequestCrop,
    *,
    uow: SqlAlchemyUnitOfWork,
    storage: StorageBackend,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> CropRequested:
    """§16.4's requirements 1 to 5, 9 and 10. One transaction, no rendering.

    **Everything is validated before anything is written**, because the alternative is a pending
    segment nobody can render and a job that fails forever. The rectangle and the angle go through
    `app/exports/crop.py`, the same code the renderer uses, so the check and the render cannot
    disagree about what is acceptable.

    **The client's reported raster is checked against the page's real one.**
    `05_API_Specification.md:1773` has the caller send `client_source_dimensions`, and the only
    reason to send them is so the server can notice a disagreement: coordinates normalised against a
    different raster than the server will render describe a different region of the page. This is
    the one validation §16.4 does not name and the rectangle alone cannot catch — a rectangle can be
    perfectly in-range against the wrong raster.
    """

    session = uow.session

    bundle = session.get(BankResultBundle, command.bank_result_bundle_id)
    if bundle is None:
        raise NotFoundError()
    if bundle.status == BUNDLE_CLOSED:
        raise BusinessRuleViolationError(
            f"bundle {bundle.bundle_number} is closed and accepts no new evidence"
        )

    membership = session.get(BankResultBundleFile, command.bank_result_bundle_file_id)
    if membership is None:
        raise NotFoundError()
    if membership.bank_result_bundle_id != bundle.id:
        raise BusinessRuleViolationError("the bundle file named belongs to a different bundle")
    if membership.file_id != command.source_file_id:
        raise BusinessRuleViolationError(
            "the bundle file named does not hold the source file named"
        )

    source = _usable_source(session, command.source_file_id)

    if command.rotation_degrees not in PERMITTED_ROTATIONS:
        raise BusinessRuleViolationError(
            f"rotation must be one of {PERMITTED_ROTATIONS}; received {command.rotation_degrees}"
        )
    try:
        command.rectangle.validate()
    except CropRefused as refused:
        raise BusinessRuleViolationError(str(refused)) from refused

    document = _read(storage, source)
    if command.page_number < 1 or command.page_number > page_count(document):
        raise BusinessRuleViolationError(
            f"page {command.page_number} does not exist in this document"
        )

    raster = _rotated_page_size(document, command.page_number, command.rotation_degrees)
    if (command.client_source_width, command.client_source_height) != raster:
        raise BusinessRuleViolationError(
            f"the rectangle was drawn against a {command.client_source_width}x"
            f"{command.client_source_height} raster and this page renders at {raster[0]}x"
            f"{raster[1]} at {command.rotation_degrees} degrees; the same coordinates would "
            "describe a different region"
        )

    segment = ReceiptSegment(
        bank_result_bundle_id=bundle.id,
        bank_result_bundle_file_id=membership.id,
        source_file_id=source.id,
        # NULL until the worker renders. `15_Agent_Implementation_Plan.md:1069`'s "a failed render
        # leaves no active evidence" is exactly this column staying NULL.
        segment_file_id=None,
        page_number=command.page_number,
        bbox_x=command.rectangle.x,
        bbox_y=command.rectangle.y,
        bbox_width=command.rectangle.width,
        bbox_height=command.rectangle.height,
        rotation_degrees=command.rotation_degrees,
        source_pixel_width=raster[0],
        source_pixel_height=raster[1],
        renderer_version=RENDERER_VERSION,
        creation_method=METHOD_CROP,
        status=SEGMENT_CREATED,
        extracted_beneficiary_name=command.fields.beneficiary_name,
        extracted_destination_iban=command.fields.destination_iban,
        extracted_amount_irr=command.fields.amount_irr,
        extracted_tracking_number=command.fields.tracking_number,
        extracted_payment_at=command.fields.payment_at,
        # No confidence. §12.4 keeps `extraction_confidence` for a machine's guess, and a human who
        # read a number off a receipt did not produce a probability. Slice 6's AI path is what fills
        # it — leaving it NULL here is the difference between "a person typed this" and "something
        # was 90% sure".
        created_by_actor_type=actor.actor_type,
        created_by_actor_id=actor.actor_id,
    )
    session.add(segment)
    uow.flush()

    job = new_job(
        job_type=CROP_JOB_TYPE,
        queue_name=CROP_QUEUE,
        input_payload={
            "receipt_segment_id": str(segment.id),
            "page_number": command.page_number,
            "rotation_degrees": command.rotation_degrees,
            # The same spelling the derivation records, so a reader comparing the job's payload with
            # the derivation's parameters is comparing like with like.
            "render_scale": RENDER_SCALE_TEXT,
        },
        # One job per segment. §16.4's ninth requirement covers a retried *request* through the
        # route's `Idempotency-Key`; this covers a retried *enqueue*, which is a different event.
        idempotency_key=f"{CROP_JOB_TYPE}:{segment.id}",
        entity_type="receipt_segment",
        entity_id=segment.id,
    )
    # Not parameters of `new_job`, because most jobs have no external provider. A crop does: the
    # renderer is what makes the output reproducible, and the job is what an operator looks at when
    # a crop fails.
    job.provider = RENDERER_NAME
    job.provider_version = RENDERER_VERSION
    session.add(job)
    uow.flush()

    AuditWriter(session, policy).record(
        AuditEntry(
            action=CREATE_RECEIPT_CROP.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="receipt_segment",
            entity_id=segment.id,
            entity_record_version=segment.record_version,
            previous_values=None,
            new_values={
                "creation_method": segment.creation_method,
                "status": segment.status,
                "page_number": segment.page_number,
                "rotation_degrees": segment.rotation_degrees,
                # Decimal strings, so the audit row alone can reproduce the crop.
                "bbox": [
                    str(command.rectangle.x),
                    str(command.rectangle.y),
                    str(command.rectangle.width),
                    str(command.rectangle.height),
                ],
                "renderer_version": segment.renderer_version,
                "processing_job_id": str(job.id),
            },
            reason="manual in-panel crop requested",
            occurred_at=now,
            metadata={"operation": CREATE_RECEIPT_CROP.audit_action},
        ),
        actor=actor,
        context=context,
    )
    return CropRequested(segment=segment, job=job)


def render_pending_crop(
    segment_id: uuid.UUID,
    *,
    uow: SqlAlchemyUnitOfWork,
    storage: StorageBackend,
    now: datetime,
    job_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """§16.4's requirements 6, 7 and 8. The worker's half, returning the derived file's id.

    **The source file is not modified, and that is measured rather than asserted.** Requirement 6
    is "preserve source file"; the digest is taken before the render and again after the derivation,
    because the only honest way to claim a file is unchanged is to look at it twice.

    **The derived file's digest is storage's**, not one computed here. §1 of the baseline forbids a
    placeholder hash, and `record_derivation` already reads the digest off the write — so a
    truncated write cannot produce a row that agrees with itself.

    **A failure leaves `segment_file_id` NULL** and the segment in `created`. Nothing here sets a
    failure status on the segment: the job carries the failure, which is what
    `15_Agent_Implementation_Plan.md:1069` means by a failed render leaving no active evidence.
    """

    session = uow.session
    segment = session.get(ReceiptSegment, segment_id)
    if segment is None:
        raise NotFoundError()
    if segment.creation_method != METHOD_CROP:
        raise BusinessRuleViolationError(
            f"segment {segment_id} was created by {segment.creation_method!r}; only a crop is "
            "rendered from a rectangle"
        )
    if segment.segment_file_id is not None:
        # Already rendered. §16.4's ninth requirement at the worker: a redelivered message must not
        # produce a second file, and returning the existing one is what makes a retry harmless.
        return segment.segment_file_id

    source = _usable_source(session, segment.source_file_id)
    before = measure_now(storage, source)

    document = _read(storage, source)
    rendered = render_crop(
        document,
        page_number=segment.page_number or 1,
        rectangle=Rectangle(
            x=_required(segment.bbox_x, "bbox_x"),
            y=_required(segment.bbox_y, "bbox_y"),
            width=_required(segment.bbox_width, "bbox_width"),
            height=_required(segment.bbox_height, "bbox_height"),
        ),
        # From the row, not from the job payload. `SVC-CROP-004`'s claim is that the stored
        # provenance alone reproduces the crop, and reading the angle from anywhere else would make
        # that claim untestable.
        rotation_degrees=segment.rotation_degrees,
    )

    # **Requirement 8 is checked here, not written here.** `20260824_0024` grants the runtime no
    # UPDATE on `renderer_version`, `source_pixel_width` or `source_pixel_height` — slice 2 froze
    # them because provenance that can be rewritten describes nothing. So `request_crop` recorded
    # them and this confirms the render agrees.
    #
    # It is a real check rather than a formality. A deploy between the request and the render leaves
    # a row claiming one renderer and a file produced by another, and the honest response is to
    # refuse: the operator re-requests the crop and gets one whose provenance describes it. Writing
    # the file anyway would produce exactly the artifact `SVC-CROP-004` exists to rule out.
    if segment.renderer_version != rendered.renderer_version:
        raise BusinessRuleViolationError(
            f"segment {segment_id} was drawn against {segment.renderer_version!r} and this worker "
            f"renders with {rendered.renderer_version!r}; the crop would not match its own "
            "provenance, so it must be requested again"
        )
    recorded_raster = (segment.source_pixel_width, segment.source_pixel_height)
    if recorded_raster != (rendered.source_pixel_width, rendered.source_pixel_height):
        raise BusinessRuleViolationError(
            f"segment {segment_id} records a {recorded_raster[0]}x{recorded_raster[1]} raster and "
            f"the page rendered at {rendered.source_pixel_width}x{rendered.source_pixel_height}; "
            "the stored rectangle does not describe this image"
        )

    # `08_...Processing.md:431`'s five: source file, operation type, parameters, renderer version,
    # checksums. All of it through M4's helper, so a crop cannot exist without a row accounting
    # for it.
    result = record_derivation(
        DerivationRequest(
            source_file_id=source.id,
            derivation_type=CROP,
            renderer_version=rendered.renderer_version,
            parameters={
                "page_number": segment.page_number,
                "rotation_degrees": segment.rotation_degrees,
                # A string, because `parameters_hash` refuses a float and is right to: a digest that
                # depended on how this platform formats 2.0 would call two identical derivations
                # different. Found by the hasher on this slice's first integration run.
                "render_scale": RENDER_SCALE_TEXT,
                "bbox_x": str(segment.bbox_x),
                "bbox_y": str(segment.bbox_y),
                "bbox_width": str(segment.bbox_width),
                "bbox_height": str(segment.bbox_height),
            },
            media_type=CROP_MEDIA_TYPE,
            filename=f"segment-{segment.id}.png",
            body=io.BytesIO(rendered.content),
            created_by_job_id=job_id,
        ),
        uow=uow,
        storage=storage,
        moment=now,
    )

    after = measure_now(storage, source)
    if before != after:
        # Requirement 6, and it fails loudly rather than being trusted. A source that changed while
        # its own crop was being taken makes the crop evidence of something that no longer exists.
        raise BusinessRuleViolationError(
            f"file {source.id} changed while its crop was being rendered; the crop cannot be "
            "evidence of a document that no longer matches it"
        )

    # The only column this function writes on the segment, and the only one it has a grant for.
    # Everything else about the crop was decided when the operator drew the rectangle.
    segment.segment_file_id = result.derived_file_id
    segment.record_version += 1
    uow.flush()

    return result.derived_file_id


def pending_crops(session: Session) -> list[uuid.UUID]:
    """Crop segments with no file yet, oldest first. The worker's work list."""

    return list(
        session.scalars(
            select(ReceiptSegment.id)
            .where(
                ReceiptSegment.creation_method == METHOD_CROP,
                ReceiptSegment.segment_file_id.is_(None),
            )
            .order_by(ReceiptSegment.created_at)
        ).all()
    )


def _usable_source(session: Session, file_id: uuid.UUID) -> FileObject:
    """§16.4's second requirement: validate the file's lifecycle state.

    Two conditions and both matter. An unscanned or quarantined file is one nobody may open; a file
    that is not `available` is one storage may not have. `SVC-CROP-006` is this function.
    """

    source = session.get(FileObject, file_id)
    if source is None:
        raise NotFoundError()
    if source.scan_status != CLEAN_SCAN_STATUS:
        raise BusinessRuleViolationError(
            f"file {file_id} has scan status {source.scan_status!r}; a crop may only be taken from "
            "a file scanned clean"
        )
    if source.storage_status != AVAILABLE:
        raise BusinessRuleViolationError(
            f"file {file_id} is {source.storage_status!r}; only an available file can be cropped"
        )
    return source


def _read(storage: StorageBackend, record: FileObject) -> bytes:
    """The source bytes, through the file service rather than around it.

    `open_stream` and not `storage.open(record.storage_key)`: M4's boundary obligation forbids any
    module outside `app/storage/` and `app/files/` from handling a storage key, because ADR-003 has
    not chosen a production adapter and a change of provider must touch one place.
    """

    return b"".join(open_stream(storage, record).chunks)


def _rotated_page_size(document: bytes, page_number: int, rotation: int) -> tuple[int, int]:
    """The raster the operator was looking at, which depends on the angle.

    A thin wrapper kept for the name: `page_size` handles the rotation itself, and it is worth
    reading here that the angle is part of the question, not an afterthought. A page rotated a
    quarter turn is 800x600 where it was 600x800, so ignoring the angle would reject every rotated
    crop for disagreeing with a raster nobody would have rendered.
    """

    return page_size(document, page_number, rotation=rotation)


def _required(value: Decimal | None, name: str) -> Decimal:
    if value is None:
        raise BusinessRuleViolationError(
            f"segment has no {name}; a crop cannot be rendered without its rectangle"
        )
    return value
