"""`POST /api/v1/files` — the first route that writes a byte to storage.

Multipart, per `05_API_Specification.md:976-997`. The response shape is `:1000-1012`
verbatim, and what is *absent* from it is the point: no `storage_key`, no
`storage_bucket`, no `storage_provider`. `command_catalog.yaml`'s global rules state
`raw_storage_keys_never_returned`, and `API-FILE-001` asserts it against the response
model's fields rather than against one example payload, so a field added later fails even
if no test happens to exercise that path.

The upload streams through `UploadFile.file`, Starlette's `SpooledTemporaryFile`. It is
handed to the command as a plain binary stream and the command never reads it into
memory: the size limit is enforced as the bytes go past, so an oversized upload is
abandoned rather than absorbed and then measured.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    Path,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor, requires
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.core.errors import BusinessRuleViolationError, ErrorEnvelope, NotFoundError
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.file_object import FileObject
from app.files import upload
from app.files.download import FileBytesUnavailableError, open_stream
from app.files.ownership import FileFacts, may_access
from app.files.preview import PreviewRaceLost, preview_page
from app.files.states import AVAILABLE
from app.security.actor import ActorContext
from app.security.permissions import declare

router = APIRouter(prefix="/files", tags=["files"])

IDEMPOTENCY_HEADER = "Idempotency-Key"
MAX_IDEMPOTENCY_KEY_LENGTH = 255

# POL-003 has not settled which roles see a full IBAN, and an audit row for an upload can
# carry a filename a person chose. Masking on, for the same reason the operations surface
# masks: a masked value can be widened by policy later, an unmasked one cannot be taken
# back.
UPLOAD_REDACTION = RedactionPolicy(mask_iban=True)


class UploadedFileResponse(BaseModel):
    """`05_API_Specification.md:1000-1012`.

    `extra="forbid"` is not cosmetic here: with it, adding a storage field to this model
    is the only way one could ever reach a client, and `API-FILE-001` reads these field
    names. Without it, a dict returned from somewhere else could carry one through.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    status: str
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str | None
    processing_job_id: uuid.UUID | None


