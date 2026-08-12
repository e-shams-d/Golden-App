"""Create the first staff account, once, from a shell on the host.

`18_Production_Setup_and_Runbook.md:1094-1105` §11.8 requires this and states six
things the command must do. Until now it did not exist, and the consequence was not
theoretical: a fresh deployment accepted a public trader registration
(`POST /traders/register` is the platform's only unauthenticated write) and then could
never act on it, because approval needs `trader.approve`, which resolves only through
`admin_user_roles`, and **no code anywhere created an `AdminUser` or an
`AdminUserRole`.** The platform could not onboard its own first user.

WHY A COMMAND AND NOT A ROUTE. The bootstrap has to require a capability an attacker
cannot obtain by reaching the network, because at the moment it runs there is no
account to authenticate against and therefore nothing to check. Shell access to the
host running the database is the only such capability, and it is one whoever holds it
could already use directly. A "first-run endpoint that disables itself once an admin
exists" has the opposite property: its window is between `compose up` and the
operator's first action, and on a routable address the likely winner of that race is a
scanner. It is also untestable here without building the attacker's precondition —
"the route refuses once an admin exists" passes on every fixture in this repository,
because every fixture has an admin.

WHY NOT A MIGRATION. `12_Security_RBAC_Audit.md:386` and the SEED-ACCT-001 gate forbid
an identity row in a migration, and the reason is the one that matters here: a
migration ships in the image, so the credential would be identical in every
deployment. The operator supplies this one, so it differs by construction. Note that
`13_DevOps_Deployment_Operations.md:907` permits "a controlled command **or migration
task**" — this repository has taken the stricter reading, and that divergence is
recorded rather than assumed.

WHAT THIS COMMAND DOES NOT DO, and it is the requirement most worth stating.
Doc 18:1103 asks that the account "require credential change or secure activation".
This does not, and setting `status='recovery_required'` to fake it would be worse than
admitting the gap: `recovery_required` refuses **authentication**
(`app/security/account_state.py`), `AccountAction.RECOVER` is passed by no application
code, and there is no change-password route yet — so the flag would produce a
correctly-provisioned account that can never sign in and cannot be recovered. The
account is therefore created `active`, the operator is told so on stdout, and the gap
is owed to slice 8C.

Covers: SEED-ACCT-002.
"""

from __future__ import annotations

import argparse
import getpass
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TextIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import CREATE_FIRST_ADMIN
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.core.config import Settings
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.identity import AdminUser
from app.db.models.rbac import AdminUserRole, Permission, Role, RolePermission
from app.security import passwords
from app.security.passwords import Argon2Parameters

# Constructed here rather than taken from a default, because `RedactionPolicy` has
# none — `app/api/v1/traders.py:61` records why: the open decision has to stay visible
# at every call site. Masking is the right side to err on for a command that writes an
# identity row, even though nothing in this payload is an IBAN.
BOOTSTRAP_REDACTION = RedactionPolicy(mask_iban=True)

# The permission that decides whether a bootstrapped role is useful. An
# administrator who cannot create administrators is a dead end: they cannot be
# joined by a colleague, and they cannot hand over. `user.create` is therefore not a
# preference, it is the property that makes the account a *bootstrap* rather than
# merely the first account.
REQUIRED_PERMISSION = "user.create"

# Metadata envelope, matching what every other command records.
METADATA_SCHEMA = "audit.metadata"
METADATA_VERSION = 1

ALREADY_PROVISIONED = 2
USAGE_ERROR = 3


