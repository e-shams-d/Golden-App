"""Payment results. `05_API_Specification.md` §17.2-17.3.

M9 slices 3 and 4. Two routes, and they are the first in this project that record money as having
moved.

**Neither request body carries an amount, and that is §17 `:1131`'s "amount is exact".** The
attempt already knows what was sent; a client-supplied figure could disagree with it, and the
absence of the field is a stronger guarantee than any check on one. `SVC-CONFIRM-003` asserts the
absence over the request models rather than testing a value.

**`If-Match` and `Idempotency-Key` on both**, which is `command_catalog.yaml`'s
`if_match_attempt_and_lock_request_aggregate` plus `idempotency: required` — and doc 05 shows both
headers at `:1566` and `:1596`. The lock half happens inside the command; the header half is here.

**`manager` is the negative actor**, and a sharp one: `20260801_0008:313` gives it
`payment_attempt.read` and neither confirmation grant, so the refusals prove the routes want
*these* permissions rather than merely some attempt permission.

M11 Screens slice 4 adds the **read**, and the reason is in `get_attempt`'s own docstring: every
command here requires `If-Match` on the attempt and nothing in the contract returned an attempt's
version, so a screen could only guess one.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor, requires
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.commands import payment_result as result_commands
from app.commands import payment_retry as retry_commands
from app.core.errors import (
    ErrorEnvelope,
    ForbiddenError,
    NotFoundError,
    PreconditionRequiredError,
    VersionConflictError,
)
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.payment_batch import PaymentAttempt
from app.db.models.payment_request import PaymentRequest
from app.security.actor import ActorContext
from app.security.permissions import declare

router = APIRouter(prefix="/payment-attempts", tags=["payment-attempts"])

# The attempt carries a beneficiary IBAN snapshot, so this is not optional here the way it is on
# the candidate surface.
RESULT_REDACTION = RedactionPolicy(mask_iban=True)

RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "The caller lacks the confirmation permission."},
    404: {"model": ErrorEnvelope, "description": "No such attempt or evidence link."},
    409: {"model": ErrorEnvelope, "description": "The attempt moved first."},
    412: {"model": ErrorEnvelope, "description": "If-Match is stale or unreadable."},
    428: {"model": ErrorEnvelope, "description": "If-Match and Idempotency-Key are required."},
    **VALIDATION_ERROR_RESPONSE,
}


class ConfirmPaidRequest(BaseModel):
    """§17.2's body, field for field. **No amount** — see the module docstring."""

    model_config = ConfigDict(extra="forbid")

    bank_tracking_number: str = Field(min_length=1, max_length=128)
    bank_result_at: datetime
    primary_evidence_link_id: uuid.UUID | None = None
    evidence_unavailable_reason: str | None = Field(default=None, max_length=4000)
    confirmation_note: str | None = Field(default=None, max_length=4000)


class ConfirmFailedRequest(BaseModel):
    """§17.3's body.

    `failure_reason` is required by the schema *and* by the command. Both, for the reason slice 2
    records: the schema gives a client a 422 naming the field, and the command gives the same
    refusal to any caller that does not come through it.
    """

    model_config = ConfigDict(extra="forbid")

    failure_code: str = Field(min_length=1, max_length=64)
    failure_reason: str = Field(min_length=1, max_length=4000)
    receipt_segment_id: uuid.UUID | None = None


class MarkRetryRequiredRequest(BaseModel):
    """§17.4's body. A reason, and nothing else — this creates nothing."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=4000)


class CreateRetryRequest(BaseModel):
    """§17.5's body, field for field.

    **No beneficiary fields.** `:1634`: "The server rejects free-form beneficiary/IBAN changes.
    Material beneficiary changes must exist in the referenced request revision." The strongest way
    to reject a field is to have nowhere for it to arrive, which is the same enforcement
    `ConfirmPaidRequest` uses for the amount. `SVC-RETRY-002` asserts the absence.
    """

    model_config = ConfigDict(extra="forbid")

    payment_request_revision_id: uuid.UUID
    amount_irr: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=4000)


class AttemptResult(BaseModel):
    """What a confirmed attempt looks like, and what its request became.

    `request_status` is included because the confirmation changes it and a client that had to
    re-read the request to find out would be reading a value that another confirmation may already
    have moved.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    payment_request_id: uuid.UUID
    attempt_number: int
    status: str
    amount_irr: int
    bank_tracking_number: str | None
    bank_result_at: datetime | None
    failure_code: str | None
    failure_reason: str | None
    confirmed_at: datetime | None
    record_version: int
    request_status: str


