"""The export's own surface: read it, download it, say you sent it.

M7 slice 4. `05_API_Specification.md:1500-1530` puts these under `/bank-exports/{export_id}`
rather than under the batch, and the path is the contract: mark-sent "acts on an exact
`BankExcelExport`, not a generic batch" (`15_Agent_Implementation_Plan.md:978`). A batch may have
had several versions and several exports; exactly one of them was uploaded.

**The file is a list of every payment the centre is making.** So the download is guarded by its
own permission, refused to a trader outright, and revalidated on the way out — every time, not
once at generation.

**No `If-Match` on mark-sent, and that is recorded rather than decided here.**
`05_API_Specification.md:1519` shows `If-Match: "rv-5"`, but §11.8 gives `bank_excel_exports` no
`record_version` column and `command_catalog.yaml:203` says so in its own words:
`"concurrency": "open_conflict_if_match_target_not_defined"`. The catalogue is describing an
unresolved contract, not a requirement this route is ignoring. `Idempotency-Key` is required and
unambiguous, and it is what makes a retry safe; G-13 records the rest.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor, requires
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.commands import bank_export as export_commands
from app.core.errors import ErrorEnvelope, NotFoundError, PreconditionRequiredError
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.bank import BankAccount, BankMapping, BankProfile, BankProfileVersion
from app.db.models.bank_export import EXPORT_FINAL, BankExcelExport
from app.db.models.file_object import FileObject
from app.db.models.identity import AdminUser
from app.db.models.payment_batch import BatchApproval, PaymentBatch, PaymentBatchVersion
from app.files.download import measure_now, open_stream
from app.security.actor import ActorContext
from app.security.permissions import declare
from app.storage.interface import StorageBackend

router = APIRouter(prefix="/bank-exports", tags=["bank-exports"])

EXPORT_REDACTION = RedactionPolicy(mask_iban=True)

# Not one of §15.5's eight, and named so it cannot be mistaken for one. A file storage cannot
# produce is a worse problem than any comparison failing, and rendering it inside the list of
# checks would imply the other seven were evaluated.
MISSING_FILE_CHECK = "file_is_missing_from_storage: expected the stored file, found nothing"


def _username(session: Session, admin_user_id: uuid.UUID | None) -> str | None:
    """The name to show for an actor id, or `None` when there is no actor.

    `None` is a real answer: an export nobody has marked sent has no sender. The second copy of
    this helper in the codebase — `payment_batches.py` has the first — and left as a copy on
    purpose, because sharing it would mean a module of user lookups that both API surfaces import
    for three lines.
    """

    if admin_user_id is None:
        return None
    found = session.get(AdminUser, admin_user_id)
    return found.username if found is not None else None

RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "The caller lacks the export permission."},
    404: {"model": ErrorEnvelope, "description": "No such export."},
    409: {
        "model": ErrorEnvelope,
        "description": (
            "EXPORT_INTEGRITY_MISMATCH — revalidation failed and the export has been "
            "quarantined; or the export was already marked sent."
        ),
    },
    **VALIDATION_ERROR_RESPONSE,
}


class ExportDetail(BaseModel):
    """`05_API_Specification.md:1500-1505`, plus what §14.4 and §14.7 of the screen specification
    require.

    `sendable` and `awaiting_send_confirmation` are not in document 05 and are deliberate.
    `15_Agent_Implementation_Plan.md:989` — "Downloading does not mean sent" — is this milestone's
    central human-factors risk: an accountant who downloads a file, emails it to the bank and
    forgets to come back leaves the system believing the payment was never made, and the next
    reconciliation cycle chases it.

    `SVC-SENT-002` asks that such an export be *visibly* unsent rather than merely lacking a
    timestamp. A screen cannot show what the response does not say, and "the timestamp is null"
    is not something a UI should have to interpret.

    **Screens slice 2B widened this from fifteen fields to twenty-six.** The survey in the plan's
    slice 2B found the export screens could not be rendered from what this returned: it gave ids
    where §14.4 asks for names, both hashes where §14.4 asks whether they *match*, and a status
    where §14.5 asks which checks failed. `API-EXPORTREAD-001` asserts the list parsed from the
    document, which is the same parse slice 3's screen uses.

    **Names and numbers, not ids**, for slice 0's reason: a screen showing a UUID for "mapping"
    is a screen nobody can read, and the two ids stay for callers that need to navigate.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    export_number: str
    export_type: str
    status: str
    sendable: bool
    awaiting_send_confirmation: bool
    row_count: int
    total_amount_irr: str
    content_hash: str
    file_sha256_hash: str
    payment_batch_version_id: uuid.UUID
    batch_approval_id: uuid.UUID | None
    generated_at: datetime
    downloaded_at: datetime | None
    sent_to_bank_marked_at: datetime | None

    # §14.4's "file name". The name the file was stored under, from `file_objects` — this route
    # does not know a storage key and `TRACE-DOD-003` is why.
    file_name: str

    # §14.4's "exact version", which an id alone does not give a reader. The batch id stays so a
    # screen can link back to the approval detail slice 1 built.
    batch_id: uuid.UUID
    batch_number: str
    version_number: int

    # §14.4's "mapping" and "source account", and the bank they belong to.
    bank: str | None
    bank_profile_version_number: int | None
    mapping_version: int | None
    source_account: str | None

    # §14.4's "approval/hash match" — a comparison, not two hashes for a screen to compare itself.
    # `None` for a preview, which has no approval: there is nothing to match, and `False` would
    # read as a mismatch. `API-EXPORTREAD-003` asserts the comparison is against the *version*.
    approval_hash_matches: bool | None

    # §14.5's "show each failed check". Empty for a sound export, and empty is the answer a screen
    # needs in order to say nothing is wrong.
    integrity_failed_checks: list[str]

    generated_by: str | None
    sent_by: str | None


