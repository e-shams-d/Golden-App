"""Bank profiles, their immutable versions, centre accounts, and file mappings.

**Nothing here is seeded, in any value.** ADR-007's safe default is synthetic
fixtures only, and the reason is specific rather than procedural: a seeded transfer
limit would silently drive real splitting decisions the first time a batch was
built, and a seeded cutoff time would decide which day a payment belongs to. Both
would look like configuration and behave like policy. `tests/integration/` asserts
the migration inserts nothing at all.

**`bank_profiles.current_version_id` is a composite deferrable foreign key**, using
the pattern slice 3 proved before anything needed it:
`(current_version_id, id) REFERENCES bank_profile_versions (id, bank_profile_id)`.

Two things about that are worth stating because both are easy to get wrong:

The invariant worth having is not "current_version_id is some version" but "is a
version **of this profile**". The single-column form validates, creates cleanly, and
enforces the weaker rule — so a profile could point at another bank's configuration
and the database would agree. The column order matters too: reversed, it still works
and still means something else.

`DEFERRABLE INITIALLY DEFERRED` is what makes a profile and its first version
insertable in one transaction. Without it the pair is impossible — whichever row
goes first violates something — and the workaround is a two-step write with a window
where the pointer is null, which is a window where a reader sees a bank with no
configuration.

**`bank_profile_versions` and `bank_mappings` are immutable snapshots.** Neither
carries `record_version`: a change is a new row, not an edit. The database enforces
that with a **column-level** grant — the runtime may UPDATE `status` and nothing
else — because "immutable except for a controlled status transition" is not
expressible as a table-level privilege, and a comment saying so does not stop an
UPDATE.

**The two uniques on each are scoped differently, and the scope is the whole point.**
On a version: `(bank_profile_id, version_number)` orders versions per bank, and
`(bank_profile_id, config_hash)` stops an operator recreating an identical
configuration as a "new" version, which would break the audit link between a batch
and the configuration that produced it. On a mapping both uniques include
`file_type`, so an import mapping and an export mapping can both exist at
`template_version` 1 — a globally scoped unique would make that impossible and the
failure would arrive during the first export.

**The IBAN asymmetry across tables is a recorded decision, not an oversight.**
`bank_accounts.normalized_iban` is nullable with a **null-tolerant** regex, because
a centre account may be registered before its IBAN is known and copying the
beneficiaries' NOT NULL form here would refuse legitimate rows. Beneficiaries (M5)
will be NOT NULL with the same regex, because a payment destination without an IBAN
cannot be paid. `trader_bank_accounts` specifies neither and must not be harmonised
by assumption.

**No unique beneficiary-per-IBAN or per-name constraint may ever be added.**
Duplicates are legitimate — the same person may hold two accounts, and two people
may share a name — and the approved behaviour is to warn, never to auto-merge. A
unique index would turn a warning into a refusal at data entry.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, named_check, updated_at_column, uuid_primary_key

# An account is a source for outgoing payments, a destination for incoming ones,
# or both. Enumerated because the three values come from the centre's own
# operating model rather than from a bank document, and because a wrong value here
# would let an outgoing batch draw on an incoming-only account.
ACCOUNT_ROLES: tuple[str, ...] = ("outgoing_source", "incoming_destination", "both")

# DOC-CONFLICT-047: `bank_mappings.file_type` is the mapping type, per document 04's
# prose — "Statement import, outgoing export, result import". These are the identifiers
# this repository already uses; document 04 supplies no identifiers of its own, which is
# why they are an application-level allowlist and not a CHECK. See the note on
# `BankMapping.__table_args__`.
MAPPING_TYPES: tuple[str, ...] = (
    "statement_import",
    "outgoing_export",
    "incoming_result",
)

# Iranian IBAN: `IR` then 24 digits. Applied null-tolerantly on `bank_accounts`.
IBAN_PATTERN = "^IR[0-9]{24}$"

# The two CHAR(64) digest columns share one shape, so they share one expression:
# a second copy is a second place for the length to drift.
HEX_64_CHECK = "{column} ~ '^[0-9a-f]{{64}}$'"


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class BankProfile(Base):
    __tablename__ = "bank_profiles"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)

    # No value CHECK. `status_catalog.yaml` records `bank_profile` without a
    # canonical set, and enumerating one here would decide it from a migration.
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    # Points at the version currently in operational use. Nullable because a
    # profile may legitimately exist with no active version yet; the composite
    # deferrable foreign key below is what keeps it pointing inside this profile.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True
    )

    record_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("1")
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        # Composite, ordered, and deferred. See the module docstring: the
        # single-column form enforces a weaker invariant, and the reversed column
        # order enforces a different one.
        ForeignKeyConstraint(
            ["current_version_id", "id"],
            ["bank_profile_versions.id", "bank_profile_versions.bank_profile_id"],
            name="fk_bank_profiles_current_version_within_profile",
            deferrable=True,
            initially="DEFERRED",
        ),
        named_check("code = lower(code)", name="code_is_lowercase"),
        named_check("length(btrim(code)) > 0", name="code_not_blank"),
        named_check("length(btrim(name)) > 0", name="name_not_blank"),
    )


class BankProfileVersion(Base):
    """An immutable operational configuration snapshot for one bank.

    Superseded by inserting a new row, never edited — which is why there is no
    `record_version` here and why the runtime's UPDATE grant covers `status` alone.
    """

    __tablename__ = "bank_profile_versions"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    bank_profile_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("bank_profiles.id"), nullable=False
    )
    # Monotonic per bank, enforced by the unique below rather than by a sequence:
    # a global sequence would number bank B's first version 7 because bank A had
    # six, and an operator reading "version 7" would look for six predecessors.
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # No value CHECK: `status_catalog.yaml:633-645` records `bank_profile_version`
    # with `canonical: null`, so `draft/active/retired` is not written here. The
    # column ships application-enforced with the conflict recorded, and the CHECK
    # arrives by expand/contract at M4.
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Null-tolerant positive checks. Null means "this bank publishes no limit",
    # which is different from zero — zero would mean every transfer must be split
    # into nothing, and a NOT NULL column would force somebody to invent a number.
    default_transfer_limit_irr: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    after_cutoff_transfer_limit_irr: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # TIME, not TIMESTAMPTZ. A cutoff is a wall-clock rule — "16:00 at the bank" —
    # evaluated in the configured business timezone under ADR-006. Storing it as an
    # instant would bind it to one date and shift it twice a year in any zone with
    # daylight saving. Bank cutoff *date* conventions and the holiday calendar are
    # still Open and are deliberately not encoded anywhere here.
    cutoff_time: Mapped[time | None] = mapped_column(Time(timezone=False), nullable=True)

    splitting_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    supports_description_field: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    required_fields: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    rules: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    # `CHAR(64)`, so the bare digest from `app.core.hashing.unversioned_digest`.
    # That function's docstring records what the missing version prefix costs.
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=True
    )
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint(
            "bank_profile_id", "version_number", name="uq_bank_profile_versions_number"
        ),
        # Stops an operator recreating an identical configuration as a "new"
        # version. Without it the audit link between a batch and the configuration
        # that produced it can be broken by a round trip through the admin screen.
        UniqueConstraint(
            "bank_profile_id", "config_hash", name="uq_bank_profile_versions_config_hash"
        ),
        # Required by the composite foreign key on `bank_profiles`. Looks redundant
        # because `id` is already the primary key; PostgreSQL needs a unique over
        # exactly the referenced column list, so removing it as duplicative breaks
        # the pointer constraint.
        UniqueConstraint("id", "bank_profile_id", name="uq_bank_profile_versions_id_profile"),
        named_check("version_number > 0", name="version_number_positive"),
        named_check(
            "default_transfer_limit_irr IS NULL OR default_transfer_limit_irr > 0",
            name="default_limit_positive_when_set",
        ),
        named_check(
            "after_cutoff_transfer_limit_irr IS NULL OR after_cutoff_transfer_limit_irr > 0",
            name="after_cutoff_limit_positive_when_set",
        ),
        named_check(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from",
            name="effective_window_is_ordered",
        ),
        named_check(HEX_64_CHECK.format(column="config_hash"), name="config_hash_is_lowercase_hex"),
        # No `status` CHECK, deliberately. M4 slice 8 added one and
        # `test_status_catalogue_drift.py` refused it: the catalogue records
        # `bank_profile_version` with `canonical: null`, and that file's own note says the
        # reason is there so "the next person to reach for an enum finds the reason before
        # the constraint". The argument for adding it — that constraining the column to
        # the three aliases on offer decides nothing — is exactly the argument the rule
        # exists to refuse, because it is how an alias set quietly becomes canonical.
        Index("idx_bank_profile_versions_profile", "bank_profile_id", "version_number"),
    )


class BankAccount(Base):
    """A centre-owned account: the source outgoing payments draw on, or the
    destination incoming ones arrive at, or both."""

    __tablename__ = "bank_accounts"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    bank_profile_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("bank_profiles.id"), nullable=False
    )

    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    account_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deposit_number: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # As entered, for display and for reconciliation against a bank statement.
    iban: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Normalised for comparison and uniqueness. Nullable **and** the regex is
    # null-tolerant: a centre account may be registered before its IBAN is known,
    # and copying the beneficiaries' NOT NULL form here would refuse that row.
    normalized_iban: Mapped[str | None] = mapped_column(String(26), nullable=True, unique=True)

    account_role: Mapped[str] = mapped_column(String(32), nullable=False)

    # No value CHECK, for the same catalogue reason as the profile status.
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    record_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("1")
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        named_check(f"account_role IN ({_quoted(ACCOUNT_ROLES)})", name="account_role"),
        named_check(
            f"normalized_iban IS NULL OR normalized_iban ~ '{IBAN_PATTERN}'",
            name="normalized_iban_shape",
        ),
        named_check("length(btrim(display_name)) > 0", name="display_name_not_blank"),
        Index("idx_bank_accounts_profile_role", "bank_profile_id", "account_role"),
    )


class BankMapping(Base):
    """An immutable mapping/template version for one file type of one bank version.

    Like `bank_profile_versions`: no `record_version`, and the runtime's UPDATE
    grant covers `status` alone.
    """

    __tablename__ = "bank_mappings"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    bank_profile_version_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("bank_profile_versions.id"), nullable=False
    )

    # Which kind of file this maps — an outgoing export, an incoming result, a
    # statement. No value CHECK: the set follows the file categories, and doc 04
    # gives no enumeration for it.
    file_type: Mapped[str] = mapped_column(String(60), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)

    # No value CHECK: `bank_mapping` is the other `canonical: null` entry.
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    required_fields: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    normalization_rules: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    sample_header_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=True
    )
    # Separate from created_by, so a mapping cannot be approved by whoever wrote it
    # once M4 enforces the workflow. Nullable because an unapproved draft is a
    # legitimate state.
    approved_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=True
    )
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        # Both uniques include `file_type`, so an import mapping and an export
        # mapping can each be template_version 1 for the same bank version. A
        # globally scoped unique would make that impossible, and the failure would
        # arrive during the first export rather than here.
        UniqueConstraint(
            "bank_profile_version_id",
            "file_type",
            "template_version",
            name="uq_bank_mappings_template_version",
        ),
        UniqueConstraint(
            "bank_profile_version_id",
            "file_type",
            "config_hash",
            name="uq_bank_mappings_config_hash",
        ),
        named_check("template_version > 0", name="template_version_positive"),
        named_check("length(btrim(file_type)) > 0", name="file_type_not_blank"),
        # DOC-CONFLICT-047 is recorded and NOT enforced here, which took two attempts to
        # get right. This column is the **mapping type** (document 04) and not the file
        # format (document 08), and M4 slice 8 first added a value CHECK to make the wrong
        # reading fail at the write rather than during the first export in M7.
        #
        # The CHECK enumerated document 08's identifiers — `payment_export`,
        # `payment_result_import` — while this repository's own fixtures use
        # `outgoing_export` and `incoming_result`. So it enforced document 04's *meaning*
        # with document 08's *spellings* and broke every existing bank test.
        #
        # Correcting the spellings would not have made it right. Document 04 gives prose,
        # not identifiers: "Statement import, outgoing export, result import". There is no
        # approved identifier set, and enumerating one in a CHECK is the same act
        # `test_status_catalogue_drift.py` refuses for the status columns. The meaning is
        # enforced in `app/commands/bank_configuration.py`, where an allowlist is a
        # decision somebody can revisit rather than a schema claiming to be canonical.
        named_check(HEX_64_CHECK.format(column="config_hash"), name="config_hash_is_lowercase_hex"),
        named_check(
            "sample_header_hash IS NULL OR " + HEX_64_CHECK.format(column="sample_header_hash"),
            name="sample_header_hash_is_lowercase_hex",
        ),
        Index("idx_bank_mappings_version_type", "bank_profile_version_id", "file_type"),
    )


# Exported so a test can assert the prohibition rather than trusting a comment:
# no unique constraint anywhere may make a beneficiary IBAN or name one-per-row.
# Duplicates are legitimate and the approved behaviour is to warn, not to merge.
IBAN_UNIQUE_IS_PERMITTED_ONLY_ON: tuple[tuple[str, str], ...] = (
    ("bank_accounts", "normalized_iban"),
)

__all__ = [
    "ACCOUNT_ROLES",
    "IBAN_PATTERN",
    "IBAN_UNIQUE_IS_PERMITTED_ONLY_ON",
    "BankAccount",
    "BankMapping",
    "BankProfile",
    "BankProfileVersion",
]
