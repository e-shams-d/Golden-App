"""Finalizer is not approver. Not configurable, and that is the point.

DOC-CONFLICT-021 was Resolved — Approved on 2026-07-20 because two authorities
disagreed: some workflow text presented preparer/approver separation as
configurable, while `12_Security_RBAC_Audit.md:650` makes it a Phase 1A acceptance
requirement. The approved resolution, recorded in
`FINANCIAL_INTEGRITY_BASELINE.md` §5, is that
`finalizer_actor_id != approver_actor_id` is **mandatory for every Phase 1A
outgoing batch and cannot be configured off**.

So there is no flag here, and no settings import. That absence is the feature:
`SEC-SOD-001` asserts that no configuration changes the outcome, and the way to
keep that true is to have nothing to read. A switch defaulting to "on" is a switch
someone turns off during an incident at 2am, which is exactly when the control
matters most.

**M3 has no batch to approve, and this still belongs here.** `:653-659` describes
the chain — accountant finalizes, a *different* manager approves, accountant
exports and marks sent — and M6/M7 implement it. What M3 owes is the policy object
and its tests, so those milestones consume one decision rather than each deriving
it. A rule re-derived at two call sites is a rule that disagrees with itself at
one of them.

**A worker is never a party to it.** `:344` gives workers a controlled `system`
actor for attribution and `:357` says they do not exercise approval or
confirmation authority. `14_Testing_QA_Acceptance.md:1294` requires the test.

Covers: SEC-SOD-001, SEC-SOD-002.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from app.security.actor import ActorContext, ActorType


class SeparationRefusal(StrEnum):
    SAME_IDENTITY = "same_identity"
    NOT_A_HUMAN_ACTOR = "not_a_human_actor"
    NO_FINALIZER_RECORDED = "no_finalizer_recorded"


@dataclass(frozen=True, slots=True)
class ApprovalAttempt:
    """Who finalized, and who is now trying to approve.

    `finalizer_actor_id` is optional so the "nobody finalized this" case has a
    representation. It is refused rather than allowed: an approval of a version
    with no recorded preparer cannot satisfy a rule about two different people,
    and treating a missing value as "different from everyone" is how a separation
    check passes on incomplete data.
    """

    finalizer_actor_id: uuid.UUID | None
    approver: ActorContext


# Actor types that may hold approval authority at all. Written as an allowlist:
# a new actor type added later is refused until somebody says otherwise, which is
# the fail-closed direction for a financial control.
HUMAN_ACTOR_TYPES: frozenset[ActorType] = frozenset({ActorType.ADMIN_USER})


def refusal_for(attempt: ApprovalAttempt) -> SeparationRefusal | None:
    """`None` when the approval may proceed on separation grounds alone.

    Separation only. Whether the approver holds `payment_batch_version.approve`,
    whether the version is current, and whether its hash still matches are
    different questions asked elsewhere — `12_Security_RBAC_Audit.md:575` is
    explicit that a role name is not sufficient authorization, and this function
    deliberately answers the narrowest of the several questions involved.
    """

    if attempt.approver.actor_type not in HUMAN_ACTOR_TYPES:
        # Covers the worker case (`:357`, QA `:1294`) and any trader reaching an
        # approval path at all.
        return SeparationRefusal.NOT_A_HUMAN_ACTOR

    if attempt.finalizer_actor_id is None:
        return SeparationRefusal.NO_FINALIZER_RECORDED

    if attempt.finalizer_actor_id == attempt.approver.actor_id:
        return SeparationRefusal.SAME_IDENTITY

    return None


def is_permitted(attempt: ApprovalAttempt) -> bool:
    """Convenience for call sites that only need the boolean.

    Kept alongside `refusal_for` rather than replacing it: the reason is what an
    `auth_events` row records, and a call site that discards it makes an incident
    harder to reconstruct than it needs to be.
    """

    return refusal_for(attempt) is None
