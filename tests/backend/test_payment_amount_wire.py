"""What the payment-request API accepts as money, tested without a database.

**This file exists because the integration suite timed out on CI.** Thirty-one money
cases each provisioned a disposable PostgreSQL and ran the whole Alembic chain, and
sixteen of them were testing a Pydantic pattern and `_money` — not the database. A test
that needs no database should not have one; the cost was the symptom and the misplacement
was the defect.

What stays in `tests/integration/test_payment_request_money.py` is what genuinely needs a
database: that the conversion is *stored*, that a refusal writes nothing, and one
representative refusal driven through the real route so the wiring between the validator
and the endpoint is still proved. The matrix lives here.

Covers: SVC-REQ-002, SVC-REQ-003, API-REQ-001.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from app.api.v1.payment_requests import (
    AmountRequest,
    CreateDraftRequest,
    DraftRevisionResponse,
    EnteredAmountResponse,
    _draft_amount,
    _money,
)
from app.core.money import AmountUnitMismatchError, MoneyUnit
from pydantic import ValidationError

BENEFICIARY = uuid.uuid4()


def request_with(**amount: Any) -> CreateDraftRequest:
    return CreateDraftRequest(beneficiary_id=BENEFICIARY, amount=AmountRequest(**amount))


@pytest.mark.parametrize(
    ("value", "unit", "expected_irr"),
    [
        ("500", "TOMAN", 5000),
        ("5000", "IRR", 5000),
        ("1", "TOMAN", 10),
        # Document 05's own example value (`:1087`), so the arithmetic is checked against
        # the number the specification chose rather than only convenient ones.
        ("3440000000", "TOMAN", 34400000000),
        # Above 2^53, which is the whole reason the wire form is a string. A JSON number
        # here would already have lost precision before the server saw it.
        ("99999999999999999", "IRR", 99999999999999999),
    ],
)
def test_the_server_converts_exactly(value: str, unit: str, expected_irr: int) -> None:
    """SVC-REQ-002. Integer arithmetic, no float anywhere in the path."""

    money = _money(AmountRequest(value=value, unit=unit))

    assert money.amount_irr == expected_irr
    assert money.entered_amount == int(value)
    assert money.entered_unit is MoneyUnit(unit)


def test_the_conversion_is_not_applied_to_rial() -> None:
    """SVC-REQ-002, the error `to_rial`'s docstring names: "a second implementation of
    this is how a factor of ten gets applied twice"."""

    assert _money(AmountRequest(value="5000", unit="IRR")).amount_irr == 5000
    assert _money(AmountRequest(value="500", unit="TOMAN")).amount_irr == 5000


@pytest.mark.parametrize("unit", ["irr", "IRR ", "RIAL", "USD", "TOMANS", "", "TOMAN\n", "toman"])
def test_an_invalid_unit_is_refused(unit: str) -> None:
    """SVC-REQ-002.

    `irr` and `toman` lowercase are in the list deliberately. Phase 1A supports exactly
    two units, and accepting a case variant would mean `entered_amount_unit` has more
    than one spelling — which the column's CHECK would then refuse at the insert, turning
    a client's typo into a 500 instead of a 400.
    """

    with pytest.raises(ValidationError):
        AmountRequest(value="500", unit=unit)


@pytest.mark.parametrize(
    "value", ["0", "-500", "5.5", "1e9", "1,000", " 500", "500 ", "abc", "", "0500", "١٢٣"]
)
def test_a_value_that_is_not_a_plain_integer_is_refused(value: str) -> None:
    """SVC-REQ-002, and why `parse_integer_string` is strict.

    `"1.25e9"` and `"1,250,000,000"` are both plausible typos for values that differ by
    orders of magnitude, and `"0"` is not a payment. `"0500"` is refused because a leading
    zero is how an octal-looking value sneaks past a lenient reader, and the Arabic-Indic
    digits because the wire form is ASCII — `normalize_iban` folds digits for an IBAN a
    human types, but an amount arrives from a program.
    """

    with pytest.raises(ValidationError):
        AmountRequest(value=value, unit="TOMAN")


def test_a_json_number_is_refused() -> None:
    """API-REQ-001, from the client's side.

    The money contract's rule 8 is that API monetary values are base-10 integer strings
    and rule 9 forbids JavaScript Number for financial amounts. A client sending `500`
    instead of `"500"` uses the type the contract forbids, and it is refused rather than
    coerced — coercion would make the forbidden form work, and then it would be used.
    """

    with pytest.raises(ValidationError):
        AmountRequest(value=500, unit="TOMAN")  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        AmountRequest(value="500", unit="TOMAN", amount_irr=5000)  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["rial_per_toman", "factor", "rate", "multiplier"])
