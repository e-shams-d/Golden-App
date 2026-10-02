"""Create bank configuration: profiles, immutable versions, mappings, source accounts.

**ADR-007 blocks the content, not the mechanism.** Its title is "Initial bank profiles,
verified templates, mappings, limits, and source accounts" and its safe default is
"synthetic fixtures only" — a sentence that presumes fixtures can be created, which
presumes a creation path. `15_Agent_Implementation_Plan.md:684` lists "test fixture bank
profiles" as an M4 deliverable alongside `:685` "configuration validation and audit", and
a milestone cannot validate configuration it has no way to create.

So the commands exist and the constraint is enforced as a refusal at the boundary:
**creating a bank profile is refused under `APP_ENV=production`**. The reason is specific
rather than procedural, and `app/db/models/bank.py` already states it — a seeded transfer
limit would silently drive real splitting decisions the first time a batch was built, and
a seeded cutoff time would decide which day a payment belongs to. Both look like
configuration and behave like policy.

**`config_hash` is canonical, and uses `unversioned_digest` rather than
`parameters_hash`.** Both hash the same canonical bytes; the second carries a `v1:` prefix
and is 67 characters, which does not fit the `CHAR(64)` document 04 specifies. That module
already anticipated these exact two columns and records the cost of the bare form: a
digest computed under a changed serialiser becomes indistinguishable from a current one,
so changing `canonical_bytes` requires a migration that recomputes them.

Canonical is the point. The `(bank_profile_id, config_hash)` unique catches an operator
recreating an identical configuration as a "new" version, and a digest defeated by key
ordering or whitespace would not — that unique is what keeps the audit link between a
batch and the configuration that produced it meaningful.

**Versions and mappings are immutable.** Neither carries `record_version`: a change is a
new row, not an edit, and the database enforces it with a column-level grant permitting
`UPDATE` of `status` alone. Nothing here widens that grant — activation is slice 9 and
touches only that one column.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import time
from typing import Any, Final

from app.audit import AuditActor, AuditContext, AuditEntry, AuditWriter
from app.audit.redaction import RedactionPolicy
from app.audit.registry import (
    CREATE_BANK_MAPPING_VERSION,
    CREATE_BANK_PROFILE_VERSION,
    CREATE_SOURCE_BANK_ACCOUNT,
)
from app.core.errors import BusinessRuleViolationError, NotFoundError
from app.core.hashing import unversioned_digest
from app.db.models.bank import MAPPING_TYPES as _MODEL_MAPPING_TYPES
from app.db.models.bank import BankAccount, BankMapping, BankProfile, BankProfileVersion
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.security.identifiers import InvalidIdentifier, normalize_iban

DRAFT: Final = "draft"
ACTIVE: Final = "active"
RETIRED: Final = "retired"
CONFIGURATION_STATUSES: Final = (DRAFT, ACTIVE, RETIRED)

# DOC-CONFLICT-047. `bank_mappings.file_type` is the **mapping type** — document 04's
# reading — and not the file format, which is document 08's. M2 implemented document 04's
# meaning: both mapping uniques include this column so an import mapping and an export
# mapping can coexist at `template_version` 1, which is only coherent under that reading.
#
# Imported from the model rather than restated, after a first attempt wrote document 08's
# identifiers (`payment_export`, `payment_result_import`) here while the repository's own
# fixtures used `outgoing_export` and `incoming_result` — enforcing the right meaning with
# the wrong vocabulary. One definition means the next reader cannot repeat that.
MAPPING_TYPES: Final = _MODEL_MAPPING_TYPES

ACCOUNT_ROLES: Final = ("outgoing_source", "incoming_destination", "both")


@dataclass(frozen=True)
class CreateBankProfile:
    code: str
    display_name: str
    version_number: int = 1
    default_transfer_limit_irr: int | None = None
    after_cutoff_transfer_limit_irr: int | None = None
    cutoff_time: time | None = None
    splitting_enabled: bool = False
    supports_description_field: bool = False
    required_fields: dict[str, Any] = field(default_factory=dict)
    rules: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CreateBankProfileVersion:
    profile_id: uuid.UUID
    default_transfer_limit_irr: int | None = None
    after_cutoff_transfer_limit_irr: int | None = None
    cutoff_time: time | None = None
    splitting_enabled: bool = False
    supports_description_field: bool = False
    required_fields: dict[str, Any] = field(default_factory=dict)
    rules: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CreateBankMapping:
    version_id: uuid.UUID
    file_type: str
    mapping: dict[str, Any]
    required_fields: dict[str, Any] = field(default_factory=dict)
    normalization_rules: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CreateSourceBankAccount:
    profile_id: uuid.UUID
    display_name: str
    account_role: str
    normalized_iban: str | None = None


def _version_configuration(
    *,
    default_transfer_limit_irr: int | None,
    after_cutoff_transfer_limit_irr: int | None,
    cutoff_time: time | None,
    splitting_enabled: bool,
    supports_description_field: bool,
    required_fields: dict[str, Any],
    rules: dict[str, Any],
) -> dict[str, Any]:
    """Everything the hash covers, in one place.

    Built here rather than at each call site so that a field added to a version and
    forgotten in the digest is one edit rather than two — the failure mode being two
    genuinely different configurations that hash the same and collide on the unique.

    `cutoff_time` belongs in the hash for the same reason as the limits: two versions
    differing only in when the second limit starts are two different configurations, and
    without it here they would collide on the unique constraint.
    """

    configuration = {
        "default_transfer_limit_irr": default_transfer_limit_irr,
        "after_cutoff_transfer_limit_irr": after_cutoff_transfer_limit_irr,
        "cutoff_time": cutoff_time,
        "splitting_enabled": splitting_enabled,
        "supports_description_field": supports_description_field,
        "required_fields": required_fields,
        "rules": rules,
    }

    # A configuration field written inside `rules` is refused rather than stored.
    #
    # `rules` is free-form JSONB, so `{"cutoff_time": "16:00"}` was accepted, hashed,
    # persisted and had no effect whatever — the column stayed null and the second
    # transfer limit went on never starting. An operator who gets `201` has every reason
    # to believe the cutoff is set. **Refusing is better than accepting with no effect**,
    # which is the whole of F-14's worse half.
    #
    # The names come from the configuration itself rather than a list beside it: a field
    # added above is covered here the moment it exists, and there is no second copy to
    # drift. `rules` is in that set too, so `rules={"rules": …}` is refused as well.
    misplaced = sorted(set(rules) & set(configuration))
    if misplaced:
        raise BusinessRuleViolationError(
            f"{', '.join(misplaced)} belongs at the top level of the request, not inside "
            "`rules`. Stored there it is kept and ignored: the column stays empty while "
            "the response says 201."
        )

    return configuration


def _digest_input(configuration: dict[str, Any]) -> dict[str, Any]:
    """The configuration in a form `canonical()` will accept.

    `canonical()` refuses a `datetime.time` outright rather than calling `str()` on it,
    so that the config hash cannot come to depend on a formatting choice nobody made
    deliberately. `isoformat()` is that deliberate choice: `"16:00:00"`, the same text the
    read model returns, so the hashed form and the published form agree.

    Rendered here rather than stored as text, because the column is `TIME` and a string
    in the mapping would reach `BankProfileVersion(**configuration)` as one.
    """

    return {
        key: value.isoformat() if isinstance(value, time) else value
        for key, value in configuration.items()
    }


def _refuse_in_production(app_env: str) -> None:
    if app_env == "production":
        raise BusinessRuleViolationError(
            "Bank configuration cannot be created in production while ADR-007 is open. "
            "Its safe default is synthetic fixtures only: a transfer limit created here "
            "would drive real splitting decisions the first time a batch was built, and "
            "a cutoff time would decide which day a payment belongs to."
        )


def create_profile(
    command: CreateBankProfile,
    *,
    uow: SqlAlchemyUnitOfWork,
    actor: AuditActor,
    context: AuditContext,
    policy: RedactionPolicy,
    app_env: str,
) -> tuple[uuid.UUID, uuid.UUID]:
    """A profile and its first version, in one transaction.

    Both together, which the composite deferrable foreign key is what makes possible: a
    two-step write would leave a window where a reader sees a bank with no configuration
    at all.
    """

    _refuse_in_production(app_env)

    code = command.code.strip().lower()
    if not code:
        raise BusinessRuleViolationError("A bank profile code cannot be blank.")

    configuration = _version_configuration(
        default_transfer_limit_irr=command.default_transfer_limit_irr,
        after_cutoff_transfer_limit_irr=command.after_cutoff_transfer_limit_irr,
        cutoff_time=command.cutoff_time,
        splitting_enabled=command.splitting_enabled,
        supports_description_field=command.supports_description_field,
        required_fields=command.required_fields,
        rules=command.rules,
    )

    profile = BankProfile(code=code, name=command.display_name, status=ACTIVE)
    uow.session.add(profile)
    uow.flush()

    version = BankProfileVersion(
        bank_profile_id=profile.id,
        version_number=command.version_number,
        status=DRAFT,
        config_hash=unversioned_digest(_digest_input(configuration)),
        created_by_admin_user_id=actor.actor_id,
        **configuration,
    )
    uow.session.add(version)
    uow.flush()

    AuditWriter(uow.session, policy).record(
        AuditEntry(
            action=CREATE_BANK_PROFILE_VERSION.audit_action,
            outcome="success",
            metadata_schema="audit.bank_profile.created",
            metadata_version=1,
            entity_type="bank_profile",
            entity_id=profile.id,
            previous_values=None,
            new_values={"code": code, "version_number": command.version_number},
            metadata={"operation": "bank_profile.create"},
        ),
        actor=actor,
        context=context,
    )
    return profile.id, version.id


def create_version(
    command: CreateBankProfileVersion,
    *,
    uow: SqlAlchemyUnitOfWork,
    actor: AuditActor,
    context: AuditContext,
    policy: RedactionPolicy,
    app_env: str,
) -> uuid.UUID:
    """A new immutable version. The version number follows the profile's highest."""

    _refuse_in_production(app_env)

    profile = uow.session.get(BankProfile, command.profile_id)
    if profile is None:
        raise NotFoundError()

    existing = [
        version
        for version in uow.session.query(BankProfileVersion)
        .filter(BankProfileVersion.bank_profile_id == profile.id)
        .all()
    ]
    next_number = max((version.version_number for version in existing), default=0) + 1

    configuration = _version_configuration(
        default_transfer_limit_irr=command.default_transfer_limit_irr,
        after_cutoff_transfer_limit_irr=command.after_cutoff_transfer_limit_irr,
        cutoff_time=command.cutoff_time,
        splitting_enabled=command.splitting_enabled,
        supports_description_field=command.supports_description_field,
        required_fields=command.required_fields,
        rules=command.rules,
    )

    version = BankProfileVersion(
        bank_profile_id=profile.id,
        version_number=next_number,
        status=DRAFT,
        config_hash=unversioned_digest(_digest_input(configuration)),
        created_by_admin_user_id=actor.actor_id,
        **configuration,
    )
    uow.session.add(version)
    uow.flush()

    AuditWriter(uow.session, policy).record(
        AuditEntry(
            action=CREATE_BANK_PROFILE_VERSION.audit_action,
            outcome="success",
            metadata_schema="audit.bank_profile.version_created",
            metadata_version=1,
            entity_type="bank_profile_version",
            entity_id=version.id,
            previous_values=None,
            new_values={"version_number": next_number},
            metadata={"operation": "bank_profile.create_version"},
        ),
        actor=actor,
        context=context,
    )
    return version.id


