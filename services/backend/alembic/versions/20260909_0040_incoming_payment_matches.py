"""A candidate, never a truth. `04_Database_Schema.md` §10.7.

M10 slice 5. One table for the relationship between a trader's claim and the bank's record —
**and it is M9 slices 1 and 2 again, in one table instead of two.**

The outgoing direction has `matching_candidates` (a suggestion) and `confirmed_evidence_links` (the
authoritative answer), two tables drawing a wall between the two. Document 04 §10.7 gives the
incoming direction one table holding both, and document 06 §11 gives it two lifecycles: §11.1's
five candidate states and §11.2's three confirmed-match states. `status_catalog.yaml` carries both
as separate aggregates — `incoming_match_candidate` and `incoming_confirmed_match` — for a single
table.

**So `status` enforces the candidate aggregate's five, exactly, and nothing here writes a confirmed
state.** That is the honest position for this slice: it proposes and rejects, and document 05
§21.5's "Candidate acceptance and financial confirmation remain separate" is what it exists to
uphold. **Slice 6 inherits the same two-axis question the import run already put to M0** — whether
`active/replaced/revoked` becomes a second column or extends the lifecycle — and it must be
answered there rather than pre-empted by a CHECK written today.

**No partial unique index, and its absence is a decision.** §10.7 `:809`: "Use partial unique rules
only if the business confirms strict one-row/one-receipt matching. The baseline supports traceable
partial/combined payment cases." So one plain unique on the pair — the same match proposed twice is
one row — and nothing else. A partial unique would silently answer the cardinality question the
plan's G-2 records as the owner's.

**The confirmation columns exist and this slice writes none of them.** §10.7 names them and slice 2
set the same precedent for `incoming_payment_receipts`: the grant covers them here rather than in
slice 6, because a column-level grant split across two revisions makes the second unreadable
without the first. What stops this slice writing them is that no command does.

Revision ID: 20260909_0040
Revises: 20260908_0039
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260909_0040"
down_revision: str | Sequence[str] | None = "20260908_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `status_catalog.yaml`'s `incoming_match_candidate` aggregate, all five, in its order. Document 06
# §11.1 is its source. Note `accepted_for_review`, not the outgoing direction's
# `accepted_for_confirmation`: two aggregates, two spellings, and the catalogue is the authority
# for each.
MATCH_STATUSES = (
    "proposed",
    "accepted_for_review",
    "rejected",
    "superseded",
    "expired",
)

# What decides a candidate, and the confirmation slice 6 will write. Not `match_method`,
# `match_score`, `match_reasons` or either foreign key: a candidate whose subject or whose evidence
# could be rewritten after the fact is one nobody can audit. The outgoing direction froze exactly
# the same four columns in `20260829_0028`.
GRANTED_COLUMNS = (
    "status",
    "confirmed_amount_irr",
    "confirmed_by_admin_user_id",
    "confirmed_at",
    "rejected_by_admin_user_id",
    "rejected_at",
    "rejection_reason",
    "replaces_match_id",
    "updated_at",
)


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
        "incoming_payment_matches",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "incoming_payment_receipt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("incoming_payment_receipts.id", name="fk_incoming_matches_receipt"),
            nullable=False,
        ),
        sa.Column(
            "bank_statement_row_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bank_statement_rows.id", name="fk_incoming_matches_row"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        # How the pair was arrived at. No CHECK: no document enumerates the values, and document 08
        # §8.8 says only that "Phase 1A allows manual search and confirmation. Candidate rules may
        # help but remain non-final." Enforcing an invented list would be this migration deciding
        # what a later phase's matcher may call itself.
        sa.Column("match_method", sa.String(64), nullable=False),
        # §10.7's CHECK verbatim. NUMERIC because a score between 0 and 1 must reproduce exactly;
        # `matching_candidate.score` is the outgoing direction's identical column and carries the
        # same recorded exception in `test_money_and_time_guards.py`.
        sa.Column("match_score", sa.Numeric(5, 4), nullable=True),
        # Why. JSONB rather than prose so a later matcher's reasons stay machine-readable, and
        # because §8.8 requires a confirmed match to "record actor, time, reason, and warnings".
        sa.Column(
            "match_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # Slice 6 writes these. Null here, and no command reaches them.
        sa.Column("confirmed_amount_irr", sa.BigInteger(), nullable=True),
        sa.Column(
            "confirmed_by_admin_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", name="fk_incoming_matches_confirmed_by"),
            nullable=True,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "rejected_by_admin_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", name="fk_incoming_matches_rejected_by"),
            nullable=True,
        ),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        # §10.7's correction path, and slice 8's. Self-referential: a corrected match points at the
        # one it replaces rather than editing it.
        sa.Column(
            "replaces_match_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("incoming_payment_matches.id", name="fk_incoming_matches_replaces"),
            nullable=True,
        ),
        sa.Column("record_version", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # §10.7's constraint verbatim, and the **only** unique on this table. See the module
        # docstring: the cardinality beyond this pair is the owner's, not this migration's.
        sa.UniqueConstraint(
            "incoming_payment_receipt_id",
            "bank_statement_row_id",
            name="uq_incoming_matches_receipt_row",
        ),
        sa.CheckConstraint(f"status IN ({_quoted(MATCH_STATUSES)})", name="status_value"),
        # §10.7's two CHECKs verbatim.
        sa.CheckConstraint(
            "match_score IS NULL OR (match_score >= 0 AND match_score <= 1)",
            name="match_score_in_range",
        ),
        sa.CheckConstraint(
            "confirmed_amount_irr IS NULL OR confirmed_amount_irr > 0",
            name="confirmed_amount_positive",
        ),
        # Not in §10.7, and it closes the shape M9 closed three times and slice 2 closed again: a
        # row that says it was rejected must say by whom and when, and one that was not must carry
        # neither.
        sa.CheckConstraint(
            "(rejected_at IS NULL AND rejected_by_admin_user_id IS NULL)"
            " OR "
            "(rejected_at IS NOT NULL AND rejected_by_admin_user_id IS NOT NULL)",
            name="rejection_needs_an_actor",
        ),
        sa.CheckConstraint(
            "(confirmed_at IS NULL AND confirmed_by_admin_user_id IS NULL)"
            " OR "
            "(confirmed_at IS NOT NULL AND confirmed_by_admin_user_id IS NOT NULL)",
            name="confirmation_needs_an_actor",
        ),
        # A candidate cannot cite itself as the thing it replaces.
        sa.CheckConstraint(
            "replaces_match_id IS NULL OR replaces_match_id <> id",
            name="replacement_is_another_row",
        ),
    )

    # The queue read: every candidate for one receipt, newest first. §8.8's "reference the exact
    # import run and row" is served by the foreign key; this is what an accountant's screen asks.
    op.create_index(
        "idx_incoming_matches_receipt_status",
        "incoming_payment_matches",
        ["incoming_payment_receipt_id", "status", "created_at"],
    )
    # The other direction, for §11.3's third rule — "a row already used in an active match causes a
    # duplicate/conflict guard" — which slice 6 enforces and which needs this lookup to be cheap.
    op.create_index(
        "idx_incoming_matches_row_status",
        "incoming_payment_matches",
        ["bank_statement_row_id", "status"],
    )

    bind = op.get_bind()
    columns = ", ".join(GRANTED_COLUMNS)
    for role in _runtime_roles():
        bind.execute(
            sa.text(
                f'GRANT UPDATE ({columns}) ON public."incoming_payment_matches" TO "{role}"'
            )
        )


def downgrade() -> None:
    op.drop_index("idx_incoming_matches_row_status", table_name="incoming_payment_matches")
    op.drop_index("idx_incoming_matches_receipt_status", table_name="incoming_payment_matches")
    op.drop_table("incoming_payment_matches")
