"""A suggestion, and the schema that stops it becoming a decision. `04_Database_Schema.md` §12.5.

M9 slice 1. §12.5 opens with two words — "Suggestions only" — and `:1274` states the consequence
the whole milestone is built around: "Accepting a candidate does not itself set an attempt to
paid; a human confirmation command creates/activates the confirmed link and updates the attempt in
one transaction." `15_Agent_Implementation_Plan.md:1102` repeats it.

**Two documents stating one rule twice is a guard against a specific implementation.** Acceptance
is the obvious place to mark an attempt paid — the reviewer has just said "yes, this receipt is
that payment" — and it is the wrong place, because a candidate carries no bank tracking number, no
result timestamp and no confirmation actor. What acceptance opens is a *context* for confirmation;
slice 3's command is what closes it.

**The enforcement is a privilege, not a branch.** `20260829_0028` grants the runtime nothing at
all on `payment_attempts`, so no code reachable from this table can write one. That holds until
slice 3 adds the grant column by column, and it is why `SEC-CANDIDATE-001` reads
`information_schema` as the runtime role rather than reading this module.

**Four columns are frozen at insert**: the segment, the attempt, the method and the score. They
are *what is being suggested*, and a re-pointable candidate would let a rejected suggestion be
quietly turned into a different accepted one — the audit row saying `rejected` while the live row
described a link nobody had reviewed. Only `status` and `resolved_at` carry a grant.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, named_check, uuid_primary_key

# `status_catalog.yaml`'s `matching_candidate` aggregate, all five, in its order. Four are terminal
# there; only `proposed` has an arrow out, which is why `PERMITTED_TRANSITIONS` below is so small.
CANDIDATE_STATUSES: tuple[str, ...] = (
    "proposed",
    "accepted_for_confirmation",
    "rejected",
    "superseded",
    "expired",
)

CANDIDATE_PROPOSED = "proposed"
CANDIDATE_ACCEPTED = "accepted_for_confirmation"
CANDIDATE_REJECTED = "rejected"
CANDIDATE_SUPERSEDED = "superseded"
CANDIDATE_EXPIRED = "expired"

# **`accepted_for_confirmation` is not terminal, and the first draft of this table said it was.**
#
# `status_catalog.yaml` marks it non-terminal and gives no arrows; document 06 §21.2 lists the
# rules without a diagram. The arrow that settles it is in document 05: `:1816` requires a reason
# "when rejecting a high-confidence candidate **or overriding a previously accepted candidate**",
# which only means something if acceptance can be undone. A table without that arrow refuses an
# operation the API specification describes — and being stricter than an approved document is
# still deviation, which is M5's lesson pointing the other way.
#
# §21.2's "source/target changes expire or supersede stale candidates" is not scoped to `proposed`
# either, so an accepted candidate whose segment or attempt moved can go stale the same way.
#
# Written as data rather than as a chain of `if`s for the reason M8's review queue records: a
# transition table can be compared against the catalogue by a test; conditionals can only be read.
PERMITTED_TRANSITIONS: dict[str, frozenset[str]] = {
    CANDIDATE_PROPOSED: frozenset(
        {CANDIDATE_ACCEPTED, CANDIDATE_REJECTED, CANDIDATE_SUPERSEDED, CANDIDATE_EXPIRED}
    ),
    CANDIDATE_ACCEPTED: frozenset(
        {CANDIDATE_REJECTED, CANDIDATE_SUPERSEDED, CANDIDATE_EXPIRED}
    ),
    CANDIDATE_REJECTED: frozenset(),
    CANDIDATE_SUPERSEDED: frozenset(),
    CANDIDATE_EXPIRED: frozenset(),
}

# How a suggestion was arrived at. §12.5 names no vocabulary for `method`, and this is deliberately
# **not** a CHECK: the column is part of a unique whose whole purpose is to let a second method
# suggest the same pair later, and constraining it now to the one value Phase 1A produces would
# make the unique's third column decorative until somebody wrote a migration to widen it.
CANDIDATE_METHOD_MANUAL = "manual"


class MatchingCandidate(Base):
    """One suggested link between a receipt segment and a payment attempt. §12.5."""

    __tablename__ = "matching_candidates"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    receipt_segment_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("receipt_segments.id", name="fk_candidates_segment"),
        nullable=False,
    )
    payment_attempt_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("payment_attempts.id", name="fk_candidates_attempt"),
        nullable=False,
    )

    method: Mapped[str] = mapped_column(String(32), nullable=False)

    # Nullable, and that is a decision rather than a convenience: a person proposing a link by hand
    # has no score to give, and defaulting to 1.0 would make a human guess indistinguishable from a
    # certainty an engine computed.
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)

    # `server_default` as well as the Python default, matching `audit_logs.role_snapshot`. The
    # column is NOT NULL, so without it any insert that does not go through the ORM — a fixture, a
    # future migration backfilling rows — fails rather than getting the empty list §12.5 implies.
    # It is also what `test_schema_matches_models.py` compares: the migration declared the default
    # and the model did not, and autogenerate reported the divergence.
    reasons: Mapped[Any] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    status: Mapped[str] = mapped_column(String(32), nullable=False)

    # Phase 1B's. §12.5 lists it; nothing in Phase 1A writes it, because Phase 1A has no provider.
    provider_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True
    )

    created_by_actor_type: Mapped[str] = mapped_column(String(24), nullable=False)
    created_by_actor_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True
    )

    created_at: Mapped[datetime] = created_at_column()
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        named_check("score IS NULL OR (score >= 0 AND score <= 1)", name="score_in_range"),
        named_check(
            "status IN (" + ", ".join(f"'{value}'" for value in CANDIDATE_STATUSES) + ")",
            name="status_value",
        ),
        # Not in §12.5. A resolved candidate with no `resolved_at`, or an unresolved one carrying
        # a timestamp, is a row whose own history contradicts it — and unlike a service rule, this
        # is decidable by the database. The same shape M8 slice 2 had to add to the bbox CHECK.
        named_check(
            "(status = 'proposed' AND resolved_at IS NULL)"
            " OR "
            "(status <> 'proposed' AND resolved_at IS NOT NULL)",
            name="resolved_at_matches_status",
        ),
        # §12.5's unique, and `method` is the load-bearing column: the same pair may legitimately
        # be suggested by a rule engine and by a person, and collapsing those would lose which one
        # a reviewer accepted.
        UniqueConstraint(
            "receipt_segment_id",
            "payment_attempt_id",
            "method",
            name="uq_candidate_segment_attempt_method",
        ),
        # The reviewer's queue: everything still awaiting a decision. Not in §12.5 — added
        # because both decision routes load by id, and the *list* a person works from would be a
        # sequential scan without it.
        Index(
            "idx_candidates_open_by_segment",
            "receipt_segment_id",
            "created_at",
            postgresql_where=f"status = '{CANDIDATE_PROPOSED}'",
        ),
        Index("idx_candidates_by_attempt", "payment_attempt_id", "status"),
    )
