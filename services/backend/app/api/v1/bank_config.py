"""Bank configuration over HTTP, per `05_API_Specification.md:2096-2136`.

Creation, and activation. DOC-CONFLICT-045 left both activation permissions seeded and granted to
no role, so `POST .../activate` refused every caller including `business_admin` — an interim rule
rather than an omission, chosen so the route, its command, its audit record and its negative tests
were all reviewable while the owner decided.

**The owner decided on 2026-09-08 and `20260914_0045` carries it: `bank_profile.activate_version`
to `business_admin`, and to nobody else.** Not the accountant — a profile version carries the
transfer limits, the cutoff time and the file rules, so it changes how *every* payment is built,
and the person who creates payments should not be the one who changes the rules they are built
under. `bank_mapping.activate` is a different permission and is still undecided; the two are not
interchangeable.

Nothing in this module changed when the grant arrived, which was the claim the interim state was
chosen to make good.

**Account numbers and IBANs are masked according to permission**
(`05_API_Specification.md:2136`). POL-003 has not settled which roles see a full IBAN, so
the safe direction while it is open is to show less: a masked value can be widened by
policy later and an unmasked one cannot be taken back.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.contract import VALIDATION_ERROR_RESPONSE
from app.api.dependencies import get_runtime
from app.api.v1.auth import authenticated_actor, requires
from app.audit.redaction import RedactionPolicy
from app.audit.writer import AuditActor, AuditContext
from app.bankconfig import resolution
from app.commands import bank_configuration
from app.core.errors import ErrorEnvelope, NotFoundError
from app.core.request_context import get_request_id
from app.core.runtime import RuntimeServices
from app.db.models.bank import BankAccount, BankProfile, BankProfileVersion
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


def _rials(value: int | None) -> str | None:
    """A monetary value as a base-10 integer string, never a number.

    `MONEY_TIME_CONTRACT.md:17` makes this the wire format and rule 9 forbids JavaScript `Number`
    for it. A transfer limit is nine digits of rial — comfortably inside a double today, and the
    point of the rule is that "comfortably inside" is not a property anybody re-checks when the
    figure grows.
    """

    return None if value is None else str(value)


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


class BankProfileVersionSummary(BaseModel):
    """One configuration snapshot, as a person choosing between them needs to see it.

    **No `record_version`, because the row has none.** `BankProfileVersion` says why in its own
    docstring: a version is "superseded by inserting a new row, never edited", so the runtime's
    UPDATE grant covers `status` alone and there is nothing for an `If-Match` to be stale against.
    `command_catalog.yaml` agrees — the activation's concurrency is
    `lock_profile_and_active_version`, a server-side lock, not a client precondition.

    The limits and the cutoff are here because they are *what the operator is choosing between*.
    A list of version numbers and statuses would make somebody activate a configuration by its
    ordinal, which is exactly how the wrong transfer limit reaches production.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    version_number: int
    status: str
    effective_from: datetime | None
    effective_to: datetime | None
    # Strings, per `MONEY_TIME_CONTRACT.md:17`: base-10 integer strings are the wire format for
    # monetary values and rule 9 forbids JavaScript `Number` for them. A transfer limit is nine
    # digits of rial and would lose precision as a float long before it looked wrong.
    default_transfer_limit_irr: str | None
    after_cutoff_transfer_limit_irr: str | None
    # `"16:00:00"`. A wall-clock rule in the configured business timezone under ADR-006, never an
    # instant — the column is `TIME` for that reason.
    cutoff_time: str | None
    splitting_enabled: bool
    supports_description_field: bool
    config_hash: str
    created_at: datetime


class BankProfileDetail(BaseModel):
    """A profile and every configuration it has ever had.

    **This read did not exist, and its absence made the activation command unreachable.** The list
    above returns four fields and no versions; `POST /bank-profiles` returns the id of the version
    it just created and no other. So a person could activate exactly one version — the one they
    had personally created moments earlier — and nothing could show them what was already there,
    which is in force, or what activating would replace.

    `current_version_id` is the profile's own pointer rather than a version derived by scanning
    statuses. The two must agree — `20260816_0014` moves them in one transaction — and deriving it
    here would hide a disagreement the operator most needs to see.
    """

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    code: str
    name: str
    status: str
    current_version_id: uuid.UUID | None
    versions: list[BankProfileVersionSummary]


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


