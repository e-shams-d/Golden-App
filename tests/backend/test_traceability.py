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
HANDOFF = REPOSITORY_ROOT / "docs" / "handoff"


# Every milestone plan, not one hard-wired path. The M3 plan existed for nine
# merged slices while this gate read only M2 — so roughly eighty obligations were
# stated in a document nothing checked, which is the failure this gate exists to
# prevent, committed against the gate itself.
#
# Slice 1's revision note deferred the fix and said why a naive glob would not do:
# obligations are discharged slice by slice, so pointing the gate at a plan in
# progress fails on the day it lands. `PENDING` below is the answer — an
# obligation is either cited by a test or owned by a named slice, and never
# neither.
def plans() -> list[Path]:
    return sorted(HANDOFF.glob("M*_IMPLEMENTATION_PLAN.md"))


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
    # M3's frontend obligations. Added when this gate was pointed at the M3 plan and
    # the invented-prefix test below refused every `UI-` id — the second time that
    # test has caught a prefix omission that would otherwise have left a whole
    # category outside the coverage check.
    "UI",
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


# Obligations a plan states that no test cites yet, each owned by the slice that
# owes it. Distinct from `RECORDED_GAPS`, which is for obligations that will never
# be discharged and say why — these are simply not written yet.
#
# An entry here is a commitment, not an exemption: two tests below fail on an entry
# whose obligation no plan states, and on an entry for something already covered.
PENDING: dict[str, str] = {
    # M3 slice 1B — the doc-04 index parity gate, split out because its day-one
    # disposition ledger is roughly forty pre-existing divergences across tables M2
    # shipped, and none of it is M3.
    "DB-SPEC-001": "M3 slice 1B",
    "TRACE-PLAN-001": "M3 slice 1B",
    # M3 slice 8B — the second endpoint family: /admin-users, role management, and
    # the credential-change routes.
    "AUD-ROLE-001": "M3 slice 8B",
    "API-PWD-001": "M3 slice 8B",
    "API-PWD-002": "M3 slice 8B",
    # Still owed, and re-owned in slice 10B with the reason narrowed by what that slice
    # measured. The *mechanism* this depends on is now proved in a real browser
    # (UI-ISO-003: Chromium refuses a `__Host-` cookie carrying Domain, and plain-HTTP
    # localhost is a secure context). What remains is the end-to-end claim — a trader
    # session cannot reach an admin surface — which needs the compose stack's two
    # hostnames, and needs the frontend images rebuilt because the ones on disk predate
    # the login screens.
    "UI-ISO-002": "M3 slice 10D (compose-stack browser run, needs rebuilt frontend images)",
    # Re-deferred in slice 10B rather than attempted, because both are build-then-prove
    # and the plan listed them as prove-only.
    #
    # There is no dashboard to land on: both login handlers do `router.refresh()` then
    # `router.replace("/")`, and `/` is a static shell with a hard-coded navigation and
    # a literal "role unknown" header — so an authenticated admin and an anonymous
    # visitor render identical bytes, and "lands on its own dashboard" has nothing to
    # assert against.
    "UI-LOGIN-001": "M3 slice 10D (needs a session-derived landing surface to assert)",
    # And no navigation reads permissions: `NavigationItem` is `{href, label}`, both
    # renderers map unconditionally, and neither app fetches `/auth/me` at runtime —
    # both auth adapters are exported and imported nowhere. Worse, the mapping itself is
    # an owner decision rather than an implementation one: doc 21 §6.3's per-role lists
    # disagree with migration `_0008`'s seeded grants, and the naive choice is actively
    # wrong — `accountant` holds `trader.read`, so gating the traders item on it would
    # hide nothing from the only unprivileged role that exists.
    "UI-NAV-001": "M3 slice 10D (the href-to-permission mapping is an owner decision)",
    # The mapping this needs does not exist anywhere: no code in either frontend turns a
    # status or an error code into a state, so there is nothing for a real response to
    # drive. Recorded against 10C with the twelve doc-21 states nothing has ever named.
    "UI-STATE-001": "M3 slice 10C",
    # An admin response carrying another trader's data needs a list endpoint to carry
    # it, and M3 has none. Recorded against M5 in the IDOR ledger too.
    "SEC-IDOR-004": "M5 (needs an internal list endpoint)",
    # The evidence emitter's M3 items — and first a decision about the identifier. The
    # plan says `OPS-EVID-001`; the two tests that exist say `OPS-EVIDENCE-001`, which is
    # M2's id (M2 plan:1358). Coverage is keyed by exact string, so this obligation has
    # zero citations today and the cheapest possible false discharge would be to add the
    # M3 spelling to a docstring that already describes M2's behaviour. Whether they are
    # one obligation or two is the first thing 10C decides.
    "OPS-EVID-001": "M3 slice 10C",
}


