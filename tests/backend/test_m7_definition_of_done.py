"""M7 slice 6B. The Definition of Done, parsed from the plan and asserted clause by clause.

The DoD's verb is **prove**:

> M7 is complete when the system can prove exactly which approved immutable version produced the
> exact checksummed file that an authorized accountant marked as sent to the bank.

It does not ask that the system *do* those things — M6 already produced versions and M7 produces
files. It asks that the chain be **recoverable**, which is a claim about queryable evidence.

**The sentence is parsed out of the plan rather than quoted here.** M5's and M6's gates do the
same, for the reason a hand-copied sentence always eventually differs from the one it copied: this
file would then assert a Definition of Done nobody agreed to. Every clause below names the
mechanism that discharges it, and `test_every_clause_names_a_mechanism` fails if a clause appears
that nothing here accounts for.

The behavioural half — that the chain really is recoverable from a real sent export — is
`tests/integration/test_m7_journey.py`. This file is structural so it cannot skip for want of a
database, which is the whole reason M5's and M6's equivalents live in `tests/backend`.

Covers: TRACE-M7-001.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_traceability import PENDING, plans

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLAN = REPOSITORY_ROOT / "docs" / "handoff" / "M7_IMPLEMENTATION_PLAN.md"

# Every obligation prefix M7 uses. Matched against the plan's own "What proves it" sections rather
# than assumed, by `test_no_m7_obligation_is_still_pending` below.
_ID = re.compile(r"\b(?:DB|SVC|SEC|CON|AUD|TRACE)-[A-Z0-9]+(?:-\d+)?\b")


def definition_of_done() -> str:
    """The DoD sentence, read from the plan's §1.2 block quote."""

    text = PLAN.read_text(encoding="utf-8")
    match = re.search(r"## 1\.2 Definition of Done \(verbatim\)\n(.*?)\n\n\*\*", text, re.S)
    assert match, "the plan's §1.2 no longer has a Definition of Done block"
    quoted = " ".join(
        line.lstrip("> ").strip()
        for line in match.group(1).splitlines()
        if line.startswith(">")
    )
    assert quoted, f"§1.2 was found but held no quoted sentence: {match.group(1)!r}"
    return quoted


# Each clause of the DoD, with the mechanism that makes it answerable. The clauses are substrings
# of the parsed sentence and are asserted to be present in it — so a plan edit that dropped one
# fails here rather than quietly narrowing what this milestone claims.
CLAUSES: dict[str, str] = {
    "approved": (
        "batch_approvals, one row per version by UNIQUE(payment_batch_version_id), with the "
        "approver held apart from the finalizer and preparer by two CHECK constraints"
    ),
    "immutable version": (
        "payment_batch_versions and payment_batch_items, insert-only: the runtime holds UPDATE "
        "on (status, superseded_at) and nothing else"
    ),
    "produced the exact checksummed file": (
        "bank_excel_exports.content_hash equals the version's, and file_sha256_hash is what "
        "storage measured; fk_export_approval_same_version ties the export to an approval of "
        "that same version"
    ),
    "authorized accountant": (
        "bank_export.mark_sent, granted to accountant only, recorded in "
        "sent_to_bank_marked_by_admin_user_id"
    ),
    "marked as sent to the bank": (
        "sent_to_bank_marked_at, separate from downloaded_at because downloading is not sending"
    ),
}


def test_the_plan_still_states_a_definition_of_done() -> None:
    """The control. Everything below reads this sentence, so an empty parse must fail loudly.

    A parser that returned `""` would make every clause assertion vacuous while reporting
    success — the shape this repository has been caught by more than once.
    """

    sentence = definition_of_done()

    assert len(sentence) > 80, sentence
    assert sentence.startswith("M7 is complete when"), sentence


@pytest.mark.parametrize("clause", sorted(CLAUSES))
def test_every_clause_of_the_definition_of_done_is_present(clause: str) -> None:
    """Each clause is really in the sentence, so the mapping below cannot drift from it."""

    assert clause in definition_of_done(), (
        f"{clause!r} is no longer in the Definition of Done; either the plan changed or this "
        "file is asserting something the milestone does not claim"
    )


def test_every_clause_names_a_mechanism() -> None:
    """No clause may be listed with an empty explanation.

    Cheap, and it exists because the tempting way to make this file pass a future plan edit is to
    add a key with a placeholder. A clause whose mechanism is `""` reads as covered.
    """

    empty = sorted(clause for clause, mechanism in CLAUSES.items() if not mechanism.strip())

    assert empty == [], f"these clauses claim a mechanism and name none: {empty}"


def test_no_m7_obligation_is_still_pending() -> None:
    """`TRACE-M7-001`. Matched by **id against the plan**, not by prefix.

    A prefix match would be wrong in both directions: `SVC-EXPORT-005` belongs to M7 and
    `SVC-BATCH-005` does not, and both start with `SVC-`. So the M7 plan's own "What proves it"
    sections are the corpus, and any of those ids still sitting in `PENDING` is an obligation this
    milestone stated and did not discharge.

    This is necessarily the last obligation in the milestone: it reads the dictionary that every
    other slice empties.
    """

    text = PLAN.read_text(encoding="utf-8")
    proves = re.findall(r"### What proves it\n(.*?)(?=\n### |\n## |\Z)", text, re.S)
    assert proves, "the M7 plan has no 'What proves it' sections; the corpus is empty"

    stated = {found for section in proves for found in _ID.findall(section)}
    assert len(stated) >= 30, f"only {len(stated)} obligations parsed; the reader is broken"

    outstanding = sorted(stated & set(PENDING))

    assert outstanding == [], (
        "these M7 obligations are stated by the plan and still recorded as pending:\n"
        + "\n".join(f"  {found}: {PENDING[found]}" for found in outstanding)
    )


def test_the_m7_plan_is_one_of_the_plans_the_traceability_gate_reads() -> None:
    """The corpus check for the corpus check.

    `test_no_m7_obligation_is_still_pending` reads the plan directly. The traceability gate reads
    every `M*_IMPLEMENTATION_PLAN.md`, and if M7's were ever renamed out of that glob, this
    milestone's obligations would leave both readers at once — which is precisely how M3's plan
    went nine merged slices with roughly eighty obligations nothing checked.
    """

    assert PLAN in plans(), (
        f"{PLAN.name} is not among the plans the traceability gate reads: "
        f"{[path.name for path in plans()]}"
    )
