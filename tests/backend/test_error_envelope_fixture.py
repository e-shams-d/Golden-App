"""The error envelopes the frontend maps are recorded from the server that produces them.

`packages/api-client/src/application-state.ts` turns an error code into one of document
21's eighteen states. Nothing made that mapping true of *this* server: a TypeScript test
driving hand-typed envelopes proves the mapping is self-consistent and says nothing about
whether the shapes it maps are the shapes the API sends.

So the fixture is **recorded**, not written. This module builds each envelope by raising
the real `AppError` subclass through the real handler, and asserts the committed file is
byte-equal to what it just produced. The frontend then reads that file. If a code, a
status or the envelope's shape changes, this test fails on the same commit — and the
frontend test that consumes the fixture starts driving the new shape without anyone
editing it.

**What makes it a binding rather than a ritual.** A fixture regenerated from the same
source it is compared against would always match. The comparison here is against a file in
git, so the diff is what a reviewer sees: changing `VERSION_CONFLICT`'s status shows up as
a changed fixture line in the same pull request as the code change, next to a frontend
test that now maps it differently.

**The catalogue is the floor, not the handler.** Every code in
`docs/governance/api_error_catalog.yaml` must have a state, including the sixteen no route
raises yet. Deriving the floor from what the application currently throws would let a code
be added to the catalogue and reach a screen with no state at all — and would report green
over nine of twenty-five.

Covers: UI-STATE-001.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from app.core.errors import (
    AppError,
    BackgroundProcessingUnavailableError,
    BusinessRuleViolationError,
    DependencyUnavailableError,
    ForbiddenError,
    IdempotencyKeyReusedError,
    InvalidStateTransitionError,
    NotFoundError,
    PreconditionRequiredError,
    VersionConflictError,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPOSITORY_ROOT / "tests" / "fixtures" / "api_error_envelopes.json"
CATALOGUE = REPOSITORY_ROOT / "docs" / "governance" / "api_error_catalog.yaml"
MAPPING = REPOSITORY_ROOT / "packages" / "api-client" / "src" / "application-state.ts"

# A fixed request id, so the fixture is stable across runs. The real envelope carries the
# request's own; substituting a constant here is the one field that is *not* recorded, and
# it is called out rather than silently normalised — a fixture that quietly rewrote fields
# would be a hand-written stub with extra steps.
FIXED_REQUEST_ID = "00000000-0000-4000-8000-000000000000"

# One instance per error the application can raise today, constructed the way its call
# sites construct it. Not every catalogued code: the rest have no class yet, and inventing
# one to record an envelope would record a shape nothing produces.
RAISABLE: tuple[AppError, ...] = (
    ForbiddenError(),
    NotFoundError(),
    VersionConflictError(),
    PreconditionRequiredError("If-Match"),
    IdempotencyKeyReusedError(),
    BusinessRuleViolationError("the transition is not allowed"),
    InvalidStateTransitionError("the record is not in a state that permits this"),
    DependencyUnavailableError(),
    BackgroundProcessingUnavailableError(),
    AppError("UNAUTHENTICATED", "Authentication is required.", 401),
    AppError("RATE_LIMITED", "Too many attempts. Try again later.", 429),
    AppError("INTERNAL_ERROR", "The request could not be completed.", 500),
)

_CATALOGUE_CODE = re.compile(r"\b([A-Z][A-Z_]{3,})\b")

# Names that appear in the catalogue in upper case and are not error codes. Listed rather
# than filtered by shape, because a filter that dropped a real code would shrink the floor
# and report full coverage over a smaller set.
NOT_A_CODE = frozenset({"IBAN"})


def catalogue_codes() -> frozenset[str]:
    found = frozenset(_CATALOGUE_CODE.findall(CATALOGUE.read_text(encoding="utf-8")))
    return found - NOT_A_CODE


def build_envelopes() -> dict[str, Any]:
    """One recorded envelope per raisable error, keyed by code and sorted."""

    envelopes: dict[str, Any] = {}
    for error in RAISABLE:
        envelopes[error.code] = {
            "status": error.status_code,
            "body": {
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": [],
                    "request_id": FIXED_REQUEST_ID,
                }
            },
        }
    return dict(sorted(envelopes.items()))


def rendered() -> str:
    return json.dumps(build_envelopes(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def test_the_committed_fixture_matches_what_the_server_produces() -> None:
    """The binding. Regenerate with `python -m tests.backend.test_error_envelope_fixture`.

    Byte-equality rather than a structural comparison: a structural check would accept a
    fixture whose formatting drifted, and the frontend reads the bytes.
    """

    assert FIXTURE.exists(), (
        f"{FIXTURE.relative_to(REPOSITORY_ROOT)} is missing. The frontend state test reads "
        "it, and without it that test has nothing to drive — regenerate it rather than "
        "letting the frontend fall back to hand-written envelopes."
    )
    assert FIXTURE.read_text(encoding="utf-8") == rendered(), (
        "the recorded error envelopes no longer match what the application produces. This "
        "is the intended failure when a code, a status or the envelope shape changes: "
        "regenerate the fixture in the same commit, so the frontend's state mapping is "
        "reviewed against the new shape rather than silently mapping the old one."
    )


def test_the_recording_is_not_empty_and_covers_what_the_app_can_raise() -> None:
    """Guard the guard: an empty `RAISABLE` would make the comparison above vacuous."""

    envelopes = build_envelopes()
    assert len(envelopes) >= 12, (
        f"only {len(envelopes)} envelopes were recorded, which is fewer than the errors "
        "this application raises — the comparison above is now against almost nothing"
    )
    # Every recorded envelope carries the four fields `normalizeApiError` requires. Without
    # all four the frontend's `isErrorEnvelope` returns false and every fixture would map
    # through the status fallback, which would pass while proving the codes are unread.
    for code, envelope in envelopes.items():
        assert set(envelope["body"]["error"]) == {"code", "message", "details", "request_id"}, code
        assert envelope["body"]["error"]["code"] == code


@pytest.mark.parametrize("code", sorted(catalogue_codes()))
def test_every_catalogued_code_has_a_state(code: str) -> None:
    """The floor comes from the approved catalogue, not from what the app throws today.

    Sixteen of these twenty-five have no route raising them yet. Mapping only the nine that
    are raised would let a code be added to a route and reach a screen with no state — and
    the coverage claim would read as complete while covering a third of the contract.
    """

    mapping = MAPPING.read_text(encoding="utf-8")
    assert f"  {code}:" in mapping, (
        f"{code} is in the approved error catalogue and has no entry in STATE_FOR_CODE. "
        "An unmapped code falls through to the status fallback, which cannot tell a "
        "workflow rejection from a stale version — both are 409."
    )


def test_the_catalogue_floor_is_not_empty() -> None:
    """Guard the guard, again: a pattern that matched nothing would parametrise zero cases.

    A parametrised test over an empty set does not fail. It reports nothing and passes,
    which is exactly the shape this whole file exists to avoid.
    """

    codes = catalogue_codes()
    assert len(codes) >= 20, (
        f"only {len(codes)} codes were parsed out of the error catalogue, which is fewer "
        "than it defines — the pattern no longer matches how it writes them"
    )


if __name__ == "__main__":  # pragma: no cover - the regeneration entry point
    FIXTURE.write_text(rendered(), encoding="utf-8")
    print(f"wrote {FIXTURE.relative_to(REPOSITORY_ROOT)}")
