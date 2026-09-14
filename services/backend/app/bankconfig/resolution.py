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
from app.audit.registry import ACTIVATE_BANK_PROFILE_VERSION
from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.db.models.bank import BankMapping, BankProfile, BankProfileVersion
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.statements.expected_file import (
    EXPECTED_CONFIG_HASH,
    EXPECTED_NORMALIZATION_RULES,
    EXPECTED_STATEMENT_MAPPING,
    EXPECTED_STATEMENT_TEMPLATE_VERSION,
)

DRAFT: Final = "draft"
ACTIVE: Final = "active"
RETIRED: Final = "retired"

# `bank_statement.py` spells the same two values for its own guards. Restated here rather than
# imported from that module, because importing a *command* from a configuration resolver would
# invert the dependency — and
# `test_a_run_needs_no_mapping_id_and_uses_the_statements_own_version` is what keeps the two
# spellings honest, by using one to satisfy the other.
STATEMENT_MAPPING_TYPE: Final = "statement_import"
MAPPING_ACTIVE: Final = "active"


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
    _give_this_version_the_expected_statement_mapping(uow, version)
    uow.flush()

    AuditWriter(uow.session, policy).record(
        AuditEntry(
            action=ACTIVATE_BANK_PROFILE_VERSION.audit_action,
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


def _give_this_version_the_expected_statement_mapping(
    uow: SqlAlchemyUnitOfWork, version: BankProfileVersion
) -> None:
    """The statement mapping this platform expects, attached to the version now in force.

    **Why activation is where this happens.** A statement is parsed "with exact BankProfileVersion
    and BankMapping" (§8.2), and `bank_statement.py` refuses a mapping belonging to any other
    version. Activation is the moment a new version becomes the one statements will be filed
    against — so without this, the first ordinary use of the bank-configuration screen would leave
    the new version with no mapping, and every import filed against it would refuse. The operator's
    action would be "raise a transfer limit" and the consequence would be "statement import stops",
    with nothing connecting the two.

    **This is configuration written from code, and that is the owner's decision of 2026-09-13**, not
    an invention here: the mapping is a single fixed function, the file we expect *is* the input.
    The two commands that would let an operator supply a mapping are catalogued and never served, so
    there is no operator intent this could overwrite.

    **And it is written here rather than by a migration because ADR-007 is open.** Its safe default
    is synthetic fixtures only, and `TestNothingIsSeeded` enforces that against the revision files
    themselves. A row that appears when an admin activates a configuration is not a seed; a row that
    appears in a database nobody has touched is. The difference is the whole of ADR-007's concern.

    **Nothing is written if the version already has one.** No path reaches that today —
    `activate_version` refuses a version that is not a draft, and a draft has never been activated —
    so this is a precondition rather than a guard against a known failure, and it is recorded as one
    rather than justified with a scenario that does not exist. What it buys is that this function is
    safe to call twice, which is what would make it safe to give a second caller: without it,
    `UNIQUE(bank_profile_version_id, file_type, template_version)` turns the second call into a 500
    during an activation. The check is on the pair rather than on an id, so a row written by any
    other means is respected rather than duplicated.

    `created_by_admin_user_id` and `approved_by_admin_user_id` stay null deliberately. Naming the
    activating admin as the author would record that a person wrote and approved this mapping, and
    nobody did — it came from `expected_file.py`. The audit entry for the activation is what ties a
    human to this moment.
    """

    existing = uow.session.scalars(
        select(BankMapping).where(
            BankMapping.bank_profile_version_id == version.id,
            BankMapping.file_type == STATEMENT_MAPPING_TYPE,
        )
    ).first()
    if existing is not None:
        return

    uow.session.add(
        BankMapping(
            # No id: `uuid_primary_key()` generates one. An id derived from the version would be
            # machinery for agreeing with a second writer, and there is no second writer.
            bank_profile_version_id=version.id,
            file_type=STATEMENT_MAPPING_TYPE,
            template_version=EXPECTED_STATEMENT_TEMPLATE_VERSION,
            status=MAPPING_ACTIVE,
            mapping=EXPECTED_STATEMENT_MAPPING,
            normalization_rules=EXPECTED_NORMALIZATION_RULES,
            config_hash=EXPECTED_CONFIG_HASH,
        )
    )
