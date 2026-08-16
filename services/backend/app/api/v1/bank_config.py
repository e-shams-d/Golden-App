"""Bank configuration over HTTP, per `05_API_Specification.md:2096-2136`.

Creation only. Activation is slice 9 and needs two permissions that do not exist yet
(DOC-CONFLICT-045), so the routes that would use them are not here — a route guarded by an
identifier nobody has approved is a route that denies everyone, and shipping it before the
guard is reviewable would be shipping a decision as an accident.

**Account numbers and IBANs are masked according to permission**
(`05_API_Specification.md:2136`). POL-003 has not settled which roles see a full IBAN, so
the safe direction while it is open is to show less: a masked value can be widened by
policy later and an unmasked one cannot be taken back.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor, requires
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.commands import bank_configuration
from app.core.errors import ErrorEnvelope
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.db.models.bank import BankAccount, BankProfile
from app.security.actor import ActorContext
from app.security.permissions import declare

router = APIRouter(tags=["bank-configuration"])

BANK_REDACTION = RedactionPolicy(mask_iban=True)

# Who may see an unmasked account identifier. Narrow while POL-003 is open.
FULL_ACCOUNT_PERMISSION = "source_bank_account.manage"


def _audit_actor(actor: ActorContext) -> AuditActor:
    return AuditActor(
        actor_type=actor.actor_type.value,
        actor_id=actor.actor_id,
        role_snapshot=tuple(sorted(actor.roles)),
        session_id=actor.session_id,
        authentication_assurance=actor.auth_level,
    )


def _mask_iban(value: str | None, *, unmasked: bool) -> str | None:
    """Last four digits, or the whole value for an actor permitted to see it.

    Four rather than six: enough for a person to recognise an account they already know,
    not enough to reconstruct one they do not.
    """

    if value is None or unmasked:
        return value
    return f"****{value[-4:]}" if len(value) > 4 else "****"


class CreateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=40)
    display_name: str = Field(min_length=1, max_length=160)
    default_transfer_limit_irr: int | None = Field(default=None, gt=0)
    after_cutoff_transfer_limit_irr: int | None = Field(default=None, gt=0)
    splitting_enabled: bool = False
    supports_description_field: bool = False
    required_fields: dict[str, Any] = Field(default_factory=dict)
    rules: dict[str, Any] = Field(default_factory=dict)


class ProfileCreatedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: uuid.UUID
    version_id: uuid.UUID


class BankProfileSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    code: str
    name: str
    status: str


class BankProfileListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bank_profiles: list[BankProfileSummary]


class CreateAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: uuid.UUID
    display_name: str = Field(min_length=1, max_length=160)
    account_role: str
    normalized_iban: str | None = None


class AccountSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    display_name: str
    account_role: str
    status: str
    normalized_iban: str | None


class AccountListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bank_accounts: list[AccountSummary]


@router.get(
    "/bank-profiles",
    operation_id="listBankProfiles",
    response_model=BankProfileListResponse,
    dependencies=[requires(declare("bank_profile.read"))],
    responses={**VALIDATION_ERROR_RESPONSE},
)
def list_bank_profiles(
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
) -> BankProfileListResponse:
    del actor
    with runtime.uow_factory() as uow:
        rows = uow.session.execute(select(BankProfile).order_by(BankProfile.code)).scalars()
        return BankProfileListResponse(
            bank_profiles=[
                BankProfileSummary(id=row.id, code=row.code, name=row.name, status=row.status)
                for row in rows
            ]
        )


@router.post(
    "/bank-profiles",
    operation_id="createBankProfile",
    status_code=status.HTTP_201_CREATED,
    response_model=ProfileCreatedResponse,
    dependencies=[requires(declare("bank_profile.create_version"))],
    responses={400: {"model": ErrorEnvelope}, **VALIDATION_ERROR_RESPONSE},
)
def create_bank_profile(
    request: CreateProfileRequest,
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
) -> ProfileCreatedResponse:
    with runtime.uow_factory() as uow:
        profile_id, version_id = bank_configuration.create_profile(
            bank_configuration.CreateBankProfile(
                code=request.code,
                display_name=request.display_name,
                default_transfer_limit_irr=request.default_transfer_limit_irr,
                after_cutoff_transfer_limit_irr=request.after_cutoff_transfer_limit_irr,
                splitting_enabled=request.splitting_enabled,
                supports_description_field=request.supports_description_field,
                required_fields=request.required_fields,
                rules=request.rules,
            ),
            uow=uow,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            policy=BANK_REDACTION,
            app_env=runtime.app_env,
        )
        uow.commit()
    return ProfileCreatedResponse(profile_id=profile_id, version_id=version_id)


@router.get(
    "/bank-accounts",
    operation_id="listBankAccounts",
    response_model=AccountListResponse,
    dependencies=[requires(declare("bank_profile.read"))],
    responses={**VALIDATION_ERROR_RESPONSE},
)
def list_bank_accounts(
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
) -> AccountListResponse:
    unmasked = FULL_ACCOUNT_PERMISSION in actor.permissions
    with runtime.uow_factory() as uow:
        rows = uow.session.execute(
            select(BankAccount).order_by(BankAccount.display_name)
        ).scalars()
        return AccountListResponse(
            bank_accounts=[
                AccountSummary(
                    id=row.id,
                    display_name=row.display_name,
                    account_role=row.account_role,
                    status=row.status,
                    normalized_iban=_mask_iban(row.normalized_iban, unmasked=unmasked),
                )
                for row in rows
            ]
        )


@router.post(
    "/bank-accounts",
    operation_id="createBankAccount",
    status_code=status.HTTP_201_CREATED,
    response_model=AccountSummary,
    dependencies=[requires(declare("source_bank_account.manage"))],
    responses={400: {"model": ErrorEnvelope}, **VALIDATION_ERROR_RESPONSE},
)
def create_bank_account(
    request: CreateAccountRequest,
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
) -> AccountSummary:
    with runtime.uow_factory() as uow:
        account_id = bank_configuration.create_source_account(
            bank_configuration.CreateSourceBankAccount(
                profile_id=request.profile_id,
                display_name=request.display_name,
                account_role=request.account_role,
                normalized_iban=request.normalized_iban,
            ),
            uow=uow,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            policy=BANK_REDACTION,
            app_env=runtime.app_env,
        )
        row = uow.session.get(BankAccount, account_id)
        assert row is not None
        summary = AccountSummary(
            id=row.id,
            display_name=row.display_name,
            account_role=row.account_role,
            status=row.status,
            # The creator holds `source_bank_account.manage` by definition of this route's
            # guard, so the value is returned as given rather than masked back to them.
            normalized_iban=row.normalized_iban,
        )
        uow.commit()
    return summary
