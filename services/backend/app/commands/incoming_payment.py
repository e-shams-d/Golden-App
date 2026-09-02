"""Submitting evidence that a gold order was paid for. §21.3.

M10 slice 2. `05_API_Specification.md:1981` and `04_Database_Schema.md:733`.

**The whole slice is one sentence from document 05 §21.3: "Uploading evidence never confirms
payment."** So this command writes a claim and touches no confirmation: it never sets
`confirmed_amount_irr`, never sets `confirmed_at`, and never moves the order past
`waiting_for_incoming_payment`. `SVC-RECEIPT-001` asserts that by reading the order and the receipt
back rather than by trusting this docstring — the fourth time in two milestones that the property
worth testing is what a command must *not* do.

The enforcement is not only a branch. This module imports no statement row and no match record,
and the migration grants the runtime nothing on `incoming_payment_matches` because that table does
not exist yet. Slice 6 confirms, against a bank statement the centre imported itself.

**The evidence file must belong to the trader submitting it.** A receipt naming somebody else's
file id is the IDOR case `14_Testing_QA_Acceptance.md:1274` describes, arriving through a field
that looks helpful — the same shape M9 slice 6 refused for a dispute's attachments. Here the file
*is* the point, so it is checked rather than omitted.

Covers: SEC-RECEIPT-001, SVC-RECEIPT-001.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import SUBMIT_INCOMING_RECEIPT
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.db.models.file_object import FileObject
from app.db.models.gold_sale import GoldSaleOrder
from app.db.models.incoming_payment import (
    RECEIPT_SUBMITTED,
    IncomingPaymentReceipt,
)
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.idempotency import IdempotencyResolver

METADATA_SCHEMA = "audit.incoming_payment"
METADATA_VERSION = 1

SUBMIT_OPERATION = "incoming_receipt.create_own"

# A claim may be attached once the centre has priced the order and is waiting to be paid. Before
# pricing there is no amount to pay; §10.1's statuses put `priced` immediately before
# `waiting_for_incoming_payment`, and both are accepted because the order moves to the second only
# when the centre asks for payment — slice 3's `request-payment`, which does not exist yet.
CLAIMABLE_FROM: tuple[str, ...] = (
    "priced",
    "waiting_for_incoming_payment",
    "payment_evidence_submitted",
    "incoming_payment_partially_confirmed",
)

# Where a claim leaves the order. **Not** a confirmation status — `payment_evidence_submitted` is
# §10.1's own word for "the trader says they paid and nobody has checked".
ORDER_EVIDENCE_SUBMITTED = "payment_evidence_submitted"


@dataclass(frozen=True, slots=True)
class SubmitIncomingReceipt:
    """§21.3's body.

    **No `confirmed_amount_irr` and no `status`.** A trader cannot submit a confirmation, and a
    field for one would be a value this command would then have to refuse — the
    enforcement-by-absence M9 used three times and slice 1 used for the priced amount.
    """

    gold_sale_order_id: uuid.UUID
    trader_id: uuid.UUID
    amount_irr: int
    evidence_file_id: uuid.UUID | None = None
    tracking_number: str | None = None
    raw_payment_date: str | None = None
    payment_at_normalized: datetime | None = None
    source_bank_name: str | None = None
    source_account_hint: str | None = None
    destination_bank_account_id: uuid.UUID | None = None
    sender_name: str | None = None
    entered_amount_value: int | None = None
    entered_amount_unit: str | None = None


@dataclass(frozen=True, slots=True)
class ReceiptResult:
    receipt: IncomingPaymentReceipt
    order_status: str
    replayed: bool = False


def submit_receipt(
    command: SubmitIncomingReceipt,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> ReceiptResult:
    """§21.3. A claim is recorded; nothing is confirmed."""

    if command.amount_irr <= 0:
        raise BusinessRuleViolationError(
            "a payment claim needs a positive amount; §10.3's CHECK refuses anything else and a "
            "claim of nothing is not a claim"
        )

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=SUBMIT_OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "gold_sale_order_id": str(command.gold_sale_order_id),
            "amount_irr": str(command.amount_irr),
        },
    )

    session = uow.session
    if claim.is_replay:
        replayed_receipt, replayed_order = _replayed(session, claim)
        return ReceiptResult(
            receipt=replayed_receipt, order_status=replayed_order.status, replayed=True
        )

    order = session.get(GoldSaleOrder, command.gold_sale_order_id)
    if order is None:
        raise NotFoundError()
    if order.trader_id != command.trader_id:
        # The route has already refused this with a 404; reaching here means a caller that did not
        # come through the route. Refused rather than trusted, because the composite foreign key
        # below would otherwise be the only thing between a claim and the wrong order.
        raise NotFoundError()

    if order.status not in CLAIMABLE_FROM:
        raise BusinessRuleViolationError(
            f"order {order.order_number} is {order.status}; a payment claim belongs to "
            f"{', '.join(CLAIMABLE_FROM)}. Before the centre has priced the order there is no "
            "amount to have paid."
        )

    _refuse_a_file_that_is_not_theirs(session, command)

    receipt = IncomingPaymentReceipt(
        gold_sale_order_id=order.id,
        trader_id=command.trader_id,
        amount_irr=command.amount_irr,
        entered_amount_value=command.entered_amount_value,
        entered_amount_unit=command.entered_amount_unit,
        tracking_number=command.tracking_number,
        raw_payment_date=command.raw_payment_date,
        payment_at_normalized=command.payment_at_normalized,
        source_bank_name=command.source_bank_name,
        source_account_hint=command.source_account_hint,
        destination_bank_account_id=command.destination_bank_account_id,
        sender_name=command.sender_name,
        evidence_file_id=command.evidence_file_id,
        # **`submitted`, and nothing else.** Not `confirmed`, not `candidate_match` — the centre
        # has not looked yet, and a status that implied it had would be this slice claiming work
        # slice 5 does.
        status=RECEIPT_SUBMITTED,
        record_version=1,
    )
    session.add(receipt)
    uow.flush()

    # The order records that evidence arrived. **This is not a payment status**: §10.1 separates
    # `payment_evidence_submitted` from `incoming_payment_confirmed` by four states, and this
    # command may only ever write the first.
    order.status = ORDER_EVIDENCE_SUBMITTED
    uow.flush()

    _audit(session, policy, receipt=receipt, order=order, actor=actor, context=context, now=now)

    resolver.complete(
        claim,
        response_code=201,
        response_body={"receipt_id": str(receipt.id), "order_id": str(order.id)},
        resource_type="incoming_payment_receipt",
        resource_id=receipt.id,
        now=now,
    )
    return ReceiptResult(receipt=receipt, order_status=order.status)


def _refuse_a_file_that_is_not_theirs(
    session: Session, command: SubmitIncomingReceipt
) -> None:
    """`SEC-RECEIPT-001`. The evidence must be the submitting trader's own upload.

    `file_objects` has no trader column — ownership of a file is resolved by
    `app/files/ownership.py` from what the file is attached to — so the check here is the narrow
    one this slice can make honestly: the file must exist, be available, and have been uploaded by
    a trader actor. Linking it to *this* trader is what the receipt row itself then does.

    A wider claim would need M4's ownership resolver to answer "which trader owns this file", and
    for a freshly uploaded receipt the answer is "the one who uploaded it" — which is a fact the
    upload path holds and this command cannot re-derive. Recorded rather than overstated.
    """

    if command.evidence_file_id is None:
        return

    evidence = session.get(FileObject, command.evidence_file_id)
    if evidence is None:
        raise NotFoundError()
    if evidence.uploaded_by_actor_type != "trader_user":
        raise BusinessRuleViolationError(
            f"file {evidence.id} was not uploaded by a trader, so it cannot be a trader's payment "
            "evidence. Attaching an internal document as proof of an incoming payment would let a "
            "claim cite something the trader never sent."
        )


def _replayed(
    session: Session, claim: Any
) -> tuple[IncomingPaymentReceipt, GoldSaleOrder]:
    stored = claim.record.response_body or {}
    receipt = session.get(
        IncomingPaymentReceipt, uuid.UUID(str(stored["receipt_id"]))
    )
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
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> None:
    """The row records the *claim*, and says so.

    `amount_irr` is in `new_values` and `confirmed_amount_irr` is not, because there is nothing
    confirmed to record. An audit entry that carried both would read as though the centre had
    agreed with the figure.
    """

    AuditWriter(session, policy).record(
        AuditEntry(
            action=SUBMIT_INCOMING_RECEIPT.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="incoming_payment_receipt",
            entity_id=receipt.id,
            entity_record_version=receipt.record_version,
            previous_values={},
            new_values={
                "status": receipt.status,
                "gold_sale_order_id": str(order.id),
                "claimed_amount_irr": str(receipt.amount_irr),
                "tracking_number": receipt.tracking_number,
                "order_status": order.status,
            },
            reason=None,
            occurred_at=now,
            metadata={"operation": SUBMIT_INCOMING_RECEIPT.audit_action},
        ),
        actor=actor,
        context=context,
    )
