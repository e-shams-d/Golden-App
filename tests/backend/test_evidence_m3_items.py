"""OPS-EVID-001: the artifact records M3's state, and says what it cannot record.

**First, the identifier, because it was the cheapest possible false discharge.** The M3
plan writes `OPS-EVID-001`; the two tests that already exist write `OPS-EVIDENCE-001`,
which is M2's (M2 plan:1358). Coverage is keyed by exact string, so the M3 obligation had
**zero** citations — and the fastest way to make it green would have been to add the M3
spelling to a docstring that already described M2's behaviour. That would have discharged
an M3 obligation with an M2 test and nobody would have noticed.

They are two obligations, and the distinction is not clerical:

* `OPS-EVIDENCE-001` is about the emitter's **shape and refusals** — every field M2 can
  supply is present, an unreachable instance produces no artifact, and an unsupplyable
  field is null with its reason. `tests/backend/test_evidence_emitter.py` proves that.
* `OPS-EVID-001` is about the artifact carrying **M3's own state**: what this build was
  constructed to grant, and the two M3 facts it honestly cannot supply.

So this file exists rather than a sentence being added to that one.

**The interesting assertion is the negative one.** M3 built authentication and
authorisation, and the obvious evidence item would be "the permissions the deployment
resolves". The running instance does not publish that, and adding it to
`/api/v1/operations/release-evidence` would change a published schema whose
breaking-change waiver process is an unresolved TODO(governance). The catalogue digest
answers a *different* question — what the build was made to grant, not what it grants — so
it is labelled `repository`, and the instance's answer is recorded as unfilled with that
reason. An artifact that filed the repository's answer under the instance's name would be
the same substitution this emitter refuses for the Alembic revision.

Covers: OPS-EVID-001.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from scripts.emit_evidence import (
    UNFILLABLE_AT_M2,
    UNFILLABLE_AT_M3,
    authorization_state,
    build_artifact,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CATALOGUE = REPOSITORY_ROOT / "docs" / "governance" / "permission_catalog.yaml"

INSTANCE: dict[str, Any] = {
    "service": "golden-backend",
    "version": "0.1.0",
    "commit": "abcdef1234567",
    "environment": "test",
    "schema_state": {
        "applied_revisions": ["0016"],
        "expected_revisions": ["0016"],
        "matches": True,
    },
    "feature_flags": [{"flag_key": "ocr.enabled", "is_enabled": False}],
}


@pytest.fixture
def artifact() -> dict[str, Any]:
    return build_artifact(INSTANCE, run_id="run-1", moment=datetime(2026, 8, 14, tzinfo=UTC))


def test_the_artifact_records_what_the_build_was_made_to_grant(artifact: dict[str, Any]) -> None:
    """The digest is over the approved catalogue's bytes, so a re-scoped permission moves it.

    Compared against a digest computed here from the same file. That is a weak check on its
    own — it would pass over an empty file — so the floors below are what make it mean
    something.
    """

    authorization = artifact["authorization"]

    assert authorization["catalogue_digest"] == hashlib.sha256(CATALOGUE.read_bytes()).hexdigest()
    assert authorization["read_from"].startswith("docs/governance/permission_catalog.yaml")


def test_the_declared_counts_are_a_floor_and_not_a_zero() -> None:
    """Guard the guard. A pattern that stopped matching would report zero permissions.

    Zero is the number an empty parse produces, and an artifact recording "this release
    declares 0 permissions" would be filed as evidence that authority is absent rather than
    as evidence that the parser broke.
    """

    state = authorization_state()

    assert state["declared_permissions"] >= 80, (
        f"only {state['declared_permissions']} permissions were counted in the approved "
        "catalogue, which is far fewer than it defines — the pattern no longer matches "
        "how it writes them, and the digest beside it would still look correct"
    )
    assert state["declared_roles"] >= 5, (
        f"only {state['declared_roles']} roles were counted; the catalogue defines the "
        "eight Phase 1A roles"
    )


def test_the_authorization_block_is_attributed_to_the_repository(artifact: dict[str, Any]) -> None:
    """Never to the instance, and this is the assertion that keeps it honest.

    `source_of_each_field` is what a reader consults to know whose claim each field is.
    Listing the catalogue under `instance` would turn "what we built" into "what is
    running" with no code change at all.
    """

    sources = artifact["source_of_each_field"]

    assert "authorization" in sources["repository"]
    assert "authorization" not in sources["instance"]


def test_the_two_facts_m3_cannot_supply_are_present_and_null_with_reasons(
    artifact: dict[str, Any],
) -> None:
    """An evidence set that silently lacked these would read as complete.

    `assurance_factor` is ADR-009, which is the owner's decision and not a technical one.
    `resolved_permissions_from_instance` is the one that matters more: it is the field
    somebody would most expect an identity milestone to supply, and supplying it from the
    repository would have been easy and wrong.
    """

    unfilled = artifact["unfilled"]

    for field in ("assurance_factor", "resolved_permissions_from_instance"):
        assert field in unfilled, f"{field} is absent, so the gap reads as no gap"
        assert len(unfilled[field]) > 80, f"{field} is recorded with no usable reason"

    assert "ADR-009" in unfilled["assurance_factor"]
    assert "TODO(governance)" in unfilled["resolved_permissions_from_instance"]


def test_m2_s_unfilled_fields_survive_the_merge(artifact: dict[str, Any]) -> None:
    """The merge is where M2's gaps would quietly disappear.

    `{**M2, **M3}` with a shared key would drop one silently. Asserted because the two
    dictionaries are edited by different milestones and nothing else would report it.
    """

    unfilled = artifact["unfilled"]

    assert set(UNFILLABLE_AT_M2) <= set(unfilled)
    assert set(UNFILLABLE_AT_M3) <= set(unfilled)
    assert len(unfilled) == len(UNFILLABLE_AT_M2) + len(UNFILLABLE_AT_M3), (
        "a key collided between the M2 and M3 unfilled sets, so one milestone's reason "
        "has been overwritten by the other's"
    )


def test_no_unfilled_field_is_also_filled(artifact: dict[str, Any]) -> None:
    """A field recorded as missing while present somewhere is the worst of both.

    A reader who trusts `unfilled` would report a gap that is not there; a reader who
    trusts the body would report evidence the emitter says it does not have.
    """

    for field in artifact["unfilled"]:
        assert field not in artifact, f"{field} is recorded as unfilled and is also present"
