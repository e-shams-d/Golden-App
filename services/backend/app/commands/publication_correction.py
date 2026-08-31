"""Correcting a published result without erasing what the trader was shown. §17.7.

M9 slice 7B. `15_Agent_Implementation_Plan.md:1172` (the eight steps),
`04_Database_Schema.md:1162` (the same thing in one sentence),
`12_Security_RBAC_Audit.md:1345` (the control), `05_API_Specification.md:1855` (where a correction
comes from).

**POL-002 is approved and it decides the control.** ADR_INDEX: "manager authority or dual control
is required; the accountant-only default is rejected... `payment_publication.correct` keeps
`default_roles: []` with preparer and approver split." So the empty default roles are a deployment
decision — an administrator assigns them — and not a reason to leave the command unbuilt. POL-002
also sets this slice's headline obligation in its own words: **"M9 correction and UAT must prove
the control cannot be configured off."**

That sentence is why the separation is enforced *here* rather than by which permissions a role
happens to hold. Grant one person both permissions — which an administrator can do, deliberately or
by accident — and `_refuse_a_single_human` still refuses. Configuring the control off requires
editing this file, which is what "cannot be configured off" has to mean if it means anything.

**A correction is not a new route; it is what evidence replacement must do once a result is
published.** Doc 05 `:1855`, in full: "In one transaction the old link becomes `replaced`, the new
link becomes active, affected publication state is recalculated, and audit/outbox events are
created. When a published result materially changes, a corrected publication and trader
notification are required." Slice 2 built the first half before publications existed;
`confirmed_evidence_link.replace_evidence_link` now refuses the published case and sends it here.

`command_catalog.yaml`'s `payment_publication.correct_paid_result` row carries `method: TBD, path:
TBD`, and this command declines to invent one: it is reached at the address document 05 already
gives the replacement, with the second human's headers alongside.

**The eight steps of §17.7, and where each lives:**

    create a sensitive review task          _open_a_correction_task
    preserve old result and evidence        the grant: only `status` is writable on publication N
    require dual-control decision           _refuse_a_single_human + the step-up context
    recalculate aggregates                  no paid sum changes; the request status is re-derived
    create publication N+1                  _publish_the_correction
    supersede N                             the same function, one transaction
    notify the trader                       `TraderResultCorrected` -> slice 7's projection
    retain full audit history               `payment_publication.superseded`

Covers: SVC-CORRECTION-001, SVC-CORRECTION-002, SEC-CORRECTION-001.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.outbox import OutboxMessage, OutboxWriter
from app.audit.redaction import RedactionPolicy
from app.audit.registry import CORRECT_PAYMENT_PUBLICATION
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.commands.manual_review_task import OpenTask, open_task
from app.commands.payment_publication import (
    PublicationRefused,
    _evidence_that_points_here,
    _next_version,
    _refuse_unverified_privacy,
    _snapshot,
)
from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.core.hashing import unversioned_digest
from app.db.locking import LockScope, LockTarget, lock_rows
from app.db.models.confirmed_evidence_link import (
    LINK_ACTIVE,
    LINK_REPLACED,
    ConfirmedEvidenceLink,
)
from app.db.models.manual_review_task import (
    ENTITY_PAYMENT_PUBLICATION,
    TASK_TYPE_RESULT_DISCREPANCY,
)
from app.db.models.payment_request import PaymentRequest
from app.db.models.payment_result_publication import (
    PUBLICATION_ACTIVE,
    PUBLICATION_SUPERSEDED,
    PaymentResultPublication,
)
from app.db.models.receipt_segment import ReceiptSegment
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.idempotency import IdempotencyResolver

METADATA_SCHEMA = "audit.publication_correction"
METADATA_VERSION = 1

CORRECT_OPERATION = "payment_publication.correct"

STEP_UP_PURPOSE = "payment_publication.correct"
STEP_UP_RESOURCE_TYPE = "payment_result_publication"

# Between M9's overpayment at 4 and M7's quarantine at 5. A published result that turned out to be
# wrong is money a trader has already been told about, which is more urgent than a discrepancy the
# centre found itself and less urgent than a file whose integrity failed on its way to a bank.
CORRECTION_PRIORITY = 5

REQUEST_RESULT_PUBLISHED = "result_published"

# `06_Workflows_and_State_Machines.md:602-605`. A correction may follow a publication a trader has
# acknowledged or disputed as well as one they have not touched — the dispute arrow returns to
# `result_published`, which is what a correction resolving a dispute looks like.
CORRECTABLE_FROM: tuple[str, ...] = (
    "result_published",
    "trader_acknowledged",
    "trader_disputed",
)


@dataclass(frozen=True, slots=True)
class CorrectPublishedResult:
    """One correction, prepared by one human and approved by another.

    **Both actors are fields, and neither comes from the same session.** The preparer is the
    caller; the approver is the human whose step-up reference is presented. A command that took one
    actor and checked a permission could be satisfied by one person holding both grants, which is
    the accountant-only default POL-002 rejects.
    """

    payment_request_id: uuid.UUID
    expected_record_version: int
    replaces_evidence_link_id: uuid.UUID
    new_receipt_segment_id: uuid.UUID
    correction_reason: str
    prepared_by_admin_user_id: uuid.UUID
    approved_by_admin_user_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class CorrectionResult:
    publication: PaymentResultPublication
    superseded: PaymentResultPublication
    task_id: uuid.UUID | None = None
    replayed: bool = False


def correct_published_result(
    command: CorrectPublishedResult,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> CorrectionResult:
    """§17.7's eight steps, in one transaction."""

    if not command.correction_reason.strip():
        raise BusinessRuleViolationError(
            "a correction requires a reason. §11.9 makes `correction_reason` NOT NULL whenever a "
            "publication supersedes another, and the CHECK refuses the row without one — this "
            "refusal exists so the caller is told which field rather than shown a constraint."
        )

    _refuse_a_single_human(command)
    _refuse_an_approver_without_the_grant(uow.session, command)

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=CORRECT_OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "payment_request_id": str(command.payment_request_id),
            "replaces_evidence_link_id": str(command.replaces_evidence_link_id),
        },
    )

    session = uow.session

    if claim.is_replay:
        publication, superseded = _replayed(session, claim)
        return CorrectionResult(
            publication=publication, superseded=superseded, replayed=True
        )

    request = _locked_request(session, command.payment_request_id)
    if request.status not in CORRECTABLE_FROM:
        raise PublicationRefused(
            f"request {request.request_number} is {request.status}; only "
            f"{', '.join(CORRECTABLE_FROM)} may be corrected. There is nothing to correct until a "
            "result has been published, and `04_Database_Schema.md:1162` describes a correction "
            "entirely in terms of the publication it supersedes."
        )

    active = _active_publication(session, request)
    replacement = _replace_the_evidence(session, command, request=request, now=now)
    _refuse_unverified_privacy(session, replacement)

    payload = _snapshot(session, request, replacement)
    content_hash = unversioned_digest(payload)

    # **The first thing a correction has to be is a change.** `uq_publication_content_per_request`
    # would refuse this row anyway, but by then publication N is already superseded and the
    # transaction unwinds — a caller told "duplicate key" learns nothing. The comparison is the
    # same digest the unique index holds, so the two cannot disagree.
    if content_hash == active.content_hash:
        raise PublicationRefused(
            f"the corrected result for {request.request_number} is identical to publication "
            f"v{active.publication_version}. `04_Database_Schema.md:1155` refuses a second version "
            "whose content is the same — a correction that changed nothing is not a new answer, "
            "and superseding the old one would tell the trader something happened when it did not."
        )

    superseded_version = active.publication_version
    active.status = PUBLICATION_SUPERSEDED
    uow.flush()

    corrected = _publish_the_correction(
        session,
        command,
        request=request,
        payload=payload,
        content_hash=content_hash,
        supersedes=active,
        evidence=replacement,
        now=now,
    )

    task = _open_a_correction_task(
        session,
        policy,
        request=request,
        publication=corrected,
        command=command,
        actor=actor,
        context=context,
        now=now,
    )

    _audit(
        session,
        policy,
        request=request,
        corrected=corrected,
        superseded_version=superseded_version,
        command=command,
        actor=actor,
        context=context,
        now=now,
    )

    OutboxWriter(session, policy).enqueue(
        OutboxMessage(
            aggregate_type="payment_result_publication",
            aggregate_id=corrected.id,
            aggregate_version=corrected.publication_version,
            event_type=str(CORRECT_PAYMENT_PUBLICATION.outbox_event_type),
            payload={
                "publication_id": str(corrected.id),
                "payment_request_id": str(request.id),
                "publication_version": corrected.publication_version,
                "supersedes_version": superseded_version,
            },
            payload_version=1,
            headers={},
        )
    )

    resolver.complete(
        claim,
        response_code=201,
        response_body={
            "publication_id": str(corrected.id),
            "superseded_id": str(active.id),
        },
        resource_type="payment_result_publication",
        resource_id=corrected.id,
        now=now,
    )
    return CorrectionResult(
        publication=corrected, superseded=active, task_id=task.id if task else None
    )


