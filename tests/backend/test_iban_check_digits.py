"""The IBAN's check digits, which nothing read until now.

`normalize_iban` matched `IR` plus twenty-four digits and returned. The acceptance pass
submitted `IR060120000000000000000105` and `IR990120000000000000000105` — one body, two
different check digits — and the server took both. At most one of any such pair can be
right, so the system had no opinion about the difference between a correct account number
and a mistyped one.

That matters further down than it looks. A beneficiary's IBAN is snapshotted onto each
payment request, carried through batching, and written into the file the bank executes.
Nothing between the form and the bank looks at it again, which is precisely why the check
digits are part of the number.

Covers: F-11.
"""

from __future__ import annotations

import pytest
from app.security.identifiers import InvalidIdentifier, normalize_iban

# A real, published Iranian IBAN shape with correct check digits. It is already in this
# suite as `tests/backend/test_audit_redaction.py`'s fixture, which is where it came from.
VALID = "IR820540102680020817909002"


def test_a_correct_iban_is_still_accepted() -> None:
    """The rule has to let the true thing through, or it is not a check."""

    assert normalize_iban(VALID) == VALID


def test_persian_digits_and_bank_spacing_still_fold_before_the_check() -> None:
    """Order matters: the check digits are read after folding, not instead of it.

    A trader types into a Persian interface and copies from a bank statement that prints
    in groups of four. If the checksum ran first it would reject every ordinary input.
    """

    persian = "IR۸۲ ۰۵۴۰ ۱۰۲۶ ۸۰۰۲ ۰۸۱۷ ۹۰۹۰ ۰۲"
    assert normalize_iban(persian) == VALID


def test_the_evidence_pair_cannot_both_be_accepted() -> None:
    """The two IBANs from the acceptance pass: one body, two check digits.

    Written as a pair rather than as two separate cases because the pair is the argument.
    Either both are refused, or exactly one is accepted; what cannot happen is what used
    to happen.
    """

    body = "0120000000000000000105"
    accepted = []
    for digits in ("06", "99"):
        try:
            normalize_iban(f"IR{digits}{body}")
        except InvalidIdentifier:
            continue
        accepted.append(digits)

    assert len(accepted) <= 1, (
        f"both IR{accepted[0]}{body} and IR{accepted[1]}{body} were accepted. "
        "One body cannot have two correct check digits; the checksum is not being read."
    )


@pytest.mark.parametrize(
    ("broken", "what"),
    [
        ("IR830540102680020817909002", "one check digit raised by one"),
        ("IR820540102680020817909003", "the last digit of the account raised by one"),
        ("IR820504102680020817909002", "two adjacent digits transposed"),
        ("IR820540102680020817909020", "the final pair transposed"),
    ],
)
def test_a_single_slip_is_refused(broken: str, what: str) -> None:
    """The four ways a person mistypes a number they are copying.

    Each of these is shaped exactly like an IBAN — `IR` and twenty-four digits — so the
    format check and the column's CHECK constraint both pass. The checksum is the only
    thing in the system that can tell them from the real one.
    """

    assert broken != VALID
    with pytest.raises(InvalidIdentifier, match="check digits"):
        normalize_iban(broken)


def test_the_message_tells_the_trader_what_to_look_at() -> None:
    """A refusal that says "invalid" sends someone back to the form to retype it whole.

    This one is reached through `BusinessRuleViolationError` in the beneficiary command,
    so the text lands in front of a person.
    """

    with pytest.raises(InvalidIdentifier) as raised:
        normalize_iban("IR830540102680020817909002")

    message = str(raised.value)
    assert "check digits" in message
    assert "mistyped" in message
