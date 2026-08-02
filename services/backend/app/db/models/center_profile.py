"""The deployment's own profile: one active row, mutable, non-financial.

This is the exemplar mutable aggregate the slice-1 command writes against. It is
deliberately not a tenant table. There is no `organization_id`, no `tenant_id`,
and nothing propagates a `center_id` to child tables; a second active row is
rejected by the database rather than by a convention nobody enforces.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    created_at_column,
    named_check,
    record_version_column,
    updated_at_column,
    uuid_primary_key,
)

DEFAULT_CURRENCY = "IRR"
DEFAULT_TIMEZONE = "Asia/Tehran"

ACTIVE_STATUS = "active"


class CenterProfile(Base):
    __tablename__ = "center_profile"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # Phase 1A settles in IRR only. A CHECK rather than a default alone, because a
    # row written with another currency would misprice every amount that joins to
    # it, and nothing downstream re-reads this column to notice.
    default_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default=text(f"'{DEFAULT_CURRENCY}'")
    )
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text(f"'{DEFAULT_TIMEZONE}'")
    )

    # No value CHECK. `center_profile` has no approved status catalogue entry, and
    # enumerating one here would decide it. The partial unique index below still
    # constrains the only value that carries meaning today.
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    record_version: Mapped[int] = record_version_column()
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        named_check(
            f"default_currency = '{DEFAULT_CURRENCY}'",
            name="default_currency_is_irr",
        ),
        named_check("length(btrim(name)) > 0", name="name_not_blank"),
        # A partial unique index, not a constraint: PostgreSQL supports WHERE only
        # on an index. The doc-04 name is used verbatim rather than the ix_
        # convention, because doc 04 states it and a rename would break the
        # reference.
        Index(
            "uq_center_profile_one_active",
            "status",
            unique=True,
            postgresql_where=text(f"status = '{ACTIVE_STATUS}'"),
        ),
    )