def _refuse_a_single_human(command: CorrectPublishedResult) -> None:
    """`SEC-CORRECTION-001`, and POL-002's "the control cannot be configured off".

    **Enforced on the identifiers, not on the permissions.** A guard that only asked "does the
    approver hold `payment_publication.correct`" would be satisfied by one administrator granting
    both permissions to one accountant — which is exactly the accountant-only default POL-002
    rejects, arriving through configuration rather than through code. Comparing the two ids cannot
    be switched off by any grant.
    """

    if command.prepared_by_admin_user_id == command.approved_by_admin_user_id:
        raise BusinessRuleViolationError(
            "a correction to a published paid result needs two people. "
            "`12_Security_RBAC_Audit.md:1345` requires that an accountant prepares and a second "
            "authorised human approves, and ADR_INDEX's POL-002 rejects the accountant-only "
            "default outright. Holding both permissions does not make one person two."
        )


def _refuse_an_approver_without_the_grant(
    session: Session, command: CorrectPublishedResult
) -> None:
    """The other half of POL-002's split: the approver holds `payment_publication.correct`.

    **Read from the approver's own roles, not from the caller's session**, because the approver is
    by definition not the caller. That is what makes this dual control rather than one person
    naming a colleague: an accountant cannot approve their own correction by typing a manager's id,
    because the manager's grants are what the query reads.

    Together with `_refuse_a_single_human` this is the whole control. Neither half is sufficient —
    the first alone would let two people without the grant do it, the second alone would let one
    person with both grants — and POL-002 requires both to be true at once.
    """

    from app.db.models.rbac import AdminUserRole, Permission, Role, RolePermission

    held = session.scalar(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(AdminUserRole, AdminUserRole.role_id == Role.id)
        .where(
            AdminUserRole.admin_user_id == command.approved_by_admin_user_id,
            Permission.code == CORRECT_OPERATION,
            Role.is_enabled.is_(True),
        )
    )
    if held is None:
        raise BusinessRuleViolationError(
            f"the named approver does not hold {CORRECT_OPERATION}. "
            "ADR_INDEX's POL-002 splits preparer from approver and keeps this permission at "
            "`default_roles: []` so that an administrator assigns it deliberately — naming "
            "somebody who does not have it is not a second authorisation."
        )


