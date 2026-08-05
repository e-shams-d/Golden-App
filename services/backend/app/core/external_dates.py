"""External date strings: kept raw, normalised beside, never guessed.

Bank files carry dates in whatever the producing system emits. Some are ISO, some
are Jalali, some are ambiguous — `03/04/2026` is two different days depending on
a convention the file does not state.

**An ambiguous or unparseable date goes to manual review.** Guessing is the one
option that must not exist here: a settlement dated a month earlier than it
happened reconciles against the wrong statement period, and nothing downstream
can detect it because the value looks perfectly reasonable.

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

from app.core.time import BUSINESS_TIMEZONE, ensure_utc

# Bumped when parsing rules change, and stored beside every normalised value so a
# fix can be re-run over exactly the rows the old rules produced.
PARSER_VERSION = "v1"

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?")
# Jalali years in the range a bank file plausibly carries. Written explicitly so
# a four-digit Gregorian year is never read as Jalali or the reverse.
_JALALI_DATE = re.compile(r"^(1[34]\d{2})[/-](\d{1,2})[/-](\d{1,2})$")
# The genuinely ambiguous shape: two small numbers and a year, with no statement
# of which is the day.
_AMBIGUOUS_SLASHED = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$")


class DateResolution(StrEnum):
    NORMALISED = "normalised"
    MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True)
class ParsedExternalDate:
    """What a bank sent, what it was read as, and how confident that reading is.

    `raw` is always populated, including on the manual-review path. A review item
    without the original string cannot be resolved by a human.
    """

    raw: str
    resolution: DateResolution
    normalised_utc: datetime | None = None
    parser_version: str = PARSER_VERSION
    reason: str | None = None

    @property
    def needs_review(self) -> bool:
        return self.resolution is DateResolution.MANUAL_REVIEW


def _review(raw: str, reason: str) -> ParsedExternalDate:
    return ParsedExternalDate(
        raw=raw, resolution=DateResolution.MANUAL_REVIEW, reason=reason
    )


def parse_external_date(raw: str) -> ParsedExternalDate:
    """Read a bank-supplied date, or route it to review. Never guesses.

    Only unambiguous shapes are accepted. Everything else — including a date that
    *could* be read one way — is a review item, because "probably" is not a
    standard a settlement date can be held to.
    """

    if not isinstance(raw, str) or not raw.strip():
        return _review(str(raw), "empty or non-textual value")

    candidate = raw.strip()

    if _ISO_DATETIME.match(candidate):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return _review(raw, "ISO-shaped but unparseable")
        if parsed.tzinfo is None:
            # A date-time with no zone is a wall clock. Interpreting it in the
            # business zone is a decision, and it is the bank's to state — but the
            # file does not, so it is recorded rather than assumed.
            return _review(raw, "date-time without a timezone; interpretation unstated")
        return ParsedExternalDate(
            raw=raw,
            resolution=DateResolution.NORMALISED,
            normalised_utc=ensure_utc(parsed),
        )

    iso_date = _ISO_DATE.match(candidate)
    if iso_date:
        year, month, day = (int(part) for part in iso_date.groups())
        try:
            calendar_date = date(year, month, day)
        except ValueError:
            return _review(raw, "ISO-shaped date that is not a real day")
        # A date with no time is midnight in the business zone, which is a
        # statement about the business day rather than about an instant.
        return ParsedExternalDate(
            raw=raw,
            resolution=DateResolution.NORMALISED,
            normalised_utc=datetime.combine(
                calendar_date, time.min, tzinfo=BUSINESS_TIMEZONE
            ).astimezone(UTC),
        )

    if _JALALI_DATE.match(candidate):
        # Recognised and deliberately not converted. Jalali conversion needs a
        # calendar library this project has not adopted, and an approximate
        # conversion is exactly the guess this module refuses to make.
        return _review(raw, "Jalali date; conversion not available in Phase 1A")

    if _AMBIGUOUS_SLASHED.match(candidate):
        return _review(raw, "day/month order not stated by the source")

    return _review(raw, "unrecognised date format")


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