class MarkSentConfirmation(ExportDetail):
    """§14.7's confirmation, which needs two values no table stores.

    `submission_channel` and `note` are **audit-only by design**: §11.8 gives
    `bank_excel_exports` no column for either, and slice 4 recorded that inventing two would be
    the schema drift this milestone guards hardest against. The route has both in hand at the
    moment the confirmation is shown, so it echoes what it recorded rather than reading it back.

    **A later `GET` cannot carry them**, and `API-EXPORTREAD-004` asserts that too. The asymmetry
    is real, and a test that only checked this response would let somebody build a screen that
    expects to re-read them.
    """

    model_config = ConfigDict(extra="forbid")

    submission_channel: str
    note: str | None


class MarkSentRequest(BaseModel):
    """`05_API_Specification.md:1523-1528`."""

    model_config = ConfigDict(extra="forbid")

    sent_at: datetime
    submission_channel: str = Field(min_length=1, max_length=64)
    note: str | None = Field(default=None, max_length=2000)


@dataclass(frozen=True, slots=True)
class _Context:
    """The joins §14.4 needs, read once.

    A dataclass rather than a tuple because `configuration[3]` at the call site is how the wrong
    column gets rendered under the right label.
    """

    file_name: str
    batch_id: uuid.UUID
    batch_number: str
    version_number: int
    bank: str | None
    bank_profile_version_number: int | None
    mapping_version: int | None
    source_account: str | None
    approval_hash_matches: bool | None
    integrity_failed_checks: tuple[str, ...]
    generated_by: str | None
    sent_by: str | None


