"""Money is integer IRR, the entry is provenance, and the unit is never guessed.

Every rule here is from the approved MONEY_TIME_CONTRACT, and every test names
the failure it prevents rather than the rule it restates — the rules are already
written down, and a test that repeats them adds nothing.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.core.money import (
    RIAL_PER_TOMAN,
    AmountUnitMismatchError,
    Money,
    MoneyUnit,
    is_forbidden_monetary_type,
    parse_integer_string,
    sum_rial,
    to_rial,
)


class TestConversion:
    def test_toman_converts_by_exactly_ten(self) -> None:
        assert to_rial(125_000_000, MoneyUnit.TOMAN) == 1_250_000_000

    def test_rial_is_unchanged(self) -> None:
        assert to_rial(1_250_000_000, MoneyUnit.IRR) == 1_250_000_000

    def test_the_rate_is_not_configurable(self) -> None:
        """Defined by law, not by deployment. A per-environment rate would let
        staging and production disagree about what a number means."""

        assert RIAL_PER_TOMAN == 10

    def test_a_float_is_refused_rather_than_rounded(self) -> None:
        """0.1 + 0.2 != 0.3, and a thousand transfers drift by an amount no
        reconciliation can absorb."""

        with pytest.raises(TypeError, match="floating point"):
            to_rial(125.0, MoneyUnit.TOMAN)  # type: ignore[arg-type]

    def test_a_bool_is_not_an_integer_here(self) -> None:
        """`True` is an int in Python, and one rial is not what anybody meant."""

        with pytest.raises(TypeError):
            to_rial(True, MoneyUnit.IRR)  # type: ignore[arg-type]

    def test_large_amounts_stay_exact(self) -> None:
        """Above 2^53 is where a float would start losing whole rials."""

        huge = 9_007_199_254_740_993  # 2^53 + 1
        assert to_rial(huge, MoneyUnit.TOMAN) == huge * 10


class TestThreeWayAgreement:
    def test_a_consistent_payload_is_accepted(self) -> None:
        money = Money.from_wire(
            {
                "amount_irr": "1250000000",
                "entered_amount": "125000000",
                "entered_unit": "TOMAN",
            }
        )

        assert money.amount_irr == 1_250_000_000
        assert money.entered_unit is MoneyUnit.TOMAN

    def test_a_disagreeing_payload_is_rejected_not_reconciled(self) -> None:
        """Reconciling means guessing which part to believe.

        Believing the amount silently changes the unit the trader chose;
        believing the unit silently changes the amount by 10x. Both move money.
        """

        with pytest.raises(AmountUnitMismatchError):
            Money.from_wire(
                {
                    "amount_irr": "125000000",  # not the TOMAN value times ten
                    "entered_amount": "125000000",
                    "entered_unit": "TOMAN",
                }
            )

    def test_a_missing_part_is_rejected(self) -> None:
        """All three are required so the server can check them against each other."""

        with pytest.raises(AmountUnitMismatchError, match="missing"):
            Money.from_wire({"amount_irr": "100", "entered_unit": "IRR"})

    def test_an_unknown_unit_is_rejected(self) -> None:
        with pytest.raises(AmountUnitMismatchError, match="entered_unit"):
            Money.from_wire(
                {
                    "amount_irr": "100",
                    "entered_amount": "100",
                    "entered_unit": "USD",
                }
            )

    def test_constructing_directly_still_validates(self) -> None:
        """The check is in __post_init__, so no construction path skips it."""

        with pytest.raises(AmountUnitMismatchError):
            Money(amount_irr=999, entered_amount=100, entered_unit=MoneyUnit.TOMAN)


class TestWireFormat:
    def test_amounts_serialise_as_strings(self) -> None:
        """A JSON number loses precision above 2^53, and IRR passes it routinely.

        One billion toman is 10,000,000,000 IRR — already beyond what JavaScript
        `number` represents exactly.
        """

        wire = Money.entered(1_000_000_000, MoneyUnit.TOMAN).to_wire()

        assert wire["amount_irr"] == "10000000000"
        assert isinstance(wire["amount_irr"], str)

    def test_a_json_number_is_refused_on_input(self) -> None:
        with pytest.raises(AmountUnitMismatchError, match="integer string"):
            parse_integer_string(1250000000, field="amount_irr")  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "raw", ["1.25e9", "1,250,000,000", "1_250_000_000", "0x10", " 100", "100 ", "", "01"]
    )
    def test_lenient_forms_are_refused(self, raw: str) -> None:
        """Each of these is a plausible typo for a value orders of magnitude away."""

        with pytest.raises(AmountUnitMismatchError):
            parse_integer_string(raw, field="amount_irr")

    def test_a_round_trip_preserves_everything(self) -> None:
        original = Money.entered(125_000_000, MoneyUnit.TOMAN)

        assert Money.from_wire(original.to_wire()) == original


class TestAggregation:
    def test_summing_is_exact(self) -> None:
        amounts = [1] * 1_000_000

        assert sum_rial(amounts) == 1_000_000

    def test_a_decimal_is_refused(self) -> None:
        """Exact and still not canonical: two representations of one amount means
        the comparison that matters is eventually between different types."""

        with pytest.raises(TypeError):
            sum_rial([Decimal("1.5")])  # type: ignore[list-item]

    def test_an_empty_sum_is_zero_not_an_error(self) -> None:
        """Aggregate totals are legitimately zero, unlike individual amounts."""

        assert sum_rial([]) == 0


class TestForbiddenTypes:
    @pytest.mark.parametrize("value", [1.0, 0.1, Decimal("1"), Decimal("0.1")])
    def test_float_and_decimal_are_both_flagged(self, value: object) -> None:
        assert is_forbidden_monetary_type(value) is True

    @pytest.mark.parametrize("value", [1, 0, -1, "100"])
    def test_integers_and_strings_are_not(self, value: object) -> None:
        assert is_forbidden_monetary_type(value) is False
