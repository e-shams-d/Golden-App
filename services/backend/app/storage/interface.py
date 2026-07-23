"""Minimal M1 storage contract, intentionally free of financial file concepts."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    def check_available(self) -> None:
        """Raise on unavailable/unwritable storage without returning path details."""

    def close(self) -> None:
        """Release adapter resources."""
