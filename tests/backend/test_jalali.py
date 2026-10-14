"""The Jalali calendar, held to a table this repository did not compute.

`app/core/jalali.py` exists because the owner decided on 2026-10-14 that bank statements dated
in the Jalali calendar should be read rather than left as warnings. The module it overturned had
refused for a precise reason — "an approximate conversion is exactly the guess this module refuses
to make" — so these tests are built to show the conversion is not approximate, and to fail the day
it becomes so.

Three kinds of evidence, each catching a different way the rule could be wrong:

- **An external table.** `tests/fixtures/jalali_new_years_icu.txt` is ICU's own answer for the
  first day and length of every year in the window. A wrong leap rule moves a New Year and fails
  here; nothing in this repository produced those values.
- **Continuity.** Every day of every year, converted, must be exactly one day after the previous.
  A wrong month length leaves a gap or a repeat inside a year, which the New Year table alone
  cannot see — it only checks where each year starts.
- **Dates of record.** The New Years everyone remembers, the specification's own example, and the
  leap days that actually happened.

Covers: D-2.
"""

from __future__ import annotations

import pathlib
from datetime import date, timedelta

import pytest
from app.core.jalali import (
    FIRST_VERIFIED_YEAR,
    LAST_VERIFIED_YEAR,
    JalaliDateError,
    OutsideVerifiedWindow,
    is_leap,
    month_length,
    new_year,
    to_gregorian,
)

TABLE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "jalali_new_years_icu.txt"


def _icu_table() -> dict[int, tuple[date, int]]:
    rows: dict[int, tuple[date, int]] = {}
    for line in TABLE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        year, first_day, length = line.split()
        rows[int(year)] = (date.fromisoformat(first_day), int(length))
    return rows


def test_the_table_covers_the_whole_window() -> None:
    """The guard on the comparison below: a short table would agree with anything."""

    table = _icu_table()
    assert min(table) == FIRST_VERIFIED_YEAR
    assert max(table) == LAST_VERIFIED_YEAR
    assert len(table) == LAST_VERIFIED_YEAR - FIRST_VERIFIED_YEAR + 1


def test_every_new_year_and_every_year_length_agrees_with_icu() -> None:
    disagreements = []
    for year, (first_day, length) in _icu_table().items():
        mine = (new_year(year), 366 if is_leap(year) else 365)
        if mine != (first_day, length):
            disagreements.append(f"{year}: computed {mine}, ICU says {(first_day, length)}")

    assert not disagreements, "; ".join(disagreements[:5])


def test_every_day_follows_the_one_before() -> None:
    """A month length off by one is invisible to the New Year table and fatal here."""

    previous = new_year(FIRST_VERIFIED_YEAR) - timedelta(days=1)
    for year in range(FIRST_VERIFIED_YEAR, LAST_VERIFIED_YEAR + 1):
        for month in range(1, 13):
            for day in range(1, month_length(year, month) + 1):
                current = to_gregorian(year, month, day)
                assert current == previous + timedelta(days=1), (
                    f"{year}/{month}/{day} is {current}, the day before it was {previous}"
                )
                previous = current


@pytest.mark.parametrize(
    ("jalali", "gregorian", "why"),
    [
        ((1357, 1, 1), date(1978, 3, 21), "a New Year of public record"),
        ((1399, 1, 1), date(2020, 3, 20), "a New Year that fell on the 20th"),
        ((1400, 1, 1), date(2021, 3, 21), "the anchor itself"),
        ((1403, 12, 30), date(2025, 3, 20), "a leap day that happened"),
        ((1404, 1, 1), date(2025, 3, 21), "the day after it"),
        ((1405, 4, 27), date(2026, 7, 18), "document 08 §8.4's canonical row"),
        ((1405, 5, 22), date(2026, 8, 13), "the statement fixture's Jalali row"),
        # The second half of the year, where the month lengths change. Swapping Shahrivar's
        # length with Mehr's keeps every year the same length and every day consecutive, so
        # neither the ICU table nor the continuity test can see it — only a date of record
        # on either side of the change can.
        ((1400, 6, 31), date(2021, 9, 22), "the last day of Shahrivar"),
        ((1400, 7, 1), date(2021, 9, 23), "1 Mehr, the first day of autumn"),
        ((1357, 11, 22), date(1979, 2, 11), "22 Bahman 1357, a date of public record"),
    ],
)
def test_dates_of_record(jalali: tuple[int, int, int], gregorian: date, why: str) -> None:
    assert to_gregorian(*jalali) == gregorian, why


@pytest.mark.parametrize(
    ("jalali", "why"),
    [
        ((1405, 13, 1), "there is no thirteenth month"),
        ((1405, 0, 1), "there is no month zero"),
        ((1405, 7, 31), "Mehr has thirty days"),
        ((1404, 12, 30), "1404 is a common year, so Esfand has twenty-nine"),
        ((1405, 1, 0), "there is no day zero"),
    ],
)
def test_a_day_the_calendar_does_not_have_is_refused(
    jalali: tuple[int, int, int], why: str
) -> None:
    with pytest.raises(JalaliDateError):
        to_gregorian(*jalali)


@pytest.mark.parametrize("year", [FIRST_VERIFIED_YEAR - 1, LAST_VERIFIED_YEAR + 1, 1600])
def test_a_year_outside_the_verified_window_is_refused_rather_than_extrapolated(
    year: int,
) -> None:
    """The arithmetic would happily answer. Nobody has checked the answer, so it is not given."""

    with pytest.raises(OutsideVerifiedWindow):
        to_gregorian(year, 1, 1)
