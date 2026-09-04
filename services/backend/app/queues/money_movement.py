"""The accountant's queues over batches, exports, attempts, bundles, receipts and tasks.
`15_Agent_Implementation_Plan.md:1262`.

M11 slice 3. Seven of §19.2's eleven, over six tables that M6 to M10 built. **No new table, no new
column, no new command and no new permission** — every row these return was written by an earlier
milestone, and the work here is deciding which states each queue names.

Grouped in one module because they share a shape: a status filter over an aggregate the accountant
already has a read grant for. The four request queues live next door in `payment_requests.py`
because they share a *predicate problem* — telling a first submission from a resubmission — that
none of these have.

**Every state value is named from `status_catalog.yaml`, not from the code that writes it.** The
catalogue is what M0 approved; a queue built from a constant somebody typed is a queue that agrees
with the implementation and not with the decision.
"""

from __future__ import annotations

from sqlalchemy import Select

from app.db.models.bank_export import BankExcelExport
from app.db.models.bank_result_bundle import BankResultBundle
from app.db.models.incoming_payment import IncomingPaymentReceipt
from app.db.models.manual_review_task import ManualReviewTask
from app.db.models.payment_batch import PaymentAttempt, PaymentBatchVersion
from app.db.pagination import ListSpec, SortField
from app.queues.contract import QueueDefinition, QueueRow
from app.security.actor import ActorContext

# --- `payment_batch_version`, `06_Workflows_and_State_Machines.md:770-903` -----------------
VERSION_DRAFT = "draft"
VERSION_REJECTED = "rejected"

# --- `bank_export`, `:914-970` -------------------------------------------------------------
EXPORT_VALIDATED = "validated"
EXPORT_DOWNLOADED = "downloaded"

# --- `payment_attempt`, `:658-748` ---------------------------------------------------------
ATTEMPT_SENT = "sent_to_bank"
ATTEMPT_RESULT_PENDING = "bank_result_pending"
ATTEMPT_FAILED = "failed"
ATTEMPT_RETRY_REQUIRED = "retry_required"

# --- `bank_result_bundle`, `:976-1013` -----------------------------------------------------
BUNDLE_READY_FOR_REVIEW = "ready_for_manual_review"
BUNDLE_PARTIALLY_MATCHED = "partially_matched"

# --- `incoming_payment_receipt`, `:404-439` ------------------------------------------------
RECEIPT_NEEDS_REVIEW = "needs_review"
RECEIPT_DUPLICATE_SUSPECTED = "duplicate_suspected"

# --- `manual_review_task`, `:1225-1261` ----------------------------------------------------
TASK_OPEN = "open"
TASK_IN_PROGRESS = "in_progress"
# §19.2 says "reconciliation tasks" and `manual_review_task.task_type` has no value spelled
# `reconciliation`. These two are the reconciliation work the catalogue actually holds: a published
# result that does not reconcile with what the bank reported, and an incoming payment that does not
# reconcile with the order it claims to pay. Both were *added* to `TASK_TYPES` by the milestone that
# needed them, and neither is a general-purpose review type.
#
# Recorded as the plan's G-7 rather than settled here: if the owner means something wider by
# "reconciliation", this queue gains types rather than changing shape.
RECONCILIATION_TASK_TYPES = ("payment_result_discrepancy", "incoming_payment_discrepancy")


def _internal[T](statement: Select[tuple[T]], actor: ActorContext) -> Select[tuple[T]]:
    """None of these queues consults the actor.

    Every permission below goes to internal roles only, so there is no trader who could be scoped
    and a `scoped()` call would be a filter that never fires. Written once and shared, so the claim
    is made in one place instead of seven — and so a queue that *does* need scoping has to say so
    by not using this.
    """

    del actor
    return statement


# --- Batch versions ------------------------------------------------------------------------


