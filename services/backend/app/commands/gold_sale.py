"""Placing a gold order, submitting it, and pricing it. §21.1-21.2.

M10 slice 1. `05_API_Specification.md:1948` (the eight endpoints), `:1971` (pricing),
`04_Database_Schema.md:686` and `:720` (both tables).

**Pricing creates a version; it never edits one.** §10.2 at `:731`: "Updating price creates a new
row and updates `gold_sale_orders.current_pricing_version_id` transactionally." So the command
inserts, repoints and marks the predecessor superseded in one transaction, and the migration grants
`superseded_at` alone on that table — a version is otherwise unwritable, which is what makes
"immutable pricing/amount snapshot" a property of the database rather than of this file.

**Re-pricing at identical figures is refused by the database.**
`UNIQUE(gold_sale_order_id, content_hash)`, which is M5's rule for revisions and the same argument:
an accountant who re-prices without changing anything has not re-priced, and a second identical row
would reach a reviewer looking like new work.

**The order number's prefix is this implementation's, and that is recorded rather than
attributed.** `05_API_Specification.md:304` enumerates `PR-`, `PB-` and `EXP-`, and
`07_UI_UX_Specification.md:632` shows the family with `PBV-` and `BRB-` besides — **none of them
is a gold sale**. M5 met this exact gap and got it wrong: it shipped `GP-` citing a line that says
only "Human-readable unique", which is the failure this docstring exists to avoid repeating. So
the *format* comes from the documented family — a prefix, a Gregorian day, a six-digit sequence —
and the *letters* `GS-` are mine. M0 owes the prefix.

The date is Gregorian for ADR-006's reason, which M5's `_next_request_number` states in full: a
Jalali date here would leak a presentation calendar into a stored and transported value, and the
ADR forbids exactly that.

**Three audit actions, none of them catalogued.** `audit_outbox_catalog.yaml` names
`gold_sale.dispatched` and nothing for creating, submitting or pricing an order — the plan's G-3,
which predicted this would be M10's largest block of declarations. Each is declared against
`gold_sale.create_own`, `gold_sale.review` or `gold_sale.price`, the approved permissions the
routes already use.

Covers: DB-GOLDSALE-001, SVC-PRICING-001, SVC-PRICING-002.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import CREATE_GOLD_SALE_ORDER, PRICE_GOLD_SALE_ORDER, SUBMIT_GOLD_SALE_ORDER
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.core.errors import BusinessRuleViolationError, ConflictError, NotFoundError
from app.core.hashing import unversioned_digest
from app.core.time import to_business_time
from app.db.concurrency import compare_and_swap
from app.db.models.gold_sale import (
    ORDER_DRAFT,
    ORDER_PRICED,
    ORDER_SUBMITTED,
    GoldSaleOrder,
    GoldSalePricingVersion,
)
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.idempotency import IdempotencyResolver

METADATA_SCHEMA = "audit.gold_sale"
METADATA_VERSION = 1

CREATE_OPERATION = "gold_sale.create_own"
SUBMIT_OPERATION = "gold_sale.submit"
PRICE_OPERATION = "gold_sale.price"

# `05_API_Specification.md:304`'s family shape, with letters this implementation chose. See the
# module docstring: no document gives a gold-sale prefix, and inventing one silently is what M5 did.
ORDER_NUMBER_PREFIX = "GS"

# `06_Workflows_and_State_Machines.md` puts submission between the two. A draft is the trader's;
# once submitted the centre owns it, which is why pricing may not reach back past this point.
SUBMITTABLE_FROM: tuple[str, ...] = (ORDER_DRAFT,)

# An order may be priced once the centre has it, and re-priced afterwards — §10.2's whole point is
# that a second version is normal. A `draft` cannot be priced: nobody has asked the centre for it.
PRICEABLE_FROM: tuple[str, ...] = (ORDER_SUBMITTED, "under_center_review", ORDER_PRICED)


@dataclass(frozen=True, slots=True)
class CreateGoldSaleOrder:
    """§21.1's body. **No amount and no price** — those are the centre's, through a version."""

    trader_id: uuid.UUID
    gold_type: str
    gold_weight: Decimal
    weight_unit: str
    gold_purity: str
    created_by_actor_type: str
    created_by_actor_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class SubmitGoldSaleOrder:
    gold_sale_order_id: uuid.UUID
    expected_record_version: int


@dataclass(frozen=True, slots=True)
class CreatePricingVersion:
    """§21.2's body.

    **No `expected_amount_irr` field.** The amount is `unit_price_irr` multiplied by the weight,
    computed here, so there is no figure a client could submit that disagrees with the arithmetic
    — the same enforcement-by-absence M9 used three times. `entered_amount_*` is provenance, not
    the canonical value, which is `MONEY_TIME_CONTRACT.md`'s rule and M5's `entered_amount` pair.
    """

    gold_sale_order_id: uuid.UUID
    expected_record_version: int
    unit_price_irr: int
    created_by_admin_user_id: uuid.UUID
    pricing_note: str | None = None
    entered_amount_value: int | None = None
    entered_amount_unit: str | None = None


@dataclass(frozen=True, slots=True)
class OrderResult:
    order: GoldSaleOrder
    pricing_version: GoldSalePricingVersion | None = None
    replayed: bool = False


def create_order(
    command: CreateGoldSaleOrder,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> OrderResult:
    """§21.1. A draft order, with a weight and no price."""

    if command.gold_weight <= 0:
        raise BusinessRuleViolationError(
            "a gold sale order needs a positive weight; §4.5's CHECK refuses anything else and "
            "this refusal names the field rather than showing a constraint"
        )

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=CREATE_OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "trader_id": str(command.trader_id),
            "gold_weight": str(command.gold_weight),
        },
    )

    session = uow.session
    if claim.is_replay:
        return OrderResult(order=_replayed(session, claim), replayed=True)

    order = GoldSaleOrder(
        trader_id=command.trader_id,
        order_number=_next_order_number(session, now),
        status=ORDER_DRAFT,
        gold_type=command.gold_type,
        gold_weight=command.gold_weight,
        weight_unit=command.weight_unit,
        gold_purity=command.gold_purity,
        created_by_actor_type=command.created_by_actor_type,
        created_by_actor_id=command.created_by_actor_id,
        record_version=1,
    )
    session.add(order)
    _flush_or_conflict(uow)

    _audit(
        session,
        policy,
        names=CREATE_GOLD_SALE_ORDER,
        order=order,
        previous_status=None,
        actor=actor,
        context=context,
        now=now,
        extra={"gold_weight": str(order.gold_weight), "weight_unit": order.weight_unit},
    )

    resolver.complete(
        claim,
        response_code=201,
        response_body={"order_id": str(order.id)},
        resource_type="gold_sale_order",
        resource_id=order.id,
        now=now,
    )
    return OrderResult(order=order)


def submit_order(
    command: SubmitGoldSaleOrder,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> OrderResult:
    """§21.1's submit. The trader hands the order to the centre."""

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=SUBMIT_OPERATION,
        idempotency_key=idempotency_key,
        payload={"gold_sale_order_id": str(command.gold_sale_order_id)},
    )

    session = uow.session
    if claim.is_replay:
        return OrderResult(order=_replayed(session, claim), replayed=True)

    order = _order(session, command.gold_sale_order_id)
    if order.status not in SUBMITTABLE_FROM:
        raise BusinessRuleViolationError(
            f"order {order.order_number} is {order.status}; only "
            f"{', '.join(SUBMITTABLE_FROM)} may be submitted. Once the centre has an order, "
            "changing it is a correction rather than a submission."
        )

    compare_and_swap(
        session,
        GoldSaleOrder,
        entity_id=order.id,
        expected_version=command.expected_record_version,
        values={"status": ORDER_SUBMITTED},
    )
    uow.flush()
    session.refresh(order)

    _audit(
        session,
        policy,
        names=SUBMIT_GOLD_SALE_ORDER,
        order=order,
        previous_status=ORDER_DRAFT,
        actor=actor,
        context=context,
        now=now,
        extra={},
    )

    resolver.complete(
        claim,
        response_code=200,
        response_body={"order_id": str(order.id)},
        resource_type="gold_sale_order",
        resource_id=order.id,
        now=now,
    )
    return OrderResult(order=order)


