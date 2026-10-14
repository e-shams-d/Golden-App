"""Jalali dates to Gregorian ones: exact inside a verified window, refused outside it.

**Adopted on the owner's decision of 2026-10-14**, which closed the question
`app/core/external_dates.py` had deliberately left open. Its objection was precise: "Jalali
conversion needs a calendar library this project has not adopted, and an approximate
conversion is exactly the guess this module refuses to make." Both halves are answered here
rather than set aside.

*No library.* The rule is a handful of lines and has not changed in decades, so a dependency
would add a package to keep patched in the path reconciliation reads — and the dependency
scan went red four times during the acceptance pass on packages nobody chose. F-11 made the
same call for the IBAN check digits.

*Not approximate inside the window.* The official calendar is astronomical, and every
arithmetic rule approximates it. Three independent descriptions were compared year by year —
the 33-year rule used below, Borkowski's break-table algorithm (what jalaali-js implements),
and ICU 78.3's Persian calendar as shipped with Node 24 — and they agree on the first day and
the length of **every year from 1300 to 1499**. Agreement outside that window was not
measured, so a year outside it raises `OutsideVerifiedWindow` and the caller sends the value
to manual review, as ADR-006 point 5 requires of anything that cannot be read exactly.

`tests/fixtures/jalali_new_years_icu.txt` is ICU's table committed to the repository, and
`tests/backend/test_jalali.py` holds this module to it, so a change to the rule cannot pass
quietly. The same table is the compatibility anchor ADR-006 asks for between interface and
backend conversion: browsers draw the Persian calendar through ICU as well.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import cache
from typing import Final

FIRST_VERIFIED_YEAR: Final = 1300
LAST_VERIFIED_YEAR: Final = 1499

# Names the rule in the provenance a parser records beside each value it derives, which is
# what ADR-006's implementation section asks of files and workers. Change it whenever the rule
# or the window changes, so values produced under the old one can be found and re-run.
CALENDAR_RULE: Final = "jalali-1300-1499"

# `year % 33` for the eight leap years of each 33-year cycle.
_LEAP_REMAINDERS: Final = frozenset({1, 5, 9, 13, 17, 22, 26, 30})

# A New Year nobody disputes, from which every other is counted: 1 Farvardin 1400.
_ANCHOR_YEAR: Final = 1400
_ANCHOR_NEW_YEAR: Final = date(2021, 3, 21)


class JalaliDateError(ValueError):
    """Not a day of the Jalali calendar: a month 13, a 31 Mehr, a 30 Esfand in a common year."""


class OutsideVerifiedWindow(ValueError):
    """A Jalali year for which no conversion has been verified, so none is offered."""


def _require_window(year: int) -> None:
    if not FIRST_VERIFIED_YEAR <= year <= LAST_VERIFIED_YEAR:
        raise OutsideVerifiedWindow(
            f"year {year} is outside {FIRST_VERIFIED_YEAR}-{LAST_VERIFIED_YEAR}, the years "
            "for which this conversion was checked against two independent references"
        )


def is_leap(year: int) -> bool:
    """Whether Esfand of this year has 30 days."""

    _require_window(year)
    return year % 33 in _LEAP_REMAINDERS


def month_length(year: int, month: int) -> int:
    """Six months of 31 days, five of 30, and Esfand with 29 or 30."""

    if not 1 <= month <= 12:
        raise JalaliDateError(f"month {month} does not exist")
    if month <= 6:
        return 31
    if month <= 11:
        return 30
    return 30 if is_leap(year) else 29


@cache
def new_year(year: int) -> date:
    """The Gregorian date of 1 Farvardin of this year.

    Counted year by year from the anchor rather than by a closed formula. At most a couple of
    hundred additions, cached, and obviously correct — which is worth more here than speed.
    """

    _require_window(year)
    day = _ANCHOR_NEW_YEAR
    if year >= _ANCHOR_YEAR:
        for earlier in range(_ANCHOR_YEAR, year):
            day += timedelta(days=366 if is_leap(earlier) else 365)
    else:
        for later in range(year, _ANCHOR_YEAR):
            day -= timedelta(days=366 if is_leap(later) else 365)
    return day


def to_gregorian(year: int, month: int, day: int) -> date:
    """The Gregorian date of a Jalali one, or an exception that says which rule it broke."""

    _require_window(year)
    length = month_length(year, month)
    if not 1 <= day <= length:
        raise JalaliDateError(f"month {month} of {year} has {length} days, not {day}")
    before = sum(month_length(year, earlier) for earlier in range(1, month))
    return new_year(year) + timedelta(days=before + day - 1)