@router.get(
    "/bank-profiles/{profile_id}",
    operation_id="getBankProfile",
    response_model=BankProfileDetail,
    dependencies=[requires(declare("bank_profile.read"))],
    responses={404: {"model": ErrorEnvelope}, **VALIDATION_ERROR_RESPONSE},
)
def get_bank_profile(
    profile_id: uuid.UUID,
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
) -> BankProfileDetail:
    """`GET /api/v1/bank-profiles/{profile_id}`. **The read that made activation reachable.**

    M2 built `POST /bank-profile-versions/{version_id}/activate` and M0 granted it to
    `business_admin` on 2026-09-08. Neither made it *usable*: a `version_id` could be obtained from
    exactly one place, the response to creating a profile, so the only version anybody could
    activate was one they had just made. Nothing listed what a bank already had, which of them was
    in force, or what activating would replace.

    That is the same shape M0 slice A2 found behind the correction screen — a command with no read
    to feed it — and it is worth naming as a pattern rather than a coincidence: a write surface
    built before anybody tried to *operate* it tends to be missing the read that makes choosing
    possible, and the gap is invisible to a gate that counts published operations.

    **Newest version first.** An operator opening a bank is asking "what is in force and what came
    before", and the answer they need is at the top. `version_number` is monotonic per profile —
    `uq_bank_profile_versions_number` enforces it — so it is a total order and needs no tiebreaker,
    unlike the timestamps this repository has twice been bitten by ordering on.
    """

    del actor
    with runtime.uow_factory() as uow:
        session = uow.session
        profile = session.get(BankProfile, profile_id)
        if profile is None:
            raise NotFoundError()
        versions = list(
            session.scalars(
                select(BankProfileVersion)
                .where(BankProfileVersion.bank_profile_id == profile_id)
                .order_by(BankProfileVersion.version_number.desc())
            )
        )
        return BankProfileDetail(
            id=profile.id,
            code=profile.code,
            name=profile.name,
            status=profile.status,
            current_version_id=profile.current_version_id,
            versions=[
                BankProfileVersionSummary(
                    id=version.id,
                    version_number=version.version_number,
                    status=version.status,
                    effective_from=version.effective_from,
                    effective_to=version.effective_to,
                    default_transfer_limit_irr=_rials(version.default_transfer_limit_irr),
                    after_cutoff_transfer_limit_irr=_rials(
                        version.after_cutoff_transfer_limit_irr
                    ),
                    cutoff_time=(
                        None if version.cutoff_time is None else version.cutoff_time.isoformat()
                    ),
                    splitting_enabled=version.splitting_enabled,
                    supports_description_field=version.supports_description_field,
                    config_hash=version.config_hash,
                    created_at=version.created_at,
                )
                for version in versions
            ],
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


@router.post(
    "/bank-profile-versions/{version_id}/activate",
    operation_id="activateBankProfileVersion",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[requires(declare("bank_profile.activate_version"))],
    responses={
        400: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        **VALIDATION_ERROR_RESPONSE,
    },
)
def activate_bank_profile_version(
    version_id: uuid.UUID,
    runtime: Annotated[RuntimeServices, Depends(get_runtime)],
    actor: Annotated[ActorContext, Depends(authenticated_actor)],
) -> None:
    """DOC-CONFLICT-045, resolved. **`business_admin` alone, since 2026-09-08.**

    This route denied everyone for two milestones, because `bank_profile.activate_version` was
    seeded and granted to no role. Shipping it guarded by a borrowed permission was the
    alternative, and it would have made the role that drafts a configuration the role that puts it
    into production — deciding by default the question the owner had been asked.

    `20260914_0045` grants it, and this function is unchanged: the guard already named the right
    permission, so the decision was a row in `role_permissions` rather than an edit here.
    `test_only_the_business_admin_may_activate_a_version` walks every seeded role and asserts three
    refusals and one activation, so a second grant is a failure rather than a widening nobody sees.
    """

    with runtime.uow_factory() as uow:
        resolution.activate_version(
            version_id,
            uow=uow,
            actor=_audit_actor(actor),
            context=AuditContext(request_id=get_request_id()),
            policy=BANK_REDACTION,
        )
        uow.commit()


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
