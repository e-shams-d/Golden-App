"""Upload a private file: three short transactions, and never one long one.

`15_Agent_Implementation_Plan.md:691` requires "streaming upload without holding a long
database transaction", and that requirement is the whole shape of this module. A file is
as large as the purpose's limit allows, the network is as slow as the client is, and a
transaction held open for the duration pins a connection and a snapshot for as long as
somebody's phone takes to send a photograph.

So:

    1. INITIATE   claim idempotency, generate the storage key, insert the row as
                  `pending` with no checksum. Commit.
    2. STREAM     write the bytes through the storage backend, outside any transaction,
                  enforcing the size limit *during* the stream rather than after it.
    3. FINALIZE   record the measured size and digest, set the resulting state, write the
                  audit row, complete the idempotency claim. Commit.

**The row is written before the bytes, deliberately.** A crash between 1 and 2 leaves a
`pending` row with no object, which `stale_pending_uploads` already detects and which
carries who was uploading and why. Bytes-first would leave an orphan blob —
`storage_objects_without_a_record` detects that too, but a blob carries nothing, so the
operator learns that something was uploaded and nothing about what or by whom.

**Every upload lands in `quarantined`.** No scan policy exists yet: ADR-008 is open and
slice 4 introduces the port. Until then the honest answer to "has this been scanned" is
no, and `available_requires_clean_scan` — a whitelist of the single value `clean` —
turns that answer into a refusal at the database whether or not application code
remembers to. This is DOC-CONFLICT-029's fail-closed rule, and it is a state this slice
produces on purpose rather than a gap in it.

**Idempotency is keyed on the caller's header, never on the checksum** (DOC-CONFLICT-046).
Two people legitimately uploading the same document are two pieces of evidence with two
owners; deduplicating on content would attach one trader's file to another's request. The
digest is recorded and indexed as a duplicate *indicator*, which is what
`12_Security_RBAC_Audit.md:1506` asks for, and it never merges rows.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO

from app.audit import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.audit.redaction import RedactionPolicy
from app.audit.registry import UPLOAD_FILE
from app.core.errors import BusinessRuleViolationError
from app.db.models.file_object import FileObject
from app.db.models.idempotency_record import IdempotencyRecord
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.files.purposes import UnknownFilePurposeError, resolve
from app.idempotency import IdempotencyResolver, key_hash
from app.idempotency.resolver import IdempotencyClaim
from app.storage.interface import StorageBackend
from app.storage.keys import generate_storage_key

OPERATION = "file.upload"

METADATA_SCHEMA = "audit.file.upload"
METADATA_VERSION = 1

MAX_FILENAME_LENGTH = 255

# What a file lands in until slice 4 gives the finalize step a scan policy to consult.
# Named rather than inlined so that slice 4 changes one place and the reason travels with
# the value.
UNSCANNED_STORAGE_STATUS = "quarantined"
UNSCANNED_SCAN_STATUS = "pending"

# `file_objects.storage_provider` / `.storage_bucket`. ADR-003 has not chosen the
# production adapter, so the triple records what actually wrote the bytes rather than
# assuming a filesystem.
LOCAL_PROVIDER = "local"
DEFAULT_BUCKET = "private"


class FileTooLargeError(BusinessRuleViolationError):
    """The stream exceeded the purpose's limit. Raised mid-stream, not after it."""


class _LimitedReader:
    """A read-through wrapper that refuses past a byte ceiling.

    The limit is enforced here rather than by checking `Content-Length`, because a
    declared length is a claim by the client and the bytes are the fact. Checking after
    the write would mean the oversized object had already been written to storage and
    then had to be deleted — a delete this milestone has no business performing, and a
    window in which the disk holds something nothing accounts for.

    `StorageBackend.write` unlinks its partial file on any exception, so raising from
    `read` leaves no object behind. `FILE-UP-005` asserts that rather than assuming it.
    """

    def __init__(self, source: BinaryIO, *, limit: int, purpose: str) -> None:
        self._source = source
        self._limit = limit
        self._purpose = purpose
        self._seen = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._source.read(size)
        if not chunk:
            return chunk
        self._seen += len(chunk)
        if self._seen > self._limit:
            raise FileTooLargeError(
                f"An upload for {self._purpose!r} may not exceed {self._limit} bytes."
            )
        return chunk


@dataclass(frozen=True)
class UploadFile:
    """What the caller asked for, already parsed and bounded."""

    purpose: str
    original_filename: str
    declared_media_type: str
    stream: BinaryIO


@dataclass(frozen=True)
class UploadResult:
    file_id: uuid.UUID
    status: str
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str | None
    processing_job_id: uuid.UUID | None
    replayed: bool


def sanitise_filename(raw: str) -> str:
    """Strip everything a filename could do besides be displayed.

    The result never reaches a path — `generate_storage_key` does not consult it — so
    this is not a traversal defence. It is a display and storage bound: control
    characters, embedded separators and unbounded length in a value that will be rendered
    in a browser and written to a `VARCHAR(255)` column.
    """

    collapsed = raw.replace("\\", "/").split("/")[-1]
    cleaned = "".join(character for character in collapsed if character.isprintable()).strip()
    if not cleaned:
        cleaned = "unnamed"
    return cleaned[:MAX_FILENAME_LENGTH]


def _validate(command: UploadFile) -> None:
    try:
        purpose = resolve(command.purpose)
    except UnknownFilePurposeError as error:
        raise BusinessRuleViolationError(str(error)) from error

    if command.declared_media_type not in purpose.accepted_media_types:
        raise BusinessRuleViolationError(
            f"{command.declared_media_type!r} is not accepted for {command.purpose!r}. "
            f"Accepted: {', '.join(sorted(purpose.accepted_media_types))}."
        )


