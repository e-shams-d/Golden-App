"""The export reads carry what §14.4 and §14.7 require, parsed from the specification.

Screens slice 2B. Same method as slice 0's `test_approval_read_shape.py`, for the same reason: the
lists are read out of `21_UI_Design_System_and_Screen_Specification.md` at test time and mapped to
response fields, never transcribed. Slice 3's screen parses the same two sections, so the API and
the screen are held to one list rather than two copies that agree until the document changes.

**Two of §14.4's twelve are recorded as absent rather than mapped**, with the plan question that
owns each. A mapping invented for either would point at a field that does not mean what its label
says, which is worse than a gap somebody can see.

Covers: API-EXPORTREAD-001, API-EXPORTREAD-004.
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

DETAIL_HEADING = "## 14.4 Final export detail"
SENT_HEADING = "## 14.7 Mark exact export as sent"


def bulleted(heading: str) -> list[str]:
    """The bullet list under a heading, lower-cased and stripped of its trailing semicolon.

    Ends at the next heading of **any** level, not the next `## `. §14.7 is the last subsection of
    section 14, so the next `## ` is inside section 15 — a parser looking only for that would read
    the bank-result screens' bullets as if they were §14.7's, and every assertion below would still
    pass while testing the wrong list.
    """

    text = SPECIFICATION.read_text(encoding="utf-8")
    start = text.index(heading)
    body = text[start + len(heading) :]
    end = body.index("\n#")
    return [
        line[2:].strip().rstrip(";.").lower()
        for line in body[:end].splitlines()
        if line.startswith("- ")
    ]


# Each specified item, mapped to the response field carrying it. The mapping is the part a human
# has to get right; the *list* comes from the document.
DETAIL_ITEMS: dict[str, str] = {
    "file name": "file_name",
    "checksum": "file_sha256_hash",
    "generation time": "generated_at",
    "exact version": "version_number",
    "approval/hash match": "approval_hash_matches",
    "row count": "row_count",
    "total": "total_amount_irr",
    "mapping": "mapping_version",
    "source account": "source_account",
    "integrity state": "integrity_failed_checks",
}

# §14.4 names these and this slice deliberately returns neither. Each is a plan question, and each
# would need a schema or permission decision rather than a field.
#
# The value is the reason, kept next to the item so a later reader does not have to guess whether
# the omission was considered.
RECORDED_AS_ABSENT: dict[str, str] = {
    "generator version": (
        "S-6. It exists nowhere: §11.8 gives the table no column and app/exports/ has no version "
        "constant. A constant read at request time would name the current writer rather than the "
        "one that produced the file, which is the opposite of what the field is for."
    ),
    "download history where permitted": (
        "S-5. The table records one downloaded_at, not a history, and 'where permitted' names a "
        "permission no catalogue entry defines. The single timestamp is returned; the history is "
        "not invented."
    ),
}

SENT_ITEMS: dict[str, str] = {
    "export reference": "export_number",
    "filename": "file_name",
    "batch/version": "batch_number",
    "checksum/integrity state": "file_sha256_hash",
    "row count": "row_count",
    "total": "total_amount_irr",
    "bank/source account": "source_account",
    "submission channel": "submission_channel",
    "sent time": "sent_to_bank_marked_at",
    "note": "note",
}


def response_fields(model_name: str) -> set[str]:
    from app.api.v1 import bank_exports

    model = getattr(bank_exports, model_name)
    return set(model.model_fields)


def test_the_specification_still_lists_these_screens() -> None:
    """The control. A parser returning nothing would make every assertion below vacuous.

    This has caught a real defect twice in this repository, both times as a list that quietly
    became empty rather than as a comparison that failed.
    """

    assert len(bulleted(DETAIL_HEADING)) == 12, bulleted(DETAIL_HEADING)
    assert len(bulleted(SENT_HEADING)) == 10, bulleted(SENT_HEADING)


@pytest.mark.parametrize("item", sorted(DETAIL_ITEMS))
def test_the_export_detail_carries_every_item_the_specification_names(item: str) -> None:
    """`API-EXPORTREAD-001`. §14.4's list, one test each so a failure names the item."""

    assert DETAIL_ITEMS[item] in response_fields("ExportDetail"), (
        f"§14.4 names {item!r} and ExportDetail has no {DETAIL_ITEMS[item]!r}"
    )


@pytest.mark.parametrize("item", sorted(SENT_ITEMS))
def test_the_confirmation_carries_every_item_the_specification_names(item: str) -> None:
    """`API-EXPORTREAD-004`. §14.7's ten, on the mark-sent response specifically."""

    assert SENT_ITEMS[item] in response_fields("MarkSentConfirmation"), (
        f"§14.7 names {item!r} and MarkSentConfirmation has no {SENT_ITEMS[item]!r}"
    )


def test_the_channel_and_note_are_not_readable_afterwards() -> None:
    """`API-EXPORTREAD-004`'s other half, and it is an absence on purpose.

    §11.8 gives `bank_excel_exports` no column for either, so the confirmation is the only moment
    they can be shown honestly. Asserting they are absent from `ExportDetail` keeps that true: if
    somebody later adds them there, either a column was invented or the values are being read back
    out of an audit payload, and both are things this test should stop.
    """

    later = response_fields("ExportDetail")

    assert "submission_channel" not in later
    assert "note" not in later


