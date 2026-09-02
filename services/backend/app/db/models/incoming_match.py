"""The relationship between a trader's claim and the bank's record. `04_Database_Schema.md` §10.7.

M10 slice 5. **A candidate, never a truth.** Document 05 §21.5: "Candidate acceptance and financial
confirmation remain separate", and document 06 §11.3 says it again from the other side: "Candidate
acceptance is not financial confirmation."

**One table, two lifecycles, and only one of them is enforced here.** `status_catalog.yaml` carries
`incoming_match_candidate` (document 06 §11.1's five states) and `incoming_confirmed_match` (§11.2's
three) as separate aggregates for this single table. `status` enforces the candidate set exactly;
whether the confirmed set becomes a second column or extends this one is the same two-axis question
`bank_statement_import_run` already put to M0, and slice 6 is where it has to be answered rather
than assumed.

**Four columns are frozen at insert**: the receipt, the row, the method and the score. A candidate
whose subject or whose evidence could be rewritten afterwards is one nobody can audit — and
`matching_candidate.py`, the outgoing direction's twin, froze exactly the same four for exactly
this reason.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
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

# `status_catalog.yaml`'s `incoming_match_candidate` aggregate, all five, in its order.
#
# **`accepted_for_review`, not `accepted_for_confirmation`.** The outgoing direction's candidate
# uses the second spelling and this one uses the first; they are two aggregates and the catalogue
# is the authority for each. Copying the neighbouring model's constant would have been the easy
# mistake and `test_status_catalogue_drift.py` would have caught it.
MATCH_STATUSES: tuple[str, ...] = (
    "proposed",
    "accepted_for_review",
    "rejected",
    "superseded",
    "expired",
)

MATCH_PROPOSED = "proposed"
MATCH_ACCEPTED_FOR_REVIEW = "accepted_for_review"
MATCH_REJECTED = "rejected"
MATCH_SUPERSEDED = "superseded"
MATCH_EXPIRED = "expired"

# What slice 5 can reach. `superseded` and `expired` belong to document 06 §11.3's fourth rule —
# "Changing source receipt, import run, or row interpretation expires/supersedes stale candidates"
# — which is slice 8's correction path, and `accepted_for_review` is slice 6's. Kept beside the full
# set so the difference is visible rather than discovered.
SLICE_FIVE_REACHABLE: tuple[str, ...] = (MATCH_PROPOSED, MATCH_REJECTED)

# Phase 1A's only method. Document 08 §8.8: "Phase 1A allows manual search and confirmation.
# Candidate rules may help but remain non-final." There is no CHECK on the column — no document
# enumerates the values — so this constant is what the command writes rather than what the schema
# permits.
METHOD_MANUAL = "manual_search"


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class IncomingPaymentMatch(Base):
    """One proposed pairing of one receipt with one statement row. §10.7."""

    __tablename__ = "incoming_payment_matches"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    incoming_payment_receipt_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("incoming_payment_receipts.id", name="fk_incoming_matches_receipt"),
        nullable=False,
    )
    bank_statement_row_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bank_statement_rows.id", name="fk_incoming_matches_row"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(String(32), nullable=False)

    match_method: Mapped[str] = mapped_column(String(64), nullable=False)
    # Nullable, and that is the point: a human who searched and found the row has no score to give,
    # and defaulting to 1.0 would make a person's judgement indistinguishable from a machine's
    # certainty. The outgoing direction's `score` says the same thing in the same words.
    match_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    # **NOT NULL with a default of `[]`, and that is the opposite call from
    # `bank_statement_rows.raw_data` a slice earlier.** There the default was removed, because an
    # empty raw copy would have hidden a statement line nobody preserved. Here an empty list is a
    # true and ordinary answer: a human who searched and recognised the row has no reasons to give
    # beyond having looked. Forcing every writer to spell `[]` would buy nothing.
    #
    # Declared here as well as in the migration because `test_schema_matches_models.py` compares
    # server defaults, and the mismatch is invisible until a real database is built from both.
    match_reasons: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    # Slice 6's. Null here, and no command in this slice reaches them.
    confirmed_amount_irr: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    confirmed_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_incoming_matches_confirmed_by"),
        nullable=True,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    rejected_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_incoming_matches_rejected_by"),
        nullable=True,
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # §10.7's correction path, and slice 8's. A corrected match points at the one it replaces
    # rather than editing it — the shape M9 slice 2's `confirmed_evidence_links` uses.
    replaces_match_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("incoming_payment_matches.id", name="fk_incoming_matches_replaces"),
        nullable=True,
    )

    record_version: Mapped[int] = record_version_column()
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        # §10.7's constraint, and the only unique on this table. §10.7 `:809` leaves anything
        # stricter to the business: "The baseline supports traceable partial/combined payment
        # cases."
        UniqueConstraint(
            "incoming_payment_receipt_id",
            "bank_statement_row_id",
            name="uq_incoming_matches_receipt_row",
        ),
        named_check(f"status IN ({_quoted(MATCH_STATUSES)})", name="status_value"),
        named_check(
            "match_score IS NULL OR (match_score >= 0 AND match_score <= 1)",
            name="match_score_in_range",
        ),
        named_check(
            "confirmed_amount_irr IS NULL OR confirmed_amount_irr > 0",
            name="confirmed_amount_positive",
        ),
        named_check(
            "(rejected_at IS NULL AND rejected_by_admin_user_id IS NULL)"
            " OR "
            "(rejected_at IS NOT NULL AND rejected_by_admin_user_id IS NOT NULL)",
            name="rejection_needs_an_actor",
        ),
        named_check(
            "(confirmed_at IS NULL AND confirmed_by_admin_user_id IS NULL)"
            " OR "
            "(confirmed_at IS NOT NULL AND confirmed_by_admin_user_id IS NOT NULL)",
            name="confirmation_needs_an_actor",
        ),
        named_check(
            "replaces_match_id IS NULL OR replaces_match_id <> id",
            name="replacement_is_another_row",
        ),
        Index(
            "idx_incoming_matches_receipt_status",
            "incoming_payment_receipt_id",
            "status",
            "created_at",
        ),
        Index("idx_incoming_matches_row_status", "bank_statement_row_id", "status"),
    )


__all__ = [
    "MATCH_ACCEPTED_FOR_REVIEW",
    "MATCH_EXPIRED",
    "MATCH_PROPOSED",
    "MATCH_REJECTED",
    "MATCH_STATUSES",
    "MATCH_SUPERSEDED",
    "METHOD_MANUAL",
    "SLICE_FIVE_REACHABLE",
    "IncomingPaymentMatch",
]