def create_pricing_version(
    command: CreatePricingVersion,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> OrderResult:
    """§21.2. A new immutable snapshot, and the order repointed at it in the same transaction."""

    if command.unit_price_irr <= 0:
        raise BusinessRuleViolationError(
            "a unit price must be positive; §10.2's CHECK refuses anything else"
        )

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=PRICE_OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "gold_sale_order_id": str(command.gold_sale_order_id),
            "unit_price_irr": str(command.unit_price_irr),
        },
    )

    session = uow.session
    if claim.is_replay:
        order = _replayed(session, claim)
        return OrderResult(order=order, pricing_version=_current(session, order), replayed=True)

    order = _order(session, command.gold_sale_order_id)
    if order.status not in PRICEABLE_FROM:
        raise BusinessRuleViolationError(
            f"order {order.order_number} is {order.status}; only "
            f"{', '.join(PRICEABLE_FROM)} may be priced. A draft has not been handed to the "
            "centre, and an order past pricing has money or gold moving against it."
        )

    expected_amount = _amount_for(order.gold_weight, command.unit_price_irr)
    payload = _snapshot(order, command, expected_amount)

    previous = _current(session, order)
    version = GoldSalePricingVersion(
        gold_sale_order_id=order.id,
        version_number=_next_version_number(session, order.id),
        pricing_method="manual",
        gold_weight=order.gold_weight,
        weight_unit=order.weight_unit,
        gold_purity=order.gold_purity,
        unit_price_irr=command.unit_price_irr,
        expected_amount_irr=expected_amount,
        entered_amount_value=command.entered_amount_value,
        entered_amount_unit=command.entered_amount_unit,
        pricing_note=command.pricing_note,
        content_hash=unversioned_digest(payload),
        created_by_admin_user_id=command.created_by_admin_user_id,
    )
    session.add(version)
    _flush_or_conflict(uow, order_number=order.order_number)

    if previous is not None:
        previous.superseded_at = now

    # §10.2 at `:731`: the pointer moves in the same transaction that created the row. Through
    # `compare_and_swap` so the caller's `If-Match` is honoured — an accountant pricing an order
    # somebody else has just moved should be told, not silently win.
    compare_and_swap(
        session,
        GoldSaleOrder,
        entity_id=order.id,
        expected_version=command.expected_record_version,
        values={
            "status": ORDER_PRICED,
            "current_pricing_version_id": version.id,
            "expected_amount_irr": expected_amount,
        },
    )
    uow.flush()
    session.refresh(order)

    _audit(
        session,
        policy,
        names=PRICE_GOLD_SALE_ORDER,
        order=order,
        previous_status=None,
        actor=actor,
        context=context,
        now=now,
        extra={
            "pricing_version_id": str(version.id),
            "version_number": version.version_number,
            "expected_amount_irr": str(expected_amount),
            "content_hash": version.content_hash,
        },
    )

    resolver.complete(
        claim,
        response_code=201,
        response_body={"order_id": str(order.id)},
        resource_type="gold_sale_order",
        resource_id=order.id,
        now=now,
    )
    return OrderResult(order=order, pricing_version=version)


