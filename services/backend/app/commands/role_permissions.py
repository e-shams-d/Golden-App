"""Replacing a role's permission set — and the first production consumer of step-up.

`app/security/step_up.py` has been complete since slice 7: contexts are issued, bound to
four things, hashed, and `rejection_for` decides whether a presented one authorises a
command. **Nothing ever presented one.** `rejection_for` had zero production call sites,
so six obligations were green against a mechanism no route exercised, and the binding
argument — a context for batch version 7 must not approve version 8 — was a docstring.
This command is where that stops being true, and it is the right first consumer:
`12_Security_RBAC_Audit.md:642` names recent authentication as a requirement for
high-risk grants in the same sentence as the alert.

**The header is `X-Recent-Auth`**, which is the name `packages/api-client` already sends.
Choosing a different spelling here would have made the shipped client wrong about a route
it was written for.

**Concurrency is a content ETag, not `rv-N`, and that is a decision rather than an
inconsistency.** Every other route in this API publishes `"rv-<record_version>"` because
its entity has that column. `roles` does not — see `app/db/models/rbac.py`, which has
`created_at` and `updated_at` and no version — and adding one would be a migration in a
slice about authorisation. A digest of the sorted permission codes gives the guarantee
`If-Match` exists for: a caller who read the set and then writes is refused if anybody
changed it in between. It also refuses something a version column would not — two callers
who each write the *same* new set are the only case where a content ETag says "already
done" and a version says "conflict", and for a set replacement the content answer is the
truthful one.

**No `Idempotency-Key`.** A recent-auth context is consumable exactly once, so a retried
request cannot re-apply the change: the second attempt is refused as `ALREADY_CONSUMED`
before it reaches the write. Requiring a second single-use token would be requiring the
same guarantee twice, and the four trader decision routes already demonstrate the cost of
a header that is required and then discarded.

**Break-glass is refused, not alerted.** See `app/security/high_risk_grants.py` — POL-005
disables `break_glass.activate` for Phase 1A "with no endpoint, grant, feature flag,
runtime activation or financial bypass", so a grant of it is a policy violation rather
than a high-risk act to be recorded.

**Removals are refused too, and for a different reason: this codebase may not delete.**
`tests/backend/test_no_deletion_machinery.py` forbids every `delete(...)` in `app/` while
ADR-005 is open, absolutely and with no allowlist. Taking a permission away from a role
means deleting a `role_permissions` row, so the removal half of a set replacement cannot
be built here. It is refused with a message naming the constraint rather than omitted,
and the route still accepts the full set — a caller sending an unchanged or larger set
succeeds, and one sending a smaller set is told exactly why it cannot. Authority is
withdrawn in the two places the schema already models it: `admin_user_roles.revoked_at`
and `roles.is_enabled`.

Covers: SEC-ROLECHANGE-001, AUD-ROLE-001.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import UPDATE_ROLE_PERMISSIONS
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.db.models.rbac import Permission, Role, RolePermission
from app.db.models.session_and_security import AuthEvent, RecentAuthContext
from app.security import high_risk_grants, step_up
from app.security.actor import ActorContext
from app.security.events import OUTCOME_DENIED, OUTCOME_SUCCESS, SecurityEvent
from app.security.step_up import StepUpRefused, StepUpRejection, StepUpRequest

METADATA_SCHEMA = "audit.metadata"
METADATA_VERSION = 1

# What a caller must have re-authenticated *for*. Bound to the role as the resource, so a
# step-up obtained to edit `accountant` cannot be spent editing `business_admin` — the
# batch-version-7-approves-8 case, in the shape this route has.
STEP_UP_PURPOSE = "role.permissions.update"
STEP_UP_RESOURCE_TYPE = "role"

# The alert's event type and class. `administrative` is the `EVENT_CLASSES` member for an
# authorised administrative act, which is what this is — the row is not a refusal.
ALERT_EVENT_TYPE = "role.high_risk_permission_granted"
ALERT_EVENT_CLASS = "administrative"


@dataclass(frozen=True, slots=True)
class RolePermissionUpdate:
    role_id: uuid.UUID
    permission_codes: tuple[str, ...]
    expected_etag: str
    recent_auth_reference: str
    reason: str


@dataclass(frozen=True, slots=True)
class RolePermissionsUpdated:
    role_id: uuid.UUID
    role_code: str
    permission_codes: tuple[str, ...]
    etag: str
    granted: tuple[str, ...]
    revoked: tuple[str, ...]
    alerts_written: int


class StaleRolePermissions(Exception):
    """The `If-Match` digest names a permission set that is no longer current."""


# `StepUpRefused` moved to `app/security/step_up.py` when M7's approval became the second
# command to raise it. Re-exported here because `app/api/v1/roles.py` catches
# `role_permissions.StepUpRefused` and that spelling is still the honest one for a reader of
# this module — the class did not change, only where it is defined.
__all__ = ["StepUpRefused"]


def permission_etag(codes: tuple[str, ...]) -> str:
    """A stable digest of a permission set.

    Sorted before hashing, so the ETag describes the set and not the order a query
    happened to return it in — an ETag that changed when nothing did would make every
    write fail intermittently and teach callers to send `*`.
    """

    joined = "\n".join(sorted(codes))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]


def current_codes(session: Session, role_id: uuid.UUID) -> tuple[str, ...]:
    return tuple(
        sorted(
            session.scalars(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role_id)
            )
        )
    )


def _consume_context(
    session: Session,
    reference: str,
    actor: ActorContext,
    role_id: uuid.UUID,
    now: datetime,
) -> RecentAuthContext | StepUpRejection:
    """Find the presented context, decide whether it authorises this, and spend it.

    Consumption happens inside the caller's transaction, which is the requirement
    `recent_auth_contexts.consumed_at` exists for: marking it spent in a separate
    transaction would let a timeout-and-retry apply the change twice on one step-up.
    """

    stored = session.scalar(
        select(RecentAuthContext).where(
            RecentAuthContext.challenge_hash == step_up.digest_reference(reference)
        )
    )

    # Through the value object rather than passing the ORM row, which is the shape
    # `rejection_for` asks for: it keeps the comparison logic free of a database and every
    # rejection branch reachable from a unit test.
    presented = (
        None
        if stored is None
        else step_up.PresentedContext(
            actor_id=stored.actor_id,
            session_id=stored.session_id,
            purpose=stored.purpose,
            resource_type=stored.resource_type,
            resource_id=stored.resource_id,
            assurance_factor=stored.assurance_factor,
            expires_at=stored.expires_at,
            consumed_at=stored.consumed_at,
            revoked_at=stored.revoked_at,
        )
    )

    rejection = step_up.rejection_for(
        presented,
        actor=actor,
        request=StepUpRequest(
            purpose=STEP_UP_PURPOSE,
            resource_type=STEP_UP_RESOURCE_TYPE,
            resource_id=role_id,
        ),
        now=now,
    )
    if rejection is not None:
        return rejection

    assert stored is not None  # `rejection_for` returns UNKNOWN_REFERENCE for None
    stored.consumed_at = now
    stored.consumed_by_command = UPDATE_ROLE_PERMISSIONS.audit_action
    return stored


def update_role_permissions(
    command: RolePermissionUpdate,
    *,
    session: Session,
    actor: ActorContext,
    audit_actor: AuditActor,
    context: AuditContext,
    policy: RedactionPolicy,
    now: datetime,
) -> RolePermissionsUpdated:
    """Replace the set, alert on the high-risk additions, refuse the forbidden one.

    The caller commits. Everything is one transaction because the step-up consumption, the
    permission rows and the alert are one fact — an alert that survived a rolled-back grant
    would send somebody to investigate a change that never happened, and a consumed context
    beside an unapplied change would cost the caller their step-up for nothing.
    """

    role = session.get(Role, command.role_id)
    if role is None:
        raise NotFoundError()

    if not command.reason.strip():
        # `:642` lists "reason" among what a role change must carry, alongside the
        # before/after audit and the alert. It is not optional there and is not here.
        raise BusinessRuleViolationError(
            "a role permission change requires a reason; doc 12:642 lists it among what "
            "such a change must produce"
        )

    before = current_codes(session, command.role_id)
    if permission_etag(before) != command.expected_etag.strip().strip('"'):
        raise StaleRolePermissions()

    requested = frozenset(command.permission_codes)
    found = {
        permission.code: permission
        for permission in session.scalars(select(Permission).where(Permission.code.in_(requested)))
    }
    missing = sorted(requested - set(found))
    if missing:
        # Refused rather than filtered, for the reason `_resolve_roles` gives about roles:
        # a silently-dropped permission hands back a role with less authority than the
        # caller asked for, and it is discovered the next time somebody cannot do their job.
        raise BusinessRuleViolationError(f"no permission has the code(s): {', '.join(missing)}")

    granted = requested - frozenset(before)
    revoked = frozenset(before) - requested

    forbidden, alertable = high_risk_grants.classify(granted)
    if forbidden:
        raise BusinessRuleViolationError(high_risk_grants.FORBIDDEN_REASON)

    # The step-up is consumed **after** the refusals above and before any write. Spending
    # a caller's single-use assurance on a request that was going to be refused anyway
    # would make them re-authenticate to learn they made a typo.
    consumed = _consume_context(session, command.recent_auth_reference, actor, role.id, now)
    if isinstance(consumed, StepUpRejection):
        # The reason is recorded and never returned: a caller who could tell "expired"
        # from "wrong role" could map which contexts exist.
        session.add(
            AuthEvent(
                **SecurityEvent(
                    actor_type=actor.actor_type.value,
                    actor_id=actor.actor_id,
                    session_id=actor.session_id,
                    event_type="step_up.rejected",
                    event_class="authorization",
                    outcome=OUTCOME_DENIED,
                    metadata_payload={"rejection_reason": consumed.value, "role_code": role.code},
                ).as_row()
            )
        )
        raise StepUpRefused(consumed)

    if revoked:
        # THE HALF THIS SLICE CANNOT BUILD, and it is refused rather than quietly omitted.
        #
        # Removing a permission from a role means deleting a `role_permissions` row, and
        # `tests/backend/test_no_deletion_machinery.py` forbids every `delete(...)` in
        # `app/` while ADR-005 is open. That gate is absolute by design and has no
        # allowlist: its own docstring anticipates this exact argument — "nobody reviews a
        # pull request looking for the purge job it *added*, because adding one looks like
        # finishing the feature" — and it names a route as the most dangerous place for
        # one, because a route is reachable by anyone holding a token.
        #
        # Writing an exception for the first slice that trips it, justified by the slice
        # that needs it, is the pattern this repository refuses. So the request is refused
        # and the gap is visible, rather than the gate being widened and the gap invisible.
        #
        # **No deployment is stranded by this.** Authority is withdrawn at the assignment
        # layer, which is where the schema already models revocation properly:
        # `admin_user_roles.revoked_at` exists precisely so a grant can be withdrawn while
        # keeping its history, and `roles.is_enabled` disables a role outright. Removing a
        # permission from a role is the only one of the three that needs a DELETE, and it
        # is the only one this refuses.
        raise BusinessRuleViolationError(
            "this request would remove "
            + ", ".join(sorted(revoked))
            + " from the role, which means deleting a role_permissions row. ADR-005 is "
            "open and no governed deletion procedure exists, so nothing in this codebase "
            "may issue a delete. Withdraw authority by revoking the role from the people "
            "who hold it, or by disabling the role — both are recorded and reversible."
        )

    for code in sorted(granted):
        session.add(RolePermission(role_id=role.id, permission_id=found[code].id))

    after = tuple(sorted(requested))

    AuditWriter(session, policy).record(
        AuditEntry(
            action=UPDATE_ROLE_PERMISSIONS.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="role",
            entity_id=role.id,
            entity_record_version=None,
            # The before/after `:642` requires, as the sets rather than as a diff: a
            # reader reconstructing authority at a point in time needs what the role held,
            # and a diff makes them replay every row from the beginning to find out.
            previous_values={"permission_codes": list(before)},
            new_values={"permission_codes": list(after)},
            reason=command.reason,
            occurred_at=now,
            metadata={
                "operation": UPDATE_ROLE_PERMISSIONS.audit_action,
                "role_code": role.code,
                "granted": sorted(granted),
                "revoked": sorted(revoked),
            },
        ),
        actor=audit_actor,
        context=context,
    )

    # One alert row per high-risk permission, not one per request. An operator reviewing
    # them should be able to count "how many times has audit export been granted" without
    # parsing a list out of a metadata blob.
    for code, capability in sorted(alertable.items()):
        session.add(
            AuthEvent(
                **SecurityEvent(
                    actor_type=actor.actor_type.value,
                    actor_id=actor.actor_id,
                    session_id=actor.session_id,
                    event_type=ALERT_EVENT_TYPE,
                    event_class=ALERT_EVENT_CLASS,
                    # `success`, because the grant succeeded. The row is an alert, not a
                    # refusal — recording it as a failure would put it in
                    # `idx_auth_events_failures` and make every high-risk grant look like
                    # an incident to anything reading that index.
                    outcome=OUTCOME_SUCCESS,
                    metadata_payload={
                        "capability": capability,
                        "permission_code": code,
                        "role_code": role.code,
                    },
                ).as_row()
            )
        )

    return RolePermissionsUpdated(
        role_id=role.id,
        role_code=role.code,
        permission_codes=after,
        etag=permission_etag(after),
        granted=tuple(sorted(granted)),
        revoked=tuple(sorted(revoked)),
        alerts_written=len(alertable),
    )
