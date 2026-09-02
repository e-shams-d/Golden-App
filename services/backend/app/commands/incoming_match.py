"""Proposing and rejecting a match. `05_API_Specification.md:2002`.

M10 slice 5. Two commands, and the whole slice is the wall between them and slice 6: §21.5,
"Candidate acceptance and financial confirmation remain separate."

**This module cannot confirm anything, and the enforcement is not a branch.** It never writes
`confirmed_amount_irr`, `confirmed_at` or `confirmed_by_admin_user_id`; it never touches the
receipt's confirmation columns; and it never moves the receipt past `candidate_match`. `20260905_
0036` and `20260909_0040` both grant those columns — deliberately, so the grant reads as one
lifecycle rather than as two half-revisions — and what stops this slice writing them is that no
command here does. `SVC-MATCH-001` reads the receipt back rather than trusting that sentence.

**A match may only cite a row from a run that succeeded, and that guard comes from a document the
M10 plan did not cite until slice 3.** Document 08 §8.2's workflow ends: "confirmed rows become
available for matching." The *confirmation* half of that needs the review axis M0 still owes — see
the plan's G-4 — so the half this slice can enforce honestly is the execution half: the run must
have `succeeded`. A row from a `queued`, `running` or `failed` run describes a parse that either
has not finished or did not work, and matching against it would make the platform's belief about
incoming money depend on a parse nobody completed. The remaining half is recorded, not silently
claimed.

Covers: DB-MATCH-001, CON-MATCH-001, SVC-MATCH-001.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import PROPOSE_INCOMING_MATCH, REJECT_INCOMING_MATCH
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.core.errors import (
    BusinessRuleViolationError,
    ConflictError,
    NotFoundError,
)
from app.db.models.bank_statement import (
    RUN_SUCCEEDED,
    BankStatementImportRun,
    BankStatementRow,
)
from app.db.models.incoming_match import (
    MATCH_PROPOSED,
    MATCH_REJECTED,
    METHOD_MANUAL,
    IncomingPaymentMatch,
)
from app.db.models.incoming_payment import IncomingPaymentReceipt
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.idempotency import IdempotencyResolver

METADATA_SCHEMA = "audit.incoming_match"
METADATA_VERSION = 1

PROPOSE_OPERATION = "incoming_payment.match"
REJECT_OPERATION = "incoming_payment.match_rejected"

# A receipt whose claim is still open. `confirmed` and `rejected` are closed, and `superseded`
# belongs to a receipt something replaced — proposing a match against any of the three would be
# offering evidence for a question already answered.
MATCHABLE_RECEIPT_STATUSES: tuple[str, ...] = (
    "submitted",
    "waiting_for_bank_statement",
    "candidate_match",
    "needs_review",
    "duplicate_suspected",
    "partially_confirmed",
)

# Where a proposal leaves the receipt. §10.3's own word for "somebody has suggested which bank row
# this is, and nobody has agreed yet" — and four states before `confirmed`.
RECEIPT_CANDIDATE_MATCH = "candidate_match"


@dataclass(frozen=True, slots=True)
class ProposeMatch:
    """§21.5's body.

    **No `status`, no `confirmed_amount_irr`.** A proposal is `proposed`; a caller who could name
    either would be naming a confirmation, and the strongest refusal is having nowhere for one to
    arrive.
    """

    incoming_payment_receipt_id: uuid.UUID
    bank_statement_row_id: uuid.UUID
    match_reasons: list[str] = field(default_factory=list)
    match_score: Decimal | None = None


@dataclass(frozen=True, slots=True)
class RejectMatch:
    incoming_payment_match_id: uuid.UUID
    expected_record_version: int
    rejection_reason: str


@dataclass(frozen=True, slots=True)
class MatchResult:
    match: IncomingPaymentMatch
    receipt_status: str
    replayed: bool = False


def propose_match(
    command: ProposeMatch,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> MatchResult:
    """§21.5. A suggestion is recorded. Nothing is confirmed."""

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=PROPOSE_OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "incoming_payment_receipt_id": str(command.incoming_payment_receipt_id),
            "bank_statement_row_id": str(command.bank_statement_row_id),
        },
    )

    session = uow.session
    if claim.is_replay:
        replayed_match, replayed_receipt = _replayed(session, claim)
        return MatchResult(
            match=replayed_match, receipt_status=replayed_receipt.status, replayed=True
        )

    receipt = session.get(IncomingPaymentReceipt, command.incoming_payment_receipt_id)
    if receipt is None:
        raise NotFoundError()
    if receipt.status not in MATCHABLE_RECEIPT_STATUSES:
        raise BusinessRuleViolationError(
            f"receipt {receipt.id} is {receipt.status!r}; a match may be proposed only while the "
            f"claim is open ({', '.join(MATCHABLE_RECEIPT_STATUSES)}). Offering evidence for a "
            "question already answered is a correction, which is slice 8's."
        )

    row = _row_from_a_finished_parse(session, command.bank_statement_row_id)

    match = IncomingPaymentMatch(
        incoming_payment_receipt_id=receipt.id,
        bank_statement_row_id=row.id,
        # **`proposed`, and nothing else.** Not `accepted_for_review` — that is a person agreeing,
        # and §11.3's first rule is that even agreeing is not financial confirmation.
        status=MATCH_PROPOSED,
        match_method=METHOD_MANUAL,
        match_score=command.match_score,
        match_reasons=list(command.match_reasons),
        record_version=1,
    )
    session.add(match)
    _flush_or_conflict(uow, receipt_id=receipt.id, row_id=row.id)

    # The receipt records that a suggestion exists. **Not a confirmation**: §10.3's status list puts
    # `candidate_match` four states before `confirmed`, and this command may only ever write the
    # first.
    receipt.status = RECEIPT_CANDIDATE_MATCH
    receipt.record_version += 1
    uow.flush()

    _audit(
        session,
        policy,
        names=PROPOSE_INCOMING_MATCH,
        match=match,
        receipt=receipt,
        actor=actor,
        context=context,
        now=now,
        previous={},
    )

    resolver.complete(
        claim,
        response_code=201,
        response_body={"match_id": str(match.id), "receipt_id": str(receipt.id)},
        resource_type="incoming_payment_match",
        resource_id=match.id,
        now=now,
    )
    return MatchResult(match=match, receipt_status=receipt.status)


def reject_match(
    command: RejectMatch,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> MatchResult:
    """§21.5's other half. A suggestion is refused, with a reason and an actor."""

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=REJECT_OPERATION,
        idempotency_key=idempotency_key,
        payload={"incoming_payment_match_id": str(command.incoming_payment_match_id)},
    )

    session = uow.session
    if claim.is_replay:
        replayed_match, replayed_receipt = _replayed(session, claim)
        return MatchResult(
            match=replayed_match, receipt_status=replayed_receipt.status, replayed=True
        )

    match = session.get(IncomingPaymentMatch, command.incoming_payment_match_id)
    if match is None:
        raise NotFoundError()
    if match.record_version != command.expected_record_version:
        raise ConflictError(
            f"match {match.id} is at version {match.record_version} and If-Match named "
            f"{command.expected_record_version}"
        )
    if match.status != MATCH_PROPOSED:
        raise BusinessRuleViolationError(
            f"match {match.id} is {match.status!r}; only a proposal can be rejected. A decision "
            "already taken is corrected rather than reversed."
        )
    if not command.rejection_reason.strip():
        raise BusinessRuleViolationError(
            "a rejection needs a reason. §8.8 requires a match decision to record actor, time and "
            "reason, and a blank one records two of the three."
        )

    receipt = session.get(IncomingPaymentReceipt, match.incoming_payment_receipt_id)
    if receipt is None:  # pragma: no cover - the foreign key holds it
        raise NotFoundError()

    previous = {"status": match.status}
    match.status = MATCH_REJECTED
    match.rejected_by_admin_user_id = actor.actor_id
    match.rejected_at = now
    match.rejection_reason = command.rejection_reason
    match.record_version += 1
    uow.flush()

    _audit(
        session,
        policy,
        names=REJECT_INCOMING_MATCH,
        match=match,
        receipt=receipt,
        actor=actor,
        context=context,
        now=now,
        previous=previous,
    )

    resolver.complete(
        claim,
        response_code=200,
        response_body={"match_id": str(match.id), "receipt_id": str(receipt.id)},
        resource_type="incoming_payment_match",
        resource_id=match.id,
        now=now,
    )
    return MatchResult(match=match, receipt_status=receipt.status)


