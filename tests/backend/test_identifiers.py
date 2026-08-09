"""Login identifiers must have exactly one spelling.

If `09123456789` and `+989123456789` both reach the column, `UNIQUE (phone_number)`
permits two accounts for one person, and a rate limit keyed on the identifier
gives one attacker two budgets.

Covers: SEC-IDENT-001.
"""

from __future__ import annotations

import pytest
from app.security.identifiers import (
    InvalidIdentifier,
    fold_digits,
    normalize_mobile,
    normalize_username,
)

CANONICAL = "+989123456789"


@pytest.mark.parametrize(
    "written",
    [
        "09123456789",
        "+989123456789",
        "00989123456789",
        "989123456789",
        "0912 345 6789",
        "0912-345-6789",
        "(0912) 345-6789",
        "  09123456789  ",
        # The ordinary path in a Persian interface, not an edge case: an Iranian
        # keyboard produces these digits by default.
        "۰۹۱۲۳۴۵۶۷۸۹",
        "+۹۸۹۱۲۳۴۵۶۷۸۹",
        # Arabic-Indic, which some keyboards and copied text produce instead.
        "٠٩١٢٣٤٥٦٧٨٩",
    ],
)
def test_every_way_of_writing_one_number_normalises_to_the_same_string(written: str) -> None:
    assert normalize_mobile(written) == CANONICAL


def test_two_different_numbers_stay_different() -> None:
    """Guard the guard: a normaliser that returned a constant would pass above."""

    assert normalize_mobile("09123456789") != normalize_mobile("09123456780")


@pytest.mark.parametrize(
    "rejected",
    [
        "",
        "   ",
        "0912345678",  # one digit short
        "091234567890",  # one digit too many
        "08123456789",  # not a mobile prefix
        "02112345678",  # Tehran landline
        "+447700900000",  # not Iranian
        "not-a-number",
        "0912345678a",
    ],
)
def test_anything_that_is_not_an_iranian_mobile_is_refused(rejected: str) -> None:
    with pytest.raises(InvalidIdentifier):
        normalize_mobile(rejected)


def test_digit_folding_is_exhaustive_across_both_scripts() -> None:
    """All ten of each, because an off-by-one in the codepoint map is invisible.

    A range built with `range(9)` would fold nine digits and leave one, and the
    survivor would be whichever digit nobody happened to test with.
    """

    assert fold_digits("۰۱۲۳۴۵۶۷۸۹") == "0123456789"
    assert fold_digits("٠١٢٣٤٥٦٧٨٩") == "0123456789"
    assert fold_digits("0123456789") == "0123456789"


def test_usernames_are_trimmed_but_not_lowered() -> None:
    """`admin_users.username` is CITEXT, so the column already ignores case.

    Lowering here as well would be a second rule that can drift from the
    column's; trimming is what the column does not do, and `  name ` is a paste
    artefact rather than a different person.
    """

    assert normalize_username("  accountant1  ") == "accountant1"
    assert normalize_username("Accountant1") == "Accountant1"
    assert normalize_username("hesabdar۱") == "hesabdar1"

    with pytest.raises(InvalidIdentifier):
        normalize_username("   ")
