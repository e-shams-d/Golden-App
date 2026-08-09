"""What an actor may do, resolved from the seeded catalogue and failing closed.

`12_Security_RBAC_Audit.md:625` makes the backend's permission definitions
authoritative and `:629` requires unknown permissions to fail closed. Both are
structural here rather than conventions.

**An unknown permission fails at import, not at request time.** A route declaring
`payment_batch.aprove` would otherwise deny every caller silently, and the symptom
— "the manager cannot approve" — points at the grant rather than at the typo. The
declaration is checked against the approved catalogue when the module loads, so
the mistake is a failed start.

**Traders resolve no permissions at all.** `04_Database_Schema.md:405` states in
terms that trader access is determined by authenticated identity and ownership
scope, not through `admin_user_roles`. So this module answers `frozenset()` for a
trader and the ownership guard does the work — and `ActorContext` already refuses
to hold a trader with grants, so the two halves cannot disagree.

**A revoked grant stops granting immediately.** `admin_user_roles.revoked_at` is
the authority; the partial unique index means at most one live grant per
(user, role) pair, and the query filters on it rather than assuming the row was
deleted.

Covers: SEC-PERM-001, SEC-PERM-002, SEC-PERM-003.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.rbac import AdminUserRole, Permission, Role, RolePermission
from app.security.actor import Audience
from app.security.permission_catalogue import APPROVED_PERMISSIONS


class UnknownPermission(ValueError):
    """Raised at import time by `declare`, never at request time."""


def approved_permissions() -> frozenset[str]:
    """The approved canonical identifiers, from the inlined copy.

    Read from `app.security.permission_catalogue` rather than from
    `docs/governance/permission_catalog.yaml`, because `docs/` is not copied into
    the container image — a module that parsed it at import would crash every
    deployment on start-up, which is the same reason migration `20260801_0008`
    inlines its seed data. The copy is gated against the catalogue by
    `tests/backend/test_permission_catalogue_inline.py`.
    """

    return APPROVED_PERMISSIONS


def declare(code: str) -> str:
    """Name a permission a route requires, checked now rather than on first call.

    Returns the code so a route can write `dependencies=[requires(declare(...))]`
    and have the check happen at module import.
    """

    if code not in approved_permissions():
        raise UnknownPermission(
            f"{code!r} is not in the approved permission catalogue. A route declaring "
            "an unrecognised permission denies every caller silently, and the symptom "
            "points at the grant rather than at the typo. Add it to "
            "docs/governance/permission_catalog.yaml through the governance process, "
            "or fix the spelling."
        )
    return code


def resolve_for_admin(
    session: Session, admin_user_id: uuid.UUID
) -> tuple[frozenset[str], frozenset[str]]:
    """The live roles and permissions of one internal identity.

    Two sets rather than one because `12_Security_RBAC_Audit.md:575` says role
    names alone are not sufficient for sensitive authorization: the permission set
    is what a guard consults, and the role set is what an audit row records.
    """

    rows = session.execute(
        select(Role.code, Permission.code)
        .join(AdminUserRole, AdminUserRole.role_id == Role.id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(AdminUserRole.admin_user_id == admin_user_id)
        # The grant is live only while it has not been revoked. Filtering rather
        # than assuming deletion: the row is kept so an audit can say what was
        # held and when it stopped.
        .where(AdminUserRole.revoked_at.is_(None))
        .where(Role.is_enabled.is_(True))
    ).all()

    return frozenset(role for role, _ in rows), frozenset(permission for _, permission in rows)


def resolve(
    session: Session, audience: Audience, actor_id: uuid.UUID
) -> tuple[frozenset[str], frozenset[str]]:
    """Permissions for any actor. Traders hold none, by design."""

    if audience is Audience.TRADER:
        return frozenset(), frozenset()
    return resolve_for_admin(session, actor_id)
