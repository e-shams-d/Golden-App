"""External dates are read or reviewed, never guessed.

The guessing failure is the one worth preventing: a settlement dated a month
earlier than it happened reconciles against the wrong statement period, and
nothing downstream can detect it, because the value looks entirely reasonable.

**Two tests in this file were inverted on the owner's decision of 2026-10-14**, and
they are kept here in their new form rather than deleted, so the change is visible:
a Jalali date is now converted (exactly, inside the window three independent
references agree on), and a zoneless wall clock is now read in Asia/Tehran. What
stays a review item is anything that still cannot be read exactly — a day/month
order the file does not state, an hour a daylight-saving change skipped or repeated.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone

import pytest
from app.core.external_dates import (
    GREGORIAN,
    PARSER_VERSION,
    DateResolution,
    business_day_end,
    business_day_start,
    business_wall_clock,
    is_same_business_day,
    parse_external_date,
    parse_external_date_time,
)
from app.core.jalali import CALENDAR_RULE
from app.core.time import BUSINESS_TIMEZONE

TEHRAN_OFFSET = timedelta(hours=3, minutes=30)


class TestUnambiguousInputs:
    def test_an_iso_datetime_with_a_zone_normalises(self) -> None:
        parsed = parse_external_date("2026-08-01T12:00:00+03:30")

        assert parsed.resolution is DateResolution.NORMALISED
        assert parsed.normalised_utc == datetime(2026, 8, 1, 8, 30, tzinfo=UTC)

    def test_an_iso_date_becomes_midnight_in_the_business_zone(self) -> None:
        """A date with no time is a statement about the business day, not an instant."""

        parsed = parse_external_date("2026-08-01")

        assert parsed.resolution is DateResolution.NORMALISED
        assert parsed.normalised_utc is not None
        local = parsed.normalised_utc.astimezone(BUSINESS_TIMEZONE)
        assert (local.hour, local.minute) == (0, 0)
        assert local.date() == datetime(2026, 8, 1).date()

    def test_the_raw_string_is_always_retained(self) -> None:
        """An operator resolving a review needs to see what the bank actually sent."""

        parsed = parse_external_date("2026-08-01")

        assert parsed.raw == "2026-08-01"

    def test_the_parser_version_is_recorded(self) -> None:
        """So a parser fix can be re-run over exactly the rows the old rules produced."""

        assert parse_external_date("2026-08-01").parser_version == PARSER_VERSION


class TestTheOwnersDecision:
    """What changed on 2026-10-14, each half with the case that still goes to review."""

    def test_a_datetime_without_a_zone_is_read_as_a_tehran_wall_clock(self) -> None:
        """Inverted. It used to be "a decision the bank has not stated". An Iranian bank's
        statement states it by being one: document 08 §8.4 reads `09:15:23` as `+03:30`."""

        parsed = parse_external_date("2026-08-01T12:00:00")

        assert parsed.resolution is DateResolution.NORMALISED
        assert parsed.normalised_utc == datetime(2026, 8, 1, 8, 30, tzinfo=UTC)

    def test_a_late_evening_transfer_stays_on_the_day_the_bank_wrote(self) -> None:
        """F-37's case. Read as UTC, 22:15 on the 11th became 01:45 on the 12th in Tehran."""

        parsed = parse_external_date_time("2026-08-11", "22:15:00")

        assert parsed.normalised_utc is not None
        local = parsed.normalised_utc.astimezone(BUSINESS_TIMEZONE)
        assert (local.date().isoformat(), local.hour, local.minute) == ("2026-08-11", 22, 15)

    def test_a_jalali_date_is_converted_exactly(self) -> None:
        """Inverted. It used to be "recognised and not approximated"; the conversion is no
        longer approximate inside the window, so it is no longer refused there."""

        parsed = parse_external_date("1405/05/10")

        assert parsed.resolution is DateResolution.NORMALISED
        assert parsed.calendar == CALENDAR_RULE
        assert parsed.normalised_utc is not None
        local = parsed.normalised_utc.astimezone(BUSINESS_TIMEZONE)
        assert (local.date().isoformat(), local.hour) == ("2026-08-01", 0)

    def test_the_specifications_own_row_reads_as_the_specification_says(self) -> None:
        """Document 08 §8.4: `1405/04/27` and `09:15:23` are `2026-07-18T09:15:23+03:30`."""

        parsed = parse_external_date_time("1405/04/27", "09:15:23")

        expected = datetime(2026, 7, 18, 9, 15, 23, tzinfo=timezone(TEHRAN_OFFSET))
        assert parsed.normalised_utc == expected

    def test_a_hyphenated_jalali_date_is_not_read_as_six_centuries_ago(self) -> None:
        """`1405-05-10` is ISO-shaped. The ISO branch used to run first and return a day in
        1405 CE. The year decides the calendar: no bank statement is dated 1405 CE."""

        parsed = parse_external_date("1405-05-10")

        assert parsed.calendar == CALENDAR_RULE
        assert parsed.normalised_utc is not None
        assert parsed.normalised_utc.year == 2026

    def test_digits_are_read_whatever_script_the_bank_wrote_them_in(self) -> None:
        # Built from code points so no confusable character sits in this file.
        persian = "".join(
            chr(0x06F0 + int(character)) if character.isdigit() else character
            for character in "1405/05/10"
        )

        parsed = parse_external_date(persian)

        assert parsed.normalised_utc == parse_external_date("1405/05/10").normalised_utc
        assert parsed.raw == persian, "the raw string must keep what the bank wrote"

    def test_a_gregorian_date_records_its_calendar_too(self) -> None:
        assert parse_external_date("2026-08-01").calendar == GREGORIAN


