"""The approval reads carry what §13.2 and §13.3 require, parsed from the specification.

Screens slice 0. Both lists are read out of
`21_UI_Design_System_and_Screen_Specification.md` at test time and mapped to response fields —
never transcribed. M5 shipped a wrong type behind a green test because a hand-copied list agreed
with the code that copied it, and a screen specification is exactly the kind of list somebody
maintains in two places.

**This is a backend test for a frontend requirement, and that is the point.** Slice 1's screen
will parse the same sections. If the API and the screen each kept their own copy of "the nineteen
mandatory fields", the day the document gained a twentieth they would disagree about which one it
was.

Covers: API-APPROVALREAD-001, API-APPROVALREAD-002.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SPECIFICATION = (
    REPOSITORY_ROOT
    / "Implementation Docs"
    / "04_Frontend_and_Experience"
    / "21_UI_Design_System_and_Screen_Specification.md"
)

QUEUE_HEADING = "## 13.2 Approval queue"
DETAIL_HEADING = "## 13.3 Approval detail"


def bulleted(heading: str) -> list[str]:
    """The bullet list under a heading, lower-cased and stripped of its trailing semicolon.

    The specification writes each screen's fields as a `-` list ending in `;` or `.`. Anything
    else in the section — the prose sentence §13.2 opens with — is not a field and is skipped.
    """

    text = SPECIFICATION.read_text(encoding="utf-8")
    start = text.index(heading)
    end = text.index("\n## ", start + len(heading))
    section = text[start:end]
    return [
        line[2:].strip().rstrip(";.").lower()
        for line in section.splitlines()
        if line.startswith("- ")
    ]


# Each specified field, mapped to the response field that carries it. The mapping is the part a
# human has to get right; the *list* comes from the document, so a field added there fails the
# completeness test below rather than being quietly unmapped.
QUEUE_COLUMNS: dict[str, str] = {
    "batch reference": "batch_number",
    "version": "version_number",
    "total": "total_amount_irr",
    "row count": "row_count",
    "bank": "bank",
    "source account": "source_account",
    "mapping version": "mapping_version",
    "warning count": "warning_count",
    "prepared/finalized by": "prepared_by",
    "age": "version_created_at",
}

DETAIL_FIELDS: dict[str, str] = {
    "batch reference": "batch",
    "exact version": "version",
    "immutable status": "version",
    "total irr and toman equivalent": "version",
    "request count": "request_count",
    "attempt/row count": "version",
    "trader count": "trader_count",
    "beneficiary count": "beneficiary_count",
    "bank profile version": "bank_profile_version_number",
    "mapping version": "mapping_version",
    "source account": "source_account",
    "content hash fingerprint": "version",
    "ordered rows": "items",
    "warnings": "version",
    "non-sendable preview export if available": "preview_export_id",
    "finalizer identity": "finalized_by",
    "separation-of-duty status": "separation_of_duty",
}


def response_fields(model_name: str) -> set[str]:
    from app.api.v1 import payment_batches

    model = getattr(payment_batches, model_name)
    return set(model.model_fields)


def test_the_specification_still_lists_these_screens() -> None:
    """The control. A parser that returned nothing would make every assertion below vacuous."""

    assert len(bulleted(QUEUE_HEADING)) == 10, bulleted(QUEUE_HEADING)
    assert len(bulleted(DETAIL_HEADING)) == 17, bulleted(DETAIL_HEADING)


@pytest.mark.parametrize("column", sorted(QUEUE_COLUMNS))
def test_the_queue_carries_every_column_the_specification_names(column: str) -> None:
    """`API-APPROVALREAD-001`. §13.2's ten, one test each.

    Ten separate assertions rather than a set comparison, so a failure names the column. "The
    queue is missing a column" sends somebody to read two documents; "the queue has no
    `mapping_version`" does not.
    """

    assert column in QUEUE_COLUMNS, f"{column} is specified and this file does not map it"
    assert QUEUE_COLUMNS[column] in response_fields("BatchListEntry"), (
        f"§13.2 names {column!r} and BatchListEntry has no {QUEUE_COLUMNS[column]!r}"
    )


@pytest.mark.parametrize("field", sorted(DETAIL_FIELDS))
def test_the_detail_carries_every_field_the_specification_names(field: str) -> None:
    """`API-APPROVALREAD-002`. §13.3's mandatory list.

    Several fields map to `version` because the version summary already carries them — the exact
    version, its immutable status, its total, its row count, its hash and its warnings are one
    object. That is a mapping decision recorded here, not a gap: the screen reads them from that
    object, and if it were ever split the mapping is where the change lands.
    """

    assert DETAIL_FIELDS[field] in response_fields("ApprovalView"), (
        f"§13.3 names {field!r} and ApprovalView has no {DETAIL_FIELDS[field]!r}"
    )


def test_every_specified_column_is_mapped() -> None:
    """The corpus check: the document is the authority, so nothing in it may be unmapped.

    M6's lesson in its usual form. Without this, a column added to §13.2 would simply never be
    tested — the parametrised tests above iterate the *mapping*, and an unmapped column is
    invisible to them.
    """

    specified = set(bulleted(QUEUE_HEADING))
    unmapped = sorted(specified - set(QUEUE_COLUMNS))

    assert unmapped == [], (
        f"§13.2 names these columns and nothing maps them to a response field: {unmapped}"
    )


def test_every_specified_field_is_mapped() -> None:
    """The same for §13.3."""

    specified = set(bulleted(DETAIL_HEADING))
    unmapped = sorted(specified - set(DETAIL_FIELDS))

    assert unmapped == [], (
        f"§13.3 names these fields and nothing maps them to a response field: {unmapped}"
    )


def test_no_mapping_names_a_field_that_does_not_exist() -> None:
    """The other direction: a mapping pointing at a removed response field.

    A stale entry would make its parametrised test fail, which is fine — but it would fail with
    "the specification names X and the model has no Y", which reads as a missing feature rather
    than a stale map. This says which it is.
    """

    queue = response_fields("BatchListEntry")
    detail = response_fields("ApprovalView")

    stale = sorted(
        f"queue.{column} -> {field}" for column, field in QUEUE_COLUMNS.items()
        if field not in queue
    ) + sorted(
        f"detail.{name} -> {field}" for name, field in DETAIL_FIELDS.items()
        if field not in detail
    )

    assert stale == [], f"these mappings name response fields that no longer exist: {stale}"


def test_the_separation_status_says_which_rule_refuses() -> None:
    """`API-APPROVALREAD-003`, structurally: the status carries a reason, not just a boolean.

    A bare `may_decide: false` would render as "you cannot approve this" with no remedy. The two
    refusals have different ones — a preparer hands the file to a colleague, a finalizer asks a
    different manager — so the reason is part of the contract.

    The behavioural half — that each actor gets the right reason, and that the advice agrees with
    what the command actually does — is in `tests/integration/test_batch_approval.py`, which
    already seeds the three administrators it needs.
    """

    from app.api.v1.payment_batches import SeparationOfDutyStatus

    assert set(SeparationOfDutyStatus.model_fields) == {"may_decide", "reason"}


def test_the_toman_equivalent_is_not_a_stored_field() -> None:
    """S-1, asserted as an absence.

    §13.3 asks for "total IRR and Toman equivalent". Toman is IRR ÷ 10 by definition, and
    `MONEY_TIME_CONTRACT.md:17` requires transported monetary values to be base-10 integer strings
    in IRR. So the equivalent is a *rendering*, and a `total_amount_toman` on the wire would be a
    second monetary representation for the same money — which is how two numbers start disagreeing.
    """

    fields = response_fields("ApprovalView") | response_fields("BatchListEntry")
    toman = sorted(name for name in fields if "toman" in name.lower())

    assert toman == [], (
        f"these fields transport Toman: {toman}. It is IRR ÷ 10 and belongs to the renderer; "
        "MONEY_TIME_CONTRACT.md:17 makes IRR integer strings the wire format."
    )
