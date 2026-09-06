"""What retention *would* delete, if anything were ever allowed to.
`15_Agent_Implementation_Plan.md:1318`.

M11 slice 6B. §19.5's last job — "retention dry run and approved execution only" — and this is the
dry run half. The execution half is not built and must not be: ADR-005 is open, the owner's
decision of 2026-09-05 is no automatic deletion, and `tests/backend/test_no_deletion_machinery.py`
refuses a scheduled task that removes rows.

**The authority for building the dry run first is the model's own docstring.**
`app/db/models/configuration.py`'s `RetentionPolicy` records the approved workflow as
`proposal → review → approval → legal-hold check → dry-run impact → backup coordination →
activation → separate deletion execution → deletion evidence`. The dry run is step five and
activation is step seven: the impact is meant to be known and trusted *before* anything is
switched on. So this is not a placeholder for the deletion job — it is the step that precedes it.

**`retention_policies` has had no application caller since M2.** A full
proposal-approval-activation lifecycle with three separate actor columns, and nothing has ever read
a row of it. This is the reader.

**An unresolvable resource type is reported, never counted as zero.** `resource_type` is a free
string with no approved vocabulary — inventing one here would decide by implementation what M0 has
not decided. So this module resolves the types it can and says plainly which it cannot. A policy
naming `receipt_segment` when nothing here maps that name produces `resolvable=False`, not
`eligible=0`. The difference is everything: one says "nothing would be deleted", the other says
"nobody knows what would be deleted", and a retention report that confuses them is worse than none.

**A legal hold wins over every policy.** Step four of the workflow above is the legal-hold check,
and it is applied here rather than left to the execution that does not exist: a row under an
unreleased hold is counted as protected and excluded from what would expire, so the report can
never suggest deleting something a hold covers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.db.models.configuration import LegalHold, RetentionPolicy
from app.db.models.file_object import FileObject

# Which `resource_type` values this module can turn into a query, and the column that decides a
# row's age.
#
# **One entry, deliberately.** `file_object` is the only resource whose retention question is
# unambiguous today: a file has one creation time and one owner table. Adding `payment_request` or
# `audit_log` would require deciding *from which timestamp* their retention runs — submission,
# publication, closure — and that is a governance answer rather than a mapping. A type absent from
# here is reported unresolvable, which is the honest outcome and the one that gets somebody to
# decide.
RESOLVERS: dict[str, tuple[type[FileObject], InstrumentedAttribute[datetime]]] = {
    "file_object": (FileObject, FileObject.created_at),
}

# `retention_policies.status` carries no CHECK — no approved catalogue enumerates it, and the model
# says inventing the set there would decide it. The same restraint applies here: this module asks
# whether a policy was *activated*, which is a timestamp the schema does constrain
# (`activated_at IS NULL OR approved_at IS NOT NULL`), rather than matching a status string nobody
# approved.
#
# So "active" means `activated_at IS NOT NULL`, and that is a fact rather than a vocabulary.


@dataclass(frozen=True, slots=True)
class PolicyImpact:
    """What one activated policy would do, and how confident this report is about it."""

    policy_id: uuid.UUID
    resource_type: str
    retention_seconds: int
    # `False` when no resolver maps this resource type. `eligible` and `protected` are then
    # meaningless and are reported as `None` rather than `0`, so a caller cannot read an unknown
    # as an empty.
    resolvable: bool
    eligible: int | None = None
    protected_by_legal_hold: int | None = None


@dataclass(frozen=True, slots=True)
class RetentionDryRun:
    """Every activated policy's impact, and whether anything is activated at all."""

    impacts: tuple[PolicyImpact, ...]

    @property
    def total_eligible(self) -> int:
        """Rows that would be deleted. Unresolvable policies contribute nothing to this."""

        return sum(impact.eligible or 0 for impact in self.impacts)

    @property
    def unresolved(self) -> tuple[str, ...]:
        """Resource types named by a policy that this module cannot query.

        Checked by callers rather than inferred from a zero count: a report whose totals look calm
        because half its policies could not be evaluated is the failure this field exists to make
        impossible.
        """

        return tuple(
            sorted({impact.resource_type for impact in self.impacts if not impact.resolvable})
        )


def _held_ids(session: Session, resource_type: str) -> Select[tuple[uuid.UUID | None]]:
    """Rows under a legal hold that nobody has released.

    `released_at IS NULL` is the whole test: a released hold is history, and treating it as live
    would make retention impossible to ever apply — which is a different failure from applying it
    too eagerly, and just as wrong.
    """

    return select(LegalHold.resource_id).where(
        LegalHold.resource_type == resource_type,
        LegalHold.released_at.is_(None),
    )


def plan_retention(session: Session, *, now: datetime) -> RetentionDryRun:
    """Report what activated retention policies would remove. Deletes nothing.

    **Bounded by the number of policies, not by the rows they describe.** §19 `:1318` wants a job
    that cannot grow without limit; this one issues two counting queries per activated policy and
    reads no row bodies at all, so its cost tracks the policy table — which a human proposes into,
    one row at a time — rather than the tables it describes.
    """

    policies = (
        session.execute(
            select(RetentionPolicy)
            .where(RetentionPolicy.activated_at.is_not(None))
            .order_by(RetentionPolicy.activated_at, RetentionPolicy.id)
        )
        .scalars()
        .all()
    )

    impacts: list[PolicyImpact] = []
    for policy in policies:
        resolver = RESOLVERS.get(policy.resource_type)
        if resolver is None:
            impacts.append(
                PolicyImpact(
                    policy_id=policy.id,
                    resource_type=policy.resource_type,
                    retention_seconds=policy.retention_seconds,
                    resolvable=False,
                )
            )
            continue

        model, aged_by = resolver
        cutoff = now - timedelta(seconds=policy.retention_seconds)
        older = aged_by < cutoff
        held = _held_ids(session, policy.resource_type)

        eligible = session.execute(
            select(func.count())
            .select_from(model)
            .where(older)
            .where(model.id.not_in(held))
        ).scalar_one()
        protected = session.execute(
            select(func.count()).select_from(model).where(older).where(model.id.in_(held))
        ).scalar_one()

        impacts.append(
            PolicyImpact(
                policy_id=policy.id,
                resource_type=policy.resource_type,
                retention_seconds=policy.retention_seconds,
                resolvable=True,
                eligible=int(eligible),
                protected_by_legal_hold=int(protected),
            )
        )

    return RetentionDryRun(impacts=tuple(impacts))