class BootstrapRefused(Exception):
    """The platform already has staff, or the requested role cannot bootstrap."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Created:
    admin_user_id: uuid.UUID
    username: str
    role_code: str
    audit_log_id: uuid.UUID


def _read_secret(stream: TextIO | None, prompt: str) -> str:
    """A password from a terminal, or from a pipe when there is no terminal.

    Never from `argv`. A password passed as an argument is visible in the process
    table to every user on the machine, is written to shell history, and survives in
    `docker inspect` for the lifetime of the container — three places it cannot be
    removed from afterwards.
    """

    if stream is not None:
        value = stream.readline().rstrip("\n")
    elif sys.stdin.isatty():
        value = getpass.getpass(prompt)
    else:
        value = sys.stdin.readline().rstrip("\n")
    if not value:
        raise BootstrapRefused("the password was empty", USAGE_ERROR)
    return value


def _resolve_bootstrap_role(session: Session, role_code: str) -> Role:
    """The requested role, refused unless it can actually create administrators.

    The check is against the *seeded grant*, not against a list written here. Asking
    the database which permissions the role holds means this command cannot disagree
    with migration `_0008` — and the failure it prevents is the quiet one: a role that
    looks administrative, provisions cleanly, and yields somebody who cannot add a
    second administrator or reset their own colleague.
    """

    role = session.scalar(select(Role).where(Role.code == role_code))
    if role is None:
        available = sorted(code for code in session.scalars(select(Role.code)))
        raise BootstrapRefused(
            f"no role has the code {role_code!r}. Seeded roles: {', '.join(available)}",
            USAGE_ERROR,
        )

    held = set(
        session.scalars(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role.id)
        )
    )
    if REQUIRED_PERMISSION not in held:
        raise BootstrapRefused(
            f"role {role_code!r} does not hold {REQUIRED_PERMISSION!r}, so the account "
            "it creates could never add a second administrator. Choose a role that "
            "holds it, or grant it first.",
            USAGE_ERROR,
        )
    return role


def bootstrap(
    session: Session,
    *,
    username: str,
    full_name: str,
    password: str,
    role_code: str,
    policy: RedactionPolicy,
    parameters: Argon2Parameters,
    password_max_length: int,
    now: datetime,
) -> Created:
    """Create the account, its role grant and its audit row, or nothing at all.

    The caller commits. Everything below is one transaction on purpose: an admin row
    without its grant is an account that cannot act, and a grant without an audit row
    is the most privileged act in the system's life going unrecorded.
    """

    # The guard is on the *platform having no staff*, not on the username being free.
    # A `username` check would let a second administrator be created by anyone who
    # picks a different name, which is precisely the capability this command must not
    # leave behind. Counting inside the same transaction as the insert is what makes
    # it a guard rather than a race.
    existing = session.scalar(select(func.count()).select_from(AdminUser)) or 0
    if existing:
        raise BootstrapRefused(
            f"the platform already has {existing} staff account(s); this command "
            "creates only the first. Use the administration API to add more.",
            ALREADY_PROVISIONED,
        )

    role = _resolve_bootstrap_role(session, role_code)

    admin = AdminUser(
        username=username.strip(),
        full_name=full_name.strip(),
        password_hash=passwords.hash_password(password, parameters, max_length=password_max_length),
        # `active`, and the reason is in the module docstring: `recovery_required`
        # would be provably unusable until slice 8C ships a recovery path.
        status="active",
        password_changed_at=now,
    )
    session.add(admin)
    # The grant needs the id and `autoflush=False` means nothing has assigned one.
    session.flush()

    session.add(
        AdminUserRole(
            admin_user_id=admin.id,
            role_id=role.id,
            # Nullable, and null is the truthful value: no administrator granted this.
            # Naming the new account as its own grantor would read, to anyone auditing
            # later, as a self-elevation performed through the API.
            granted_by_admin_id=None,
        )
    )

    entry = AuditWriter(session, policy).record(
        AuditEntry(
            action=CREATE_FIRST_ADMIN.audit_action,
            outcome="success",
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="admin_user",
            entity_id=admin.id,
            entity_record_version=admin.record_version,
            previous_values=None,
            new_values={"status": "active", "role": role.code},
            reason="platform bootstrap: no staff identity existed",
            occurred_at=now,
            metadata={"operation": CREATE_FIRST_ADMIN.audit_action},
        ),
        # `system_maintenance` with no id, which is not a convenience: the audit table
        # has a named CHECK requiring a human action to identify its actor, and
        # `AuditWriter` raises before the database does. Inventing a placeholder human
        # would make this row indistinguishable from a real attributed one — the same
        # reasoning public trader registration records at `app/api/v1/traders.py:151`.
        actor=AuditActor(actor_type="system_maintenance"),
        context=AuditContext(request_id=None),
    )
    # `record` stages the row and never commits, so its primary key is unassigned
    # until something flushes. Without this the command printed `audit_logs id None`
    # and told the operator to look for a record it could not name.
    session.flush()

    return Created(
        admin_user_id=admin.id,
        username=admin.username,
        role_code=role.code,
        audit_log_id=entry.id,
    )


def main(argv: Sequence[str] | None = None, *, secret_stream: TextIO | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.create_first_admin",
        description=(
            "Create the platform's first staff account. Refuses if any already exists. "
            "The password is read from a terminal or from stdin, never from arguments."
        ),
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--full-name", required=True)
    parser.add_argument(
        "--role",
        required=True,
        help=(
            "The role code to grant. Required rather than defaulted: which authority "
            "the first account carries is a decision about who installs the system "
            "versus who runs the business, and a default would make it silently."
        ),
    )
    arguments = parser.parse_args(argv)

    settings = Settings()
    runtime = RuntimeServices.from_settings(settings)
    try:
        password = _read_secret(secret_stream, "Password for the first administrator: ")
        parameters = Argon2Parameters.from_settings(settings)
        with runtime.uow_factory() as uow:
            created = bootstrap(
                uow.session,
                username=arguments.username,
                full_name=arguments.full_name,
                password=password,
                role_code=arguments.role,
                policy=BOOTSTRAP_REDACTION,
                parameters=parameters,
                password_max_length=settings.password_max_length,
                now=utc_now(),
            )
            uow.commit()
    except BootstrapRefused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return refusal.code
    finally:
        runtime.close()

    # The username and the audit row id, so the operator can find the record. Never
    # the password, and nothing derived from it.
    print(f"created admin_user {created.admin_user_id} username={created.username}")
    print(f"granted role {created.role_code}")
    print(f"audit_logs id {created.audit_log_id}")
    print(
        "NOTE: this account's password cannot yet be changed through the API. "
        "18_Production_Setup_and_Runbook.md:1103 requires a credential change on "
        "first use and no change-password route exists yet (M3 slice 8C owes it), so "
        "the install-time password stays in force until then. Treat it accordingly.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