def _rendered(attempt: PaymentAttempt, request_status: str) -> AttemptResult:
    return AttemptResult(
        id=attempt.id,
        payment_request_id=attempt.payment_request_id,
        attempt_number=attempt.attempt_number,
        status=attempt.status,
        amount_irr=attempt.amount_irr,
        bank_tracking_number=attempt.bank_tracking_number,
        bank_result_at=attempt.bank_result_at,
        failure_code=attempt.failure_code,
        failure_reason=attempt.failure_reason,
        confirmed_at=attempt.confirmed_at,
        record_version=attempt.record_version,
        request_status=request_status,
    )


def _request_status(session: Any, request_id: uuid.UUID) -> str:
    """The request's status as it stands, for the two retry routes.

    They do not move it — a retry decision and an unbatched retry attempt change no paid sum — so
    the response reports rather than recomputes. Recomputing here would put a second copy of
    `_recalculate`'s rule in a route, which is how two answers to one question begin.
    """

    request = session.get(PaymentRequest, request_id)
    if request is None:  # pragma: no cover - the foreign key guarantees it
        raise NotFoundError()
    return str(request.status)


def _audit_actor(actor: ActorContext) -> AuditActor:
    return AuditActor(
        actor_type=actor.actor_type.value,
        actor_id=actor.actor_id,
        role_snapshot=tuple(sorted(actor.roles)),
        session_id=actor.session_id,
        authentication_assurance=actor.auth_level,
    )


def _confirming_admin(actor: ActorContext) -> uuid.UUID:
    """`confirmed_by_admin_user_id` comes from the session, never from the body.

    §11.3 calls it the human confirmation. Taking it from a request field would let a client
    attribute a payment confirmation to somebody who never made one.
    """

    if actor.actor_id is None:
        raise ForbiddenError()
    return actor.actor_id


def _parse_record_version(if_match: str | None) -> int:
    """`"rv-3"` -> `3`. The M5 shape, and a 412 for anything unreadable.

    412 rather than 400 because `api_error_catalog.yaml` gives 412 the meaning "If-Match value is
    stale", and a value this cannot read is a caller who cannot be told their precondition held.
    """

    if if_match is None:
        raise PreconditionRequiredError("If-Match")
    cleaned = if_match.strip().strip('"')
    if not cleaned.startswith("rv-"):
        raise VersionConflictError()
    try:
        return int(cleaned.removeprefix("rv-"))
    except ValueError as exc:
        raise VersionConflictError() from exc


def _require_key(idempotency_key: str | None) -> str:
    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")
    return idempotency_key


