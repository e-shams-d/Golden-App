"""Suggestions, and nothing a suggestion is allowed to decide. `04_Database_Schema.md` §12.5.

M9 slice 1. Twelve columns, one unique, one CHECK, and — more importantly — **no grant of any
kind on `payment_attempts`**.

**The table is advisory and the schema is what says so.** §12.5 at `:1261` opens "Suggestions
only", and `:1274` spells out the consequence: "Accepting a candidate does not itself set an
attempt to paid; a human confirmation command creates/activates the confirmed link and updates the
attempt in one transaction." `15_Agent_Implementation_Plan.md:1102` says it again in four words.
Two documents stating one rule twice is a guard against a specific implementation — the one where
acceptance is a shortcut to `paid` because it is the obvious place to put it.

**So this migration grants the runtime nothing on `payment_attempts`**, and that absence is the
enforcement. A code path that tried to mark an attempt paid from here would fail against
PostgreSQL rather than against a reviewer's memory, and it stays that way until slice 3 adds the
column-level grant deliberately. `SEC-CANDIDATE-001` reads the privilege back as the runtime role
rather than asserting anything about this file.

**Grants on this table: `status` and `resolved_at`, and nothing else.** A candidate's segment, its
attempt, its method and its score are what it *is*. If they were writable, a rejected suggestion
could be quietly re-pointed and re-accepted as a different one — the audit row would say
`rejected` and the live row would describe a link nobody rejected.

`provider_job_id` is nullable and unwritten in Phase 1A: §12.5 says a candidate "may be manually
created in Phase 1A and AI-assisted later", and the column is where the later case will record
which job proposed it. It is created now because adding it later would mean a second migration for
a column document 04 already specifies.

**`UNIQUE(receipt_segment_id, payment_attempt_id, method)` is §12.5's**, and the third column is
the load-bearing one: the same pair may legitimately be suggested twice by two different methods —
a rule engine and a person — and collapsing those would lose which one a reviewer accepted.

Revision ID: 20260829_0028
Revises: 20260828_0027
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260829_0028"
down_revision: str | Sequence[str] | None = "20260828_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `status_catalog.yaml`'s `matching_candidate` aggregate, all five, in its order. Four of them are
# terminal; only `proposed` has an arrow out that this slice can draw.
CANDIDATE_STATUSES = (
    "proposed",
    "accepted_for_confirmation",
    "rejected",
    "superseded",
    "expired",
)

# What a candidate's lifecycle may move, and nothing else. See the module docstring: the four
# columns that say *what* is being suggested are frozen at insert.
GRANTED_COLUMNS = ("status", "resolved_at")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _runtime_roles() -> tuple[str, ...]:
    from app.core.config import load_settings

    settings = load_settings()
    configured = {
        "APP_DB_ROLE": settings.app_db_role,
        "WORKER_DB_ROLE": settings.worker_db_role,
    }
    missing = sorted(name for name, value in configured.items() if not value)
    if missing:
        raise RuntimeError(
            f"Migration {revision} grants on mutable columns and these roles are "
            f"not set: {', '.join(missing)}."
        )
    return tuple(str(value) for value in configured.values())


def upgrade() -> None:
    op.create_table(
        "matching_candidates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # §12.5: "For Phase 1A outgoing-payment matching, use explicit FKs." Both NOT NULL — a
        # suggestion that names only one side suggests nothing.
        sa.Column(
            "receipt_segment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("receipt_segments.id", name="fk_candidates_segment"),
            nullable=False,
        ),
        sa.Column(
            "payment_attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_attempts.id", name="fk_candidates_attempt"),
            nullable=False,
        ),
        # How the suggestion was arrived at. Not a status and not a lifecycle: it is fixed at
        # insert and it is the third column of the unique below.
        sa.Column("method", sa.String(32), nullable=False),
        # §12.5's CHECK constrains it to [0, 1]. Nullable because a person proposing a link by
        # hand has no score to give, and a default of 1.0 would make a human guess look like a
        # certainty an engine computed.
        sa.Column("score", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("status", sa.String(32), nullable=False),
        # Phase 1B's. Nullable and unwritten here; see the module docstring.
        sa.Column("provider_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        # The two-column actor shape M8's `receipt_segments` uses, for the same reason: a
        # candidate may later be proposed by a job rather than a person, and `actor_id` is
        # nullable so a system proposal does not have to borrow somebody's identity.
        sa.Column("created_by_actor_type", sa.String(24), nullable=False),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Set when the candidate leaves `proposed`, whichever way it leaves.
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        # §12.5, verbatim.
        sa.CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 1)", name="score_in_range"
        ),
        sa.CheckConstraint(f"status IN ({_quoted(CANDIDATE_STATUSES)})", name="status_value"),
        # Not in §12.5, and it closes the same shape M8 slice 2 found in the bbox CHECK: a
        # resolved candidate with no `resolved_at`, or an unresolved one carrying a timestamp,
        # is a row whose own history contradicts it. Decidable, unlike a rule left to a service.
        sa.CheckConstraint(
            "(status = 'proposed' AND resolved_at IS NULL)"
            " OR "
            "(status <> 'proposed' AND resolved_at IS NOT NULL)",
            name="resolved_at_matches_status",
        ),
        sa.UniqueConstraint(
            "receipt_segment_id",
            "payment_attempt_id",
            "method",
            name="uq_candidate_segment_attempt_method",
        ),
    )

    # The reviewer's queue: everything still awaiting a decision, newest first. Not in §12.5 —
    # added because the accept and reject routes both load by id and the *list* a person works
    # from is a scan over `proposed` without it.
    op.create_index(
        "idx_candidates_open_by_segment",
        "matching_candidates",
        ["receipt_segment_id", "created_at"],
        postgresql_where=sa.text("status = 'proposed'"),
    )
    op.create_index(
        "idx_candidates_by_attempt",
        "matching_candidates",
        ["payment_attempt_id", "status"],
    )

    bind = op.get_bind()
    columns = ", ".join(GRANTED_COLUMNS)
    for role in _runtime_roles():
        bind.execute(
            sa.text(f'GRANT UPDATE ({columns}) ON public."matching_candidates" TO "{role}"')
        )


def downgrade() -> None:
    op.drop_index("idx_candidates_by_attempt", table_name="matching_candidates")
    op.drop_index("idx_candidates_open_by_segment", table_name="matching_candidates")
    op.drop_table("matching_candidates")
