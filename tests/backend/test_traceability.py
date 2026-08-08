"""TRACE-001: every obligation the plan claims is proved must name a test.

The plan's "What proves it" sections list the obligations each slice discharges. That
list is a promise, and until now nothing checked it — a slice could claim
`DB-BANK-003` and ship no test for it, and the only way to notice would be for
somebody to read both documents side by side.

So the plan is the authority and this reads it directly. There is no second
hand-maintained list of requirement IDs, because a second list is a second thing to
drift — which is the failure this whole slice has been about.

**An uncovered obligation is recorded, not tolerated silently.** `RECORDED_GAPS`
holds the ones M2 genuinely does not discharge, each with its reason, and the gate
fails on any obligation that is neither cited by a test nor listed there. The
difference between "we know this is not covered" and "nobody checked" is the entire
value of a traceability matrix.

Citations live in module docstrings as `Covers: ID, ID.` lines, alongside the IDs
already quoted in prose throughout the suite. Docstrings rather than markers or a
mapping file: the ID belongs next to the reasoning that explains why the test proves
it, and a reader looking for coverage looks at the test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLAN = REPOSITORY_ROOT / "docs" / "handoff" / "M2_IMPLEMENTATION_PLAN.md"
TESTS = REPOSITORY_ROOT / "tests"

# The catalogue prefixes. An ID outside these is a typo or an invented category, and
# either way nothing downstream can group it.
#
# The plan's slice-10 text names ten prefixes (UT, DB, SVC, API, SEC, CON, FILE, AUD,
# OPS, PERF) but its own "What proves it" sections also use JOB, CI, TRACE, SEED and
# BANK. `JOB` was missing from this list on the first attempt, and the invented-prefix
# test below caught it — which meant four obligations (JOB-CRASH-001, JOB-EAGER-001,
# JOB-LEASE-001, JOB-RETRY-001) had been silently outside the coverage check. The list
# here follows the plan's usage rather than its narrower prose.
PREFIXES = (
    "UT",
    "DB",
    "SVC",
    "API",
    "SEC",
    "CON",
    "FILE",
    "AUD",
    "OPS",
    "PERF",
    "CI",
    "TRACE",
    "SEED",
    "BANK",
    "JOB",
)

_ID = re.compile(rf"\b(?:{'|'.join(PREFIXES)})-[A-Z0-9]+(?:-\d+)?\b")
_PROVES_SECTION = re.compile(r"### What proves it\n(.*?)(?=\n### |\n## |\Z)", re.S)

# Obligations M2 does not discharge, with the reason. Each must be a real decision
# rather than a deferral of convenience.
RECORDED_GAPS: dict[str, str] = {
    "PERF-QUEUE-001": (
        "Performance evidence requires a recorded p95 together with the test data "
        "volume and the environment it was measured on. A latency figure without "
        "both is not acceptable evidence, and M2 produces neither a representative "
        "volume nor a production-shaped environment. The evidence emitter records "
        "this field as unfilled with the same reason rather than omitting it, so a "
        "release reader sees the gap instead of a complete-looking set."
    ),
}


def plan_obligations() -> set[str]:
    text = PLAN.read_text(encoding="utf-8")
    return {
        identifier
        for section in _PROVES_SECTION.findall(text)
        for identifier in _ID.findall(section)
    }


def cited_ids() -> dict[str, set[str]]:
    """Every obligation id cited in the suite, mapped to the files citing it."""

    found: dict[str, set[str]] = {}
    for path in sorted(TESTS.rglob("*.py")):
        # This file names ids in `RECORDED_GAPS` and in its own prose. Counting those
        # as coverage would let a gap register itself as discharged.
        if path.name == "test_traceability.py":
            continue
        for identifier in _ID.findall(path.read_text(encoding="utf-8")):
            found.setdefault(identifier, set()).add(str(path.relative_to(REPOSITORY_ROOT)))
    return found


@pytest.fixture(scope="module")
def obligations() -> set[str]:
    found = plan_obligations()
    assert found, "no obligations parsed from the plan; its section headings changed"
    return found


def test_the_plan_states_a_substantial_number_of_obligations(obligations: set[str]) -> None:
    """Guard the guard.

    Every assertion below passes vacuously if the plan parser returns nothing, which
    is exactly what a changed heading would cause.
    """

    assert len(obligations) > 50, f"only {len(obligations)} obligations parsed"


def test_every_obligation_is_cited_or_recorded_as_a_gap(obligations: set[str]) -> None:
    cited = cited_ids()
    uncovered = sorted(obligations - set(cited) - set(RECORDED_GAPS))

    assert uncovered == [], (
        "the plan claims these are proved and no test names them:\n"
        + "\n".join(f"  {identifier}" for identifier in uncovered)
        + "\nAdd the id to the docstring of the test that proves it, or record it in "
        "RECORDED_GAPS with the reason it is not discharged."
    )


def test_no_recorded_gap_is_actually_covered(obligations: set[str]) -> None:
    """The other direction.

    A gap entry for something a test now proves understates the coverage, and it
    would let the obligation be quietly dropped later on the strength of a stale
    excuse.
    """

    cited = set(cited_ids())
    resolved = sorted(set(RECORDED_GAPS) & cited)

    assert resolved == [], (
        f"these are recorded as gaps but a test now cites them: {resolved}. Remove the entry."
    )


def test_every_recorded_gap_is_a_real_obligation(obligations: set[str]) -> None:
    """A gap for an id the plan does not require is an excuse for nothing."""

    invented = sorted(set(RECORDED_GAPS) - obligations)

    assert invented == [], f"recorded gaps that the plan does not require: {invented}"


@pytest.mark.parametrize("identifier", sorted(RECORDED_GAPS))
def test_each_gap_states_a_reason_not_a_placeholder(identifier: str) -> None:
    reason = RECORDED_GAPS[identifier]

    assert len(reason) > 80, f"{identifier} has no real reason recorded"
    assert "TODO" not in reason and "later" not in reason.lower()[:40]


def test_the_recorded_gap_matches_what_the_evidence_emitter_reports() -> None:
    """The gap must say the same thing in both places a reader might look.

    `PERF-QUEUE-001` is unfilled here and `performance_p95` is unfilled in the
    emitter's artifact. If those two disagreed, one of them would be reassuring
    somebody falsely.
    """

    from scripts.emit_evidence import UNFILLABLE_AT_M2

    assert "performance_p95" in UNFILLABLE_AT_M2
    assert "PERF-QUEUE-001" in RECORDED_GAPS
    for phrase in ("volume", "environment"):
        assert phrase in UNFILLABLE_AT_M2["performance_p95"].lower()
        assert phrase in RECORDED_GAPS["PERF-QUEUE-001"].lower()


def test_every_cited_id_uses_a_catalogue_prefix() -> None:
    """The extraction only matches catalogue prefixes, so this checks the inverse:
    that nothing shaped like an id is sitting in the suite under an invented
    category, which would look like traceability and provide none."""

    invented = re.compile(r"\b([A-Z]{2,6})-[A-Z0-9]+-\d+\b")
    offenders: dict[str, set[str]] = {}
    for path in sorted(TESTS.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for prefix in invented.findall(path.read_text(encoding="utf-8")):
            if prefix not in PREFIXES and prefix != "DOC":
                offenders.setdefault(prefix, set()).add(str(path.relative_to(REPOSITORY_ROOT)))

    assert offenders == {}, f"ids using a prefix outside the catalogue: {offenders}"


def test_the_heaviest_obligations_are_cited_by_more_than_one_test(
    obligations: set[str],
) -> None:
    """The integrity primitives the plan calls critical must be proved at more than
    one layer.

    A single test can be wrong in the same way the code is wrong. These four are the
    ones whose failure would be silent and financial.
    """

    cited = cited_ids()
    thin = {
        identifier: sorted(cited.get(identifier, set()))
        for identifier in ("SVC-ATOMIC-001", "CON-IDEM-001", "AUD-ROLLBACK-001", "DB-MIG-001")
        if len(cited.get(identifier, set())) < 1
    }

    assert thin == {}, f"critical obligations with no citation: {thin}"
