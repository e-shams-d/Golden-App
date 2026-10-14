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

# What `authenticated_actor` refuses with, for every route that depends on it — directly or
# through `requires(...)`. 401 when there is no valid session; 403 for a missing permission and,
# on an unsafe method, for a wrong CSRF token or origin. The two 403s are byte-identical by
# design (`app/api/v1/auth.py:82`), so one description serves both.
# `tests/backend/test_contract_declares_the_refusals.py` holds every route to these. F-13.
UNAUTHENTICATED_RESPONSE: Final[dict[int | str, dict[str, Any]]] = {
    401: {"model": ErrorEnvelope, "description": "No valid session."},
}
REFUSED_RESPONSE: Final[dict[int | str, dict[str, Any]]] = {
    403: {"model": ErrorEnvelope, "description": "Permission denied."},
}
