"""Eight comparisons, eight failing cases, and one test that all eight exist.

M7 slice 3. `15_Agent_Implementation_Plan.md` §15.5 lists eight equalities to verify before a
final download or a mark-sent.

**Why eight tests rather than one.** `SVC-INTEGRITY-001` says "each with its own failing case",
and M6 is why it says that: a hash test written as `"content hash" in text or "sum to" in text`
passed with either guard removed, because a disjunction is satisfied by whichever half survives.
A single `assert holds(facts) is False` on a fixture with everything wrong would pass with seven
of the eight comparisons deleted.

So each test below breaks **exactly one** field and asserts that **exactly that** check is
reported. Breaking one and asserting "some failure" would be the same mistake one level down.

Covers: SVC-INTEGRITY-001.
"""

from __future__ import annotations

import uuid

import pytest
from app.exports.integrity import (
    IntegrityCheck,
    IntegrityFacts,
    failed_checks,
    holds,
)

VERSION_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
MAPPING_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
ACCOUNT_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
OTHER_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")

CONTENT_HASH = "a" * 64
FILE_HASH = "b" * 64
OTHER_HASH = "c" * 64


def consistent(**overrides: object) -> IntegrityFacts:
    """A set of facts where all eight hold, with one field replaceable per test."""

    fields: dict[str, object] = {
        "export_version_id": VERSION_ID,
        "export_content_hash": CONTENT_HASH,
        "export_total_amount_irr": 1_500_000_000,
        "export_row_count": 3,
        "export_bank_mapping_id": MAPPING_ID,
        "export_bank_account_id": ACCOUNT_ID,
        "export_file_sha256_hash": FILE_HASH,
        "version_id": VERSION_ID,
        "version_content_hash": CONTENT_HASH,
        "version_total_amount_irr": 1_500_000_000,
        "version_row_count": 3,
        "version_bank_mapping_id": MAPPING_ID,
        "version_bank_account_id": ACCOUNT_ID,
        "approval_version_id": VERSION_ID,
        "approval_content_hash": CONTENT_HASH,
        "measured_file_sha256_hash": FILE_HASH,
    }
    fields.update(overrides)
    return IntegrityFacts(**fields)  # type: ignore[arg-type]


def test_a_consistent_export_passes_every_check() -> None:
    """The control, and it is not decoration.

    Without it, a function that reported all eight as failed unconditionally would satisfy every
    other test in this file — each of them asserts a failure, and each would find one.
    """

    assert failed_checks(consistent()) == ()
    assert holds(consistent()) is True


# Each entry is one field of the fixture, the value that breaks it, and the check that must be
# the one reported. Parametrised rather than written out eight times so that adding a ninth
# comparison to §15.5 is a line here, and so the *mapping* between field and check is visible in
# one place instead of spread over eight docstrings.
BREAKAGES: tuple[tuple[str, object, IntegrityCheck], ...] = (
    (
        "export_version_id",
        OTHER_ID,
        IntegrityCheck.EXPORT_VERSION_IS_THE_APPROVED_VERSION,
    ),
    (
        "export_content_hash",
        OTHER_HASH,
        IntegrityCheck.EXPORT_CONTENT_HASH_MATCHES_VERSION,
    ),
    (
        "approval_content_hash",
        OTHER_HASH,
        IntegrityCheck.APPROVAL_HASH_MATCHES_VERSION,
    ),
    (
        "export_total_amount_irr",
        1_500_000_001,
        IntegrityCheck.EXPORT_TOTAL_MATCHES_VERSION,
    ),
    (
        "export_row_count",
        4,
        IntegrityCheck.EXPORT_ROW_COUNT_MATCHES_VERSION,
    ),
    (
        "export_bank_mapping_id",
        OTHER_ID,
        IntegrityCheck.MAPPING_MATCHES_APPROVED_MAPPING,
    ),
    (
        "export_bank_account_id",
        OTHER_ID,
        IntegrityCheck.SOURCE_ACCOUNT_MATCHES_APPROVED_ACCOUNT,
    ),
    (
        "measured_file_sha256_hash",
        OTHER_HASH,
        IntegrityCheck.FILE_CHECKSUM_MATCHES_STORED_CHECKSUM,
    ),
)


@pytest.mark.parametrize(("field", "broken_value", "expected_check"), BREAKAGES)
def test_breaking_one_field_reports_exactly_that_check(
    field: str, broken_value: object, expected_check: IntegrityCheck
) -> None:
    """One field wrong, one check reported, and nothing else.

    The `== (expected_check,)` is the strict part. `expected_check in reported` would pass on an
    implementation that reported all eight every time — which is exactly as useless as reporting
    none, and much harder to notice because the failure looks thorough.
    """

    facts = consistent(**{field: broken_value})
    reported = tuple(failure.check for failure in failed_checks(facts))

    assert reported == (expected_check,), (
        f"breaking {field} should report exactly {expected_check.value}; got {reported}"
    )
    assert holds(facts) is False


def test_every_check_has_a_breakage_case() -> None:
    """The corpus check: no comparison may exist without a test that provokes it.

    This is M6's lesson in its most direct form. `ALL_COMMAND_NAMES` was the only tuple a
    catalogue gate iterated, and five entries defined outside it went unverified for two
    milestones behind a green gate. `BREAKAGES` is this file's equivalent, so a ninth comparison
    added to `IntegrityCheck` without a case here fails immediately rather than being silently
    untested.
    """

    covered = {expected for _field, _value, expected in BREAKAGES}
    missing = sorted(check.value for check in IntegrityCheck if check not in covered)

    assert missing == [], (
        f"these comparisons have no failing case, so nothing proves they run: {missing}"
    )


def test_all_failures_are_reported_not_just_the_first() -> None:
    """A quarantined export needs the whole picture, not the first symptom.

    A file whose checksum alone moved is a different incident from one whose hash, total and row
    count all disagree — the first suggests the bytes were touched, the second that the wrong
    version was rendered. Short-circuiting would make an operator investigate the wrong thing.
    """

    facts = consistent(
        export_total_amount_irr=999,
        export_row_count=99,
        measured_file_sha256_hash=OTHER_HASH,
    )
    reported = {failure.check for failure in failed_checks(facts)}

    assert reported == {
        IntegrityCheck.EXPORT_TOTAL_MATCHES_VERSION,
        IntegrityCheck.EXPORT_ROW_COUNT_MATCHES_VERSION,
        IntegrityCheck.FILE_CHECKSUM_MATCHES_STORED_CHECKSUM,
    }


def test_a_failure_says_what_it_expected_and_what_it_found() -> None:
    """The security event has to be readable by somebody who is not holding the code.

    `expected` and `actual` are rendered as strings so a UUID and an integer describe themselves
    the same way, and so the pair can go into an audit row without a second serialisation
    decision being made at the call site.
    """

    (failure,) = failed_checks(consistent(export_total_amount_irr=42))

    assert failure.expected == "1500000000"
    assert failure.actual == "42"
    assert "expected 1500000000" in failure.describe()
    assert failure.check.value in failure.describe()


def test_the_checks_are_exactly_the_eight_the_document_lists() -> None:
    """Eight, and the count is asserted rather than left to the reader of an enum.

    §15.5 lists eight equalities. A ninth appearing here without the document gaining one means
    somebody invented a check — which is a smaller problem than a missing one, but it would still
    quarantine exports for a reason no document supports.
    """

    assert len(IntegrityCheck) == 8, sorted(check.value for check in IntegrityCheck)
