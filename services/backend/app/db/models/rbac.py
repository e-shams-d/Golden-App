"""Roles, permissions, and the grants between them.

Three shapes here are decisions rather than defaults.

**`role_permissions` uses a composite primary key and the one sanctioned
`ON DELETE CASCADE`.** A role's permission set is a set: the pair either is a
member or is not, and there is nothing else to say about it. Cascading is safe
precisely because the row carries no history — deleting a role should not leave
orphan pairs pointing at nothing.

**`admin_user_roles` uses a surrogate key and does not cascade.** Doc 04
specifies no primary key for it at all, and a composite `(admin_user_id,
role_id)` would make revoke-then-regrant impossible: the second grant collides
with the revoked first, so either history is destroyed or the regrant fails.
Uniqueness is therefore partial — one *live* grant per pair, any number of
revoked ones — and a revoked grant is retained because who held what authority
and when is exactly what an audit asks.

**Permission and role codes are text, not enums.** A PostgreSQL enum needs a
migration to add a value, and the catalogue is explicitly provisional: seeding a
new permission must be data, not DDL.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, named_check, updated_at_column, uuid_primary_key


class Permission(Base):
    """One thing a role may be allowed to do.

    Codes come from `permission_catalog.yaml` and are dotted lowercase, matching
    doc 12's identifiers rather than doc 05's API spellings — DOC-CONFLICT-013
    settled that, and the deprecated aliases are deliberately not rows here so
    they cannot be granted.
    """

    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = uuid_primary_key()
    code: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    domain: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        named_check("code = lower(code)", name="code_is_lowercase"),
        named_check("code LIKE '%.%'", name="code_is_dotted"),
    )


class Role(Base):
    """A named bundle of permissions.

    `is_system` marks a role the platform depends on — `system_worker` exists so
    background work can author audit rows without holding human financial
    authority. Marking it lets a later admin screen refuse to delete it without
    needing a hardcoded list of names.
    """

    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = uuid_primary_key()
    code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    # Seeded disabled where the catalogue says so — `support_operator` is
    # disabled by default and enabling it is a deliberate act.
    is_enabled: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (named_check("code = lower(code)", name="code_is_lowercase"),)


class RolePermission(Base):
    """Which permissions a role carries. A set, so a composite key fits."""

    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        # The one sanctioned cascade in the schema. Safe because the row holds no
        # history: a pair is either a member of the set or it is not.
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    )

    created_at: Mapped[datetime] = created_at_column()


class AdminUserRole(Base):
    """A grant of a role to an admin, retained after revocation.

    Deliberately not a composite key. Revoke-then-regrant is ordinary — someone
    changes team and comes back — and a composite key forces a choice between
    destroying the revocation record and refusing the second grant. Neither is
    acceptable when the question an audit asks is "who could approve this, and
    when".
    """

    __tablename__ = "admin_user_roles"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    admin_user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        # No cascade: deleting an admin must not silently erase the record of
        # what they were allowed to do.
        ForeignKey("admin_users.id"),
        nullable=False,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("roles.id"), nullable=False
    )

    granted_at: Mapped[datetime] = created_at_column()
    granted_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=True
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=True
    )
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # One live grant per pair; revoked ones accumulate freely.
        Index(
            "uq_admin_user_roles_live_grant",
            "admin_user_id",
            "role_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        named_check(
            "(revoked_at IS NULL AND revoked_by_admin_id IS NULL) "
            "OR (revoked_at IS NOT NULL)",
            name="revocation_fields_move_together",
        ),
        Index("idx_admin_user_roles_admin", "admin_user_id"),
    )