def _amount_for(weight: Decimal, unit_price_irr: int) -> int:
    """Weight times unit price, in whole rials.

    **`Decimal` throughout and `int` at the end.** `MONEY_TIME_CONTRACT.md` stores rials as whole
    numbers, so the product is quantised once, here, rather than left as a decimal that every
    later reader rounds differently. A float would make the same multiplication give two answers
    on two machines — which is why `app/core/hashing.py` refuses one and why this returns `int`.

    Rounded **down**: charging a trader a rial they were not quoted is worse than absorbing one,
    and `Decimal.__int__` truncates toward zero, which for a positive product is the floor.
    """

    if unit_price_irr <= 0:
        raise BusinessRuleViolationError("a unit price must be positive")
    amount = int(weight * Decimal(unit_price_irr))
    if amount <= 0:
        raise BusinessRuleViolationError(
            "the priced amount rounds to zero rials, which §10.2's CHECK refuses. A weight and "
            "unit price this small mean one of the two is wrong."
        )
    return amount


def _snapshot(
    order: GoldSaleOrder, command: CreatePricingVersion, expected_amount: int
) -> dict[str, Any]:
    """What the content hash covers. Every number a string, for the reason M9 slice 5 records.

    The weight is `str(Decimal)` rather than a float: `app/core/hashing.py` refuses floats, and
    two masses a human calls equal would otherwise hash differently. Document 05 §21.1 spells the
    weight as a string in its own example, which is the same decision reached independently.
    """

    return {
        "gold_sale_order_id": str(order.id),
        "gold_weight": str(order.gold_weight),
        "weight_unit": order.weight_unit,
        "gold_purity": order.gold_purity,
        "unit_price_irr": str(command.unit_price_irr),
        "expected_amount_irr": str(expected_amount),
        "pricing_method": "manual",
    }


