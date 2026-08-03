"""The exemplar command over HTTP.

A named command path, not `PATCH /center-profile`. A generic mutation endpoint
routes every field change through one operation, and the audit row can then only
say that something was patched.

**Authentication does not exist yet — it is M3.** That leaves this endpoint with a
real problem: the audit contract requires a human action to name its actor, and
there is nobody to name. Inventing a placeholder human would be the worst answer,
because the resulting rows would be indistinguishable from real attributed ones
and could never be told apart afterwards.

So the endpoint is gated on the operations token that already protects the
restricted health paths, and it records `system_maintenance` — which the database
CHECK requires to carry a NULL actor. That is accurate rather than convenient: an
operations-token call really is a maintenance action by the deployment, not by a
person. When M3 lands, the authenticated actor replaces this and the audit rows
written before that point remain correctly labelled as maintenance.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime, require_operations_access
from app.audit import AuditActor, AuditContext, RedactionPolicy
from app.commands.rename_center_profile import RenameCenterProfile, execute
from app.core.errors import ErrorEnvelope, PreconditionRequiredError
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices

router = APIRouter(prefix="/center-profile", tags=["center-profile"])

IDEMPOTENCY_HEADER = "Idempotency-Key"
IF_MATCH_HEADER = "If-Match"

MAX_IDEMPOTENCY_KEY_LENGTH = 255

# POL-003 has not settled which roles see a full IBAN. Operations tooling is the
# narrowest audience there is, so masking is on: the safe direction while the
# decision is open is to show less, and a masked value in an audit row can be
# widened later by policy, whereas an unmasked one cannot be taken back.
OPERATIONS_REDACTION = RedactionPolicy(mask_iban=True)


class RenameCenterProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: uuid.UUID
    new_name: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=1000)


class CenterProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: uuid.UUID
    name: str
    record_version: int
    replayed: bool


def _require_idempotency_key(provided: str | None) -> str:
    if not provided or not provided.strip():
        raise PreconditionRequiredError(IDEMPOTENCY_HEADER)
    key = provided.strip()
    if len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise PreconditionRequiredError(IDEMPOTENCY_HEADER)
    return key


def _require_expected_version(provided: str | None) -> int:
    """Parse If-Match as the record version the caller believes is current.

    A missing precondition is 428 and not 412 on purpose: 412 tells a client to
    reload and retry, while 428 tells it the request was never safe to send. A
    client given 412 for a missing header would retry forever.
    """

    if provided is None or not provided.strip():
        raise PreconditionRequiredError(IF_MATCH_HEADER)
    candidate = provided.strip().strip('"').removeprefix("W/").strip('"')
    try:
        version = int(candidate)
    except ValueError:
        raise PreconditionRequiredError(IF_MATCH_HEADER) from None
    if version < 1:
        raise PreconditionRequiredError(IF_MATCH_HEADER)
    return version


@router.post(
    "/rename",
    response_model=CenterProfileResponse,
    operation_id="renameCenterProfile",
    summary="Rename the center profile",
    dependencies=[Depends(require_operations_access)],
    responses={
        400: {"model": ErrorEnvelope, "description": "The new name violates a business rule."},
        403: {"model": ErrorEnvelope, "description": "The operations token is invalid."},
        404: {"model": ErrorEnvelope, "description": "No such center profile."},
        409: {"model": ErrorEnvelope, "description": "The key was used for another request."},
        412: {"model": ErrorEnvelope, "description": "The If-Match version is stale."},
        # Without this the contract would publish FastAPI's own
        # HTTPValidationError, a shape this application never returns: every
        # validation failure is converted to the canonical envelope. A generated
        # client would branch on a field that never arrives.
        **VALIDATION_ERROR_RESPONSE,
        428: {"model": ErrorEnvelope, "description": "Idempotency-Key or If-Match is missing."},
    },
)
def rename_center_profile(
    payload: RenameCenterProfileRequest,
    response: Response,
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
    if_match: Annotated[str | None, Header(alias=IF_MATCH_HEADER)] = None,
    correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
) -> CenterProfileResponse:
    key = _require_idempotency_key(idempotency_key)
    expected_version = _require_expected_version(if_match)

    with runtime.uow_factory() as uow:
        result = execute(
            RenameCenterProfile(
                profile_id=payload.profile_id,
                new_name=payload.new_name,
                expected_record_version=expected_version,
                reason=payload.reason,
            ),
            uow=uow,
            actor=AuditActor(actor_type="system_maintenance"),
            context=AuditContext(
                request_id=get_request_id(),
                correlation_id=correlation_id or get_request_id(),
            ),
            idempotency_key=key,
            policy=OPERATIONS_REDACTION,
        )
        uow.commit()

    # The version a conditional follow-up must send. Returned on a replay too,
    # because a client that retried after a dropped response still needs it.
    response.headers["ETag"] = f'"{result.record_version}"'
    return CenterProfileResponse(
        profile_id=result.profile_id,
        name=result.name,
        record_version=result.record_version,
        replayed=result.replayed,
    )
