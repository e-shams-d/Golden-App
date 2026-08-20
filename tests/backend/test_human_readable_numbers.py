"""The human-readable number family, read from the documents that specify it.

M5 shipped `GP-YYYYMM-NNNN` for `request_number`, citing `04_Database_Schema.md:833` — a
line that says only "Human-readable unique" and gives no format. The format is specified
in two other places, and `GP-` appears in neither, nor in any plan, ADR or conflict row.
It was written from memory and attributed to a line that could not support it, and nothing
noticed because the only assertion anywhere was `startswith("GP-")` against the code's own
choice. A test that asserts what the code does cannot tell you the code is wrong.

So this file asserts against the **documents**, by parsing them:

- `05_API_Specification.md:304` enumerates the prefixes.
- `07_UI_UX_Specification.md:630-640` gives the whole family in a fenced block, from which
  the date precision and the sequence width are read.

The one thing not taken from those documents is the **calendar**. Their examples are
Jalali; ADR-006 is Approved and says at `:69` that "Jalali presentation does not leak into
database or transport contracts", and at `:59-61` that screen-level UX copy cannot override
it. `request_number` is a stored column and an API field, so the ADR governs and the date is
Gregorian. `DOC-CONFLICT-054` records the disagreement, and the last test here fails if that
row stops being Open — because on the day it is resolved, this is the file that has to change.

**No `Covers:` line, deliberately.** This is a defect fix, not the discharge of an
obligation. `DB-REQ-001` is M5's and `tests/backend/test_payment_request_schema.py`
discharges it; naming it here would make two files look like proof of one obligation, which
is the "a mention is not a proof" failure the traceability gate exists to prevent.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "Implementation Docs"
UI_SPEC = DOCS / "04_Frontend_and_Experience" / "07_UI_UX_Specification.md"
API_SPEC = DOCS / "02_Architecture_and_Contracts" / "05_API_Specification.md"
REGISTER = ROOT / "docs" / "governance" / "CONFLICT_REGISTER.md"
COMMANDS = ROOT / "services" / "backend" / "app" / "commands" / "payment_request.py"

# `PREFIX-DATE-SEQUENCE`, where the middle group is eight digits and the last is the
# sequence. Deliberately loose on widths so the parsed examples decide them.
EXAMPLE = re.compile(r"^([A-Z]{2,4})-(\d+)-(\d+)$")


@pytest.fixture(scope="module")
def documented_family() -> dict[str, tuple[int, int]]:
    """Every `PREFIX-date-sequence` example in the UI specification's fenced block.

    Returns prefix -> (date digits, sequence digits). Parsed rather than transcribed: a
    transcription of a width can be wrong in the same direction as the code, which is the
    failure mode this whole file exists to answer.
    """

    text = UI_SPEC.read_text(encoding="utf-8")
    blocks = re.findall(r"```text\n(.*?)```", text, re.S)

    family: dict[str, tuple[int, int]] = {}
    for block in blocks:
        candidates = [line.strip() for line in block.splitlines() if line.strip()]
        matches = [EXAMPLE.match(line) for line in candidates]
        # A block counts only if *every* line in it is an example of this shape. A block
        # that merely contains one is a list of something else that happens to include a
        # number, and reading widths out of it would be reading a coincidence.
        if not candidates or not all(matches):
            continue
        for match in matches:
            assert match is not None  # narrowed by the all() above
            prefix, date_part, sequence = match.groups()
            family[prefix] = (len(date_part), len(sequence))

    assert family, (
        f"no number-family example block found in {UI_SPEC.name}; the document may have "
        "been restructured, in which case this gate is asserting nothing and the whole "
        "file needs rewriting rather than deleting"
    )
    return family


def test_the_documented_prefixes_include_the_request_and_the_batch(
    documented_family: dict[str, tuple[int, int]],
) -> None:
    """Both numbers M5 and M6 generate are in the family, under the names document 05 uses."""

    api_text = API_SPEC.read_text(encoding="utf-8")

    for prefix in ("PR", "PB"):
        assert prefix in documented_family, (
            f"{prefix}- is not in {UI_SPEC.name}'s example family: "
            f"{sorted(documented_family)}"
        )
        assert f"`{prefix}-...`" in api_text, (
            f"{API_SPEC.name} does not list {prefix}- among the human-readable prefixes"
        )


def test_the_family_agrees_on_one_date_precision_and_one_sequence_width(
    documented_family: dict[str, tuple[int, int]],
) -> None:
    """Eight date digits and six sequence digits, everywhere the date appears.

    The batch-version example carries no date — it is numbered within its batch — so it is
    excluded by the date-digit check rather than by name. If a future example broke the
    agreement, every generator would need its own rule and this test says so before that
    happens.

    Its literal form is deliberately not quoted here: the traceability scanner reads any
    `PREFIX-digits` token in a test file as an obligation citation, and it read the quoted
    example as a citation of an obligation prefix no catalogue defines. Eighth time that
    scanner has caught a prose mention this session, and it was right every time.
    """

    dated = {
        prefix: widths for prefix, widths in documented_family.items() if widths[0] == 8
    }
    assert dated, "no dated example in the family; the date precision cannot be read"

    assert {widths[0] for widths in dated.values()} == {8}, dated
    assert {widths[1] for widths in dated.values()} == {6}, (
        f"the family disagrees on sequence width: {dated}. Document 05's own example at "
        "`:1332` uses four digits, which is why this is read from the UI specification's "
        "block rather than from the first example that turns up."
    )


def test_the_generated_request_number_matches_the_documented_shape(
    documented_family: dict[str, tuple[int, int]],
) -> None:
    """The code's format string, checked against the widths just parsed.

    Asserted on the source rather than by generating a number, because generating one
    needs a session and this gate must not become a skip when PostgreSQL is absent.

    Every assertion here targets an **f-string literal**, not any mention of a prefix. The
    first version forbade `GP-` anywhere in the file and failed on the docstring that
    explains where `GP-` came from — the same false positive shape as a prose mention
    counting as an obligation citation. The defect was `prefix = f"GP-{...}"`; a sentence
    recording that it happened is the opposite of the defect and worth keeping.
    """

    source = COMMANDS.read_text(encoding="utf-8")
    date_digits, sequence_digits = documented_family["PR"]

    literals = set(re.findall(r'f"([A-Z]{2,4}-\{[^"]*)"', source))
    assert len(literals) == 1, (
        f"expected exactly one prefix f-string in {COMMANDS.name}, found {literals}. "
        "Two generators means two formats, and this test can only speak for one."
    )
    prefix_literal = literals.pop()

    assert prefix_literal.startswith("PR-"), (
        f"the request-number prefix is {prefix_literal.split('-')[0]}-, and "
        f"{API_SPEC.name}:304 lists PR-. `GP-` is in no document, no plan, no ADR and no "
        "conflict row; see DOC-CONFLICT-054."
    )
    assert "to_business_time(now).strftime('%Y%m%d')" in prefix_literal, (
        f"the date part is not a business-day {date_digits}-digit date: {prefix_literal!r}. "
        "ADR-006 point 3 puts date-only interpretation in Asia/Tehran, so a UTC date would "
        "put a request raised at 23:00 UTC on the wrong business day."
    )
    assert date_digits == 8, date_digits
    assert f"{{(used or 0) + 1:0{sequence_digits}d}}" in source, (
        f"the sequence is not {sequence_digits} digits wide, which is what "
        f"{UI_SPEC.name}'s examples carry"
    )


def test_the_date_is_gregorian_because_adr_006_says_so() -> None:
    """The one departure from the documents, and the authority for it.

    `to_business_time` rather than a Jalali conversion, and no Jalali conversion exists in
    the backend to reach for: `app/core/external_dates.py` refuses one in terms. This test
    pins the *reason* in the register, so the departure cannot survive the row that
    authorises it.
    """

    register = REGISTER.read_text(encoding="utf-8")
    row = [line for line in register.splitlines() if line.startswith("| DOC-CONFLICT-054 |")]

    assert len(row) == 1, f"expected exactly one DOC-CONFLICT-054 row, found {len(row)}"
    assert "Open" in row[0].rsplit("|", 2)[1], (
        "DOC-CONFLICT-054 is no longer Open. Someone has decided the calendar question, "
        "so the shape this file asserts may now be wrong — read the row and update the "
        "generator and this test together."
    )