def _order(session: Session, order_id: uuid.UUID) -> GoldSaleOrder:
    order = session.get(GoldSaleOrder, order_id)
    if order is None:
        raise NotFoundError()
    return order


def _current(session: Session, order: GoldSaleOrder) -> GoldSalePricingVersion | None:
    if order.current_pricing_version_id is None:
        return None
    return session.get(GoldSalePricingVersion, order.current_pricing_version_id)


def _next_version_number(session: Session, order_id: uuid.UUID) -> int:
    """Monotonic per order, confirmed by `uq_pricing_version_per_order`.

    The count is what usually gets it right and the unique is what makes it always right — M9
    slice 5's division, and the same one M5 uses for revisions.
    """

    highest = session.scalar(
        select(func.max(GoldSalePricingVersion.version_number)).where(
            GoldSalePricingVersion.gold_sale_order_id == order_id
        )
    )
    return int(highest or 0) + 1


def _next_order_number(session: Session, now: datetime) -> str:
    """`GS-YYYYMMDD-NNNNNN`. The format is documented; the two letters are not.

    See the module docstring: `05_API_Specification.md:304` and `07_UI_UX_Specification.md:632`
    give the family and none of their five prefixes is a gold sale. The date is Gregorian because
    ADR-006 forbids a Jalali one in a stored and transported value.

    Counted inside the transaction, so two concurrent creations can compute the same number and
    `UNIQUE(order_number)` refuses the second. The database owns uniqueness and the caller retries;
    a `SELECT max()+1` pretending to be safe is the version that silently collides.
    """

    prefix = f"{ORDER_NUMBER_PREFIX}-{to_business_time(now).strftime('%Y%m%d')}-"
    used = session.scalar(
        select(func.count())
        .select_from(GoldSaleOrder)
        .where(GoldSaleOrder.order_number.startswith(prefix))
    )
    return f"{prefix}{(used or 0) + 1:06d}"


def _flush_or_conflict(uow: SqlAlchemyUnitOfWork, order_number: str | None = None) -> None:
    """Turn a unique violation into a sentence the caller can act on.

    Two constraints reach here and they mean different things, so the message names both rather
    than guessing: `UNIQUE(order_number)` is a concurrent creation that should be retried, and
    `UNIQUE(gold_sale_order_id, content_hash)` is a re-price that changed nothing.
    """

    try:
        uow.flush()
    except IntegrityError as exc:  # pragma: no cover - exercised by the live conflict tests
        if order_number is not None:
            raise ConflictError(
                f"order {order_number} already has a pricing version with exactly these figures. "
                "`04_Database_Schema.md:728` refuses a second identical snapshot — re-pricing at "
                "the same weight, purity and unit price has not re-priced anything."
            ) from exc
        raise ConflictError(
            "another order took this number first; retry. The number is counted inside the "
            "transaction and `UNIQUE(order_number)` is what settles a race."
        ) from exc


def _replayed(session: Session, claim: Any) -> GoldSaleOrder:
    stored = claim.record.response_body or {}
    order = session.get(GoldSaleOrder, uuid.UUID(str(stored["order_id"])))
    if order is None:  # pragma: no cover - the record made it
        raise NotFoundError()
    return order


def _audit(
    session: Session,
    policy: RedactionPolicy,
    *,
    names: Any,
    order: GoldSaleOrder,
    previous_status: str | None,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
    extra: dict[str, Any],
) -> None:
    new_values: dict[str, Any] = {
        "status": order.status,
        "order_number": order.order_number,
        "trader_id": str(order.trader_id),
    }
    new_values.update(extra)

    AuditWriter(session, policy).record(
        AuditEntry(
            action=names.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="gold_sale_order",
            entity_id=order.id,
            entity_record_version=order.record_version,
            previous_values={"status": previous_status} if previous_status else {},
            new_values=new_values,
            reason=None,
            occurred_at=now,
            metadata={"operation": names.audit_action},
        ),
        actor=actor,
        context=context,
    )
