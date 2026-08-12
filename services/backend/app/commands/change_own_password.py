"""Changing your own password, and the first security-stamp increment in the codebase.

`12_Security_RBAC_Audit.md:468-477` lists the triggers that must invalidate a live
session, and a credential change is one of them. The mechanism was built in M2 —
`auth_sessions.security_stamp_version` is copied from the identity at login and compared
on every request — and until this command, **nothing ever incremented it.** Thirteen
references across `app/`, every one a read, a copy, a column declaration or a `> 0`
CHECK. So the obligation that a bump invalidates sessions was green against a mechanism
with no producer, and its negative control could not fail.

THE PART THAT CANNOT BE IMPLEMENTED AS THE PLAN PHRASES IT. The plan asks that a change
"revokes the caller's other sessions and keeps the current one". A bump alone does not
do that: `sessions.classify_stamp` compares for **equality** and treats a session ahead
of its identity as its own rejection, deliberately, so that a restored identity table
cannot silently re-authorise old sessions. One increment therefore invalidates *every*
session including the caller's. Keeping the current one means writing that session's own
stamp forward in the same transaction — which is a second write, not a subtlety of the
first, and it is the reason this command exists rather than a one-line update.

WHICH SESSION IS "CURRENT" IS NOT A CLIENT'S ANSWER. The id comes from the
already-authenticated actor. If it came from the request body, "keeps the current one"
would let a caller nominate somebody else's session to spare and revoke their own — a
guarantee inverted by the party it is meant to protect.

Covers: API-PWD-001, SEC-STAMP-002.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, update
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import CHANGE_OWN_PASSWORD
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.db.models.identity import AdminUser, TraderUser
from app.db.models.session_and_security import AuthSession
from app.security import passwords
from app.security.actor import Audience
from app.security.passwords import Argon2Parameters

METADATA_SCHEMA = "audit.metadata"
METADATA_VERSION = 1

# The reason written on every session this command ends. Taken from the value the suite
# already writes (`tests/integration/test_sessions_and_security_events.py:166`) rather
# than coined here: a second spelling of one reason is permanent, lives in a database
# column, and makes an incident report depend on which code path ended the session.
REVOCATION_REASON = "password_changed"


@dataclass(frozen=True, slots=True)
class PasswordChanged:
    new_stamp: int
    other_sessions_revoked: int


def change_own_password(
    identity: AdminUser | TraderUser,
    *,
    session: Session,
    audience: Audience,
    current_session_id: uuid.UUID,
    new_password: str,
    policy: RedactionPolicy,
    parameters: Argon2Parameters,
    password_max_length: int,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> PasswordChanged:
    """Rotate the credential, invalidate every other session, keep this one.

    The caller commits. Everything here is one transaction because the three writes are
    one fact: a credential that changed without its sessions ending is the old
    credential still working, and sessions that ended without the credential changing is
    an outage.
    """

    new_stamp = identity.security_stamp_version + 1

    identity.password_hash = passwords.hash_password(
        new_password, parameters, max_length=password_max_length
    )
    identity.password_changed_at = now
    identity.security_stamp_version = new_stamp

    owner_column = (
        AuthSession.admin_user_id if audience is Audience.ADMIN else AuthSession.trader_user_id
    )

    # Every live session of this identity except the caller's. `revoked_at IS NULL` keeps
    # the count honest — without it a repeated change would report revoking sessions it
    # had already ended, and the reason on an already-revoked row would be overwritten
    # with a later cause than the one that actually ended it.
    # `Session.execute` is typed as returning `Result`, and `rowcount` belongs to the
    # `CursorResult` a DML statement actually produces. Cast rather than ignore, so the
    # narrowing says which type it is instead of only that mypy was wrong.
    revocation = cast(
        "CursorResult[Any]",
        session.execute(
            update(AuthSession)
            .where(owner_column == identity.id)
            .where(AuthSession.id != current_session_id)
            .where(AuthSession.revoked_at.is_(None))
            .values(revoked_at=now, revocation_reason=REVOCATION_REASON, updated_at=now)
        ),
    )
    revoked = revocation.rowcount

    # And the caller's own, carried forward to the new stamp. Without this line the
    # caller is signed out by their own password change: `classify_stamp` demands
    # equality, so the session it copied the old value into now disagrees with the
    # identity and is rejected as STAMP_BEHIND.
    session.execute(
        update(AuthSession)
        .where(AuthSession.id == current_session_id)
        .values(security_stamp_version=new_stamp, updated_at=now)
    )

    AuditWriter(session, policy).record(
        AuditEntry(
            action=CHANGE_OWN_PASSWORD.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="admin_user" if audience is Audience.ADMIN else "trader_user",
            entity_id=identity.id,
            entity_record_version=identity.record_version,
            # No values on either side. `previous_values` is where an audit row would
            # otherwise carry a password hash, and doc 12:383 keeps credential material
            # out of readable records — the fact that changed is the whole content here,
            # and the stamp is what makes it verifiable after the fact.
            previous_values=None,
            new_values={"security_stamp_version": new_stamp},
            reason=None,
            occurred_at=now,
            metadata={
                "operation": CHANGE_OWN_PASSWORD.audit_action,
                "other_sessions_revoked": revoked,
            },
        ),
        actor=actor,
        context=context,
    )

    return PasswordChanged(new_stamp=new_stamp, other_sessions_revoked=revoked)
