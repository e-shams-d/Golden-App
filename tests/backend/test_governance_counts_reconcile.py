"""The conflict register's counts must equal its rows. Enforced, not trusted.

`CONFLICT_REGISTER.md` states its own rule: *"Count authority: the rows below. This
header and the summary table are derived from them and must be reconciled by
enumeration whenever a row is added or resolved."* That is a rule nobody can follow
reliably by hand — the register has three derived places (a header sentence, a
three-row summary table, and a total) and forty-three rows spread across two tables.

The cost of it drifting is not cosmetic. The M2 implementation plan was written
against a register that read "7 Resolved; 26 Open" and instructed slice 10 to correct
records that had already been corrected. A planner reading a stale count blocks work
that is unblocked, or proceeds on one that is not.

So this file recomputes every derived number from the rows and requires them to
agree. It also checks the two documents that quote those numbers, because a count
that is right in one file and stale in the next is the same failure one step further
away.

Covers: CI-MANIFEST-001.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

GOVERNANCE = Path(__file__).resolve().parents[2] / "docs" / "governance"
REGISTER = GOVERNANCE / "CONFLICT_REGISTER.md"
README = GOVERNANCE / "README.md"

# A row in the main table: id, severity, then eight more cells ending in the status.
_ROW = re.compile(r"^\|\s*(DOC-CONFLICT-\d+)\s*\|\s*(Critical|Important)\s*\|")


def register_rows() -> dict[str, tuple[str, str]]:
    """Every distinct conflict id with its severity and resolution status.

    Distinct by id and first occurrence: seven ids also appear in the blocking-order
    table further down, and counting those twice is precisely the arithmetic error
    this test exists to prevent.
    """

    rows: dict[str, tuple[str, str]] = {}
    for line in REGISTER.read_text(encoding="utf-8").splitlines():
        match = _ROW.match(line)
        if not match or match.group(1) in rows:
            continue
        cells = [cell.strip() for cell in line.split("|") if cell.strip()]
        rows[match.group(1)] = (match.group(2), cells[-1])
    return rows


@pytest.fixture(scope="module")
def rows() -> dict[str, tuple[str, str]]:
    found = register_rows()
    assert found, "no conflict rows parsed; the register's table layout changed"
    return found


def tally(rows: dict[str, tuple[str, str]]) -> dict[str, int]:
    severities = Counter(severity for severity, _ in rows.values())
    resolved = Counter(
        severity for severity, status in rows.values() if status.startswith("Resolved")
    )
    return {
        "total": len(rows),
        "resolved": sum(resolved.values()),
        "open": len(rows) - sum(resolved.values()),
        "critical": severities["Critical"],
        "critical_open": severities["Critical"] - resolved["Critical"],
        "important": severities["Important"],
        "important_open": severities["Important"] - resolved["Important"],
    }


def test_every_row_carries_a_recognised_status(rows: dict[str, tuple[str, str]]) -> None:
    """`Open` or `Resolved`, nothing else.

    A row ending in prose rather than a status silently becomes "not resolved" in
    every count below, and the register would look consistent while meaning
    something nobody chose.
    """

    unrecognised = {
        ident: status
        for ident, (_severity, status) in rows.items()
        if not status.startswith(("Open", "Resolved"))
    }

    assert unrecognised == {}, f"rows with an unparseable status: {unrecognised}"


def test_the_header_sentence_matches_the_rows(rows: dict[str, tuple[str, str]]) -> None:
    counts = tally(rows)
    text = REGISTER.read_text(encoding="utf-8")

    match = re.search(r"(\d+) decisions Resolved/Approved; (\d+) conflicts Open", text)

    assert match, "the register header no longer states its counts in the expected form"
    assert (int(match.group(1)), int(match.group(2))) == (counts["resolved"], counts["open"]), (
        f"header says {match.group(1)} resolved / {match.group(2)} open; "
        f"the rows say {counts['resolved']} / {counts['open']}"
    )


def test_the_closing_paragraph_matches_the_rows(rows: dict[str, tuple[str, str]]) -> None:
    """The sixth restatement site, and the one that stayed wrong the longest.

    The register's closing paragraph read "Twenty-six conflicts remain Open. Seven
    decisions are Resolved — Approved" while its header said 23 and 21. The 2026-08-06
    note in the same file records that exact pair — "7 Resolved; 26 Open" — as having
    already been corrected, so the sentence the note was about survived the correction
    the note describes.

    It survived because it **spelled its numbers as words**, and every one of the five
    reconciliation tests above matches `(\\d+)`. A restatement is only checked in the
    notation somebody thought to check, which is the same shape as the defect this whole
    file exists to catch. The paragraph now uses digits and this reads it.
    """

    counts = tally(rows)
    text = REGISTER.read_text(encoding="utf-8")

    match = re.search(
        r"(\d+) conflicts remain Open\. (\d+) decisions are Resolved", text
    )

    assert match, (
        "the register's closing paragraph no longer states its counts in digits. If it "
        "was reworded, reword it with digits: this site was wrong for two milestones "
        "because it spelled them out and nothing could read it"
    )
    assert (int(match.group(1)), int(match.group(2))) == (counts["open"], counts["resolved"]), (
        f"the closing paragraph says {match.group(1)} open / {match.group(2)} resolved; "
        f"the rows say {counts['open']} / {counts['resolved']}"
    )


def test_no_count_in_the_register_is_spelled_as_a_word(rows: dict[str, tuple[str, str]]) -> None:
    """Guard the guard for the test above.

    Restoring the words would make that test fail on its `assert match` — but only while
    the phrasing stays recognisable. This refuses the number-words outright in the two
    sentences that carry counts, so the failure mode cannot come back by rewording.
    """

    del rows
    text = REGISTER.read_text(encoding="utf-8")

    # Anchored at the start of the line, so a sentence that *quotes* the old wording —
    # the note recording this very correction does — is prose about a count rather than
    # a count. The distinction is the whole reason this is anchored and not a substring
    # search: the first version of this test failed on the note explaining it.
    statements = re.findall(r"^(\S+) conflicts remain Open", text, re.M)

    assert statements, "the register's closing count statement has gone missing entirely"
    for stated in statements:
        assert stated.isdigit(), (
            f"the register opens its count sentence with {stated!r}. Counts are "
            "reconciled by enumeration and must be written in digits so they can be "
            "read — this exact sentence was wrong for two milestones because it was "
            "spelled out and no test could see it"
        )


def test_the_summary_table_matches_the_rows(rows: dict[str, tuple[str, str]]) -> None:
    counts = tally(rows)
    text = REGISTER.read_text(encoding="utf-8")

    expected = {
        "Critical": (
            counts["critical_open"],
            counts["critical"] - counts["critical_open"],
            counts["critical"],
        ),
        "Important": (
            counts["important_open"],
            counts["important"] - counts["important_open"],
            counts["important"],
        ),
        "Total": (counts["open"], counts["resolved"], counts["total"]),
    }

    for label, (open_count, resolved, total) in expected.items():
        match = re.search(rf"\|\s*{label}\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|", text)
        assert match, f"the summary table has no {label} row"
        actual = tuple(int(group) for group in match.groups())
        assert actual == (open_count, resolved, total), (
            f"summary row {label} says {actual}; the rows say {(open_count, resolved, total)}"
        )


def test_no_critical_conflict_is_open(rows: dict[str, tuple[str, str]]) -> None:
    """Stated in the header, and load-bearing for every milestone gate.

    Asserted separately from the arithmetic above so the failure names the thing that
    actually matters rather than a mismatched number.
    """

    still_open = [
        ident
        for ident, (severity, status) in rows.items()
        if severity == "Critical" and not status.startswith("Resolved")
    ]

    assert still_open == [], f"Critical conflicts are open: {still_open}"


def test_the_governance_readme_agrees_with_the_register(
    rows: dict[str, tuple[str, str]],
) -> None:
    """The same numbers, one file away.

    `README.md` restates the register's totals for a reader who never opens it, which
    means it is a second place for them to go stale.
    """

    counts = tally(rows)
    match = re.search(
        r"CONFLICT_REGISTER\.md — (\d+) conflicts: (\d+) Resolved/Approved and (\d+) Open",
        README.read_text(encoding="utf-8"),
    )

    assert match, "the governance README no longer restates the conflict counts"
    assert tuple(int(group) for group in match.groups()) == (
        counts["total"],
        counts["resolved"],
        counts["open"],
    ), (
        f"README says {match.groups()}; the register rows say "
        f"{(counts['total'], counts['resolved'], counts['open'])}"
    )


def test_the_manifest_decision_state_agrees_with_the_register(
    rows: dict[str, tuple[str, str]],
) -> None:
    """The third place the counts live, and the easiest one to miss.

    `m0_manifest.py --write` deliberately recomputes only digests and byte counts; it
    prints a reminder that `decision_state` is editorial and must be reviewed by hand.
    A reminder is not a gate, and this field was stale until slice 10 — the manifest
    was certifying correct hashes over wrong counts, which is the failure it exists to
    prevent, one level up.
    """

    import json

    counts = tally(rows)
    state = json.loads((GOVERNANCE / "M0_MANIFEST.json").read_text(encoding="utf-8"))[
        "decision_state"
    ]

    assert state["total_conflicts"] == counts["total"]
    assert state["open_conflicts"] == counts["open"]

    listed = set(state["resolved_conflicts"])
    actual = {ident for ident, (_sev, status) in rows.items() if status.startswith("Resolved")}

    assert listed == actual, (
        f"manifest lists {sorted(listed - actual)} as resolved that the register does not, "
        f"and omits {sorted(actual - listed)}"
    )


# A canonical decision row. `ADR-AI-###` is the shape that broke the first attempt at
# counting these: a pattern of `(ADR|POL|OPS|PKG)-\d+` misses all eight AI rows and
# derives 25 instead of 33. The prefix may contain hyphens, so the row id is matched
# as a whole rather than as a known prefix plus a number.
_DECISION_ROW = re.compile(r"^\|\s*([A-Z][A-Z0-9-]+-\d+)\s*\|")


def decision_rows() -> tuple[dict[str, str], set[str]]:
    """Every canonical decision id, and which of them are Approved.

    First occurrence wins: three ids also appear in the approved-evidence table below
    the main one, and counting those twice is the same arithmetic error the conflict
    register's blocking-order table invites.
    """

    text = (Path(__file__).resolve().parents[2] / "docs" / "adr" / "ADR_INDEX.md").read_text(
        encoding="utf-8"
    )
    rows: dict[str, str] = {}
    approved: set[str] = set()
    for line in text.splitlines():
        match = _DECISION_ROW.match(line)
        if not match:
            continue
        rows.setdefault(match.group(1), line)
        if "**Approved" in line:
            approved.add(match.group(1))
    return rows, approved


def test_the_adr_count_table_matches_its_rows() -> None:
    """The same rule the conflict register states, applied to the decision index.

    This was written after deriving 25 from a parser that missed the `ADR-AI-###`
    rows and writing that number into three files. The count table said 33 the whole
    time; nothing compared them.
    """

    rows, approved = decision_rows()
    text = (Path(__file__).resolve().parents[2] / "docs" / "adr" / "ADR_INDEX.md").read_text(
        encoding="utf-8"
    )

    for label, expected in (
        ("Total", len(rows)),
        ("Approved", len(approved)),
        ("Open", len(rows) - len(approved)),
    ):
        match = re.search(rf"\|\s*{label}\s*\|\s*(\d+)\s*\|", text)
        assert match, f"the ADR count table has no {label} row"
        assert int(match.group(1)) == expected, (
            f"the count table says {label} {match.group(1)}; the rows say {expected}"
        )


def test_the_adr_header_matches_its_rows() -> None:
    rows, approved = decision_rows()
    text = (Path(__file__).resolve().parents[2] / "docs" / "adr" / "ADR_INDEX.md").read_text(
        encoding="utf-8"
    )

    match = re.search(r"Decision state: (.*?) Approved; (\d+) entries remain Open", text)

    assert match, "the ADR index header no longer states its counts in the expected form"
    assert int(match.group(2)) == len(rows) - len(approved)
    for identifier in approved:
        assert identifier in match.group(1), f"{identifier} is Approved but absent from the header"


def test_the_readme_matches_the_adr_index() -> None:
    rows, approved = decision_rows()

    match = re.search(
        r"ADR_INDEX\.md — (\d+) canonical decisions: (.*?) Approved, (\d+) Open",
        README.read_text(encoding="utf-8"),
    )

    assert match, "the governance README no longer restates the decision counts"
    assert (int(match.group(1)), int(match.group(3))) == (len(rows), len(rows) - len(approved))


def test_the_traceability_matrix_matches_both_registers() -> None:
    """The matrix's M0 row restates both count sets, so it is a fifth copy.

    It held `33 conflicts: 7 Resolved/Approved and 26 Open, including 5 Critical` while
    the register said 43/20/23 and no open Critical — stale by ten conflicts and by the
    one number a reader would act on. Restating a count is fine; restating it ungated is
    what produces a document that argues with itself.
    """

    rows, approved = decision_rows()
    matrix = (GOVERNANCE / "TRACEABILITY_MATRIX.md").read_text(encoding="utf-8")
    register = (GOVERNANCE / "CONFLICT_REGISTER.md").read_text(encoding="utf-8")

    decisions = re.search(
        r"ADR_INDEX\.md contains (\d+) decisions: (.*?) Approved; (\d+) Open", matrix
    )
    assert decisions, "the matrix no longer restates the decision counts"
    assert (int(decisions.group(1)), int(decisions.group(3))) == (
        len(rows),
        len(rows) - len(approved),
    )
    for identifier in approved:
        assert identifier in decisions.group(2), f"{identifier} is Approved and unlisted"

    totals = re.search(r"\|\s*Total\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|", register)
    critical = re.search(r"\|\s*Critical\s*\|\s*(\d+)\s*\|", register)
    assert totals and critical, "the conflict register no longer states its totals"
    open_count, resolved, total = (int(value) for value in totals.groups())

    conflicts = re.search(
        r"CONFLICT_REGISTER\.md contains (\d+) conflicts: (\d+) Resolved/Approved and "
        r"(\d+) Open, (none|including \d+) Critical",
        matrix,
    )
    assert conflicts, "the matrix no longer restates the conflict counts"
    assert (int(conflicts.group(1)), int(conflicts.group(2)), int(conflicts.group(3))) == (
        total,
        resolved,
        open_count,
    ), "the matrix and the conflict register disagree on the conflict counts"

    stated_critical = 0 if conflicts.group(4) == "none" else int(conflicts.group(4).split()[-1])
    assert stated_critical == int(critical.group(1)), (
        "the matrix and the register disagree on how many Critical conflicts are open"
    )


def test_the_manifest_lists_every_approved_decision() -> None:
    """The manifest names them in prose, so it is a fourth place to go stale."""

    import json

    _rows, approved = decision_rows()
    listed = json.loads((GOVERNANCE / "M0_MANIFEST.json").read_text(encoding="utf-8"))[
        "decision_state"
    ]["approved_canonical_decisions"]

    for identifier in sorted(approved):
        assert any(entry.startswith(identifier) for entry in listed), (
            f"{identifier} is Approved in the index and absent from the manifest"
        )
    assert len(listed) == len(approved), (
        f"the manifest lists {len(listed)} approved decisions; the index has {len(approved)}"
    )


def test_ids_are_unique_and_unbroken(rows: dict[str, tuple[str, str]]) -> None:
    """A gap or a reused id makes every citation ambiguous.

    Citations name conflicts by id, so a reused number points two different readers
    at two different rows, and a gap usually means a row was deleted rather than
    resolved — which is how a conflict stops being tracked without being decided.
    """

    numbers = sorted(int(ident.rsplit("-", 1)[1]) for ident in rows)

    assert numbers == list(range(1, len(numbers) + 1)), (
        "conflict ids are not a contiguous run from 1; "
        f"missing {sorted(set(range(1, numbers[-1] + 1)) - set(numbers))}"
    )


def test_the_catalogue_approval_claim_names_each_catalogue(
    rows: dict[str, tuple[str, str]],
) -> None:
    """Two catalogues are approved and three are not.

    The README used to say all five were provisional, which was false for status and
    permission after 2026-08-01 — and it matters because a CI gate may only be written
    against an approved catalogue. A blanket claim in either direction licenses the
    wrong thing.
    """

    import yaml

    text = README.read_text(encoding="utf-8")
    for name, expected in (
        ("status_catalog", "approved_phase_1a"),
        ("permission_catalog", "approved_phase_1a"),
        ("api_error_catalog", "provisional_pending_m0_approval"),
        ("command_catalog", "provisional_pending_m0_approval"),
        ("audit_outbox_catalog", "provisional_pending_m0_approval"),
    ):
        document = yaml.safe_load((GOVERNANCE / f"{name}.yaml").read_text(encoding="utf-8"))
        # Two shapes: the approved catalogues put `catalog_status` at the top level,
        # the three JSON-shaped ones nest `status` under `metadata`. Read both rather
        # than normalising the files — reformatting a governance artifact to suit a
        # test is the wrong direction, and the manifest hashes them.
        actual = (
            document.get("catalog_status")
            or document.get("status")
            or document.get("metadata", {}).get("status")
        )
        assert actual == expected, f"{name}.yaml carries status {actual!r}, expected {expected!r}"
        assert f"`{name}.yaml`" in text, f"the README does not name {name}.yaml in its status list"
