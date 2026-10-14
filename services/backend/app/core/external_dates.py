"""External date strings: kept raw, normalised beside, never guessed.

Bank files carry dates in whatever the producing system emits. Some are ISO, some
are Jalali, some are ambiguous — `03/04/2026` is two different days depending on
a convention the file does not state.

**An ambiguous or unparseable date goes to manual review.** Guessing is the one
option that must not exist here: a settlement dated a month earlier than it
happened reconciles against the wrong statement period, and nothing downstream
can detect it because the value looks perfectly reasonable.

**Two things this module used to refuse, and reads since the owner's decision of
2026-10-14.** Both were refused as decisions nobody had made; both now have an
owner and a rule.

- *A Jalali date* is converted by `app/core/jalali.py` — exactly, inside the years
  where three independent references agree. Outside them it is still a review item.
- *A wall clock with no zone* is read in `Asia/Tehran`. The earlier position was
  that the interpretation "is the bank's to state — but the file does not". An
  Iranian bank's statement states it by being one: document 08 §8.4's canonical row
  carries the bank's `09:15:23` as `+03:30`, and ADR-006 point 3 puts date-only
  interpretation in the business zone. **A wall clock that names no single instant
  is still a review item** — the hour skipped or the hour repeated by a
  daylight-saving change, which Tehran observed until 2022.

**The calendar is decided by the year, and that is not a guess.** `1405-05-10` is
ISO-shaped and Jalali. A bank statement cannot be dated 1405 CE, and the Jalali
years converted here (1300-1499) do not overlap the Gregorian years accepted
(1900-2199), so the year settles the calendar deterministically. Before this the
ISO branch ran first and read that value as a day six centuries ago.

**Digits are read, not stored.** A date written in Persian or Arabic-Indic digits is
transcribed to ASCII for reading; the raw string keeps whatever the bank wrote.

**The raw string is retained beside the normalised timestamp, with the parser
version that produced it.** Three reasons: an operator resolving a review needs
to see what the bank actually sent; a parser fix must be re-runnable over the
values it previously misread; and a normalised value with no provenance cannot be
audited against the source document.

Business-day and cutoff arithmetic uses the IANA identifier through the installed
tz database. A hard-coded +03:30 would pass every test written today and be wrong
the first time Iran's offset rules change — and it has changed: daylight saving
was abolished in 2022, which the tz database knows and a constant does not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Final

from app.core.jalali import (
    CALENDAR_RULE,
    JalaliDateError,
    OutsideVerifiedWindow,
    to_gregorian,
)
from app.core.time import BUSINESS_TIMEZONE, ensure_utc

# Bumped when parsing rules change, and stored beside every normalised value so a
# fix can be re-run over exactly the rows the old rules produced. v2: Jalali dates
# are converted and zoneless wall clocks are read in the business zone.
PARSER_VERSION = "v2"

# The calendar a normalised value was read in, for the record beside it.
GREGORIAN: Final = "gregorian"

# Jalali years in the range this platform converts. Written with the literal century
# so the shape alone excludes every Gregorian year a bank file carries.
_JALALI_DATE = re.compile(r"^(1[34]\d{2})[/-](\d{1,2})[/-](\d{1,2})$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_ISO_DATETIME = re.compile(r"^(\d{4})-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?")
# The genuinely ambiguous shape: two small numbers and a year, with no statement
# of which is the day.
_AMBIGUOUS_SLASHED = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$")
_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")

_FIRST_GREGORIAN_YEAR: Final = 1900
_LAST_GREGORIAN_YEAR: Final = 2199

# Persian and Arabic-Indic digits to ASCII, built from code points so no confusable
# character appears in this file.
_ASCII_DIGITS: Final = str.maketrans(
    {chr(0x06F0 + n): str(n) for n in range(10)} | {chr(0x0660 + n): str(n) for n in range(10)}
)


class DateResolution(StrEnum):
    NORMALISED = "normalised"
    MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True)
class ParsedExternalDate:
    """What a bank sent, what it was read as, and how confident that reading is.

    `raw` is always populated, including on the manual-review path. A review item
    without the original string cannot be resolved by a human. `calendar` names the
    rule a normalised value was read under — `gregorian`, or the Jalali rule and the
    window it is verified for.
    """

    raw: str
    resolution: DateResolution
    normalised_utc: datetime | None = None
    parser_version: str = PARSER_VERSION
    reason: str | None = None
    calendar: str | None = None

    @property
    def needs_review(self) -> bool:
        return self.resolution is DateResolution.MANUAL_REVIEW


def _review(raw: str, reason: str) -> ParsedExternalDate:
    return ParsedExternalDate(raw=raw, resolution=DateResolution.MANUAL_REVIEW, reason=reason)


def _normalised(raw: str, instant: datetime, calendar: str) -> ParsedExternalDate:
    return ParsedExternalDate(
        raw=raw,
        resolution=DateResolution.NORMALISED,
        normalised_utc=ensure_utc(instant),
        calendar=calendar,
    )


def business_wall_clock(calendar_date: date, clock: time) -> datetime | None:
    """The UTC instant a Tehran wall clock names, or `None` if it names none or two.

    A daylight-saving change makes a wall clock skip an hour or repeat one. In the
    skipped hour the time never happened; in the repeated one it happened twice. The
    tz database answers both by giving the two folds different offsets, so a
    difference between them is exactly the case ADR-006 point 5 sends to review.
    """

    local = datetime.combine(calendar_date, clock)
    earlier = local.replace(tzinfo=BUSINESS_TIMEZONE, fold=0)
    later = local.replace(tzinfo=BUSINESS_TIMEZONE, fold=1)
    if earlier.utcoffset() != later.utcoffset():
        return None
    return earlier.astimezone(UTC)


def _start_of_business_day(calendar_date: date) -> datetime:
    """Midnight in Tehran — or, on a day whose midnight was skipped, the first instant
    the day had, which is what the tz database returns for the earlier fold."""

    return datetime.combine(calendar_date, time.min, tzinfo=BUSINESS_TIMEZONE).astimezone(UTC)


def _calendar_date(raw: str, text: str) -> tuple[date, str] | ParsedExternalDate:
    """The day a date-only string names and the calendar it was read in, or a review item."""

    jalali = _JALALI_DATE.match(text)
    if jalali:
        year, month, day = (int(part) for part in jalali.groups())
        try:
            return to_gregorian(year, month, day), CALENDAR_RULE
        except OutsideVerifiedWindow as error:
            return _review(raw, f"Jalali date outside the verified conversion window: {error}")
        except JalaliDateError as error:
            return _review(raw, f"not a day of the Jalali calendar: {error}")

    iso = _ISO_DATE.match(text)
    if iso:
        year, month, day = (int(part) for part in iso.groups())
        if not _FIRST_GREGORIAN_YEAR <= year <= _LAST_GREGORIAN_YEAR:
            return _review(raw, f"year {year} is not a year a bank file carries")
        try:
            return date(year, month, day), GREGORIAN
        except ValueError:
            return _review(raw, "ISO-shaped date that is not a real day")

    if _AMBIGUOUS_SLASHED.match(text):
        return _review(raw, "day/month order not stated by the source")

    return _review(raw, "unrecognised date format")


def _clock(raw: str, text: str) -> time | ParsedExternalDate:
    match = _CLOCK.match(text)
    if match is None:
        return _review(raw, f"time {text!r} is not readable")
    hour, minute = int(match.group(1)), int(match.group(2))
    second = int(match.group(3) or 0)
    if hour > 23 or minute > 59 or second > 59:
        return _review(raw, f"time {text!r} is not a time of day")
    return time(hour, minute, second)


def parse_external_date_time(date_raw: str, time_raw: str | None = None) -> ParsedExternalDate:
    """Read a bank-supplied date, with the clock from a separate column if there is one.

    Statements usually carry the two in separate columns; a spreadsheet cell typed as a
    date-time arrives as one ISO string. When both carry a clock, the separate column
    wins — it is the one the bank labelled as the time.
    """

    raw = date_raw if time_raw is None else f"{date_raw} {time_raw}"
    if not isinstance(date_raw, str) or not date_raw.strip():
        return _review(str(raw), "empty or non-textual value")

    text = date_raw.strip().translate(_ASCII_DIGITS)
    clock: time | None = None
    if time_raw is not None and time_raw.strip():
        read = _clock(raw, time_raw.strip().translate(_ASCII_DIGITS))
        if isinstance(read, ParsedExternalDate):
            return read
        clock = read

    datetime_shape = _ISO_DATETIME.match(text)
    if datetime_shape:
        if _JALALI_DATE.match(text[:10].replace("-", "/")):
            return _review(
                raw,
                "a Jalali date written with an ISO time; the parts are not read separately",
            )
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return _review(raw, "ISO-shaped but unparseable")
        if not _FIRST_GREGORIAN_YEAR <= parsed.year <= _LAST_GREGORIAN_YEAR:
            return _review(raw, f"year {parsed.year} is not a year a bank file carries")
        if parsed.tzinfo is not None:
            # The file stated its zone. Its own clock unless a separate column gives one.
            stated = clock if clock is not None else parsed.timetz().replace(tzinfo=None)
            return _normalised(
                raw, datetime.combine(parsed.date(), stated, tzinfo=parsed.tzinfo), GREGORIAN
            )
        wall = clock if clock is not None else parsed.time()
        instant = business_wall_clock(parsed.date(), wall)
        if instant is None:
            return _review(raw, _transition_reason(parsed.date(), wall))
        return _normalised(raw, instant, GREGORIAN)

    read_date = _calendar_date(raw, text)
    if isinstance(read_date, ParsedExternalDate):
        return read_date
    calendar_date, calendar = read_date

    if clock is None:
        # A date with no time is a statement about the business day, not an instant.
        return _normalised(raw, _start_of_business_day(calendar_date), calendar)

    instant = business_wall_clock(calendar_date, clock)
    if instant is None:
        return _review(raw, _transition_reason(calendar_date, clock))
    return _normalised(raw, instant, calendar)


def _transition_reason(calendar_date: date, clock: time) -> str:
    return (
        f"{calendar_date.isoformat()} {clock.isoformat()} falls in a daylight-saving change "
        "in Asia/Tehran and names no single instant"
    )


def parse_external_date(raw: str) -> ParsedExternalDate:
    """Read a bank-supplied date held in one string, or route it to review."""

    if not isinstance(raw, str):
        return _review(str(raw), "empty or non-textual value")
    return parse_external_date_time(raw)


def business_day_start(moment: datetime) -> datetime:
    """Midnight in Tehran for the business day containing `moment`, as UTC.

    Computed through the IANA database rather than an offset. Iran abolished
    daylight saving in 2022; an arithmetic +03:30 would silently produce the
    wrong boundary for any historical date before that, and for any future rule
    change nobody can predict.
    """

    local = ensure_utc(moment).astimezone(BUSINESS_TIMEZONE)
    start = datetime.combine(local.date(), time.min, tzinfo=BUSINESS_TIMEZONE)
    return start.astimezone(UTC)


def business_day_end(moment: datetime) -> datetime:
    """Exclusive end of the business day: the next day's start.

    Exclusive rather than 23:59:59 so a timestamp in the final second of the day
    is not silently excluded, and so a day with a DST transition still covers
    exactly the hours it has.
    """

    return business_day_start(business_day_start(moment) + timedelta(days=1, hours=12))


def is_same_business_day(first: datetime, second: datetime) -> bool:
    """Whether two instants fall on one Tehran business day."""

    return business_day_start(first) == business_day_start(second)