def _context_for(
    session: Session, storage: StorageBackend, export: BankExcelExport
) -> _Context:
    """Everything §14.4 asks for that is not on the export row.

    **The integrity checks are re-evaluated, not read back out of the audit row.** `_quarantine`
    records what happened at the moment it happened, which is what an audit trail is for; a screen
    asks a different question — *is this file sound now* — and the eight comparisons are pure and
    cheap. Parsing them back out of `new_values` would also make the screen depend on the shape of
    an audit payload, which is the one place in this system that must be free to change.
    """

    row = session.execute(
        select(
            FileObject.original_filename,
            PaymentBatch.id,
            PaymentBatch.batch_number,
            PaymentBatchVersion.version_number,
            BankProfile.name,
            BankProfileVersion.version_number,
            BankMapping.template_version,
            BankAccount.display_name,
        )
        .select_from(BankExcelExport)
        .join(FileObject, BankExcelExport.file_id == FileObject.id)
        .join(
            PaymentBatchVersion,
            BankExcelExport.payment_batch_version_id == PaymentBatchVersion.id,
        )
        .join(PaymentBatch, PaymentBatchVersion.payment_batch_id == PaymentBatch.id)
        .outerjoin(
            BankProfileVersion,
            BankExcelExport.bank_profile_version_id == BankProfileVersion.id,
        )
        .outerjoin(BankProfile, BankProfileVersion.bank_profile_id == BankProfile.id)
        .outerjoin(BankMapping, BankExcelExport.bank_mapping_id == BankMapping.id)
        .outerjoin(BankAccount, PaymentBatchVersion.bank_account_id == BankAccount.id)
        .where(BankExcelExport.id == export.id)
    ).one()

    version = session.get(PaymentBatchVersion, export.payment_batch_version_id)
    approval = (
        session.get(BatchApproval, export.batch_approval_id)
        if export.batch_approval_id is not None
        else None
    )

    # §14.4's "approval/hash match", compared against the **version**. The export's own
    # `content_hash` is a copy, and a copy agrees with itself: an export written from the wrong
    # version would report a match if this compared those two. `API-EXPORTREAD-003`.
    matches: bool | None = None
    if approval is not None and version is not None:
        matches = (
            approval.approved_content_hash == version.content_hash
            and export.content_hash == version.content_hash
        )

    return _Context(
        file_name=row[0],
        batch_id=row[1],
        batch_number=row[2],
        version_number=row[3],
        bank=row[4],
        bank_profile_version_number=row[5],
        mapping_version=row[6],
        source_account=row[7],
        approval_hash_matches=matches,
        integrity_failed_checks=_failed_checks_now(
            session, storage, export, version=version, approval=approval
        ),
        generated_by=_username(session, export.generated_by_admin_user_id),
        sent_by=_username(session, export.sent_to_bank_marked_by_admin_user_id),
    )


def _failed_checks_now(
    session: Session,
    storage: StorageBackend,
    export: BankExcelExport,
    *,
    version: PaymentBatchVersion | None,
    approval: BatchApproval | None,
) -> tuple[str, ...]:
    """The eight comparisons, evaluated for display. Never a write.

    A preview returns none, and not because it always passes: it has no approval, and half the
    comparisons read one. §14.1 forbids a preview from showing a final checksum, and a preview
    reporting "integrity holds" would be that in another form — an assurance about a file nobody
    may send.

    **This does not quarantine.** Reading a screen must not change a lifecycle state, and the
    download path already quarantines on the same comparison. If those two ever disagree it is
    because the file changed between the two calls, which is the thing being watched for.
    """

    if export.export_type != EXPORT_FINAL or version is None or approval is None:
        return ()

    record = session.get(FileObject, export.file_id)
    if record is None:  # pragma: no cover - `fk_bank_exports_file` guarantees it
        return ()
    measured = measure_now(storage, record)
    if measured is None:
        # The file is gone. That is not one of §15.5's eight comparisons and must not be rendered
        # as one — a screen that listed it among the checks would imply the other seven ran.
        return (MISSING_FILE_CHECK,)

    failures = export_commands.facts_and_failures(
        export, version=version, approval=approval, measured=measured
    )
    return tuple(failure.describe() for failure in failures)


