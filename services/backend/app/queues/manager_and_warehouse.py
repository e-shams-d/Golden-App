"""The manager's approval queue and the warehouse's three. `15_Agent_Implementation_Plan.md:1276`.

M11 slice 4. §19.2 gives the manager four queues and the warehouse three. **Four are built here and
three are not**, each for a reason that is about governance rather than effort — see
`app/queues/registry.py`'s `BLOCKED`.

**G-2 is answered: "ready for dispatch" is computed, not stored.** §19 `:1283` asks for the
warehouse's orders-ready-for-dispatch queue, and M10 records that `gold_sale_orders.status` never
becomes `ready_for_dispatch` — doc 06 §8.2 draws that edge, but slice 7 evaluates the dispatch
guard at dispatch time instead, so an order goes from `incoming_payment_confirmed` straight to
`dispatched`.

The plan offered two options and reserved the choice. Taken: the **derived** read, on the owner's
instruction to prefer the reversible one. It changes no merged behaviour, and if the stored fact is
wanted later the change is this queue's predicate plus a migration — where the reverse would mean
undoing a tested transition. Recorded here rather than in a commit message, because the next person
to read this file is the one who needs to know it was a choice.

**The warehouse's three are guarded by `gold_sale.dispatch`, not `gold_sale.read`.** That matters:
`gold_sale.read` (`permission_catalog.yaml:353`) includes `trader_owner`, so a queue behind it
would be reachable by every trader and would need ownership scoping. `gold_sale.dispatch` (`:372`)
is the warehouse operator's alone, which is the correct audience for work about releasing metal —
and it keeps these queues in the same "internal, no trader to scope" class as the accountant's.
"""

from __future__ import annotations

from sqlalchemy import Select

from app.db.models.gold_dispatch import GoldDispatch
from app.db.models.gold_sale import GoldSaleOrder
from app.db.models.payment_batch import PaymentBatchVersion
from app.db.pagination import ListSpec, SortField
from app.queues.contract import QueueDefinition, QueueRow
from app.security.actor import ActorContext

# `status_catalog.yaml`'s `payment_batch_version` aggregate, `:770-903`.
VERSION_READY_FOR_APPROVAL = "ready_for_approval"

# `gold_sale_order`, `06_Workflows_and_State_Machines.md` §8.2 / §10.1.
ORDER_PAYMENT_CONFIRMED = "incoming_payment_confirmed"
ORDER_MANAGER_APPROVAL_REQUIRED = "manager_approval_required"

# `gold_dispatch`, doc 06 §12.
DISPATCH_DISPATCHED = "dispatched"


def _internal[T](statement: Select[tuple[T]], actor: ActorContext) -> Select[tuple[T]]:
    """None of these consults the actor: every grant below is internal-only.

    Asserted rather than assumed — `tests/integration/test_queue_contract.py` sweeps every built
    queue and refuses a trader on each.
    """

    del actor
    return statement


# --- Manager -------------------------------------------------------------------------------


def _awaiting_a_manager(
    statement: Select[tuple[PaymentBatchVersion]], actor: ActorContext
) -> Select[tuple[PaymentBatchVersion]]:
    """§19.2's "exact batch versions awaiting approval", and *exact* is the load-bearing word.

    The queue is over versions, not batches. A batch's `ready_for_approval` is a **derived** state
    meaning its current version is finalized; approving is done to one immutable version, and M7's
    whole approval design turns on the manager deciding about the exact bytes they were shown.
    Returning batches would name the aggregate whose current version can change under the reader.

    `draft` and `rejected` are excluded — they are the accountant's queue, built in slice 3 — and
    `approved` and `superseded` are decided.
    """

    return _internal(statement, actor).where(
        PaymentBatchVersion.status == VERSION_READY_FOR_APPROVAL
    )


def _render_version(row: PaymentBatchVersion) -> QueueRow:
    return QueueRow(
        id=row.id,
        reference=f"v{row.version_number}",
        status=row.status,
        created_at=row.created_at,
    )


BATCH_VERSIONS_AWAITING_APPROVAL: QueueDefinition[PaymentBatchVersion] = QueueDefinition(
    name="batch-versions-awaiting-approval",
    permission="payment_batch_version.read_approval_view",
    spec=ListSpec(
        sorts=(
            SortField("created_at", PaymentBatchVersion.created_at),
            SortField("id", PaymentBatchVersion.id, unique=True),
        ),
        default_sort="created_at",
    ),
    predicate=_awaiting_a_manager,
    source="15_Agent_Implementation_Plan.md:1277",
    entity=PaymentBatchVersion,
    render=_render_version,
)


# --- Warehouse -----------------------------------------------------------------------------