def test_every_specified_item_is_mapped_or_recorded_as_absent() -> None:
    """The corpus check: the document is the authority, so nothing in it may be silently unmapped.

    Asserted against the recorded set rather than against nothing, so a *thirteenth* item added to
    §14.4 fails here — which is the case a bare `unmapped == []` would have caught and a
    `RECORDED_AS_ABSENT` subtraction alone would not.
    """

    specified = set(bulleted(DETAIL_HEADING))
    unmapped = sorted(specified - set(DETAIL_ITEMS))

    assert unmapped == sorted(RECORDED_AS_ABSENT), (
        "§14.4's items must each be mapped to a response field or recorded as absent with a "
        f"reason. Unmapped: {unmapped}"
    )

    specified_sent = set(bulleted(SENT_HEADING))
    unmapped_sent = sorted(specified_sent - set(SENT_ITEMS))

    assert unmapped_sent == [], (
        f"§14.7 names these and nothing maps them to a response field: {unmapped_sent}"
    )


def test_no_mapping_names_a_field_that_does_not_exist() -> None:
    """The other direction: a mapping left pointing at a removed field.

    Without this, a stale entry fails as "the specification names X and the model has no Y", which
    reads as a missing feature rather than a stale map.
    """

    detail = response_fields("ExportDetail")
    confirmation = response_fields("MarkSentConfirmation")

    stale = sorted(
        f"detail.{item} -> {field}" for item, field in DETAIL_ITEMS.items() if field not in detail
    ) + sorted(
        f"sent.{item} -> {field}"
        for item, field in SENT_ITEMS.items()
        if field not in confirmation
    )

    assert stale == [], f"these mappings name response fields that no longer exist: {stale}"


def test_each_recorded_absence_carries_a_reason() -> None:
    """A recorded gap with an empty reason is an exemption wearing a gap's clothes.

    M7 had this shape three times: an entry that suppressed a failure and explained nothing, so
    the next reader could not tell whether the omission had been thought about.
    """

    assert RECORDED_AS_ABSENT
    for item, reason in RECORDED_AS_ABSENT.items():
        assert len(reason) > 80, f"{item} is recorded as absent with no real reason"
        assert "S-" in reason, f"{item} is recorded as absent and names no plan question"


def test_the_integrity_field_is_a_list_of_checks_not_a_boolean() -> None:
    """§14.5 says "show each failed check", which a boolean cannot do.

    `SVC-INTEGRITY-001`'s lesson at the read layer: a single `integrity_holds` renders identically
    whether one comparison failed or eight, and an operator investigating needs to know which.
    """

    from app.api.v1.bank_exports import ExportDetail

    annotation = ExportDetail.model_fields["integrity_failed_checks"].annotation

    assert annotation is not bool
    assert "list" in str(annotation), annotation


def test_one_of_the_eight_checks_cannot_disagree_for_a_stored_row() -> None:
    """S-7, pinned so the display cannot quietly start claiming otherwise.

    `_facts_for` fills `export_bank_account_id` from `version.bank_account_id`, because
    `bank_excel_exports` has no account column — so `source_account_matches_approved_account`
    compares one value against itself and always holds. The unit tests for the comparison pass
    because `IntegrityFacts` takes flat values and a test can make any pair disagree; the check is
    inert only for rows that came out of the database, which is the only place it matters.

    **This test asserts the defect, not the fix.** It exists so that whoever resolves S-7 has to
    come here and delete it, rather than a later reader assuming eight live comparisons because the
    field lists eight names. Slice 2B displays what the checks return and neither hides this nor
    pretends to have fixed it.
    """

    import inspect

    from app.commands import bank_export

    source = inspect.getsource(bank_export._facts_for)

    assert "export_bank_account_id=version.bank_account_id" in source, (
        "S-7 appears to have been resolved: the export now supplies its own account. Delete this "
        "test, remove the S-7 row from the plan, and make sure a screen showing the eight checks "
        "is no longer showing one that cannot fail."
    )


def test_a_missing_file_is_not_rendered_as_one_of_the_eight() -> None:
    """A file storage cannot produce is a worse problem than any comparison failing.

    Listing it among the checks would imply the other seven were evaluated, when in fact none of
    them could be: the eighth compares against bytes that are not there. It gets its own name, and
    the name is not one of §15.5's.
    """

    from app.api.v1.bank_exports import MISSING_FILE_CHECK
    from app.exports.integrity import IntegrityCheck

    assert MISSING_FILE_CHECK not in {check.value for check in IntegrityCheck}
    assert not any(MISSING_FILE_CHECK.startswith(check.value) for check in IntegrityCheck)


def test_the_toman_equivalent_is_not_a_stored_field() -> None:
    """S-1 again, on this surface. `MONEY_TIME_CONTRACT.md:17` makes IRR integer strings the wire
    format, so a Toman field here would be a second monetary representation of the same money.
    """

    fields = response_fields("ExportDetail") | response_fields("MarkSentConfirmation")
    toman = sorted(name for name in fields if "toman" in name.lower())

    assert toman == [], f"these fields transport Toman: {toman}"