def _row_from_a_finished_parse(session: Session, row_id: uuid.UUID) -> BankStatementRow:
    """Document 08 §8.2, as far as this slice can honestly enforce it.

    "Confirmed rows become available for matching." The *confirmation* is the accountant's review
    of an import run, which needs the second status axis M0 has not yet chosen — the plan's G-4
    records it. So the half enforced here is the execution half: the run must have **succeeded**.

    A row from a `queued` or `running` run is one a parse has not finished with; a row from a
    `failed` run belongs to a parse whose mapping did not fit. Matching against either would make
    the platform's belief about incoming money rest on a parse nobody completed.
    """

    row = session.get(BankStatementRow, row_id)
    if row is None:
        raise NotFoundError()

    run = session.get(BankStatementImportRun, row.bank_statement_import_run_id)
    if run is None:  # pragma: no cover - the foreign key holds it
        raise NotFoundError()
    if run.status != RUN_SUCCEEDED:
        raise BusinessRuleViolationError(
            f"import run {run.id} is {run.status!r}; only rows from a run that succeeded may be "
            "matched. Document 08 §8.2 makes rows available for matching after the import is "
            "settled, not while it is running."
        )
    return row


def _flush_or_conflict(
    uow: SqlAlchemyUnitOfWork, *, receipt_id: uuid.UUID, row_id: uuid.UUID
) -> None:
    """`CON-MATCH-001`. The unique decides, not a read-then-insert.

    Two accountants proposing the same pair at the same instant both pass any `SELECT` written
    before the `INSERT`; only the constraint can separate them. Taking the ids as arguments rather
    than reading them off the object is deliberate — a failed flush expires the instance's
    attributes, and touching `match.id` in the handler would raise a second, unrelated error over
    the first.
    """

    try:
        uow.flush()
    except IntegrityError as error:
        uow.rollback()
        raise ConflictError(
            f"receipt {receipt_id} is already matched against row {row_id}. §10.7's unique on the "
            "pair means the same suggestion is one row, however many people propose it."
        ) from error