def _detail_fields(export: BankExcelExport, context: _Context) -> dict[str, object]:
    return {
        "id": export.id,
        "export_number": export.export_number,
        "export_type": export.export_type,
        "status": export.status,
        "sendable": export.export_type == "final" and export.status != "quarantined",
        # The whole of `SVC-SENT-002`, in one derived field: downloaded, still unsent, and
        # therefore something a person needs to be reminded about.
        "awaiting_send_confirmation": (
            export.export_type == "final"
            and export.downloaded_at is not None
            and export.sent_to_bank_marked_at is None
        ),
        "row_count": export.row_count,
        "total_amount_irr": str(export.total_amount_irr),
        "content_hash": export.content_hash,
        "file_sha256_hash": export.file_sha256_hash,
        "payment_batch_version_id": export.payment_batch_version_id,
        "batch_approval_id": export.batch_approval_id,
        "generated_at": export.generated_at,
        "downloaded_at": export.downloaded_at,
        "sent_to_bank_marked_at": export.sent_to_bank_marked_at,
        "file_name": context.file_name,
        "batch_id": context.batch_id,
        "batch_number": context.batch_number,
        "version_number": context.version_number,
        "bank": context.bank,
        "bank_profile_version_number": context.bank_profile_version_number,
        "mapping_version": context.mapping_version,
        "source_account": context.source_account,
        "approval_hash_matches": context.approval_hash_matches,
        "integrity_failed_checks": list(context.integrity_failed_checks),
        "generated_by": context.generated_by,
        "sent_by": context.sent_by,
    }


def _detail(
    session: Session, storage: StorageBackend, export: BankExcelExport
) -> ExportDetail:
    return ExportDetail(**_detail_fields(export, _context_for(session, storage, export)))


