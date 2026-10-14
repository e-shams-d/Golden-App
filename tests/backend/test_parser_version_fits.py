"""The statement parser's version string fits every column that stores it.

2.0.0 carries build metadata naming the calendar rule and the zone, because ADR-006 asks files
and workers to persist "parser, timezone, and calendar/cutoff rule versions". The string is
written to two places: the import run's `parser_version` and the job's `provider_version`, and
the second is only 40 characters wide.

The first version of the string drafted for this change was 42 characters. It would have passed
every unit test and failed the first real import with a truncation error from PostgreSQL — the
same class of fault as F-30, where a value the application never checked overflowed a
`varchar(26)`. The widths are read from the models, so a narrower column later fails here too.

Covers: D-2.
"""

from __future__ import annotations

from app.commands.bank_statement import PARSER_VERSION
from app.core.jalali import CALENDAR_RULE
from app.db.models.bank_statement import BankStatementImportRun
from app.db.models.processing_job import ProcessingJob


def test_the_version_fits_every_column_it_is_written_to() -> None:
    widths = {
        "bank_statement_import_runs.parser_version": BankStatementImportRun.__table__.c[
            "parser_version"
        ].type.length,
        "processing_jobs.provider_version": ProcessingJob.__table__.c[
            "provider_version"
        ].type.length,
    }

    for column, width in widths.items():
        assert width is not None, f"{column} has no declared width to check against"
        assert len(PARSER_VERSION) <= width, (
            f"{PARSER_VERSION!r} is {len(PARSER_VERSION)} characters and {column} holds {width}"
        )


def test_the_version_names_the_calendar_rule() -> None:
    """So a run's row says which conversion produced its instants."""

    assert CALENDAR_RULE in PARSER_VERSION
