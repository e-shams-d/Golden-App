"""Gold sale orders: create, submit, price, read. `05_API_Specification.md` §21.1-21.2.

M10 slice 1. Four of §21.1's eight routes; request-payment, cancel and close belong to later
slices, and building them now would mean writing guards for states nothing can reach yet.

**Two audiences, and the split is M5's.** A trader creates and submits their own order through
ownership; the centre reads and prices through permissions. `04_Database_Schema.md:405` gives a
trader session no grants at all, so a route-level `requires(...)` denies the only audience the
trader routes have — measured in M9 slice 6, where the first version did exactly that and every
trader test failed with `Permission denied`. `payment_requests.py` established the closure guard
that carries the permission name for the gate to see while ownership does the work.

**Weight arrives as a string and stays one until it is a `Decimal`.** §21.1's example is
`"125.500000"`, and the reason is `app/core/hashing.py` refusing floats: a weight that reached
Python as a float would already have lost the exactness the hash depends on. Pydantic is given
`Decimal`, which parses the string without going through binary floating point.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor, requires
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.commands import gold_sale as gold_sale_commands
from app.core.errors import (
    BusinessRuleViolationError,
    ErrorEnvelope,
    ForbiddenError,
    NotFoundError,
    PreconditionRequiredError,
    VersionConflictError,
)
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.gold_sale import (
    WEIGHT_UNITS,
    GoldSaleOrder,
    GoldSalePricingVersion,
)
from app.security.actor import ActorContext
from app.security.ownership import require_owned, scoped
from app.security.permissions import declare

router = APIRouter(prefix="/gold-sale-orders", tags=["gold-sale-orders"])

# An order carries a trader's name and weight but no IBAN. The policy is passed explicitly anyway,
# for the reason `RedactionPolicy` takes it per call site: POL-003 is open and every dependent
# point should say so rather than inherit a default that reads as approved.
GOLD_SALE_REDACTION = RedactionPolicy(mask_iban=True)

RESPONSES: dict[int | str, dict[str, object]] = {
    400: {"model": ErrorEnvelope, "description": "The order is not in a state that permits this."},
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "The caller lacks the permission."},
    404: {
        "model": ErrorEnvelope,
        "description": "No such order, or it belongs to somebody else. The two are deliberately "
        "indistinguishable.",
    },
    409: {"model": ErrorEnvelope, "description": "This order already says exactly this."},
    412: {"model": ErrorEnvelope, "description": "If-Match is stale or unreadable."},
    428: {"model": ErrorEnvelope, "description": "If-Match and Idempotency-Key are required."},
    **VALIDATION_ERROR_RESPONSE,
}


class CreateOrderRequest(BaseModel):
    """§21.1's body, field for field.

    **No amount and no price.** What a trader orders is a weight; what it costs is the centre's,
    through a pricing version. A price field here would be a number a client could disagree with,
    which is the shape M9 refused three times.
    """

    model_config = ConfigDict(extra="forbid")

    gold_type: str = Field(min_length=1, max_length=64)
    # `Decimal`, never `float`. Pydantic parses the JSON string directly into one.
    gold_weight: Decimal = Field(gt=0)
    weight_unit: str = Field(min_length=1, max_length=16)
    gold_purity: str = Field(min_length=1, max_length=16)


class PricingVersionRequest(BaseModel):
    """§21.2's body.

    `entered_amount_value` and `_unit` are **provenance**, not the canonical value — document 04
    §4.4's rule and M5's `entered_amount` pair. The canonical amount is computed from the unit
    price and the weight and is not a field here.
    """

    model_config = ConfigDict(extra="forbid")

    unit_price_irr: int = Field(gt=0)
    pricing_note: str | None = Field(default=None, max_length=4000)
    entered_amount_value: int | None = Field(default=None, gt=0)
    entered_amount_unit: str | None = Field(default=None, max_length=8)


class PricingVersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    version_number: int
    pricing_method: str
    gold_weight: Decimal
    weight_unit: str
    gold_purity: str
    unit_price_irr: int
    expected_amount_irr: int
    content_hash: str
    created_at: datetime
    superseded_at: datetime | None


class OrderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    order_number: str
    trader_id: uuid.UUID
    status: str
    gold_type: str
    gold_weight: Decimal
    weight_unit: str
    gold_purity: str
    expected_amount_irr: int | None
    final_amount_irr: int | None
    current_pricing_version_id: uuid.UUID | None
    record_version: int
    created_at: datetime


def owned_or_permitted(trader_permission: str, internal_permission: str) -> Any:
    """M5's dual-audience guard, reused verbatim in shape.

    Both names are read inside the closure, and that is deliberate rather than tidy:
    `test_permission_guards.py` finds a route's permissions by walking this closure for approved
    codes, so a name it does not carry is a name the gate cannot see. `payment_requests.py` records
    the version that wrote `del declared_trader` and turned a closure variable into a local, so
    every call raised `UnboundLocalError`.
    """

    declared_trader = declare(trader_permission)
    declared_internal = declare(internal_permission)

    def guard(
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
    ) -> uuid.UUID | None:
        required = declared_trader if actor.is_trader else declared_internal
        if actor.is_trader:
            # A trader session holds no permission at all, so `required` names the intent the
            # catalogue records while ownership does the work.
            return actor.trader_id
        if required not in actor.permissions:
            raise ForbiddenError()
        return None

    return Depends(guard)


def _audit_actor(actor: ActorContext) -> AuditActor:
    return AuditActor(
        actor_type=actor.actor_type.value,
        actor_id=actor.actor_id,
        role_snapshot=tuple(sorted(actor.roles)),
        session_id=actor.session_id,
        authentication_assurance=actor.auth_level,
    )


def _parse_record_version(if_match: str | None) -> int:
    if if_match is None:
        raise PreconditionRequiredError("If-Match")
    cleaned = if_match.strip().strip('"')
    if not cleaned.startswith("rv-"):
        raise VersionConflictError()
    try:
        return int(cleaned.removeprefix("rv-"))
    except ValueError as exc:
        raise VersionConflictError() from exc


def _require_key(idempotency_key: str | None) -> str:
    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")
    return idempotency_key


def _rendered(order: GoldSaleOrder) -> OrderResponse:
    return OrderResponse(
        id=order.id,
        order_number=order.order_number,
        trader_id=order.trader_id,
        status=order.status,
        gold_type=order.gold_type,
        gold_weight=order.gold_weight,
        weight_unit=order.weight_unit,
        gold_purity=order.gold_purity,
        expected_amount_irr=order.expected_amount_irr,
        final_amount_irr=order.final_amount_irr,
        current_pricing_version_id=order.current_pricing_version_id,
        record_version=order.record_version,
        created_at=order.created_at,
    )


def _rendered_version(version: GoldSalePricingVersion) -> PricingVersionResponse:
    return PricingVersionResponse(
        id=version.id,
        version_number=version.version_number,
        pricing_method=version.pricing_method,
        gold_weight=version.gold_weight,
        weight_unit=version.weight_unit,
        gold_purity=version.gold_purity,
        unit_price_irr=version.unit_price_irr,
        expected_amount_irr=version.expected_amount_irr,
        content_hash=version.content_hash,
        created_at=version.created_at,
        superseded_at=version.superseded_at,
    )


def _refuse_an_unapproved_unit(payload: CreateOrderRequest) -> None:
    """`04_Database_Schema.md:180`: the unit must be explicit, `GRAM` or `MITHQAL`.

    Checked here as well as by the CHECK, for the reason slice 2 of M9 gives: the schema gives a
    client a constraint violation and this gives them the field and the permitted values. The
    document's "or an approved code" is deliberately unimplemented — a third unit is a governance
    addition, not a string somebody passes.
    """

    if payload.weight_unit not in WEIGHT_UNITS:
        # `BusinessRuleViolationError`, not a bare `ValueError`. The first version raised the
        # latter and FastAPI turned it into a 500 — a refusal the caller could not act on, and an
        # alert for an operator with nothing wrong on their side.
        raise BusinessRuleViolationError(
            f"{payload.weight_unit!r} is not an approved weight unit. "
            f"`04_Database_Schema.md:180` names {' and '.join(WEIGHT_UNITS)}; a third unit is a "
            "governance addition rather than a value a caller may pass."
        )


@router.post(
    "",
    response_model=OrderResponse,
    status_code=201,
    operation_id="createGoldSaleOrder",
    summary="Place a gold sale order.",
    responses=RESPONSES,
    dependencies=[owned_or_permitted("gold_sale.create_own", "gold_sale.review")],
)
def create_gold_sale_order(
    payload: CreateOrderRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> OrderResponse:
    """`POST /api/v1/gold-sale-orders`, per `:1951`.

    **No `If-Match`.** There is no prior version of a thing that does not exist yet; the
    `Idempotency-Key` is what makes a retried creation return the first order rather than a second.
    """

    _refuse_an_unapproved_unit(payload)
    key = _require_key(idempotency_key)
    now = utc_now()

    trader_id = actor.trader_id if actor.is_trader else None
    if trader_id is None:
        # An internal caller creating on a trader's behalf needs to name which trader, and §21.1's
        # body has no field for it. Refused rather than guessed — the route exists for the trader
        # today, and an admin-created order is a later decision with a body change behind it.
        raise ForbiddenError()

    with runtime.uow_factory() as uow:
        result = gold_sale_commands.create_order(
            gold_sale_commands.CreateGoldSaleOrder(
                trader_id=trader_id,
                gold_type=payload.gold_type,
                gold_weight=payload.gold_weight,
                weight_unit=payload.weight_unit,
                gold_purity=payload.gold_purity,
                created_by_actor_type=actor.actor_type.value,
                created_by_actor_id=actor.actor_id,
            ),
            uow=uow,
            policy=GOLD_SALE_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=key,
            now=now,
        )
        response = _rendered(result.order)
        uow.commit()

    return response


@router.get(
    "",
    response_model=list[OrderResponse],
    operation_id="listGoldSaleOrders",
    summary="Orders the caller may see.",
    responses=RESPONSES,
    dependencies=[owned_or_permitted("gold_sale.read", "gold_sale.read")],
)
def list_gold_sale_orders(
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> list[OrderResponse]:
    """`GET /api/v1/gold-sale-orders`, per `:1950` — "scoped list".

    A trader sees their own through `scoped()`, which takes the actor rather than an id so the
    predicate cannot be written any other way. An internal caller sees every order.
    """

    with runtime.uow_factory() as uow:
        query = select(GoldSaleOrder).order_by(GoldSaleOrder.created_at.desc())
        if actor.is_trader:
            query = scoped(query, GoldSaleOrder.trader_id, actor)
        rows = list(uow.session.scalars(query))
        response = [_rendered(row) for row in rows]
        uow.rollback()

    return response


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    operation_id="getGoldSaleOrder",
    summary="One order.",
    responses=RESPONSES,
    dependencies=[owned_or_permitted("gold_sale.read", "gold_sale.read")],
)
def get_gold_sale_order(
    order_id: uuid.UUID,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> OrderResponse:
    """`GET /api/v1/gold-sale-orders/{id}`, per `:1952`.

    A second trader gets 404 rather than 403: an authorisation error over a guessable identifier
    tells them the order exists, which `app/security/ownership.py` refuses to do.
    """

    with runtime.uow_factory() as uow:
        order = uow.session.get(GoldSaleOrder, order_id)
        if actor.is_trader:
            require_owned(order, order.trader_id if order else None, actor)
        elif order is None:
            uow.rollback()
            raise NotFoundError()
        assert order is not None
        response = _rendered(order)
        uow.rollback()

    return response


@router.post(
    "/{order_id}/submit",
    response_model=OrderResponse,
    operation_id="submitGoldSaleOrder",
    summary="Hand the order to the centre.",
    responses=RESPONSES,
    dependencies=[owned_or_permitted("gold_sale.create_own", "gold_sale.review")],
)
def submit_gold_sale_order(
    order_id: uuid.UUID,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> OrderResponse:
    """`POST /api/v1/gold-sale-orders/{id}/submit`, per `:1953` — "trader/admin submit"."""

    expected = _parse_record_version(if_match)
    key = _require_key(idempotency_key)
    now = utc_now()

    with runtime.uow_factory() as uow:
        order = uow.session.get(GoldSaleOrder, order_id)
        if actor.is_trader:
            require_owned(order, order.trader_id if order else None, actor)
        elif order is None:
            uow.rollback()
            raise NotFoundError()

        result = gold_sale_commands.submit_order(
            gold_sale_commands.SubmitGoldSaleOrder(
                gold_sale_order_id=order_id, expected_record_version=expected
            ),
            uow=uow,
            policy=GOLD_SALE_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=key,
            now=now,
        )
        response = _rendered(result.order)
        uow.commit()

    return response


@router.post(
    "/{order_id}/pricing-versions",
    response_model=PricingVersionResponse,
    status_code=201,
    operation_id="createGoldSalePricingVersion",
    summary="Price the order, as a new immutable snapshot.",
    responses=RESPONSES,
    dependencies=[requires(declare("gold_sale.price"))],
)
def create_pricing_version(
    order_id: uuid.UUID,
    payload: PricingVersionRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> PricingVersionResponse:
    """`POST /api/v1/gold-sale-orders/{order_id}/pricing-versions`, per `:1971`.

    **Internal only**, and `requires(...)` rather than the dual guard above: `20260801_0008:228`
    gives `gold_sale.price` to the accountant alone, and a trader pricing their own order is the
    thing the separation exists to prevent.

    §21.2: "Stores exact amount provenance and does not overwrite earlier pricing versions." Both
    halves are the command's — `entered_amount_*` is the provenance and the predecessor is marked
    superseded rather than edited.
    """

    expected = _parse_record_version(if_match)
    key = _require_key(idempotency_key)
    now = utc_now()

    if actor.actor_id is None:
        raise ForbiddenError()

    with runtime.uow_factory() as uow:
        result = gold_sale_commands.create_pricing_version(
            gold_sale_commands.CreatePricingVersion(
                gold_sale_order_id=order_id,
                expected_record_version=expected,
                unit_price_irr=payload.unit_price_irr,
                created_by_admin_user_id=actor.actor_id,
                pricing_note=payload.pricing_note,
                entered_amount_value=payload.entered_amount_value,
                entered_amount_unit=payload.entered_amount_unit,
            ),
            uow=uow,
            policy=GOLD_SALE_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=key,
            now=now,
        )
        assert result.pricing_version is not None
        response = _rendered_version(result.pricing_version)
        uow.commit()

    return response


__all__ = ["router"]