class TestAmbiguityGoesToReview:
    def test_a_slashed_date_is_not_guessed(self) -> None:
        """03/04/2026 is two different days, and the file does not say which."""

        parsed = parse_external_date("03/04/2026")

        assert parsed.needs_review is True
        assert parsed.normalised_utc is None
        assert "day/month" in (parsed.reason or "")

    def test_an_hour_the_clocks_skipped_names_no_instant(self) -> None:
        """Measured from the tz database: Tehran went from 00:00 to 01:00 on 2021-03-22
        (1400/01/02), so 00:30 that night never happened."""

        parsed = parse_external_date_time("1400/01/02", "00:30:00")

        assert parsed.needs_review is True
        assert "daylight-saving" in (parsed.reason or "")
        assert business_wall_clock(date(2021, 3, 22), time(0, 30)) is None

    def test_an_hour_the_clocks_repeated_names_two_instants(self) -> None:
        """Measured from the tz database: Tehran went from 24:00 back to 23:00 on 2021-09-21
        (1400/06/30), so 23:30 that night happened twice, an hour apart."""

        parsed = parse_external_date_time("1400/06/30", "23:30:00")

        assert parsed.needs_review is True
        assert "daylight-saving" in (parsed.reason or "")

    def test_the_hours_around_a_change_are_still_read(self) -> None:
        """The guard on the two above: refusing the whole day would also pass them."""

        before = parse_external_date_time("1400/06/30", "22:30:00")
        after = parse_external_date_time("1400/06/31", "00:30:00")

        assert before.resolution is DateResolution.NORMALISED
        assert after.resolution is DateResolution.NORMALISED

    def test_a_jalali_date_with_an_iso_time_is_not_split_and_guessed(self) -> None:
        parsed = parse_external_date("1405-05-10T12:00:00")

        assert parsed.needs_review is True
        assert "Jalali" in (parsed.reason or "")

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "not a date",
            "2026-13-01",
            "20260801",
            # 1404 is a common year, so Esfand has no thirtieth day.
            "1404/12/30",
            # A year outside the window shaped like a Jalali one: read by nothing, so reviewed.
            "1550/01/01",
        ],
    )
    def test_unparseable_values_go_to_review_with_the_original(self, raw: str) -> None:
        parsed = parse_external_date(raw)

        assert parsed.needs_review is True
        assert parsed.raw == raw
        assert parsed.reason

    def test_a_review_item_carries_no_normalised_value(self) -> None:
        """A half-parsed value invites somebody downstream to use it anyway."""

        parsed = parse_external_date("03/04/2026")

        assert parsed.normalised_utc is None


class TestBusinessDays:
    def test_the_day_boundary_uses_the_tz_database_not_an_offset(self) -> None:
        """Iran abolished daylight saving in 2022.

        A hard-coded +03:30 passes every test written for a date after that and
        is wrong for every date before it. Comparing a 2021 summer instant
        against a 2026 one is what separates the two implementations.
        """

        summer_2021 = datetime(2021, 7, 1, 12, 0, tzinfo=UTC)
        summer_2026 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

        offset_2021 = summer_2021.astimezone(BUSINESS_TIMEZONE).utcoffset()
        offset_2026 = summer_2026.astimezone(BUSINESS_TIMEZONE).utcoffset()

        assert offset_2021 == timedelta(hours=4, minutes=30), (
            "the tz database is not being consulted: Iran observed DST in 2021"
        )
        assert offset_2026 == TEHRAN_OFFSET
        assert offset_2021 != offset_2026

    def test_the_day_starts_at_local_midnight(self) -> None:
        moment = datetime(2026, 8, 1, 20, 0, tzinfo=UTC)  # late evening in Tehran

        start = business_day_start(moment)

        local = start.astimezone(BUSINESS_TIMEZONE)
        assert (local.hour, local.minute) == (0, 0)

    def test_the_end_is_exclusive(self) -> None:
        """23:59:59 would silently exclude a timestamp in the final second."""

        moment = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

        start = business_day_start(moment)
        end = business_day_end(moment)

        assert end > start
        assert end == business_day_start(end)

    def test_two_instants_late_and_early_can_be_different_business_days(self) -> None:
        """20:45 UTC is already tomorrow in Tehran. A UTC-day comparison gets this
        wrong, which is why the helper exists."""

        before_midnight_tehran = datetime(2026, 8, 1, 19, 0, tzinfo=UTC)
        after_midnight_tehran = datetime(2026, 8, 1, 21, 0, tzinfo=UTC)

        assert before_midnight_tehran.date() == after_midnight_tehran.date()
        assert is_same_business_day(before_midnight_tehran, after_midnight_tehran) is False

    def test_the_same_instant_expressed_differently_is_one_day(self) -> None:
        tehran = timezone(TEHRAN_OFFSET)
        as_utc = datetime(2026, 8, 1, 8, 30, tzinfo=UTC)
        as_local = datetime(2026, 8, 1, 12, 0, tzinfo=tehran)

        assert is_same_business_day(as_utc, as_local) is True

    def test_a_naive_datetime_is_refused(self) -> None:
        with pytest.raises(ValueError, match="timezone"):
            business_day_start(datetime(2026, 8, 1, 12, 0))
