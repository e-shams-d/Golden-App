"""Suspension, reactivation and the administrative reset — the three acts on somebody else.

Split from `admin_user_lifecycle.py`, which holds the four CRUD routes slice 8D shipped.
The division is not by size: those four change *what an account says*, and these three
change *whether it works*. Every one of the three has a guard that the CRUD family does
not need, and two of them end sessions belonging to a person who is not the caller.

**Nothing here can strand the deployment, and that needed a guard nobody had written.**
`business_admin` is the only seeded role holding `user.create`, `user.update`,
`user.deactivate` and `user.read`. One administrator suspending the last account that
holds them leaves a running platform with nobody able to create staff, and the bootstrap
command deliberately refuses once any staff account exists — so the recovery would be
editing the database by hand. `_refuse_if_last_administrator` is what stops that, and it
counts *live grants on active accounts*, not rows in `admin_users`.

**Self-reset is refused, and the reason is specific rather than hygienic.** A reset drives
the target into `recovery_required`, which refuses every action except the recovery flow.
An administrator resetting themselves would be relying on being able to complete that flow
with a credential they have just replaced with one they have not been told — the reset
returns none. Refusing self-reset costs an administrator nothing: `POST /auth/change-password`
is the route for their own credential, and it keeps their session.

**The reset returns no credential at all**, which is what makes `API-PWD-002` a claim about
this module rather than about a serialiser. The new password arrives in the request, chosen
by the resetting administrator and communicated out of band; nothing is generated here and
nothing is sent back, so there is no path by which a credential reaches a response body, a
header or a log.

Covers: API-PWD-002, SEC-ACCT-003, SEC-ROLECHANGE-001.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import (
    REACTIVATE_ADMIN_USER,
    RESET_ADMIN_PASSWORD,
    SUSPEND_ADMIN_USER,
    CommandNames,
)
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.db.concurrency import compare_and_swap
from app.db.models.identity import AdminUser
from app.db.models.rbac import AdminUserRole, Permission, Role, RolePermission
from app.db.models.session_and_security import AuthSession
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.security import account_state, passwords
from app.security.passwords import Argon2Parameters

METADATA_SCHEMA = "audit.metadata"
METADATA_VERSION = 1

# The reasons that land on `auth_sessions.revocation_reason`. Distinct strings, because
# the column is what an investigator reads to answer "why did this person's session end",
# and one shared value would make an administrative act indistinguishable from a
# self-service one.
SUSPENSION_REVOCATION = "admin_user_suspended"
RESET_REVOCATION = "password_reset_by_administrator"

# The permission family that administers staff. Held by `business_admin` alone in the
# seeded catalogue, which is exactly why stranding is possible.
ADMINISTRATION_PERMISSIONS: tuple[str, ...] = (
    "user.read",
    "user.create",
    "user.update",
    "user.deactivate",
)


@dataclass(frozen=True, slots=True)
class StateChange:
    admin_user_id: uuid.UUID
    expected_record_version: int
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PasswordReset:
    admin_user_id: uuid.UUID
    expected_record_version: int
    new_password: str
    reason: str


@dataclass(frozen=True, slots=True)
class StateChanged:
    """What the caller may see. Deliberately not the new credential, and not a token.

    A reset produces nothing presentable — that is the obligation, not an omission — so
    this shape is the same for all three commands and there is no field a later edit could
    put a password into without changing the type.
    """

    admin_user_id: uuid.UUID
    status: str
    record_version: int
    sessions_revoked: int


def _load(session: Session, admin_user_id: uuid.UUID) -> AdminUser:
    admin = session.get(AdminUser, admin_user_id)
    if admin is None:
        raise NotFoundError()
    return admin


def administrators_holding_administration(session: Session) -> int:
    """How many **active** accounts can still administer staff.

    Counts through live role grants and live role-permission rows rather than by role
    code, so a deployment that moved `user.create` onto a different role is counted
    correctly. Counting `business_admin` members by name would be a guard that silently
    stops guarding the moment somebody reorganises the roles — which is precisely when a
    deployment is most likely to strand itself.

    `status == active` is the condition that matters: a suspended administrator cannot
    administer anything, so an installation whose only two administrators are one active
    and one suspended has exactly one, not two.
    """

    return int(
        session.scalar(
            select(func.count(func.distinct(AdminUser.id)))
            .select_from(AdminUser)
            .join(AdminUserRole, AdminUserRole.admin_user_id == AdminUser.id)
            .join(Role, Role.id == AdminUserRole.role_id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(AdminUser.status == account_state.ACTIVE)
            .where(AdminUserRole.revoked_at.is_(None))
            .where(Role.is_enabled.is_(True))
            .where(Permission.code.in_(ADMINISTRATION_PERMISSIONS))
        )
        or 0
    )


def _refuse_if_last_administrator(session: Session, target: AdminUser, act: str) -> None:
    """Stop an act that would leave nobody able to administer staff.

    Checked before the act rather than after: a count taken afterwards would be correct
    and useless, because the transaction that discovered the problem is the one that
    caused it.
    """

    if target.status != account_state.ACTIVE:
        # Already not counted, so this act cannot reduce the number.
        return

    remaining = administrators_holding_administration(session)
    if remaining > 1:
        return

    if _holds_administration(session, target.id):
        raise BusinessRuleViolationError(
            f"this is the last active account that can administer staff, so {act} it "
            "would leave the deployment with nobody able to create or amend a staff "
            "account — and the bootstrap command refuses once any account exists. "
            "Grant the permissions to another active account first."
        )


def _holds_administration(session: Session, admin_user_id: uuid.UUID) -> bool:
    return bool(
        session.scalar(
            select(func.count())
            .select_from(AdminUserRole)
            .join(Role, Role.id == AdminUserRole.role_id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(AdminUserRole.admin_user_id == admin_user_id)
            .where(AdminUserRole.revoked_at.is_(None))
            .where(Role.is_enabled.is_(True))
            .where(Permission.code.in_(ADMINISTRATION_PERMISSIONS))
        )
    )


def _revoke_sessions(session: Session, admin_user_id: uuid.UUID, reason: str, now: datetime) -> int:
    """End every live session of one identity, with the reason that ended it.

    `revoked_at IS NULL` in the predicate keeps the count honest and keeps the reason
    truthful: without it, a second suspension would report revoking sessions it had
    already ended, and would overwrite the earlier reason with a later cause.
    """

    result = cast(
        "CursorResult[Any]",
        session.execute(
            update(AuthSession)
            .where(AuthSession.admin_user_id == admin_user_id)
            .where(AuthSession.revoked_at.is_(None))
            .values(revoked_at=now, revocation_reason=reason, updated_at=now)
        ),
    )
    return result.rowcount


def _record(
    session: Session,
    names: CommandNames,
    *,
    admin: AdminUser,
    policy: RedactionPolicy,
    previous_status: str,
    new_status: str,
    record_version: int,
    reason: str | None,
    sessions_revoked: int,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> None:
    AuditWriter(session, policy).record(
        AuditEntry(
            action=names.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="admin_user",
            entity_id=admin.id,
            entity_record_version=record_version,
            previous_values={"status": previous_status},
            new_values={"status": new_status},
            reason=reason,
            occurred_at=now,
            metadata={
                "operation": names.audit_action,
                "sessions_revoked": sessions_revoked,
            },
        ),
        actor=actor,
        context=context,
    )


def suspend_admin_user(
    command: StateChange,
    *,
    uow: SqlAlchemyUnitOfWork,
    actor: AuditActor,
    context: AuditContext,
    policy: RedactionPolicy,
    now: datetime,
) -> StateChanged:
    """Cut an account off now, and end its live sessions in the same transaction.

    The two halves are one fact. A suspension that left sessions running would take effect
    only at the next login — which is the one thing the person being suspended has no
    reason to do.
    """

    session = uow.session
    admin = _load(session, command.admin_user_id)

    if not (command.reason or "").strip():
        # Required here and not on reactivation. Doc 05 requires a reason for the
        # restrictive halves of the trader decisions for the same reason it applies here:
        # a refusal nobody explained cannot be reviewed later, while restoring access
        # needs no defence.
        raise BusinessRuleViolationError(
            "a suspension requires a reason; an access removal nobody explained cannot "
            "be reviewed later"
        )

    if admin.status == account_state.SUSPENDED:
        raise BusinessRuleViolationError("the account is already suspended")
    if admin.status == account_state.DEACTIVATED:
        raise BusinessRuleViolationError(
            "a deactivated account has no access to remove; reactivate it first if the "
            "intent is to suspend a working account"
        )

    _refuse_if_last_administrator(session, admin, "suspending")

    previous = admin.status
    outcome = compare_and_swap(
        session,
        AdminUser,
        entity_id=admin.id,
        expected_version=command.expected_record_version,
        values={"status": account_state.SUSPENDED},
    )
    revoked = _revoke_sessions(session, admin.id, SUSPENSION_REVOCATION, now)

    _record(
        session,
        SUSPEND_ADMIN_USER,
        admin=admin,
        policy=policy,
        previous_status=previous,
        new_status=account_state.SUSPENDED,
        record_version=outcome.new_version,
        reason=command.reason,
        sessions_revoked=revoked,
        actor=actor,
        context=context,
        now=now,
    )

    session.refresh(admin)
    return StateChanged(
        admin_user_id=admin.id,
        status=admin.status,
        record_version=admin.record_version,
        sessions_revoked=revoked,
    )


def reactivate_admin_user(
    command: StateChange,
    *,
    uow: SqlAlchemyUnitOfWork,
    actor: AuditActor,
    context: AuditContext,
    policy: RedactionPolicy,
    now: datetime,
) -> StateChanged:
    """Return a suspended account to `active`.

    **Only from `suspended`.** A `recovery_required` account is not restored by an
    administrator declaring it well: its credential is one the target has not chosen, and
    reactivating it here would let a reset be undone by the same person who ordered it,
    leaving an account whose owner never proved presence. That state ends by completing
    the recovery, which is the only transition out of it.
    """

    session = uow.session
    admin = _load(session, command.admin_user_id)

    if admin.status == account_state.ACTIVE:
        raise BusinessRuleViolationError("the account is already active")
    if admin.status == account_state.RECOVERY_REQUIRED:
        raise BusinessRuleViolationError(
            "an account awaiting recovery is not reactivated by an administrator; it "
            "leaves that state when its owner completes the recovery and sets a "
            "credential only they know"
        )
    if admin.status == account_state.DEACTIVATED:
        raise BusinessRuleViolationError(
            "a deactivated account is not reactivated through this route; deactivation "
            "is the terminal state and re-admitting somebody is a creation decision"
        )

    previous = admin.status
    outcome = compare_and_swap(
        session,
        AdminUser,
        entity_id=admin.id,
        expected_version=command.expected_record_version,
        values={"status": account_state.ACTIVE},
    )

    _record(
        session,
        REACTIVATE_ADMIN_USER,
        admin=admin,
        policy=policy,
        previous_status=previous,
        new_status=account_state.ACTIVE,
        record_version=outcome.new_version,
        reason=command.reason,
        # Nothing is revoked. Restoring access does not end anything, and reporting a
        # number here would invite a reader to believe a count of zero meant something.
        sessions_revoked=0,
        actor=actor,
        context=context,
        now=now,
    )

    session.refresh(admin)
    return StateChanged(
        admin_user_id=admin.id,
        status=admin.status,
        record_version=admin.record_version,
        sessions_revoked=0,
    )


def reset_admin_password(
    command: PasswordReset,
    *,
    uow: SqlAlchemyUnitOfWork,
    caller_admin_id: uuid.UUID | None,
    actor: AuditActor,
    context: AuditContext,
    policy: RedactionPolicy,
    parameters: Argon2Parameters,
    password_max_length: int,
    now: datetime,
) -> StateChanged:
    """Set another administrator's credential, end their sessions, require recovery.

    Four writes, one transaction, because any three of them without the fourth is a
    defect: a credential replaced without ending sessions leaves the old access working;
    sessions ended without the stamp bump leaves anything that reissues them able to
    resurrect the access; and a stamp bump without `recovery_required` leaves an account
    whose password is known to somebody other than its owner and nothing requiring them
    to change it.
    """

    session = uow.session
    admin = _load(session, command.admin_user_id)

    if not command.reason.strip():
        raise BusinessRuleViolationError(
            "a reset requires a reason; an administrator setting another person's "
            "credential is the act most in need of a recorded justification"
        )

    if caller_admin_id is not None and caller_admin_id == admin.id:
        # See the module docstring: self-reset plus `recovery_required` plus a credential
        # the caller was never told is a permanent self-lockout.
        raise BusinessRuleViolationError(
            "an administrator does not reset their own credential through this route: "
            "the reset drives the account into recovery_required and returns no "
            "password, so the caller would be locked out of their own account. Use "
            "POST /auth/change-password, which keeps the session."
        )

    if admin.status == account_state.DEACTIVATED:
        raise BusinessRuleViolationError(
            "a deactivated account cannot sign in with any credential, so resetting one "
            "would record a change with no effect"
        )

    _refuse_if_last_administrator(session, admin, "resetting")

    previous = admin.status
    new_stamp = admin.security_stamp_version + 1

    outcome = compare_and_swap(
        session,
        AdminUser,
        entity_id=admin.id,
        expected_version=command.expected_record_version,
        values={
            "password_hash": passwords.hash_password(
                command.new_password, parameters, max_length=password_max_length
            ),
            "password_changed_at": now,
            "security_stamp_version": new_stamp,
            "status": account_state.RECOVERY_REQUIRED,
            # The lockout counters are cleared. An account whose credential an
            # administrator has just replaced should not arrive at its recovery already
            # locked by the failed attempts that prompted the reset.
            "failed_login_count": 0,
            "locked_until": None,
        },
    )

    revoked = _revoke_sessions(session, admin.id, RESET_REVOCATION, now)

    _record(
        session,
        RESET_ADMIN_PASSWORD,
        admin=admin,
        policy=policy,
        previous_status=previous,
        new_status=account_state.RECOVERY_REQUIRED,
        record_version=outcome.new_version,
        reason=command.reason,
        sessions_revoked=revoked,
        actor=actor,
        context=context,
        now=now,
    )

    session.refresh(admin)
    return StateChanged(
        admin_user_id=admin.id,
        status=admin.status,
        record_version=admin.record_version,
        sessions_revoked=revoked,
    )