def plan_obligations() -> set[str]:
    found: set[str] = set()
    for plan in plans():
        text = plan.read_text(encoding="utf-8")
        for section in _PROVES_SECTION.findall(text):
            found.update(_ID.findall(section))
    return found


def _citation_files() -> list[Path]:
    """Every file that may cite an obligation.

    Python under `tests/`, and **TypeScript under `apps/` and `packages/`**. The
    second half was missing until slice 10: M3's `UI-*` obligations are proved by
    vitest files, so a Python-only scanner reported them uncovered no matter how
    thoroughly they were tested. A gate that cannot see half the suite reports the
    wrong half as the gap, which is worse than reporting nothing.
    """

    files = [path for path in TESTS.rglob("*.py") if path.name != "test_traceability.py"]

    for root in (REPOSITORY_ROOT / "apps", REPOSITORY_ROOT / "packages"):
        for pattern in ("*.ts", "*.tsx"):
            files.extend(
                path
                for path in root.rglob(pattern)
                if "node_modules" not in path.parts
                and ".next" not in path.parts
                # Only test files count as coverage. A `UI-NAV-001` in a comment in
                # `src/auth.ts` explaining *why* the code is shaped a certain way is
                # documentation, not a test — and counting it satisfied the gate for
                # an obligation nothing exercised. Found by the guard-the-guard
                # below, which reported the entry as "already covered".
                and (
                    path.name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"))
                    or "test" in path.parts
                    or "tests" in path.parts
                )
            )
    return sorted(files)


def cited_ids() -> dict[str, set[str]]:
    """Every obligation id cited in the suite, mapped to the files citing it.

    This file is excluded by `_citation_files`: it names ids in `RECORDED_GAPS` and
    `PENDING`, and counting those as coverage would let a gap register itself as
    discharged.
    """

    found: dict[str, set[str]] = {}
    for path in _citation_files():
        for identifier in _ID.findall(path.read_text(encoding="utf-8", errors="replace")):
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
    uncovered = sorted(obligations - set(cited) - set(RECORDED_GAPS) - set(PENDING))

    assert uncovered == [], (
        "these plans claim the following are proved and no test names them:\n"
        + "\n".join(f"  {identifier}" for identifier in uncovered)
        + "\nAdd the id to the docstring of the test that proves it, record it in "
        "RECORDED_GAPS with the reason it will never be discharged, or list it in "
        "PENDING with the slice that owes it."
    )


def test_every_pending_obligation_names_a_slice_that_owes_it(obligations: set[str]) -> None:
    """A pending obligation with no owner is one nobody will write.

    The same rule the IDOR ledger and the ownership-scope exemptions follow: "not
    yet" has to name who, or it is indistinguishable from "not at all".
    """

    for identifier, owner in sorted(PENDING.items()):
        assert identifier in obligations, (
            f"{identifier} is listed as pending and no plan states it — a stale entry "
            "that exempts nothing while reading like a decision"
        )
        assert owner.strip(), f"{identifier} is pending with no owner"


def test_no_pending_obligation_is_already_covered(obligations: set[str]) -> None:
    """Guard the guard, in the other direction.

    An entry in PENDING for an obligation a test already cites is a licence nobody
    is using, and it would silently absorb the next real gap under the same id.
    """

    del obligations
    cited = cited_ids()
    stale = sorted(identifier for identifier in PENDING if identifier in cited)

    assert stale == [], f"pending obligations that are in fact cited: {stale}"


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
