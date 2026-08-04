"""API-LIST-001: bounded, totally ordered, allowlisted reads over audit history.

The stability tests need real concurrent writes. A page that repeats or drops a
row does so because rows arrived between requests, and a fixture that inserts
everything up front cannot produce that.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.audit.reading import AUDIT_LIST_SPEC, AuditQuery, read_audit_page  # noqa: E402
from app.db.models.audit_log import AuditLog  # noqa: E402
from app.db.pagination import (  # noqa: E402
    MAX_LIMIT,
    InvalidCursorError,
    InvalidListParameterError,
    ListSpec,
    SortField,
    normalise_limit,
)

pytestmark = pytest.mark.integration

ACTOR = uuid.uuid4()


def _sqlalchemy_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture
def session_factory(migrated_database: str) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(_sqlalchemy_url(migrated_database))
    try:
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(session_factory: sessionmaker[Session]) -> Iterator[None]:
    yield
    with session_factory() as session:
        session.execute(text("DELETE FROM audit_logs"))
        session.commit()


def write_rows(session_factory: sessionmaker[Session], count: int, action: str) -> None:
    with session_factory() as session:
        for index in range(count):
            session.add(
                AuditLog(
                    action=action,
                    outcome="success",
                    actor_type="admin_user",
                    actor_id=ACTOR,
                    metadata_schema="audit.test",
                    metadata_version=1,
                    request_id=f"req-{index}",
                )
            )
        session.commit()


class TestLimits:
    def test_a_missing_limit_does_not_mean_unbounded(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """The failure this prevents: one support query selecting the whole table."""

        write_rows(session_factory, 60, "audit.default")

        with session_factory() as session:
            page = read_audit_page(session)

        assert len(page.rows) == 50
        assert page.has_more is True

    def test_an_out_of_range_limit_is_refused_rather_than_clamped(self) -> None:
        """Clamping lets a caller ask for 10,000, get 200, and believe it has them all."""

        with pytest.raises(InvalidListParameterError):
            normalise_limit(MAX_LIMIT + 1)
        with pytest.raises(InvalidListParameterError):
            normalise_limit(0)

    def test_the_last_page_reports_no_more(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        write_rows(session_factory, 3, "audit.short")

        with session_factory() as session:
            page = read_audit_page(session, limit=10)

        assert len(page.rows) == 3
        assert page.next_cursor is None


class TestPaginationIsStable:
    def test_pages_do_not_repeat_or_drop_rows(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        write_rows(session_factory, 25, "audit.paged")

        seen: list[int] = []
        cursor: str | None = None
        with session_factory() as session:
            while True:
                page = read_audit_page(session, limit=10, cursor=cursor)
                seen.extend(row.sequence_number for row in page.rows)
                cursor = page.next_cursor
                if cursor is None:
                    break

        assert len(seen) == 25
        assert len(set(seen)) == 25, "a row appeared on more than one page"
        assert seen == sorted(seen, reverse=True), "the order was not stable across pages"

    def test_rows_written_between_pages_do_not_shift_the_window(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """The reason it is a cursor and not an OFFSET.

        Under OFFSET, rows inserted before the cursor push everything down, so the
        second page repeats what the first already returned.
        """

        write_rows(session_factory, 15, "audit.first")

        with session_factory() as session:
            first = read_audit_page(session, limit=10)
        first_ids = [row.sequence_number for row in first.rows]

        # New rows arrive between the two requests, sorting above the cursor.
        write_rows(session_factory, 5, "audit.interleaved")

        with session_factory() as session:
            second = read_audit_page(session, limit=10, cursor=first.next_cursor)
        second_ids = [row.sequence_number for row in second.rows]

        assert not set(first_ids) & set(second_ids), (
            "a row returned on page one came back on page two"
        )

    def test_sorting_by_a_non_unique_column_still_paginates_without_repeats(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """`occurred_at` ties are the case a non-total sort gets wrong.

        Every row here is written in one transaction, so many share a timestamp
        exactly. The unique tiebreaker is what keeps the boundary from landing
        inside a tie group and repeating a row.
        """

        write_rows(session_factory, 20, "audit.tied")

        seen: list[int] = []
        cursor: str | None = None
        with session_factory() as session:
            while True:
                page = read_audit_page(session, sort="occurred_at", limit=6, cursor=cursor)
                seen.extend(row.sequence_number for row in page.rows)
                cursor = page.next_cursor
                if cursor is None:
                    break

        assert len(seen) == 20
        assert len(set(seen)) == 20, (
            "rows repeated across pages, so the sort on a tied column was not "
            "made total by the tiebreaker"
        )


class TestAllowlisting:
    def test_an_unlisted_sort_field_is_refused(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """Not injection safety — an unlisted column is one no index covers."""

        with session_factory() as session, pytest.raises(InvalidListParameterError):
            read_audit_page(session, sort="new_values")

    def test_an_unlisted_filter_field_is_refused(self) -> None:
        with pytest.raises(InvalidListParameterError):
            AUDIT_LIST_SPEC.require_filterable("previous_values")

    def test_every_allowlisted_filter_is_actually_usable(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """A name on the list that the query cannot apply is worse than absent."""

        write_rows(session_factory, 2, "audit.filterable")

        with session_factory() as session:
            page = read_audit_page(
                session, AuditQuery(action="audit.filterable", actor_type="admin_user")
            )

        assert len(page.rows) == 2

    def test_a_filter_narrows_the_result(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        write_rows(session_factory, 4, "audit.kept")
        write_rows(session_factory, 3, "audit.excluded")

        with session_factory() as session:
            page = read_audit_page(session, AuditQuery(action="audit.kept"))

        assert len(page.rows) == 4
        assert {row.action for row in page.rows} == {"audit.kept"}


class TestCursors:
    def test_a_tampered_cursor_is_a_client_error(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with session_factory() as session, pytest.raises(InvalidCursorError) as raised:
            read_audit_page(session, cursor="not-a-cursor")

        assert raised.value.status_code == 400

    def test_the_error_does_not_describe_the_encoding(self) -> None:
        """A cursor is opaque. Describing its shape invites clients to build their own."""

        message = InvalidCursorError().message.lower()

        assert "base64" not in message
        assert "json" not in message
        assert "sequence" not in message


class TestTheSpecRefusesUnstableConfigurations:
    def test_a_spec_without_a_unique_sort_is_rejected_at_construction(self) -> None:
        """Caught where the read path is defined, not when a page repeats in production."""

        with pytest.raises(ValueError, match="unique sort field"):
            ListSpec(sorts=(SortField("occurred_at", AuditLog.occurred_at),))

    def test_a_spec_with_no_sorts_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="cannot order deterministically"):
            ListSpec(sorts=())

    def test_a_default_sort_outside_the_allowlist_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="not an allowlisted field"):
            ListSpec(
                sorts=(SortField("sequence_number", AuditLog.sequence_number, unique=True),),
                default_sort="occurred_at",
            )
