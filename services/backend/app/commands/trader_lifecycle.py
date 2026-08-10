"""Registering a trader, and the center's four decisions about one.

Five commands, one transaction each, none of them committing — the route owns the
boundary, as every command in this codebase does.

**Registration creates two rows or neither.** A `traders` row without its primary
contact is a business nobody can sign in to; a `trader_users` row without its
business fails the `NOT NULL` foreign key slice 1 added. Doing both in one
transaction is not an optimisation, it is the only correct shape, and
`API-REG-001` proves the failure path leaves nothing behind.

**Registration tells the caller nothing about who already exists.** A public
endpoint that answered "this phone number is already registered" would be a
membership oracle for the platform's entire customer list — and in a market where
knowing which goldsmiths deal with which center is commercially useful, that is
not a small leak. So a duplicate answers exactly as a success does, and the
duplicate is recorded for staff rather than reported to the caller.

**The four decisions are the center's, and none of them is self-service.**
`approve` and `reject` move `approval_status`; `suspend` and `reactivate` move
`operational_status`. They are separate axes (DOC-CONFLICT-024) and separate
permissions, because a business that is barred today is not a business whose
counterparty relationship was rejected.

Covers: API-REG-001, API-REG-002, API-REG-003, API-APPROVE-001, API-APPROVE-002.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.outbox import OutboxMessage, OutboxWriter
from app.audit.redaction import RedactionPolicy
from app.audit.registry import (
    APPROVE_TRADER,
    REACTIVATE_TRADER,
    REGISTER_TRADER,
    REJECT_TRADER,
    SUSPEND_TRADER,
    CommandNames,
)
from app.audit.writer import (
    AuditActor,
    AuditContext,
    AuditEntry,
    AuditWriter,
)
from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.db.concurrency import compare_and_swap
from app.db.models.identity import TraderUser
from app.db.models.trader import Trader
from app.security import passwords
from app.security.identifiers import normalize_mobile
from app.security.passwords import Argon2Parameters

PAYLOAD_VERSION = 1

# Declared per command family, as `rename_center_profile` does.
# `FINANCIAL_INTEGRITY_BASELINE.md` §4 requires both descriptors on every row, and
# a shared constant would mean one schema name describing metadata of two
# different shapes — which is the thing a version number exists to prevent.
METADATA_SCHEMA = "audit.trader.lifecycle"
METADATA_VERSION = 1

# `traders.approval_status`, per `04_Database_Schema.md:459`.
PENDING_APPROVAL = "pending_approval"
APPROVED = "approved"
REJECTED = "rejected"

# `traders.operational_status`, per `:458`. A newly registered business is
# `inactive` rather than `active`: nothing about submitting a form makes a
# counterparty able to transact, and starting active would mean the approval step
# only ever *removes* capability, which inverts what approval means.
INACTIVE = "inactive"
ACTIVE = "active"
SUSPENDED = "suspended"


@dataclass(frozen=True, slots=True)
class RegisterTrader:
    display_name: str
    primary_phone: str
    contact_full_name: str
    password: str
    legal_name: str | None = None


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    """Deliberately carries no identifiers.

    Returning the new `trader_id` would let a caller distinguish a real
    registration from the no-op a duplicate produces, which is the oracle this
    command exists to avoid. The trader learns their state by signing in.
    """

    accepted: bool


@dataclass(frozen=True, slots=True)
class TraderDecision:
    trader_id: uuid.UUID
    expected_record_version: int
    reason: str | None = None


def register_trader(
    command: RegisterTrader,
    *,
    session: Session,
    policy: RedactionPolicy,
    parameters: Argon2Parameters,
    password_max_length: int,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> RegistrationResult:
    """Create a pending business and its primary contact, or record a duplicate.

    Both rows or neither. The caller cannot tell which happened.
    """

    phone = normalize_mobile(command.primary_phone)

    existing = session.scalar(select(Trader).where(Trader.primary_phone == phone))
    if existing is not None:
        # Recorded so staff can see a repeated attempt, and answered as a success
        # so the caller learns nothing. `outcome` distinguishes the two for anyone
        # reading `audit_logs`.
        _audit(
            session,
            policy,
            REGISTER_TRADER,
            outcome="rejected",
            entity_id=existing.id,
            record_version=existing.record_version,
            reason="duplicate_primary_phone",
            actor=actor,
            context=context,
            now=now,
        )
        return RegistrationResult(accepted=True)

    trader = Trader(
        display_name=command.display_name.strip(),
        legal_name=(command.legal_name or "").strip() or None,
        primary_phone=phone,
        operational_status=INACTIVE,
        approval_status=PENDING_APPROVAL,
    )
    session.add(trader)
    # The contact's foreign key needs the id, and `autoflush=False` means nothing
    # has assigned one yet.
    session.flush()

    session.add(
        TraderUser(
            trader_id=trader.id,
            phone_number=phone,
            full_name=command.contact_full_name.strip(),
            password_hash=passwords.hash_password(
                command.password, parameters, max_length=password_max_length
            ),
            # `active` is the *account* axis: this person may sign in. What they
            # can reach is decided by the business being `pending_approval`, which
            # is the separation DOC-CONFLICT-024 requires.
            status="active",
            is_primary=True,
        )
    )

    _audit(
        session,
        policy,
        REGISTER_TRADER,
        outcome="success",
        entity_id=trader.id,
        record_version=trader.record_version,
        reason=None,
        actor=actor,
        context=context,
        now=now,
        new_values={"approval_status": PENDING_APPROVAL, "operational_status": INACTIVE},
    )
    _publish(session, policy, REGISTER_TRADER, trader, context)

    return RegistrationResult(accepted=True)


def decide(
    command: TraderDecision,
    names: CommandNames,
    *,
    session: Session,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> Trader:
    """Apply one of the center's four decisions, with optimistic concurrency.

    Through `compare_and_swap` rather than a read-then-write: the comparison
    belongs in the statement that writes, because a check in Python loses the race
    under READ COMMITTED and loses it silently.
    """

    trader = session.get(Trader, command.trader_id)
    if trader is None:
        raise NotFoundError()

    previous = {
        "approval_status": trader.approval_status,
        "operational_status": trader.operational_status,
    }
    values = _values_for(names, trader, actor, now)

    outcome = compare_and_swap(
        session,
        Trader,
        entity_id=command.trader_id,
        expected_version=command.expected_record_version,
        values=values,
    )

    session.expire(trader)
    _audit(
        session,
        policy,
        names,
        outcome="success",
        entity_id=command.trader_id,
        record_version=outcome.new_version,
        reason=command.reason,
        actor=actor,
        context=context,
        now=now,
        previous_values=previous,
        new_values=_json_safe(values),
    )
    _publish(session, policy, names, trader, context, version=outcome.new_version)
    return trader


def _values_for(
    names: CommandNames, trader: Trader, actor: AuditActor, now: datetime
) -> dict[str, Any]:
    """What each decision changes, and which transitions it refuses.

    Refusals are `BusinessRuleViolationError` rather than silent no-ops: an
    operator who approved an already-rejected business needs to know the request
    did not do what they meant, and a 200 that changed nothing reads as success.
    """

    if names is APPROVE_TRADER:
        if trader.approval_status == REJECTED:
            raise BusinessRuleViolationError(
                "a rejected trader cannot be approved without a fresh registration; "
                "document 06 permits governed resubmission, which is a separate command"
            )
        return {
            "approval_status": APPROVED,
            # Approval is what makes a business able to transact, so it moves the
            # operational axis too. Leaving it `inactive` would mean every
            # approval needed a second call nobody would remember to make.
            "operational_status": ACTIVE,
            "approved_at": now,
            "approved_by_admin_user_id": actor.actor_id,
        }

    if names is REJECT_TRADER:
        if trader.approval_status == APPROVED:
            raise BusinessRuleViolationError(
                "an approved trader is suspended or deactivated, not rejected; "
                "rejection is a decision about a pending application"
            )
        return {"approval_status": REJECTED, "operational_status": INACTIVE}

    if names is SUSPEND_TRADER:
        return {"operational_status": SUSPENDED}

    if names is REACTIVATE_TRADER:
        if trader.approval_status != APPROVED:
            raise BusinessRuleViolationError(
                "only an approved trader can be reactivated; reactivating an "
                "unapproved business would grant it capability approval never gave"
            )
        return {"operational_status": ACTIVE}

    raise ValueError(f"no transition defined for {names.audit_action!r}")  # pragma: no cover


def _json_safe(values: dict[str, Any]) -> dict[str, Any]:
    """The audit columns are JSONB, and `approved_at` is a datetime.

    The same dict feeds `compare_and_swap`, which needs real Python values, and
    the audit row, which is serialised. Converting a copy rather than the original
    keeps the write correct while making the record storable — and doing it here
    rather than at the writer means the writer stays a place that records what it
    is given rather than one that reinterprets it.

    ISO-8601 in UTC, per the approved money/time contract: a timestamp rendered
    any other way in an append-only table is one nobody can compare later.
    """

    rendered: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, datetime):
            rendered[key] = value.isoformat()
        elif isinstance(value, uuid.UUID):
            rendered[key] = str(value)
        else:
            rendered[key] = value
    return rendered


def _audit(
    session: Session,
    policy: RedactionPolicy,
    names: CommandNames,
    *,
    outcome: str,
    entity_id: uuid.UUID,
    record_version: int,
    reason: str | None,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
    previous_values: dict[str, Any] | None = None,
    new_values: dict[str, Any] | None = None,
) -> None:
    AuditWriter(session, policy).record(
        AuditEntry(
            action=names.audit_action,
            outcome=outcome,
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="trader",
            entity_id=entity_id,
            entity_record_version=record_version,
            previous_values=previous_values,
            new_values=new_values,
            reason=reason,
            occurred_at=now,
            metadata={"operation": names.audit_action},
        ),
        actor=actor,
        context=context,
    )


def _publish(
    session: Session,
    policy: RedactionPolicy,
    names: CommandNames,
    trader: Trader,
    context: AuditContext,
    version: int | None = None,
) -> None:
    if names.outbox_event_type is None:  # pragma: no cover - all five publish
        return
    OutboxWriter(session, policy).enqueue(
        OutboxMessage(
            aggregate_type="trader",
            aggregate_id=trader.id,
            aggregate_version=version if version is not None else trader.record_version,
            event_type=names.outbox_event_type,
            # No phone number and no name. A consumer that needs them can read the
            # aggregate; putting them on a queue widens where personal data lives
            # for no gain, and `12_Security_RBAC_Audit.md` treats the trader
            # directory as sensitive.
            payload={"trader_id": str(trader.id)},
            payload_version=PAYLOAD_VERSION,
            correlation_id=context.correlation_id,
            causation_id=context.causation_id,
        )
    )
