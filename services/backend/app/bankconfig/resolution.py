"""Which configuration was in force at a given instant, and activating a new one.

`15_Agent_Implementation_Plan.md:683` asks for effective-date and version handling;
`08_Bank_File_and_Result_Processing.md:342-350` gives the activation and immutability
rules. Both come down to one question a later milestone will ask constantly: *which rules
applied when this batch was built?*

**The window is `[effective_from, effective_to)`** — inclusive at the start, exclusive at
the end. The alternative closes both ends, and then an instant exactly on a boundary
belongs to two versions or to none. Both are wrong for a cutoff time, which is precisely
an instant on a boundary. UTC throughout, per ADR-006; `cutoff_time` is interpreted in
`Asia/Tehran` by the same approved decision, and that interpretation belongs to whatever
consumes the cutoff rather than here.

**Two active versions with overlapping windows cannot both exist for one profile.** The
database cannot express that with a unique, so activation refuses it — and a refusal at
one command is only as good as the number of writers, which is why activation is the only
path that sets `active`.

**Activation writes `status` and nothing else.** M2's column-level grant permits exactly
that on this table, and this command is written to stay inside it: repointing
`bank_profiles.current_version_id` is a write to a different table, which is why it is
possible at all.

**Who activated a version is answered by `audit_logs`, not by a column here.** Document 08
lists `activated_by` and `activated_at` fields; document 04's column set has neither, and
adding them would mean widening an immutable snapshot's UPDATE grant from one column to
three to store a fact the audit log already records under DOC-CONFLICT-040's approved
resolution. That trade is recorded in DOC-CONFLICT-047 and refused.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from sqlalchemy import select

from app.audit import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.audit.redaction import RedactionPolicy
from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.db.models.bank import BankProfile, BankProfileVersion
from app.db.unit_of_work import SqlAlchemyUnitOfWork

DRAFT: Final = "draft"
ACTIVE: Final = "active"
RETIRED: Final = "retired"


@dataclass(frozen=True)
class ResolvedVersion:
    """A version id and the rules it carries, never one without the other.

    The id is first and required. A caller that logs or stores the configuration it used
    stores the id alongside it, so "which rules applied" stays answerable after the rules
    have been superseded — which they will be.
    """

    version_id: uuid.UUID
    version_number: int
    default_transfer_limit_irr: int | None
    after_cutoff_transfer_limit_irr: int | None
    splitting_enabled: bool
    supports_description_field: bool
    required_fields: dict[str, Any]
    rules: dict[str, Any]


def _covers(version: BankProfileVersion, at: datetime) -> bool:
    """`[effective_from, effective_to)`, with an open end treated as unbounded.

    A null `effective_from` means "since always" and a null `effective_to` means "until
    superseded". Both are legitimate for a first version nobody has dated.
    """

    if version.effective_from is not None and at < version.effective_from:
        return False
    return not (version.effective_to is not None and at >= version.effective_to)


def resolve_active_version(
    profile_id: uuid.UUID, at: datetime, *, uow: SqlAlchemyUnitOfWork
) -> ResolvedVersion:
    """The configuration in force for this profile at this instant.

    Raises rather than returning `None` when nothing is in force. A caller that received
    `None` would have to decide what to do with a bank whose rules are unknown, and the
    only safe answer is to stop — so stopping is what this does, once, here.
    """

    versions = (
        uow.session.execute(
            select(BankProfileVersion)
            .where(
                BankProfileVersion.bank_profile_id == profile_id,
                BankProfileVersion.status == ACTIVE,
            )
            .order_by(BankProfileVersion.version_number.desc())
        )
        .scalars()
        .all()
    )

    covering = [version for version in versions if _covers(version, at)]
    if not covering:
        raise NotFoundError()
    if len(covering) > 1:
        # Activation refuses to create this, so reaching it means something wrote around
        # the command. Refusing loudly is the only safe answer: silently taking the
        # highest version number would make a batch's configuration depend on which row
        # sorted first.
        raise BusinessRuleViolationError(
            f"{len(covering)} active versions cover {at.isoformat()} for this bank "
            "profile. Configuration in force must be unambiguous."
        )

    version = covering[0]
    return ResolvedVersion(
        version_id=version.id,
        version_number=version.version_number,
        default_transfer_limit_irr=version.default_transfer_limit_irr,
        after_cutoff_transfer_limit_irr=version.after_cutoff_transfer_limit_irr,
        splitting_enabled=version.splitting_enabled,
        supports_description_field=version.supports_description_field,
        required_fields=dict(version.required_fields),
        rules=dict(version.rules),
    )


def _overlaps(left: BankProfileVersion, right: BankProfileVersion) -> bool:
    """Two half-open windows overlap unless one ends before the other begins."""

    if (
        left.effective_to is not None
        and right.effective_from is not None
        and left.effective_to <= right.effective_from
    ):
        return False
    return not (
        right.effective_to is not None
        and left.effective_from is not None
        and right.effective_to <= left.effective_from
    )


def activate_version(
    version_id: uuid.UUID,
    *,
    uow: SqlAlchemyUnitOfWork,
    actor: AuditActor,
    context: AuditContext,
    policy: RedactionPolicy,
) -> None:
    """Move a draft to active, retire what it replaces, and repoint the profile.

    One transaction. A profile whose pointer and whose version statuses disagreed would be
    a bank with two answers to "what are the current rules", and the window in which that
    was true would be exactly the window in which a batch might be built.
    """

    version = uow.session.get(BankProfileVersion, version_id)
    if version is None:
        raise NotFoundError()
    if version.status != DRAFT:
        raise BusinessRuleViolationError(
            f"Only a draft version can be activated; this one is {version.status!r}. A "
            "change to an active version is a new version, not an edit."
        )

    profile = uow.session.get(BankProfile, version.bank_profile_id)
    if profile is None:  # pragma: no cover - the foreign key makes this unreachable
        raise NotFoundError()

    currently_active = (
        uow.session.execute(
            select(BankProfileVersion).where(
                BankProfileVersion.bank_profile_id == profile.id,
                BankProfileVersion.status == ACTIVE,
            )
        )
        .scalars()
        .all()
    )

    clashing = [other for other in currently_active if _overlaps(other, version)]
    if clashing:
        raise BusinessRuleViolationError(
            "This version's effective window overlaps an already active version. Retire "
            "or re-date the existing one first: two sets of rules in force at one instant "
            "is a bank with two answers."
        )

    previous = [other.id for other in currently_active]
    for other in currently_active:
        other.status = RETIRED

    version.status = ACTIVE
    profile.current_version_id = version.id
    uow.flush()

    AuditWriter(uow.session, policy).record(
        AuditEntry(
            action="bank_profile.version_activated",
            outcome="success",
            metadata_schema="audit.bank_profile.version_activated",
            metadata_version=1,
            entity_type="bank_profile_version",
            entity_id=version.id,
            previous_values={"status": DRAFT, "retired": [str(one) for one in previous]},
            new_values={"status": ACTIVE, "version_number": version.version_number},
            metadata={"operation": "bank_profile.activate_version"},
        ),
        actor=actor,
        context=context,
    )