def _replayed(
    session: Session, claim: Any
) -> tuple[IncomingPaymentMatch, IncomingPaymentReceipt]:
    stored = claim.record.response_body or {}
    match = session.get(IncomingPaymentMatch, uuid.UUID(str(stored["match_id"])))
    receipt = session.get(IncomingPaymentReceipt, uuid.UUID(str(stored["receipt_id"])))
    if match is None or receipt is None:  # pragma: no cover - the record made it
        raise NotFoundError()
    return match, receipt


def _audit(
    session: Session,
    policy: RedactionPolicy,
    *,
    names: Any,
    match: IncomingPaymentMatch,
    receipt: IncomingPaymentReceipt,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
    previous: dict[str, Any],
) -> None:
    """The entry says what was suggested, and deliberately not what it is worth.

    No `confirmed_amount_irr` and no amount at all. An audit row carrying a figure beside a
    *proposal* would read as though the centre had agreed with it, which is the shape slice 2
    refused for the claim itself.
    """

    AuditWriter(session, policy).record(
        AuditEntry(
            action=names.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="incoming_payment_match",
            entity_id=match.id,
            entity_record_version=match.record_version,
            previous_values=previous,
            new_values={
                "status": match.status,
                "incoming_payment_receipt_id": str(receipt.id),
                "bank_statement_row_id": str(match.bank_statement_row_id),
                "match_method": match.match_method,
                "receipt_status": receipt.status,
                "rejection_reason": match.rejection_reason,
            },
            reason=match.rejection_reason,
            occurred_at=now,
            metadata={"operation": names.audit_action},
        ),
        actor=actor,
        context=context,
    )
