"""Reading a stored file's bytes, so that no route has to know where they are.

M4's Definition of Done: every later module must be able to reference a stable
`FileObject` "without directly handling storage paths". The download route was handling
one — `runtime.storage.open(record.storage_key)` — and slice 11's gate is what found it.
The route was correct and the boundary was not: an address that only one file outside this
package touches is still an address outside this package, and the next route to serve
bytes would have copied the line.

So the key never leaves. A caller passes the record and receives an iterator.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass

from app.core.logging import get_logger
from app.db.models.file_object import FileObject
from app.storage.interface import StorageBackend, StorageError

CHUNK_BYTES = 64 * 1024


class FileBytesUnavailableError(Exception):
    """The row says the object exists and storage disagrees.

    Carries no key and no path. `StorageError` carries the storage key in its message, and
    an unhandled exception is the one path where a traceback can put that in front of a
    caller — which is the whole boundary, leaking through an error page.
    """


@dataclass(frozen=True)
class FileStream:
    chunks: Iterator[bytes]
    media_type: str
    filename: str


def open_stream(storage: StorageBackend, record: FileObject) -> FileStream:
    """Open the object and hand back an iterator over its bytes.

    The context is entered here rather than inside the generator. `StorageBackend.open`
    only builds a context manager; the object is untouched until entry, and entry inside
    the streaming generator happens after the response has begun, where the exception can
    no longer become a status code.
    """

    stack = ExitStack()
    try:
        body = stack.enter_context(storage.open(record.storage_key))
    except StorageError as error:
        stack.close()
        get_logger("files").error(
            "file_object_missing_from_storage",
            extra={"file_id": str(record.id), "category": record.category},
        )
        raise FileBytesUnavailableError from error

    def chunks() -> Iterator[bytes]:
        with stack:
            while chunk := body.read(CHUNK_BYTES):
                yield chunk

    return FileStream(
        chunks=chunks(),
        media_type=record.mime_type_declared,
        filename=record.original_filename,
    )


def measure_now(storage: StorageBackend, record: FileObject) -> str | None:
    """Re-hash the stored object and return the digest, or `None` if it is gone.

    Added for M7 §15.5's eighth integrity check, which is the only one whose left side is not a
    stored value: it exists to detect a file that changed *after* it was recorded, so the digest
    has to be measured now rather than read from the row.

    **Here rather than in the caller**, because `TRACE-DOD-003` is the reason this package exists:
    a module outside `app/files/` names a `FileObject` and asks for what it needs, never learning
    where the bytes are. M7 slice 4 wrote `storage.stat(record.storage_key)` at the call site
    first and the boundary gate refused it — correctly, since ADR-003 is still open and a change
    of storage provider must touch `app/storage/` and nothing else.
    """

    measured = storage.stat(record.storage_key)
    return None if measured is None else measured.sha256_hash
