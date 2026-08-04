"""The outbox dispatcher: a post-commit reader, in its own session and transaction.

Write side and dispatch side are two different transactional regimes and must not
share a session. The writer inserts an event inside the business transaction so
the two share a fate. The dispatcher reads only committed rows, and its failures
must not touch the business transaction at all — by then there is nothing to roll
back, and pretending otherwise would let a notification failure undo a payment.

Delivery is at-least-once. That is not a weakness to be engineered away: making
it exactly-once would require the broker and the database to commit together,
which they cannot. `outbox_event_id` is the mandated consumer dedup key, and a
consumer that ignores it will see duplicates — the contract is stated here
because nowhere downstream can discover it.

The dispatcher is deliberately not scheduled from this module. Wiring the poll
interval belongs with the scheduler, and a loop that starts itself on import is
one that runs in every process that happens to import it, including the API.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select

from app.core.logging import get_logger, log_event
from app.core.time import utc_now
from app.db.claiming import DEFAULT_LEASE, claim_outbox_events
from app.db.models.outbox_event import OutboxEvent
from app.db.unit_of_work import UnitOfWorkFactory
from app.workers.execution import backoff_delay

logger = get_logger("workers.dispatcher")

MAX_DELIVERY_ATTEMPTS = 8


@dataclass(frozen=True)
class DispatchReport:
    published: int = 0
    failed: int = 0
    dead_lettered: int = 0
    claimed: int = 0
    errors: tuple[str, ...] = field(default_factory=tuple)


def dispatch_once(
    uow_factory: UnitOfWorkFactory,
    deliver: Callable[[OutboxEvent], None],
    *,
    worker_id: str,
    limit: int = 20,
    lease: timedelta = DEFAULT_LEASE,
) -> DispatchReport:
    """Claim a batch, deliver each, record the result. One transaction.

    Claim and result share a transaction on purpose: a crash between them would
    otherwise leave rows claimed by a dispatcher that no longer exists, and only
    the lease would eventually recover them. Delivery itself happens inside that
    window, which is acceptable only because `deliver` publishes to a broker
    rather than doing business work — the no-IO-under-lock rule applies to
    commands, and this is the one place whose entire purpose is the outbound call.
    """

    published = failed = dead_lettered = 0
    errors: list[str] = []

    with uow_factory() as uow:
        claimed = claim_outbox_events(
            uow.session, worker_id=worker_id, limit=limit, lease=lease
        )

        for event in claimed:
            try:
                deliver(event)
            except Exception as error:
                message = f"{type(error).__name__}: {error}"
                errors.append(message)
                if event.attempt_count >= MAX_DELIVERY_ATTEMPTS:
                    event.status = "dead_lettered"
                    event.locked_at = None
                    event.locked_by = None
                    dead_lettered += 1
                    log_event(
                        logger,
                        logging.ERROR,
                        "outbox_event_dead_lettered",
                        event_type=event.event_type,
                        attempts=event.attempt_count,
                    )
                else:
                    event.status = "failed"
                    event.locked_at = None
                    event.locked_by = None
                    event.available_at = utc_now() + backoff_delay(event.attempt_count)
                    failed += 1
                # Redacted: an exception from a client library routinely carries
                # the payload it was sending.
                event.last_error = type(error).__name__
                continue

            event.status = "published"
            event.published_at = utc_now()
            event.locked_at = None
            event.locked_by = None
            published += 1

        uow.commit()

    return DispatchReport(
        published=published,
        failed=failed,
        dead_lettered=dead_lettered,
        claimed=len(claimed),
        errors=tuple(errors),
    )


@dataclass(frozen=True)
class OutboxLag:
    """What an operator needs to know without reading the table.

    Age of the oldest undelivered event, not a count: a backlog of ten thousand
    events published seconds ago is healthy, and a single event stuck for six
    hours is not. A count cannot tell those apart.
    """

    pending: int
    dead_lettered: int
    oldest_pending_age_seconds: float | None

    @property
    def has_dead_letters(self) -> bool:
        return self.dead_lettered > 0


def outbox_lag(uow_factory: UnitOfWorkFactory) -> OutboxLag:
    with uow_factory() as uow:
        pending = uow.session.execute(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.status.in_(("pending", "processing", "failed")))
        ).scalar_one()
        dead = uow.session.execute(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.status == "dead_lettered")
        ).scalar_one()
        oldest = uow.session.execute(
            select(func.min(OutboxEvent.created_at)).where(
                OutboxEvent.status.in_(("pending", "processing", "failed"))
            )
        ).scalar_one()
        uow.rollback()

    age = (utc_now() - oldest).total_seconds() if oldest is not None else None
    return OutboxLag(pending=pending, dead_lettered=dead, oldest_pending_age_seconds=age)


def undeliverable(events: Sequence[OutboxEvent]) -> list[OutboxEvent]:
    """Events an operator must look at. Kept, never cleaned up automatically.

    ADR-005 is open, so nothing here deletes or archives anything.
    """

    return [event for event in events if event.status == "dead_lettered"]
