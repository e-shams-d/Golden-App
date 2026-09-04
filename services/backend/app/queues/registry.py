"""The queues that exist, and the twenty-three that do not yet.
`15_Agent_Implementation_Plan.md:1260`.

M11 slice 2. §19.2 names twenty-four queues across four roles. This module holds the ones that are
built, and `PLANNED` names the rest — **by the document's own words**, so that "which queues exist"
is answerable by reading one file rather than by counting routes.

**Why the unbuilt ones are listed at all.** A registry containing only what is built cannot be
checked against the document: nothing fails when a queue is forgotten, because a missing thing is
silent in a way a wrong thing is not. `test_queue_contract.py` compares `BUILT | PLANNED` against
§19.2's list, so a queue that is neither built nor planned is a test failure that names it. Slice 3
moves ten entries from one collection to the other and the count is what proves it.

Slice 2 builds exactly one, which is the plan's own instruction: G-1 is decided by something that
works, and reversing the decision costs one slice rather than seven.
"""

from __future__ import annotations

from typing import Any

from app.queues.contract import QueueDefinition
from app.queues.money_movement import (
    APPROVED_EXPORTS_AWAITING_SEND,
    DRAFT_INVALID_BATCH_VERSIONS,
    FAILED_PARTIAL_RETRY_PAYMENTS,
    INCOMING_RECEIPTS_REQUIRING_REVIEW,
    RECONCILIATION_TASKS,
    SENT_ATTEMPTS_AWAITING_RESULT,
    UNRESOLVED_BUNDLES_SEGMENTS,
)
from app.queues.payment_requests import (
    CORRECTION_RESPONSES,
    ELIGIBLE_FOR_BATCHING_QUEUE,
    NEW_REQUESTS,
    TRADER_DISPUTES,
)

# Every queue with a route. Keyed by the URL segment, which is also the name §19.2 gives it.
#
# M11 slice 3 completes the accountant's eleven. The order is §19.2's, not alphabetical: the
# document lists them roughly in the order money moves, and keeping that makes a missing one
# visible by reading rather than by counting.
_ACCOUNTANT: tuple[QueueDefinition[Any], ...] = (
    NEW_REQUESTS,
    CORRECTION_RESPONSES,
    ELIGIBLE_FOR_BATCHING_QUEUE,
    DRAFT_INVALID_BATCH_VERSIONS,
    APPROVED_EXPORTS_AWAITING_SEND,
    SENT_ATTEMPTS_AWAITING_RESULT,
    UNRESOLVED_BUNDLES_SEGMENTS,
    FAILED_PARTIAL_RETRY_PAYMENTS,
    INCOMING_RECEIPTS_REQUIRING_REVIEW,
    TRADER_DISPUTES,
    RECONCILIATION_TASKS,
)

BUILT: dict[str, QueueDefinition[Any]] = {queue.name: queue for queue in _ACCOUNTANT}

# §19.2's remaining twenty-three, each spelled as the document spells it. This is a list of names,
# not of decisions: which permission guards each, and what "requiring review" means for a
# statement, are questions their own slices answer.
#
# Kept in §19.2's order and grouped by its four roles, because the grouping is the document's and
# regrouping it by table would lose the one fact that matters here — which role's day this queue is.
PLANNED: dict[str, str] = {
    # The accountant's eleven are all in `BUILT` as of slice 3.
    # Manager — §19.2's four. Slice 4.
    "batch-versions-awaiting-approval": "manager",
    "sensitive-publication-corrections": "manager",
    "approved-exception-tasks": "manager",
    "operational-warning-summaries": "manager",
    # Warehouse — §19.2's three. Slice 4, and the plan's G-2 lives in the first of them: M10
    # records that no order ever sits in `ready_for_dispatch`, so that queue cannot be a status
    # filter.
    "orders-ready-for-dispatch": "warehouse",
    "blocked-dispatches": "warehouse",
    "receipt-confirmation-work": "warehouse",
    # Technical operations — §19.2's six, less AI status. Slice 5, under §19 `:1298`'s last rule.
    "failed-jobs": "technical",
    "stale-outbox-records": "technical",
    "storage-reconciliation": "technical",
    "quarantined-files-exports": "technical",
    "backup-health-warnings": "technical",
    # `ai-status` is deliberately absent rather than planned. §19.2 admits it "only when enabled",
    # and no AI path exists in this system — so a planned entry for it would be the registry
    # promising a queue that has nothing to hold.
}


def definition(name: str) -> QueueDefinition[Any] | None:
    return BUILT.get(name)
