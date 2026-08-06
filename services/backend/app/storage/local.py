"""Local private-storage adapter for development/on-prem operation.

`check_available` and `close` are unchanged from M1, byte for byte in behaviour:
the readiness probe binds directly to the first, and altering it would change what
`/health/ready` reports while looking like a refactor.

Three properties of the added methods are worth stating, because each is a decision
rather than an implementation detail:

**Every key is resolved inside the root, and the check is on the resolved path.**
Validating the string and then joining it is the classic hole — `a/../../b` passes
a substring test and lands outside. `Path.resolve()` first, then confirm the root is
one of its parents, so symlinks and `..` are both accounted for.

**Writes land atomically.** Bytes go to a temporary file in the same directory, are
fsynced, and are then renamed into place. `os.replace` is atomic within a
filesystem, so a reader never opens a half-written object — and a half-written
object is one that could be hashed, recorded and treated as evidence.

**A write refuses an existing key.** Overwriting would let a retry replace content
whose digest another row already records, which is the quietest possible form of
evidence tampering: the row still verifies, against different bytes.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from app.storage.interface import StorageError, StorageKeyError, StoredObject

# 256 KiB. Large enough that a 50 MB statement is a couple of hundred reads,
# small enough that concurrent workers do not each hold a megabyte.
_CHUNK_BYTES = 256 * 1024


class LocalStorageBackend:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve(strict=False)

    def check_available(self) -> None:
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self._root.is_dir():
            raise OSError("storage unavailable")

        probe_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=".health-",
                dir=self._root,
                delete=False,
            ) as handle:
                probe_path = Path(handle.name)
                handle.write(b"storage-health")
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            if probe_path is not None:
                probe_path.unlink(missing_ok=True)

    def _resolve(self, key: str) -> Path:
        """Map a key to a path inside the root, or refuse it.

        The order matters: resolve, then check containment. Checking the string
        first and joining afterwards is how `a/../../etc/passwd` gets through.
        """

        if not key or key != key.strip():
            raise StorageKeyError(f"key must be non-empty and unpadded; got {key!r}")
        if key.startswith("/") or "\\" in key or ":" in key:
            raise StorageKeyError(
                f"key must be a relative POSIX path with no drive or backslash; got {key!r}"
            )
        if any(segment in {"", ".", ".."} for segment in key.split("/")):
            raise StorageKeyError(f"key segments must be ordinary names; got {key!r}")

        candidate = (self._root / key).resolve(strict=False)
        if candidate != self._root and self._root not in candidate.parents:
            raise StorageKeyError(
                f"key resolves outside the storage root; got {key!r}. This is a "
                "traversal attempt or a bug that would let one tenant read another."
            )
        return candidate

    def write(self, key: str, source: BinaryIO) -> StoredObject:
        target = self._resolve(key)
        if target.exists():
            raise StorageError(
                f"an object already exists at {key!r}. Overwriting would replace "
                "content whose digest an existing record already claims."
            )
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

        digest = hashlib.sha256()
        size = 0
        # Created beside the target so `os.replace` stays within one filesystem;
        # across filesystems it is not atomic. `mkstemp` rather than
        # `NamedTemporaryFile(delete=False)` so the descriptor is owned by exactly
        # one context manager and cannot be left open on an error path.
        descriptor, partial_name = tempfile.mkstemp(prefix=".partial-", dir=target.parent)
        partial = Path(partial_name)
        try:
            with os.fdopen(descriptor, "wb") as sink:
                while chunk := source.read(_CHUNK_BYTES):
                    digest.update(chunk)
                    size += len(chunk)
                    sink.write(chunk)
                sink.flush()
                os.fsync(sink.fileno())
            os.replace(partial, target)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise

        return StoredObject(size_bytes=size, sha256_hash=digest.hexdigest())

    @contextlib.contextmanager
    def open(self, key: str) -> Iterator[BinaryIO]:
        path = self._resolve(key)
        try:
            handle = path.open("rb")
        except FileNotFoundError as error:
            raise StorageError(f"no object at {key!r}") from error
        try:
            yield handle
        finally:
            handle.close()

    def stat(self, key: str) -> StoredObject | None:
        path = self._resolve(key)
        if not path.is_file():
            return None

        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while chunk := handle.read(_CHUNK_BYTES):
                digest.update(chunk)
                size += len(chunk)
        return StoredObject(size_bytes=size, sha256_hash=digest.hexdigest())

    def iter_keys(self) -> Iterator[str]:
        """Every stored object, as a POSIX-style key relative to the root.

        Skips the dotfiles this adapter creates itself — health probes and
        interrupted partial writes. Reporting a `.partial-` file as an orphaned
        object would make reconciliation cry wolf on every killed worker.
        """

        if not self._root.is_dir():
            return
        for path in sorted(self._root.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            yield path.relative_to(self._root).as_posix()

    def close(self) -> None:
        return None
