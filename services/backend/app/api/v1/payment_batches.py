"""What a batch would be, computed without writing anything.

M6 slice 1. `05_API_Specification.md:1268-1315` specifies one route here and ends with the
sentence that shapes it: "Preview is advisory and not approvable. The create command
revalidates everything."

**This route is not a command.** No `Idempotency-Key`, no `If-Match`, no audit row, no outbox
event, no idempotency record. `15_Agent_Implementation_Plan.md:893` asks that the preview "does
not mutate records"; the negative control in `tests/integration/test_batch_preview.py` asserts
the stronger claim, because a read that leaves a governance trace is a write nobody has noticed
yet.

**It is guarded by `payment_batch.read`, not `payment_batch.create`.** A route that writes
nothing must not require the grant that authorises writing — otherwise the only role able to
look at a proposed batch is the role able to make one. Document 05 names no permission here and
`command_catalog.yaml` excludes queries, so nothing in governance decides it; the choice is
recorded as G-2 in `docs/handoff/M6_IMPLEMENTATION_PLAN.md` §4 and is the narrower of the two
candidates.

**Every monetary field leaves as a string.** `MONEY_TIME_CONTRACT.md:17-18`, against document
05's own unquoted examples at `:1300` and `:1307` — DOC-CONFLICT-050, now on the batch surface.
The contract wins; document 05 is owed an editorial fix.

Covers: API-BATCH-001, API-BATCH-002, CON-BATCH-001, SEC-BATCH-001.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import RecentAuthRequiredError, authenticated_actor, requires
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.batching.splitting import SplittingRules, split
from app.commands import payment_batch as commands
from app.commands import payment_batch_approval as approval_commands
from app.core.errors import (
    ConflictError,
    ErrorEnvelope,
    NotFoundError,
    PreconditionRequiredError,
    VersionConflictError,
)
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.bank import BankProfileVersion
from app.db.models.payment_batch import (
    BatchApproval,
    PaymentAttemptAllocation,
    PaymentBatch,
    PaymentBatchItem,
    PaymentBatchVersion,
)
from app.db.models.payment_request import PaymentRequest, PaymentRequestRevision
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.security.actor import ActorContext
from app.security.permissions import declare
from app.security.step_up import StepUpRefused

router = APIRouter(prefix="/payment-batches", tags=["payment-batches"])

RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "The caller lacks payment_batch.read."},
    404: {"model": ErrorEnvelope, "description": "A named request or bank version is missing."},
    409: {
        "model": ErrorEnvelope,
        "description": "A named revision or record version is no longer current.",
    },
    **VALIDATION_ERROR_RESPONSE,
}

# The state a request must be in to be previewed. Document 06 makes `eligible_for_batching`
# the entry to batching, and M5's `mark-eligible-for-batching` is what reaches it.
ELIGIBLE = "eligible_for_batching"


class PreviewItem(BaseModel):
    """`05_API_Specification.md:1274-1280`.

    All three fields are required, and the two expectations are the point: a preview computed
    against a revision that has since been corrected is not a stale answer, it is a *wrong*
    one, and it looks exactly like a right one.
    """

    model_config = ConfigDict(extra="forbid")

    payment_request_id: uuid.UUID
    expected_revision_id: uuid.UUID
    expected_record_version: int = Field(ge=1)


class PreviewRequest(BaseModel):
    """`05_API_Specification.md:1272-1288`.

    `bank_account_id` and `bank_mapping_id` are accepted and not consulted in this slice: the
    split depends on the profile version's limits, and the account and mapping shape the export
    M7 builds. They are declared because the document declares them and refusing them would
    reject the documented payload — and they are named here rather than silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[PreviewItem] = Field(min_length=1)
    bank_profile_version_id: uuid.UUID
    bank_account_id: uuid.UUID | None = None
    bank_mapping_id: uuid.UUID | None = None
    apply_split_rules: bool = True


class ProposedRowResponse(BaseModel):
    """`05_API_Specification.md:1293-1308`, with the amount as a string."""

    model_config = ConfigDict(extra="forbid")

    source_request_id: uuid.UUID
    source_revision_id: uuid.UUID
    row_order: int
    amount_irr: str
    beneficiary_name: str
    beneficiary_iban: str
    split_reason: str


class PreviewValidation(BaseModel):
    """`:1309-1312`. Advisory, and both lists are always present.

    Present even when empty, because a client that has to distinguish "no warnings" from "the
    field was omitted" will get it wrong in one direction, and the safer direction is not the
    one it will guess.
    """

    model_config = ConfigDict(extra="forbid")

    errors: list[str]
    warnings: list[str]


class PreviewResponse(BaseModel):
    """`:1291-1313`, with every monetary field a base-10 integer string."""

    model_config = ConfigDict(extra="forbid")

    proposed_rows: list[ProposedRowResponse]
    row_count: int
    total_amount_irr: str
    validation: PreviewValidation


