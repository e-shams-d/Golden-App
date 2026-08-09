"""What an account may do right now — one answer, in one place.

The four values are DOC-CONFLICT-037's decision (Resolved 2026-08-08):
`active`, `suspended`, `recovery_required`, `deactivated`. A lock is deliberately
not among them; it is `locked_until`, a fact that expires without anything
running.

**A lock blocks signing in, and does not end a session already signed in.** That
asymmetry is the whole design of this module, and it is a security decision
rather than a convenience.

Lockout exists to stop online password guessing. An established session is not
guessing. If a lock also killed live sessions, then failing five logins against a
manager's username would end that manager's session — an attacker could log any
user out, on demand, without any credential, in the middle of approving a
payment batch. The control meant to frustrate an attacker would become a tool
for one.

The operational need a lock seems to serve — "cut this person off *now*" — is
served properly by `suspended`, which is an administrative act, is recorded, and
takes effect on the next request through the security stamp. Automatic lockout
and administrative suspension are different events and are kept as different
mechanisms.

`12_Security_RBAC_Audit.md:434` describes `locked` as blocking *authentication*,
which is the reading implemented here.

Covers: SEC-ACCT-001, SEC-ACCT-002, SEC-ACCT-003, SEC-LOCK-002.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

# DOC-CONFLICT-037's four, kept as one tuple so `app.db.models.identity` and this
# module cannot drift. The model owns the database CHECK; this owns the meaning.
ACTIVE = "active"
SUSPENDED = "suspended"
RECOVERY_REQUIRED = "recovery_required"
DEACTIVATED = "deactivated"


class AccountAction(StrEnum):
    """What is being attempted, because the answer differs by intent."""

    AUTHENTICATE = "authenticate"
    """Sign in with a credential."""

    RECOVER = "recover"
    """The approved credential-recovery flow, and nothing else."""

    ACT = "act"
    """Use a session that already exists."""


class AccountRefusal(StrEnum):
    """Why the account may not do the thing.

    Recorded in `auth_events`; never distinguished to the client, which receives
    one generic response for all of them (`12_Security_RBAC_Audit.md:403`).
    """

    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"
    RECOVERY_REQUIRED = "recovery_required"
    RECOVERY_NOT_APPLICABLE = "recovery_not_applicable"
    LOCKED = "locked"
    UNKNOWN_STATUS = "unknown_status"


def is_locked(locked_until: datetime | None, now: datetime) -> bool:
    """A lock is a timestamp in the future, not a stored state.

    This is why `locked` is not one of the four account values: it expires by
    itself, with nothing scheduled to unlock anything, and storing it twice would
    permit an `active` row with a future lock and no constraint able to say which
    is authoritative.
    """

    return locked_until is not None and locked_until > now


def refusal_for(
    status: str,
    locked_until: datetime | None,
    now: datetime,
    action: AccountAction,
) -> AccountRefusal | None:
    """`None` if the action is permitted, otherwise why not.

    An unknown status refuses everything. `12_Security_RBAC_Audit.md:629` requires
    unknown permissions to fail closed and the same reasoning applies here: a
    value this module does not recognise is a value whose meaning nobody has
    decided, and guessing it open is the one unrecoverable direction.
    """

    if status == DEACTIVATED:
        return AccountRefusal.DEACTIVATED

    if status == SUSPENDED:
        return AccountRefusal.SUSPENDED

    if status == RECOVERY_REQUIRED:
        # The one status whose answer depends on the intent. `:435` permits only
        # the approved credential-recovery flow, which means recovery is allowed
        # and everything else is not — including using a session issued before
        # the reset, so an administrative reset cannot be outlived by a tab that
        # was already open.
        if action is AccountAction.RECOVER:
            return None if not is_locked(locked_until, now) else AccountRefusal.LOCKED
        return AccountRefusal.RECOVERY_REQUIRED

    if status != ACTIVE:
        return AccountRefusal.UNKNOWN_STATUS

    if action is AccountAction.RECOVER:
        # An active account has nothing to recover from. Permitting it would give
        # an attacker who guesses a username a way to drive an account into
        # `recovery_required` and lock its owner out of a working credential.
        return AccountRefusal.RECOVERY_NOT_APPLICABLE

    if action is AccountAction.AUTHENTICATE and is_locked(locked_until, now):
        return AccountRefusal.LOCKED

    # AccountAction.ACT with an active status: permitted even while locked. See
    # the module docstring — a lock must not become a way to log someone out.
    return None
