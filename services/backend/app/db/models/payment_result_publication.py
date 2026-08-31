"""One immutable trader-visible answer. `04_Database_Schema.md` §11.9.

M9 slice 5. §11.9's first sentence is the whole design: "Immutable versions of the trader-visible
result/share output. This table is required because a published result may later be corrected
without erasing what was previously shown or shared."

**What the row holds and what the payload holds are different questions, deliberately.**

    summary_payload   the content a trader is shown, and exactly what content_hash covers
    the columns       which request, which version, who published it, when, what it supersedes

The split is not cosmetic. `UNIQUE(payment_request_id, content_hash)` is what refuses a correction
that changed nothing, and it can only refuse anything if the digest is blind to the clock and to
the version counter. A payload carrying `published_at` would make every republication unique and
the constraint decorative. `app/commands/payment_publication.py` owns the digest and its test.

**No `record_version` and no `updated_at`**, for the reason `payment_request_revisions` has
neither: both are machinery for changing a row that nothing may change. The migration grants the
runtime no UPDATE on this table at all, so the absence is enforced a level below this file.

`status` still moves — `active` to `superseded` when a correction publishes N+1 — and that is M9
slice 7, which brings the grant with the command rather than ahead of it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, named_check, uuid_primary_key

# §11.9's `status` column, in document 04's own order. `status_catalog.yaml` names no
# `payment_result_publication` aggregate, so document 04 is the only source and the drift gate has
# nothing to compare these against — recorded in the migration and owed to M0.
PUBLICATION_STATUSES: tuple[str, ...] = ("active", "superseded", "revoked")

PUBLICATION_ACTIVE = "active"
PUBLICATION_SUPERSEDED = "superseded"
PUBLICATION_REVOKED = "revoked"

# `04_Database_Schema.md:1162` in arrow form: a correction supersedes the active version, and
# nothing brings a superseded one back. Slice 7 is the only thing entitled to use this.
PERMITTED_TRANSITIONS: dict[str, frozenset[str]] = {
    PUBLICATION_ACTIVE: frozenset({PUBLICATION_SUPERSEDED, PUBLICATION_REVOKED}),
    PUBLICATION_SUPERSEDED: frozenset(),
    PUBLICATION_REVOKED: frozenset(),
}


class PaymentResultPublication(Base):
    """One published version of one request's result. §11.9."""

    __tablename__ = "payment_result_publications"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    payment_request_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("payment_requests.id", name="fk_publications_request"),
        nullable=False,
    )

    # §11.9: "Monotonic per request". The counter lives here rather than in the payload so that
    # `uq_publication_content_per_request` still has something to refuse.
    publication_version: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(String(24), nullable=False)

    summary_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    share_file_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("file_objects.id", name="fk_publications_share_file"),
        nullable=True,
    )

    primary_evidence_link_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("confirmed_evidence_links.id", name="fk_publications_evidence"),
        nullable=True,
    )

    content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)

    published_by_admin_user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_publications_published_by"),
        nullable=False,
    )
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    supersedes_publication_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("payment_result_publications.id", name="fk_publications_supersedes"),
        nullable=True,
    )
    correction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        named_check(
            "status IN (" + ", ".join(f"'{value}'" for value in PUBLICATION_STATUSES) + ")",
            name="status_value",
        ),
        named_check("publication_version > 0", name="version_positive"),
        named_check(
            "(supersedes_publication_id IS NULL AND correction_reason IS NULL)"
            " OR "
            "(supersedes_publication_id IS NOT NULL AND correction_reason IS NOT NULL)",
            # Short: `ck_payment_result_publications_` already spends 31 of PostgreSQL's 63 bytes.
            name="supersession_needs_a_reason",
        ),
        named_check(
            "supersedes_publication_id IS NULL OR supersedes_publication_id <> id",
            name="no_self_supersession",
        ),
        UniqueConstraint(
            "payment_request_id",
            "publication_version",
            name="uq_publication_version_per_request",
        ),
        UniqueConstraint(
            "payment_request_id", "content_hash", name="uq_publication_content_per_request"
        ),
        Index(
            "uq_active_publication_per_request",
            "payment_request_id",
            unique=True,
            postgresql_where="status = 'active'",
        ),
    )
