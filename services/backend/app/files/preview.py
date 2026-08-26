"""Page images for the review workspace. `08_Bank_File_and_Result_Processing.md` §15.2.

M8 slice 5, and mostly a connection rather than a construction. M4 built the preview *request* path
— `PREVIEWABLE_MEDIA_TYPES`, the outbox dispatch on upload, `GET /files/{id}/preview` — and left
that route serving the original bytes with a docstring saying a later milestone "resolves to one
when it does". Slice 4 brought the renderer. This is the resolution.

**Rendered on demand and cached as a derivation, not pre-rendered on upload.** A bundle can be forty
pages and an operator looks at three of them; rendering all forty at upload spends the work on
pages nobody opens. On demand is also the honest shape for the request: the operator is *waiting for
this page*, so there is nothing to do asynchronously — a job would only add a poll. What makes it
cheap the second time is `file_derivations`' own reproducibility unique
(`source_file_id, derivation_type, parameters_hash, renderer_version`), which turns "have I already
rendered this page at this angle with this renderer?" into one indexed lookup.

**So a GET writes.** Stated plainly rather than hidden, because it is the one thing here that will
surprise a reader: the preview route can insert a `file_objects` row and a `file_derivations` row.
It is a cache fill, it is idempotent, and the unique constraint is what makes it safe when two
operators open the same page at the same moment — the loser of that race reads the winner's row
instead of writing a second copy. `SVC-PREVIEW-002`'s "never the original" is the property that
matters and it holds either way.

**Nothing here trusts `mime_type_declared`.** The renderer sniffs the bytes, because that column
holds what the uploader said. A JPEG announced as a PDF is a mislabelled file, not a broken one.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from datetime import datetime

from PIL import Image
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.core.hashing import parameters_hash
from app.db.models.file_object import FileDerivation, FileObject
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.exports.crop import (
    CROP_MEDIA_TYPE,
    PERMITTED_ROTATIONS,
    RENDER_SCALE_TEXT,
    RENDERER_VERSION,
    CropRefused,
    page_count,
    page_size,
    render_page,
)
from app.files.derivation import PREVIEW, DerivationRequest, record_derivation
from app.files.download import open_stream
from app.files.states import AVAILABLE, SCAN_CLEAN
from app.storage.interface import StorageBackend


class PreviewRaceLost(Exception):
    """Two requests rendered one page at once and this one lost the unique.

    Its own type rather than a swallowed retry, because the caller owns the transaction: this one
    has to be rolled back before the winner's row can be read, and a function that cannot commit
    cannot make that decision for the caller.
    """

    def __init__(self, file_id: uuid.UUID, page_number: int, rotation_degrees: int) -> None:
        super().__init__(
            f"page {page_number} of file {file_id} at {rotation_degrees} degrees was rendered "
            "concurrently; read the stored derivation instead"
        )
        self.file_id = file_id
        self.page_number = page_number
        self.rotation_degrees = rotation_degrees


@dataclass(frozen=True, slots=True)
class PreviewPage:
    """One page image, and the dimensions a client needs before it can draw on it."""

    file_id: uuid.UUID
    page_number: int
    rotation_degrees: int
    content: bytes
    media_type: str
    pixel_width: int
    pixel_height: int
    renderer_version: str
    was_rendered: bool


@dataclass(frozen=True, slots=True)
class PageInformation:
    """`05_API_Specification.md:1680`'s "page information", for one file.

    Dimensions at rotation zero, because that is the raster a client normalises against before the
    operator touches the rotation control — and `API-PREVIEW-001` exists because a client that must
    send `client_source_dimensions` (`:1773`) cannot invent them.
    """

    file_id: uuid.UUID
    page_count: int
    pixel_width: int
    pixel_height: int


def preview_parameters(page_number: int, rotation_degrees: int) -> dict[str, object]:
    """What identifies one page image. The cache key, and the derivation's own record.

    Includes the scale even though it is a constant, because the derivation has to be reproducible
    from its own row after somebody changes that constant — the same reason slice 4's crop records
    it.
    """

    return {
        "page_number": page_number,
        "rotation_degrees": rotation_degrees,
        "render_scale": RENDER_SCALE_TEXT,
    }


def page_information(
    file_id: uuid.UUID, *, session: Session, storage: StorageBackend
) -> PageInformation:
    """How many pages this file has and how big page one is.

    **Counted from the bytes, never from a stored claim.** `bank_result_bundle_files.page_count` is
    supplied by the caller that attached the file (`05_API_Specification.md:1642`'s
    `AttachFileRequest`) and slice 1 had no renderer to check it with. Reading it back here would
    make `SVC-PREVIEW-001` — "page count matching `page_count`" — a comparison between the renderer
    and a number a client made up.
    """

    record = _previewable_source(session, file_id)
    document = _read(storage, record)
    try:
        pages = page_count(document)
        width, height = page_size(document, 1)
    except CropRefused as refused:
        raise BusinessRuleViolationError(str(refused)) from refused

    return PageInformation(
        file_id=record.id, page_count=pages, pixel_width=width, pixel_height=height
    )


def preview_page(
    file_id: uuid.UUID,
    *,
    page_number: int,
    rotation_degrees: int = 0,
    uow: SqlAlchemyUnitOfWork,
    storage: StorageBackend,
    now: datetime,
) -> PreviewPage:
    """The page image, from the cache when it is there and from the renderer when it is not."""

    session = uow.session
    if rotation_degrees not in PERMITTED_ROTATIONS:
        raise BusinessRuleViolationError(
            f"rotation must be one of {PERMITTED_ROTATIONS}; received {rotation_degrees}"
        )

    record = _previewable_source(session, file_id)
    parameters = preview_parameters(page_number, rotation_degrees)

    cached = _cached_derivation(session, record.id, parameters)
    if cached is not None:
        derived = session.get(FileObject, cached.derived_file_id)
        if derived is not None:
            content = _read(storage, derived)
            # **The image's own dimensions, not a stored copy of them.** Recording width and height
            # on the row would put the same fact in two places, and the copy is the one that can be
            # wrong. A PNG header is four bytes to read and cannot disagree with its own pixels.
            width, height = Image.open(io.BytesIO(content)).size
            return PreviewPage(
                file_id=record.id,
                page_number=page_number,
                rotation_degrees=rotation_degrees,
                content=content,
                media_type=derived.mime_type_declared,
                pixel_width=width,
                pixel_height=height,
                renderer_version=cached.renderer_version,
                was_rendered=False,
            )

    document = _read(storage, record)
    try:
        rendered = render_page(
            document, page_number=page_number, rotation_degrees=rotation_degrees
        )
    except CropRefused as refused:
        raise BusinessRuleViolationError(str(refused)) from refused

    try:
        record_derivation(
            DerivationRequest(
                source_file_id=record.id,
                derivation_type=PREVIEW,
                renderer_version=rendered.renderer_version,
                parameters=parameters,
                media_type=rendered.media_type,
                filename=f"{record.id}-page-{page_number}.png",
                body=io.BytesIO(rendered.content),
            ),
            uow=uow,
            storage=storage,
            moment=now,
        )
    except IntegrityError:
        # Another request rendered the same page while this one was working. The reproducibility
        # unique is what refused the second write, and reading the winner's row is the right
        # response: two identical page images in storage would be waste, not a conflict anybody
        # needs to hear about.
        session.rollback()
        raise PreviewRaceLost(file_id, page_number, rotation_degrees) from None

    return PreviewPage(
        file_id=record.id,
        page_number=page_number,
        rotation_degrees=rotation_degrees,
        content=rendered.content,
        media_type=rendered.media_type,
        pixel_width=rendered.crop_pixel_width,
        pixel_height=rendered.crop_pixel_height,
        renderer_version=rendered.renderer_version,
        was_rendered=True,
    )


def _cached_derivation(
    session: Session, source_file_id: uuid.UUID, parameters: dict[str, object]
) -> FileDerivation | None:
    """The stored page image for exactly these parameters, or nothing.

    Matched on `parameters_hash` rather than on the JSONB, which is the reason M4 stored a hash at
    all: two payloads differing only in key order are the same derivation, and a JSONB comparison
    would call them different and render the page twice.
    """

    return session.scalar(
        select(FileDerivation).where(
            FileDerivation.source_file_id == source_file_id,
            FileDerivation.derivation_type == PREVIEW,
            FileDerivation.parameters_hash == parameters_hash(parameters),
            FileDerivation.renderer_version == RENDERER_VERSION,
        )
    )


def _previewable_source(session: Session, file_id: uuid.UUID) -> FileObject:
    """A file this may be asked to render, or a refusal saying why not.

    The same two lifecycle conditions the crop command applies, for the same reason: an unscanned or
    quarantined file is one nobody may open, and a file that is not `available` is one storage may
    not have. Rendering a preview of quarantined content would put the renderer in front of bytes
    an inspection just refused — which is the reasoning M4 wrote against its own dispatch.
    """

    record = session.get(FileObject, file_id)
    if record is None:
        raise NotFoundError()
    if record.scan_status != SCAN_CLEAN:
        raise BusinessRuleViolationError(
            f"file {file_id} has scan status {record.scan_status!r}; only a file scanned clean can "
            "be previewed"
        )
    if record.storage_status != AVAILABLE:
        raise BusinessRuleViolationError(
            f"file {file_id} is {record.storage_status!r}; only an available file can be previewed"
        )
    return record


def _read(storage: StorageBackend, record: FileObject) -> bytes:
    """The bytes, through the file service. M4's boundary: no storage key outside this package."""

    return b"".join(open_stream(storage, record).chunks)


# Re-exported so a caller can name the media type without importing the renderer, which keeps
# `app/api/` free of a rendering import it has no other use for.
PREVIEW_MEDIA_TYPE = CROP_MEDIA_TYPE
