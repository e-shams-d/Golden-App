"""Suggestions, and the two decisions a person makes about them.
`05_API_Specification.md` §19.4-19.6.

M9 slice 1. Three routes, and the only interesting thing about them is what they cannot reach.

**The proposal route is mounted under the segment, and the decisions under the candidate.**
`:1798` gives `POST /receipt-segments/{segment_id}/matching-candidates`; `:1806` and `:1816` give
`POST /matching-candidates/{candidate_id}/…`. Two prefixes, so this module owns one router and
`receipt_segments.py` mounts the other — the alternative, a single prefix with a rewritten path,
would put a route at an address document 05 does not define.

**Two permissions, three routes.** `permission_catalog.yaml` approves `matching_candidate.create`
and `matching_candidate.review`; there is no `.accept` and no `.reject`, so both decisions take
`.review`. That is the catalogue's shape rather than a shortcut — deciding a suggestion either way
*is* reviewing it — and it follows the rule M8 slice 3 recorded when three permissions covered six
queue routes: a permission is a grant, grants are seeded and audited, and inventing one is not an
implementer's decision.

**No `If-Match` on any of them, and that is not an omission.** §12.5 gives `matching_candidates`
no `record_version` column, so there is no version a client could quote. What
`command_catalog.yaml:295` asks for — `candidate_version_revalidated` — is done by locking the row
and re-reading its status inside the command's transaction, which is the same guarantee for a row
whose only mutable field is that status. Requiring a header a client cannot compute would be
ceremony; adding the column would be inventing one document 04 does not list.

**`Idempotency-Key` on all three.** Only acceptance has a catalogue row asking for it
(`:294`), and the other two are inferred from their neighbours the way M8 slice 4 inferred the
crop's — every command in this area carries `idempotency: required`. For the proposal it is load
bearing rather than decorative: without it a retried request is refused by
`uq_candidate_segment_attempt_method`, which tells the client somebody else proposed this link when
in fact they did it themselves.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor, requires
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.commands import matching_candidate as candidate_commands
from app.core.errors import ErrorEnvelope, NotFoundError, PreconditionRequiredError
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.matching_candidate import (
    CANDIDATE_METHOD_MANUAL,
    MatchingCandidate,
)
from app.db.models.receipt_segment import ReceiptSegment
from app.security.actor import ActorContext
from app.security.permissions import declare

router = APIRouter(prefix="/matching-candidates", tags=["matching-candidates"])

# Mounted by `receipt_segments.py`, because `:1798` puts the proposal under the segment.
segment_scoped_router = APIRouter(prefix="/receipt-segments", tags=["matching-candidates"])

# A candidate names a segment and an attempt and carries no payee data of its own, but the policy
# is applied anyway: the audit rows it writes are read beside rows that do carry an IBAN, and a
# policy chosen per module is one that drifts.
CANDIDATE_REDACTION = RedactionPolicy(mask_iban=True)

RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope, "description": "No valid session."},
    403: {"model": ErrorEnvelope, "description": "The caller lacks the candidate permission."},
    404: {"model": ErrorEnvelope, "description": "No such candidate, segment or attempt."},
    409: {
        "model": ErrorEnvelope,
        "description": "The candidate already exists, or its status moved first.",
    },
    428: {"model": ErrorEnvelope, "description": "Idempotency-Key is required."},
    **VALIDATION_ERROR_RESPONSE,
}


class ProposeRequest(BaseModel):
    """§19.4's body.

    `method` defaults to `manual` because Phase 1A has no engine: §12.5 says a candidate "may be
    manually created in Phase 1A and AI-assisted later", and the column is the third member of the
    unique that lets a later engine suggest the same pair without colliding with a person.

    `score` is optional and stays `None` for a manual proposal. A default of 1.0 would make a
    human guess indistinguishable from a certainty something computed.
    """

    model_config = ConfigDict(extra="forbid")

    payment_attempt_id: uuid.UUID
    method: str = Field(default=CANDIDATE_METHOD_MANUAL, min_length=1, max_length=32)
    score: Decimal | None = Field(default=None, ge=0, le=1)
    reasons: tuple[str, ...] = ()


class DecisionRequest(BaseModel):
    """The body both decisions share.

    `reason` is optional here and required by the *command* for a rejection. The rule lives there
    rather than in the schema because it is a business rule with a citation and a deviation
    recorded against it, and a `min_length` on a field cannot carry either.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=4000)


