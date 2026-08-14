"""The alert mapping is a human reading English prose. This is what checks the reading.

`12_Security_RBAC_Audit.md:642` names five capabilities in words — "manager approval, role
management, audit export, retention approval, or break-glass capability" — and no
permission codes at all. `app/security/high_risk_grants.py` turns that sentence into codes,
which means somebody typed five strings that nothing else in the system validates.

**That is the failure this file exists for.** A mapping naming a permission the platform
does not have would read as complete coverage while alerting on nothing, and the alert
would be discovered missing at the moment somebody wanted it. So every code here is
checked against `docs/governance/permission_catalog.yaml`, an approved artifact this
module did not write and cannot edit without a governance change.

**The count is asserted, and that is not pedantry.** The plan's slice-8E section says
four; the document says five. The difference was found by reading `:642` rather than the
plan, and the fifth is handled differently — refused rather than alerted, because POL-005
disables break-glass for Phase 1A entirely. A loop that silently shrank back to four, or
grew to six, is precisely how this reading would drift away from the document again.

Covers: SEC-HIGHRISK-001.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.security import high_risk_grants

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CATALOGUE = REPOSITORY_ROOT / "docs" / "governance" / "permission_catalog.yaml"
DOC_12 = (
    REPOSITORY_ROOT
    / "Implementation Docs"
    / "05_Backend_and_Security"
    / "12_Security_RBAC_Audit.md"
)

# Every `domain.action:` key under the catalogue's permission sections. Parsed with a
# regular expression rather than a YAML loader on purpose: the loader is a dependency this
# test would then share with the code under test, and the question here is "does this
# string appear in the approved file", which is a question about the file.
_CODE = re.compile(r"^ {6}([a-z_]+\.[a-z_]+):", re.M)


@pytest.fixture(scope="module")
def catalogue_codes() -> frozenset[str]:
    codes = frozenset(_CODE.findall(CATALOGUE.read_text(encoding="utf-8")))
    # Guard the guard. If the catalogue's indentation changed, this set would be empty and
    # every membership assertion below would fail loudly — but a *subset* check against an
    # empty set is the shape that passes, so the floor is here rather than assumed.
    assert len(codes) >= 80, (
        f"only {len(codes)} permission codes were parsed out of the catalogue, which is "
        "far fewer than it defines — the pattern no longer matches how it writes them, "
        "and every check in this file is now comparing against almost nothing"
    )
    return codes


def test_the_document_still_names_the_five_capabilities() -> None:
    """The mapping is derived from one sentence. This is that sentence.

    Quoted rather than paraphrased, so an edit to `:642` that removed a capability — or
    added one — fails here instead of leaving the mapping quietly incomplete.
    """

    text = DOC_12.read_text(encoding="utf-8")
    assert (
        "alerting for grants of manager approval, role management, audit export, "
        "retention approval, or break-glass capability" in text
    ), (
        "doc 12's alerting sentence has changed. app/security/high_risk_grants.py is a "
        "reading of that exact sentence, and it must be re-derived rather than left as a "
        "reading of a sentence that no longer exists."
    )


def test_every_alertable_code_exists_in_the_approved_catalogue(
    catalogue_codes: frozenset[str],
) -> None:
    """A code the platform does not have would alert on nothing while reading as coverage."""

    unknown = sorted(high_risk_grants.alertable_codes() - catalogue_codes)
    assert unknown == [], (
        f"these codes are named as high-risk but are not in permission_catalog.yaml: "
        f"{unknown}. A permission that does not exist can never be granted, so the alert "
        "for it can never fire."
    )


def test_the_forbidden_code_exists_and_is_the_one_policy_disables(
    catalogue_codes: frozenset[str],
) -> None:
    assert high_risk_grants.FORBIDDEN_GRANTS <= catalogue_codes
    assert high_risk_grants.FORBIDDEN_GRANTS == {"break_glass.activate"}

    catalogue = CATALOGUE.read_text(encoding="utf-8")
    # The refusal's justification, checked against the file that justifies it. Without
    # this the refusal is an opinion held by one module.
    assert "disabled_by_approved_POL_005" in catalogue
    # And that `break_glass.review` is deliberately **not** refused: it is a read-only
    # reviewer appointment the policy contemplates, not the bypass POL-005 disables.
    assert "break_glass.review" in catalogue_codes
    assert "break_glass.review" not in high_risk_grants.FORBIDDEN_GRANTS


def test_the_mapping_has_exactly_the_four_alertable_capabilities() -> None:
    """Four alerted plus one refused is five — the number `:642` names.

    A loop that silently shrinks is this mapping's failure mode: the plan itself says four
    because it omitted break-glass, so "four" is a number that looks right from two
    different directions and is only correct for one of them.
    """

    assert set(high_risk_grants.ALERTABLE_GRANTS) == {
        "manager approval",
        "role management",
        "audit export",
        "retention approval",
    }
    assert len(high_risk_grants.ALERTABLE_GRANTS) + len(high_risk_grants.FORBIDDEN_GRANTS) == 5


def test_classify_separates_the_forbidden_from_the_alertable() -> None:
    forbidden, alertable = high_risk_grants.classify(
        frozenset({"role.manage", "break_glass.activate", "trader.read"})
    )

    assert forbidden == {"break_glass.activate"}
    assert alertable == {"role.manage": "role management"}


def test_an_ordinary_grant_produces_nothing() -> None:
    """Without this half, the alert test passes on any grant at all.

    `trader.read` is held by four seeded roles and is granted constantly. If it produced
    an alert, the alert stream would be noise and the grant that mattered would arrive
    inside it.
    """

    forbidden, alertable = high_risk_grants.classify(frozenset({"trader.read", "audit.read"}))

    assert forbidden == frozenset()
    assert alertable == {}


def test_audit_read_is_not_treated_as_audit_export() -> None:
    """The document says export. Reading a masked audit record is a routine activity.

    Three seeded roles hold `audit.read`; conflating it with `audit.export` would fire the
    alert on ordinary auditor onboarding, which is how an alert becomes something people
    dismiss without looking.
    """

    assert high_risk_grants.capability_for("audit.read") is None
    assert high_risk_grants.capability_for("audit.export") == "audit export"


def test_retention_propose_is_not_retention_approval() -> None:
    """The half of the pair that cannot act alone is not the half that needs an alert."""

    assert high_risk_grants.capability_for("retention.propose") is None
    assert high_risk_grants.capability_for("retention.approve") == "retention approval"


def test_the_mapping_cannot_be_mutated_at_runtime() -> None:
    """A `dict` here would let any caller add a capability, or remove one, at import time.

    Not hypothetical in shape: the module is imported by a command that runs on every role
    change, and a mapping that could be edited in place is one that a later convenience
    edit turns into per-deployment configuration without a governance decision.
    """

    with pytest.raises(TypeError):
        high_risk_grants.ALERTABLE_GRANTS["break-glass"] = ("break_glass.activate",)  # type: ignore[index]
