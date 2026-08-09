"""Who is acting, and under what authority — assembled once, never from a request.

`12_Security_RBAC_Audit.md:377` requires domain services to consume an
authenticated `ActorContext` rather than transport-specific claims. Every field
here is therefore something the **server** established: read from the identity
row, from the session row, or from the grants resolved for that identity. None of
it is anything the caller sent.

That distinction is the whole point, and it is easiest to see in `trader_id`. A
trader's ownership scope arrives from `trader_users.trader_id`, looked up by the
session's actor id. `14_Testing_QA_Acceptance.md:1280` makes the alternative a
mandatory attack case — "trader A submits `trader_id` belonging to B" — and the
defence is not validation. It is that there is no path by which a request field
could reach this object.

`audience` is likewise structural rather than declared. `auth_sessions` carries a
CHECK that exactly one of `admin_user_id`/`trader_user_id` is set, so the audience
is read from which column is populated. DOC-CONFLICT-023's approved direction says
in terms: never trust a `user_type` field to select authority.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum


class Audience(StrEnum):
    """Which security domain an actor belongs to.

    Two domains, kept apart everywhere: `12_Security_RBAC_Audit.md:305-314`
    requires separate routes, session audiences, permission evaluation,
    middleware and DTOs, and `:316` states that a trader session must not be
    accepted as an internal one.
    """

    ADMIN = "admin"
    TRADER = "trader"


class ActorType(StrEnum):
    """The vocabulary `auth_events.actor_type` and `audit_logs` already enforce.

    Kept identical to `app.db.models.session_and_security.ACTOR_TYPES` rather
    than re-spelled; a second vocabulary for the same column is how DOC-CONFLICT-034
    happened.
    """

    ADMIN_USER = "admin_user"
    TRADER_USER = "trader_user"
    SYSTEM_WORKER = "system_worker"
    SYSTEM_MAINTENANCE = "system_maintenance"


@dataclass(frozen=True, slots=True)
class ActorContext:
    """An authenticated actor, as the domain sees it.

    Frozen because authority must not change between the guard that checked it
    and the command that acts on it. `slots=True` so a field cannot be attached
    at runtime — an `actor.is_admin = True` written in a hurry raises instead of
    creating a phantom permission that nothing declared.
    """

    actor_type: ActorType
    actor_id: uuid.UUID
    audience: Audience
    session_id: uuid.UUID

    # The security stamp the *session* was issued with. Compared against the
    # identity's current value on every protected request; a session carrying an
    # older one has had its authority changed since sign-in.
    security_stamp_version: int

    # Present only for a trader. The single source of ownership scope: `None`
    # here means the actor owns nothing, which is the correct answer for staff.
    trader_id: uuid.UUID | None = None

    # Resolved from the seeded RBAC catalogue for admins. Traders receive no
    # role grants at all — `04_Database_Schema.md:405` states trader access is
    # determined by authenticated identity and ownership scope, not by
    # `admin_user_roles` — so these stay empty and the ownership guard does the
    # work.
    roles: frozenset[str] = field(default_factory=frozenset)
    permissions: frozenset[str] = field(default_factory=frozenset)

    # `password` today. ADR-009 decides what else may appear, so nothing here
    # enumerates alternatives.
    auth_level: str = "password"

    def __post_init__(self) -> None:
        """Reject contexts that could not describe a real actor.

        Raising rather than returning a flag: an `ActorContext` that exists is a
        statement that authentication succeeded, and a half-built one would be
        passed to a permission check that reads the fields it does have.
        """

        if self.audience is Audience.TRADER:
            if self.actor_type is not ActorType.TRADER_USER:
                raise ValueError(
                    f"trader audience with actor_type {self.actor_type!r}: the audience is "
                    "read from which auth_sessions column is populated, so a mismatch "
                    "means the session row and this context disagree"
                )
            if self.trader_id is None:
                raise ValueError(
                    "a trader actor has no trader_id, so every ownership guard would have "
                    "a case with no answer. trader_users.trader_id is NOT NULL; a None here "
                    "means it was not read."
                )
            if self.permissions or self.roles:
                raise ValueError(
                    "a trader actor carries role grants. 04_Database_Schema.md:405 assigns "
                    "trader access to identity and ownership scope; grants here would make "
                    "a trader authorisable through the internal RBAC path."
                )
        elif self.audience is Audience.ADMIN:
            if self.actor_type is not ActorType.ADMIN_USER:
                raise ValueError(f"admin audience with actor_type {self.actor_type!r}: see above")
            if self.trader_id is not None:
                raise ValueError(
                    "an admin actor carries a trader_id. 12_Security_RBAC_Audit.md:316 "
                    "forbids treating an internal session as ownership of a trader account "
                    "without an explicitly authorised support workflow, and none exists."
                )

        if self.security_stamp_version <= 0:
            raise ValueError("security_stamp_version must be positive, as the column requires")

    @property
    def is_trader(self) -> bool:
        return self.audience is Audience.TRADER

    def owns(self, trader_id: uuid.UUID | None) -> bool:
        """Whether this actor's ownership scope covers `trader_id`.

        Staff never own: an internal session is not ownership of a trader account
        (`12_Security_RBAC_Audit.md:316`). Staff reach trader records through
        permissions instead, which is a different question asked elsewhere — so
        this returning `False` for an admin is the correct answer, not a gap.
        """

        return self.trader_id is not None and trader_id is not None and self.trader_id == trader_id
