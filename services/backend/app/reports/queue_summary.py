"""How much work is waiting, for the person asking. `15_Agent_Implementation_Plan.md:1331`.

M11 slice 7. §19's goal is that "each role can identify and complete its work from controlled
queues", and a role that must open sixteen pages to find out whether anything is waiting cannot do
the first half of that.

**Its content needs no judgement, which is why this is the report the milestone builds.** The
plan's G-4 records that §19 names report generation as a job and names no report, and that
`report.read` exists while no document says what a report contains. Choosing what belongs in a
financial report is M0's to decide. A count per queue is derivable from tables that already exist
and decides nothing: it is the queues this milestone built, counted.

**Permission-aware, and that is §19 `:1298`'s sixth rule rather than a convenience.** A holder of
`report.read` is not thereby a holder of `gold_sale.dispatch`, so the summary lists only the queues
whose own grant the caller holds. Reporting a count for a queue somebody may not read would leak
exactly what the queue's guard exists to withhold — how much is happening in a part of the business
that is not theirs.

**No export.** §19 lists report export and `permission_catalog.yaml:700` gives `report.export`
`default_roles: []` — no role holds it, pending an explicit grant. A route behind it would deny
every caller, which this project already carries once in `bank_profile.activate_version`, and
guarding an export by a *different* permission would invent an authority the catalogue withholds
on purpose. Recorded as the plan's G-3 rather than built.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.queues.contract import read_queue_page
from app.queues.registry import BUILT
from app.security.actor import ActorContext


@dataclass(frozen=True, slots=True)
class QueueCount:
    """One queue and how much is in it, for a caller who may read that queue."""

    queue: str
    waiting: int


@dataclass(frozen=True, slots=True)
class QueueSummary:
    """Every queue this caller may read, counted.

    `total` is the sum across them, which is the number a person actually acts on — "is there
    anything for me today". It is deliberately not a system-wide total: two roles asking the same
    question get different answers, because they have different work.
    """

    counts: tuple[QueueCount, ...]

    @property
    def total(self) -> int:
        return sum(count.waiting for count in self.counts)


def summarise_queues(session: Session, *, actor: ActorContext) -> QueueSummary:
    """Count each built queue the actor's grants allow, in the registry's order.

    **The count comes from the queue's own predicate**, through `read_queue_page` with a limit of
    one. Re-implementing the counting here would be a second definition of what "waiting" means for
    sixteen queues, and the two would drift the first time a predicate changed. One row is fetched
    and discarded; the `total` this reads is computed over the full narrowed statement, which is
    the same number the queue's own page returns.
    """

    counts: list[QueueCount] = []
    for name, definition in BUILT.items():
        if definition.permission not in actor.permissions:
            # Not an error and not a zero — the queue simply is not this person's work, so it is
            # absent from their summary. A zero would tell them a queue exists and is empty, which
            # is information about somebody else's business.
            continue
        page = read_queue_page(
            session,
            definition,
            select(definition.entity),
            actor=actor,
            limit=1,
        )
        counts.append(QueueCount(queue=name, waiting=page.total))
    return QueueSummary(counts=tuple(counts))
