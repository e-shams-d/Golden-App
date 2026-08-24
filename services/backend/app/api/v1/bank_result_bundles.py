"""The bundle's surface: bring it in, say what it might relate to, read it, close it.
`05_API_Specification.md` §18.

M8 slice 1. Four mutations and two reads, and the shape worth stating is what is **not** here.

**No `start-review` route.** `05_API_Specification.md:1693` defines one and
`permission_catalog.yaml` has no permission for it — not an ungranted permission but no entry at
all, so deny-by-default would answer `403` to every caller. Building it would ship a route nobody
can use; inventing a permission is not an implementer's decision, because a permission is a grant
and grants are seeded and audited. The transition it would perform,
`06_Workflows_and_State_Machines.md:995`'s `uploaded --> ready_for_manual_review: direct manual
mode`, happens at upload instead — Phase 1A has no normalization job to take the other branch, so
upload *is* the direct manual mode. Q-7 in the M8 plan carries it.

**No `ai-extraction` route.** `:1721` defines one and marks it Phase 1B+.
`04_Database_Schema.md:1259` keeps `ai_auto_segmentation` feature-flagged, and slice 7 asserts no
AI path is reachable at all.

**A trader reaches none of this.** Every route declares a permission, and `ActorContext` refuses by
invariant to give a trader actor any permission — so the refusal is structural rather than a check
somebody could forget on the seventh route.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor, requires
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.commands import bank_result_bundle as bundle_commands
from app.core.errors import ErrorEnvelope, NotFoundError, PreconditionRequiredError
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.bank import BankProfile
from app.db.models.bank_result_bundle import (
    BUNDLE_STATUSES,
    FILE_ROLES,
    LINK_ACTIVE,
    LINK_METHODS,
    SOURCE_TYPES,
    BankResultBundle,
    BankResultBundleBatchLink,
    BankResultBundleFile,
)
from app.db.models.file_object import FileObject
from app.db.models.identity import AdminUser
from app.db.models.payment_batch import PaymentBatch
from app.security.actor import ActorContext
from app.security.permissions import declare

router = APIRouter(prefix="/bank-result-bundles", tags=["bank-result-bundles"])

# A bundle is a list of somebody's payments as the bank sees them, so the audit trail masks IBANs
# for the same reason M7's export surface does.
BUNDLE_REDACTION = RedactionPolicy(mask_iban=True)

RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "The caller lacks the bundle permission."},
    404: {"model": ErrorEnvelope, "description": "No such bundle, batch, version or file."},
    409: {
        "model": ErrorEnvelope,
        "description": "The bundle is closed, or a rule refuses the change.",
    },
    **VALIDATION_ERROR_RESPONSE,
}


class AttachFileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: uuid.UUID
    sequence_number: int = Field(ge=1)
    file_role: str = Field(default="source")
    page_count: int | None = Field(default=None, ge=1)


class UploadBundleRequest(BaseModel):
    """`05_API_Specification.md:1642`."""

    model_config = ConfigDict(extra="forbid")

    source_type: str = Field(min_length=1, max_length=32)
    files: list[AttachFileRequest] = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=4000)
    bank_profile_id: uuid.UUID | None = None


class LinkBatchRequest(BaseModel):
    """`05_API_Specification.md:1685`."""

    model_config = ConfigDict(extra="forbid")

    payment_batch_id: uuid.UUID
    link_method: str = Field(min_length=1, max_length=32)
    payment_batch_version_id: uuid.UUID | None = None


class CloseBundleRequest(BaseModel):
    """`05_API_Specification.md:1705`.

    `unresolved_dispositions` is absent and slice 1 says why in the command: it needs segments,
    which slice 2 creates. A field accepted and ignored would be worse than one that is not there.
    """

    model_config = ConfigDict(extra="forbid")

    resolution_note: str = Field(min_length=1, max_length=4000)


class BundleFileEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    file_id: uuid.UUID
    file_name: str
    sequence_number: int
    file_role: str
    page_count: int | None


class BatchLinkEntry(BaseModel):
    """One recorded belief, and the field that keeps it honest.

    `proves_payment` is always `False` and is in the response on purpose. §12.3 at `:1199` says the
    association "does not prove payment completion"; a screen showing a batch beside a bundle will
    be read as a claim unless something says otherwise, and the place to say it is the payload
    rather than a comment nobody renders.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    payment_batch_id: uuid.UUID
    batch_number: str
    payment_batch_version_id: uuid.UUID | None
    link_method: str
    status: str
    created_by: str | None
    created_at: datetime
    replaced_at: datetime | None
    proves_payment: bool = False