def test_no_conversion_factor_can_be_submitted(field: str) -> None:
    """SVC-REQ-003.

    `RIAL_PER_TOMAN` is a constant in one module and the API has no field through which a
    caller could supply another. `extra="forbid"` refuses the field rather than ignoring
    it, because a factor that could be submitted is one that could be submitted as `1`,
    making a TOMAN amount ten times too small.
    """

    with pytest.raises(ValidationError):
        AmountRequest(**{"value": "500", "unit": "TOMAN", field: "1"})  # type: ignore[arg-type]


def test_a_client_supplied_amount_irr_that_agrees_is_accepted() -> None:
    """SVC-REQ-002. Document 05's create example carries all three parts (`:1085-1091`)."""

    money = _money(AmountRequest(value="500", unit="TOMAN", amount_irr="5000"))
    assert money.amount_irr == 5000


@pytest.mark.parametrize("claimed", ["500", "50000", "4999", "5001"])
def test_a_client_supplied_amount_irr_that_disagrees_is_refused(claimed: str) -> None:
    """SVC-REQ-002.

    `500` and `50000` are the two off-by-the-factor mistakes — converting not at all, and
    converting twice. The neighbours either side of the right answer are here because a
    check that only caught factor-of-ten errors would miss a transposed digit, which is
    the more common human error and moves less money in a way nobody notices.
    """

    with pytest.raises(AmountUnitMismatchError):
        _money(AmountRequest(value="500", unit="TOMAN", amount_irr=claimed))


def test_the_nested_and_flat_shapes_both_reach_the_same_money() -> None:
    """The compatibility path, which exists because the oasdiff waiver does not.

    Both shapes must converge, or the deprecated path would be a second set of rules.
    """

    nested = _draft_amount(request_with(value="500", unit="TOMAN"))
    flat = _draft_amount(
        CreateDraftRequest(
            beneficiary_id=BENEFICIARY,
            entered_amount_value="500",
            entered_amount_unit="TOMAN",
        )
    )

    assert nested == flat


def test_the_flat_path_verifies_a_supplied_amount_irr_too() -> None:
    """The compatibility path is not a way around the three-way check.

    A path that skipped the checks would be the shape an attacker uses.
    """

    with pytest.raises(AmountUnitMismatchError):
        _draft_amount(
            CreateDraftRequest(
                beneficiary_id=BENEFICIARY,
                entered_amount_value="500",
                entered_amount_unit="TOMAN",
                amount_irr="500",
            )
        )


def test_sending_both_shapes_is_refused() -> None:
    """Refused rather than resolved by precedence.

    A rule about which shape wins is a rule somebody has to know, and a caller sending
    `amount` alongside a contradicting `entered_amount_value` has already lost track of
    what they are asking for. Answering with one of them would pick a number for them.
    """

    with pytest.raises(AmountUnitMismatchError):
        _draft_amount(
            CreateDraftRequest(
                beneficiary_id=BENEFICIARY,
                amount=AmountRequest(value="500", unit="TOMAN"),
                entered_amount_value="900",
                entered_amount_unit="TOMAN",
            )
        )


def test_an_amount_is_required_in_one_shape_or_the_other() -> None:
    """`amount` is schema-optional and not optional in effect.

    Making it schema-optional was forced by the additive rule; it must not become a way
    to create a request with no amount at all.
    """

    with pytest.raises(AmountUnitMismatchError):
        _draft_amount(CreateDraftRequest(beneficiary_id=BENEFICIARY))

    # Half of the flat trio is not an amount either.
    with pytest.raises(AmountUnitMismatchError):
        _draft_amount(
            CreateDraftRequest(beneficiary_id=BENEFICIARY, entered_amount_value="500")
        )


def test_every_monetary_field_in_the_response_is_declared_as_a_string() -> None:
    """API-REQ-001, from the server's side, asserted over the response model.

    The integration suite checks the raw JSON text of a real response; this checks the
    *declaration*, so a field retyped to `int` fails here without needing a database. Both
    are wanted: a model can be right while a renderer is wrong, and the reverse.

    Read from Pydantic's `model_fields` rather than `__annotations__`: the route module
    uses `from __future__ import annotations`, so the raw annotations are strings and
    comparing them would compare spellings — `"str"` would pass and so would `"str "`.
    `model_fields` carries the resolved type Pydantic will actually validate against.
    """

    def declared(model: Any, field: str) -> Any:
        return model.model_fields[field].annotation

    assert declared(DraftRevisionResponse, "amount_irr") is str
    assert declared(DraftRevisionResponse, "entered_amount_value") == (str | None)
    assert declared(DraftRevisionResponse, "entered_amount_unit") == (str | None)

    assert declared(EnteredAmountResponse, "value") is str
    assert declared(EnteredAmountResponse, "unit") is str

    # And the request side, so a client cannot send a number even if the response is right.
    assert declared(AmountRequest, "value") is str
    assert declared(AmountRequest, "amount_irr") == (str | None)
