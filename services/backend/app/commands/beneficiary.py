"""A trader's address book: create, correct, retire — and warn without refusing.

Three commands, one transaction each, none of them committing. The route owns the
boundary, as every command in this codebase does.

**The duplicate warning is the point of this slice.** `15_Agent_Implementation_Plan.md:801`
says the warning "does not auto-block unless an approved policy says so", document
04 says "the service produces duplicate warnings; it does not auto-merge", and
document 06 says the same a third time. So creating a beneficiary whose IBAN
already exists in the trader's own set **succeeds**, and the response names what it
matched.

That is the opposite of the reflex. A duplicate IBAN looks like an error, and the
natural implementation refuses it — which is why three documents say not to.
Duplicates are legitimate: a goldsmith may hold two accounts at one bank, two
people may share a name, and a half-entered record is corrected by entering the
right one rather than by being blocked. `SVC-BEN-001` is the test that keeps the
reflex out.

**Nothing here deletes.** Retiring a beneficiary sets `inactive`; the row stays and
every request that already references it keeps resolving. That is not politeness
toward old data — a payment request's revision snapshots the beneficiary at
submission, and the row is what a dispute six months later is read against.

**The trader scope comes from the actor, never from the body.** A create request
may carry `trader_id` when an internal actor is acting for a trader
(`05_API_Specification.md:947`), and for a trader actor that field is not read at
all. Taking it from the body for a trader would be an IDOR with a form field.

Covers: SVC-BEN-001, SVC-BEN-002, SEC-BEN-001, AUD-BEN-001.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import (
    CREATE_BENEFICIARY,
    DEACTIVATE_BENEFICIARY,
    UPDATE_BENEFICIARY,
    CommandNames,
)
from app.audit.writer import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.db.concurrency import compare_and_swap
from app.db.models.beneficiary import Beneficiary
from app.security.actor import ActorContext
from app.security.identifiers import (
    InvalidIdentifier,
    normalize_iban,
    normalize_person_name,
)
from app.security.ownership import scoped

METADATA_SCHEMA = "audit.beneficiary.lifecycle"
METADATA_VERSION = 1

ACTIVE = "active"
INACTIVE = "inactive"
NOT_CHECKED = "not_checked"


@dataclass(frozen=True, slots=True)
class CreateBeneficiary:
    trader_id: uuid.UUID
    full_name: str
    iban: str
    national_id: str | None = None
    phone_number: str | None = None
    notes_internal: str | None = None


@dataclass(frozen=True, slots=True)
class UpdateBeneficiary:
    beneficiary_id: uuid.UUID
    expected_record_version: int
    full_name: str | None = None
    iban: str | None = None
    national_id: str | None = None
    phone_number: str | None = None


@dataclass(frozen=True, slots=True)
class DeactivateBeneficiary:
    beneficiary_id: uuid.UUID
    expected_record_version: int
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class DuplicateWarning:
    """One existing beneficiary that resembles the one just created.

    Carries the id and what matched, so a screen can say "you already have this
    IBAN under a different name" and link to it. It is advice, not an outcome:
    the beneficiary in `BeneficiaryResult.beneficiary` was created.
    """

    beneficiary_id: uuid.UUID
    matched_on: str
    full_name: str


@dataclass(frozen=True, slots=True)
class BeneficiaryResult:
    beneficiary: Beneficiary
    warnings: tuple[DuplicateWarning, ...] = ()


def create_beneficiary(
    command: CreateBeneficiary,
    *,
    acting: ActorContext,
    session: Session,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> BeneficiaryResult:
    """Create the beneficiary, and report what it resembles.

    The order matters: duplicates are looked up **before** the insert, so the
    warning describes rows that existed beforehand rather than the row just
    written.
    """

    normalized_iban = _normalized_iban(command.iban)
    full_name = command.full_name.strip()
    if not full_name:
        raise BusinessRuleViolationError("a beneficiary needs a name")

    normalized_name = normalize_person_name(full_name)
    warnings = _duplicates(
        session,
        acting=acting,
        trader_id=command.trader_id,
        normalized_iban=normalized_iban,
        normalized_name=normalized_name,
    )

    beneficiary = Beneficiary(
        trader_id=command.trader_id,
        full_name=full_name,
        normalized_name=normalized_name or None,
        iban=command.iban.strip(),
        normalized_iban=normalized_iban,
        national_id=_clean(command.national_id),
        phone_number=_clean(command.phone_number),
        notes_internal=_clean(command.notes_internal),
        status=ACTIVE,
        verification_status=NOT_CHECKED,
        verification_metadata={},
    )
    session.add(beneficiary)
    session.flush()

    _audit(
        session,
        policy,
        CREATE_BENEFICIARY,
        outcome="success",
        beneficiary=beneficiary,
        record_version=beneficiary.record_version,
        reason=None,
        actor=actor,
        context=context,
        now=now,
        new_values={"status": ACTIVE, "verification_status": NOT_CHECKED},
        # The warning is recorded rather than only returned. A trader who created
        # a duplicate on purpose and one who did it by accident look identical
        # afterwards, and the audit row is where "they were told" is written down.
        extra_metadata={"duplicate_warnings": [str(w.beneficiary_id) for w in warnings]},
    )

    return BeneficiaryResult(beneficiary=beneficiary, warnings=warnings)


def update_beneficiary(
    command: UpdateBeneficiary,
    *,
    session: Session,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> BeneficiaryResult:
    """Correct a beneficiary's details, under optimistic concurrency.

    Editing here changes nothing that was already submitted. A payment request's
    revision holds its own snapshot of the name and IBAN, taken when it was
    submitted, and `SVC-SUB-002` in slice 6 is the test that proves this command
    cannot reach it.
    """

    beneficiary = _load(session, command.beneficiary_id)

    if beneficiary.status != ACTIVE:
        raise BusinessRuleViolationError(
            f"a {beneficiary.status} beneficiary is not edited; document 06 replaces "
            "an identity record rather than correcting a retired one"
        )

    values: dict[str, Any] = {}
    if command.full_name is not None:
        full_name = command.full_name.strip()
        if not full_name:
            raise BusinessRuleViolationError("a beneficiary needs a name")
        values["full_name"] = full_name
        values["normalized_name"] = normalize_person_name(full_name) or None
    if command.iban is not None:
        values["iban"] = command.iban.strip()
        values["normalized_iban"] = _normalized_iban(command.iban)
    if command.national_id is not None:
        values["national_id"] = _clean(command.national_id)
    if command.phone_number is not None:
        values["phone_number"] = _clean(command.phone_number)

    if not values:
        raise BusinessRuleViolationError("no field to update")

    previous = {key: getattr(beneficiary, key) for key in values}

    outcome = compare_and_swap(
        session,
        Beneficiary,
        entity_id=command.beneficiary_id,
        expected_version=command.expected_record_version,
        values=values,
    )
    session.expire(beneficiary)

    _audit(
        session,
        policy,
        UPDATE_BENEFICIARY,
        outcome="success",
        beneficiary=beneficiary,
        record_version=outcome.new_version,
        reason=None,
        actor=actor,
        context=context,
        now=now,
        previous_values=previous,
        new_values=values,
    )

    return BeneficiaryResult(beneficiary=beneficiary)


def deactivate_beneficiary(
    command: DeactivateBeneficiary,
    *,
    session: Session,
    policy: RedactionPolicy,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
) -> BeneficiaryResult:
    """Retire a beneficiary. The row stays; only its status moves.

    `active -> inactive`, per document 06's transition table. Nothing deletes, and
    nothing here touches a request that already references this row.
    """

    beneficiary = _load(session, command.beneficiary_id)

    if beneficiary.status != ACTIVE:
        raise BusinessRuleViolationError(
            f"only an active beneficiary is deactivated; this one is {beneficiary.status}"
        )

    outcome = compare_and_swap(
        session,
        Beneficiary,
        entity_id=command.beneficiary_id,
        expected_version=command.expected_record_version,
        values={"status": INACTIVE},
    )
    session.expire(beneficiary)

    _audit(
        session,
        policy,
        DEACTIVATE_BENEFICIARY,
        outcome="success",
        beneficiary=beneficiary,
        record_version=outcome.new_version,
        reason=command.reason,
        actor=actor,
        context=context,
        now=now,
        previous_values={"status": ACTIVE},
        new_values={"status": INACTIVE},
    )

    return BeneficiaryResult(beneficiary=beneficiary)


def _duplicates(
    session: Session,
    *,
    acting: ActorContext,
    trader_id: uuid.UUID,
    normalized_iban: str,
    normalized_name: str,
) -> tuple[DuplicateWarning, ...]:
    """What the trader already has that resembles this.

    Scoped to one trader, always, and scoped **twice** on the trader path. An
    unscoped lookup would answer "somebody else already has this IBAN", which tells
    one trader something about another — DOC-CONFLICT-011's isolation defeated by
    a warning message rather than by a missing guard.

    `trader_id` is the owner of the row being created. For a trader acting for
    itself that is the session's own id, and `scoped()` adds the same condition a
    second time from `ActorContext` — where no caller-supplied value can reach it.
    The two are equal today; if a later edit made them differ the query returns
    nothing rather than another trader's rows, which is the direction a scoping bug
    should fail in.

    Retired rows count. A trader who deactivated a beneficiary and is re-entering
    it wants to know the old one is there, and hiding it would produce the second
    copy this warning exists to prevent.
    """

    resembles = [Beneficiary.normalized_iban == normalized_iban]
    if normalized_name:
        # Only when there is one. `normalized_name` is nullable, and a bare
        # equality against an empty string would match every row whose name folded
        # to nothing — turning "no name to compare" into "matches everything".
        resembles.append(Beneficiary.normalized_name == normalized_name)

    query = (
        select(Beneficiary)
        .where(Beneficiary.trader_id == trader_id)
        .where(or_(*resembles))
        .order_by(Beneficiary.created_at)
    )
    if acting.is_trader:
        query = scoped(query, Beneficiary.trader_id, acting)

    matches = session.scalars(query).all()

    return tuple(
        DuplicateWarning(
            beneficiary_id=match.id,
            matched_on="iban" if match.normalized_iban == normalized_iban else "name",
            full_name=match.full_name,
        )
        for match in matches
    )


def _load(session: Session, beneficiary_id: uuid.UUID) -> Beneficiary:
    beneficiary = session.get(Beneficiary, beneficiary_id)
    if beneficiary is None:
        raise NotFoundError()
    return beneficiary


def _normalized_iban(value: str) -> str:
    try:
        return normalize_iban(value)
    except InvalidIdentifier as error:
        raise BusinessRuleViolationError(str(error)) from error


def _clean(value: str | None) -> str | None:
    """An empty field and an absent one are the same fact, stored one way."""

    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _audit(
    session: Session,
    policy: RedactionPolicy,
    names: CommandNames,
    *,
    outcome: str,
    beneficiary: Beneficiary,
    record_version: int,
    reason: str | None,
    actor: AuditActor,
    context: AuditContext,
    now: datetime,
    previous_values: dict[str, Any] | None = None,
    new_values: dict[str, Any] | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> None:
    AuditWriter(session, policy).record(
        AuditEntry(
            action=names.audit_action,
            outcome=outcome,
            metadata_schema=METADATA_SCHEMA,
            metadata_version=METADATA_VERSION,
            entity_type="beneficiary",
            entity_id=beneficiary.id,
            entity_record_version=record_version,
            previous_values=previous_values,
            new_values=new_values,
            reason=reason,
            occurred_at=now,
            metadata={"operation": names.audit_action, **(extra_metadata or {})},
        ),
        actor=actor,
        context=context,
    )