@router.get(
    "/{export_id}",
    response_model=ExportDetail,
    operation_id="getBankExport",
    summary="What this export is, and whether anybody has confirmed sending it.",
    responses=RESPONSES,
    dependencies=[requires(declare("bank_export.read"))],
)
def get_bank_export(
    export_id: uuid.UUID,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> ExportDetail:
    """`GET /api/v1/bank-exports/{export_id}`.

    `bank_export.read` goes to `accountant`, `manager` and `read_only_auditor`
    (`permission_catalog.yaml:495`) — reading what was sent is not the same authority as sending
    it, and an auditor needs the first without the second.
    """

    del actor
    with runtime.uow_factory() as uow:
        export = uow.session.get(BankExcelExport, export_id)
        if export is None:
            raise NotFoundError()
        # Read-only: `_detail` re-evaluates §15.5's comparisons for display and writes nothing,
        # so there is no `commit` here and a quarantine stays the download path's business.
        return _detail(uow.session, runtime.storage, export)


@router.get(
    "/{export_id}/download",
    operation_id="downloadBankExport",
    summary="Stream the file, after revalidating it.",
    responses=RESPONSES,
    dependencies=[requires(declare("bank_export.download"))],
    # M4's file download declares the same, and without it FastAPI describes the 200 as an empty
    # schema — which the client type generator refuses, correctly: a response with no type is a
    # response no caller can be written against.
    response_class=StreamingResponse,
)
def download_bank_export(
    export_id: uuid.UUID,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> StreamingResponse:
    """`GET /api/v1/bank-exports/{export_id}/download`.

    **Revalidated before *this* download**, per `:1514`. `SVC-INTEGRITY-003` is about the word
    "every": checking once at generation catches a file that was wrong when written and misses one
    that changed afterwards, which is the only thing a checksum can actually detect. A mismatch
    quarantines and answers `409`.

    **`downloaded_at` is set, and it is not a lifecycle step.** It exists so that §2.5's question —
    "who has a copy of this and has not told us they sent it" — is answerable. The status moves to
    `downloaded` only from `validated`, so a re-download does not walk a `sent_to_bank_marked`
    export backwards.
    """

    now = utc_now()
    audit_actor = AuditActor(
        actor_type=actor.actor_type.value,
        actor_id=actor.actor_id,
        role_snapshot=tuple(sorted(actor.roles)),
        session_id=actor.session_id,
        authentication_assurance=actor.auth_level,
    )
    context = AuditContext(request_id=get_request_id())

    with runtime.uow_factory() as uow:
        session = uow.session
        export = session.get(BankExcelExport, export_id)
        if export is None:
            raise NotFoundError()
        if export.status == "quarantined":
            # `SEC-DOWNLOAD-001`. A quarantined export is evidence, not a deliverable; whatever
            # is wrong with it must not reach a bank while somebody investigates.
            raise export_commands.IntegrityRefused(())

        try:
            export_commands.revalidate_for_download(
                export,
                session=session,
                storage=runtime.storage,
                policy=EXPORT_REDACTION,
                actor=audit_actor,
                context=context,
                now=now,
            )
        except export_commands.IntegrityRefused:
            # **Committed on purpose**, and the first version of this route did not — so the
            # quarantine and its audit row were rolled back with the failed request and the next
            # download found the export still `validated`. §15.5 says a mismatch *quarantines*;
            # discarding that record would leave the export downloadable again by whoever tries
            # next, which is the opposite of what quarantine means.
            #
            # The same choice as the step-up refusal in `app/api/v1/roles.py` and slice 1's
            # approval: on a failure path whose whole point is the record, the record commits.
            uow.commit()
            raise

        record = session.get(FileObject, export.file_id)
        if record is None:  # pragma: no cover - `fk_bank_exports_file` guarantees it
            raise NotFoundError()
        # Through the file service, which returns an iterator and keeps the address. Reading
        # `record.storage_key` here was the first attempt and `TRACE-DOD-003` refused it: ADR-003
        # has not chosen a production storage adapter, so a change of provider must touch
        # `app/storage/` and nothing else.
        stream = open_stream(runtime.storage, record)

        if export.downloaded_at is None:
            export.downloaded_at = now
        if export.status == "validated":
            export.status = "downloaded"
        uow.commit()

    return StreamingResponse(
        stream.chunks,
        media_type=stream.media_type,
        headers={"Content-Disposition": f'attachment; filename="{stream.filename}"'},
    )


@router.post(
    "/{export_id}/mark-sent-to-bank",
    response_model=MarkSentConfirmation,
    operation_id="markBankExportSent",
    summary="Record that a person uploaded this exact file to the bank.",
    responses=RESPONSES,
    dependencies=[requires(declare("bank_export.mark_sent"))],
)
def mark_bank_export_sent(
    export_id: uuid.UUID,
    payload: MarkSentRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> MarkSentConfirmation:
    """`POST /api/v1/bank-exports/{export_id}/mark-sent-to-bank`.

    **Nothing here contacts a bank.** §15.7 makes submission manual by design, so this records a
    claim a person makes — which is why it captures the channel they used and what they said
    about it. The record has to be enough for somebody else to check the claim later.

    **No `If-Match`.** Document 05 shows one; §11.8 gives this table no `record_version`; and
    `command_catalog.yaml:203` says `open_conflict_if_match_target_not_defined` — the catalogue
    describing an unresolved contract rather than a requirement being ignored. G-13 records it.
    `Idempotency-Key` is required, and `CON-SENT-001` is what makes a retry safe.

    **The response echoes the channel and the note.** §14.7's confirmation must show all ten of
    the values it lists, and those two live only in the audit row — so this is the one moment they
    can be shown without inventing a column. `API-EXPORTREAD-004`.
    """

    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")

    now = utc_now()
    with runtime.uow_factory() as uow:
        result = export_commands.mark_sent(
            export_commands.MarkSent(
                bank_excel_export_id=export_id,
                sent_at=payload.sent_at,
                submission_channel=payload.submission_channel,
                note=payload.note,
            ),
            uow=uow,
            storage=runtime.storage,
            policy=EXPORT_REDACTION,
            actor=AuditActor(
                actor_type=actor.actor_type.value,
                actor_id=actor.actor_id,
                role_snapshot=tuple(sorted(actor.roles)),
                session_id=actor.session_id,
                authentication_assurance=actor.auth_level,
            ),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=idempotency_key,
            now=now,
        )
        # Rendered before the commit, on the same session, so the confirmation describes the row
        # the command just wrote rather than a re-read that could see somebody else's change.
        rendered = MarkSentConfirmation(
            **_detail_fields(
                result.export, _context_for(uow.session, runtime.storage, result.export)
            ),
            submission_channel=payload.submission_channel,
            note=payload.note,
        )
        uow.commit()

    return rendered