@router.post(
    "",
    operation_id="uploadFile",
    status_code=status.HTTP_201_CREATED,
    response_model=UploadedFileResponse,
    dependencies=[requires(declare("file.upload"))],
    responses={
        400: {
            "model": ErrorEnvelope,
            "description": "The purpose, media type, size or idempotency key was refused.",
        },
        # Spread, not nested: `VALIDATION_ERROR_RESPONSE` is already keyed by 422.
        **VALIDATION_ERROR_RESPONSE,
    },
)
def upload_file(
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    file: Annotated[UploadFile, File()],
    purpose: Annotated[str, Form()],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
    client_filename: Annotated[str | None, Form()] = None,
) -> UploadedFileResponse:
    if not idempotency_key or len(idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise BusinessRuleViolationError(
            f"{IDEMPOTENCY_HEADER} is required and must not exceed "
            f"{MAX_IDEMPOTENCY_KEY_LENGTH} characters."
        )

    result = upload.execute(
        upload.UploadFile(
            purpose=purpose,
            # The client's name is metadata and nothing else. It never reaches a path:
            # `generate_storage_key` does not consult it.
            original_filename=client_filename or file.filename or "unnamed",
            declared_media_type=file.content_type or "application/octet-stream",
            stream=file.file,
        ),
        uow_factory=runtime.uow_factory,
        storage=runtime.storage,
        scan_policy=runtime.scan_policy,
        actor=AuditActor(
            actor_type=actor.actor_type.value,
            actor_id=actor.actor_id,
            # The roles and assurance the request actually carried, snapshotted now. A
            # later reader asking "was this person allowed to upload this" needs what was
            # true at the time, not what the account holds today.
            role_snapshot=tuple(sorted(actor.roles)),
            session_id=actor.session_id,
            authentication_assurance=actor.auth_level,
        ),
        context=AuditContext(request_id=get_request_id()),
        idempotency_key=idempotency_key,
        policy=UPLOAD_REDACTION,
        moment=utc_now(),
    )

    return UploadedFileResponse(
        id=result.file_id,
        status=result.status,
        original_filename=result.original_filename,
        mime_type=result.mime_type,
        size_bytes=result.size_bytes,
        sha256=result.sha256,
        processing_job_id=result.processing_job_id,
    )


class FileMetadataResponse(BaseModel):
    """`05_API_Specification.md:1022` — public metadata and allowed actions.

    No storage address, and `extra="forbid"` so adding one is the only way it could ever
    reach a client. `allowed_actions` is computed from this actor's authority rather than
    from the file alone: a client that renders a download button it will be refused is a
    client that teaches people the platform is broken.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    status: str
    purpose: str
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str | None
    allowed_actions: list[str]


def _facts(record: FileObject) -> FileFacts:
    return FileFacts(
        category=record.category,
        visibility_scope=record.visibility_scope,
        uploaded_by_actor_type=record.uploaded_by_actor_type,
        uploaded_by_actor_id=record.uploaded_by_actor_id,
    )


def _authorized_file(
    runtime: RuntimeServices, actor: ActorContext, file_id: uuid.UUID
) -> FileObject:
    """Load a file this actor is allowed to know exists, or refuse indistinguishably.

    **A file the actor may not reach is reported exactly as one that does not exist.**
    Two different answers would make the id space enumerable: a `403` tells the caller
    the id is real, which is the fact worth protecting when the id is the only secret.
    `15_Agent_Implementation_Plan.md:720` asks for this directly.

    The ownership decision is re-run on every request rather than cached with the session,
    because `12_Security_RBAC_Audit.md:1530` says every request re-evaluates — a grant
    revoked a second ago must not survive in a cached answer.
    """

    with runtime.uow_factory() as uow:
        record = uow.session.get(FileObject, file_id)
        if record is None or not may_access(actor, _facts(record)):
            raise NotFoundError()
        # Detached deliberately: the caller streams bytes afterwards, and a live session
        # held open across that is the long transaction this milestone keeps refusing.
        uow.session.expunge(record)
        return record


def _no_store(response: Response) -> None:
    """Headers every file-bearing response carries.

    `12_Security_RBAC_Audit.md:1555` forbids sensitive files in browser or service-worker
    caches. `attachment` stops a PDF or an SVG rendering in the origin's context, and
    `nosniff` stops a browser deciding for itself that a declared type was wrong.
    """

    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


@router.get(
    "/{file_id}",
    operation_id="getFileMetadata",
    response_model=FileMetadataResponse,
    dependencies=[requires(declare("file.read_metadata"))],
    responses={404: {"model": ErrorEnvelope}, **VALIDATION_ERROR_RESPONSE},
)
def get_file_metadata(
    file_id: uuid.UUID,
    response: Response,
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
) -> FileMetadataResponse:
    record = _authorized_file(runtime, actor, file_id)
    _no_store(response)

    # Only an available file offers anything. A quarantined one is still visible as
    # metadata so its uploader learns what happened, and offers no action at all.
    actions: list[str] = []
    if record.storage_status == AVAILABLE:
        if "file.download" in actor.permissions:
            actions.append("download")
        if "file.preview" in actor.permissions:
            actions.append("preview")

    return FileMetadataResponse(
        id=record.id,
        status=record.storage_status,
        purpose=record.category,
        original_filename=record.original_filename,
        mime_type=record.mime_type_declared,
        size_bytes=record.size_bytes,
        sha256=record.sha256_hash,
        allowed_actions=actions,
    )


def _stream(runtime: RuntimeServices, record: FileObject) -> StreamingResponse:
    """Serve the bytes, or refuse if the file is not usable.

    `12_Security_RBAC_Audit.md:1468` permits only `available` files to be used by normal
    business commands. A quarantined or pending file is refused to its own uploader too:
    the point of quarantine is that nobody uses the content, not that only strangers are
    kept away.
    """

    if record.storage_status != AVAILABLE:
        raise NotFoundError()

    # The route never sees a storage address. Slice 11's gate found this line reaching
    # into the backend with `record.storage_key`: the code was correct and the boundary
    # was not, and the next route to serve bytes would have copied it.
    try:
        stream = open_stream(runtime.storage, record)
    except FileBytesUnavailableError as error:
        # The row says the object exists and storage disagrees — the defect
        # `records_without_a_storage_object` exists to find. Not this request's to repair,
        # and not something to surface as an unhandled error either: the underlying
        # `StorageError` carries the key in its message.
        raise NotFoundError() from error

    return StreamingResponse(
        stream.chunks,
        media_type=stream.media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            # `attachment` rather than `inline`: an SVG or a PDF rendered in the origin's
            # context can execute against this origin's cookies. The filename is the
            # sanitised stored one, and it is display metadata even here.
            "Content-Disposition": f'attachment; filename="{stream.filename}"',
        },
    )


@router.get(
    "/{file_id}/download",
    operation_id="downloadFile",
    dependencies=[requires(declare("file.download"))],
    responses={404: {"model": ErrorEnvelope}, **VALIDATION_ERROR_RESPONSE},
    response_class=StreamingResponse,
)
def download_file(
    file_id: uuid.UUID,
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
) -> StreamingResponse:
    return _stream(runtime, _authorized_file(runtime, actor, file_id))


PREVIEW_RESPONSES: dict[int | str, dict[str, object]] = {
    400: {"model": ErrorEnvelope, "description": "No such page, or an unsupported rotation."},
    404: {"model": ErrorEnvelope},
    **VALIDATION_ERROR_RESPONSE,
}


@router.get(
    "/{file_id}/preview",
    operation_id="previewFile",
    dependencies=[requires(declare("file.preview"))],
    responses=PREVIEW_RESPONSES,
    response_class=Response,
)
def preview_file(
    file_id: uuid.UUID,
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    rotation_degrees: Annotated[int, Query(ge=0, le=270)] = 0,
) -> Response:
    """`05_API_Specification.md:1045`: preview is authorized separately from download.

    Separately, not more weakly. It carries its own permission, so holding one grant does
    not confer the other — `SEC-FILEDL-007` asserts both directions.

    **This served the original bytes until M8 slice 5**, with a note saying a later milestone would
    resolve it to a derived preview. It now does: page one, rendered, recorded as a
    `file_derivations` row. `SVC-PREVIEW-002` is what makes the change checkable — a preview that
    returns the source is a preview grant that acts as a download grant, which is exactly the
    separation `:1045` asks for and the placeholder quietly broke.
    """

    return _preview(runtime, actor, file_id, page_number=1, rotation_degrees=rotation_degrees)


@router.get(
    "/{file_id}/pages/{page_number}/preview",
    operation_id="previewFilePage",
    dependencies=[requires(declare("file.preview"))],
    responses=PREVIEW_RESPONSES,
    response_class=Response,
)
def preview_file_page(
    file_id: uuid.UUID,
    page_number: Annotated[int, Path(ge=1)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    rotation_degrees: Annotated[int, Query(ge=0, le=270)] = 0,
) -> Response:
    """`05_API_Specification.md:1042`, and doc 08 `:983`'s "PDF page navigation".

    **The rotation is a query parameter, not a stored preference.** doc 08 `:985` gives the operator
    a rotation control, and what they turn is their *view* — nothing about the file changes. Storing
    it would let one operator's straightening decide what the next one sees.

    **Zoom and pan are the client's**, and deliberately absent. They change no bytes: a viewer
    scales and translates an image it already holds, so serving them would mean rendering the same
    page at every zoom level and storing a derivation for each.
    """

    return _preview(
        runtime, actor, file_id, page_number=page_number, rotation_degrees=rotation_degrees
    )


def _preview(
    runtime: RuntimeServices,
    actor: ActorContext,
    file_id: uuid.UUID,
    *,
    page_number: int,
    rotation_degrees: int,
) -> Response:
    """Render or fetch one page image, and answer with the bytes plus its dimensions.

    **`Response`, not `StreamingResponse`.** A page image is one small object, already whole in
    memory by the time the renderer returns; wrapping it in a generator would add machinery around
    bytes that are already there. Downloads stream because a bundle PDF can be tens of megabytes.

    **The dimensions travel as headers**, which is `API-PREVIEW-001`: a client that must send
    `client_source_dimensions` (`05_API_Specification.md:1773`) cannot invent them, and it needs the
    raster *of this rotation* — the two numbers swap on a quarter turn. Headers rather than a JSON
    envelope because the body is the image, and wrapping it would make every viewer decode base64 to
    show a picture.
    """

    # Authorized first, by the same helper the download uses. `SEC-PREVIEW-001`'s "no preview URL is
    # guessable" is this call: a file the actor may not reach is reported exactly as one that does
    # not exist, so a page URL cannot be used to learn that an id is real.
    record = _authorized_file(runtime, actor, file_id)

    # **404, and the status matters more than the check.** `_previewable_source` refuses a
    # quarantined file with a 400 that names its state, which is right for a command and wrong for a
    # route: a 400 saying "file X is quarantined" confirms the id is real and leaks the verdict.
    # `_stream` has answered 404 here since M4 and this route lost it in a refactor —
    # `test_a_quarantined_file_is_not_downloadable_by_its_own_uploader` is what noticed.
    if record.storage_status != AVAILABLE:
        raise NotFoundError()

    try:
        return _rendered(runtime, record.id, page_number, rotation_degrees)
    except PreviewRaceLost:
        # Somebody else rendered this page between the cache miss and the write. That transaction is
        # already rolled back, so a second attempt finds their row — and the caller gets the picture
        # rather than an error about a race they did not cause.
        return _rendered(runtime, record.id, page_number, rotation_degrees)


def _rendered(
    runtime: RuntimeServices, file_id: uuid.UUID, page_number: int, rotation_degrees: int
) -> Response:
    with runtime.uow_factory() as uow:
        page = preview_page(
            file_id,
            page_number=page_number,
            rotation_degrees=rotation_degrees,
            uow=uow,
            storage=runtime.storage,
            now=utc_now(),
        )
        uow.commit()

    return Response(
        content=page.content,
        media_type=page.media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            # `attachment`, on the download route's reasoning: an image rendered in this origin's
            # context is still content this origin did not author.
            "Content-Disposition": f'attachment; filename="page-{page.page_number}.png"',
            # `API-PREVIEW-001`. The raster this image actually is, at this rotation.
            "X-Preview-Page-Number": str(page.page_number),
            "X-Preview-Pixel-Width": str(page.pixel_width),
            "X-Preview-Pixel-Height": str(page.pixel_height),
            "X-Preview-Rotation-Degrees": str(page.rotation_degrees),
            "X-Preview-Renderer-Version": page.renderer_version,
        },
    )