class BundleSummary(BaseModel):
    """One row of the bundle queue. `05_API_Specification.md:1676`."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    bundle_number: str
    status: str
    source_type: str
    bank: str | None
    uploaded_by: str | None
    uploaded_at: datetime
    file_count: int
    segment_count: int
    resolved_segment_count: int
    unresolved_segment_count: int
    record_version: int


class BundleDetail(BundleSummary):
    """Everything §16's review workspace needs to open a bundle.

    `15_Agent_Implementation_Plan.md:1028` lists eleven items for that workspace and this carries
    the ones that are facts about the bundle: its summary, its files, and what it is linked to.
    Segments arrive in slice 2 and previews in slice 5, and `API-BUNDLE-001` parses §16's list so
    the API and slice 6's screen answer to one source rather than two copies of it.
    """

    model_config = ConfigDict(extra="forbid")

    notes: str | None
    closed_at: datetime | None
    closed_by: str | None
    files: list[BundleFileEntry]
    batch_links: list[BatchLinkEntry]
    # The three vocabularies a screen needs in order to offer choices it knows the server accepts.
    # Sent rather than duplicated in the client, for the reason M7's screens plan gives about
    # parsing one source: a client-side copy disagrees the day the server gains a value.
    accepted_source_types: list[str]
    accepted_file_roles: list[str]
    accepted_link_methods: list[str]


def _username(session: Session, admin_user_id: uuid.UUID | None) -> str | None:
    if admin_user_id is None:
        return None
    found = session.get(AdminUser, admin_user_id)
    return found.username if found is not None else None


def _bank_name(session: Session, bank_profile_id: uuid.UUID | None) -> str | None:
    if bank_profile_id is None:
        return None
    profile = session.get(BankProfile, bank_profile_id)
    return profile.name if profile is not None else None


def _summary(session: Session, bundle: BankResultBundle) -> BundleSummary:
    files = (
        session.scalar(
            select(func.count())
            .select_from(BankResultBundleFile)
            .where(BankResultBundleFile.bank_result_bundle_id == bundle.id)
        )
        or 0
    )
    return BundleSummary(
        id=bundle.id,
        bundle_number=bundle.bundle_number,
        status=bundle.status,
        source_type=bundle.source_type,
        bank=_bank_name(session, bundle.bank_profile_id),
        uploaded_by=_username(session, bundle.uploaded_by_admin_user_id),
        uploaded_at=bundle.uploaded_at,
        file_count=files,
        segment_count=bundle.segment_count,
        resolved_segment_count=bundle.resolved_segment_count,
        unresolved_segment_count=bundle.unresolved_segment_count,
        record_version=bundle.record_version,
    )


def _detail(session: Session, bundle: BankResultBundle) -> BundleDetail:
    files = session.execute(
        select(BankResultBundleFile, FileObject.original_filename)
        .join(FileObject, BankResultBundleFile.file_id == FileObject.id)
        .where(BankResultBundleFile.bank_result_bundle_id == bundle.id)
        .order_by(BankResultBundleFile.sequence_number, BankResultBundleFile.file_role)
    ).all()

    links = session.execute(
        select(BankResultBundleBatchLink, PaymentBatch.batch_number)
        .join(PaymentBatch, BankResultBundleBatchLink.payment_batch_id == PaymentBatch.id)
        .where(BankResultBundleBatchLink.bank_result_bundle_id == bundle.id)
        .order_by(BankResultBundleBatchLink.created_at)
    ).all()

    return BundleDetail(
        **_summary(session, bundle).model_dump(),
        notes=bundle.notes,
        closed_at=bundle.closed_at,
        closed_by=_username(session, bundle.closed_by_admin_user_id),
        files=[
            BundleFileEntry(
                id=row.id,
                file_id=row.file_id,
                file_name=name,
                sequence_number=row.sequence_number,
                file_role=row.file_role,
                page_count=row.page_count,
            )
            for row, name in files
        ],
        batch_links=[
            BatchLinkEntry(
                id=link.id,
                payment_batch_id=link.payment_batch_id,
                batch_number=number,
                payment_batch_version_id=link.payment_batch_version_id,
                link_method=link.link_method,
                status=link.status,
                created_by=_username(session, link.created_by_admin_user_id),
                created_at=link.created_at,
                replaced_at=link.replaced_at,
            )
            for link, number in links
        ],
        accepted_source_types=list(SOURCE_TYPES),
        accepted_file_roles=list(FILE_ROLES),
        accepted_link_methods=list(LINK_METHODS),
    )


def _audit_actor(actor: ActorContext) -> AuditActor:
    return AuditActor(
        actor_type=actor.actor_type.value,
        actor_id=actor.actor_id,
        role_snapshot=tuple(sorted(actor.roles)),
        session_id=actor.session_id,
        authentication_assurance=actor.auth_level,
    )


@router.post(
    "",
    response_model=BundleDetail,
    status_code=201,
    operation_id="uploadBankResultBundle",
    summary="Record a delivery of bank-returned evidence.",
    responses=RESPONSES,
    dependencies=[requires(declare("bank_result_bundle.upload"))],
)
def upload_bank_result_bundle(
    payload: UploadBundleRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> BundleDetail:
    """`POST /api/v1/bank-result-bundles`.

    **The files must already exist.** `command_catalog.yaml:267` names both
    `bank_result_bundle.upload` and `file.upload` as this command's permissions, which is the
    catalogue saying the same thing: the bytes arrive through M4's upload endpoint and this command
    records what they are part of. `08_Bank_File_and_Result_Processing.md:137` forbids overwriting
    an original, and never holding a second copy is the cheapest way to honour it.

    **`Idempotency-Key` is required** per `command_catalog.yaml:264`. A retried upload must not
    produce two bundles claiming the same delivery.
    """

    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")

    now = utc_now()
    with runtime.uow_factory() as uow:
        bundle = bundle_commands.upload_bundle(
            bundle_commands.UploadBundle(
                source_type=payload.source_type,
                files=tuple(
                    bundle_commands.AttachedFile(
                        file_id=entry.file_id,
                        sequence_number=entry.sequence_number,
                        file_role=entry.file_role,
                        page_count=entry.page_count,
                    )
                    for entry in payload.files
                ),
                notes=payload.notes,
                bank_profile_id=payload.bank_profile_id,
            ),
            uow=uow,
            policy=BUNDLE_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            now=now,
        )
        rendered = _detail(uow.session, bundle)
        uow.commit()

    return rendered


@router.get(
    "",
    response_model=list[BundleSummary],
    operation_id="listBankResultBundles",
    summary="The bundle queue, or all of them.",
    responses=RESPONSES,
    dependencies=[requires(declare("bank_result_bundle.read"))],
)
def list_bank_result_bundles(
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    awaiting_review: Annotated[bool, Query()] = True,
) -> list[BundleSummary]:
    """`GET /api/v1/bank-result-bundles`. `05_API_Specification.md:1676`.

    `awaiting_review` defaults to **true**, and the filtered set is exactly the predicate of
    `idx_bundle_review_queue` — the index `04_Database_Schema.md:1659` specifies for this query. A
    filter that did not match its index would be a queue that reads the whole table.

    The unfiltered list stays available, for M7 slice 1's reason: a history that becomes unreachable
    is a history nobody can audit.
    """

    del actor
    open_states = ("ready_for_manual_review", "partially_matched", "failed")
    with runtime.uow_factory() as uow:
        statement = select(BankResultBundle)
        if awaiting_review:
            statement = statement.where(BankResultBundle.status.in_(open_states))
        rows = uow.session.scalars(
            statement.order_by(BankResultBundle.uploaded_at.desc())
        ).all()
        return [_summary(uow.session, bundle) for bundle in rows]


@router.get(
    "/{bundle_id}",
    response_model=BundleDetail,
    operation_id="getBankResultBundle",
    summary="Everything needed to open a bundle for review.",
    responses=RESPONSES,
    dependencies=[requires(declare("bank_result_bundle.read"))],
)
def get_bank_result_bundle(
    bundle_id: uuid.UUID,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> BundleDetail:
    """`GET /api/v1/bank-result-bundles/{bundle_id}`. `05_API_Specification.md:1677`."""

    del actor
    with runtime.uow_factory() as uow:
        bundle = uow.session.get(BankResultBundle, bundle_id)
        if bundle is None:
            raise NotFoundError()
        return _detail(uow.session, bundle)


@router.post(
    "/{bundle_id}/batch-links",
    response_model=BatchLinkEntry,
    status_code=201,
    operation_id="linkBankResultBundleToBatch",
    summary="Record that a bundle appears to relate to a batch. Not evidence of payment.",
    responses=RESPONSES,
    dependencies=[requires(declare("bank_result_bundle.link_batch"))],
)
def link_bundle_to_batch(
    bundle_id: uuid.UUID,
    payload: LinkBatchRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> BatchLinkEntry:
    """`POST /api/v1/bank-result-bundles/{bundle_id}/batch-links`. `05_API_Specification.md:1685`.

    **`:1688`: "This association is operational context only and does not prove payment
    completion."** The response says so in a field, because a screen putting a batch number beside
    a bundle will be read as a claim unless something contradicts it.

    **The permission is catalogued and the command is not.** `bank_result_bundle.link_batch` is in
    `permission_catalog.yaml:528` and seeded to `accountant`; `command_catalog.yaml` has no row and
    `audit_outbox_catalog.yaml` names no action. That is DOC-CONFLICT-052's shape for the third
    time, and the route is implemented against the permission's own identifier because M6 slice 4
    set that precedent under the same conflict. `app/audit/registry.py` declares the audit action
    `catalogued=False` with its reason rather than pretending the catalogue covers it.

    **No `Idempotency-Key`.** No catalogue row means no idempotency contract to honour, and
    `uq_bundle_links_active_pair` makes a repeat harmless: the second call replaces the first link
    with an identical one and leaves the old row as evidence. Recorded rather than assumed.
    """

    now = utc_now()
    with runtime.uow_factory() as uow:
        link = bundle_commands.link_to_batch(
            bundle_commands.LinkBundleToBatch(
                bank_result_bundle_id=bundle_id,
                payment_batch_id=payload.payment_batch_id,
                link_method=payload.link_method,
                payment_batch_version_id=payload.payment_batch_version_id,
            ),
            uow=uow,
            policy=BUNDLE_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            now=now,
        )
        uow.session.flush()
        batch = uow.session.get(PaymentBatch, link.payment_batch_id)
        rendered = BatchLinkEntry(
            id=link.id,
            payment_batch_id=link.payment_batch_id,
            batch_number=batch.batch_number if batch is not None else "",
            payment_batch_version_id=link.payment_batch_version_id,
            link_method=link.link_method,
            status=link.status,
            created_by=_username(uow.session, link.created_by_admin_user_id),
            created_at=link.created_at,
            replaced_at=link.replaced_at,
        )
        uow.commit()

    return rendered


@router.post(
    "/{bundle_id}/close",
    response_model=BundleDetail,
    operation_id="closeBankResultBundle",
    summary="Record that everything in this bundle has been dealt with.",
    responses=RESPONSES,
    dependencies=[requires(declare("bank_result_bundle.close"))],
)
def close_bank_result_bundle(
    bundle_id: uuid.UUID,
    payload: CloseBundleRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> BundleDetail:
    """`POST /api/v1/bank-result-bundles/{bundle_id}/close`. `05_API_Specification.md:1700`.

    **The counts are recomputed before the decision.** Closing asserts that everything in the
    bundle has been dealt with, and asserting that from a cached number would be asserting it from
    something that may have drifted — `04_Database_Schema.md:1179` says these are not independent
    truth.

    **No `If-Match`, and it is recorded rather than overlooked.** `:1702` shows one and
    `bank_result_bundles` does carry `record_version`, so unlike M7's mark-sent this could take
    one. It does not yet because slice 1 is the only writer and there is nothing to race with;
    slice 2 gives segments a way to change a bundle underneath a reader, and that is the slice
    where the precondition earns its place. `Idempotency-Key` is required now, per
    `command_catalog.yaml:593`.
    """

    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")

    now = utc_now()
    with runtime.uow_factory() as uow:
        bundle = bundle_commands.close_bundle(
            bundle_commands.CloseBundle(
                bank_result_bundle_id=bundle_id,
                resolution_note=payload.resolution_note,
            ),
            uow=uow,
            policy=BUNDLE_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            now=now,
        )
        rendered = _detail(uow.session, bundle)
        uow.commit()

    return rendered


# Referenced so the constant is not dead: the CHECK's value list and the API's accepted values are
# the same set, and a route that accepted a status the table refuses would answer 500.
_ALL_STATUSES = BUNDLE_STATUSES
_ACTIVE = LINK_ACTIVE
