"""External dates are read or reviewed, never guessed.

The guessing failure is the one worth preventing: a settlement dated a month
earlier than it happened reconciles against the wrong statement period, and
nothing downstream can detect it, because the value looks entirely reasonable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from app.core.external_dates import (
    PARSER_VERSION,
    DateResolution,
    business_day_end,
    business_day_start,
    is_same_business_day,
    parse_external_date,
)
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


class TestAmbiguityGoesToReview:
    def test_a_slashed_date_is_not_guessed(self) -> None:
        """03/04/2026 is two different days, and the file does not say which."""

        parsed = parse_external_date("03/04/2026")

        assert parsed.needs_review is True
        assert parsed.normalised_utc is None
        assert "day/month" in (parsed.reason or "")

    def test_a_datetime_without_a_zone_is_not_assumed_to_be_local(self) -> None:
        """Interpreting a bare wall clock is a decision the bank has not stated."""

        parsed = parse_external_date("2026-08-01T12:00:00")

        assert parsed.needs_review is True
        assert "timezone" in (parsed.reason or "")

    def test_a_jalali_date_is_recognised_and_not_approximated(self) -> None:
        """Recognising it is useful; converting it approximately is the guess."""

        parsed = parse_external_date("1405/05/10")

        assert parsed.needs_review is True
        assert "Jalali" in (parsed.reason or "")

    @pytest.mark.parametrize("raw", ["", "   ", "not a date", "2026-13-01", "20260801"])
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
