"""Bring the bank's answer in, say what it might relate to, and close it out.
`05_API_Specification.md` §18, `04_Database_Schema.md` §12.1-12.3.

M8 slice 1. Three commands, and each one had a decision worth recording.

**Upload lands the bundle in `ready_for_manual_review`, not in `uploaded`.**
`06_Workflows_and_State_Machines.md:995` draws `uploaded --> ready_for_manual_review: direct manual
mode`, and Phase 1A has no normalization job to take the `processing` branch — so upload *is* the
direct manual mode. The alternative was to leave the bundle in `uploaded` and wait for
`05_API_Specification.md:1693`'s `start-review`, which **has no permission in
`permission_catalog.yaml`**: not a missing grant but a missing entry, so deny-by-default makes the
route unreachable and a bundle waiting for it waits forever. Building the route anyway would ship a
`403` for every caller; inventing a permission is not an implementer's decision, because a
permission is a grant and grants are seeded and audited. Q-7 in the M8 plan carries it.

`uploaded` is still reachable and still meaningful: it is where a bundle sits if a future slice adds
the normalization job, and the CHECK admits it.

**A link proves nothing, and this module cannot make it prove anything.** `04_Database_Schema.md`
§12.3 at `:1199`. `link_batch` touches no attempt, no batch and no batch version — it inserts one
row and, when the batch supplies a bank profile the bundle lacks, fills that one nullable column.
`tests/integration/test_bundle_links.py` asserts the absence by reading the batch before and after.

**Counts are recomputed, never incremented.** §12.1 at `:1179` calls them cached read values that
must be "recomputed/validated transactionally from segments/tasks". Slice 1 has no segments to
count, so `recount` exists and returns zeros — written now rather than in slice 2 because the
alternative is slice 2 adding `+= 1` at three call sites and this comment arriving too late.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import (
    CLOSE_BANK_RESULT_BUNDLE,
    LINK_BANK_RESULT_BUNDLE_TO_BATCH,
    UPLOAD_BANK_RESULT_BUNDLE,
)
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.core.time import to_business_time
from app.db.models.bank_result_bundle import (
    BUNDLE_CLOSED,
    BUNDLE_READY_FOR_REVIEW,
    FILE_ROLE_SOURCE,
    LINK_ACTIVE,
    LINK_REPLACED,
    BankResultBundle,
    BankResultBundleBatchLink,
    BankResultBundleFile,
)
from app.db.models.file_object import CLEAN_SCAN_STATUS, FileObject
from app.db.models.payment_batch import PaymentBatch, PaymentBatchVersion
from app.db.unit_of_work import SqlAlchemyUnitOfWork

METADATA_SCHEMA = "audit.bank_result_bundle"
METADATA_VERSION = 1


@dataclass(frozen=True, slots=True)
class AttachedFile:
    """One file to bring into the bundle, with the position and role it takes."""

    file_id: uuid.UUID
    sequence_number: int
    file_role: str = FILE_ROLE_SOURCE
    page_count: int | None = None


@dataclass(frozen=True, slots=True)
class UploadBundle:
    source_type: str
    files: tuple[AttachedFile, ...]
    notes: str | None = None
    bank_profile_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class LinkBundleToBatch:
    bank_result_bundle_id: uuid.UUID
    payment_batch_id: uuid.UUID
    link_method: str
    payment_batch_version_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class CloseBundle:
    bank_result_bundle_id: uuid.UUID
    resolution_note: str


def upload_bundle(
    command: UploadBundle,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> BankResultBundle:
    """`POST /api/v1/bank-result-bundles`. `05_API_Specification.md:1642`.

    **The files must already exist and must already be clean.** A bundle file is a *link* to an
    M4 file object, never a copy — `08_Bank_File_and_Result_Processing.md:137` forbids overwriting
    an original, and the cheapest way to honour that is to never hold a second copy that could be
    confused with it. The scan state is checked here rather than trusted, because a bundle
    containing a file nobody has scanned is evidence nobody may open.

    **At least one file.** A bundle with none is not a delivery; it is a row that will sit in the
    review queue forever with nothing to review.
    """

    session = uow.session

    if not command.files:
        raise BusinessRuleViolationError(
            "a bank-result bundle needs at least one file; an empty bundle would sit in the "
            "review queue with nothing in it"
        )

    seen: set[uuid.UUID] = set()
    for attachment in command.files:
        if attachment.file_id in seen:
            # `uq_bundle_files_file` refuses this too. Caught here so the message names the file
            # rather than a constraint.
            raise BusinessRuleViolationError(
                f"file {attachment.file_id} is attached twice to one bundle"
            )
        seen.add(attachment.file_id)

        record = session.get(FileObject, attachment.file_id)
        if record is None:
            raise NotFoundError()
        if record.scan_status != CLEAN_SCAN_STATUS:
            raise BusinessRuleViolationError(
                f"file {attachment.file_id} has scan status {record.scan_status!r}; a bundle may "
                "only contain files that have been scanned clean"
            )

    bundle = BankResultBundle(
        bundle_number=_next_bundle_number(session, now),
        bank_profile_id=command.bank_profile_id,
        # Straight to review. See the module docstring: Phase 1A has no processing job, and
        # `start-review` has no permission to move it later.
        status=BUNDLE_READY_FOR_REVIEW,
        source_type=command.source_type,
        notes=command.notes,
        uploaded_by_admin_user_id=actor.actor_id,
        uploaded_at=now,
        segment_count=0,
        resolved_segment_count=0,
        unresolved_segment_count=0,
        record_version=1,
        created_at=now,
        updated_at=now,
    )
    session.add(bundle)
    session.flush()

    for attachment in command.files:
        session.add(
            BankResultBundleFile(
                bank_result_bundle_id=bundle.id,
                file_id=attachment.file_id,
                sequence_number=attachment.sequence_number,
                file_role=attachment.file_role,
                page_count=attachment.page_count,
                created_at=now,
            )
        )
    # Flushed here so the caller's `file_count` sees them. Without it the read ran before these
    # rows reached the database and reported a bundle with no files — which looked like the upload
    # having silently dropped them.
    session.flush()

    AuditWriter(session, policy).record(
        AuditEntry(
            action=UPLOAD_BANK_RESULT_BUNDLE.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="bank_result_bundle",
            entity_id=bundle.id,
            entity_record_version=bundle.record_version,
            previous_values=None,
            new_values={
                "bundle_number": bundle.bundle_number,
                "status": bundle.status,
                "source_type": bundle.source_type,
                "file_count": len(command.files),
            },
            reason="bank-returned evidence received",
            occurred_at=now,
            metadata={"operation": UPLOAD_BANK_RESULT_BUNDLE.audit_action},
        ),
        actor=actor,
        context=context,
    )
    return bundle


def link_to_batch(
    command: LinkBundleToBatch,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> BankResultBundleBatchLink:
    """`POST /api/v1/bank-result-bundles/{id}/batch-links`. `05_API_Specification.md:1685`.

    **This changes nothing about the batch.** §12.3: the association "does not prove payment
    completion. Attempt/segment confirmation remains authoritative." So this function reads the
    batch to check it exists and writes nothing to it — no status, no timestamp, no counter.

    **Re-linking replaces rather than edits.** `uq_bundle_links_active_pair` allows one active link
    per pair, so a corrected belief marks the old row `replaced` and inserts a new one in the same
    transaction. §12.3's `replaced_at` only means something if the old row survives to carry it,
    and the old row is the record that somebody once thought otherwise.
    """

    session = uow.session

    bundle = session.get(BankResultBundle, command.bank_result_bundle_id)
    if bundle is None:
        raise NotFoundError()
    if bundle.status == BUNDLE_CLOSED:
        raise BusinessRuleViolationError(
            f"bundle {bundle.bundle_number} is closed; a closed bundle records what was concluded "
            "and does not accept new associations"
        )

    batch = session.get(PaymentBatch, command.payment_batch_id)
    if batch is None:
        raise NotFoundError()

    if command.payment_batch_version_id is not None:
        version = session.get(PaymentBatchVersion, command.payment_batch_version_id)
        if version is None:
            raise NotFoundError()
        if version.payment_batch_id != batch.id:
            # A link naming a version of a different batch would be a link to two things at once,
            # and the read would render whichever it happened to join first.
            raise BusinessRuleViolationError(
                "the version named does not belong to the batch named"
            )

    superseded = session.scalar(
        select(BankResultBundleBatchLink).where(
            BankResultBundleBatchLink.bank_result_bundle_id == bundle.id,
            BankResultBundleBatchLink.payment_batch_id == batch.id,
            BankResultBundleBatchLink.status == LINK_ACTIVE,
        )
    )
    if superseded is not None:
        superseded.status = LINK_REPLACED
        superseded.replaced_at = now
        session.flush()

    link = BankResultBundleBatchLink(
        bank_result_bundle_id=bundle.id,
        payment_batch_id=batch.id,
        payment_batch_version_id=command.payment_batch_version_id,
        link_method=command.link_method,
        status=LINK_ACTIVE,
        created_by_admin_user_id=actor.actor_id,
        created_at=now,
    )
    session.add(link)

    # The one thing a link may tell the bundle: which bank it came from, when the bundle did not
    # know and the batch does. Filled only when empty — a link never overwrites an established
    # bank, because that would let a mistaken link rewrite a known fact.
    if bundle.bank_profile_id is None:
        profile_id = _bank_profile_of(session, batch)
        if profile_id is not None:
            bundle.bank_profile_id = profile_id
            bundle.updated_at = now

    AuditWriter(session, policy).record(
        AuditEntry(
            action=LINK_BANK_RESULT_BUNDLE_TO_BATCH.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="bank_result_bundle",
            entity_id=bundle.id,
            entity_record_version=bundle.record_version,
            previous_values=(
                {"link_status": LINK_ACTIVE, "link_id": str(superseded.id)}
                if superseded is not None
                else None
            ),
            new_values={
                "payment_batch_id": str(batch.id),
                "payment_batch_version_id": (
                    str(command.payment_batch_version_id)
                    if command.payment_batch_version_id
                    else None
                ),
                "link_method": command.link_method,
                # Said in the record itself, because an audit row for a link is exactly where
                # somebody later looks for proof of payment and must not find it.
                "proves_payment": False,
            },
            reason="operational association recorded; not evidence of payment",
            occurred_at=now,
            metadata={"operation": LINK_BANK_RESULT_BUNDLE_TO_BATCH.audit_action},
        ),
        actor=actor,
        context=context,
    )
    return link


def close_bundle(
    command: CloseBundle,
    *,
    uow: SqlAlchemyUnitOfWork,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> BankResultBundle:
    """`POST /api/v1/bank-result-bundles/{id}/close`. `05_API_Specification.md:1700`.

    **The counts are recomputed before the decision, not read.** Closing asserts that everything
    in the bundle has been dealt with, and asserting it from a cached number would be asserting it
    from something that may have drifted. `:1179` is explicit that these are not independent truth.

    **`unresolved_dispositions` is not implemented here and the reason is honest.** Document 05 at
    `:1710` lets a caller close a bundle by explicitly dispositioning unresolved segments — which
    needs segments, and slice 1 has none. Slice 2 creates them and slice 7's journey closes a
    bundle that has some. Until then the count is zero and the note is what `:1709` asks for.
    """

    session = uow.session

    bundle = session.get(BankResultBundle, command.bank_result_bundle_id)
    if bundle is None:
        raise NotFoundError()
    if bundle.status == BUNDLE_CLOSED:
        raise BusinessRuleViolationError(f"bundle {bundle.bundle_number} is already closed")

    if not command.resolution_note.strip():
        # `:1709` shows a resolution note and `:1716` says the API "does not silently discard
        # unmatched content". A blank note is the silent discard with a field around it.
        raise BusinessRuleViolationError(
            "closing a bundle requires a resolution note; the API does not silently discard "
            "unmatched content"
        )

    recount(session, bundle, now=now)

    if bundle.unresolved_segment_count > 0:
        raise BusinessRuleViolationError(
            f"bundle {bundle.bundle_number} has {bundle.unresolved_segment_count} unresolved "
            "segments; each needs an explicit disposition before the bundle closes"
        )

    previous = bundle.status
    bundle.status = BUNDLE_CLOSED
    bundle.closed_at = now
    bundle.closed_by_admin_user_id = actor.actor_id
    bundle.record_version += 1
    bundle.updated_at = now

    AuditWriter(session, policy).record(
        AuditEntry(
            action=CLOSE_BANK_RESULT_BUNDLE.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="bank_result_bundle",
            entity_id=bundle.id,
            entity_record_version=bundle.record_version,
            previous_values={"status": previous},
            new_values={
                "status": bundle.status,
                "segment_count": bundle.segment_count,
                "resolved_segment_count": bundle.resolved_segment_count,
            },
            reason=command.resolution_note,
            occurred_at=now,
            metadata={"operation": CLOSE_BANK_RESULT_BUNDLE.audit_action},
        ),
        actor=actor,
        context=context,
    )
    return bundle


def recount(session: Session, bundle: BankResultBundle, *, now: datetime) -> None:
    """Recompute §12.1's three counts from the segments themselves.

    **Recomputed, never incremented**, and the difference is not stylistic: an increment is correct
    until the first retry, and this table's counts are read by a queue that decides what a person
    works on next. `:1179` requires them "recomputed/validated transactionally from
    segments/tasks", which is what this is.

    **Slice 2 made this live.** Slice 1 wrote it against a table that did not exist yet, behind a
    runtime `has_table` check, and returned zeros — written early on purpose, because the shape of
    the alternative was three `+= 1` call sites that would already have been there by the time the
    table arrived. `receipt_segments` now always exists, so the check is gone: an inspection that
    can only answer one way is a branch nothing tests.

    One query, two counts. `RESOLVED_SEGMENT_STATUSES` is the segment module's decision about which
    statuses need no further work, so "resolved" has one definition rather than one here and another
    on whatever screen reads the number.
    """

    from app.db.models.receipt_segment import RESOLVED_SEGMENT_STATUSES, ReceiptSegment

    counted = session.execute(
        select(
            func.count(),
            func.count().filter(ReceiptSegment.status.in_(RESOLVED_SEGMENT_STATUSES)),
        ).where(ReceiptSegment.bank_result_bundle_id == bundle.id)
    ).one()
    total, resolved = int(counted[0]), int(counted[1])

    bundle.segment_count = total
    bundle.resolved_segment_count = resolved
    bundle.unresolved_segment_count = total - resolved
    bundle.updated_at = now


def _bank_profile_of(session: Session, batch: PaymentBatch) -> uuid.UUID | None:
    """The bank profile the batch's current version was built against, if it has one.

    Read through the version rather than from the batch, because the batch does not carry a
    profile: the *version* does, which is the same reason M7's approval view reads its bank name
    through `bank_profile_versions`.
    """

    from app.db.models.bank import BankProfileVersion

    return session.scalar(
        select(BankProfileVersion.bank_profile_id)
        .select_from(PaymentBatchVersion)
        .join(
            BankProfileVersion,
            PaymentBatchVersion.bank_profile_version_id == BankProfileVersion.id,
        )
        .where(PaymentBatchVersion.payment_batch_id == batch.id)
        .order_by(PaymentBatchVersion.version_number.desc())
        .limit(1)
    )


def _next_bundle_number(session: Session, now: datetime) -> str:
    """`BRB-YYYYMMDD-NNNNNN`, counted within the business day.

    The prefix is `05_API_Specification.md:304`'s and the day precision and six-digit width are
    `07_UI_UX_Specification.md:630-640`'s — the third place in this codebase to implement that
    family, and `tests/backend/test_human_readable_numbers.py` parses both documents so it cannot
    drift the way M5's invented `GP-YYYYMM-NNNN` did.

    **Gregorian, per ADR-006 rather than per this function.** The documented examples are Jalali;
    ADR-006 is Approved and states that Jalali presentation "does not leak into database or
    transport contracts", and this value is both stored and transported. DOC-CONFLICT-054 records
    the disagreement and a frontend may render the Jalali form.

    Counted, not maximised, and the count is taken in this transaction — so two concurrent uploads
    can compute the same number and `uq_bundles_bundle_number` refuses the second. The database
    owns uniqueness; a `max() + 1` that looked safe would be the version that collides silently.
    """

    prefix = f"BRB-{to_business_time(now).strftime('%Y%m%d')}-"
    used = session.scalar(
        select(func.count())
        .select_from(BankResultBundle)
        .where(BankResultBundle.bundle_number.startswith(prefix))
    )
    return f"{prefix}{(used or 0) + 1:06d}"
