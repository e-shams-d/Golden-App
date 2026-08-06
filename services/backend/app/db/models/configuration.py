"""Settings, feature flags, and the retention structures nothing acts on yet.

Two tables that change behaviour and two that only describe intent.

**Secrets do not live in `system_settings`.** Doc 04:1486 prohibits it, and the
reason is that this table is readable by every role with `system_setting.read`,
writable through an admin screen, and dumped into every backup — three properties
that are right for a cutoff time and wrong for a credential. Deployment secret
management owns those. The prohibition is enforced by a test rather than stated
in a comment, because a comment does not stop the first person who needs a token
somewhere convenient.

**`break_glass_enabled` is not seeded, in any value.** POL-005 is approved and
disables break-glass activation, permission grants, endpoints, *feature flags*
and runtime bypasses — the flag itself, not merely its enablement. A seeded row,
even set false, would be writable through `feature_flag.update`, whose default
grant is `technical_admin`: the one role that must hold no financial authority.
Doc 18's wider "recommended initial flags" list includes it under a different
naming convention, and that document carries no owner sign-off; the approved
policy overrides it, and the divergence is recorded rather than silently
normalised.

**`retention_policies` and `legal_holds` are structure only.** No executor, no
sweeper, no trigger, nothing that deletes. ADR-005 is open, so the governed
procedures that would authorise a deletion do not exist — and a table that can
express a retention policy is useful for review long before anything is allowed
to act on one. The separate propose/approve/activate actor columns exist so the
approved workflow stays expressible without a schema change when it lands.

There is no soft-delete column anywhere here, and deliberately no mixin that
could add one. Deletion is modelled as a governed, table-specific state — a
payment request is `cancelled`, an export is `superseded`, an evidence link is
`replaced` — because a shared `deleted_at` would apply one meaning to every
future financial table at once, and "deleted" means something different in each.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, named_check, updated_at_column, uuid_primary_key

# Typed rather than parsed. A setting stored as text and interpreted by whoever
# reads it produces "true"/"True"/"1" disagreements between two call sites, and
# the one that guesses wrong is the one nobody tested.
VALUE_TYPES: tuple[str, ...] = ("string", "integer", "boolean", "json", "duration_seconds")

# The five Phase 1A flags from 04:1502-1506, exactly. `break_glass_enabled` is
# absent and its absence is the point.
PHASE_1A_FLAGS: tuple[tuple[str, bool], ...] = (
    ("manual_crop.enabled", True),
    ("auto_segmentation.enabled", False),
    ("ocr.enabled", False),
    ("ai_matching.enabled", False),
    ("bank_api.enabled", False),
)

# Names that must never appear as a settings key. Checked as substrings, because
# the risk is `bank_api_token` and `storage_secret_key`, not a key somebody
# helpfully called `secret`.
PROHIBITED_SETTING_FRAGMENTS: tuple[str, ...] = (
    "password",
    "secret",
    "token",
    "credential",
    "private_key",
    "api_key",
    "access_key",
    "encryption_key",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(24), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)

    # No value CHECK on status: no approved catalogue enumerates it, and
    # inventing the set here would decide it.
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    # Who last changed it. Nullable because a seeded row has no human author, and
    # recording a fictional one would be worse than recording none.
    updated_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=True
    )

    record_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("1")
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        named_check(f"value_type IN ({_quoted(VALUE_TYPES)})", name="value_type"),
        named_check("length(btrim(key)) > 0", name="key_not_blank"),
        named_check("key = lower(key)", name="key_is_lowercase"),
        # The prohibition, enforced by the database rather than by review. A
        # settings row is readable by every holder of system_setting.read,
        # writable from an admin screen, and present in every backup — three
        # properties that are right for a cutoff time and wrong for a credential.
        named_check(
            " AND ".join(
                f"key NOT LIKE '%{fragment}%'" for fragment in PROHIBITED_SETTING_FRAGMENTS
            ),
            name="key_is_not_a_secret",
        ),
        Index("idx_system_settings_category", "category"),
    )


class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    flag_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    rollout_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    updated_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=True
    )

    record_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("1")
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        named_check("length(btrim(flag_key)) > 0", name="flag_key_not_blank"),
        named_check("flag_key = lower(flag_key)", name="flag_key_is_lowercase"),
        # Enforced in the database, not only by not seeding it. POL-005 prohibits
        # the flag itself; without this, `feature_flag.update` — granted by
        # default to technical_admin — could create it at runtime, and the role
        # that must hold no financial authority would have created the bypass.
        named_check(
            "flag_key NOT LIKE '%break_glass%'",
            name="break_glass_flag_is_prohibited",
        ),
    )


class RetentionPolicy(Base):
    """A retention intention. Nothing in M2 acts on one.

    The three actor columns are separate because the approved workflow is
    proposal → review → approval → legal-hold check → dry-run impact → backup
    coordination → activation → separate deletion execution → deletion evidence.
    Collapsing them into a single `updated_by` would make the separation of
    proposer from approver unexpressible, and that separation is the control.
    """

    __tablename__ = "retention_policies"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    # Which records the policy covers. Free text rather than a foreign key: the
    # tables it will name mostly do not exist yet.
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    retention_class: Mapped[str] = mapped_column(String(80), nullable=False)
    retention_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # A version chain rather than an edit. Reducing a retention duration creates
    # a new policy version and deletes nothing (04:1517) — editing in place would
    # make the shorter period appear always to have applied.
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("retention_policies.id"), nullable=True
    )

    status: Mapped[str] = mapped_column(String(32), nullable=False)

    proposed_by_admin_user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=False
    )
    proposed_at: Mapped[datetime] = created_at_column()

    approved_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    activated_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        named_check("retention_seconds > 0", name="retention_is_positive"),
        named_check("version > 0", name="version_positive"),
        named_check("supersedes_id IS NULL OR supersedes_id <> id", name="supersedes_is_not_self"),
        # An approval that does not say who approved it cannot be audited, and
        # separation of proposer from approver is the whole control.
        named_check(
            "(approved_at IS NULL AND approved_by_admin_user_id IS NULL) "
            "OR (approved_at IS NOT NULL AND approved_by_admin_user_id IS NOT NULL)",
            name="approval_fields_move_together",
        ),
        named_check(
            "(activated_at IS NULL AND activated_by_admin_user_id IS NULL) "
            "OR (activated_at IS NOT NULL AND activated_by_admin_user_id IS NOT NULL)",
            name="activation_fields_move_together",
        ),
        # Cannot be activated without having been approved first.
        named_check(
            "activated_at IS NULL OR approved_at IS NOT NULL",
            name="activation_requires_approval",
        ),
        Index("idx_retention_policies_resource", "resource_type", "retention_class"),
    )


class LegalHold(Base):
    """A hold that must survive any future retention policy. Structure only."""

    __tablename__ = "legal_holds"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    # Nullable: a hold may cover a whole resource type rather than one record.
    resource_id: Mapped[uuid.UUID | None] = mapped_column(PostgresUUID(as_uuid=True), nullable=True)

    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)

    placed_by_admin_user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=False
    )
    placed_at: Mapped[datetime] = created_at_column()

    released_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=True
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        named_check("length(btrim(reason)) > 0", name="reason_not_blank"),
        # Releasing a hold is the act that would allow deletion, so it records
        # who and why or it does not happen.
        named_check(
            "(released_at IS NULL AND released_by_admin_user_id IS NULL "
            "AND release_reason IS NULL) "
            "OR (released_at IS NOT NULL AND released_by_admin_user_id IS NOT NULL "
            "AND release_reason IS NOT NULL)",
            name="release_fields_move_together",
        ),
        # The lookup a deletion path would perform, if one existed. Partial so
        # released holds leave the index.
        Index(
            "idx_legal_holds_active",
            "resource_type",
            "resource_id",
            postgresql_where=text("released_at IS NULL"),
        ),
    )
