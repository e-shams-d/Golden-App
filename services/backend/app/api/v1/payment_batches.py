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
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor, requires
from app.batching.splitting import SplittingRules, split
from app.core.errors import ConflictError, ErrorEnvelope, NotFoundError
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.bank import BankProfileVersion
from app.db.models.payment_request import PaymentRequest, PaymentRequestRevision
from app.security.actor import ActorContext
from app.security.permissions import declare

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
