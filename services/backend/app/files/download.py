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
