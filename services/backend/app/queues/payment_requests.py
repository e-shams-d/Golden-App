"""The accountant's first queue: requests that arrived and nobody has picked up.
`15_Agent_Implementation_Plan.md:1262`.

M11 slice 2. §19.2's first accountant queue, built against `payment_requests`, which M5 created and
has read since — so this slice adds no table, no column, no command and no permission.

**"New" is `submitted_to_center`, and only that.** `status_catalog.yaml`'s `payment_request`
aggregate gives the state its meaning: "current revision submitted for center review".
`under_accountant_review` is the adjacent state and is deliberately excluded — a request somebody
is already working on is not new, and a queue that includes it hands two accountants the same work.
That exclusion is the half of `SVC-QUEUE-001` that fails against a query returning everything.

**Why this queue exists when `GET /payment-requests` already lists requests.** That route is M5's
and it is **unbounded**: it selects every matching row with no limit and no cursor
(`app/api/v1/payment_requests.py:381`). §19 `:1298` forbids exactly that — "no client loading of
all financial records" — so the accountant's daily surface could not be built on it without
changing a shipped response shape. Recorded here rather than fixed: narrowing that route is a
breaking contract change and belongs to whoever owns the deprecation, not to this slice.
"""

from __future__ import annotations

from sqlalchemy import Select

from app.db.models.payment_request import PaymentRequest
from app.db.pagination import ListSpec, SortField
from app.queues.contract import QueueDefinition
from app.security.actor import ActorContext

# `status_catalog.yaml`'s `payment_request` aggregate, `06_Workflows_and_State_Machines.md:555-607`.
SUBMITTED_TO_CENTER = "submitted_to_center"

NEW_REQUESTS_SPEC = ListSpec(
    sorts=(
        # Oldest first is the default for this queue — see `descending=False` at the route. A work
        # queue is drained from the bottom, unlike an audit log which is read from the top.
        SortField("created_at", PaymentRequest.created_at),
        # The unique tiebreak. `created_at` cannot terminate the sort: several requests submitted
        # in one batch of trader activity can share a timestamp, and a sort that ends there repeats
        # or drops rows at exactly the page boundary a busy queue spends its time near.
        SortField("id", PaymentRequest.id, unique=True),
    ),
    # One filter. `trader_id` narrows the queue to one business, which is the question an
    # accountant asks when a trader telephones. `status` is deliberately **not** filterable: the
    # status is what defines this queue, and letting a caller override it would make
    # `/queues/new-requests?status=paid` a different queue reached through the wrong name.
    filters=frozenset({"trader_id"}),
    default_sort="created_at",
)


def _submitted_and_unclaimed(
    statement: Select[tuple[PaymentRequest]], actor: ActorContext
) -> Select[tuple[PaymentRequest]]:
    """The queue's whole definition, and it does not consult the actor.

    **No ownership scoping, on purpose.** This queue is guarded by `payment_request.read`, which
    `permission_catalog.yaml` gives to internal staff and no trader holds — a trader resolves no
    permissions at all. So there is no trader who can reach this to be scoped, and adding a
    `scoped()` call would be a filter that never fires, protecting against nothing while looking
    like protection. A trader's own list is `GET /payment-requests`, which does scope.
    """

    del actor
    return statement.where(PaymentRequest.status == SUBMITTED_TO_CENTER)


NEW_REQUESTS: QueueDefinition[PaymentRequest] = QueueDefinition(
    name="new-requests",
    permission="payment_request.read",
    spec=NEW_REQUESTS_SPEC,
    predicate=_submitted_and_unclaimed,
    source="15_Agent_Implementation_Plan.md:1262",
    filter_columns={"trader_id": PaymentRequest.trader_id},
)