@router.post(
    "/preview",
    response_model=PreviewResponse,
    operation_id="previewPaymentBatch",
    summary="What a batch would be. Advisory, and writes nothing.",
    responses=RESPONSES,
    dependencies=[requires(declare("payment_batch.read"))],
)
def preview_batch(
    payload: PreviewRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> PreviewResponse:
    """`POST /api/v1/payment-batches/preview`.

    Internal-only: there is no trader audience for a proposed bank file, so the guard is a
    permission rather than `owned_or_permitted`, and no ownership scope is filtered.

    The evaluation instant is taken once and passed to every split, so a preview that straddles
    a bank's cutoff second does not apply two different limits to two of its own rows.
    """

    at = utc_now()

    with runtime.uow_factory() as uow:
        version = uow.session.get(BankProfileVersion, payload.bank_profile_version_id)
        if version is None:
            raise NotFoundError()

        rules = SplittingRules(
            default_transfer_limit_irr=version.default_transfer_limit_irr,
            after_cutoff_transfer_limit_irr=version.after_cutoff_transfer_limit_irr,
            cutoff_time=version.cutoff_time,
            # `apply_split_rules: false` asks for the unsplit shape, which is the same
            # question `splitting_enabled: false` answers — so it is expressed as the rule
            # rather than as a second branch through the engine.
            splitting_enabled=version.splitting_enabled and payload.apply_split_rules,
        )

        rows: list[ProposedRowResponse] = []
        for item in payload.items:
            request, revision = _current(uow.session, item)
            for proposed in split(int(revision.amount_irr), rules, at):
                rows.append(
                    ProposedRowResponse(
                        source_request_id=request.id,
                        source_revision_id=revision.id,
                        # Continuous across the whole file, not restarted per request: the
                        # order is the order of the rows a bank will read.
                        row_order=len(rows) + 1,
                        amount_irr=str(proposed.amount_irr),
                        beneficiary_name=revision.beneficiary_name_snapshot,
                        beneficiary_iban=revision.beneficiary_iban_snapshot,
                        split_reason=proposed.split_reason,
                    )
                )

        # No commit. The unit of work is entered for the reads alone, and leaving without
        # committing is what makes that visible in the code rather than only in a comment.

    return PreviewResponse(
        proposed_rows=rows,
        row_count=len(rows),
        total_amount_irr=str(sum(int(row.amount_irr) for row in rows)),
        validation=PreviewValidation(errors=[], warnings=[]),
    )


class CreateBatchRequest(BaseModel):
    """`05_API_Specification.md:1318-1322`: "the same selection/configuration contract as preview".

    Same shape as `PreviewRequest` with two differences, both narrowings. `bank_account_id` and
    `bank_mapping_id` become **required**, because `payment_batch_versions` makes both NOT NULL:
    `FINANCIAL_INTEGRITY_BASELINE.md` §1 requires a final artifact to name what produced it, and
    a version that cannot say which mapping rendered it cannot be re-rendered. A preview writes
    nothing, so it can afford to omit them.

    Not expressed as a subclass of `PreviewRequest`. Inheriting would put the two routes' request
    bodies in one inheritance chain in the generated OpenAPI, so widening the preview later would
    silently widen the command too.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[PreviewItem] = Field(min_length=1)
    bank_profile_version_id: uuid.UUID
    bank_account_id: uuid.UUID
    bank_mapping_id: uuid.UUID
    apply_split_rules: bool = True


class BatchSummary(BaseModel):
    """`05_API_Specification.md:1327-1332`."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    batch_number: str
    status: str
    record_version: int


class VersionSummary(BaseModel):
    """`:1333-1341`, with `total_amount_irr` a string.

    Document 05 shows `4500000000` unquoted at `:1338`. `MONEY_TIME_CONTRACT.md:17-18` requires
    base-10 integer strings and forbids `Number`; the contract wins, as it did in M5 slice 4 and
    on the preview surface. DOC-CONFLICT-050, third surface.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    version_number: int
    status: str
    row_count: int
    total_amount_irr: str
    content_hash: str
    validation_summary: dict[str, list[str]]


class BatchCreated(BaseModel):
    """`:1325-1343`. `replayed` is not in document 05 and is added deliberately.

    A caller retrying after a timeout has no other way to tell "your batch was created" from
    "your batch was created twice" — and the second is the thing an accountant would go looking
    for in the bank file. The same field is on M5's revision response for the same reason.
    """

    model_config = ConfigDict(extra="forbid")

    batch: BatchSummary
    current_version: VersionSummary
    replayed: bool


class BatchItemResponse(BaseModel):
    """One row of a version, as `04_Database_Schema.md` §11.6 stores it."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    row_order: int
    payment_attempt_id: uuid.UUID
    amount_irr: str
    beneficiary_name: str
    beneficiary_iban: str
    description: str | None
    row_hash: str


class BatchDetail(BaseModel):
    """`05_API_Specification.md:1347-1353`, restricted to what M6 can answer.

    Document 05 asks the detail read to include "current version, historical versions, approval
    summary, exports, result progress, record version, and allowed actions". Three of those
    describe things M6 cannot reach: there is no approval (M7), no export (M7), and no result
    (M8). They are **omitted rather than returned empty**, because an empty `exports: []` reads
    as "this batch has no exports" when the truth is "this deployment cannot have any", and a
    screen would render the first as a fact.

    `historical_versions` is present and will be non-empty from slice 4, which is the first
    thing that supersedes one.
    """

    model_config = ConfigDict(extra="forbid")

    batch: BatchSummary
    current_version: VersionSummary
    historical_versions: list[VersionSummary]
    items: list[BatchItemResponse]
    active_allocation_count: int


class BatchListEntry(BaseModel):
    """One line of the list. Enough to choose a batch, not enough to be a detail read."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    batch_number: str
    status: str
    record_version: int
    row_count: int
    total_amount_irr: str


class BatchList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batches: list[BatchListEntry]


CREATE_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "The caller lacks payment_batch.create."},
    404: {"model": ErrorEnvelope, "description": "A named request or configuration is missing."},
    409: {
        "model": ErrorEnvelope,
        "description": (
            "A named revision or record version is stale, an attempt is already allocated, "
            "or the Idempotency-Key was reused with a different body."
        ),
    },
    # 400 and not 422: `api_error_catalog.yaml:16` gives `BUSINESS_RULE_VIOLATION` http 400,
    # "Domain rule failed". 422 is the validation-envelope code and belongs to a malformed body,
    # which is a different thing a client handles differently.
    400: {
        "model": ErrorEnvelope,
        "description": "A named request is not at eligible_for_batching.",
    },
    428: {"model": ErrorEnvelope, "description": "Idempotency-Key is required."},
    **VALIDATION_ERROR_RESPONSE,
}

# Redaction for the batch surface. `mask_iban=True` for the same reason the request surface
# uses it: an audit row that carries a full IBAN widens where a payment destination lives, and
# the row already names the attempt that holds it.
BATCH_REDACTION = RedactionPolicy(mask_iban=True)


@router.post(
    "",
    response_model=BatchCreated,
    status_code=201,
    operation_id="createPaymentBatch",
    summary="Create a batch and its first draft version, with every attempt allocated.",
    responses=CREATE_RESPONSES,
    dependencies=[requires(declare("payment_batch.create"))],
)
def create_batch(
    payload: CreateBatchRequest,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> BatchCreated:
    """`POST /api/v1/payment-batches`.

    **`Idempotency-Key` is required and `If-Match` is not.** `command_catalog.yaml:111` says
    `"idempotency": "required"`, and the reason is specific: a create that runs twice on a
    network retry would allocate the same attempts to two batches. There is no `If-Match`
    because there is no resource to be stale against — the expectations are per-item and live in
    the body, which is what `:1274-1280` specifies and why 409 rather than 412 is the refusal.

    The command owns every read and every refusal. This function exists to turn a header into a
    precondition, a payload into a command, and a result into JSON.
    """

    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")

    now = utc_now()
    with runtime.uow_factory() as uow:
        result = commands.create_batch(
            commands.CreateBatch(
                items=tuple(
                    commands.BatchSelection(
                        payment_request_id=item.payment_request_id,
                        expected_revision_id=item.expected_revision_id,
                        expected_record_version=item.expected_record_version,
                    )
                    for item in payload.items
                ),
                bank_profile_version_id=payload.bank_profile_version_id,
                bank_account_id=payload.bank_account_id,
                bank_mapping_id=payload.bank_mapping_id,
                apply_split_rules=payload.apply_split_rules,
            ),
            uow=uow,
            policy=BATCH_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=idempotency_key,
            now=now,
        )
        rendered = BatchCreated(
            batch=_batch_summary(result.batch),
            current_version=_version_summary(result.version),
            replayed=result.replayed,
        )
        uow.commit()

    response.headers["ETag"] = f'"rv-{rendered.batch.record_version}"'
    return rendered


@router.get(
    "",
    response_model=BatchList,
    operation_id="listPaymentBatches",
    summary="Every batch, newest first.",
    responses=RESPONSES,
    dependencies=[requires(declare("payment_batch.read"))],
)
def list_batches(
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> BatchList:
    """`GET /api/v1/payment-batches`.

    **No ownership scope, and that is not an omission.** A batch has no trader: it is a file the
    centre sends to a bank, and its rows belong to many traders at once. `owned_or_permitted`
    would have nothing to scope on, and `app/security/ownership.py`'s `scoped()` takes an actor
    precisely so a route cannot invent a filter. The guard is the permission, and
    `permission_catalog.yaml:459` gives `payment_batch.read` to no trader role.

    A container nothing can read is a container nobody can act on, which is why this ships in the
    same slice as the create rather than waiting for a screen to need it.
    """

    del actor  # The guard consumed it; there is no per-actor filtering to do.

    with runtime.uow_factory() as uow:
        rows = (
            uow.session.execute(
                select(PaymentBatch, PaymentBatchVersion)
                # An outer join: a batch whose version row is missing would vanish from a list
                # built on an inner join, and vanishing is the one behaviour an operator cannot
                # debug. The composite deferred key makes it impossible, so this is belt to that
                # brace — and the `None` branch below says what it would mean.
                .outerjoin(
                    PaymentBatchVersion,
                    PaymentBatch.current_version_id == PaymentBatchVersion.id,
                )
                .order_by(PaymentBatch.created_at.desc())
            )
            .tuples()
            .all()
        )

        # Rendered inside the unit of work. Built outside it, every attribute access on these
        # rows raises `DetachedInstanceError` — which is what the first version of this route
        # did, and what `test_the_list_holds_every_batch_newest_first` caught. The detail read
        # below has always done it this way; the two now agree.
        listed = BatchList(
            batches=[
                BatchListEntry(
                    id=batch.id,
                    batch_number=batch.batch_number,
                    status=batch.status,
                    record_version=batch.record_version,
                    row_count=version.row_count if version else 0,
                    total_amount_irr=str(version.total_amount_irr) if version else "0",
                )
                for batch, version in rows
            ]
        )

    return listed


@router.get(
    "/{batch_id}",
    response_model=BatchDetail,
    operation_id="getPaymentBatch",
    summary="One batch, its current version, its history and its rows.",
    responses=RESPONSES,
    dependencies=[requires(declare("payment_batch.read"))],
)
def get_batch(
    batch_id: uuid.UUID,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> BatchDetail:
    """`GET /api/v1/payment-batches/{batch_id}`, per `05_API_Specification.md:1347-1353`.

    `active_allocation_count` is here because it is the only way a reader can see the invariant
    holding: it must equal `row_count` for a draft version whose every row owns its allocation,
    and slice 3's finalization refuses to proceed when it does not. Returning the number rather
    than a boolean means a screen can say *how many* rows are unallocated instead of only that
    something is wrong.
    """

    del actor

    with runtime.uow_factory() as uow:
        batch = uow.session.get(PaymentBatch, batch_id)
        if batch is None:
            raise NotFoundError()

        versions = (
            uow.session.execute(
                select(PaymentBatchVersion)
                .where(PaymentBatchVersion.payment_batch_id == batch.id)
                .order_by(PaymentBatchVersion.version_number.desc())
            )
            .scalars()
            .all()
        )
        current = next(
            (version for version in versions if version.id == batch.current_version_id), None
        )
        if current is None:  # pragma: no cover - the deferred composite key guarantees it
            raise NotFoundError()

        items = (
            uow.session.execute(
                select(PaymentBatchItem)
                .where(PaymentBatchItem.payment_batch_version_id == current.id)
                .order_by(PaymentBatchItem.row_order)
            )
            .scalars()
            .all()
        )
        allocated = uow.session.scalars(
            select(PaymentAttemptAllocation.id).where(
                PaymentAttemptAllocation.payment_batch_version_id == current.id,
                PaymentAttemptAllocation.released_at.is_(None),
            )
        ).all()

        detail = BatchDetail(
            batch=_batch_summary(batch),
            current_version=_version_summary(current),
            historical_versions=[
                _version_summary(version) for version in versions if version.id != current.id
            ],
            items=[
                BatchItemResponse(
                    id=item.id,
                    row_order=item.row_order,
                    payment_attempt_id=item.payment_attempt_id,
                    amount_irr=str(item.amount_irr),
                    beneficiary_name=item.beneficiary_name_snapshot,
                    beneficiary_iban=item.beneficiary_iban_snapshot,
                    description=item.description_snapshot,
                    row_hash=item.row_hash,
                )
                for item in items
            ],
            active_allocation_count=len(allocated),
        )

    response.headers["ETag"] = f'"rv-{detail.batch.record_version}"'
    return detail


class FinalizeVersionRequest(BaseModel):
    """`05_API_Specification.md:1376-1380`. One optional field.

    The note is the accountant's own sentence about what they checked, and it becomes the audit
    row's `reason`. Optional because document 05's example shows one and nothing requires it —
    making it mandatory would be an unmandated refusal, which is the mirror of the unmandated
    side effect this milestone has been avoiding.
    """

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=2000)


class VersionFinalized(BaseModel):
    """The batch and the version it just froze, plus whether this call was the one that did it."""

    model_config = ConfigDict(extra="forbid")

    batch: BatchSummary
    version: VersionSummary
    replayed: bool


FINALIZE_RESPONSES: dict[int | str, dict[str, object]] = {
    400: {
        "model": ErrorEnvelope,
        "description": (
            "A guard document 06 §16.2 lists refused: the version is not current or not a "
            "draft, a validation error exists, the counts or hashes do not recompute, a row "
            "does not own its allocation, a source revision moved, or the bank configuration "
            "is no longer active."
        ),
    },
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {
        "model": ErrorEnvelope,
        "description": "The caller lacks payment_batch_version.finalize.",
    },
    404: {"model": ErrorEnvelope, "description": "No such batch, or no such version in it."},
    409: {
        "model": ErrorEnvelope,
        "description": "The batch moved since it was read, or the Idempotency-Key was reused.",
    },
    412: {"model": ErrorEnvelope, "description": "The If-Match value is not a record version."},
    428: {
        "model": ErrorEnvelope,
        "description": "If-Match and Idempotency-Key are both required.",
    },
    **VALIDATION_ERROR_RESPONSE,
}


@router.post(
    "/{batch_id}/versions/{version_id}/finalize",
    response_model=VersionFinalized,
    operation_id="finalizePaymentBatchVersion",
    summary="Freeze a draft version as the exact thing a manager will approve.",
    responses=FINALIZE_RESPONSES,
    dependencies=[requires(declare("payment_batch_version.finalize"))],
)
def finalize_version(
    batch_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: FinalizeVersionRequest,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> VersionFinalized:
    """`POST /api/v1/payment-batches/{batch_id}/versions/{version_id}/finalize`.

    **Both headers are required, and they answer different questions.**
    `command_catalog.yaml:139-140` says `if_match_batch_and_lock_current_version` and
    `"idempotency": "required"`. `If-Match` is "is the batch still in the state you read", which
    refuses an accountant acting on a stale screen. `Idempotency-Key` is "have I already
    finalized this", which makes a retry after a timeout return the first answer instead of
    meeting a `draft`-only guard and reporting a failure for work that succeeded.

    **`If-Match` targets the batch, not the version.** A version is an immutable snapshot and has
    no `record_version` — giving it one would invite a compare-and-swap against a record nobody
    may modify, which `app/db/base.py:record_version_column` warns about in as many words.

    **The guard is `payment_batch_version.finalize`, which is not `payment_batch.create`.**
    `permission_catalog.yaml:472` gives it to `accountant` with the `batch_finalize` constraint,
    and `FINANCIAL_INTEGRITY_BASELINE.md` §5 is why it is separate: the actor recorded here is
    the one M7 must refuse as an approver, so conflating it with any other grant would blur the
    identity the separation rule compares.
    """

    if if_match is None:
        raise PreconditionRequiredError("If-Match")
    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")
    expected = _parse_record_version(if_match)

    now = utc_now()
    with runtime.uow_factory() as uow:
        result = commands.finalize_version(
            commands.FinalizeVersion(
                payment_batch_id=batch_id,
                payment_batch_version_id=version_id,
                expected_batch_record_version=expected,
                note=payload.note,
            ),
            uow=uow,
            policy=BATCH_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=idempotency_key,
            now=now,
        )
        rendered = VersionFinalized(
            batch=_batch_summary(result.batch),
            version=_version_summary(result.version),
            replayed=result.replayed,
        )
        uow.commit()

    response.headers["ETag"] = f'"rv-{rendered.batch.record_version}"'
    return rendered


class CreateReplacementVersionRequest(BaseModel):
    """`05_API_Specification.md:1361-1368`. The selection contract again, plus a reason.

    The reason is optional and lands in the audit row. §16.5 says a replacement "never edits an
    approved/finalized version" and gives no required field, so requiring one would be a stricter
    refusal than the document states.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[PreviewItem] = Field(min_length=1)
    bank_profile_version_id: uuid.UUID
    bank_account_id: uuid.UUID
    bank_mapping_id: uuid.UUID
    apply_split_rules: bool = True
    reason: str | None = Field(default=None, max_length=2000)


class CancelBatchRequest(BaseModel):
    """`06_Workflows_and_State_Machines.md` §29.2, draft half.

    **No required reason.** §29.2 attaches "with reason" to the *ready-for-approval* case and not
    to the draft case, so demanding one here would be an unmandated refusal — the mirror of the
    unmandated side effect this milestone has been avoiding, and the mistake M5 slice 7 made by
    requiring a cancellation reason §29.1 does not ask for.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=2000)


REPLACEMENT_RESPONSES: dict[int | str, dict[str, object]] = {
    400: {
        "model": ErrorEnvelope,
        "description": (
            "The batch is cancelled, or a named request is not eligible for batching."
        ),
    },
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {
        "model": ErrorEnvelope,
        "description": "The caller lacks payment_batch_version.create.",
    },
    404: {"model": ErrorEnvelope, "description": "No such batch, or a named row is missing."},
    409: {
        "model": ErrorEnvelope,
        "description": "A named revision is stale, or the Idempotency-Key was reused.",
    },
    412: {"model": ErrorEnvelope, "description": "The If-Match value is stale or malformed."},
    428: {
        "model": ErrorEnvelope,
        "description": "If-Match and Idempotency-Key are both required.",
    },
    **VALIDATION_ERROR_RESPONSE,
}

CANCEL_RESPONSES: dict[int | str, dict[str, object]] = {
    400: {
        "model": ErrorEnvelope,
        "description": (
            "The batch is not a draft. §29.2 also permits cancelling a ready-for-approval "
            "batch with a reason and no permission authorises that — see DOC-CONFLICT-056."
        ),
    },
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "The caller lacks payment_batch.cancel_draft."},
    404: {"model": ErrorEnvelope, "description": "No such batch."},
    409: {"model": ErrorEnvelope, "description": "The Idempotency-Key was reused."},
    412: {"model": ErrorEnvelope, "description": "The If-Match value is stale or malformed."},
    428: {
        "model": ErrorEnvelope,
        "description": "If-Match and Idempotency-Key are both required.",
    },
    **VALIDATION_ERROR_RESPONSE,
}


@router.post(
    "/{batch_id}/versions",
    response_model=BatchCreated,
    status_code=201,
    operation_id="createReplacementPaymentBatchVersion",
    summary="A new draft version. The previous one becomes superseded.",
    responses=REPLACEMENT_RESPONSES,
    dependencies=[requires(declare("payment_batch_version.create"))],
)
def create_replacement_version(
    batch_id: uuid.UUID,
    payload: CreateReplacementVersionRequest,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> BatchCreated:
    """`POST /api/v1/payment-batches/{batch_id}/versions`, per `05_API_Specification.md:1361`.

    **Its own permission, `payment_batch_version.create`, and not the batch's create grant.**
    `permission_catalog.yaml:469` gives it separately, and the separation matters for the reason
    `FINANCIAL_INTEGRITY_BASELINE.md` §5 gives: the version-level acts are the ones whose actors a
    manager's approval must be checked against, so conflating them with the container-level grant
    would blur an identity the separation rule compares.

    The response is `BatchCreated` — the same shape the create returns, because the caller needs
    the same two things: the batch as it now stands and the version it now points at. `replayed`
    is what tells a retried caller they did not make a third version.
    """

    if if_match is None:
        raise PreconditionRequiredError("If-Match")
    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")
    expected = _parse_record_version(if_match)

    now = utc_now()
    with runtime.uow_factory() as uow:
        result = commands.create_replacement_version(
            commands.CreateReplacementVersion(
                payment_batch_id=batch_id,
                expected_batch_record_version=expected,
                items=tuple(
                    commands.BatchSelection(
                        payment_request_id=item.payment_request_id,
                        expected_revision_id=item.expected_revision_id,
                        expected_record_version=item.expected_record_version,
                    )
                    for item in payload.items
                ),
                bank_profile_version_id=payload.bank_profile_version_id,
                bank_account_id=payload.bank_account_id,
                bank_mapping_id=payload.bank_mapping_id,
                apply_split_rules=payload.apply_split_rules,
                reason=payload.reason,
            ),
            uow=uow,
            policy=BATCH_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=idempotency_key,
            now=now,
        )
        rendered = BatchCreated(
            batch=_batch_summary(result.batch),
            current_version=_version_summary(result.version),
            replayed=result.replayed,
        )
        uow.commit()

    response.headers["ETag"] = f'"rv-{rendered.batch.record_version}"'
    return rendered


@router.post(
    "/{batch_id}/cancel",
    response_model=BatchSummary,
    operation_id="cancelPaymentBatch",
    summary="Cancel a draft batch and release every allocation it holds.",
    responses=CANCEL_RESPONSES,
    dependencies=[requires(declare("payment_batch.cancel_draft"))],
)
def cancel_batch(
    batch_id: uuid.UUID,
    payload: CancelBatchRequest,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> BatchSummary:
    """`POST /api/v1/payment-batches/{batch_id}/cancel`, per `05_API_Specification.md:1539`.

    **Draft only, and the reason is a missing permission rather than a missing arrow.** §29.2
    permits cancelling a ready-for-approval batch with a reason;
    `permission_catalog.yaml` holds one batch cancellation permission and it is
    `payment_batch.cancel_draft`. Inventing a second is not an implementer's decision, so the
    command refuses that state and its message names `DOC-CONFLICT-056` — an implementer who hits
    it should learn that the rule exists and the grant does not.

    **`command_catalog.yaml` has no row for this command at all** (G-4), so its concurrency and
    idempotency contract is inferred from its neighbours: every other batch command in that file
    carries `"idempotency": "required"`, and cancelling twice on a retry would release
    allocations a second time and overwrite the first reason. Both headers are required for that
    reason rather than by citation, and G-4 is where the citation is owed.
    """

    if if_match is None:
        raise PreconditionRequiredError("If-Match")
    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")
    expected = _parse_record_version(if_match)

    now = utc_now()
    with runtime.uow_factory() as uow:
        result = commands.cancel_batch(
            commands.CancelBatch(
                payment_batch_id=batch_id,
                expected_batch_record_version=expected,
                reason=payload.reason,
            ),
            uow=uow,
            policy=BATCH_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=idempotency_key,
            now=now,
        )
        rendered = _batch_summary(result.batch)
        uow.commit()

    response.headers["ETag"] = f'"rv-{rendered.record_version}"'
    return rendered


def _parse_record_version(if_match: str) -> int:
    """`"rv-3"` -> `3`, and a refusal for anything else.

    `VersionConflictError` (412) rather than a 400: `api_error_catalog.yaml` gives 412 the
    meaning "If-Match value is stale", and a value this parser cannot read is a caller who
    cannot be told their precondition held. The same shape M5 uses at
    `payment_requests.py:1070`.

    Kept local rather than imported from that module: a cross-module helper between two route
    files for four lines is a dependency for nothing, and M5 slice 7 found that a shared route
    helper made `run()` opaque to `test_no_io_under_lock.py`.
    """

    cleaned = if_match.strip().strip('"')
    if not cleaned.startswith("rv-") or not cleaned[3:].isdigit():
        raise VersionConflictError()
    return int(cleaned[3:])


def _batch_summary(batch: PaymentBatch) -> BatchSummary:
    return BatchSummary(
        id=batch.id,
        batch_number=batch.batch_number,
        status=batch.status,
        record_version=batch.record_version,
    )


def _version_summary(version: PaymentBatchVersion) -> VersionSummary:
    return VersionSummary(
        id=version.id,
        version_number=version.version_number,
        status=version.status,
        row_count=version.row_count,
        total_amount_irr=str(version.total_amount_irr),
        content_hash=version.content_hash,
        validation_summary={
            "errors": list(version.validation_summary.get("errors", [])),
            "warnings": list(version.validation_summary.get("warnings", [])),
        },
    )


def _audit_actor(actor: ActorContext) -> AuditActor:
    return AuditActor(
        actor_type=actor.actor_type.value,
        actor_id=actor.actor_id,
        role_snapshot=tuple(sorted(actor.roles)),
        session_id=actor.session_id,
        authentication_assurance=actor.auth_level,
    )


def _current(
    session: Session, item: PreviewItem
) -> tuple[PaymentRequest, PaymentRequestRevision]:
    """The request and the revision the caller named, or a refusal.

    `CON-BATCH-001`. Three refusals, and they are different questions:

    - the request does not exist, or is not eligible for batching — `404`;
    - the named record version is not the current one — `409`;
    - the named revision is not the request's current one — `409`, because somebody corrected
      it while the accountant was choosing.

    `409` rather than `412`: `api_error_catalog.yaml` gives 412 the meaning "If-Match value is
    stale", and this route has no If-Match — document 05 puts the expectation in the body.

    A stale preview is worse than an error. It looks like an answer, and the accountant's next
    action is to create the batch from what they were shown.
    """

    record = session.get(PaymentRequest, item.payment_request_id)
    if record is None or record.status != ELIGIBLE:
        # Indistinguishable on purpose: whether the id is unknown or merely not eligible is
        # not something this route should teach a caller.
        raise NotFoundError()

    if record.record_version != item.expected_record_version:
        raise ConflictError(
            f"request {record.request_number} has moved since it was read; "
            "re-read it before previewing"
        )
    if record.current_revision_id != item.expected_revision_id:
        raise ConflictError(
            f"request {record.request_number} has a newer revision than the one named"
        )

    revision = session.get(PaymentRequestRevision, item.expected_revision_id)
    if revision is None:  # pragma: no cover - the pointer's FK guarantees it
        raise NotFoundError()
    return record, revision


# ---------------------------------------------------------------------------
# M7 slice 1. The manager's decision on one exact version.
# ---------------------------------------------------------------------------

DECISION_RESPONSES: dict[int | str, dict[str, object]] = {
    400: {
        "model": ErrorEnvelope,
        "description": (
            "The version is not awaiting approval, or the caller prepared or finalized it "
            "(FINANCIAL_INTEGRITY_BASELINE.md §5)."
        ),
    },
    401: {
        "model": ErrorEnvelope,
        "description": "No valid session, or X-Recent-Auth did not authorise this decision.",
    },
    403: {"model": ErrorEnvelope, "description": "The caller lacks the decision permission."},
    404: {"model": ErrorEnvelope, "description": "No such batch or version."},
    409: {
        "model": ErrorEnvelope,
        "description": (
            "The content hash is stale, the version is no longer current, or another decision "
            "reached this version first."
        ),
    },
    428: {"model": ErrorEnvelope, "description": "Idempotency-Key or X-Recent-Auth is missing."},
    **VALIDATION_ERROR_RESPONSE,
}


class PriorDecision(BaseModel):
    """`:1409` — "prior decision if any". Absent until one exists."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    decision: str
    decided_at: datetime
    approved_content_hash: str | None
    reason: str | None


class ApprovalView(BaseModel):
    """`05_API_Specification.md:1395-1410`, the manager's screen.

    `version.content_hash` is the field the approve call sends back, and that is the whole
    mechanism behind the word "exact": the server does not assume the manager saw the current
    version, it requires them to quote it.
    """

    model_config = ConfigDict(extra="forbid")

    batch: BatchSummary
    version: VersionSummary
    items: list[BatchItemResponse]
    prior_decision: PriorDecision | None = None


class ApproveVersionRequest(BaseModel):
    """`05_API_Specification.md:1421-1426`."""

    model_config = ConfigDict(extra="forbid")

    expected_content_hash: str = Field(min_length=64, max_length=64)
    approval_note: str | None = Field(default=None, max_length=2000)


class RejectVersionRequest(BaseModel):
    """`:1456-1461`. Both required — "Rejection reason is mandatory"."""

    model_config = ConfigDict(extra="forbid")

    expected_content_hash: str = Field(min_length=64, max_length=64)
    reason_code: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=2000)