def _draft_or_rejected(
    statement: Select[tuple[PaymentBatchVersion]], actor: ActorContext
) -> Select[tuple[PaymentBatchVersion]]:
    """§19.2's "draft/invalid batch versions".

    `draft` is a version being prepared; `rejected` is one a manager sent back. Both are the
    accountant's to act on, and both are the *version* aggregate rather than the batch — a batch's
    `approval_invalidated` is a derived state about the batch's current version, and filtering on it
    would return the batch rather than the version somebody has to rebuild.

    `ready_for_approval` and `approved` are excluded: they are the manager's queue, which slice 4
    builds. `superseded` is excluded because it is terminal history.
    """

    return _internal(statement, actor).where(
        PaymentBatchVersion.status.in_((VERSION_DRAFT, VERSION_REJECTED))
    )


def _render_version(row: PaymentBatchVersion) -> QueueRow:
    # `reference` is the version number rather than the batch number, which lives on the parent and
    # would need a join this contract deliberately does not do — a per-row lazy load would be an
    # N+1 inside an open transaction, which `test_no_io_under_lock.py` exists to catch. The `id`
    # identifies the row; the detail route carries the batch.
    return QueueRow(
        id=row.id,
        reference=f"v{row.version_number}",
        status=row.status,
        created_at=row.created_at,
    )


DRAFT_INVALID_BATCH_VERSIONS: QueueDefinition[PaymentBatchVersion] = QueueDefinition(
    name="draft-invalid-batch-versions",
    permission="payment_batch.read",
    spec=ListSpec(
        sorts=(
            SortField("created_at", PaymentBatchVersion.created_at),
            SortField("id", PaymentBatchVersion.id, unique=True),
        ),
        default_sort="created_at",
    ),
    predicate=_draft_or_rejected,
    source="15_Agent_Implementation_Plan.md:1265",
    entity=PaymentBatchVersion,
    render=_render_version,
)


# --- Exports -------------------------------------------------------------------------------


def _awaiting_manual_send(
    statement: Select[tuple[BankExcelExport]], actor: ActorContext
) -> Select[tuple[BankExcelExport]]:
    """§19.2's "approved exports awaiting manual send".

    **Three conditions, and the third is the one that matters.** A final export that is `validated`
    or `downloaded` still has to be carried to the bank by a person; `sent_to_bank_marked_at IS
    NULL` is what says nobody has. M7 slice 4's rule — "downloading does not mean sent" — is exactly
    this: without the timestamp condition, an export somebody downloaded would leave the queue while
    the money had not moved.

    `preview` exports are excluded by type, not by status: a preview is unsendable by construction
    (`bank_excel_exports` was given no grant that could promote one), so a preview in this queue
    would be work nobody could do.
    """

    return (
        _internal(statement, actor)
        .where(BankExcelExport.export_type == "final")
        .where(BankExcelExport.status.in_((EXPORT_VALIDATED, EXPORT_DOWNLOADED)))
        .where(BankExcelExport.sent_to_bank_marked_at.is_(None))
    )


def _render_export(row: BankExcelExport) -> QueueRow:
    return QueueRow(
        id=row.id,
        reference=row.export_number,
        status=row.status,
        created_at=row.created_at,
    )


APPROVED_EXPORTS_AWAITING_SEND: QueueDefinition[BankExcelExport] = QueueDefinition(
    name="approved-exports-awaiting-send",
    permission="bank_export.read",
    spec=ListSpec(
        sorts=(
            SortField("created_at", BankExcelExport.created_at),
            SortField("id", BankExcelExport.id, unique=True),
        ),
        default_sort="created_at",
    ),
    predicate=_awaiting_manual_send,
    source="15_Agent_Implementation_Plan.md:1266",
    entity=BankExcelExport,
    render=_render_export,
)


# --- Attempts ------------------------------------------------------------------------------


def _awaiting_bank_result(
    statement: Select[tuple[PaymentAttempt]], actor: ActorContext
) -> Select[tuple[PaymentAttempt]]:
    """§19.2's "sent attempts awaiting result".

    Two states rather than one, and the catalogue explains why: its own note records that
    `payment_request.sent_to_bank` and `payment_attempt.bank_result_pending` "are two different
    facts and stay separate". At the attempt level both mean the same thing to an accountant —
    the money left and the bank has not said what happened — so both belong here.
    """

    return _internal(statement, actor).where(
        PaymentAttempt.status.in_((ATTEMPT_SENT, ATTEMPT_RESULT_PENDING))
    )


