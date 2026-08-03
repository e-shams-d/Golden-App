"""Named commands. One module per command, never a generic mutation path."""

from __future__ import annotations

from app.commands.rename_center_profile import (
    OPERATION as RENAME_CENTER_PROFILE_OPERATION,
)
from app.commands.rename_center_profile import (
    RenameCenterProfile,
    RenameResult,
    execute,
)

__all__ = [
    "RENAME_CENTER_PROFILE_OPERATION",
    "RenameCenterProfile",
    "RenameResult",
    "execute",
]