@router.get(
    "/{attempt_id}",
    response_model=AttemptResult,
    operation_id="getPaymentAttempt",
    summary="Read one payment attempt and the precondition its commands require.",
    responses={
        401: {"model": ErrorEnvelope, "description": "No valid session."},
        403: {"model": ErrorEnvelope, "description": "The caller lacks `payment_attempt.read`."},
        404: {"model": ErrorEnvelope, "description": "No such attempt."},
        **VALIDATION_ERROR_RESPONSE,
    },
    dependencies=[requires(declare("payment_attempt.read"))],
)
def get_attempt(
    attempt_id: uuid.UUID,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> AttemptResult:
    """`GET /api/v1/payment-attempts/{attempt_id}`.

    M11 Screens slice 4, and it exists because **the four commands below required a precondition
    nothing supplied.** All of them take `If-Match` on the attempt — `command_catalog.yaml`'s
    `if_match_attempt_and_lock_request_aggregate` — and until this route no read anywhere in the
    contract returned an attempt's `record_version`:

    - `PaymentRequestDetail` has three fields, and its own docstring says why: "`attempts` arrive
      with M6". They did not.
    - `GET /queues/sent-attempts-awaiting-result` returns `QueueRow`, five fields by a deliberate
      disclosure decision, and a version is not one of them.
    - `AttemptResult` carries `record_version` but was only ever a *response* to a confirmation, so
      the version arrived after acting and never before it.

    A screen could therefore only guess an `If-Match`, and a guessed precondition is worse than
    none: present, well-formed and meaningless. It is the mirror of the defect this project has hit
    five times — machinery with no caller — arriving as a caller with no way to satisfy the guard.

    **`payment_attempt.read`, which already existed.** `20260801_0008:313` gives it to `manager`
    and grants that role neither confirmation permission, which is the split the four routes below
    rely on for their negative tests: reading an attempt is not permission to confirm one.

    **The `ETag` is the purpose of the route**, not a convenience on it. It is what a screen echoes
    as `If-Match`, and `admin_users.py` states the rule — a client computing `rv-${record_version}`
    itself would be inventing a precondition.

    Nothing is recomputed: `request_status` is reported as it stands, the same way the two retry
    routes report it, because a second copy of `_recalculate`'s rule in a route is how two answers
    to one question begin.
    """

    del actor
    with runtime.uow_factory() as uow:
        attempt = uow.session.get(PaymentAttempt, attempt_id)
        if attempt is None:
            raise NotFoundError()
        rendered = _rendered(attempt, _request_status(uow.session, attempt.payment_request_id))
        uow.rollback()

    response.headers["ETag"] = f'"rv-{rendered.record_version}"'
    return rendered


@router.post(
    "/{attempt_id}/confirm-paid",
    response_model=AttemptResult,
    operation_id="confirmAttemptPaid",
    summary="Record that the bank paid this attempt.",
    responses=RESPONSES,
    dependencies=[requires(declare("payment_attempt.confirm_paid"))],
)
def confirm_attempt_paid(
    attempt_id: uuid.UUID,
    payload: ConfirmPaidRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AttemptResult:
    """`POST /api/v1/payment-attempts/{attempt_id}/confirm-paid`, per `:1564`.

    Seven validations run inside the command, each with its own refusal — see
    `app/commands/payment_result.py`. The two worth naming here are the ones a caller most often
    trips: an attempt that was never sent, and an overpayment, which opens a reconciliation task
    **and** refuses.
    """

    expected = _parse_record_version(if_match)
    key = _require_key(idempotency_key)
    now = utc_now()

    with runtime.uow_factory() as uow:
        try:
            result = result_commands.confirm_paid(
                result_commands.ConfirmPaid(
                    payment_attempt_id=attempt_id,
                    expected_record_version=expected,
                    bank_tracking_number=payload.bank_tracking_number,
                    bank_result_at=payload.bank_result_at,
                    confirmed_by_admin_user_id=_confirming_admin(actor),
                    primary_evidence_link_id=payload.primary_evidence_link_id,
                    evidence_unavailable_reason=payload.evidence_unavailable_reason,
                    confirmation_note=payload.confirmation_note,
                ),
                uow=uow,
                policy=RESULT_REDACTION,
                actor=_audit_actor(actor),
                context=AuditContext(request_id=get_request_id()),
                idempotency_key=key,
                now=now,
            )
        except result_commands.OverpaymentRefused:
            # **Committed on purpose**, and the first version of this route did not — so the
            # reconciliation task was rolled back with the refused request and nobody was asked
            # to look at the discrepancy. `04_Database_Schema.md:1606` requires the task *and*
            # the block; discarding the task keeps only the half that says no.
            #
            # The same choice M7's download route makes about quarantine, and its comment puts it
            # best: on a failure path whose whole point is the record, the record commits.
            uow.commit()
            raise

        rendered = _rendered(result.attempt, result.request_status)
        uow.commit()

    return rendered


@router.post(
    "/{attempt_id}/confirm-failed",
    response_model=AttemptResult,
    operation_id="confirmAttemptFailed",
    summary="Record that the bank did not pay this attempt, and why.",
    responses=RESPONSES,
    dependencies=[requires(declare("payment_attempt.confirm_failed"))],
)
def confirm_attempt_failed(
    attempt_id: uuid.UUID,
    payload: ConfirmFailedRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AttemptResult:
    """`POST /api/v1/payment-attempts/{attempt_id}/confirm-failed`, per `:1594`.

    **A separate permission from confirming paid**, and the catalogue is right to separate them:
    recording a failure is not the same authority as recording that money left, even though the
    same role holds both today.
    """

    expected = _parse_record_version(if_match)
    key = _require_key(idempotency_key)
    now = utc_now()

    with runtime.uow_factory() as uow:
        result = result_commands.confirm_failed(
            result_commands.ConfirmFailed(
                payment_attempt_id=attempt_id,
                expected_record_version=expected,
                failure_code=payload.failure_code,
                failure_reason=payload.failure_reason,
                confirmed_by_admin_user_id=_confirming_admin(actor),
                receipt_segment_id=payload.receipt_segment_id,
            ),
            uow=uow,
            policy=RESULT_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=key,
            now=now,
        )
        rendered = _rendered(result.attempt, result.request_status)
        uow.commit()

    return rendered


@router.post(
    "/{attempt_id}/mark-retry-required",
    response_model=AttemptResult,
    operation_id="markAttemptRetryRequired",
    summary="Record that this attempt needs retrying. Creates nothing.",
    responses=RESPONSES,
    dependencies=[requires(declare("payment_attempt.create_retry"))],
)
def mark_attempt_retry_required(
    attempt_id: uuid.UUID,
    payload: MarkRetryRequiredRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AttemptResult:
    """`POST /api/v1/payment-attempts/{attempt_id}/mark-retry-required`, per `:1608`.

    **"This does not itself create or send a retry"** — `:1612`, and the summary above repeats it
    because the route name is where a reader looks first. `SVC-RETRY-001` counts the request's
    attempts before and after.

    **Guarded by `payment_attempt.create_retry`**, because the catalogue has no
    `mark_retry_required` and deciding a retry is needed is the same authority as making one.
    Recorded here rather than resolved by inventing a permission — the rule M8 slice 3 followed
    when three permissions covered six queue routes.
    """

    expected = _parse_record_version(if_match)
    key = _require_key(idempotency_key)
    now = utc_now()

    with runtime.uow_factory() as uow:
        result = retry_commands.mark_retry_required(
            retry_commands.MarkRetryRequired(
                payment_attempt_id=attempt_id,
                expected_record_version=expected,
                reason=payload.reason,
            ),
            uow=uow,
            policy=RESULT_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=key,
            now=now,
        )
        # The request's own status is untouched by this command, so it is reported as it stands
        # rather than recomputed — a retry decision moves no paid sum.
        request_status = _request_status(uow.session, result.attempt.payment_request_id)
        rendered = _rendered(result.attempt, request_status)
        uow.commit()

    return rendered


@router.post(
    "/{attempt_id}/retry",
    response_model=AttemptResult,
    status_code=201,
    operation_id="createRetryAttempt",
    summary="Create a retry attempt from a marked one, unbatched.",
    responses=RESPONSES,
    dependencies=[requires(declare("payment_attempt.create_retry"))],
)
def create_retry_attempt(
    attempt_id: uuid.UUID,
    payload: CreateRetryRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AttemptResult:
    """`POST /api/v1/payment-attempts/{attempt_id}/retry`, per `:1616`.

    **201, because the response is the new attempt.** The original becomes `superseded` in the
    same transaction — `06_Workflows_and_State_Machines.md:684` — and handing back the retired row
    would give a client something already historical.

    **The retry is unbatched.** `:1636`: "The retry attempt remains unbatched until included in a
    future batch version." It is created in `created`, which is where M6's allocation picks it up.
    """

    expected = _parse_record_version(if_match)
    key = _require_key(idempotency_key)
    now = utc_now()

    with runtime.uow_factory() as uow:
        result = retry_commands.create_retry_attempt(
            retry_commands.CreateRetryAttempt(
                payment_attempt_id=attempt_id,
                expected_record_version=expected,
                payment_request_revision_id=payload.payment_request_revision_id,
                amount_irr=payload.amount_irr,
                reason=payload.reason,
            ),
            uow=uow,
            policy=RESULT_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=key,
            now=now,
        )
        request_status = _request_status(uow.session, result.attempt.payment_request_id)
        rendered = _rendered(result.attempt, request_status)
        uow.commit()

    return rendered
