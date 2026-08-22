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
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

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
from app.db.models.bank_export import BankExcelExport
from app.db.models.file_object import FileObject
from app.files.download import open_stream
from app.security.actor import ActorContext
from app.security.permissions import declare

router = APIRouter(prefix="/bank-exports", tags=["bank-exports"])

EXPORT_REDACTION = RedactionPolicy(mask_iban=True)

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
    """`05_API_Specification.md:1500-1505`, plus the two fields §2.5 of the M7 plan argues for.

    `sendable` and `awaiting_send_confirmation` are not in document 05 and are deliberate.
    `15_Agent_Implementation_Plan.md:989` — "Downloading does not mean sent" — is this milestone's
    central human-factors risk: an accountant who downloads a file, emails it to the bank and
    forgets to come back leaves the system believing the payment was never made, and the next
    reconciliation cycle chases it.

    `SVC-SENT-002` asks that such an export be *visibly* unsent rather than merely lacking a
    timestamp. A screen cannot show what the response does not say, and "the timestamp is null"
    is not something a UI should have to interpret.
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


class MarkSentRequest(BaseModel):
    """`05_API_Specification.md:1523-1528`."""

    model_config = ConfigDict(extra="forbid")

    sent_at: datetime
    submission_channel: str = Field(min_length=1, max_length=64)
    note: str | None = Field(default=None, max_length=2000)


def _detail(export: BankExcelExport) -> ExportDetail:
    return ExportDetail(
        id=export.id,
        export_number=export.export_number,
        export_type=export.export_type,
        status=export.status,
        sendable=export.export_type == "final" and export.status != "quarantined",
        # The whole of `SVC-SENT-002`, in one derived field: downloaded, still unsent, and
        # therefore something a person needs to be reminded about.
        awaiting_send_confirmation=(
            export.export_type == "final"
            and export.downloaded_at is not None
            and export.sent_to_bank_marked_at is None
        ),
        row_count=export.row_count,
        total_amount_irr=str(export.total_amount_irr),
        content_hash=export.content_hash,
        file_sha256_hash=export.file_sha256_hash,
        payment_batch_version_id=export.payment_batch_version_id,
        batch_approval_id=export.batch_approval_id,
        generated_at=export.generated_at,
        downloaded_at=export.downloaded_at,
        sent_to_bank_marked_at=export.sent_to_bank_marked_at,
    )


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
        return _detail(export)


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
    response_model=ExportDetail,
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
) -> ExportDetail:
    """`POST /api/v1/bank-exports/{export_id}/mark-sent-to-bank`.

    **Nothing here contacts a bank.** §15.7 makes submission manual by design, so this records a
    claim a person makes — which is why it captures the channel they used and what they said
    about it. The record has to be enough for somebody else to check the claim later.

    **No `If-Match`.** Document 05 shows one; §11.8 gives this table no `record_version`; and
    `command_catalog.yaml:203` says `open_conflict_if_match_target_not_defined` — the catalogue
    describing an unresolved contract rather than a requirement being ignored. G-13 records it.
    `Idempotency-Key` is required, and `CON-SENT-001` is what makes a retry safe.
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
        rendered = _detail(result.export)
        uow.commit()

    return rendered