class DecisionRecorded(BaseModel):
    """`:1430-1442`, plus `replayed` for the reason `BatchCreated` gives."""

    model_config = ConfigDict(extra="forbid")

    approval: PriorDecision
    batch: BatchSummary
    version: VersionSummary
    replayed: bool = False


@router.get(
    "/{batch_id}/versions/{version_id}/approval-view",
    response_model=ApprovalView,
    operation_id="getPaymentBatchApprovalView",
    summary="What the manager decides on, including the hash they must quote back.",
    responses=RESPONSES,
    dependencies=[requires(declare("payment_batch_version.read_approval_view"))],
)
def get_approval_view(
    batch_id: uuid.UUID,
    version_id: uuid.UUID,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> ApprovalView:
    """`GET /api/v1/payment-batches/{batch_id}/versions/{version_id}/approval-view`.

    **A separate permission from deciding.** `permission_catalog.yaml:475` gives
    `read_approval_view` to `accountant`, `manager` and `read_only_auditor`, and the decision only
    to `manager`. An auditor must be able to see what was decided without being able to decide,
    and the accountant who prepared the file must be able to check their own work — which they can
    do here and, by `SEC-APPROVAL-002`, cannot do by approving.

    **The prior decision is included when one exists**, because `:1409` asks for it: a manager
    arriving after a colleague sees the answer rather than a button that will fail.
    """

    with runtime.uow_factory() as uow:
        session = uow.session
        batch = session.get(PaymentBatch, batch_id)
        if batch is None:
            raise NotFoundError()
        version = session.get(PaymentBatchVersion, version_id)
        if version is None or version.payment_batch_id != batch.id:
            raise NotFoundError()

        items = list(
            session.scalars(
                select(PaymentBatchItem)
                .where(PaymentBatchItem.payment_batch_version_id == version.id)
                .order_by(PaymentBatchItem.row_order)
            )
        )
        decision = session.scalar(
            select(BatchApproval).where(BatchApproval.payment_batch_version_id == version.id)
        )
        return ApprovalView(
            batch=_batch_summary(batch),
            version=_version_summary(version),
            items=[
                BatchItemResponse(
                    id=item.id,
                    row_order=item.row_order,
                    payment_attempt_id=item.payment_attempt_id,
                    amount_irr=str(item.amount_irr),
                    beneficiary_name=item.beneficiary_name_snapshot,
                    beneficiary_iban=item.beneficiary_iban_snapshot,
                    description=item.description_snapshot,
                    row_hash=item.row_hash,
                )
                for item in items
            ],
            prior_decision=_prior_decision(decision),
        )


@router.post(
    "/{batch_id}/versions/{version_id}/approve",
    response_model=DecisionRecorded,
    operation_id="approvePaymentBatchVersion",
    summary="Approve the exact version whose hash the caller quotes back.",
    responses=DECISION_RESPONSES,
    dependencies=[requires(declare("payment_batch_version.approve"))],
)
def approve_version(
    batch_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: ApproveVersionRequest,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    recent_auth: Annotated[str | None, Header(alias="X-Recent-Auth")] = None,
) -> DecisionRecorded:
    """`POST /api/v1/payment-batches/{batch_id}/versions/{version_id}/approve`.

    **No `If-Match`, and that is document 05's decision, not an omission.** `:1443` — "No
    `If-Match` is needed for the immutable version itself, but the server verifies it remains the
    batch's current version." The hash in the body is the stronger token: a record version says
    *when* the caller read, the hash says *what* they read.

    **`X-Recent-Auth` is required here and was not required to finalize.**
    `command_catalog.yaml:150` says `required_action_bound` for this command and
    `not_required_by_current_baseline` for finalization. This is the moment money is authorised,
    and `FINANCIAL_INTEGRITY_BASELINE.md` §3 wants proof the person holding the session is
    present — bound to this action and this version, so a context obtained to approve version 7
    cannot approve version 8.
    """

    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")
    if recent_auth is None:
        raise PreconditionRequiredError("X-Recent-Auth")

    now = utc_now()
    with runtime.uow_factory() as uow:
        try:
            result = approval_commands.approve_version(
                approval_commands.ApproveVersion(
                    payment_batch_id=batch_id,
                    payment_batch_version_id=version_id,
                    expected_content_hash=payload.expected_content_hash,
                    recent_auth_reference=recent_auth,
                    approval_note=payload.approval_note,
                ),
                uow=uow,
                policy=BATCH_REDACTION,
                actor=actor,
                audit_actor=_audit_actor(actor),
                context=AuditContext(request_id=get_request_id()),
                idempotency_key=idempotency_key,
                now=now,
            )
        except StepUpRefused:
            raise _recent_auth_refused(uow) from None
        rendered = _decision_response(result)
        uow.commit()

    response.headers["ETag"] = f'"rv-{rendered.batch.record_version}"'
    return rendered


@router.post(
    "/{batch_id}/versions/{version_id}/reject",
    response_model=DecisionRecorded,
    operation_id="rejectPaymentBatchVersion",
    summary="Reject the exact version, with the reason document 05 makes mandatory.",
    responses=DECISION_RESPONSES,
    dependencies=[requires(declare("payment_batch_version.reject"))],
)
def reject_version(
    batch_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: RejectVersionRequest,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    recent_auth: Annotated[str | None, Header(alias="X-Recent-Auth")] = None,
) -> DecisionRecorded:
    """`POST /api/v1/payment-batches/{batch_id}/versions/{version_id}/reject`.

    The same two headers, because `command_catalog.yaml:163` asks for the same. A rejection is not
    the dangerous direction, but a rejection nobody made is: it stops a payment, and the
    separation rule and the step-up together are what make "who rejected this, and were they
    present" answerable.
    """

    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")
    if recent_auth is None:
        raise PreconditionRequiredError("X-Recent-Auth")

    now = utc_now()
    with runtime.uow_factory() as uow:
        try:
            result = approval_commands.reject_version(
                approval_commands.RejectVersion(
                    payment_batch_id=batch_id,
                    payment_batch_version_id=version_id,
                    expected_content_hash=payload.expected_content_hash,
                    recent_auth_reference=recent_auth,
                    reason_code=payload.reason_code,
                    reason=payload.reason,
                ),
                uow=uow,
                policy=BATCH_REDACTION,
                actor=actor,
                audit_actor=_audit_actor(actor),
                context=AuditContext(request_id=get_request_id()),
                idempotency_key=idempotency_key,
                now=now,
            )
        except StepUpRefused:
            raise _recent_auth_refused(uow) from None
        rendered = _decision_response(result)
        uow.commit()

    response.headers["ETag"] = f'"rv-{rendered.batch.record_version}"'
    return rendered


def _recent_auth_refused(uow: SqlAlchemyUnitOfWork) -> RecentAuthRequiredError:
    """Commit the refusal, then produce the one thing the client is told.

    **The commit is deliberate.** The command wrote a `step_up.rejected` security event before
    raising, and rolling back would discard the record of the refusal — which is exactly what an
    investigator needs when somebody is presenting contexts that do not authorise what they are
    trying to do. `app/api/v1/roles.py:242-250` made the same choice for the same reason.

    The nine reasons `StepUpRejection` distinguishes stay in `auth_events`. The client is told one
    thing, as login is, so a caller cannot map which contexts exist by reading error messages.
    """

    uow.commit()
    return RecentAuthRequiredError()


def _decision_response(
    result: approval_commands.DecisionResult,
) -> DecisionRecorded:
    decision = _prior_decision(result.approval)
    if decision is None:  # pragma: no cover - the command returned the row
        raise RuntimeError("a recorded decision cannot be absent from its own response")
    return DecisionRecorded(
        approval=decision,
        batch=_batch_summary(result.batch),
        version=_version_summary(result.version),
        replayed=result.replayed,
    )


def _prior_decision(decision: BatchApproval | None) -> PriorDecision | None:
    if decision is None:
        return None
    return PriorDecision(
        id=decision.id,
        decision=decision.decision,
        decided_at=decision.decided_at,
        approved_content_hash=decision.approved_content_hash,
        reason=decision.reason,
    )