def create_mapping(
    command: CreateBankMapping,
    *,
    uow: SqlAlchemyUnitOfWork,
    actor: AuditActor,
    context: AuditContext,
    policy: RedactionPolicy,
    app_env: str,
) -> uuid.UUID:
    """A mapping for one version, typed by DOC-CONFLICT-047's reading of `file_type`."""

    _refuse_in_production(app_env)

    if command.file_type not in MAPPING_TYPES:
        raise BusinessRuleViolationError(
            f"{command.file_type!r} is not a mapping type. The three are "
            f"{', '.join(MAPPING_TYPES)}. This column is the mapping type, not the file "
            "format — see DOC-CONFLICT-047."
        )

    version = uow.session.get(BankProfileVersion, command.version_id)
    if version is None:
        raise NotFoundError()

    siblings = (
        uow.session.query(BankMapping)
        .filter(
            BankMapping.bank_profile_version_id == version.id,
            BankMapping.file_type == command.file_type,
        )
        .all()
    )
    next_template = max((row.template_version for row in siblings), default=0) + 1

    configuration = {
        "mapping": command.mapping,
        "required_fields": command.required_fields,
        "normalization_rules": command.normalization_rules,
    }

    mapping = BankMapping(
        bank_profile_version_id=version.id,
        file_type=command.file_type,
        template_version=next_template,
        status=DRAFT,
        mapping=command.mapping,
        required_fields=command.required_fields,
        normalization_rules=command.normalization_rules,
        config_hash=unversioned_digest(configuration),
        created_by_admin_user_id=actor.actor_id,
    )
    uow.session.add(mapping)
    uow.flush()

    AuditWriter(uow.session, policy).record(
        AuditEntry(
            action=CREATE_BANK_MAPPING_VERSION.audit_action,
            outcome="success",
            metadata_schema="audit.bank_mapping.created",
            metadata_version=1,
            entity_type="bank_mapping",
            entity_id=mapping.id,
            previous_values=None,
            new_values={"file_type": command.file_type, "template_version": next_template},
            metadata={"operation": "bank_mapping.create_version"},
        ),
        actor=actor,
        context=context,
    )
    return mapping.id


