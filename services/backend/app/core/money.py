"""Money as integer IRR, with the entered value kept beside it as provenance.

Delivered before any table with a monetary column exists, so the precedent is set
once rather than argued about per table.

**Integer IRR is the only canonical form.** Binary floating point is forbidden for
monetary input, calculation, transport and comparison — not discouraged. A float
cannot represent 0.1 exactly, and a sum of a thousand transfers drifts by an
amount nobody can explain and no reconciliation can absorb.

**The entered value is provenance, never the canonical amount.** A trader who
typed 125,000,000 TOMAN gets `amount_irr = 1250000000` stored, and the pair
(125000000, TOMAN) retained beside it. Discarding the entry loses the ability to
show them what they typed; treating it as canonical loses a factor of ten.

**The unit is never inferred.** Not from magnitude, not from formatting, not from
who is logged in, not from which page the request came from. Every one of those
heuristics is right most of the time, and the failure is a payment off by ten.

**Conversion happens in exactly one function.** A second conversion path is how a
factor of ten gets applied twice, or not at all.

**The wire form is a base-10 integer string.** IRR amounts pass 2^53 quickly — a
single billion-toman transfer is 10,000,000,000 IRR, and JavaScript's `number`
loses precision above 9,007,199,254,740,991. A JSON number here is silent
corruption at the boundary, so the contract is a string and the frontend uses
BigInt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from app.core.errors import AppError

# Rial per toman. Exact, integral, and not configurable: the relationship is
# defined by law, not by deployment.
RIAL_PER_TOMAN = 10

# A base-10 integer, optionally negative. No exponent, no decimal point, no
# thousands separators — each of those is a place a value could be misread.
_INTEGER_STRING = re.compile(r"^-?(0|[1-9][0-9]*)$")


class MoneyUnit(StrEnum):
    """The units a caller may enter. Phase 1A supports exactly these two."""

    IRR = "IRR"
    TOMAN = "TOMAN"


class AmountUnitMismatchError(AppError):
    """The three parts of a monetary payload do not agree.

    400 rather than a silent correction. Choosing which part to believe would
    mean guessing whether the caller meant the amount or the unit, and both
    guesses are wrong in a way that moves money.
    """

    def __init__(self, message: str) -> None:
        super().__init__("AMOUNT_UNIT_MISMATCH", message, 400)


def to_rial(value: int, unit: MoneyUnit) -> int:
    """Convert an entered amount to canonical IRR. The only conversion in the system.

    Exact integer multiplication: no rounding, no tolerance, no float anywhere in
    the path. A second implementation of this is how a factor of ten gets applied
    twice.
    """

    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(
            f"monetary values are integers; got {type(value).__name__}. Binary "
            "floating point is forbidden for money."
        )
    return value * RIAL_PER_TOMAN if unit is MoneyUnit.TOMAN else value


def parse_integer_string(raw: str, *, field: str) -> int:
    """Parse the wire form. Strict, because every leniency is a way to be wrong.

    A float string, an exponent or a thousands separator is refused rather than
    coerced: `"1.25e9"` and `"1,250,000,000"` are both plausible typos for values
    that differ by orders of magnitude.
    """

    if isinstance(raw, bool) or not isinstance(raw, str):
        raise AmountUnitMismatchError(
            f"{field} must be a base-10 integer string; a JSON number loses "
            "precision above 2^53 and IRR amounts exceed it routinely."
        )
    if not _INTEGER_STRING.match(raw):
        raise AmountUnitMismatchError(
            f"{field} must be a base-10 integer string with no separators, "
            f"decimal point or exponent; got {raw!r}."
        )
    return int(raw)


@dataclass(frozen=True)
class Money:
    """A canonical amount plus the provenance of how it was entered.

    Immutable, because a monetary value that can be adjusted in place is one
    whose audit row may describe a different number than the one that was used.
    """

    amount_irr: int
    entered_amount: int
    entered_unit: MoneyUnit

    def __post_init__(self) -> None:
        for name, value in (
            ("amount_irr", self.amount_irr),
            ("entered_amount", self.entered_amount),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an int; got {type(value).__name__}")

        expected = to_rial(self.entered_amount, self.entered_unit)
        if expected != self.amount_irr:
            raise AmountUnitMismatchError(
                f"amount_irr {self.amount_irr} does not equal {self.entered_amount} "
                f"{self.entered_unit.value} converted exactly "
                f"({expected}). The parts must agree; the server does not choose "
                "which one to believe."
            )

    @classmethod
    def entered(cls, amount: int, unit: MoneyUnit) -> Money:
        """Build from what a caller typed, converting once."""

        return cls(
            amount_irr=to_rial(amount, unit),
            entered_amount=amount,
            entered_unit=unit,
        )

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> Money:
        """Parse the canonical API shape, validating all three parts agree.

        The three-way check is the point. A payload carrying an `amount_irr` that
        does not match its entered value and unit is rejected rather than
        reconciled — reconciling means picking one to trust.
        """

        missing = sorted(
            {"amount_irr", "entered_amount", "entered_unit"} - set(payload)
        )
        if missing:
            raise AmountUnitMismatchError(
                f"the monetary payload is missing {missing}. All three parts are "
                "required so the server can verify them against each other."
            )

        raw_unit = payload["entered_unit"]
        try:
            unit = MoneyUnit(raw_unit)
        except ValueError as error:
            raise AmountUnitMismatchError(
                f"entered_unit must be one of {[u.value for u in MoneyUnit]}; "
                f"got {raw_unit!r}."
            ) from error

        return cls(
            amount_irr=parse_integer_string(payload["amount_irr"], field="amount_irr"),
            entered_amount=parse_integer_string(
                payload["entered_amount"], field="entered_amount"
            ),
            entered_unit=unit,
        )

    def to_wire(self) -> dict[str, str]:
        """The canonical wire shape. Strings, not numbers."""

        return {
            "amount_irr": str(self.amount_irr),
            "entered_amount": str(self.entered_amount),
            "entered_unit": self.entered_unit.value,
        }


def sum_rial(amounts: list[int]) -> int:
    """Exact aggregation. Present so nobody reaches for `sum(Decimal(...))`.

    Trivial by design: the value of this function is that it exists and takes
    integers, so a future caller with a float is stopped by the type rather than
    by review.
    """

    for amount in amounts:
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise TypeError(
                f"monetary aggregation takes integers; got {type(amount).__name__}. "
                "A Decimal or float here reintroduces the drift integers avoid."
            )
    return sum(amounts)


def is_forbidden_monetary_type(value: object) -> bool:
    """Whether a value must never carry money. Used by the guard tests.

    `Decimal` is included deliberately. It is exact and it is still not the
    canonical form: mixing it with the integer path means two representations of
    the same amount, and the comparison that eventually matters is between a
    stored integer and something else.
    """

    return isinstance(value, float | Decimal)