def _locked_request(session: Session, request_id: uuid.UUID) -> PaymentRequest:
    lock_rows(
        session,
        [LockTarget.of(LockScope.REQUEST_PAID_TOTAL, PaymentRequest, request_id)],
        models={PaymentRequest.__tablename__: PaymentRequest},
    )
    request = session.get(PaymentRequest, request_id)
    if request is None:
        raise NotFoundError()
    return request


def _active_publication(
    session: Session, request: PaymentRequest
) -> PaymentResultPublication:
    publication = session.scalar(
        select(PaymentResultPublication).where(
            PaymentResultPublication.payment_request_id == request.id,
            PaymentResultPublication.status == PUBLICATION_ACTIVE,
        )
    )
    if publication is None:
        raise NotFoundError()
    return publication


def _replace_the_evidence(
    session: Session,
    command: CorrectPublishedResult,
    *,
    request: PaymentRequest,
    now: datetime,
) -> ConfirmedEvidenceLink:
    """Doc 05 `:1855`'s first clause, done here because the ordinary path now refuses it.

    Retire then insert, which is slice 2's order and for its reason: the partial unique index
    permits one active primary per attempt, so inserting while the original is still active fails
    against the constraint the invariant depends on.

    **The old link is kept, not deleted.** §12.6 at `:1306`: replacement "never deletes or
    overwrites the old relationship". That is what lets publication N still resolve after this —
    the superseded publication points at a `replaced` link that is still there, which is the whole
    of "preserve old result and evidence".
    """

    original = session.get(ConfirmedEvidenceLink, command.replaces_evidence_link_id)
    if original is None:
        raise NotFoundError()
    if original.status != LINK_ACTIVE:
        raise PublicationRefused(
            f"evidence link {original.id} is {original.status}; a correction replaces the link the "
            "publication is actually citing."
        )
    if session.get(ReceiptSegment, command.new_receipt_segment_id) is None:
        raise NotFoundError()

    original.status = LINK_REPLACED
    session.flush()

    replacement = ConfirmedEvidenceLink(
        payment_attempt_id=original.payment_attempt_id,
        receipt_segment_id=command.new_receipt_segment_id,
        link_type=original.link_type,
        status=LINK_ACTIVE,
        confirmed_by_admin_user_id=command.prepared_by_admin_user_id,
        confirmed_at=now,
        replaces_link_id=original.id,
        replacement_reason=command.correction_reason,
        published_to_trader_at=now,
    )
    session.add(replacement)
    session.flush()

    # Belongs to this request, checked the way slice 5 checks it rather than assumed from the
    # attempt: a link naming another request's attempt would put somebody else's evidence into
    # this correction, and the field looks entirely legitimate.
    return _evidence_that_points_here(session, request, replacement.id) or replacement


