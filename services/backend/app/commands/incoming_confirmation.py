"""A person decides the money arrived. `05_API_Specification.md:2011`.

M10 slice 6. The moment this milestone exists for, and §21.6's last line is the whole design:
**"Partial, excess, or ambiguous amounts produce explicit order state/review tasks. They are not
silently treated as fully paid."**

Three outcomes, and none of them is "close enough":

- **short** — the order becomes `incoming_payment_partially_confirmed` and the receipt
  `partially_confirmed`. More money may arrive; nothing is closed.
- **exact** — the order becomes `incoming_payment_confirmed`.
- **excess** — a review task is opened **and the confirmation is refused**. M9's overpayment shape
  exactly, including the part that took M9 two tries: the task commits even though the command
  raises, because a refusal that rolls back its own record leaves nobody asked to look.

**The paid sum is computed, never cached.** `04_Database_Schema.md:469` forbids a second copy of a
balance and M9 slice 4 refused one for the outgoing direction. So every confirmation re-reads the
sum of this order's confirmed receipts under the order's own lock; there is no `paid_amount_irr`
column and there must not be one. `gold_sale_orders.final_amount_irr` is the *priced* figure, not a
running total.

**The row-reuse guard is here rather than in an index, and that is deliberate.** Document 06 §11.3:
"A row already used in an active match causes a duplicate/conflict guard unless an explicit
combined-payment model is used." A partial unique would have expressed it — and would also have
answered §10.7 `:809`'s open cardinality question in a migration, which is exactly what slice 5's
`test_no_partial_unique_constrains_the_pair` exists to prevent. A guard a business decision can
lift beats an index a migration must remove.

Covers: SVC-INCOMING-001, SVC-INCOMING-002, AUD-INCOMING-001.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import CONFIRM_INCOMING_PAYMENT
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.commands.manual_review_task import OpenTask, open_task
from app.core.errors import (
    BusinessRuleViolationError,
    ConflictError,
    NotFoundError,
)
from app.db.models.gold_sale import GoldSaleOrder
from app.db.models.incoming_match import (
    CONFIRMATION_ACTIVE,
    MATCH_ACCEPTED_FOR_REVIEW,
    MATCH_PROPOSED,
    IncomingPaymentMatch,
)
from app.db.models.incoming_payment import IncomingPaymentReceipt
from app.db.models.manual_review_task import (
    ENTITY_INCOMING_RECEIPT,
    TASK_TYPE_INCOMING_DISCREPANCY,
)
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.idempotency import IdempotencyResolver

METADATA_SCHEMA = "audit.incoming_confirmation"
METADATA_VERSION = 1

CONFIRM_OPERATION = "incoming_payment.confirm"

# A claim somebody may still decide. `confirmed`, `rejected` and `superseded` are closed; a second
# confirmation of a closed receipt is a correction, which is slice 8's.
CONFIRMABLE_FROM: tuple[str, ...] = (
    "submitted",
    "waiting_for_bank_statement",
    "candidate_match",
    "needs_review",
    "duplicate_suspected",
    "partially_confirmed",
)

# A candidate a person may act on. A rejected, superseded or expired one has been decided against.
CONFIRMABLE_MATCH_STATUSES: tuple[str, ...] = (MATCH_PROPOSED, MATCH_ACCEPTED_FOR_REVIEW)

RECEIPT_CONFIRMED = "confirmed"
RECEIPT_PARTIALLY_CONFIRMED = "partially_confirmed"

# `status_catalog.yaml`'s `gold_sale_order` aggregate. Both are canonical there, and §21.6's
# "not silently treated as fully paid" is the reason the first exists at all.
ORDER_PARTIALLY_CONFIRMED = "incoming_payment_partially_confirmed"
ORDER_CONFIRMED = "incoming_payment_confirmed"


class OverpaymentRefused(BusinessRuleViolationError):
    """Confirming would take the order's confirmed sum above what it was priced at.

    **Its own type so the route can commit the review task before re-raising**, which is the half
    M9's first version got wrong: it raised a plain `BusinessRuleViolationError` and the task was
    discarded with the failed transaction, leaving a refusal nobody followed up. §21.6 requires
    both — "explicit order state/review tasks" — and a task without the refusal is worse, because
    the money would read as received while somebody is still being asked about it.
    """


@dataclass(frozen=True, slots=True)
class ConfirmIncomingPayment:
    """§21.6's body, exactly.

    `incoming_payment_match_id` is nullable **because §21.6 writes it that way**: a statement may
    be unreadable, or the transfer may have arrived by a route the import cannot see, and document
    08 §8.9's first edge case is "evidence before statement availability". A confirmation with no
    match is a person taking responsibility without a bank row to point at, and the audit entry
    says so by carrying a null match id rather than omitting the field.
    """

    incoming_payment_receipt_id: uuid.UUID
    expected_record_version: int
    confirmed_amount_irr: int
    incoming_payment_match_id: uuid.UUID | None = None
    confirmation_note: str | None = None


@dataclass(frozen=True, slots=True)
class ConfirmationResult:
    receipt: IncomingPaymentReceipt
    order_status: str
    confirmed_total_irr: int
    expected_amount_irr: int | None
    replayed: bool = False


def confirm_incoming_payment(
    command: ConfirmIncomingPayment,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> ConfirmationResult:
    """§21.6. One transaction: the match, the receipt and the order move together.

    Document 06 §11.3's second rule requires exactly that — "Accountant confirmation creates the
    authoritative receipt-to-row match and updates confirmed amounts in one transaction" — and the
    reason is that any split leaves a confirmed receipt against an order that does not know.
    """

    if command.confirmed_amount_irr <= 0:
        raise BusinessRuleViolationError(
            "a confirmation needs a positive amount; §10.3's CHECK refuses anything else. "
            "Confirming that nothing arrived is a rejection, not a confirmation."
        )

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=CONFIRM_OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "incoming_payment_receipt_id": str(command.incoming_payment_receipt_id),
            "confirmed_amount_irr": str(command.confirmed_amount_irr),
        },
    )

    session = uow.session
    if claim.is_replay:
        replayed_receipt, replayed_order = _replayed(session, claim)
        return ConfirmationResult(
            receipt=replayed_receipt,
            order_status=replayed_order.status,
            confirmed_total_irr=_confirmed_total(session, replayed_order.id),
            expected_amount_irr=replayed_order.expected_amount_irr,
            replayed=True,
        )

    receipt = session.get(IncomingPaymentReceipt, command.incoming_payment_receipt_id)
    if receipt is None:
        raise NotFoundError()
    if receipt.record_version != command.expected_record_version:
        raise ConflictError(
            f"receipt {receipt.id} is at version {receipt.record_version} and If-Match named "
            f"{command.expected_record_version}"
        )
    if receipt.status not in CONFIRMABLE_FROM:
        raise BusinessRuleViolationError(
            f"receipt {receipt.id} is {receipt.status!r}; a confirmation belongs to a claim still "
            f"open ({', '.join(CONFIRMABLE_FROM)}). Re-deciding a closed one is a correction."
        )

    # **The order is locked before the sum is read.** Two accountants confirming two receipts of
    # one order would otherwise both read the old total and both pass the overpayment check —
    # M9 slice 4's lesson, and the reason `no_overpayment` is a catalogued precondition rather
    # than a comment.
    order = session.get(GoldSaleOrder, receipt.gold_sale_order_id, with_for_update=True)
    if order is None:  # pragma: no cover - the foreign key holds it
        raise NotFoundError()

    match = _confirmable_match(session, command, receipt)

    already = _confirmed_total(session, order.id)
    total = already + command.confirmed_amount_irr
    expected = order.expected_amount_irr

    if expected is not None and total > expected:
        _open_overpayment_task(
            session,
            policy,
            receipt=receipt,
            order=order,
            already=already,
            offered=command.confirmed_amount_irr,
            expected=expected,
            actor=actor,
            context=context,
            now=now,
        )
        raise OverpaymentRefused(
            f"confirming {command.confirmed_amount_irr} against order {order.order_number} would "
            f"total {total} where {expected} was priced. §21.6 refuses to treat excess as fully "
            "paid; a review task has been opened."
        )

    if match is not None:
        match.confirmed_amount_irr = command.confirmed_amount_irr
        match.confirmed_by_admin_user_id = actor.actor_id
        match.confirmed_at = now
        # The second axis. Document 06 §11.2's first state: this is the authoritative match until
        # a correction replaces it or a governed revocation retires it.
        match.confirmation_status = CONFIRMATION_ACTIVE
        match.record_version += 1

    previous = {"status": receipt.status, "order_status": order.status}

    receipt.confirmed_amount_irr = command.confirmed_amount_irr
    receipt.confirmed_by_admin_user_id = actor.actor_id
    receipt.confirmed_at = now
    receipt.status = (
        RECEIPT_CONFIRMED
        if expected is not None and total >= expected
        else RECEIPT_PARTIALLY_CONFIRMED
    )
    receipt.record_version += 1

    # **Computed from the sum, not from this receipt.** Two receipts of 40 against a 100 order
    # leave the order partially confirmed even though the second receipt was confirmed in full,
    # and that is `SVC-INCOMING-001`.
    order.status = (
        ORDER_CONFIRMED
        if expected is not None and total >= expected
        else ORDER_PARTIALLY_CONFIRMED
    )
    order.record_version += 1
    uow.flush()

    _audit(
        session,
        policy,
        receipt=receipt,
        order=order,
        match=match,
        total=total,
        note=command.confirmation_note,
        actor=actor,
        context=context,
        now=now,
        previous=previous,
    )

    resolver.complete(
        claim,
        response_code=200,
        response_body={"receipt_id": str(receipt.id), "order_id": str(order.id)},
        resource_type="incoming_payment_receipt",
        resource_id=receipt.id,
        now=now,
    )
    return ConfirmationResult(
        receipt=receipt,
        order_status=order.status,
        confirmed_total_irr=total,
        expected_amount_irr=expected,
    )


def _confirmable_match(
    session: Session, command: ConfirmIncomingPayment, receipt: IncomingPaymentReceipt
) -> IncomingPaymentMatch | None:
    """The candidate being confirmed, if one was named, and every reason it might not be.

    Document 06 §11.3's third rule lives here: "A row already used in an active match causes a
    duplicate/conflict guard." A single bank credit funding two different orders is the case it
    describes, and it is a conflict rather than a refusal because the right answer is usually to
    correct the earlier match rather than to abandon this one.
    """

    if command.incoming_payment_match_id is None:
        return None

    match = session.get(IncomingPaymentMatch, command.incoming_payment_match_id)
    if match is None:
        raise NotFoundError()
    if match.incoming_payment_receipt_id != receipt.id:
        # The match belongs to another claim. 404 rather than a description, for the reason the
        # route gives: naming the mismatch confirms the match exists.
        raise NotFoundError()
    if match.status not in CONFIRMABLE_MATCH_STATUSES:
        raise BusinessRuleViolationError(
            f"match {match.id} is {match.status!r}; only a candidate still under consideration "
            f"({', '.join(CONFIRMABLE_MATCH_STATUSES)}) can be confirmed."
        )
    if match.confirmation_status is not None:
        raise BusinessRuleViolationError(
            f"match {match.id} is already {match.confirmation_status!r}. Confirming it twice would "
            "record two decisions about one pair; changing one is a correction."
        )

    conflicting = session.scalars(
        select(IncomingPaymentMatch)
        .where(IncomingPaymentMatch.bank_statement_row_id == match.bank_statement_row_id)
        .where(IncomingPaymentMatch.confirmation_status == CONFIRMATION_ACTIVE)
        .where(IncomingPaymentMatch.id != match.id)
    ).first()
    if conflicting is not None:
        raise ConflictError(
            f"statement row {match.bank_statement_row_id} is already the active match for receipt "
            f"{conflicting.incoming_payment_receipt_id}. Document 06 §11.3 guards a row used "
            "twice: one bank credit cannot pay two different claims unless a combined-payment "
            "model says so, which G-2 leaves to the business."
        )
    return match


def _confirmed_total(session: Session, order_id: uuid.UUID) -> int:
    """Every confirmed rial on this order, read fresh.

    **Not cached, and there is no column to cache it in.** `04_Database_Schema.md:469` forbids a
    second copy of a balance; M9 slice 4 refused one for the outgoing direction and the argument is
    the same here. `gold_sale_orders.final_amount_irr` is the priced figure and must not be
    mistaken for a running total.
    """

    total = session.scalar(
        select(func.coalesce(func.sum(IncomingPaymentReceipt.confirmed_amount_irr), 0)).where(
            IncomingPaymentReceipt.gold_sale_order_id == order_id,
            IncomingPaymentReceipt.confirmed_amount_irr.is_not(None),
        )
    )
    return int(total or 0)


def _open_overpayment_task(
    session: Session,
    policy: RedactionPolicy,
    *,
    receipt: IncomingPaymentReceipt,
    order: GoldSaleOrder,
    already: int,
    offered: int,
    expected: int,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> None:
    """§21.6's "review tasks", with a declared type and a reference that navigates.

    **Both names are declared rather than borrowed, and the first draft borrowed them.** It used
    4B's `statement_duplicate_review` with `bank_statement_import_run` while passing a *receipt*
    id — a task whose type described something else and whose reference pointed nowhere. The
    enumeration exists to stop exactly that: `20260824_0025`'s comment says "a generic reference
    whose type is unconstrained is one nothing can navigate."

    So `20260910_0041` adds `incoming_payment_receipt` by the entity list's own rule — a table that
    exists — and declares `incoming_payment_discrepancy`, because `payment_result_discrepancy` is
    about an outgoing result and would file this in the queue an accountant filters for the other
    direction of money. Both are recorded as names M0 owes.
    """

    open_task(
        OpenTask(
            task_type=TASK_TYPE_INCOMING_DISCREPANCY,
            entity_type=ENTITY_INCOMING_RECEIPT,
            entity_id=receipt.id,
            entity_record_version=receipt.record_version,
            title=(
                f"Overpayment on {order.order_number}: confirming {offered} would total "
                f"{already + offered} against {expected} priced"
            ),
            description=(
                "The confirmation was refused. §21.6 does not treat excess as fully paid; either "
                "the priced amount is wrong or the trader sent more than the order asks for, and "
                "a person decides which."
            ),
            # Priority 4, matching M9's overpayment exactly: money that does not reconcile is more
            # urgent than a re-renderable image and less urgent than a failed export integrity
            # check.
            priority=4,
        ),
        session=session,
        policy=policy,
        actor=actor,
        context=context,
        now=now,
    )


def _replayed(
    session: Session, claim: Any
) -> tuple[IncomingPaymentReceipt, GoldSaleOrder]:
    stored = claim.record.response_body or {}
    receipt = session.get(IncomingPaymentReceipt, uuid.UUID(str(stored["receipt_id"])))
    order = session.get(GoldSaleOrder, uuid.UUID(str(stored["order_id"])))
    if receipt is None or order is None:  # pragma: no cover - the record made it
        raise NotFoundError()
    return receipt, order


def _audit(
    session: Session,
    policy: RedactionPolicy,
    *,
    receipt: IncomingPaymentReceipt,
    order: GoldSaleOrder,
    match: IncomingPaymentMatch | None,
    total: int,
    note: str | None,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
    previous: dict[str, Any],
) -> None:
    """`AUD-INCOMING-001`. `incoming_payment.confirmed`, and it is catalogued.

    The entry carries **both** figures: what this confirmation added and what the order now totals.
    An entry with only the first cannot answer "was the order fully paid at this moment", which is
    the question every later reader of a partial payment asks.
    """

    AuditWriter(session, policy).record(
        AuditEntry(
            action=CONFIRM_INCOMING_PAYMENT.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="incoming_payment_receipt",
            entity_id=receipt.id,
            entity_record_version=receipt.record_version,
            previous_values=previous,
            new_values={
                "status": receipt.status,
                "confirmed_amount_irr": str(receipt.confirmed_amount_irr),
                "order_confirmed_total_irr": str(total),
                "expected_amount_irr": str(order.expected_amount_irr),
                "order_status": order.status,
                # Null when no match was named, and present either way: §8.9's first edge case is
                # evidence arriving before the statement, and an omitted field would not say
                # whether a bank row was cited or simply forgotten.
                "incoming_payment_match_id": str(match.id) if match else None,
            },
            reason=note,
            occurred_at=now,
            metadata={"operation": CONFIRM_INCOMING_PAYMENT.audit_action},
        ),
        actor=actor,
        context=context,
    )
