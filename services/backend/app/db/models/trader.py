"""The trader business — the root every ownership guard in M3 hangs on.

`trader_users` is a person who signs in; `traders` is the business they act for.
M2 shipped the first without the second, which is why `trader_users.trader_id`
did not exist and why the primary-contact index degraded into a system-wide
singleton (see `20260808_0013`). Ownership needs the business, not the login:
"trader A may not read trader B's records" is a statement about businesses, and
a business can have more than one contact.

**Three status axes, and no fourth column combining them.** DOC-CONFLICT-024
records that document 04 splits trader state into `approval_status` and
`operational_status` while document 05 exposes one combined `status`. The
approved structural resolution is that they are separate concepts:
`approval_status` answers "is this an accepted counterparty", `operational_status`
answers "may it transact today", and the login account's own state lives on
`trader_users.status`. The combined value the API returns is **computed at read
time and never stored**. There is deliberately no `status` column here — a stored
projection of three facts is a fourth copy that drifts from them, and leaving the
column out makes the drift unrepresentable rather than merely tested for.

**Neither status column carries a value CHECK, and that is not an oversight.**
`status_catalog.yaml` records one `trader` aggregate holding document 06's single
five-state machine (`pending_approval`, `active`, `suspended`, `rejected`,
`inactive`), plus `blocked` and `approved` as unresolved aliases that it says in
terms must not be collapsed without policy approval. Document 04's two columns do
not partition that set. Enumerating either column here would answer, from a
migration, whether `blocked` collapses into `suspended` and whether `approved`
maps to `active` — business questions DOC-CONFLICT-024 assigns to M5's trader
lifecycle. The absence is pinned by `tests/backend/test_status_catalogue_drift.py`
so the tempting fix is blocked rather than merely undocumented.

**No balance column.** `04_Database_Schema.md:469` prohibits an authoritative
`current_balance_irr` without a ledger and reconciliation model, and a mutable
cached balance without one is named there as explicitly forbidden.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    created_at_column,
    named_check,
    record_version_column,
    updated_at_column,
    uuid_primary_key,
)


class Trader(Base):
    """A trader business. Owned records scope to this id, never to a login."""

    __tablename__ = "traders"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # The business's contact number, unique across traders. Distinct from
    # `trader_users.phone_number`, which is a login identity: the same human may
    # be reachable on both and they are not the same fact.
    primary_phone: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)

    # Two axes, never merged. See the module docstring for why neither carries a
    # value CHECK yet.
    operational_status: Mapped[str] = mapped_column(String(24), nullable=False)
    approval_status: Mapped[str] = mapped_column(String(24), nullable=False)

    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=True
    )

    # Advisory label only. It carries no authorization: nothing may read this to
    # decide whether a command is permitted.
    risk_level: Mapped[str | None] = mapped_column(String(24), nullable=True)

    # Integer IRR, per the approved money contract. Nullable means "no limit
    # recorded", which is not the same as zero — hence the CHECK admits NULL.
    credit_limit_irr: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Never trader-visible. Named so at the column rather than left to a serializer
    # to remember.
    notes_internal: Mapped[str | None] = mapped_column(Text, nullable=True)

    record_version: Mapped[int] = record_version_column()
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        named_check("length(btrim(display_name)) > 0", name="display_name_not_blank"),
        named_check("length(btrim(primary_phone)) > 0", name="primary_phone_not_blank"),
        named_check(
            "credit_limit_irr IS NULL OR credit_limit_irr >= 0",
            name="credit_limit_irr_not_negative",
        ),
        # Doc 04:474 names this index; DOC-CONFLICT-042's approved rule is that an
        # index document 04 names keeps that name, written explicitly rather than
        # left to the `ix_` convention.
        Index("idx_traders_status_approval", "operational_status", "approval_status"),
    )