class CandidateDetail(BaseModel):
    """What a suggestion is. Advisory, and the response says so in its own shape.

    There is no `payment_status` field and no `confirmed` field, because a candidate knows
    nothing about either — `04_Database_Schema.md:1274`. A response that carried one would invite
    a screen to read it as a result.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    receipt_segment_id: uuid.UUID
    payment_attempt_id: uuid.UUID
    method: str
    score: Decimal | None
    reasons: tuple[str, ...]
    status: str
    created_at: datetime
    resolved_at: datetime | None


def _detail(candidate: MatchingCandidate) -> CandidateDetail:
    return CandidateDetail(
        id=candidate.id,
        receipt_segment_id=candidate.receipt_segment_id,
        payment_attempt_id=candidate.payment_attempt_id,
        method=candidate.method,
        score=candidate.score,
        reasons=tuple(candidate.reasons or ()),
        status=candidate.status,
        created_at=candidate.created_at,
        resolved_at=candidate.resolved_at,
    )


def _audit_actor(actor: ActorContext) -> AuditActor:
    return AuditActor(
        actor_type=actor.actor_type.value,
        actor_id=actor.actor_id,
        role_snapshot=tuple(sorted(actor.roles)),
        session_id=actor.session_id,
        authentication_assurance=actor.auth_level,
    )


def _require_key(idempotency_key: str | None) -> str:
    if idempotency_key is None:
        raise PreconditionRequiredError("Idempotency-Key")
    return idempotency_key


@segment_scoped_router.post(
    "/{segment_id}/matching-candidates",
    response_model=CandidateDetail,
    status_code=201,
    operation_id="proposeMatchingCandidate",
    summary="Suggest that this segment is evidence for a payment attempt.",
    responses=RESPONSES,
    dependencies=[requires(declare("matching_candidate.create"))],
)
def propose_matching_candidate(
    segment_id: uuid.UUID,
    payload: ProposeRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CandidateDetail:
    """`POST /api/v1/receipt-segments/{segment_id}/matching-candidates`, per `:1798`.

    **"Response candidates are advisory"** (`:1802`), and the 201 says only that a suggestion was
    recorded. The segment may move to `candidate_found` —
    `06_Workflows_and_State_Machines.md:1061-1062` draws that arrow — and the attempt does not
    move at all, because nothing in this path holds a privilege that could move it.
    """

    key = _require_key(idempotency_key)
    now = utc_now()
    with runtime.uow_factory() as uow:
        result = candidate_commands.propose_candidate(
            candidate_commands.ProposeCandidate(
                receipt_segment_id=segment_id,
                payment_attempt_id=payload.payment_attempt_id,
                method=payload.method,
                score=payload.score,
                reasons=payload.reasons,
            ),
            uow=uow,
            policy=CANDIDATE_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=key,
            now=now,
        )
        rendered = _detail(result.candidate)
        uow.commit()

    return rendered


@router.post(
    "/{candidate_id}/accept-for-confirmation",
    response_model=CandidateDetail,
    operation_id="acceptMatchingCandidate",
    summary="Accept a suggestion for confirmation. Does not mark anything paid.",
    responses=RESPONSES,
    dependencies=[requires(declare("matching_candidate.review"))],
)
def accept_matching_candidate(
    candidate_id: uuid.UUID,
    payload: DecisionRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CandidateDetail:
    """`POST /api/v1/matching-candidates/{candidate_id}/accept-for-confirmation`, per `:1806`.

    **"This does not mark an attempt paid"** — `:1810`, and the summary above repeats it because
    the route name is the one place a reader looks before the specification. `:1274` and
    `15_Agent_Implementation_Plan.md:1102` say it twice more, and
    `command_catalog.yaml:296` names both prohibitions as preconditions on this exact row.

    What acceptance does is open the confirmation context. What closes it is slice 3's
    `confirm-paid`, which requires a bank tracking number, a result timestamp and an actor — none
    of which a candidate carries.
    """

    key = _require_key(idempotency_key)
    now = utc_now()
    with runtime.uow_factory() as uow:
        result = candidate_commands.accept_candidate(
            candidate_commands.DecideCandidate(
                matching_candidate_id=candidate_id, reason=payload.reason
            ),
            uow=uow,
            policy=CANDIDATE_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=key,
            now=now,
        )
        rendered = _detail(result.candidate)
        uow.commit()

    return rendered


@router.post(
    "/{candidate_id}/reject",
    response_model=CandidateDetail,
    operation_id="rejectMatchingCandidate",
    summary="Refuse a suggestion, with a reason.",
    responses=RESPONSES,
    dependencies=[requires(declare("matching_candidate.review"))],
)
def reject_matching_candidate(
    candidate_id: uuid.UUID,
    payload: DecisionRequest,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CandidateDetail:
    """`POST /api/v1/matching-candidates/{candidate_id}/reject`, per `:1816`.

    **A reason is always required, which is stricter than `:1820`.** That line asks for one "when
    rejecting a high-confidence candidate or overriding a previously accepted candidate". The
    second case is exact; the first has no approved threshold anywhere, so implementing
    "sometimes" would mean inventing the boundary. The command explains the choice and the owner
    owes the threshold.
    """

    key = _require_key(idempotency_key)
    now = utc_now()
    with runtime.uow_factory() as uow:
        result = candidate_commands.reject_candidate(
            candidate_commands.DecideCandidate(
                matching_candidate_id=candidate_id, reason=payload.reason
            ),
            uow=uow,
            policy=CANDIDATE_REDACTION,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            idempotency_key=key,
            now=now,
        )
        rendered = _detail(result.candidate)
        uow.commit()

    return rendered


@segment_scoped_router.get(
    "/{segment_id}/matching-candidates",
    response_model=list[CandidateDetail],
    operation_id="listMatchingCandidates",
    summary="Every suggestion recorded against this segment.",
    responses=RESPONSES,
    dependencies=[requires(declare("matching_candidate.review"))],
)
def list_matching_candidates(
    segment_id: uuid.UUID,
    response: Response,
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
) -> list[CandidateDetail]:
    """The read the two decision routes need, and document 05 does not define.

    **Added because a decision route with no list is a mechanism with no caller**, which is this
    repository's most-repeated defect — fifteen instances. Both decisions take a candidate id, and
    without this route the only way to obtain one is the 201 from a proposal in the same session.
    A reviewer coming back to a segment tomorrow would have nowhere to look.

    Guarded by `matching_candidate.review` rather than by a read permission of its own: the
    catalogue has no `matching_candidate.read`, and reviewing is the authority that acts on this
    list.
    """

    del actor
    with runtime.uow_factory() as uow:
        rows = list(
            uow.session.scalars(
                select(MatchingCandidate)
                .where(MatchingCandidate.receipt_segment_id == segment_id)
                .order_by(MatchingCandidate.created_at.desc())
            )
        )
        rendered = [_detail(row) for row in rows]

    if not rendered:
        # An empty list is a real answer for a segment nobody has suggested anything about, so
        # the absence of candidates is not a 404. A missing *segment* is, and telling those two
        # apart is the only reason this second read exists.
        with runtime.uow_factory() as uow:
            if uow.session.get(ReceiptSegment, segment_id) is None:
                raise NotFoundError()

    response.headers["Cache-Control"] = "no-store"
    return rendered
