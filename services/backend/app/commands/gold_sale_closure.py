"""The end of the chain: the trader confirms receipt, and the order closes.
`06_Workflows_and_State_Machines.md` §8.2, §12.3.

M10 slice 8. Two commands and no migration — every column either exists with a grant or is the
`gold_dispatches` lifecycle `20260911_0042` already opened.

**Document 06 §8.2 draws these three edges and this module is all of them:**

```text
dispatched          --> received_by_trader : receipt confirmed
received_by_trader  --> closed             : close
settled_or_offset   --> closed             : close
```

**The acknowledgement is the trader's and the closure is the centre's**, which is the whole reason
they are two commands rather than one. §12.3: "Trader acknowledgment is not required to prove that
dispatch occurred, but absence of acknowledgment keeps a follow-up task open." So a dispatch is
real without it — slice 7 already records the movement — and what an acknowledgement adds is the
trader agreeing that it arrived.

**Two states of §8.2 that no command reaches, recorded rather than quietly skipped.**
`incoming_payment_confirmed --> ready_for_dispatch: normal guard satisfied` and
`--> manager_approval_required: override/risk policy` are both in the machine. Slice 7 evaluates
the dispatch guard at dispatch time instead, so an order never sits in `ready_for_dispatch`, and
`manager_approval_required` needs a risk policy no document defines. Neither is invented here: the
plan records them as remaining M10 surface.

Covers: SVC-GOLDCORRECT-001, TRACE-M10-001.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import ACKNOWLEDGE_GOLD_DISPATCH, CLOSE_GOLD_SALE_ORDER
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.core.errors import (
    BusinessRuleViolationError,
    ConflictError,
    NotFoundError,
)
from app.db.models.gold_dispatch import (
    DISPATCH_DELIVERED,
    DISPATCH_DISPATCHED,
    DISPATCH_SETTLED,
    GoldDispatch,
)
from app.db.models.gold_sale import GoldSaleOrder
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.idempotency import IdempotencyResolver

METADATA_SCHEMA = "audit.gold_sale_closure"
METADATA_VERSION = 1

ACKNOWLEDGE_OPERATION = "gold_dispatch.acknowledge"
CLOSE_OPERATION = "gold_sale.close"

# `status_catalog.yaml`'s `gold_sale_order` aggregate, and document 06 §8.2's edges.
ORDER_DISPATCHED = "dispatched"
ORDER_RECEIVED = "received_by_trader"
ORDER_SETTLED = "settled_or_offset"
ORDER_CLOSED = "closed"

# The two states §8.2 draws an edge to `closed` from, and no others. An order still `dispatched`
# has metal in transit that nobody has confirmed arriving; closing it would record an ending
# nobody witnessed.
CLOSEABLE_FROM: tuple[str, ...] = (ORDER_RECEIVED, ORDER_SETTLED)


@dataclass(frozen=True, slots=True)
class AcknowledgeDispatch:
    """The trader's confirmation that the gold arrived.

    **No `status` and no amount.** What a trader can say is "it arrived"; the dispatch's own
    lifecycle and everything financial are the centre's.
    """

    gold_dispatch_id: uuid.UUID
    trader_id: uuid.UUID
    expected_record_version: int


@dataclass(frozen=True, slots=True)
class CloseGoldSaleOrder:
    gold_sale_order_id: uuid.UUID
    expected_record_version: int
    closure_note: str | None = None


@dataclass(frozen=True, slots=True)
class ClosureResult:
    order: GoldSaleOrder
    dispatch: GoldDispatch | None = None
    replayed: bool = False


def acknowledge_dispatch(
    command: AcknowledgeDispatch,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> ClosureResult:
    """§8.2's `dispatched --> received_by_trader`, and §12.3's fourth rule.

    Only a **physical** dispatch can be acknowledged. A settlement moved no metal, so there is
    nothing for a trader to confirm arriving — and `settled_or_offset` reaches `closed` directly in
    §8.2 for exactly that reason.
    """

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=ACKNOWLEDGE_OPERATION,
        idempotency_key=idempotency_key,
        payload={"gold_dispatch_id": str(command.gold_dispatch_id)},
    )

    session = uow.session
    if claim.is_replay:
        replayed_order, replayed_dispatch = _replayed(session, claim)
        return ClosureResult(
            order=replayed_order, dispatch=replayed_dispatch, replayed=True
        )

    dispatch = session.get(GoldDispatch, command.gold_dispatch_id)
    if dispatch is None:
        raise NotFoundError()

    order = session.get(GoldSaleOrder, dispatch.gold_sale_order_id, with_for_update=True)
    if order is None:  # pragma: no cover - the foreign key holds it
        raise NotFoundError()
    if order.trader_id != command.trader_id:
        # Somebody else's gold. 404 rather than 403, on `app/security/ownership.py`'s rule: an
        # authorisation error over a guessable id tells the caller the dispatch exists.
        raise NotFoundError()

    if dispatch.record_version != command.expected_record_version:
        raise ConflictError(
            f"dispatch {dispatch.id} is at version {dispatch.record_version} and If-Match named "
            f"{command.expected_record_version}"
        )
    if dispatch.status != DISPATCH_DISPATCHED:
        raise BusinessRuleViolationError(
            f"dispatch {dispatch.id} is {dispatch.status!r}; only a dispatch still in transit can "
            f"be acknowledged. A settlement moved no metal and reaches {ORDER_CLOSED!r} directly."
        )

    dispatch.status = DISPATCH_DELIVERED
    dispatch.confirmed_by_trader_user_id = actor.actor_id
    dispatch.confirmed_at = now
    dispatch.record_version += 1

    previous = {"order_status": order.status, "dispatch_status": DISPATCH_DISPATCHED}
    order.status = ORDER_RECEIVED
    order.record_version += 1
    uow.flush()

    _audit(
        session,
        policy,
        names=ACKNOWLEDGE_GOLD_DISPATCH,
        order=order,
        dispatch=dispatch,
        entity_type="gold_dispatch",
        entity_id=dispatch.id,
        entity_version=dispatch.record_version,
        previous=previous,
        note=None,
        actor=actor,
        context=context,
        now=now,
    )

    resolver.complete(
        claim,
        response_code=200,
        response_body={"order_id": str(order.id), "dispatch_id": str(dispatch.id)},
        resource_type="gold_dispatch",
        resource_id=dispatch.id,
        now=now,
    )
    return ClosureResult(order=order, dispatch=dispatch)


def close_order(
    command: CloseGoldSaleOrder,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> ClosureResult:
    """§8.2's two edges into `closed`, and §21.1's "closure guards".

    **An order still `dispatched` cannot close.** Metal is in transit that nobody has confirmed
    arriving, and closing would record an ending nobody witnessed — which is the difference between
    a closure guard and a status assignment.
    """

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=CLOSE_OPERATION,
        idempotency_key=idempotency_key,
        payload={"gold_sale_order_id": str(command.gold_sale_order_id)},
    )

    session = uow.session
    if claim.is_replay:
        replayed_order, _ = _replayed(session, claim)
        return ClosureResult(order=replayed_order, replayed=True)

    order = session.get(GoldSaleOrder, command.gold_sale_order_id, with_for_update=True)
    if order is None:
        raise NotFoundError()
    if order.record_version != command.expected_record_version:
        raise ConflictError(
            f"order {order.order_number} is at version {order.record_version} and If-Match named "
            f"{command.expected_record_version}"
        )
    if order.status not in CLOSEABLE_FROM:
        raise BusinessRuleViolationError(
            f"order {order.order_number} is {order.status!r}; document 06 §8.2 draws an edge to "
            f"{ORDER_CLOSED!r} from {' and '.join(CLOSEABLE_FROM)} only. An order still in transit "
            "has metal nobody has confirmed arriving."
        )

    _refuse_an_unacknowledged_movement(session, order)

    previous = {"order_status": order.status}
    order.status = ORDER_CLOSED
    order.closed_at = now
    order.record_version += 1
    uow.flush()

    _audit(
        session,
        policy,
        names=CLOSE_GOLD_SALE_ORDER,
        order=order,
        dispatch=None,
        entity_type="gold_sale_order",
        entity_id=order.id,
        entity_version=order.record_version,
        previous=previous,
        note=command.closure_note,
        actor=actor,
        context=context,
        now=now,
    )

    resolver.complete(
        claim,
        response_code=200,
        response_body={"order_id": str(order.id), "dispatch_id": None},
        resource_type="gold_sale_order",
        resource_id=order.id,
        now=now,
    )
    return ClosureResult(order=order)


def _refuse_an_unacknowledged_movement(session: Session, order: GoldSaleOrder) -> None:
    """A second guard behind the status check, and it is not redundant.

    The status says `received_by_trader`, which only `acknowledge_dispatch` writes — but an order
    may carry several dispatches, and a later physical one still in transit would leave the order's
    status describing the earlier movement. Closing then would record an ending for metal still
    moving.

    Settlements are exempt: `settled` is terminal for a row that moved nothing, and §8.2 sends
    `settled_or_offset` to `closed` without an acknowledgement at all.
    """

    in_transit = session.scalars(
        select(GoldDispatch)
        .where(GoldDispatch.gold_sale_order_id == order.id)
        .where(GoldDispatch.status == DISPATCH_DISPATCHED)
    ).first()
    if in_transit is not None:
        raise BusinessRuleViolationError(
            f"dispatch {in_transit.id} on this order is still {DISPATCH_DISPATCHED!r}. Closing an "
            "order with metal in transit records an ending nobody witnessed."
        )


def _replayed(
    session: Session, claim: Any
) -> tuple[GoldSaleOrder, GoldDispatch | None]:
    stored = claim.record.response_body or {}
    order = session.get(GoldSaleOrder, uuid.UUID(str(stored["order_id"])))
    if order is None:  # pragma: no cover - the record made it
        raise NotFoundError()
    raw = stored.get("dispatch_id")
    dispatch = session.get(GoldDispatch, uuid.UUID(str(raw))) if raw else None
    return order, dispatch


def _audit(
    session: Session,
    policy: RedactionPolicy,
    *,
    names: Any,
    order: GoldSaleOrder,
    dispatch: GoldDispatch | None,
    entity_type: str,
    entity_id: uuid.UUID,
    entity_version: int,
    previous: dict[str, Any],
    note: str | None,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> None:
    new_values: dict[str, Any] = {
        "order_status": order.status,
        "gold_sale_order_id": str(order.id),
        "order_number": order.order_number,
    }
    if dispatch is not None:
        new_values["dispatch_status"] = dispatch.status
        new_values["dispatch_type"] = dispatch.dispatch_type
    if order.status == ORDER_CLOSED:
        new_values["closed_at"] = order.closed_at.isoformat() if order.closed_at else None
        # Which of §8.2's two edges was taken. A closed order that cannot say whether metal moved
        # or the debt was offset is one an auditor has to reconstruct from other tables.
        new_values["closed_from"] = previous["order_status"]

    AuditWriter(session, policy).record(
        AuditEntry(
            action=names.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_record_version=entity_version,
            previous_values=previous,
            new_values=new_values,
            reason=note,
            occurred_at=now,
            metadata={"operation": names.audit_action},
        ),
        actor=actor,
        context=context,
    )


__all__ = [
    "DISPATCH_SETTLED",
    "AcknowledgeDispatch",
    "CloseGoldSaleOrder",
    "ClosureResult",
    "acknowledge_dispatch",
    "close_order",
]
