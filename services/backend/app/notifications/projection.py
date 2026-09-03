"""Turning outbox events into messages for people. `04_Database_Schema.md` §13.3.

M9 slice 7, and the plan's G-2. **The consumer M2 said did not exist.**
`app/workers/tasks/maintenance.py` has carried the sentence since the outbox was built: "Delivery
is a no-op for now: nothing consumes these events in Phase 1A, and a dispatcher that invented a
destination would publish somewhere no consumer agreed to." The destination now exists and document
04 specifies it, so the no-op ends here rather than being replaced by a guess.

**Three events, and the third is a promise being kept.** G-5 decided that a failed payment reaches
its trader as a notification rather than as a publication, on the grounds that
`PaymentAttemptFailed` was already enqueued and only needed a reader. A decision that routes a case
to a mechanism nobody builds is worse than no decision, so `payment_attempt_failed` is here and
`OPS-NOTIFY-002` is what proves it.

**A notification is never workflow truth.** §13.3 says it and `audit_outbox_catalog.yaml` repeats
it as `notifications_are_workflow_truth: false`. So this module *only ever inserts* — it reads the
financial tables to address and word a message and writes nothing back to them, which is what makes
`OPS-NOTIFY-001` assertable rather than aspirational.

**Its own transaction, opened by the dispatcher.** `app/workers/dispatcher.py` runs post-commit in
a session of its own, and its docstring gives the reason: "a notification failure undo a payment"
is precisely the outcome the separation prevents. An event this raises on is marked `failed` and
retried with backoff; the money it describes has already been committed and stays committed.

**Unknown event types are ignored, not an error.** The outbox carries eleven event types and this
consumer reads three. Raising on the other eight would dead-letter events that are behaving exactly
as designed, and the dispatcher would report a fault every time a batch was approved.

Covers: OPS-NOTIFY-001, OPS-NOTIFY-002.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from app.db.models.gold_sale import GoldSaleOrder
from app.db.models.notification import (
    ENTITY_GOLD_SALE_ORDER,
    ENTITY_PAYMENT_PUBLICATION,
    ENTITY_PAYMENT_REQUEST,
    NOTIFICATION_UNREAD,
    RECIPIENT_TRADER_USER,
    TYPE_ATTEMPT_FAILED,
    TYPE_GOLD_ORDER_READY,
    TYPE_RESULT_CORRECTED,
    TYPE_RESULT_PUBLISHED,
    Notification,
)
from app.db.models.outbox_event import OutboxEvent
from app.db.models.payment_request import PaymentRequest
from app.db.unit_of_work import UnitOfWorkFactory

# `audit_outbox_catalog.yaml`'s event names, mapped to what a person is told. The keys are the
# contract: an event renamed there and not here stops producing notifications silently, which is
# what `test_notification_projection.py` asserts against the catalogue rather than against this
# dictionary.
HANDLED_EVENTS: dict[str, str] = {
    "PaymentResultPublicationCreated": TYPE_RESULT_PUBLISHED,
    "TraderResultCorrected": TYPE_RESULT_CORRECTED,
    "PaymentAttemptFailed": TYPE_ATTEMPT_FAILED,
    # M10 slice 8, and the first event here whose aggregate is not a payment request. Everything
    # above is about money the centre sent; this is about gold a trader bought and has now paid
    # for. `_recipient_and_subject` is what the difference cost — see its docstring.
    "GoldOrderReadyForDispatch": TYPE_GOLD_ORDER_READY,
}


class NotificationProjectionError(RuntimeError):
    """The event named something this projection could not resolve.

    Distinct from ignoring an unhandled event type. This is "a `PaymentAttemptPaid` for a request
    that does not exist" — a statement that the event and the database disagree, which the
    dispatcher should retry and eventually dead-letter rather than swallow.
    """


def project(event: OutboxEvent, *, session: Session) -> Notification | None:
    """One event, one notification, or `None` if this consumer does not read that type.

    Returns the row rather than nothing so a test can assert on it directly; the dispatcher
    ignores the value.
    """

    notification_type = HANDLED_EVENTS.get(str(event.event_type))
    if notification_type is None:
        return None

    payload: dict[str, Any] = dict(event.payload or {})

    if notification_type == TYPE_GOLD_ORDER_READY:
        title, body, entity_type, entity_id, trader_id = _gold_order_message(session, payload)
    else:
        request = _request_for(session, payload)
        trader_id = request.trader_id
        title, body, entity_type, entity_id = _message(
            notification_type, request=request, payload=payload
        )

    recipient = _primary_trader_user(session, trader_id)
    if recipient is None:
        raise NotificationProjectionError(
            f"trader {trader_id} has no primary user, so there is nobody to tell about "
            f"{event.event_type}. `traders.primary_phone` and `trader_users.is_primary` are what "
            "make a business reachable; a business with neither cannot be notified."
        )

    notification = Notification(
        recipient_actor_type=RECIPIENT_TRADER_USER,
        recipient_actor_id=recipient,
        notification_type=notification_type,
        title=title,
        body=body,
        entity_type=entity_type,
        entity_id=entity_id,
        status=NOTIFICATION_UNREAD,
        # `audit_outbox_catalog.yaml`: `consumer_deduplication_key: outbox_event_id`. The partial
        # unique index on `(recipient, deduplication_key)` is what makes at-least-once delivery
        # produce one message instead of several.
        deduplication_key=str(event.id),
    )
    return _insert_once(session, notification)


def _insert_once(session: Session, notification: Notification) -> Notification:
    """Insert, or return the message this event already produced.

    **A redelivery must be a no-op, not a failure.** The first version let the unique violation
    escape, which was the index working and the consumer not: `dispatch_once` runs a whole batch in
    one transaction, so one duplicate poisoned every other event in it and the dispatcher reported
    a fault for delivery that had already succeeded. At-least-once is the contract, so arriving
    twice is normal traffic rather than an error.

    A savepoint rather than a read-then-insert. The dispatcher claims each event with
    `FOR UPDATE SKIP LOCKED`, so two workers cannot hold the same one and a read would in fact be
    safe — but the same argument was wrong for the evidence links in slice 2, and a savepoint costs
    nothing and does not depend on the claim staying exclusive.
    """

    existing = session.scalar(
        select(Notification).where(
            Notification.recipient_actor_type == notification.recipient_actor_type,
            Notification.recipient_actor_id == notification.recipient_actor_id,
            Notification.deduplication_key == notification.deduplication_key,
        )
    )
    if existing is not None:
        return existing

    savepoint = session.begin_nested()
    try:
        session.add(notification)
        session.flush()
    except IntegrityError:
        savepoint.rollback()
        found = session.scalar(
            select(Notification).where(
                Notification.recipient_actor_type == notification.recipient_actor_type,
                Notification.recipient_actor_id == notification.recipient_actor_id,
                Notification.deduplication_key == notification.deduplication_key,
            )
        )
        if found is None:  # pragma: no cover - the violation says a row is there
            raise
        return found
    savepoint.commit()
    return notification


def notification_deliverer(uow_factory: UnitOfWorkFactory) -> Any:
    """The `deliver` callable `dispatch_once` expects, bound to a session factory.

    **It writes in the dispatcher's own transaction**, which is the one `dispatch_once` opened and
    commits alongside the event's status. That is deliberate: a notification committed while its
    event stayed `pending` would be re-sent on the next poll, and an event marked `published` while
    its notification rolled back would be a message nobody ever gets. They share a fate with each
    other and with nothing financial — the money committed one transaction earlier.
    """

    def deliver(event: OutboxEvent) -> None:
        # The session the dispatcher loaded this row in, so the insert lands in its transaction.
        # `object_session` rather than reaching into `_sa_instance_state`: same answer, and it is
        # the documented way to ask.
        session = object_session(event)
        if session is None:  # pragma: no cover - the dispatcher always loads it in a session
            raise NotificationProjectionError(
                "the event is detached from its session, so the notification could not join the "
                "dispatcher's transaction"
            )
        project(event, session=session)

    # `uow_factory` is accepted and not used: the dispatcher already owns the transaction, and a
    # deliverer that opened a second one would write outside it. Kept in the signature because
    # every other worker entry point takes it, and a function that looked different here would
    # invite somebody to give it its own session.
    _ = uow_factory
    return deliver


def _gold_order_message(
    session: Session, payload: dict[str, Any]
) -> tuple[str, str, str, uuid.UUID, uuid.UUID]:
    """The first subject in this projection that is not a payment request.

    **Resolved from the database rather than from the payload**, for the reason
    `_request_for` gives below: an event carries what was true when it was written, and a
    notification names a row a person is about to open. The order number in particular is what the
    trader recognises, and reading it back is what keeps the message true if the row moved.

    The amounts stay from the payload. They describe the moment the order became payable and are
    the one thing that must *not* drift — a message saying "we received 50,000,000,000" has to keep
    saying it even after a correction, because that is what the trader was told.
    """

    raw = payload.get("gold_sale_order_id")
    if raw is None:
        raise NotificationProjectionError(
            "GoldOrderReadyForDispatch carried no gold_sale_order_id, so there is no order to "
            "tell anybody about"
        )

    order = session.get(GoldSaleOrder, uuid.UUID(str(raw)))
    if order is None:
        raise NotificationProjectionError(
            f"gold sale order {raw} does not exist, so the event and the database disagree"
        )

    confirmed = payload.get("confirmed_total_irr")
    title = f"Payment confirmed for order {order.order_number}"
    body = (
        f"The centre has confirmed {confirmed} IRR against order {order.order_number}. "
        "It is ready for dispatch."
    )
    return title, body, ENTITY_GOLD_SALE_ORDER, order.id, order.trader_id


def _request_for(session: Session, payload: dict[str, Any]) -> PaymentRequest:
    raw = payload.get("payment_request_id")
    if raw is None:
        raise NotificationProjectionError(
            "the event carries no `payment_request_id`, so there is no trader to address. Every "
            "event this projection reads is about one request; a payload without one is a "
            "producer and a consumer that disagree."
        )
    request = session.get(PaymentRequest, uuid.UUID(str(raw)))
    if request is None:
        raise NotificationProjectionError(
            f"payment request {raw} does not exist. The event was written inside the transaction "
            "that created the row, so this means the row was removed — worth a dead letter rather "
            "than a silently dropped message."
        )
    return request


def _primary_trader_user(session: Session, trader_id: uuid.UUID) -> uuid.UUID | None:
    """The business's contact of record.

    **One recipient per business, and that is a limitation worth naming.** A trader with three
    logins gets one notification, addressed to the primary user, because `traders.primary_phone`
    and `trader_users.is_primary` are how this system already decides who speaks for a business.
    Fanning out to every user would be a different product decision — and ADR-009, which owns the
    delivery channel, is where it belongs.
    """

    from app.db.models.identity import TraderUser

    return session.scalar(
        select(TraderUser.id).where(
            TraderUser.trader_id == trader_id, TraderUser.is_primary.is_(True)
        )
    )


def _message(
    notification_type: str, *, request: PaymentRequest, payload: dict[str, Any]
) -> tuple[str, str, str, uuid.UUID]:
    """What the trader reads, and what it points at.

    **No amount and no IBAN.** A notification is delivered outside the authenticated surface in
    every channel ADR-009 might eventually choose, and a message that carries a figure is a figure
    on somebody's lock screen. The request number is enough to open the right screen, which is
    what the entity reference is for.
    """

    number = request.request_number

    if notification_type == TYPE_RESULT_PUBLISHED:
        publication_id = payload.get("publication_id")
        return (
            f"Payment result available for {number}",
            f"The result for request {number} has been published. Sign in to view it.",
            ENTITY_PAYMENT_PUBLICATION,
            uuid.UUID(str(publication_id)) if publication_id else request.id,
        )

    if notification_type == TYPE_RESULT_CORRECTED:
        publication_id = payload.get("publication_id")
        return (
            f"Payment result corrected for {number}",
            f"The published result for request {number} has been corrected. The previous version "
            "is preserved and remains viewable.",
            ENTITY_PAYMENT_PUBLICATION,
            uuid.UUID(str(publication_id)) if publication_id else request.id,
        )

    # `TYPE_ATTEMPT_FAILED`, and the one G-5 exists for. The failure code is included because it
    # is the difference between "we are retrying" and "your account details need fixing", and the
    # trader can act on the second.
    code = payload.get("failure_code")
    detail = f" Reason recorded: {code}." if code else ""
    return (
        f"Payment attempt failed for {number}",
        f"An attempt to pay request {number} did not succeed.{detail} The centre is reviewing it; "
        "no action is needed from you yet.",
        ENTITY_PAYMENT_REQUEST,
        request.id,
    )
