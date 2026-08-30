"""The authoritative relationship between a receipt segment and a payment attempt. §12.6.

M9 slice 2. §12.6 opens by calling it exactly that — *authoritative* — which is the word that
separates this table from `matching_candidates`. A candidate suggests; this decides.

**Two partial unique indexes carry §17 `:1115`'s cardinality**, and they are the reason this table
needs a database rather than a service rule:

- one active **primary** link per attempt;
- one active **primary** target per segment;
- supplementary links unbounded, expressed by there being no third index.

A service check would read the table, find nothing, and insert — and two accountants working the
same attempt from two screens would both pass it. `CON-EVIDENCE-001` proves the difference with two
connections.

**Replacement never deletes.** §12.6 at `:1306`: the old row becomes `replaced` and a new row is
inserted in the same transaction. That is why `replaces_link_id` is a self foreign key and why the
migration grants UPDATE on `status` alone — the chain has to stay readable, and a row whose subject
could be rewritten would make the chain a record of nothing.

**`revoked` is canonical; `voided` is a deprecated alias and is not admitted here.**
`status_catalog.yaml` marks the alias provisional pending reconciliation, and
`command_catalog.yaml`'s revoke row carries `status:
blocked_by_voided_vs_revoked_status_conflict`. The migration's docstring records how that was
settled and what documents 04 and 05 are owed.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, named_check, uuid_primary_key

# `status_catalog.yaml`'s `confirmed_evidence_link` aggregate, canonical spellings only.
LINK_STATUSES: tuple[str, ...] = ("active", "replaced", "revoked")

LINK_ACTIVE = "active"
LINK_REPLACED = "replaced"
LINK_REVOKED = "revoked"

# §12.6 at `:1284`.
LINK_TYPES: tuple[str, ...] = ("primary", "supplementary")

LINK_PRIMARY = "primary"
LINK_SUPPLEMENTARY = "supplementary"

# **Document 05's spelling of the revoked state, and the one thing this module will not accept.**
# `05_API_Specification.md:1860` names the route `/void` and §12.6's column list says `voided`;
# documents 06 and 08 say `revoked` and the status catalogue makes that canonical. The route keeps
# its path — it is the API contract — and the alias never reaches the column.
DEPRECATED_REVOKED_ALIAS = "voided"

# Every arrow document 06 §22.3 draws, and no others. `active` is the only state with any.
PERMITTED_TRANSITIONS: dict[str, frozenset[str]] = {
    LINK_ACTIVE: frozenset({LINK_REPLACED, LINK_REVOKED}),
    LINK_REPLACED: frozenset(),
    LINK_REVOKED: frozenset(),
}


class ConfirmedEvidenceLink(Base):
    """One confirmed relationship. §12.6."""

    __tablename__ = "confirmed_evidence_links"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    payment_attempt_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("payment_attempts.id", name="fk_evidence_links_attempt"),
        nullable=False,
    )
    receipt_segment_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("receipt_segments.id", name="fk_evidence_links_segment"),
        nullable=False,
    )

    link_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)

    # NOT NULL. §12.6 calls it the human actor, and §17 `:1106` requires an actor on every link —
    # there is no system path to this table, so a nullable column would be an invitation to one.
    confirmed_by_admin_user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_evidence_links_confirmed_by"),
        nullable=False,
    )
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    replaces_link_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("confirmed_evidence_links.id", name="fk_evidence_links_replaces"),
        nullable=True,
    )
    replacement_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    published_to_trader_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        named_check(
            "link_type IN (" + ", ".join(f"'{value}'" for value in LINK_TYPES) + ")",
            name="link_type_value",
        ),
        named_check(
            "status IN (" + ", ".join(f"'{value}'" for value in LINK_STATUSES) + ")",
            name="status_value",
        ),
        named_check(
            "(replaces_link_id IS NULL AND replacement_reason IS NULL)"
            " OR "
            "(replaces_link_id IS NOT NULL AND replacement_reason IS NOT NULL)",
            # Short because `ck_confirmed_evidence_links_` already spends 28 of PostgreSQL's 63
            # bytes; the identifier gate refuses anything it would truncate silently.
            name="replacement_needs_a_reason",
        ),
        named_check(
            "replaces_link_id IS NULL OR replaces_link_id <> id",
            name="a_link_does_not_replace_itself",
        ),
        UniqueConstraint(
            "payment_attempt_id",
            "receipt_segment_id",
            "link_type",
            name="uq_evidence_link_attempt_segment_type",
        ),
        # §12.6 at `:1297`, both verbatim. The cardinality rules, enforced where two concurrent
        # transactions cannot both win.
        Index(
            "uq_attempt_active_primary_evidence",
            "payment_attempt_id",
            unique=True,
            postgresql_where="link_type = 'primary' AND status = 'active'",
        ),
        Index(
            "uq_segment_active_primary_attempt",
            "receipt_segment_id",
            unique=True,
            postgresql_where="link_type = 'primary' AND status = 'active'",
        ),
    )