def _dispatch_guard_would_pass(
    statement: Select[tuple[GoldSaleOrder]], actor: ActorContext
) -> Select[tuple[GoldSaleOrder]]:
    """G-2, answered as a computation. §19 `:1283`.

    An order whose incoming payment is confirmed is one the warehouse may release metal for —
    which is precisely the condition `app/commands/gold_dispatch.py` checks at dispatch time. So
    the queue asks the same question the guard asks, rather than reading a status nothing writes.

    `incoming_payment_partially_confirmed` is **excluded**, and that is the exclusion that matters:
    partial confirmation means some of the money arrived, and releasing gold against it is the
    decision the guard refuses. `manager_approval_required` is excluded too — it is the next queue,
    because an order sitting there is blocked rather than ready.
    """

    return _internal(statement, actor).where(GoldSaleOrder.status == ORDER_PAYMENT_CONFIRMED)


def _blocked_awaiting_an_override(
    statement: Select[tuple[GoldSaleOrder]], actor: ActorContext
) -> Select[tuple[GoldSaleOrder]]:
    """§19.2's "blocked dispatches".

    `manager_approval_required` is where an order lands when the payment guard did not pass and
    somebody has to decide. That is the same permission split M10 slice 7 built:
    `gold_sale.dispatch_override` is the manager's, so this queue shows the warehouse what it
    cannot move and why, without giving it the power to move it.
    """

    return _internal(statement, actor).where(
        GoldSaleOrder.status == ORDER_MANAGER_APPROVAL_REQUIRED
    )


def _render_order(row: GoldSaleOrder) -> QueueRow:
    return QueueRow(
        id=row.id,
        reference=row.order_number,
        status=row.status,
        created_at=row.created_at,
        trader_id=row.trader_id,
    )


def _order_spec() -> ListSpec:
    return ListSpec(
        sorts=(
            SortField("created_at", GoldSaleOrder.created_at),
            SortField("id", GoldSaleOrder.id, unique=True),
        ),
        filters=frozenset({"trader_id"}),
        default_sort="created_at",
    )


ORDERS_READY_FOR_DISPATCH: QueueDefinition[GoldSaleOrder] = QueueDefinition(
    name="orders-ready-for-dispatch",
    permission="gold_sale.dispatch",
    spec=_order_spec(),
    predicate=_dispatch_guard_would_pass,
    source="15_Agent_Implementation_Plan.md:1284",
    filter_columns={"trader_id": GoldSaleOrder.trader_id},
    entity=GoldSaleOrder,
    render=_render_order,
)

BLOCKED_DISPATCHES: QueueDefinition[GoldSaleOrder] = QueueDefinition(
    name="blocked-dispatches",
    permission="gold_sale.dispatch",
    spec=_order_spec(),
    predicate=_blocked_awaiting_an_override,
    source="15_Agent_Implementation_Plan.md:1285",
    filter_columns={"trader_id": GoldSaleOrder.trader_id},
    entity=GoldSaleOrder,
    render=_render_order,
)


def _awaiting_the_traders_word(
    statement: Select[tuple[GoldDispatch]], actor: ActorContext
) -> Select[tuple[GoldDispatch]]:
    """§19.2's "receipt confirmation work": metal that left and nobody has confirmed arrived.

    `dispatched` and not yet confirmed. `delivered` is excluded because the trader has
    acknowledged — that is M10 slice 8's `acknowledge_dispatch`, and the whole point of the state
    is that it records somebody's word rather than the centre's assumption.

    The `confirmed_at IS NULL` condition is **not** added alongside the status. M10 moves the
    dispatch to `delivered` in the same command that sets `confirmed_at`, so a second condition
    would be a guard that can never fire — and slice 3B's lesson is that two guards enforcing one
    rule mask each other one at a time and hide whether either is tested.
    """

    return _internal(statement, actor).where(GoldDispatch.status == DISPATCH_DISPATCHED)


def _render_dispatch(row: GoldDispatch) -> QueueRow:
    return QueueRow(
        id=row.id,
        reference=row.dispatch_type,
        status=row.status,
        created_at=row.created_at,
    )


RECEIPT_CONFIRMATION_WORK: QueueDefinition[GoldDispatch] = QueueDefinition(
    name="receipt-confirmation-work",
    permission="gold_sale.dispatch",
    spec=ListSpec(
        sorts=(
            SortField("created_at", GoldDispatch.created_at),
            SortField("id", GoldDispatch.id, unique=True),
        ),
        default_sort="created_at",
    ),
    predicate=_awaiting_the_traders_word,
    source="15_Agent_Implementation_Plan.md:1286",
    entity=GoldDispatch,
    render=_render_dispatch,
)
