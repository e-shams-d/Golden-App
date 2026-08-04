"""List conventions: bounded, deterministically ordered, allowlisted.

Every rule here exists because its absence is a specific production failure, not
because lists ought to be tidy.

**A limit is mandatory and capped.** A list endpoint without one is a denial of
service the caller does not know they are performing: `audit_logs` grows without
bound, and the first support query that omits `limit` selects the table.

**The sort is total.** Ordering by a non-unique column leaves ties in an order
PostgreSQL may change between executions, so page two can repeat or skip rows
that page one already returned. Every sort therefore ends with a unique
tiebreaker, and the cursor is built from it.

**Sort and filter fields are allowlisted.** Not to prevent SQL injection — the
query builder handles that — but because an unlisted column is one an index does
not cover, and a filter on it turns a page request into a sequential scan of the
whole table.

**Cursor, not offset.** `OFFSET` re-reads and discards every skipped row, so the
last page of a large table is the most expensive one. It is also wrong under
concurrent inserts: a row added before the cursor shifts every later page by one,
which silently duplicates or drops entries.

Counts are deliberately absent from this module. An exact count of a permission-
scoped set is a second full scan, and it is the part of a list response nobody
reads and everybody pays for. A caller that needs one asks for it explicitly.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Select, and_, or_
from sqlalchemy.orm import InstrumentedAttribute

from app.core.errors import AppError

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class InvalidCursorError(AppError):
    """The cursor did not come from this API, or has been edited.

    400 rather than 500: it is the caller's parameter. The message never explains
    the encoding — a cursor is an opaque token, and describing its shape invites
    clients to construct their own and depend on the internals.
    """

    def __init__(self) -> None:
        super().__init__("BAD_REQUEST", "The pagination cursor is not valid.", 400)


class InvalidListParameterError(AppError):
    """A sort or filter field that is not allowlisted, or a limit out of range."""

    def __init__(self, message: str) -> None:
        super().__init__("BAD_REQUEST", message, 400)


@dataclass(frozen=True)
class SortField:
    """One allowlisted sort column.

    `unique` marks a column that can terminate a sort on its own. A sort without
    at least one is not total, and pagination over it is not stable.
    """

    name: str
    column: InstrumentedAttribute[Any]
    unique: bool = False

    def decode(self, value: Any) -> Any:
        """Restore a cursor value to the type the column compares against.

        A cursor is JSON, and JSON has no datetime. Round-tripped naively a
        timestamp comes back as a string, and PostgreSQL answers
        `operator does not exist: timestamp with time zone < character varying`
        — so every sort on a non-numeric column fails at the second page. Found
        by paginating on `occurred_at`, which is exactly the column the tie-
        breaking rule exists for.

        Derived from the column's own type rather than declared per field, so a
        sort added later on a timestamp works without anyone remembering this.
        """

        if isinstance(value, str) and isinstance(self.column.type, DateTime):
            try:
                return datetime.fromisoformat(value)
            except ValueError as error:
                raise InvalidCursorError() from error
        return value


@dataclass(frozen=True)
class ListSpec:
    """What a caller may sort and filter by on one read path.

    Constructed once per read path, next to the indexes that support it, rather
    than assembled from request parameters — which is how an unindexed column
    becomes filterable by accident.
    """

    sorts: tuple[SortField, ...]
    filters: frozenset[str] = field(default_factory=frozenset)
    default_sort: str = ""

    def __post_init__(self) -> None:
        if not self.sorts:
            raise ValueError("a list spec with no sort fields cannot order deterministically")
        if not any(sort.unique for sort in self.sorts):
            raise ValueError(
                "no unique sort field: the sort cannot be made total, so pages can "
                "repeat or skip rows under concurrent writes"
            )
        names = [sort.name for sort in self.sorts]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate sort field names: {names}")
        if self.default_sort and self.default_sort not in names:
            raise ValueError(f"default sort {self.default_sort!r} is not an allowlisted field")

    def sort_by(self, name: str) -> SortField:
        for sort in self.sorts:
            if sort.name == name:
                return sort
        raise InvalidListParameterError(
            f"{name!r} is not a sortable field. Allowed: "
            f"{', '.join(sorted(sort.name for sort in self.sorts))}."
        )

    def tiebreaker(self) -> SortField:
        for sort in self.sorts:
            if sort.unique:
                return sort
        raise AssertionError("__post_init__ guarantees one exists")

    def require_filterable(self, name: str) -> None:
        if name not in self.filters:
            raise InvalidListParameterError(
                f"{name!r} is not a filterable field. Allowed: "
                f"{', '.join(sorted(self.filters)) or 'none'}."
            )


def encode_cursor(values: dict[str, Any]) -> str:
    """Opaque, but deliberately not secret.

    Base64 of JSON: a caller can decode it, and that is fine — the values are
    already in the rows they just received. What matters is that it is not a
    number they can increment, because that is how offset semantics creep back in.
    """

    raw = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        decoded = json.loads(raw)
    except (ValueError, binascii.Error, UnicodeError) as error:
        raise InvalidCursorError() from error
    if not isinstance(decoded, dict):
        raise InvalidCursorError()
    return {str(key): value for key, value in decoded.items()}


def normalise_limit(requested: int | None) -> int:
    """Absent means the default. Out of range is refused, never silently clamped.

    Clamping would let a caller ask for 10,000, receive 200, and page through the
    result believing it had them all.
    """

    if requested is None:
        return DEFAULT_LIMIT
    if requested < 1 or requested > MAX_LIMIT:
        raise InvalidListParameterError(
            f"limit must be between 1 and {MAX_LIMIT}; {requested} was requested."
        )
    return requested


@dataclass(frozen=True)
class Page[RowT]:
    rows: Sequence[RowT]
    next_cursor: str | None

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None


def apply_pagination[RowT](
    statement: Select[tuple[RowT]],
    spec: ListSpec,
    *,
    sort: str | None = None,
    descending: bool = True,
    limit: int | None = None,
    cursor: str | None = None,
) -> tuple[Select[tuple[RowT]], int]:
    """Add a total ordering, a cursor predicate and a bounded limit.

    Returns the statement and the effective limit, because the caller needs the
    limit again to decide whether a further page exists — fetching `limit + 1` and
    trimming is how that is detected without a second count query.
    """

    effective_limit = normalise_limit(limit)
    primary = spec.sort_by(sort or spec.default_sort or spec.sorts[0].name)
    tiebreaker = spec.tiebreaker()

    order = [primary.column.desc() if descending else primary.column.asc()]
    if primary.name != tiebreaker.name:
        # The sort is only total once a unique column terminates it. Without this
        # two rows sharing a timestamp can swap between executions, and a page
        # boundary that lands between them repeats or drops one.
        order.append(tiebreaker.column.desc() if descending else tiebreaker.column.asc())

    if cursor is not None:
        values = decode_cursor(cursor)
        if tiebreaker.name not in values:
            raise InvalidCursorError()
        statement = statement.where(
            _cursor_predicate(primary, tiebreaker, values, descending=descending)
        )

    # One more than asked for, so "is there another page" is answered by the rows
    # already fetched rather than by counting the whole set again.
    return statement.order_by(*order).limit(effective_limit + 1), effective_limit


def _cursor_predicate(
    primary: SortField,
    tiebreaker: SortField,
    values: dict[str, Any],
    *,
    descending: bool,
) -> Any:
    """Keyset comparison over (primary, tiebreaker).

    Written as an explicit OR rather than a row-value comparison because the two
    columns may sort in the same direction but hold different types, and a
    row-value form silently changes meaning when a NULL appears in the primary.
    """

    tiebreaker_value = tiebreaker.decode(values[tiebreaker.name])

    if primary.name == tiebreaker.name:
        return (
            tiebreaker.column < tiebreaker_value
            if descending
            else tiebreaker.column > tiebreaker_value
        )

    if values.get(primary.name) is None:
        raise InvalidCursorError()
    primary_value = primary.decode(values[primary.name])

    if descending:
        return or_(
            primary.column < primary_value,
            and_(primary.column == primary_value, tiebreaker.column < tiebreaker_value),
        )
    return or_(
        primary.column > primary_value,
        and_(primary.column == primary_value, tiebreaker.column > tiebreaker_value),
    )


def build_page[RowT](
    rows: Sequence[RowT],
    limit: int,
    spec: ListSpec,
    *,
    sort: str | None = None,
) -> Page[RowT]:
    """Trim the extra row and build the cursor from the last row actually returned."""

    if len(rows) <= limit:
        return Page(rows=rows, next_cursor=None)

    visible = rows[:limit]
    last = visible[-1]
    primary = spec.sort_by(sort or spec.default_sort or spec.sorts[0].name)
    tiebreaker = spec.tiebreaker()

    values = {tiebreaker.name: getattr(last, tiebreaker.name)}
    if primary.name != tiebreaker.name:
        values[primary.name] = getattr(last, primary.name)

    return Page(rows=visible, next_cursor=encode_cursor(values))