def _needs_a_decision(
    statement: Select[tuple[PaymentAttempt]], actor: ActorContext
) -> Select[tuple[PaymentAttempt]]:
    """§19.2's "failed/partial/retry-required payments".

    `failed` and `retry_required` are attempt states. **"Partial" is not**: `partially_resolved` is
    a *batch* state meaning some attempts are terminal and others are not, and a batch in it
    contains attempts already in the two states named here. Including the batch would put the same
    work in the queue twice under two identities, so the queue is the attempts, which is what a
    person acts on.

    `superseded` is excluded: a retry that replaced this attempt already carries the work.
    """

    return _internal(statement, actor).where(
        PaymentAttempt.status.in_((ATTEMPT_FAILED, ATTEMPT_RETRY_REQUIRED))
    )


def _render_attempt(row: PaymentAttempt) -> QueueRow:
    return QueueRow(
        id=row.id,
        reference=f"attempt-{row.attempt_number}",
        status=row.status,
        created_at=row.created_at,
    )


def _attempt_spec() -> ListSpec:
    return ListSpec(
        sorts=(
            SortField("created_at", PaymentAttempt.created_at),
            SortField("id", PaymentAttempt.id, unique=True),
        ),
        default_sort="created_at",
    )


SENT_ATTEMPTS_AWAITING_RESULT: QueueDefinition[PaymentAttempt] = QueueDefinition(
    name="sent-attempts-awaiting-result",
    permission="payment_attempt.read",
    spec=_attempt_spec(),
    predicate=_awaiting_bank_result,
    source="15_Agent_Implementation_Plan.md:1267",
    entity=PaymentAttempt,
    render=_render_attempt,
)

FAILED_PARTIAL_RETRY_PAYMENTS: QueueDefinition[PaymentAttempt] = QueueDefinition(
    name="failed-partial-retry-payments",
    permission="payment_attempt.read",
    spec=_attempt_spec(),
    predicate=_needs_a_decision,
    source="15_Agent_Implementation_Plan.md:1269",
    entity=PaymentAttempt,
    render=_render_attempt,
)


# --- Bundles -------------------------------------------------------------------------------


def _unresolved_bundle(
    statement: Select[tuple[BankResultBundle]], actor: ActorContext
) -> Select[tuple[BankResultBundle]]:
    """§19.2's "unresolved bundles/segments".

    `ready_for_manual_review` is a bundle whose automatic matching left work; `partially_matched`
    is one where some of it was done. `processing` is excluded — a job is running and there is
    nothing for a person to do yet — and so are `matched`, `closed`, `failed` and `voided`, which
    are answered.
    """

    return _internal(statement, actor).where(
        BankResultBundle.status.in_((BUNDLE_READY_FOR_REVIEW, BUNDLE_PARTIALLY_MATCHED))
    )


def _render_bundle(row: BankResultBundle) -> QueueRow:
    return QueueRow(
        id=row.id,
        reference=row.bundle_number,
        status=row.status,
        created_at=row.created_at,
    )


UNRESOLVED_BUNDLES_SEGMENTS: QueueDefinition[BankResultBundle] = QueueDefinition(
    name="unresolved-bundles-segments",
    permission="bank_result_bundle.read",
    spec=ListSpec(
        sorts=(
            SortField("created_at", BankResultBundle.created_at),
            SortField("id", BankResultBundle.id, unique=True),
        ),
        default_sort="created_at",
    ),
    predicate=_unresolved_bundle,
    source="15_Agent_Implementation_Plan.md:1268",
    entity=BankResultBundle,
    render=_render_bundle,
)


# --- Incoming receipts ---------------------------------------------------------------------


