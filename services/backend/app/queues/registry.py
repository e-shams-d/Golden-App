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
from app.queues.manager_and_warehouse import (
    BATCH_VERSIONS_AWAITING_APPROVAL,
    BLOCKED_DISPATCHES,
    ORDERS_READY_FOR_DISPATCH,
    RECEIPT_CONFIRMATION_WORK,
)
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
from app.queues.technical import QUARANTINED_FILES

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

# M11 slice 4. The manager's one buildable queue and the warehouse's three.
_MANAGER_AND_WAREHOUSE: tuple[QueueDefinition[Any], ...] = (
    BATCH_VERSIONS_AWAITING_APPROVAL,
    ORDERS_READY_FOR_DISPATCH,
    BLOCKED_DISPATCHES,
    RECEIPT_CONFIRMATION_WORK,
)

# M11 slice 5. One of §19.2's five technical queues; the other four are in `BLOCKED`.
_TECHNICAL: tuple[QueueDefinition[Any], ...] = (QUARANTINED_FILES,)

BUILT: dict[str, QueueDefinition[Any]] = {
    queue.name: queue
    for queue in (*_ACCOUNTANT, *_MANAGER_AND_WAREHOUSE, *_TECHNICAL)
}

# Queues §19.2 names that **cannot** be built as specified, each with what would unblock it.
#
# Separate from `PLANNED` on purpose. `PLANNED` means "a later slice does this"; these three have
# no later slice that could, because what is missing is a governance decision rather than work.
# Recording them as planned would be a promise nobody can keep, and dropping them would make the
# registry disagree with the document.
BLOCKED: dict[str, str] = {
    "sensitive-publication-corrections": (
        "§19.2 gives the manager this queue and `permission_catalog.yaml:625` gives "
        "`payment_publication.correct` `default_roles: []` — **no role holds it**, by design: "
        "POL-002 requires the preparer and approver permissions to be split and defers the split "
        "to ADR-SEC-009, which is unresolved. A queue guarded by that name would deny every "
        "caller, which is the `bank_profile.activate_version` shape this project already carries "
        "once. Guarding it by a *different* permission would be inventing an authority the "
        "catalogue withholds on purpose. Unblocked by ADR-SEC-009."
    ),
    "approved-exception-tasks": (
        "§19.2 names it and nothing defines it. `manual_review_task.task_type` has six values and "
        "none is an exception; `resolution_code` has no approval concept; no table records an "
        "'approved exception'. The nearest reading — a task a manager resolved by permitting "
        "something — is a guess about what the centre wants to review, and a queue built on a "
        "guess is one nobody opens twice. Unblocked by the owner saying which rows belong in it."
    ),
    "operational-warning-summaries": (
        "A **summary**, not a list of rows, and this contract returns rows. §19.2 does not say "
        "what is summarised or over what period, and `QueueRow`'s five fields cannot express an "
        "aggregate. Building it as a row list would answer a different question in the right "
        "place, which is worse than not answering. Unblocked by the owner defining the summary; "
        "it may not belong under `/queues/` at all."
    ),
    # M11 slice 5. Two different kinds of missing, and neither is unblocked by effort.
    "failed-jobs": (
        "No session permission exists. The catalogue holds none for `processing_jobs`, and the "
        "surface that already answers this — `GET /api/v1/operations/background-processing` — is "
        "guarded by an **operations token** rather than a session, which "
        "`test_m3_definition_of_done.py` classifies as its own auth class. A session-guarded twin "
        "would need an invented permission, or would duplicate an existing surface under weaker "
        "authority. Unblocked by the owner deciding whether operational reads belong to a session "
        "grant at all."
    ),
    "stale-outbox-records": (
        "Same as `failed-jobs`: no session permission for `outbox_events`, and the operations "
        "surface already reports the backlog and dead-letter count under an operations token. "
        "Unblocked by the same decision — whether operational reads belong to a session grant."
    ),
    "storage-reconciliation": (
        "**No table.** Nothing in `Base.metadata` records a reconciliation finding, so there are "
        "no rows for a predicate to select. Unblocked by the milestone that builds the "
        "reconciliation itself; a queue over nothing would be an empty list that reads as calm."
    ),
    "backup-health-warnings": (
        "**No table**, and the grant is the tell: `backup_status.read` "
        "(`permission_catalog.yaml:818`) is approved for `technical_admin` and "
        "`read_only_auditor`, so M0 decided who may look before anything was built to look at. "
        "ADR-004 — RPO, RTO, backup schedule and restore authority — is `TBD`, and its own text "
        "says production release is blocked until a restore drill passes. Unblocked by that."
    ),
}

# §19.2's remaining twenty-three, each spelled as the document spells it. This is a list of names,
# not of decisions: which permission guards each, and what "requiring review" means for a
# statement, are questions their own slices answer.
#
# Kept in §19.2's order and grouped by its four roles, because the grouping is the document's and
# regrouping it by table would lose the one fact that matters here — which role's day this queue is.
PLANNED: dict[str, str] = {
    # The accountant's eleven are in `BUILT` as of slice 3. Slice 4 took the manager's one
    # buildable queue and the warehouse's three; its other three are in `BLOCKED` above.
    # Slice 5 took the technical five: one built, four blocked above. Nothing remains planned;
    # every §19.2 name is now in BUILT or BLOCKED.
    # `ai-status` is deliberately absent rather than planned. §19.2 admits it "only when enabled",
    # and no AI path exists in this system — so a planned entry for it would be the registry
    # promising a queue that has nothing to hold.
}


def definition(name: str) -> QueueDefinition[Any] | None:
    return BUILT.get(name)
