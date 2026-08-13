"""Creating and amending staff accounts — the second way an `AdminUser` comes to exist.

The first is `app/cli/create_first_admin.py`, which exists because this one cannot be
reached without an account already holding `user.create`. The two are deliberately
distinct actions in the audit trail: this one has an actor and that one cannot, and an
auditor reading `admin_user.created` should never have to wonder whether a human
authorised it.

**The idempotency record is resolved and persisted, not merely required.**
`12_Security_RBAC_Audit.md` §12 lists thirteen ordered steps every sensitive command must
perform, and two of them are "resolve idempotency record and canonical request hash" and
"persist idempotency completion result". The four trader decision routes require an
`Idempotency-Key` header and then discard it — a defect recorded in the M3 plan's §3.5 —
so this family follows `app/commands/rename_center_profile.py`, which is the one place in
the repository that does it properly. A retried creation returns the first account rather
than a second one.

**No `password_hash` leaves this module.** `12_Security_RBAC_Audit.md:383` keeps
credential material out of readable records, so the result carries only what a caller may
see, and the audit rows carry the fields that changed with the hash excluded by name
rather than by hoping nobody adds it.

Covers: API-ADMIN-001, API-ADMIN-002.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select

from app.audit.redaction import RedactionPolicy
from app.audit.registry import CREATE_ADMIN_USER, UPDATE_ADMIN_USER
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.db.concurrency import compare_and_swap
from app.db.models.identity import ACCOUNT_STATUSES, AdminUser
from app.db.models.rbac import AdminUserRole, Role
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.idempotency import IdempotencyResolver, key_hash
from app.security import passwords
from app.security.passwords import Argon2Parameters

METADATA_SCHEMA = "audit.metadata"
METADATA_VERSION = 1

CREATE_OPERATION = "admin_user.create"

# The status a new account starts in. `active` rather than `recovery_required` for the
# same reason the bootstrap command records: `recovery_required` refuses authentication
# and no recovery path exists yet, so it would produce a correctly-provisioned account
# nobody can sign in to. When 8E ships recovery this becomes the right default and the
# change belongs there, with a test that the new account must rotate its credential.
INITIAL_STATUS = "active"


@dataclass(frozen=True, slots=True)
class NewAdminUser:
    username: str
    full_name: str
    password: str
    role_codes: tuple[str, ...]
    email: str | None = None
    phone_number: str | None = None


@dataclass(frozen=True, slots=True)
class AdminUserAmendment:
    admin_user_id: uuid.UUID
    expected_record_version: int
    full_name: str | None = None
    email: str | None = None
    phone_number: str | None = None


@dataclass(frozen=True, slots=True)
class AdminUserResult:
    """What a caller may see. Never the hash, and never the lockout internals.

    `failed_login_count` and `locked_until` are deliberately absent: they are useful to
    an operator and they also tell anybody who can read this response how close an
    account is to locking, which is a probe an attacker would value.
    """

    id: uuid.UUID
    username: str
    full_name: str
    email: str | None
    phone_number: str | None
    status: str
    role_codes: tuple[str, ...]
    record_version: int
    replayed: bool = False


def _resolve_roles(uow: SqlAlchemyUnitOfWork, codes: tuple[str, ...]) -> list[Role]:
    """Every requested role, or a refusal naming the ones that do not exist.

    Refused as a business-rule violation rather than filtered silently. A creation that
    quietly dropped an unknown role would hand back an account with less authority than
    the caller asked for and no indication of it — and the caller would discover it the
    next time that person could not do their job.
    """

    if not codes:
        raise BusinessRuleViolationError(
            "an account with no role resolves no permissions and can do nothing; name "
            "at least one role"
        )

    found = list(uow.session.scalars(select(Role).where(Role.code.in_(codes))))
    missing = sorted(set(codes) - {role.code for role in found})
    if missing:
        raise BusinessRuleViolationError(f"no role has the code(s): {', '.join(missing)}")
    return found


def _render(
    admin: AdminUser, role_codes: tuple[str, ...], *, replayed: bool = False
) -> AdminUserResult:
    return AdminUserResult(
        id=admin.id,
        username=admin.username,
        full_name=admin.full_name,
        email=admin.email,
        phone_number=admin.phone_number,
        status=admin.status,
        role_codes=role_codes,
        record_version=admin.record_version,
        replayed=replayed,
    )


def create_admin_user(
    command: NewAdminUser,
    *,
    uow: SqlAlchemyUnitOfWork,
    actor: AuditActor,
    context: AuditContext,
    idempotency_key: str,
    policy: RedactionPolicy,
    parameters: Argon2Parameters,
    password_max_length: int,
    now: datetime,
) -> AdminUserResult:
    """Create a staff account and its role grants, or replay the first identical request."""

    resolver = IdempotencyResolver(uow)
    claim = resolver.claim(
        actor_type=actor.actor_type,
        actor_id=actor.idempotency_scope_id,
        operation=CREATE_OPERATION,
        idempotency_key=idempotency_key,
        # The password is **not** in the payload. The resolver hashes this to detect a
        # same-key-different-body retry, and a credential inside that hash would be a
        # credential in a durable table — the one place doc 12:383 is most explicit
        # about. Username plus roles is enough to tell two different creations apart.
        payload={
            "username": command.username,
            "role_codes": sorted(command.role_codes),
            "email": command.email,
            "phone_number": command.phone_number,
        },
    )

    if claim.is_replay:
        stored = claim.record.response_body or {}
        existing = uow.session.get(AdminUser, uuid.UUID(str(stored["id"])))
        if existing is None:  # pragma: no cover - the record names a row it created
            raise NotFoundError()
        return _render(existing, tuple(stored.get("role_codes", ())), replayed=True)

    roles = _resolve_roles(uow, command.role_codes)

    taken = uow.session.scalar(
        select(func.count()).select_from(AdminUser).where(AdminUser.username == command.username)
    )
    if taken:
        # Named plainly. Usernames are not secrets here — this is an authenticated
        # administrator managing their own organisation's staff, not a public
        # registration surface, so the enumeration argument that shapes
        # `POST /traders/register` does not apply and a vague answer would only make
        # the operator guess.
        raise BusinessRuleViolationError(f"the username {command.username!r} is already taken")

    admin = AdminUser(
        username=command.username.strip(),
        full_name=command.full_name.strip(),
        email=(command.email or "").strip() or None,
        phone_number=(command.phone_number or "").strip() or None,
        password_hash=passwords.hash_password(
            command.password, parameters, max_length=password_max_length
        ),
        status=INITIAL_STATUS,
        password_changed_at=now,
    )
    uow.session.add(admin)
    uow.session.flush()

    for role in roles:
        uow.session.add(
            AdminUserRole(
                admin_user_id=admin.id,
                role_id=role.id,
                # Who granted it, which the bootstrap could not record and this can.
                granted_by_admin_id=actor.actor_id,
            )
        )

    codes = tuple(sorted(role.code for role in roles))
    AuditWriter(uow.session, policy).record(
        AuditEntry(
            action=CREATE_ADMIN_USER.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="admin_user",
            entity_id=admin.id,
            entity_record_version=admin.record_version,
            previous_values=None,
            new_values={"username": admin.username, "status": admin.status, "roles": list(codes)},
            reason=None,
            occurred_at=now,
            idempotency_record_id=claim.record.id,
            idempotency_key_hash=key_hash(idempotency_key),
            metadata={"operation": CREATE_OPERATION},
        ),
        actor=actor,
        context=context,
    )

    result = _render(admin, codes)
    resolver.complete(
        claim,
        response_code=200,
        # What a replay returns. The hash is absent here too: this body is stored.
        response_body={"id": str(admin.id), "role_codes": list(codes)},
        resource_type="admin_user",
        resource_id=admin.id,
        now=now,
    )
    return result


def amend_admin_user(
    command: AdminUserAmendment,
    *,
    uow: SqlAlchemyUnitOfWork,
    actor: AuditActor,
    context: AuditContext,
    policy: RedactionPolicy,
    now: datetime,
) -> AdminUserResult:
    """Change the contact details of a staff account under `If-Match`.

    What this deliberately cannot change: `username`, `status`, `password_hash` and role
    grants. The first is the login identifier and renaming it silently re-points every
    audit row a reader would join by name; the second belongs to suspend and reactivate,
    which are state transitions with their own guards; the third has its own route; the
    fourth is role management, which doc 12:642 requires an alert for. A PATCH that
    accepted any of them would be four commands wearing one name.
    """

    changes: dict[str, object] = {}
    if command.full_name is not None:
        changes["full_name"] = command.full_name.strip()
    if command.email is not None:
        changes["email"] = command.email.strip() or None
    if command.phone_number is not None:
        changes["phone_number"] = command.phone_number.strip() or None

    if not changes:
        raise BusinessRuleViolationError(
            "the request changes nothing; a no-op amendment would still consume the "
            "record version and make the next caller's If-Match stale"
        )

    before = uow.session.get(AdminUser, command.admin_user_id)
    if before is None:
        raise NotFoundError()
    previous = {field: getattr(before, field) for field in changes}

    # Through the shared helper, so the version check lives in the statement that
    # writes. A read-then-compare loses the race under READ COMMITTED and loses it
    # silently.
    outcome = compare_and_swap(
        uow.session,
        AdminUser,
        entity_id=command.admin_user_id,
        expected_version=command.expected_record_version,
        values=changes,
    )

    AuditWriter(uow.session, policy).record(
        AuditEntry(
            action=UPDATE_ADMIN_USER.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="admin_user",
            entity_id=command.admin_user_id,
            entity_record_version=outcome.new_version,
            previous_values=previous,
            new_values=changes,
            reason=None,
            occurred_at=now,
            metadata={"operation": UPDATE_ADMIN_USER.audit_action},
        ),
        actor=actor,
        context=context,
    )

    uow.session.refresh(before)
    return _render(before, _role_codes(uow, command.admin_user_id))


def _role_codes(uow: SqlAlchemyUnitOfWork, admin_user_id: uuid.UUID) -> tuple[str, ...]:
    """Live grants only. A revoked row is history, not authority."""

    return tuple(
        sorted(
            uow.session.scalars(
                select(Role.code)
                .join(AdminUserRole, AdminUserRole.role_id == Role.id)
                .where(AdminUserRole.admin_user_id == admin_user_id)
                .where(AdminUserRole.revoked_at.is_(None))
            )
        )
    )


def list_admin_users(uow: SqlAlchemyUnitOfWork) -> list[AdminUserResult]:
    """Every staff account, with its live roles.

    Unpaged, and that is a decision this slice records rather than hides: doc 05 marks
    this endpoint `none` for concurrency and says nothing about pagination, and the
    population is the centre's own staff — tens, not thousands. When it needs paging it
    needs the list-convention envelope M2 built, which is a contract change.
    """

    admins = list(uow.session.scalars(select(AdminUser).order_by(AdminUser.username)))
    return [_render(admin, _role_codes(uow, admin.id)) for admin in admins]


def read_admin_user(uow: SqlAlchemyUnitOfWork, admin_user_id: uuid.UUID) -> AdminUserResult:
    admin = uow.session.get(AdminUser, admin_user_id)
    if admin is None:
        raise NotFoundError()
    return _render(admin, _role_codes(uow, admin_user_id))


def known_statuses() -> tuple[str, ...]:
    """Exposed so a test can assert the response's status is one the column allows."""

    return ACCOUNT_STATUSES