def _receipt_needs_a_person(
    statement: Select[tuple[IncomingPaymentReceipt]], actor: ActorContext
) -> Select[tuple[IncomingPaymentReceipt]]:
    """§19.2's "incoming receipts/statements requiring review".

    `needs_review` is the catalogue's own "manual resolution is required". `duplicate_suspected` is
    included because the catalogue calls it a *warning* state that "does not reject or confirm
    automatically" — which is to say it waits for a person, which is what a queue is.

    `candidate_match` is excluded: candidates exist and the centre has not been asked to choose.
    `waiting_for_bank_statement` is excluded because the thing it waits for is a bank, not a
    person.
    """

    return _internal(statement, actor).where(
        IncomingPaymentReceipt.status.in_((RECEIPT_NEEDS_REVIEW, RECEIPT_DUPLICATE_SUSPECTED))
    )


def _render_receipt(row: IncomingPaymentReceipt) -> QueueRow:
    return QueueRow(
        id=row.id,
        # A receipt's own identifier is the tracking number the trader typed, which is nullable —
        # §8.9 admits evidence before a statement exists. Falling back to the id keeps the field
        # non-null without inventing a number nobody can look up.
        reference=row.tracking_number or str(row.id),
        status=row.status,
        created_at=row.created_at,
        trader_id=row.trader_id,
    )


INCOMING_RECEIPTS_REQUIRING_REVIEW: QueueDefinition[IncomingPaymentReceipt] = QueueDefinition(
    name="incoming-receipts-requiring-review",
    # `incoming_payment.match` rather than a read permission, because the catalogue has none for
    # this aggregate. It is the accountant's grant for working incoming payments, and it is what
    # `app/api/v1/incoming_matches.py` already guards the receipt's own reads with — so the queue
    # is reachable by exactly the people who can act on what it returns.
    permission="incoming_payment.match",
    spec=ListSpec(
        sorts=(
            SortField("created_at", IncomingPaymentReceipt.created_at),
            SortField("id", IncomingPaymentReceipt.id, unique=True),
        ),
        filters=frozenset({"trader_id"}),
        default_sort="created_at",
    ),
    predicate=_receipt_needs_a_person,
    source="15_Agent_Implementation_Plan.md:1270",
    filter_columns={"trader_id": IncomingPaymentReceipt.trader_id},
    entity=IncomingPaymentReceipt,
    render=_render_receipt,
)


# --- Reconciliation tasks ------------------------------------------------------------------


def _open_reconciliation(
    statement: Select[tuple[ManualReviewTask]], actor: ActorContext
) -> Select[tuple[ManualReviewTask]]:
    """§19.2's "reconciliation tasks".

    `open` and `in_progress` are the catalogue's two non-terminal task states. `in_progress` is
    included deliberately: unlike a request under review, a task carries its assignee in a field,
    so a person can tell their own started work from somebody else's — and excluding it would hide
    work that is genuinely outstanding.
    """

    return (
        _internal(statement, actor)
        .where(ManualReviewTask.task_type.in_(RECONCILIATION_TASK_TYPES))
        .where(ManualReviewTask.status.in_((TASK_OPEN, TASK_IN_PROGRESS)))
    )


def _render_task(row: ManualReviewTask) -> QueueRow:
    return QueueRow(
        id=row.id,
        reference=row.task_type,
        status=row.status,
        created_at=row.created_at,
    )


RECONCILIATION_TASKS: QueueDefinition[ManualReviewTask] = QueueDefinition(
    name="reconciliation-tasks",
    permission="manual_review.read",
    spec=ListSpec(
        sorts=(
            SortField("created_at", ManualReviewTask.created_at),
            SortField("id", ManualReviewTask.id, unique=True),
        ),
        filters=frozenset({"task_type"}),
        default_sort="created_at",
    ),
    predicate=_open_reconciliation,
    source="15_Agent_Implementation_Plan.md:1272",
    filter_columns={"task_type": ManualReviewTask.task_type},
    entity=ManualReviewTask,
    render=_render_task,
)
