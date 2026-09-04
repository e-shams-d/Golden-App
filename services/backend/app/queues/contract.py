"""What a queue is, expressed once. `15_Agent_Implementation_Plan.md:1256`.

M11 slice 2, and the answer to the plan's **G-1**: §19 `:1260` names twenty-four queues, document
05 defines a route for none of them, and `command_catalog.yaml` says query endpoints are outside
its scope. There is no approved shape, so this module is the implementer's decision written down
where it can be reviewed rather than inferred from seven routes.

**The decision: one endpoint per queue, under `/queues/`, named for the queue §19 names.**
The alternative — one endpoint with a `?queue=` parameter — was rejected because it makes the set
of queues a *runtime value*, and §19 `:1298` asks for allowlisted filters. A queue reached by a
parameter is a filter whose allowlist lives in a request; a queue reached by a path is one the
route table enumerates and `test_m3_definition_of_done.py` can refuse to let ship unclassified.

**Slice 2 registers exactly one**, so that reversing this decision costs one slice rather than
seven.

**A queue is four things and no more:** the rows it draws from, the permission that may see it, the
`ListSpec` that bounds it, and the predicate that names its state. Everything else — cursor,
ordering, limit, refusal of an unlisted key — comes from `app/db/pagination.py`, which has
expressed those rules since M9's audit read. Writing a second pagination helper here would have
been the easy path and the wrong one.

**The sixth rule is the only one this module invents.** §19 `:1298` asks for "permission-aware
counts", and `app/db/pagination.py` says in terms that counts are deliberately absent from it: "an
exact count of a permission-scoped set is a second full scan". That objection is about *cost*, not
about correctness, and a queue without a count is a queue a person cannot triage — "how much work
is waiting" is the question a queue exists to answer. So the count is here rather than there, and
it is computed from **the same `Select` the page came from**, which is what makes it
permission-aware by construction: there is no second predicate that could disagree with the first.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.db.pagination import (
    ListSpec,
    Page,
    apply_pagination,
    build_page,
)
from app.security.actor import ActorContext


@dataclass(frozen=True, slots=True)
class QueueRow:
    """One row of any queue. **The same five fields for all twenty-four.**

    M11 slice 3, and the shape is a disclosure decision rather than a convenience. §19 `:1298`'s
    last rule — "technical admin does not receive full financial detail by default" — is easy to
    honour when every queue answers the same narrow question and impossible to audit when each
    returns its own aggregate. A queue exists to be *triaged*: what is it, whose is it, what state
    is it in, how long has it waited. The detail route answers everything else.

    `reference` is the number a person says out loud — `request_number`, `batch_number`,
    `export_number`. `trader_id` is nullable because not every queue is about one business: a batch
    version deliberately spans many, and a maintenance task belongs to none.

    **No amount field, on any queue.** Adding one would be a decision made once and inherited
    twenty-four times, which is precisely how a technical admin ends up reading financial detail.
    """

    id: uuid.UUID
    reference: str
    status: str
    created_at: datetime
    trader_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class QueueDefinition[RowT]:
    """One of §19's twenty-four, as code.

    `name` is the URL segment and the identifier a test cites. It is the queue's name in §19.2
    rendered in kebab-case, not a name invented here — so a queue that drifts from the document is
    a rename somebody has to justify.

    `permission` is the single grant that may read it. Not a list: a queue two roles reach for
    different reasons is two queues with different columns, which is the mistake §19 `:1298`'s last
    rule exists to prevent.

    `predicate` receives the base statement and returns it narrowed to the queue's state. It takes
    the actor too, because some queues are scoped to who is asking — and a signature that cannot
    express that would push scoping into the route, where it is written once per route instead of
    once per queue.
    """

    name: str
    permission: str
    spec: ListSpec
    predicate: Callable[[Select[tuple[RowT]], ActorContext], Select[tuple[RowT]]]
    source: str
    # M11 slice 3. The mapped class the queue draws from, and how one of its rows becomes the
    # response. Both moved onto the definition when the second queue arrived: with eleven of them
    # the route body is identical apart from these two, and eleven copies of one function is how
    # the envelope drifts. `app/api/v1/queues.py` now generates a route per registry entry.
    entity: Any = None
    render: Callable[[Any], QueueRow] | None = None
    # Every allowlisted filter name, bound to the column it filters on. Separate from `spec.sorts`
    # because a field may be filterable without being sortable — `status` is the obvious one, and
    # resolving filters through the sort list would have quietly required every filter to also be
    # an ordering key.
    filter_columns: dict[str, InstrumentedAttribute[Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """An allowlisted filter with no column is refused at construction, not at request time.

        The two collections are declared separately and could disagree; if they do, the failure is
        a 500 on whichever request first names the orphaned key — which is to say, in production,
        on the day somebody uses the filter nobody tested. Checking here makes it an import error
        instead, and `test_queue_registry` never has to think about it.
        """

        missing = sorted(self.spec.filters - self.filter_columns.keys())
        if missing:
            raise ValueError(
                f"queue {self.name!r} allowlists filters with no column bound: {missing}. "
                "A filter that cannot be applied is worse than one that does not exist."
            )
        extra = sorted(self.filter_columns.keys() - self.spec.filters)
        if extra:
            raise ValueError(
                f"queue {self.name!r} binds columns for filters that are not allowlisted: "
                f"{extra}. The spec is what decides; a bound column is not permission to filter."
            )

    def statement(self, actor: ActorContext, base: Select[tuple[RowT]]) -> Select[tuple[RowT]]:
        return self.predicate(base, actor)


@dataclass(frozen=True, slots=True)
class QueuePage[RowT]:
    """A page of a queue, its cursor, and how much work is waiting.

    `total` is the count of everything the caller may see in this queue, not the size of the page.
    A page size is something the caller already knows; the number they cannot compute is the one
    behind the cursor.
    """

    rows: Sequence[RowT]
    next_cursor: str | None
    total: int


def read_queue_page[RowT](
    session: Session,
    definition: QueueDefinition[RowT],
    base: Select[tuple[RowT]],
    *,
    actor: ActorContext,
    filters: dict[str, Any] | None = None,
    sort: str | None = None,
    descending: bool = True,
    limit: int | None = None,
    cursor: str | None = None,
) -> QueuePage[RowT]:
    """§19 `:1298`'s six rules, applied in one place.

    The **filters are checked against the queue's own spec before they are applied**, so a key that
    is not allowlisted raises rather than being dropped. Dropping it would return a different page
    than the caller asked for and say nothing about it, which is the failure mode
    `app/db/pagination.py` was written to prevent and the one `SEC-QUEUE-001` asserts.

    The count is taken over `narrowed` — the statement *after* the queue predicate and the filters,
    and before pagination. Taking it before the predicate would count rows the caller may not see;
    taking it after the cursor would count only what is left, which is a different question.
    """

    narrowed = definition.statement(actor, base)
    for name, value in (filters or {}).items():
        definition.spec.require_filterable(name)
        narrowed = narrowed.where(definition.filter_columns[name] == value)

    total = session.scalar(select(func.count()).select_from(narrowed.subquery())) or 0

    statement, effective = apply_pagination(
        narrowed,
        definition.spec,
        sort=sort,
        descending=descending,
        limit=limit,
        cursor=cursor,
    )
    rows: Sequence[RowT] = session.execute(statement).scalars().all()
    page: Page[RowT] = build_page(rows, effective, definition.spec, sort=sort)
    return QueuePage(rows=page.rows, next_cursor=page.next_cursor, total=int(total))
