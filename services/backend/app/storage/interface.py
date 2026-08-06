"""The storage contract: streaming bytes in and out, and reporting on them.

Extended from the M1 shape, which had only `check_available()` and `close()`.
Both keep their exact signatures and semantics, because the readiness probe binds
directly to `check_available` and a change there would alter what `/health/ready`
means — a protocol extension must not move an operational contract.

**Everything streams.** `write` takes a file object and consumes it in chunks;
`open` hands back a file object rather than bytes. A bank statement is routinely
tens of megabytes, and a signature that returned `bytes` would put the whole file
in the worker's memory — several at once under concurrency, on a host sized for
neither. It would also make the size and hash something the caller reports rather
than something storage measures.

**The hash and the size are measured by the layer that moves the bytes**, in the
same pass. Asking the caller for them means trusting a number computed somewhere
else about content this layer just received: the two can disagree, and the
disagreement is invisible. Returning them from `write` makes the checksum that
`file_objects.sha256_hash` requires a fact of the write rather than a later
promise.

**`iter_keys` exists for reconciliation and nothing else.** Detecting a storage
object with no database record is impossible without enumerating storage, and that
condition is the one that silently accumulates orphaned bytes nobody is accounting
for.

Deliberately absent: any `delete`. ADR-005 is open, no governed retention procedure
exists, and `tests/backend/test_no_deletion_machinery.py` fails the build if one
appears. Storage that the application can erase is storage whose contents are not
evidence.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import BinaryIO, Protocol, runtime_checkable


@dataclass(frozen=True)
class StoredObject:
    """What storage measured while the bytes went past.

    Frozen, because a size or digest that can be adjusted after the fact is one
    whose `file_objects` row may describe different content than what was written.
    """

    size_bytes: int
    sha256_hash: str

    def __post_init__(self) -> None:
        if self.size_bytes < 0:
            raise ValueError(f"size_bytes cannot be negative; got {self.size_bytes}")
        if len(self.sha256_hash) != 64 or self.sha256_hash != self.sha256_hash.lower():
            raise ValueError(
                "sha256_hash must be 64 lower-case hex characters, matching the "
                f"database constraint; got {self.sha256_hash!r}"
            )


class StorageError(OSError):
    """Storage could not satisfy the request.

    An `OSError` subclass so existing `except OSError` handling — the readiness
    probe's included — keeps working unchanged.
    """


class StorageKeyError(StorageError):
    """The key is not addressable within this backend.

    Separate from `StorageError` because the causes are different in kind: a
    rejected key is a programming error or an attack, and a storage failure is an
    operational one. Conflating them turns an attempted traversal into a line in
    the disk-full alert.
    """


@runtime_checkable
class StorageBackend(Protocol):
    def check_available(self) -> None:
        """Raise on unavailable/unwritable storage without returning path details."""

    def write(self, key: str, source: BinaryIO) -> StoredObject:
        """Stream `source` to `key`, returning the size and digest measured en route.

        Must be atomic from a reader's point of view: a partially written object is
        never visible under `key`. A half-uploaded file that a reader can open is
        a half-uploaded file that becomes evidence.

        Raises if `key` already exists. Overwriting would let a retry replace
        content whose digest another row already records.
        """

    def open(self, key: str) -> AbstractContextManager[BinaryIO]:
        """Open `key` for streaming reads, as a context manager so it is closed."""

    def stat(self, key: str) -> StoredObject | None:
        """Measure the object at `key`, or return None if it is not there.

        None rather than raising: "absent" is an ordinary reconciliation answer,
        and an exception would make the common case the expensive one.
        """

    def iter_keys(self) -> Iterator[str]:
        """Every key this backend holds. For reconciliation only."""

    def close(self) -> None:
        """Release adapter resources."""