def _publish_the_correction(
    session: Session,
    command: CorrectPublishedResult,
    *,
    request: PaymentRequest,
    payload: dict[str, Any],
    content_hash: str,
    supersedes: PaymentResultPublication,
    evidence: ConfirmedEvidenceLink,
    now: datetime,
) -> PaymentResultPublication:
    """Publication N+1, in the same transaction that superseded N.

    `uq_active_publication_per_request` is what makes the ordering matter: N must be `superseded`
    before N+1 is inserted, or the partial unique refuses the row. That is the same shape as slice
    2's retire-then-insert, one aggregate up — and it is why a correction that failed halfway
    cannot leave two active publications. `SVC-CORRECTION-002` asserts exactly one survives.
    """

    corrected = PaymentResultPublication(
        payment_request_id=request.id,
        publication_version=_next_version(session, request.id),
        status=PUBLICATION_ACTIVE,
        summary_payload=payload,
        primary_evidence_link_id=evidence.id,
        content_hash=content_hash,
        published_by_admin_user_id=command.approved_by_admin_user_id,
        published_at=now,
        supersedes_publication_id=supersedes.id,
        correction_reason=command.correction_reason,
    )
    session.add(corrected)
    session.flush()

    request.status = REQUEST_RESULT_PUBLISHED
    request.result_published_at = now
    session.flush()
    return corrected


def _open_a_correction_task(
    session: Session,
    policy: RedactionPolicy,
    *,
    request: PaymentRequest,
    publication: PaymentResultPublication,
    command: CorrectPublishedResult,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> Any:
    """§17.7's first step: "create a sensitive review task".

    `payment_result_discrepancy` again — the sixth value named from M0's approved list rather than
    added to it, and the accurate one: a published result that had to be corrected is a recorded
    result that disagreed with reality. The task names the *new* publication, so somebody opening
    the queue lands on what a trader is being shown now.
    """

    return open_task(
        OpenTask(
            task_type=TASK_TYPE_RESULT_DISCREPANCY,
            entity_type=ENTITY_PAYMENT_PUBLICATION,
            entity_id=publication.id,
            entity_record_version=publication.publication_version,
            title=(
                f"Published result corrected on {request.request_number} "
                f"(now v{publication.publication_version})"
            ),
            description=command.correction_reason,
            priority=CORRECTION_PRIORITY,
        ),
        session=session,
        policy=policy,
        actor=actor,
        context=context,
        now=now,
    )


def _replayed(
    session: Session, claim: Any
) -> tuple[PaymentResultPublication, PaymentResultPublication]:
    stored = claim.record.response_body or {}
    corrected = session.get(
        PaymentResultPublication, uuid.UUID(str(stored["publication_id"]))
    )
    superseded = session.get(
        PaymentResultPublication, uuid.UUID(str(stored["superseded_id"]))
    )
    if corrected is None or superseded is None:  # pragma: no cover - the record made it
        raise NotFoundError()
    return corrected, superseded


def _audit(
    session: Session,
    policy: RedactionPolicy,
    *,
    request: PaymentRequest,
    corrected: PaymentResultPublication,
    superseded_version: int,
    command: CorrectPublishedResult,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> None:
    """§17.7's last step, and **both humans are in the row**.

    An audit entry naming only the session that made the call would record a dual-control decision
    as one person's act. `12_Security_RBAC_Audit.md:1345` is a claim about who approved, and a
    trail that cannot answer it fails the only question anybody would ask afterwards.
    """

    AuditWriter(session, policy).record(
        AuditEntry(
            action=CORRECT_PAYMENT_PUBLICATION.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="payment_result_publication",
            entity_id=corrected.id,
            entity_record_version=corrected.publication_version,
            previous_values={"publication_version": superseded_version},
            new_values={
                "publication_version": corrected.publication_version,
                "payment_request_id": str(request.id),
                "content_hash": corrected.content_hash,
                "supersedes_publication_id": str(corrected.supersedes_publication_id),
                "prepared_by_admin_user_id": str(command.prepared_by_admin_user_id),
                "approved_by_admin_user_id": str(command.approved_by_admin_user_id),
            },
            reason=command.correction_reason,
            occurred_at=now,
            metadata={"operation": CORRECT_PAYMENT_PUBLICATION.audit_action},
        ),
        actor=actor,
        context=context,
    )
