"""Stable metadata shared by the HTTP API and its generated contract."""

from __future__ import annotations

from typing import Any, Final

from app.core.errors import ErrorEnvelope

API_CONTRACT_VERSION: Final = "0.1.0"

# FastAPI otherwise documents its built-in validation payload even though the
# application converts validation failures to the canonical ErrorEnvelope.
VALIDATION_ERROR_RESPONSE: Final[dict[int | str, dict[str, Any]]] = {
    422: {
        "model": ErrorEnvelope,
        "description": "The request failed canonical validation.",
    }
}
