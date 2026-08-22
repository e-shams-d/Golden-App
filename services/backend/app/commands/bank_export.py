"""Generating a bank file, and refusing to record one that does not exist.

M7 slice 2. `bank_export.generate_preview`, and the order of operations that
`FINANCIAL_INTEGRITY_BASELINE.md` §1 dictates.

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

**No lock.** `LockScope.EXPORT_GENERATE_FINAL` is reserved for slice 3, which must not race
another final export for the same version. A preview races nothing: it writes no version state,
holds no uniqueness, and two concurrent previews of one version are two files, which is what
`uq_active_final_export_per_version`'s predicate deliberately permits by excluding previews.

Covers: SVC-EXPORT-001, SVC-EXPORT-002, AUD-EXPORT-001.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import GENERATE_EXPORT_PREVIEW
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.core.time import to_business_time
from app.db.models.bank_export import EXPORT_PREVIEW, BankExcelExport
from app.db.models.file_object import CLEAN_SCAN_STATUS, FileObject
from app.db.models.payment_batch import PaymentBatch, PaymentBatchItem, PaymentBatchVersion
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.exports.excel import ExportRow, render_bank_file
from app.idempotency import IdempotencyResolver
from app.storage.interface import StorageBackend
from app.storage.keys import generate_storage_key

METADATA_SCHEMA = "payment_batch_command"
METADATA_VERSION = 1

PREVIEW_OPERATION = "bank_export.generate_preview"

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

    # The digest of the *content*, which is what §11.8's integrity checks compare against the
    # version. Distinct from the file digest below, and the difference matters: two renderings of
    # the same version can differ byte-for-byte (a timestamp in the zip, a library upgrade) while
    # describing identical instructions to a bank.
    content_hash = _content_hash(items)

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

    file_record = FileObject(
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
        # **`clean`, and the precedent is M4's, not this slice's invention.**
        # `ck_file_objects_available_requires_clean_scan` refuses `available` for anything else —
        # a whitelist, so an unrecognised scan outcome fails closed. `app/files/derivation.py`
        # met the same question for a file this platform generates rather than receives, and
        # settled it in the same direction with the reasoning that applies here word for word:
        # the bytes were produced from content already accepted, there is nothing external to
        # scan, and `pending` would claim a scanner is coming for a file no scanner will see.
        #
        # `not_applicable` was written here first and PostgreSQL refused it, which is the
        # constraint doing exactly its job: the safe default ADR-008 asks for is that an
        # unfamiliar scan outcome cannot make a file available.
        scan_status=CLEAN_SCAN_STATUS,
        uploaded_by_actor_type=actor.actor_type,
        uploaded_by_actor_id=actor.actor_id,
        original_or_derived_relation="original",
        metadata_payload={"payment_batch_version_id": str(version.id)},
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
        content_hash=content_hash,
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


def _content_hash(items: list[PaymentBatchItem]) -> str:
    """A digest of what the file instructs, not of the bytes that carry it.

    Built from each row's own `row_hash` in `row_order`, so it changes when an instruction changes
    and does not change when the writer's output does. That is what makes §11.8's comparison —
    `export.content_hash == batch_version.content_hash` — a statement about payments rather than
    about zip metadata.
    """

    digest = hashlib.sha256()
    for item in sorted(items, key=lambda row: row.row_order):
        digest.update(f"{item.row_order}:{item.row_hash}\n".encode())
    return digest.hexdigest()


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