def create_source_account(
    command: CreateSourceBankAccount,
    *,
    uow: SqlAlchemyUnitOfWork,
    actor: AuditActor,
    context: AuditContext,
    policy: RedactionPolicy,
    app_env: str,
) -> uuid.UUID:
    """A centre-owned account. The IBAN may be absent — see `app/db/models/bank.py`."""

    _refuse_in_production(app_env)

    if command.account_role not in ACCOUNT_ROLES:
        raise BusinessRuleViolationError(
            f"{command.account_role!r} is not an account role. The three are "
            f"{', '.join(ACCOUNT_ROLES)}."
        )

    profile = uow.session.get(BankProfile, command.profile_id)
    if profile is None:
        raise NotFoundError()

    # The field is called `normalized_iban` and until now nothing normalised it. The same
    # `normalize_iban` the beneficiary path uses, for the same three reasons: an operator
    # typing in a Persian interface produces Persian digits, a bank prints IBANs in groups
    # of four, and the check digits are the only thing that can tell a mistyped account
    # number from the intended one. The column's CHECK sees shape alone, so an ordinary
    # Persian-digit entry reached it as a constraint violation rather than an answer.
    #
    # This is the account money leaves from. A beneficiary's IBAN costs one payment; this
    # one is on every outgoing file the bank executes.
    normalized_iban = (
        None if command.normalized_iban is None else _normalized_iban(command.normalized_iban)
    )

    account = BankAccount(
        bank_profile_id=profile.id,
        display_name=command.display_name,
        account_role=command.account_role,
        normalized_iban=normalized_iban,
        status=ACTIVE,
    )
    uow.session.add(account)
    uow.flush()

    AuditWriter(uow.session, policy).record(
        AuditEntry(
            action=CREATE_SOURCE_BANK_ACCOUNT.audit_action,
            outcome="success",
            metadata_schema="audit.source_bank_account.created",
            metadata_version=1,
            entity_type="bank_account",
            entity_id=account.id,
            previous_values=None,
            # The IBAN is not written into the audit row. `RedactionPolicy` masks it
            # where it appears, and the safest handling of a value POL-003 has not
            # settled is not to put it in the longest-retained table in the system.
            new_values={"display_name": command.display_name, "role": command.account_role},
            metadata={"operation": "source_bank_account.create"},
        ),
        actor=actor,
        context=context,
    )
    return account.id


def _normalized_iban(value: str) -> str:
    """`InvalidIdentifier` turned into the refusal a person reads.

    The same two lines as `app/commands/beneficiary.py`. Not shared: the duplication is
    four lines and importing one command module from another to save them would couple
    two command surfaces that have no other reason to know about each other.
    """

    try:
        return normalize_iban(value)
    except InvalidIdentifier as error:
        raise BusinessRuleViolationError(str(error)) from error