def execute(
    command: UploadFile,
    *,
    uow_factory: Callable[[], SqlAlchemyUnitOfWork],
    storage: StorageBackend,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    policy: RedactionPolicy,
    moment: datetime,
) -> UploadResult:
    """Run the upload, or return what the first identical request produced.

    A **factory**, not a unit of work: `SqlAlchemyUnitOfWork` refuses to be re-entered,
    which is the codebase saying that one instance means one transaction. This command
    needs two, with the streaming step between them and no transaction open at all —
    which `FILE-UP-002` asserts by instrumenting the connection rather than by reading
    this docstring.
    """

    _validate(command)
    purpose = resolve(command.purpose)
    filename = sanitise_filename(command.original_filename)

    # ---- 1. Initiate ------------------------------------------------------------
    with uow_factory() as uow:
        resolver = IdempotencyResolver(uow)
        claim = resolver.claim(
            actor_type=actor.actor_type,
            actor_id=actor.idempotency_scope_id,
            operation=OPERATION,
            idempotency_key=idempotency_key,
            payload={
                "purpose": command.purpose,
                "original_filename": filename,
                "declared_media_type": command.declared_media_type,
            },
        )

        if claim.is_replay:
            stored = claim.record.response_body or {}
            return UploadResult(
                file_id=uuid.UUID(str(stored["id"])),
                status=str(stored["status"]),
                original_filename=str(stored["original_filename"]),
                mime_type=str(stored["mime_type"]),
                size_bytes=int(stored["size_bytes"]),
                sha256=stored.get("sha256"),
                processing_job_id=None,
                replayed=True,
            )

        claim_id = claim.record.id
        storage_key = generate_storage_key(category=command.purpose, moment=moment)
        record = FileObject(
            storage_provider=LOCAL_PROVIDER,
            storage_bucket=DEFAULT_BUCKET,
            storage_key=storage_key,
            original_filename=filename,
            mime_type_declared=command.declared_media_type,
            mime_type_detected=None,
            size_bytes=0,
            sha256_hash=None,
            category=command.purpose,
            visibility_scope=purpose.visibility_scope,
            storage_status="pending",
            scan_status=UNSCANNED_SCAN_STATUS,
            uploaded_by_actor_type=actor.actor_type,
            uploaded_by_actor_id=actor.actor_id,
            original_or_derived_relation="original",
            metadata_payload={},
        )
        uow.session.add(record)
        uow.flush()
        file_id = record.id
        uow.commit()

    # ---- 2. Stream --------------------------------------------------------------
    # No transaction is open here, and that is the point of the whole module.
    limited = _LimitedReader(
        command.stream, limit=purpose.max_bytes_development_only, purpose=command.purpose
    )
    written = storage.write(storage_key, limited)  # type: ignore[arg-type]

    # ---- 3. Finalize ------------------------------------------------------------
    with uow_factory() as uow:
        resolver = IdempotencyResolver(uow)
        stored_record = uow.session.get(FileObject, file_id)
        if stored_record is None:  # pragma: no cover - the row was committed above
            raise BusinessRuleViolationError("the initiated file record disappeared")

        stored_record.size_bytes = written.size_bytes
        stored_record.sha256_hash = written.sha256_hash
        stored_record.storage_status = UNSCANNED_STORAGE_STATUS

        response = {
            "id": str(file_id),
            "status": UNSCANNED_STORAGE_STATUS,
            "original_filename": filename,
            "mime_type": command.declared_media_type,
            "size_bytes": written.size_bytes,
            "sha256": written.sha256_hash,
        }

        AuditWriter(uow.session, policy).record(
            AuditEntry(
                action=UPLOAD_FILE.audit_action,
                outcome="success",
                metadata_schema=METADATA_SCHEMA,
                metadata_version=METADATA_VERSION,
                entity_type="file_object",
                entity_id=file_id,
                previous_values=None,
                # No storage address in the audit row. An audit log is read by more
                # people than any API response and is retained far longer, so a key
                # leaked here outlives every other place it could have leaked.
                new_values={
                    "purpose": command.purpose,
                    "storage_status": UNSCANNED_STORAGE_STATUS,
                    "scan_status": UNSCANNED_SCAN_STATUS,
                    "size_bytes": written.size_bytes,
                    "sha256": written.sha256_hash,
                },
                idempotency_record_id=claim_id,
                idempotency_key_hash=key_hash(idempotency_key),
                metadata={"operation": OPERATION},
            ),
            actor=actor,
            context=context,
        )

        # The claim was made in transaction 1 and is completed here, in transaction 3.
        # Re-claiming would be wrong: `claim` on an in-flight record is the concurrent
        # -request path, not a way to fetch one. The record is loaded by the id carried
        # across, and wrapped in the same claim type `complete` expects.
        in_flight = uow.session.get(IdempotencyRecord, claim_id)
        if in_flight is None:  # pragma: no cover - committed in transaction 1
            raise BusinessRuleViolationError("the idempotency claim disappeared")

        resolver.complete(
            IdempotencyClaim(record=in_flight, is_replay=False),
            response_code=201,
            response_body=response,
            resource_type="file_object",
            resource_id=file_id,
        )
        uow.commit()

    return UploadResult(
        file_id=file_id,
        status=UNSCANNED_STORAGE_STATUS,
        original_filename=filename,
        mime_type=command.declared_media_type,
        size_bytes=written.size_bytes,
        sha256=written.sha256_hash,
        processing_job_id=None,
        replayed=False,
    )
