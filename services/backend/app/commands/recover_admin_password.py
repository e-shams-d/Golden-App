"""Completing a recovery — the transition that stops `recovery_required` being terminal.

`app/security/account_state.py` has described this flow since M2. `AccountAction.RECOVER`
is one of its three intents, and `refusal_for` already answers "permitted" for exactly one
combination: a `recovery_required` account that is not locked. **Nothing ever passed that
intent.** Every caller in the codebase asked `AUTHENTICATE` or `ACT`, so the branch that
makes the state escapable was reachable only from a unit test, and `SEC-ACCT-003` was
discharged by a pure-function call in a file whose own docstring says "No database and no
Redis server".

That is what slice 8B recorded when it declined to start accounts in `recovery_required`:
the state refuses authentication and had no exit, so provisioning into it would have
produced a correctly-built account nobody could sign in to. The reset in
`admin_user_state.py` creates that state deliberately, so this is the slice that owes the
way out — and `18_Production_Setup_and_Runbook.md:1103` is the requirement it finally
satisfies.

**No session, and no session is created.** The account cannot act, so it cannot hold a
session to present, and issuing one here would hand a session to a credential the caller
was given by somebody else. Recovery ends with the account `active` and the person
signing in normally, which is one extra step and the only shape in which the credential
the administrator chose never becomes access on its own.

**Every live session is revoked, including any the reset missed.** The reset already ended
them; this runs again because a recovery can happen long afterwards, and "the previous
command already did it" is an assumption about a window this command has no way to bound.

**The stamp is bumped a second time.** The reset bumped it once, so anything holding a
copy is already refused. Bumping again is not redundant: between the reset and the
recovery an operator may have restored a database, and `sessions.classify_stamp` compares
for equality precisely so a restored identity row cannot silently re-authorise sessions
that outlived it.

Covers: SEC-ACCT-003.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import RECOVER_ADMIN_PASSWORD
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.db.models.identity import AdminUser
from app.db.models.session_and_security import AuthSession
from app.security import account_state, passwords
from app.security.account_state import AccountAction, AccountRefusal
from app.security.identifiers import InvalidIdentifier, normalize_username
from app.security.passwords import Argon2Parameters

METADATA_SCHEMA = "audit.metadata"
METADATA_VERSION = 1

RECOVERY_REVOCATION = "credential_recovered"


@dataclass(frozen=True, slots=True)
class RecoveryAttempt:
    username: str
    current_password: str
    new_password: str


@dataclass(frozen=True, slots=True)
class RecoveryOutcome:
    """Whether it worked, and — for the log only — why not.

    `refusal` is never rendered to the client. The route answers one generic failure for
    an unknown username, a wrong temporary password and an account that is not awaiting
    recovery, exactly as the login route does (`12_Security_RBAC_Audit.md:403`).
    Distinguishing them would make this route a membership oracle **and** a status oracle
    for the centre's own staff, which is a more useful answer to an attacker than the
    login route gives.
    """

    succeeded: bool
    refusal: str | None = None
    sessions_revoked: int = 0


def _failure(reason: str) -> RecoveryOutcome:
    return RecoveryOutcome(succeeded=False, refusal=reason)


def recover_admin_password(
    attempt: RecoveryAttempt,
    *,
    session: Session,
    policy: RedactionPolicy,
    parameters: Argon2Parameters,
    password_max_length: int,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> RecoveryOutcome:
    """Verify the temporary credential, set the chosen one, return the account to `active`.

    The caller commits on success and rolls back the identity writes on failure — but the
    security event the route records must survive either way, which is why this returns an
    outcome instead of raising.
    """

    try:
        username = normalize_username(attempt.username)
    except InvalidIdentifier:
        return _failure("invalid_identifier")

    admin = session.scalar(select(AdminUser).where(AdminUser.username == username))
    if admin is None:
        # The password is deliberately **not** verified against a dummy hash here, unlike
        # the login route. That defence exists to flatten the timing difference between a
        # known and an unknown username; this route is reachable only by somebody who has
        # been told a username and a temporary password out of band, and is rate-limited
        # on the same network axis. Adding a dummy verification would be copying a
        # mitigation without its threat — and pretending to check a credential is the kind
        # of code that later gets mistaken for checking one.
        return _failure("unknown_username")

    refusal = account_state.refusal_for(
        admin.status, admin.locked_until, now, AccountAction.RECOVER
    )
    if refusal is not None:
        # The interesting one is `RECOVERY_NOT_APPLICABLE`: an `active` account has
        # nothing to recover from, and permitting it would let anybody holding a working
        # password drive their own account into a state only an administrator can create.
        return _failure(refusal.value)

    verification = passwords.verify_password(
        admin.password_hash, attempt.current_password, parameters, max_length=password_max_length
    )
    if not verification.is_valid:
        return _failure("wrong_password")

    previous_status = admin.status
    new_stamp = admin.security_stamp_version + 1

    admin.password_hash = passwords.hash_password(
        attempt.new_password, parameters, max_length=password_max_length
    )
    admin.password_changed_at = now
    admin.security_stamp_version = new_stamp
    admin.status = account_state.ACTIVE
    admin.failed_login_count = 0
    admin.locked_until = None

    revocation = cast(
        "CursorResult[Any]",
        session.execute(
            update(AuthSession)
            .where(AuthSession.admin_user_id == admin.id)
            .where(AuthSession.revoked_at.is_(None))
            .values(revoked_at=now, revocation_reason=RECOVERY_REVOCATION, updated_at=now)
        ),
    )
    revoked = revocation.rowcount

    AuditWriter(session, policy).record(
        AuditEntry(
            action=RECOVER_ADMIN_PASSWORD.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="admin_user",
            entity_id=admin.id,
            entity_record_version=admin.record_version,
            # No hashes on either side, the same rule the change and reset commands follow:
            # doc 12:383 keeps credential material out of readable records, and the fact
            # that changed is the status and the stamp.
            previous_values={"status": previous_status},
            new_values={"status": account_state.ACTIVE, "security_stamp_version": new_stamp},
            reason=None,
            occurred_at=now,
            metadata={
                "operation": RECOVER_ADMIN_PASSWORD.audit_action,
                "sessions_revoked": revoked,
            },
        ),
        actor=actor,
        context=context,
    )

    return RecoveryOutcome(succeeded=True, sessions_revoked=revoked)


def is_permitted_refusal(refusal: str) -> bool:
    """Whether a refusal string is one `account_state` produced, for the event log.

    Exists so the route records a value from the state machine's vocabulary rather than a
    string it invented, and so a test can assert the set has not quietly grown.
    """

    return refusal in {member.value for member in AccountRefusal} or refusal in {
        "invalid_identifier",
        "unknown_username",
        "wrong_password",
    }
