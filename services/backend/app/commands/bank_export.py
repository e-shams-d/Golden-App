"""Generating a bank file, and refusing to record one that does not exist.

M7 slices 2 and 3. `bank_export.generate_preview` and `bank_export.generate_final`, and the order
of operations that `FINANCIAL_INTEGRITY_BASELINE.md` §1 dictates.

**§1 is a sequence, not a set of fields.** "A final artifact record is inserted **only after the
file exists** and its size, media type, SHA-256, row count, total and provenance are verified. No
placeholder file, hash or timestamp is permitted." So this command renders the bytes, writes them,
**reads back what storage measured**, and only then inserts a row. The row's `file_sha256_hash` is
the digest storage computed while the bytes went past — not one this process calculated in memory
and hoped matched.

A failure anywhere before the insert leaves a file in storage that no row references. That is the
correct residual: an orphan object costs disk and is reconcilable
(`app/storage/reconciliation.py` exists for it), while an orphan *record* is a claim that a file
exists which nobody can produce — and this system's whole purpose is to answer "which exact file
went to the bank".

**Preview and final share this module and will not share a command.** `command_catalog.yaml` gives
them separate ids, separate permissions and different concurrency; §1 forbids promoting one into
the other. What they share is the renderer and the storage sequence, and those are functions here
rather than a single command with a `type` parameter — a parameter is exactly how a preview
becomes a final artifact by accident.

**Only the final export locks.** `LockScope.EXPORT_GENERATE_FINAL` had been reserved in
`app/db/locking.py` since M2 with nothing calling it — the tenth mechanism this project has found
in that state — and `generate_final` is its first caller. A preview races nothing: it writes no
version state, holds no uniqueness, and two concurrent previews of one version are two files,
which is what `uq_active_final_export_per_version`'s predicate deliberately permits by excluding
previews. A final export races everything, and the index is what finally decides.

**The difference between the two commands is what must be true first**, not what they write.
A preview asks for nothing; a final export asks for an approval of the exact version, a version
still `approved` rather than superseded, and the eight comparisons of §15.5 holding — after the
row exists, because a mismatch is quarantined rather than refused.

Covers: SVC-EXPORT-001, SVC-EXPORT-002, AUD-EXPORT-001, SVC-EXPORT-005, SVC-INTEGRITY-002,
CON-EXPORT-001, AUD-EXPORT-002.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.outbox import OutboxMessage, OutboxWriter
from app.audit.redaction import RedactionPolicy
from app.audit.registry import (
    GENERATE_EXPORT_PREVIEW,
    GENERATE_FINAL_EXPORT,
    MARK_EXPORT_SENT,
    QUARANTINE_EXPORT_ON_INTEGRITY_FAILURE,
)
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.commands.manual_review_task import OpenTask as OpenReviewTask
from app.commands.manual_review_task import open_task as open_review_task
from app.core.errors import BusinessRuleViolationError, ConflictError, NotFoundError
from app.core.time import to_business_time
from app.db.locking import LockScope, LockTarget, lock_rows
from app.db.models.bank_export import EXPORT_FINAL, EXPORT_PREVIEW, BankExcelExport
from app.db.models.file_object import CLEAN_SCAN_STATUS, FileObject
from app.db.models.manual_review_task import ENTITY_BANK_EXPORT, TASK_TYPE_EXPORT_INTEGRITY
from app.db.models.payment_batch import (
    BatchApproval,
    PaymentBatch,
    PaymentBatchItem,
    PaymentBatchVersion,
)
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.exports.excel import ExportRow, render_bank_file
from app.exports.integrity import IntegrityFacts, IntegrityFailure, failed_checks
from app.files.download import measure_now
from app.idempotency import IdempotencyResolver
from app.storage.interface import StorageBackend, StoredObject
from app.storage.keys import generate_storage_key

METADATA_SCHEMA = "payment_batch_command"
METADATA_VERSION = 1

PREVIEW_OPERATION = "bank_export.generate_preview"
FINAL_OPERATION = "bank_export.generate_final"
MARK_SENT_OPERATION = "bank_export.mark_sent"

PAYLOAD_VERSION = 1

# What `batch_approvals.decision` and `payment_batch_versions.status` must say before a final
# export may exist. Both are checked, and they answer different questions: the decision says a
# manager approved, the status says that approval is still the operational one — slice 5A made a
# replaced version `superseded` while leaving its approval row exactly as the manager left it.
DECISION_APPROVED = "approved"
VERSION_APPROVED = "approved"

# `file_purpose_catalog.yaml` lists seven purposes and every one of them describes what a caller
# may **upload**. A generated export is not an upload, so it has no purpose there — and this is
# deliberately *not* solved by borrowing `misc_internal`, which would make a bank file
# indistinguishable from a stray attachment in every query that groups by category.
#
# The consequence is a good one and is asserted rather than assumed: `ownership.may_access`
# returns `False` for a category with no resolver, so an export file is unreachable through the
# generic `/files/{id}` surface by construction. It becomes reachable in slice 4, through
# `bank_export.download`, which is the only route document 05 gives it.
EXPORT_FILE_CATEGORY = "bank_export"

# `05_API_Specification.md:1476` — the artifact is an xlsx.
EXPORT_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# §11.8's `status` for a freshly written artifact. `generating` is the state of a *job* that has
# not finished; this command finishes synchronously, so the row is born `generated`. Slice 3's
# asynchronous final export is what will use `generating`, and using it here would make the
# status mean "in progress" in one place and "done" in another.
STATUS_GENERATED = "generated"

# `validated` is `generated` plus "the eight checks held". A final export reaches it in the same
# transaction that wrote it, because §15.5's checks run before the row is returned — so a caller
# never sees a final export whose integrity is unknown.
STATUS_VALIDATED = "validated"

# Where a failed check puts it. §15.5: "A mismatch quarantines the export". The row is kept —
# quarantine is evidence, not deletion — and `uq_active_final_export_per_version`'s predicate
# excludes this status, so a quarantined export does not block the next attempt.
STATUS_QUARANTINED = "quarantined"

# `15_Agent_Implementation_Plan.md:989`: "Downloading does not mean sent." Two separate statuses
# for two separate facts, and the gap between them is the milestone's central human-factors risk.
STATUS_DOWNLOADED = "downloaded"
STATUS_SENT = "sent_to_bank_marked"

# The container follows. `status_catalog.yaml` marks nine of eleven `payment_batch` states
# `derived: true`, so this is a projection rather than an independent decision.
BATCH_SENT = "sent_to_bank"

# `file_objects.storage_status`. The bytes are on disk before the row exists, so `available` is
# the only honest value — anything else would describe a file that is in fact there.
AVAILABLE_STORAGE_STATUS = "available"


@dataclass(frozen=True, slots=True)
class GeneratePreview:
    """`05_API_Specification.md:1466-1472`. No body beyond the target."""

    payment_batch_id: uuid.UUID
    payment_batch_version_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ExportResult:
    export: BankExcelExport
    file: FileObject
    replayed: bool = False


def generate_preview(
    command: GeneratePreview,
    *,
    uow: SqlAlchemyUnitOfWork,
    storage: StorageBackend,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> ExportResult:
    """Render this version, store it, and record it — in that order.

    A preview may be generated from any version at any point in its life, including a draft.
    `05_API_Specification.md:1478` says so: "Preview may be generated before approval". The whole
    point of a preview is to look at what the file *would* be before committing to it, and a
    guard that required `ready_for_approval` would remove the only moment it is useful.
    """

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=PREVIEW_OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "payment_batch_id": str(command.payment_batch_id),
            "payment_batch_version_id": str(command.payment_batch_version_id),
        },
    )

    session = uow.session
    if claim.is_replay:
        return _replayed(session, claim.record.response_body or {})

    batch = session.get(PaymentBatch, command.payment_batch_id)
    if batch is None:
        raise NotFoundError()

    version = session.get(PaymentBatchVersion, command.payment_batch_version_id)
    if version is None or version.payment_batch_id != batch.id:
        raise NotFoundError()

    items = list(
        session.scalars(
            select(PaymentBatchItem)
            .where(PaymentBatchItem.payment_batch_version_id == version.id)
            .order_by(PaymentBatchItem.row_order)
        )
    )
    if not items:  # pragma: no cover - `ck_payment_batch_versions_row_count` refuses one
        raise BusinessRuleViolationError(
            f"version {version.version_number} has no rows, so there is nothing to render"
        )

    payload = render_bank_file([_row_of(item) for item in items])

    # Both derived once. The number is read from a count, so calling it twice could return two
    # different values and put one number in the filename and another in the row.
    export_number = _export_number(session, now)
    key = generate_storage_key(category=EXPORT_FILE_CATEGORY, moment=now)

    # **The write happens before the row, and the row uses what the write measured.** §1's "only
    # after the file exists" is this line ordering, and `stored.sha256_hash` is storage's own
    # digest of the bytes it received — not a hash of `payload` computed here, which would agree
    # with itself even if the write had truncated.
    stored = storage.write(key, io.BytesIO(payload))
    if stored.size_bytes != len(payload):
        raise BusinessRuleViolationError(
            f"storage recorded {stored.size_bytes} bytes for an export of {len(payload)}; "
            "no record is written for a file that does not match what was rendered"
        )

    file_record = _file_record_for(
        key=key, export_number=export_number, stored=stored, version=version, actor=actor
    )
    session.add(file_record)
    uow.flush()

    export = BankExcelExport(
        payment_batch_version_id=version.id,
        # NULL, and the CHECK is what makes that true for a preview rather than this line.
        batch_approval_id=None,
        bank_profile_version_id=version.bank_profile_version_id,
        bank_mapping_id=version.bank_mapping_id,
        file_id=file_record.id,
        export_number=export_number,
        export_type=EXPORT_PREVIEW,
        row_count=len(items),
        total_amount_irr=sum(item.amount_irr for item in items),
        content_hash=version.content_hash,
        file_sha256_hash=stored.sha256_hash,
        status=STATUS_GENERATED,
        generated_by_admin_user_id=_generator(actor),
        generated_at=now,
    )
    session.add(export)
    uow.flush()

    _audit(session, policy, batch=batch, version=version, export=export, actor=actor,
           context=context, now=now)

    resolver.complete(
        claim,
        response_code=201,
        response_body={"export_id": str(export.id), "file_id": str(file_record.id)},
        resource_type="bank_excel_export",
        resource_id=export.id,
        now=now,
    )

    return ExportResult(export=export, file=file_record)


@dataclass(frozen=True, slots=True)
class GenerateFinal:
    """`05_API_Specification.md:1475-1490`. Same target as a preview, different authority."""

    payment_batch_id: uuid.UUID
    payment_batch_version_id: uuid.UUID


class IntegrityRefused(ConflictError):
    """The eight checks did not hold, and the export has been quarantined.

    `05_API_Specification.md:1514` gives this `409 EXPORT_INTEGRITY_MISMATCH`. Its own type
    because the route must be able to tell it from every other 409 and because the failed checks
    travel with it — an accountant who is told *which* equality broke can act; one told
    "conflict" opens a ticket.
    """

    def __init__(self, failures: tuple[IntegrityFailure, ...]) -> None:
        super().__init__(
            "the export failed its integrity checks and has been quarantined: "
            + "; ".join(failure.describe() for failure in failures)
        )
        self.failures = failures


def generate_final(
    command: GenerateFinal,
    *,
    uow: SqlAlchemyUnitOfWork,
    storage: StorageBackend,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> ExportResult:
    """Render the approved version as the file that will go to a bank.

    **The difference from a preview is not the bytes — it is what must be true first.**
    `command_catalog.yaml:192` lists three preconditions: `valid_exact_version_approval`,
    `content_hash_matches`, `mapping_and_source_account_match`. A preview asks for none of them,
    because a preview authorises nothing.

    **The lock, and its first caller.** `LockScope.EXPORT_GENERATE_FINAL = 400` has been in
    `app/db/locking.py` since M2 with nothing calling it — the tenth mechanism this project has
    found in that state, and the second one M7 has given a caller. `CON-EXPORT-001` needs it:
    two concurrent generations must produce one file, and `uq_active_final_export_per_version`
    is what finally decides, with the lock making the ordinary case wait rather than race to a
    constraint violation.

    **A mismatch quarantines rather than refusing.** §15.5: "A mismatch quarantines the export
    and creates a high-priority task/security event." So the row is written, moved to
    `quarantined`, recorded — and *then* the caller is refused. Refusing without writing would
    lose the evidence that something disagreed, which is the one artifact an investigation needs.
    """

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=FINAL_OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "payment_batch_id": str(command.payment_batch_id),
            "payment_batch_version_id": str(command.payment_batch_version_id),
        },
    )

    session = uow.session
    if claim.is_replay:
        # `CON-EXPORT-001`'s second half: "a timeout after commit returns the stored result
        # rather than generating a second file".
        return _replayed(session, claim.record.response_body or {})

    lock_rows(
        session,
        [
            LockTarget.of(
                LockScope.EXPORT_GENERATE_FINAL, PaymentBatch, command.payment_batch_id
            ),
            LockTarget.of(
                LockScope.EXPORT_GENERATE_FINAL,
                PaymentBatchVersion,
                command.payment_batch_version_id,
            ),
        ],
        models={
            PaymentBatch.__tablename__: PaymentBatch,
            PaymentBatchVersion.__tablename__: PaymentBatchVersion,
        },
    )

    batch = session.get(PaymentBatch, command.payment_batch_id)
    if batch is None:
        raise NotFoundError()
    version = session.get(PaymentBatchVersion, command.payment_batch_version_id)
    if version is None or version.payment_batch_id != batch.id:
        raise NotFoundError()

    # `SVC-EXPORT-005`. An approval, for this exact version, that says `approved`.
    approval = session.scalar(
        select(BatchApproval).where(BatchApproval.payment_batch_version_id == version.id)
    )
    if approval is None:
        raise BusinessRuleViolationError(
            f"version {version.version_number} has no approval; a final export exists only for "
            "an approved version"
        )
    if approval.decision != DECISION_APPROVED:
        raise BusinessRuleViolationError(
            f"version {version.version_number} was {approval.decision}, so no file may be "
            "generated for it"
        )
    if version.status != VERSION_APPROVED:
        # The approval exists but the version has moved on — superseded by a replacement, most
        # likely. Slice 5A made the approval historical; this is the half that stops a historical
        # approval producing a file.
        raise BusinessRuleViolationError(
            f"version {version.version_number} is {version.status!r}; an approval that is no "
            "longer operational cannot produce a final export"
        )

    items = list(
        session.scalars(
            select(PaymentBatchItem)
            .where(PaymentBatchItem.payment_batch_version_id == version.id)
            .order_by(PaymentBatchItem.row_order)
        )
    )

    payload = render_bank_file([_row_of(item) for item in items])

    export_number = _export_number(session, now)
    key = generate_storage_key(category=EXPORT_FILE_CATEGORY, moment=now)
    stored = storage.write(key, io.BytesIO(payload))

    file_record = _file_record_for(
        key=key, export_number=export_number, stored=stored, version=version, actor=actor
    )
    session.add(file_record)
    uow.flush()

    export = BankExcelExport(
        payment_batch_version_id=version.id,
        # NOT NULL for a final export, and `ck_bank_excel_exports_approval_matches_type` plus
        # `fk_export_approval_same_version` between them make it impossible for this to name an
        # approval of a different version.
        batch_approval_id=approval.id,
        bank_profile_version_id=version.bank_profile_version_id,
        bank_mapping_id=version.bank_mapping_id,
        file_id=file_record.id,
        export_number=export_number,
        export_type=EXPORT_FINAL,
        row_count=len(items),
        total_amount_irr=sum(item.amount_irr for item in items),
        content_hash=version.content_hash,
        file_sha256_hash=stored.sha256_hash,
        status=STATUS_GENERATED,
        generated_by_admin_user_id=_generator(actor),
        generated_at=now,
    )
    session.add(export)
    try:
        uow.flush()
    except IntegrityError as error:
        # `CON-EXPORT-001`. The lock above makes the ordinary race wait, but a caller who simply
        # asks twice — or two requests that arrived before either committed — reach the index,
        # and the index is what actually decides. Translated to the catalogued 409 rather than
        # surfacing a driver error, so a client is told the thing that is true: this version
        # already has a final export somebody could send.
        if _violated_constraint(error) != "uq_active_final_export_per_version":
            raise
        uow.rollback()
        raise ConflictError(
            f"version {version.version_number} already has an active final export; a second "
            "would be a second file that could be sent for the same payments"
        ) from None

    failures = failed_checks(
        # Measured through the file service, so this module never learns where the bytes are.
        # Re-read rather than reused from the write above, which is the eighth check's whole
        # purpose: it exists to catch a file that changed after it was recorded, and reusing the
        # write's own digest would compare a number against itself.
        _facts_for(
            export,
            version=version,
            approval=approval,
            measured=measure_now(storage, file_record) or "",
        )
    )
    if failures:
        _quarantine(
            session, policy, batch=batch, export=export, failures=failures, actor=actor,
            context=context, now=now,
        )
        raise IntegrityRefused(failures)

    export.status = STATUS_VALIDATED

    _audit_final(
        session, policy, batch=batch, version=version, export=export, approval=approval,
        actor=actor, context=context, now=now,
    )

    resolver.complete(
        claim,
        response_code=201,
        response_body={"export_id": str(export.id), "file_id": str(file_record.id)},
        resource_type="bank_excel_export",
        resource_id=export.id,
        now=now,
    )

    return ExportResult(export=export, file=file_record)


@dataclass(frozen=True, slots=True)
class MarkSent:
    """`05_API_Specification.md:1516-1530`. An **export** id, not a batch id.

    `15_Agent_Implementation_Plan.md:978`: "Mark sent acts on an exact `BankExcelExport`, not a
    generic batch." The distinction is the milestone's: a batch may have had several versions and
    several exports, and only one of them was actually uploaded to the bank.
    """

    bank_excel_export_id: uuid.UUID
    sent_at: datetime
    submission_channel: str
    note: str | None = None


@dataclass(frozen=True, slots=True)
class SentResult:
    export: BankExcelExport
    replayed: bool = False


def revalidate_for_download(
    export: BankExcelExport,
    *,
    session: Session,
    storage: StorageBackend,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> None:
    """`SVC-INTEGRITY-003`. The eight checks, again, before **this** download.

    `05_API_Specification.md:1514`: "Before every final download, the server revalidates export
    integrity." *Every* is the word that matters — validating once at generation would catch a
    file that was wrong when it was written and miss one that changed afterwards, which is the
    only failure mode a checksum can actually detect.

    A preview is not revalidated because there is nothing to revalidate it against: it has no
    approval, and half the comparisons read one. It is also not sendable, so a preview whose bytes
    drifted is a file nobody can act on.
    """

    if export.export_type != EXPORT_FINAL:
        return

    version = session.get(PaymentBatchVersion, export.payment_batch_version_id)
    approval = session.scalar(
        select(BatchApproval).where(
            BatchApproval.payment_batch_version_id == export.payment_batch_version_id
        )
    )
    if version is None or approval is None:  # pragma: no cover - the FKs guarantee both
        raise NotFoundError()

    record = session.get(FileObject, export.file_id)
    if record is None:  # pragma: no cover - `fk_bank_exports_file` guarantees it
        raise NotFoundError()

    # Through the file service, which keeps the address. `TRACE-DOD-003` refused
    # `storage.stat(record.storage_key)` here, correctly: ADR-003 has not chosen a production
    # storage adapter, and a change of provider must touch `app/storage/` and nothing else.
    measured = measure_now(storage, record)
    if measured is None:
        raise BusinessRuleViolationError(
            f"export {export.export_number} names a file storage cannot produce; it is not "
            "downloadable and nothing may claim it was sent"
        )

    failures = failed_checks(
        _facts_for(export, version=version, approval=approval, measured=measured)
    )
    if failures:
        batch = session.get(PaymentBatch, version.payment_batch_id)
        if batch is None:  # pragma: no cover - the version's FK guarantees it
            raise NotFoundError()
        _quarantine(
            session, policy, batch=batch, export=export, failures=failures, actor=actor,
            context=context, now=now,
        )
        raise IntegrityRefused(failures)


def mark_sent(
    command: MarkSent,
    *,
    uow: SqlAlchemyUnitOfWork,
    storage: StorageBackend,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    now: datetime,
) -> SentResult:
    """Record that a human uploaded this exact file to the bank.

    **Nothing here talks to a bank.** §15.7 makes submission manual by design and there is no
    channel to automate, so this command records a claim a person makes. That is why it captures
    *which* channel and *what* they said about it: the record has to be enough for somebody else
    to check the claim later.

    **Revalidated first, because `:1514` says before download *and* before mark-sent.** A file
    that changed between being downloaded and being marked sent is the case this catches, and it
    is not far-fetched: the gap between the two is however long it takes a person to open a bank
    portal.
    """

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=MARK_SENT_OPERATION,
        idempotency_key=idempotency_key,
        payload={
            "bank_excel_export_id": str(command.bank_excel_export_id),
            "submission_channel": command.submission_channel,
            "note": command.note,
        },
    )

    session = uow.session
    if claim.is_replay:
        # `CON-SENT-001`. The stored result, so a retry neither moves the timestamp nor writes a
        # second audit row.
        stored = claim.record.response_body or {}
        export = session.get(BankExcelExport, uuid.UUID(str(stored["export_id"])))
        if export is None:  # pragma: no cover - the record made it
            raise NotFoundError()
        return SentResult(export=export, replayed=True)

    lock_rows(
        session,
        [LockTarget.of(LockScope.EXPORT_MARK_SENT, BankExcelExport, command.bank_excel_export_id)],
        models={BankExcelExport.__tablename__: BankExcelExport},
    )

    export = session.get(BankExcelExport, command.bank_excel_export_id)
    if export is None:
        raise NotFoundError()

    # `SVC-SENT-001`. A preview is not sendable, and this is the service half of a property the
    # database already holds by refusing to let anything write `export_type`.
    if export.export_type != EXPORT_FINAL:
        raise BusinessRuleViolationError(
            "a preview cannot be marked sent to the bank; it is a rendering to look at, and "
            "15_Agent_Implementation_Plan.md:936 requires it to stay permanently non-sendable"
        )
    if export.sent_to_bank_marked_at is not None:
        raise ConflictError(
            f"export {export.export_number} was already marked sent at "
            f"{export.sent_to_bank_marked_at.isoformat()}"
        )
    if export.status == STATUS_QUARANTINED:
        raise BusinessRuleViolationError(
            f"export {export.export_number} is quarantined and cannot be marked sent"
        )

    if not command.submission_channel.strip():
        raise BusinessRuleViolationError(
            "a submission channel is required; 15_Agent_Implementation_Plan.md:983 lists it "
            "among what mark-sent records"
        )

    revalidate_for_download(
        export, session=session, storage=storage, policy=policy, actor=actor, context=context,
        now=now,
    )

    export.sent_to_bank_marked_at = command.sent_at
    export.sent_to_bank_marked_by_admin_user_id = _generator(actor)
    export.status = STATUS_SENT

    version = session.get(PaymentBatchVersion, export.payment_batch_version_id)
    if version is None:  # pragma: no cover - the FK guarantees it
        raise NotFoundError()
    batch = session.get(PaymentBatch, version.payment_batch_id)
    if batch is None:  # pragma: no cover - the FK guarantees it
        raise NotFoundError()
    batch.status = BATCH_SENT

    uow.flush()

    _audit_sent(
        session, policy, batch=batch, version=version, export=export, command=command,
        actor=actor, context=context, now=now,
    )
    _publish_sent(session, policy, batch=batch, version=version, export=export, context=context)

    resolver.complete(
        claim,
        response_code=200,
        response_body={"export_id": str(export.id)},
        resource_type="bank_excel_export",
        resource_id=export.id,
        now=now,
    )

    return SentResult(export=export)


def _audit_sent(
    session: Session,
    policy: RedactionPolicy,
    *,
    batch: PaymentBatch,
    version: PaymentBatchVersion,
    export: BankExcelExport,
    command: MarkSent,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> None:
    """`AUD-SENT-001`, carrying all seven things §15.7 says mark-sent records.

    Export id, batch and version, actor, sent timestamp, submission channel, note, and the
    integrity state — the last being the two hashes, which is what "checksum/integrity state"
    means for a row that has just been revalidated.

    **Two of the seven live only here.** §11.8 gives the table no column for `submission_channel`
    or `note`, and inventing two would be schema drift in the one milestone where the schema is
    the evidence. An audit row is where a recorded fact with no column belongs — it is append-only
    and the runtime cannot rewrite it, which is a stronger guarantee than a nullable column would
    have had.
    """

    AuditWriter(session, policy).record(
        AuditEntry(
            action=MARK_EXPORT_SENT.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="bank_excel_export",
            entity_id=export.id,
            entity_record_version=batch.record_version,
            previous_values={"status": STATUS_DOWNLOADED, "sent_to_bank_marked_at": None},
            new_values={
                "status": export.status,
                "payment_batch_id": str(batch.id),
                "payment_batch_version_id": str(version.id),
                "sent_to_bank_marked_at": command.sent_at.isoformat(),
                "sent_to_bank_marked_by_admin_user_id": str(
                    export.sent_to_bank_marked_by_admin_user_id
                ),
                "submission_channel": command.submission_channel,
                "content_hash": export.content_hash,
                "file_sha256_hash": export.file_sha256_hash,
                "batch_status": batch.status,
            },
            reason=command.note,
            occurred_at=now,
            metadata={"operation": MARK_EXPORT_SENT.audit_action},
        ),
        actor=actor,
        context=context,
    )


def _publish_sent(
    session: Session,
    policy: RedactionPolicy,
    *,
    batch: PaymentBatch,
    version: PaymentBatchVersion,
    export: BankExcelExport,
    context: AuditContext,
) -> None:
    """`BankExportSent` — the one outbox event this family owns.

    `command_catalog.yaml:207` names it, and it is the only export command that publishes.
    Generating a file is not the moment a payment leaves the building; a person saying they
    uploaded it is.
    """

    event = MARK_EXPORT_SENT.outbox_event_type
    if event is None:  # pragma: no cover - the registry entry names one
        raise RuntimeError(
            "MARK_EXPORT_SENT has no outbox event type, and command_catalog.yaml:207 requires "
            "BankExportSent"
        )

    OutboxWriter(session, policy).enqueue(
        OutboxMessage(
            aggregate_type="bank_excel_export",
            aggregate_id=export.id,
            aggregate_version=batch.record_version,
            event_type=event,
            payload={
                "bank_excel_export_id": str(export.id),
                "export_number": export.export_number,
                "payment_batch_id": str(batch.id),
                "payment_batch_version_id": str(version.id),
                "row_count": export.row_count,
                "total_amount_irr": str(export.total_amount_irr),
                "file_sha256_hash": export.file_sha256_hash,
            },
            payload_version=PAYLOAD_VERSION,
            correlation_id=context.correlation_id,
            causation_id=context.causation_id,
        )
    )


def _violated_constraint(error: IntegrityError) -> str | None:
    """The name PostgreSQL reports, read from the diagnostic rather than from the message.

    `psycopg` puts it on `error.orig.diag.constraint_name`. The obvious-looking alternative —
    a substring test against `str(error)` — happens to work, and the equally obvious
    `str(error.orig.diag)` does **not**: the diagnostic renders as its repr, so the constraint
    name is nowhere in it and the test silently never matches.

    That mistake is in `app/commands/payment_batch_approval.py` too, where nothing reaches the
    branch because the early read returns 409 first. It is corrected there in this commit.
    """

    diagnostic = getattr(error.orig, "diag", None)
    name = getattr(diagnostic, "constraint_name", None)
    return str(name) if name else None


def _file_record_for(
    *,
    key: str,
    export_number: str,
    stored: StoredObject,
    version: PaymentBatchVersion,
    actor: AuditActor,
) -> FileObject:
    """The `file_objects` row for a rendered export, preview or final.

    Extracted when the final export became the second caller — the point the duplication note in
    `payment_batch_approval._consume_context` describes as where a shared helper stops being an
    indirection for two callers and starts being one place for a decision.

    **`scan_status` is `clean`, on M4's precedent rather than this slice's invention.**
    `ck_file_objects_available_requires_clean_scan` refuses `available` for anything else — a
    whitelist, so an unrecognised scan outcome fails closed. `app/files/derivation.py` met the
    same question for a file this platform generates rather than receives and settled it with
    reasoning that applies here word for word: the bytes were produced from content already
    accepted, there is nothing external to scan, and `pending` would claim a scanner is coming
    for a file no scanner will ever see.

    `not_applicable` was written here first and PostgreSQL refused it, which is the constraint
    doing exactly its job.
    """

    return FileObject(
        storage_provider="local",
        storage_bucket="private",
        storage_key=key,
        original_filename=f"{export_number}.xlsx",
        mime_type_declared=EXPORT_MEDIA_TYPE,
        mime_type_detected=EXPORT_MEDIA_TYPE,
        size_bytes=stored.size_bytes,
        sha256_hash=stored.sha256_hash,
        category=EXPORT_FILE_CATEGORY,
        visibility_scope="internal_only",
        storage_status=AVAILABLE_STORAGE_STATUS,
        scan_status=CLEAN_SCAN_STATUS,
        uploaded_by_actor_type=actor.actor_type,
        uploaded_by_actor_id=actor.actor_id,
        original_or_derived_relation="original",
        metadata_payload={"payment_batch_version_id": str(version.id)},
    )


def _quarantine(
    session: Session,
    policy: RedactionPolicy,
    *,
    batch: PaymentBatch,
    export: BankExcelExport,
    failures: tuple[IntegrityFailure, ...],
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> None:
    """`SVC-INTEGRITY-002`. The export is kept, moved to `quarantined`, and recorded.

    **Kept, not deleted.** A mismatch is the most interesting thing that can happen to an export
    and the row is the only evidence of it. `uq_active_final_export_per_version`'s predicate
    excludes `quarantined`, so keeping it does not block the next attempt — the index was written
    with this case in it.

    **§15.5 asks for a "high-priority task/security event". M8 slice 3 supplied the task; the
    security event is still absent.**

    The task half is done and this function creates one — see the call at the end. M7 recorded G-10
    as "there is no task table in Phase 1A", which was wrong: `04_Database_Schema.md:1314` specified
    `manual_review_tasks` all along and it was unbuilt work rather than a design gap. That half of
    the paragraph below is now history, kept because the reasoning about the *other* half still
    holds:

    `auth_events.event_class` admits six values — `authentication`, `authorization`, `session`,
    `credential`, `account_state`, `administrative` — which are doc 12's twenty security event
    types grouped. An export integrity mismatch is none of them. It is a *data* event: nobody's
    identity or access is in question, a stored file disagrees with a stored record. The model's
    own comment says the class "is what alerting and retention are decided by", so filing this
    under `administrative` to make the insert succeed would route a financial-integrity incident
    into whatever queue reads administrative actions.

    So no `auth_events` row is written. The audit row below is the record, and it carries
    everything an investigator needs: the action, `outcome="failure"`, and each comparison that
    disagreed. When the owner settles G-10 — a task table, an alerting channel, or a seventh
    event class — this is where the event goes.
    """

    export.status = STATUS_QUARANTINED

    AuditWriter(session, policy).record(
        AuditEntry(
            action=QUARANTINE_EXPORT_ON_INTEGRITY_FAILURE.audit_action,
            outcome="failure",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="bank_excel_export",
            entity_id=export.id,
            entity_record_version=batch.record_version,
            previous_values={"status": STATUS_GENERATED},
            new_values={
                "status": STATUS_QUARANTINED,
                "export_number": export.export_number,
                # Each failure spelled out. "Integrity failed" tells an investigator nothing;
                # "the row count says 3 and the version says 4" tells them where to look.
                "failed_checks": [failure.describe() for failure in failures],
            },
            reason="§15.5 integrity checks did not hold",
            occurred_at=now,
            metadata={"operation": QUARANTINE_EXPORT_ON_INTEGRITY_FAILURE.audit_action},
        ),
        actor=actor,
        context=context,
    )

    # **§14.5's fifth requirement, finally buildable.** M7 recorded G-10 — "there is no task table
    # in Phase 1A" — and used it to excuse leaving "create/link urgent review task" undone.
    # `04_Database_Schema.md:1314` specifies `manual_review_tasks` with no later-phase marker, so
    # that was unbuilt work rather than a design gap. M8 slice 3 built it and this is the caller.
    #
    # **Highest priority, because of what this is.** A quarantined export is a file whose contents
    # disagree with the record of what the centre approved, and nothing downstream can act on it
    # until a person decides why. `open_task` is idempotent on the open queue, so a second
    # revalidation of the same export finds this task instead of adding another identical item.
    #
    # It does not un-quarantine anything and cannot: §13.1 keeps financial truth in explicit
    # tables, and the export's status is one of them.
    open_review_task(
        OpenReviewTask(
            task_type=TASK_TYPE_EXPORT_INTEGRITY,
            entity_type=ENTITY_BANK_EXPORT,
            entity_id=export.id,
            title=f"Integrity failure on export {export.export_number}",
            priority=5,
            description=(
                "The stored file disagrees with the record of the approved version. "
                + "; ".join(failure.describe() for failure in failures)
            ),
        ),
        session=session,
        policy=policy,
        actor=actor,
        context=context,
        now=now,
    )


def _audit_final(
    session: Session,
    policy: RedactionPolicy,
    *,
    batch: PaymentBatch,
    version: PaymentBatchVersion,
    export: BankExcelExport,
    approval: BatchApproval,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> None:
    """`AUD-EXPORT-002`. `bank_export.final_generated`, naming the approval it was authorised by.

    The approval id is in the row because this is the link the milestone's Definition of Done is
    about: "prove exactly which approved immutable version produced the exact checksummed file".
    From this one row a reader reaches the decision, the version and the digest.
    """

    AuditWriter(session, policy).record(
        AuditEntry(
            action=GENERATE_FINAL_EXPORT.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="bank_excel_export",
            entity_id=export.id,
            entity_record_version=batch.record_version,
            previous_values={},
            new_values={
                "export_number": export.export_number,
                "export_type": export.export_type,
                "status": export.status,
                "payment_batch_version_id": str(version.id),
                "batch_approval_id": str(approval.id),
                "content_hash": export.content_hash,
                "file_sha256_hash": export.file_sha256_hash,
                "row_count": export.row_count,
                "total_amount_irr": str(export.total_amount_irr),
            },
            reason=None,
            occurred_at=now,
            metadata={"operation": GENERATE_FINAL_EXPORT.audit_action},
        ),
        actor=actor,
        context=context,
    )


def facts_and_failures(
    export: BankExcelExport,
    *,
    version: PaymentBatchVersion,
    approval: BatchApproval,
    measured: str,
) -> tuple[IntegrityFailure, ...]:
    """The eight comparisons, for a caller that wants to *show* them rather than act on them.

    Public because slice 2B's read needs the same answer the download path acts on, and the
    alternative was the read module assembling its own `IntegrityFacts`. Two copies of the
    eighteen-value gather is how a screen and a download come to disagree about whether a file is
    sound, and that is the defect shape this repository has produced in every milestone: a second
    implementation of one rule, drifting quietly.

    Reading is separated from deciding — this returns the failures and quarantines nothing.
    """

    return failed_checks(_facts_for(export, version=version, approval=approval, measured=measured))


def _facts_for(
    export: BankExcelExport,
    *,
    version: PaymentBatchVersion,
    approval: BatchApproval,
    measured: str,
) -> IntegrityFacts:
    """Gather the eighteen values §15.5's eight comparisons read.

    Assembled here and compared there, so the comparing has no database and every one of the
    eight has a failing case a unit test can construct.
    """

    return IntegrityFacts(
        export_version_id=export.payment_batch_version_id,
        export_content_hash=export.content_hash,
        export_total_amount_irr=export.total_amount_irr,
        export_row_count=export.row_count,
        export_bank_mapping_id=export.bank_mapping_id,
        export_bank_account_id=version.bank_account_id,
        export_file_sha256_hash=export.file_sha256_hash,
        version_id=version.id,
        version_content_hash=version.content_hash,
        version_total_amount_irr=version.total_amount_irr,
        version_row_count=version.row_count,
        version_bank_mapping_id=version.bank_mapping_id,
        version_bank_account_id=version.bank_account_id,
        approval_version_id=approval.payment_batch_version_id,
        approval_content_hash=approval.approved_content_hash or "",
        measured_file_sha256_hash=measured,
    )


def _row_of(item: PaymentBatchItem) -> ExportRow:
    """The frozen snapshot, never a join.

    `04_Database_Schema.md:1021-1023` calls these "the exact approved/exported value". Reading the
    beneficiary through a relationship here would render whatever the beneficiary is *now*, which
    for a version approved yesterday is the one thing the snapshot exists to prevent.
    """

    return ExportRow(
        row_order=item.row_order,
        beneficiary_name=item.beneficiary_name_snapshot,
        beneficiary_iban=item.beneficiary_iban_snapshot,
        amount_irr=item.amount_irr,
        description=item.description_snapshot,
    )


# `content_hash` on an export **is the version's `content_hash`**, copied.
#
# The first version of this module computed a separate digest over the items' `row_hash` values,
# which was wrong in a way worth recording: §15.5's second comparison is
# `export content hash == batch-version hash`, so a digest computed by any other recipe can never
# equal the version's and the check could never pass. The integrity checks caught it on the happy
# path before any test did — the export was written, compared against its version, and refused.
#
# The reading that makes §11.8's "hash of normalized export content" and §15.5's equality agree is
# the simple one: a file renders exactly one version's content, so its content hash *is* that
# version's. What distinguishes the two hash columns is `file_sha256_hash`, which is the bytes —
# and those can differ between two renderings of the same version without a single payment
# changing.


def _export_number(session: Session, now: datetime) -> str:
    """`EXP-YYYYMMDD-NNNNNN`, the family `05_API_Specification.md:304` gives and
    `07_UI_UX_Specification.md:630-640` gives the width for.

    Gregorian, because ADR-006 is Approved and this value is both stored and transported; the
    documented example is Jalali and DOC-CONFLICT-054 records that disagreement for the whole
    family rather than for this number alone. G-8 in the M7 plan says the same.

    Counted in this transaction, so two concurrent generations can compute the same number and
    `UNIQUE(export_number)` refuses the second — the database owns uniqueness, as it does for
    `batch_number`.
    """

    prefix = f"EXP-{to_business_time(now).strftime('%Y%m%d')}-"
    used = session.scalar(
        select(func.count())
        .select_from(BankExcelExport)
        .where(BankExcelExport.export_number.startswith(prefix))
    )
    return f"{prefix}{(used or 0) + 1:06d}"


def _generator(actor: AuditActor) -> uuid.UUID:
    """The administrator who generated it, narrowed from `uuid.UUID | None`."""

    if actor.actor_id is None:
        raise BusinessRuleViolationError(
            "a bank export must be generated by an administrator; a system actor has no "
            "identity to record as its provenance, which §1 requires"
        )
    return actor.actor_id


def _replayed(session: Session, stored: dict[str, Any]) -> ExportResult:
    export = session.get(BankExcelExport, uuid.UUID(str(stored["export_id"])))
    file_record = session.get(FileObject, uuid.UUID(str(stored["file_id"])))
    if export is None or file_record is None:  # pragma: no cover - the record made them
        raise NotFoundError()
    return ExportResult(export=export, file=file_record, replayed=True)


def _audit(
    session: Session,
    policy: RedactionPolicy,
    *,
    batch: PaymentBatch,
    version: PaymentBatchVersion,
    export: BankExcelExport,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> None:
    """`AUD-EXPORT-001`. `bank_export.preview_generated`, from the registry.

    `command_catalog.yaml` gives this command no outbox event, and the catalogue is right: a
    preview is something an accountant looks at, not something any consumer outside the platform
    acts on. Slice 4's mark-sent is where `BankExportSent` belongs.
    """

    AuditWriter(session, policy).record(
        AuditEntry(
            action=GENERATE_EXPORT_PREVIEW.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="bank_excel_export",
            entity_id=export.id,
            entity_record_version=batch.record_version,
            previous_values={},
            new_values={
                "export_number": export.export_number,
                "export_type": export.export_type,
                "payment_batch_version_id": str(version.id),
                "row_count": export.row_count,
                "total_amount_irr": str(export.total_amount_irr),
                "content_hash": export.content_hash,
                "file_sha256_hash": export.file_sha256_hash,
            },
            reason=None,
            occurred_at=now,
            metadata={"operation": GENERATE_EXPORT_PREVIEW.audit_action},
        ),
        actor=actor,
        context=context,
    )
