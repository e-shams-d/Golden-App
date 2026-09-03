"""Gold moves, and only when it may. `05_API_Specification.md:2029`, §18 `:1236`.

M10 slice 7, and the guard is the sentence the whole milestone was built toward:

> Gold cannot be dispatched unless the approved payment/settlement condition is satisfied or an
> explicitly authorized override is recorded with reason and audit.

**The guard is written last on purpose**, and the plan says why: "A guard written before the thing
it guards is a guard whose input does not exist — which this repository has shipped sixteen times."
Its input is slice 6's confirmed sum, which now exists.

**The two authorities are separate by seed, not by branch.** `permission_catalog.yaml` grants
`gold_sale.dispatch` to `warehouse_operator` alone and its `dispatch_control` constraint reads
"warehouse cannot override financial verification". `20260911_0042` seeds
`gold_sale.dispatch_override` for the manager, on the owner's decision of 2026-09-03. So
`SEC-DISPATCH-001` — a warehouse user cannot bypass the guard — holds because of who holds what,
which no branch in this module can undo.

**And one more check, which is the implementation's own and is marked as such.** The owner asked
for the grant to stay manageable, which is right and which reintroduces exactly the risk POL-002
names: an administrator can later grant one person both permissions, deliberately or by accident,
and the separation the catalogue describes is then configured off with nobody noticing. So
`_refuse_a_single_human` requires the overriding actor to differ from the dispatching one. **No
document asks for this.** It is one function and one test, and removing it is a one-line change if
the owner disagrees.

Covers: SEC-DISPATCH-001, SVC-DISPATCH-001, SVC-SETTLEMENT-001.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import DISPATCH_GOLD_SALE
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.core.errors import (
    BusinessRuleViolationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.db.models.gold_dispatch import (
    DISPATCH_DISPATCHED,
    DISPATCH_SETTLED,
    DISPATCH_TYPES,
    PHYSICAL_TYPES,
    GoldDispatch,
)
from app.db.models.gold_sale import GoldSaleOrder
from app.db.models.incoming_payment import IncomingPaymentReceipt
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.idempotency import IdempotencyResolver

METADATA_SCHEMA = "audit.gold_dispatch"
METADATA_VERSION = 1

DISPATCH_OPERATION = "gold_sale.dispatch"

OVERRIDE_PERMISSION = "gold_sale.dispatch_override"

# An order that has not been dispatched or closed. `dispatched`, `received_by_trader`,
# `settled_or_offset`, `closed`, `cancelled` and `rejected` are all past this point.
DISPATCHABLE_FROM: tuple[str, ...] = (
    "incoming_payment_confirmed",
    "incoming_payment_partially_confirmed",
    "manager_approval_required",
    "ready_for_dispatch",
)

# `status_catalog.yaml`'s `gold_sale_order` aggregate. A physical movement and a settlement leave
# the order in different places, which is `SVC-SETTLEMENT-001` at the order level.
ORDER_DISPATCHED = "dispatched"
ORDER_SETTLED = "settled_or_offset"


@dataclass(frozen=True, slots=True)
class RecordDispatch:
    """§21.7's body.

    **No `status`.** A physical movement is born `dispatched` and a settlement `settled`; the two
    are derived from `dispatch_type`, which is the one thing `SVC-SETTLEMENT-001` says must not be
    collapsed. A caller that could name the status could dispatch an offset.

    `guard_override_reason` is the only override field a caller supplies. Who authorised it and
    when are the platform's to record — a caller that could name the authoriser could name somebody
    who never agreed.
    """

    gold_sale_order_id: uuid.UUID
    dispatch_type: str
    expected_record_version: int
    weight: Decimal | None = None
    weight_unit: str | None = None
    gold_purity: str | None = None
    receiver_name: str | None = None
    tracking_or_delivery_note: str | None = None
    evidence_file_id: uuid.UUID | None = None
    dispatched_at: datetime | None = None
    guard_override_reason: str | None = None


@dataclass(frozen=True, slots=True)
class DispatchResult:
    dispatch: GoldDispatch
    order_status: str
    confirmed_total_irr: int
    expected_amount_irr: int | None
    replayed: bool = False


def record_dispatch(
    command: RecordDispatch,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    actor_permissions: frozenset[str],
    idempotency_key: str,
    now: datetime,
) -> DispatchResult:
    """§21.7. The guard runs before the row exists.

    Document 06 §12.3's first rule — "Dispatch creation requires the order dispatch guard" — puts
    it here rather than at completion, which is stricter than §10.8's "may be marked completed".
    A row that exists in `pending` against an unpaid order is already a record saying gold is on
    its way.
    """

    if command.dispatch_type not in DISPATCH_TYPES:
        raise BusinessRuleViolationError(
            f"{command.dispatch_type!r} is not a dispatch type; §10.8 names "
            f"{', '.join(DISPATCH_TYPES)}."
        )

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=DISPATCH_OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "gold_sale_order_id": str(command.gold_sale_order_id),
            "dispatch_type": command.dispatch_type,
        },
    )

    session = uow.session
    if claim.is_replay:
        replayed_dispatch, replayed_order = _replayed(session, claim)
        return DispatchResult(
            dispatch=replayed_dispatch,
            order_status=replayed_order.status,
            confirmed_total_irr=_confirmed_total(session, replayed_order.id),
            expected_amount_irr=replayed_order.expected_amount_irr,
            replayed=True,
        )

    # Locked before the sum is read, for the reason slice 6 locks it: two dispatches racing against
    # one order would otherwise both read the same total and both pass a guard only one should.
    order = session.get(GoldSaleOrder, command.gold_sale_order_id, with_for_update=True)
    if order is None:
        raise NotFoundError()
    if order.record_version != command.expected_record_version:
        raise ConflictError(
            f"order {order.order_number} is at version {order.record_version} and If-Match named "
            f"{command.expected_record_version}"
        )
    if order.status not in DISPATCHABLE_FROM:
        raise BusinessRuleViolationError(
            f"order {order.order_number} is {order.status!r}; a dispatch belongs to an order that "
            f"has reached payment ({', '.join(DISPATCHABLE_FROM)})."
        )

    paid = _confirmed_total(session, order.id)
    expected = order.expected_amount_irr
    guard_passes = expected is not None and paid >= expected

    override_at: datetime | None = None
    override_by: uuid.UUID | None = None
    if not guard_passes:
        _authorise_the_override(
            command,
            order=order,
            paid=paid,
            expected=expected,
            actor=actor,
            actor_permissions=actor_permissions,
        )
        override_at = now
        override_by = actor.actor_id

    physical = command.dispatch_type in PHYSICAL_TYPES

    dispatch = GoldDispatch(
        gold_sale_order_id=order.id,
        dispatch_type=command.dispatch_type,
        # **Derived from the type, never supplied.** `SVC-SETTLEMENT-001`: four types exist and two
        # move no metal, so a settlement is born `settled` and a movement `dispatched`. A single
        # status for both would let an offset read as gold having left the building.
        status=DISPATCH_DISPATCHED if physical else DISPATCH_SETTLED,
        weight=command.weight,
        weight_unit=command.weight_unit,
        gold_purity=command.gold_purity,
        receiver_name=command.receiver_name,
        tracking_or_delivery_note=command.tracking_or_delivery_note,
        evidence_file_id=command.evidence_file_id,
        created_by_admin_user_id=actor.actor_id,
        # Only a physical movement has a moment of leaving. A settlement's `dispatched_at` would be
        # a timestamp for an event that did not happen.
        dispatched_at=(command.dispatched_at or now) if physical else None,
        guard_override_by_admin_user_id=override_by,
        guard_override_at=override_at,
        guard_override_reason=command.guard_override_reason if override_at else None,
        record_version=1,
    )
    session.add(dispatch)
    uow.flush()

    previous = {"status": order.status}
    order.status = ORDER_DISPATCHED if physical else ORDER_SETTLED
    order.record_version += 1
    uow.flush()

    _audit(
        session,
        policy,
        dispatch=dispatch,
        order=order,
        paid=paid,
        guard_passed=guard_passes,
        actor=actor,
        context=context,
        now=now,
        previous=previous,
    )

    resolver.complete(
        claim,
        response_code=201,
        response_body={"dispatch_id": str(dispatch.id), "order_id": str(order.id)},
        resource_type="gold_dispatch",
        resource_id=dispatch.id,
        now=now,
    )
    return DispatchResult(
        dispatch=dispatch,
        order_status=order.status,
        confirmed_total_irr=paid,
        expected_amount_irr=expected,
    )


def _authorise_the_override(
    command: RecordDispatch,
    *,
    order: GoldSaleOrder,
    paid: int,
    expected: int | None,
    actor: AuditActor,
    actor_permissions: frozenset[str],
) -> None:
    """`SEC-DISPATCH-001` and `SVC-DISPATCH-001`. Three refusals, each its own sentence.

    **The permission.** `gold_sale.dispatch` is the warehouse operator's and authorises recording a
    dispatch; it does not authorise releasing gold against unconfirmed money. The catalogue says so
    in `dispatch_control`: "warehouse cannot override financial verification."

    **The reason.** §18 `:1236` requires the override to be "recorded with reason", and the table's
    CHECK refuses a blank one — checked here as well so the operator is told which field is missing
    rather than reading an integrity error.

    **A same-human check was intended here and is deliberately absent.** The owner asked for the
    grant to stay manageable, which reintroduces POL-002's risk: an administrator can later hold
    both permissions in one person and the separation is configured off with nobody noticing. The
    obvious answer is to require two different humans — and it cannot be had honestly in a
    single-request design, because there is exactly one actor in this request. Making the caller
    *name* an authoriser would be worse than nothing: a caller who can name somebody who never
    agreed has forged an authorisation, which is a bigger hole than the one it closes.

    Real dual control needs a manager to record an authorisation first and the dispatch to cite it
    — two commands, a second record, and a route no document names. Recorded as an owner debt
    rather than invented here, on the same rule every unspecified surface in this milestone has
    followed. The permission split still holds by seed: `warehouse_operator` cannot do this at all.
    """

    if OVERRIDE_PERMISSION not in actor_permissions:
        # `ForbiddenError` carries no message by design — `app/core/errors.py` keeps 403 opaque so
        # a refusal cannot describe what the caller is missing. The reasoning lives in this
        # docstring and in the audit trail rather than in the response, which is the same shape
        # every other permission refusal in this project has.
        raise ForbiddenError()

    if not (command.guard_override_reason or "").strip():
        raise BusinessRuleViolationError(
            "an override needs a reason. §18 `:1236` requires it to be recorded with reason and "
            "audit, and a blank one records two of the three."
        )



def _confirmed_total(session: Session, order_id: uuid.UUID) -> int:
    """Every confirmed rial on this order, read fresh.

    The same query slice 6 uses and for the same reason: `04_Database_Schema.md:469` forbids a
    second copy of a balance, so the guard's input is computed rather than cached. A dispatch guard
    reading a stale column is a guard that releases gold on yesterday's arithmetic.
    """

    total = session.scalar(
        select(func.coalesce(func.sum(IncomingPaymentReceipt.confirmed_amount_irr), 0)).where(
            IncomingPaymentReceipt.gold_sale_order_id == order_id,
            IncomingPaymentReceipt.confirmed_amount_irr.is_not(None),
        )
    )
    return int(total or 0)


def _replayed(session: Session, claim: Any) -> tuple[GoldDispatch, GoldSaleOrder]:
    stored = claim.record.response_body or {}
    dispatch = session.get(GoldDispatch, uuid.UUID(str(stored["dispatch_id"])))
    order = session.get(GoldSaleOrder, uuid.UUID(str(stored["order_id"])))
    if dispatch is None or order is None:  # pragma: no cover - the record made it
        raise NotFoundError()
    return dispatch, order


def _audit(
    session: Session,
    policy: RedactionPolicy,
    *,
    dispatch: GoldDispatch,
    order: GoldSaleOrder,
    paid: int,
    guard_passed: bool,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
    previous: dict[str, Any],
) -> None:
    """§18 `:1236`'s "and audit", and it records **why the dispatch was allowed**.

    `guard_passed` is in the entry as its own field rather than being inferable from the override
    columns. A reader asking "was this gold released against confirmed money" gets a yes or a no
    without having to reason about which of three nullable columns are set.
    """

    AuditWriter(session, policy).record(
        AuditEntry(
            action=DISPATCH_GOLD_SALE.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="gold_dispatch",
            entity_id=dispatch.id,
            entity_record_version=dispatch.record_version,
            previous_values=previous,
            new_values={
                "dispatch_type": dispatch.dispatch_type,
                "status": dispatch.status,
                "gold_sale_order_id": str(order.id),
                "order_status": order.status,
                "confirmed_total_irr": str(paid),
                "expected_amount_irr": str(order.expected_amount_irr),
                "payment_guard_passed": guard_passed,
                "guard_override_by_admin_user_id": (
                    str(dispatch.guard_override_by_admin_user_id)
                    if dispatch.guard_override_by_admin_user_id
                    else None
                ),
            },
            reason=dispatch.guard_override_reason,
            occurred_at=now,
            metadata={"operation": DISPATCH_GOLD_SALE.audit_action},
        ),
        actor=actor,
        context=context,
    )
