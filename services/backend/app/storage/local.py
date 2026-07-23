"""Local private-storage readiness adapter for development/on-prem operation."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


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

    def close(self) -> None:
        return None
