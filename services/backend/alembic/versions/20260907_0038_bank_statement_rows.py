"""Immutable parsed rows, tied to one import run. `04_Database_Schema.md` §10.6.

M10 slice 4. One table, and §10.6's first line is the whole design: "Immutable rows tied to one
import run."

**No UPDATE grant at all, on any column.** The runtime may insert rows and read them and nothing
else. That is the strongest form the schema can give of "immutable", and it is the same shape
`20260831_0031` used for `payment_result_publications`: an immutability that a later branch cannot
be edited out of, because the privilege to write is not there to begin with. A correction is a new
import run — document 08 §8.2, and slice 3's `UNIQUE(bank_statement_file_id, run_number)` is what
makes that cheap.

**The three columns document 04 forbids are absent, and their absence is the enforcement.** §10.6
`:796`: "Do not store generic `matched_entity_type/id` or a mutable `is_matched` flag as the source
of truth. Match state is derived from dedicated match records." So there is no
`matched_entity_type`, no `matched_entity_id` and no `is_matched` here, and
`tests/backend/test_statement_row_shape.py` walks the model to say so — because the failure mode
is somebody adding a convenient flag in a later slice while every behavioural test still passes.

**Raw beside normalized, everywhere the two can differ.** §10.6 asks for "normalized and raw
date/time" and document 08 §8.5 makes the rule general: "Preserve every raw source value",
"Preserve raw Jalali/Gregorian strings", "Normalize IBAN and tracking values without losing
originals". A row whose raw date was discarded cannot be re-normalised when the mapping is
corrected, and correcting a mapping and reparsing is precisely what §8.9 says must be supported.

**Every parsed field is nullable except the ones the platform itself assigns.** Document 08 §8.4:
"Missing fields remain null. They must not be guessed." So `amount_in_irr`, the timestamp, the
counterparty and the tracking number are all nullable, and `raw_data`, `row_fingerprint`, `status`
and `row_number` — which the parser produces rather than reads — are not.

Revision ID: 20260907_0038
Revises: 20260906_0037
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260907_0038"
down_revision: str | Sequence[str] | None = "20260906_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Document 08 §8.6's five row states. `status_catalog.yaml` has **no** `bank_statement_row`
# aggregate — the only M10 table for which that is true — so document 08 is this CHECK's sole
# source and `test_status_catalogue_drift.py` carries it as a `LOCAL_LIFECYCLES` entry with the
# reason written out.
ROW_STATUSES = (
    "valid",
    "warning",
    "invalid",
    "ignored_empty",
    "possible_duplicate",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "bank_statement_rows",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "bank_statement_import_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bank_statement_import_runs.id", name="fk_statement_rows_run"),
            nullable=False,
        ),
        # The row's position in the bank's file, one-based. Not a surrogate ordering: an operator
        # reading "row 42 is invalid" opens the spreadsheet and looks at row 42.
        sa.Column("row_number", sa.Integer(), nullable=False),
        # §10.6's "normalized and raw date/time". The normalized instant is nullable because a row
        # whose date could not be parsed is a row with a raw date and no instant — which is a
        # finding, not a reason to invent one.
        sa.Column("transaction_at_normalized", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transaction_date_raw", sa.String(64), nullable=True),
        sa.Column("transaction_time_raw", sa.String(32), nullable=True),
        # §10.6's three amounts. Document 08 §8.4 spells the first two `deposit_amount_irr` and
        # `withdrawal_amount_irr`; document 04 is the schema authority and its names are used.
        # Nullable and unsigned-by-CHECK rather than NOT NULL DEFAULT 0: a row with no deposit is
        # different from a row that deposited nothing, and §8.5 refuses to guess either.
        sa.Column("amount_in_irr", sa.BigInteger(), nullable=True),
        sa.Column("amount_out_irr", sa.BigInteger(), nullable=True),
        # Signed on purpose. A balance may legitimately be negative; an amount may not.
        sa.Column("balance_irr", sa.BigInteger(), nullable=True),
        # §8.7's duplicate signals include "same tracking/document number", and §8.4 names both
        # fields. Document 04 lists only `tracking_number`; `document_number` is added because the
        # duplicate rule needs it and §8.4 approves it.
        sa.Column("document_number", sa.String(128), nullable=True),
        sa.Column("tracking_number", sa.String(128), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("counterparty_name", sa.String(255), nullable=True),
        sa.Column("counterparty_account", sa.String(64), nullable=True),
        sa.Column("counterparty_iban", sa.String(64), nullable=True),
        # §8.5's first rule: "Preserve every raw source value." Every cell of the source row as it
        # was read, keyed by the header the bank wrote — including columns the mapping does not
        # name, because §22.2 refuses to "partially hide invalid rows" and an unmapped column is
        # exactly what a mapping correction later needs to see.
        # **NOT NULL and no default.** A default of `'{}'` would let an INSERT that forgot the raw
        # copy succeed and look complete, which is exactly what §8.5's first rule forbids. Written
        # with one and caught by `test_schema_matches_models.py`, which noticed the model declared
        # no default; the right fix was to remove it rather than to teach the model about it.
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        # §8.4's `normalized_fingerprint`. Computed over the normalized values, so two rows that
        # describe the same transfer written differently still collide. Slice 4B uses it for
        # §8.7's duplicate detection; here it is recorded and indexed.
        sa.Column("row_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # §10.6's constraint verbatim. Two rows claiming the same position in one parse would make
        # "row 42" ambiguous in the one place an operator needs it not to be.
        sa.UniqueConstraint(
            "bank_statement_import_run_id", "row_number", name="uq_statement_rows_run_row_number"
        ),
        sa.CheckConstraint(f"status IN ({_quoted(ROW_STATUSES)})", name="status_value"),
        sa.CheckConstraint("row_number >= 1", name="row_number_is_positive"),
        sa.CheckConstraint(
            "amount_in_irr IS NULL OR amount_in_irr >= 0", name="amount_in_not_negative"
        ),
        sa.CheckConstraint(
            "amount_out_irr IS NULL OR amount_out_irr >= 0", name="amount_out_not_negative"
        ),
        # §8.6 validates "mutually coherent deposit/withdrawal values". Both positive on one row
        # describes a transfer that went two ways at once. Permitted as *null* on both, which is
        # what an empty or unparseable row looks like.
        sa.CheckConstraint(
            "amount_in_irr IS NULL OR amount_out_irr IS NULL"
            " OR amount_in_irr = 0 OR amount_out_irr = 0",
            name="one_direction_per_row",
        ),
    )

    # §10.6's two indexes verbatim. The first is what slice 5 searches on — an amount, a date and a
    # tracking number are the three things a human matching a receipt to a statement types in.
    op.create_index(
        "idx_bank_statement_rows_match",
        "bank_statement_rows",
        ["amount_in_irr", "transaction_at_normalized", "tracking_number"],
    )
    op.create_index(
        "idx_bank_statement_rows_fingerprint",
        "bank_statement_rows",
        ["row_fingerprint"],
    )

    # **No GRANT.** Deliberately, and the absence is the point — see the module docstring. The
    # runtime's INSERT and SELECT come from the schema-wide grants; UPDATE is granted per column
    # by every other migration in this project that wants one, and this one wants none.


def downgrade() -> None:
    op.drop_index("idx_bank_statement_rows_fingerprint", table_name="bank_statement_rows")
    op.drop_index("idx_bank_statement_rows_match", table_name="bank_statement_rows")
    op.drop_table("bank_statement_rows")
