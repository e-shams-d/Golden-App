"""The accountant's request queues. `15_Agent_Implementation_Plan.md:1262`.

M11 slice 2 built `new-requests`; slice 3 adds the three others that read `payment_requests` and
**corrects the first one**.

**`new-requests` was returning correction responses too, and §19.2 lists them as two queues.**
A request handed back for correction leaves `submitted_to_center`, and returns to it when the
trader resubmits — so status alone cannot tell a first submission from a second. The marker is
`review_note`: `return_for_correction` writes it (`app/commands/payment_request.py:730`) and
nothing clears it, and the only other command that writes one moves the request to
`eligible_for_batching` instead. So within `submitted_to_center`, a null note is a request nobody
has looked at, and a non-null note is a trader answering something the centre asked.

Two queues that overlap are worse than one queue that is too wide: the accountant works the first,
the second still shows the same rows, and the work is done twice or not at all. They partition
here, and `test_queue_contract.py` asserts the partition rather than each queue separately.
"""

from __future__ import annotations

from sqlalchemy import Select

from app.db.models.payment_request import PaymentRequest
from app.db.pagination import ListSpec, SortField
from app.queues.contract import QueueDefinition, QueueRow
from app.security.actor import ActorContext

# `status_catalog.yaml`'s `payment_request` aggregate,
# `06_Workflows_and_State_Machines.md:555-607`.
SUBMITTED_TO_CENTER = "submitted_to_center"
UNDER_ACCOUNTANT_REVIEW = "under_accountant_review"
ELIGIBLE_FOR_BATCHING = "eligible_for_batching"


def _spec(*, filters: frozenset[str] = frozenset()) -> ListSpec:
    """The ordering every request queue shares.

    One helper rather than four copies: the tiebreak is the part that is easy to omit and
    impossible to notice, and `created_at` is not unique — several requests submitted in one
    sitting share a timestamp exactly.
    """

    return ListSpec(
        sorts=(
            SortField("created_at", PaymentRequest.created_at),
            SortField("id", PaymentRequest.id, unique=True),
        ),
        filters=filters,
        default_sort="created_at",
    )


def _render(row: PaymentRequest) -> QueueRow:
    return QueueRow(
        id=row.id,
        reference=row.request_number,
        status=row.status,
        created_at=row.created_at,
        trader_id=row.trader_id,
    )


def _no_scope(
    statement: Select[tuple[PaymentRequest]], actor: ActorContext
) -> Select[tuple[PaymentRequest]]:
    """These queues are internal, so the actor decides nothing.

    `payment_request.read` goes to four internal roles and no trader holds it, so there is no
    trader who could be scoped. A `scoped()` call here would be a filter that never fires —
    recorded at length in `tests/backend/test_ownership_scope.py`'s exemption.
    """

    del actor
    return statement


def _submitted_and_never_returned(
    statement: Select[tuple[PaymentRequest]], actor: ActorContext
) -> Select[tuple[PaymentRequest]]:
    """A first submission: submitted, and never handed back."""

    return _no_scope(statement, actor).where(
        PaymentRequest.status == SUBMITTED_TO_CENTER,
        PaymentRequest.review_note.is_(None),
    )


def _a_trader_answering_the_centre(
    statement: Select[tuple[PaymentRequest]], actor: ActorContext
) -> Select[tuple[PaymentRequest]]:
    """§19.2's "correction responses": resubmitted after the centre asked for a change.

    The complement of the queue above, within the same status, which is why the two are written
    next to each other. `under_accountant_review` is excluded from both — somebody has it.
    """

    return _no_scope(statement, actor).where(
        PaymentRequest.status == SUBMITTED_TO_CENTER,
        PaymentRequest.review_note.is_not(None),
    )


def _eligible_for_batching(
    statement: Select[tuple[PaymentRequest]], actor: ActorContext
) -> Select[tuple[PaymentRequest]]:
    """Approved by an accountant and waiting for a batch. Nothing derived; the status says it."""

    return _no_scope(statement, actor).where(PaymentRequest.status == ELIGIBLE_FOR_BATCHING)


def _disputed_by_a_trader(
    statement: Select[tuple[PaymentRequest]], actor: ActorContext
) -> Select[tuple[PaymentRequest]]:
    """§19.2's "trader disputes", and the one accountant queue that is not a status filter.

    Disputing is not a request state — `status_catalog.yaml` has none, and M9 recorded the dispute
    as a **timestamp** on the request (`trader_disputed_at`) because a trader saying "this is
    wrong" does not move the money that already moved. So the queue is the timestamp being set.

    **Acknowledgement does not clear it**, and nothing else does either: there is no command that
    resolves a dispute, which is a real gap rather than an omission here. Recorded as the plan's
    G-6; until a resolution exists, this queue is every dispute ever raised, which is the honest
    answer and is visibly wrong in a way a silently-filtered one would not be.
    """

    return _no_scope(statement, actor).where(PaymentRequest.trader_disputed_at.is_not(None))


NEW_REQUESTS: QueueDefinition[PaymentRequest] = QueueDefinition(
    name="new-requests",
    permission="payment_request.read",
    spec=_spec(filters=frozenset({"trader_id"})),
    predicate=_submitted_and_never_returned,
    source="15_Agent_Implementation_Plan.md:1262",
    filter_columns={"trader_id": PaymentRequest.trader_id},
    entity=PaymentRequest,
    render=_render,
)

CORRECTION_RESPONSES: QueueDefinition[PaymentRequest] = QueueDefinition(
    name="correction-responses",
    permission="payment_request.read",
    spec=_spec(filters=frozenset({"trader_id"})),
    predicate=_a_trader_answering_the_centre,
    source="15_Agent_Implementation_Plan.md:1263",
    filter_columns={"trader_id": PaymentRequest.trader_id},
    entity=PaymentRequest,
    render=_render,
)

ELIGIBLE_FOR_BATCHING_QUEUE: QueueDefinition[PaymentRequest] = QueueDefinition(
    name="eligible-for-batching",
    permission="payment_request.read",
    spec=_spec(filters=frozenset({"trader_id"})),
    predicate=_eligible_for_batching,
    source="15_Agent_Implementation_Plan.md:1264",
    filter_columns={"trader_id": PaymentRequest.trader_id},
    entity=PaymentRequest,
    render=_render,
)

TRADER_DISPUTES: QueueDefinition[PaymentRequest] = QueueDefinition(
    name="trader-disputes",
    permission="payment_request.read",
    spec=_spec(filters=frozenset({"trader_id"})),
    predicate=_disputed_by_a_trader,
    source="15_Agent_Implementation_Plan.md:1271",
    filter_columns={"trader_id": PaymentRequest.trader_id},
    entity=PaymentRequest,
    render=_render,
)
