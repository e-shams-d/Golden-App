"""Which queues are this person's, and how much is in each.
`15_Agent_Implementation_Plan.md:1260`.

M11 Screens slice 2. §19's goal is that each role can *identify* and complete its work from
controlled queues, and identifying it needs an answer to "which of the sixteen are mine" that the
screen does not have to guess.

**Why this exists when `reports/queue_summary.py` already counts them.** The report is guarded by
`report.read`, and the catalogue's own grants make that the wrong door for two of the six roles
that hold a queue:

    warehouse_operator   holds gold_sale.dispatch — three queues — and not report.read
    technical_admin      holds file.quarantine_review — one queue — and not report.read

A warehouse operator's whole working day is those three queues, so a landing page built on
`GET /reports/queue-summary` would answer 403 to the person who needs it most. That gap is already
recorded as an owner question about the report; **it is not something a screen may route around by
asking for a permission the operator does not need.**

So the count is reached a second way and computed exactly once: `visible_queues` calls
`summarise_queues`. There is no second definition of "waiting", and if a queue's predicate changes,
both surfaces move together because only one of them can count.

**No grant of its own, and each entry earns its place separately.** Asking "what is mine" needs no
authority; being told about a queue needs that queue's own grant, which is the filter
`summarise_queues` already applies. A caller holding nothing receives an empty list — true, and the
right answer for somebody with no queues.

**This is not a new disclosure.** Every field here is already reachable by the same caller: the
`waiting` number is the `total` each queue's own page returns, and the filter and sort names are the
ones that queue's route accepts. `test_queue_index.py` asserts that equality rather than asserting
this paragraph.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.queues.registry import BUILT
from app.reports.queue_summary import summarise_queues
from app.security.actor import ActorContext


@dataclass(frozen=True, slots=True)
class QueueListing:
    """One queue a caller may open, with what the screen needs to open it correctly.

    `filters` and `sorts` are here so that **no screen has to hold a copy of the allowlist.** A
    filter control rendered from a hardcoded list is a control that offers a key the route refuses
    the day a spec changes — and `read_queue_page` refuses rather than ignores, so the mistake
    surfaces as a 400 in front of a person doing their job.

    `default_sort` is what the route applies when the request names no sort. Sent so the control
    can show which ordering is in force; a screen that displayed nothing selected would be telling
    a person the rows are in no particular order, when they are always in one.
    """

    name: str
    waiting: int
    filters: tuple[str, ...]
    sorts: tuple[str, ...]
    default_sort: str


def visible_queues(session: Session, *, actor: ActorContext) -> tuple[QueueListing, ...]:
    """The caller's queues, in the registry's order, each counted.

    The order is `BUILT`'s, which is §19.2's — roughly the order money moves. Kept rather than
    sorted by name or by count: a queue list that reorders itself as work arrives is one a person
    cannot learn the shape of, and "the busiest first" is a judgement about priority that §19 does
    not make.
    """

    listings: list[QueueListing] = []
    for count in summarise_queues(session, actor=actor).counts:
        definition = BUILT[count.queue]
        listings.append(
            QueueListing(
                name=count.queue,
                waiting=count.waiting,
                # Sorted, because `filters` is a `frozenset` and an unordered field would make
                # the response differ between processes for no reason.
                filters=tuple(sorted(definition.spec.filters)),
                # Declaration order, which is the spec's: the tiebreaker is last by convention and
                # sorting the names would move it into the middle.
                sorts=tuple(sort.name for sort in definition.spec.sorts),
                default_sort=definition.spec.default_sort,
            )
        )
    return tuple(listings)
