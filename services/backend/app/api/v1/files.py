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

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile, status
from pydantic import BaseModel, ConfigDict

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor, requires
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.core.errors import BusinessRuleViolationError, ErrorEnvelope
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.files import upload
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
