"""Attempts, batches, immutable versions, ordered items, and the allocation the baseline demands.

`04_Database_Schema.md` §§11.3-11.6, with the composite integrity at `:1551-1566` and the
active-allocation relation from `FINANCIAL_INTEGRITY_BASELINE.md:34-49`.

**Five objects in one migration, because half of them is a broken head.** Three of the four
foreign keys below are composite, and each composite key needs both of its tables to exist.
Splitting the pair across pull requests would leave a migration head that either names a table
that does not exist or omits the constraint that makes the pointer mean anything.

## The three composite keys, and what each refuses

1. `payment_batches.current_version_id` → `payment_batch_versions(id, payment_batch_id)`, which
   `:1551-1562` specifies in exactly this shape. `DEFERRABLE INITIALLY DEFERRED` for the same
   reason `20260817_0016` needed it: a batch and its first version are inserted in one
   transaction and each points at the other, so whichever row went first would violate an
   immediately-checked constraint and the ordinary path would be impossible.

2. `payment_attempts.payment_request_revision_id` → `payment_request_revisions(id,
   payment_request_id)`, which `:1564-1566` requires in as many words: "An attempt's revision
   must belong to the same payment request." A single-column key would let an attempt cite a
   revision belonging to a *different* trader's request, and every snapshot frozen on that
   attempt would then be evidence about the wrong person — silently, because each row on its own
   would look consistent.

3. `payment_attempt_allocations` → `payment_batch_items(id, payment_batch_version_id)`. The
   allocation carries the version as well as the item so that "every active allocation in this
   version" is one table scan, which is what finalization has to ask. The composite key is what
   makes that copy safe: it cannot name an item belonging to some other version.

## The allocation relation, which no document names (G-1)

`FINANCIAL_INTEGRITY_BASELINE.md:36-46` is an approved decision with no name, column list, or
release shape anywhere. It asks for four things at once, and the shape below is the reading that
satisfies all four rather than the first three:

- "a dedicated active-allocation relation whose unique/primary key is `payment_attempt_id`"
- "A competing allocation for the same attempt must fail at the database boundary"
- "Historical batch items and allocation/release evidence remain immutable and queryable"
- "The constraint applies across all active batch versions, not merely within one version"

A literal primary key on `payment_attempt_id` satisfies the first two and makes the third
impossible: release would have to delete the row, and deleted evidence is not queryable. So the
uniqueness is a **partial unique index** — `WHERE released_at IS NULL` — which is what the
baseline's "unique/primary key" permits and what its own next sentence requires. The index has
no version predicate, so it is global across versions, which is the fourth requirement stated as
a warning against the narrower reading.

Release is therefore two nullable columns on the row that was allocated, not a second table. Two
tables that must agree is a new invariant with nothing enforcing it, and "the projection and the
fact disagree" is the defect class this milestone has already found twice.

**And this table receives no UPDATE grant here.** Release is slice 4's, so today the database
refuses it and `tests/integration/test_allocation_release_is_not_yet_possible.py` proves that
through the runtime role. Slice 4 widens the grant to `UPDATE (released_at, release_reason)` —
column-level, so a release can never rewrite which item was allocated. Granting it now would be
a permission with nothing behind it, which is how `payment_batch.cancel_draft` came to be
approved and seeded with no command (G-4).

G-1 is still the owner's to ratify. What is irreversible here is the name and the column list;
the reading above is written down so that amending it is an edit to a stated decision rather
than an archaeology exercise.

## Statuses, and one that is a projection

Each `status` CHECK equals its `status_catalog.yaml` aggregate exactly, because
`tests/backend/test_status_catalogue_drift.py` requires it and the catalogue records a canonical
set for all three. That is the gate deciding, not this migration: a subset would mean a state the
workflow defines cannot be reached, and a superset a state no document defines.

`payment_batches.status` is the odd one. Nine of its eleven catalogue states are `derived: true`
and document 04 stores the column anyway (`:971`), so the column is a **materialised projection**
of the current version's state and not an independent fact. `CON-BATCH-004` asserts that the two
cannot disagree, rather than asserting that the command wrote `draft` — a test of the write would
pass on a projection that had already drifted from the thing it projects.

## What is created and never written in M6

`retry_of_attempt_id` and `supersedes_attempt_id` exist because `:849-859` needs the lineage for
an attribution M7 and M8 make. Nothing in M6 writes them, and `DB-ATTEMPT-001` asserts they are
nullable and unwritten instead of pretending a retry path exists. `bank_tracking_number`,
`bank_result_at`, `failure_code`, `failure_reason`, `confirmed_by_admin_user_id` and
`confirmed_at` are the same: columns for facts a later milestone learns from a bank.

`payment_batch_items` and `payment_attempt_allocations` receive **no UPDATE grant at all**, on
the `payment_request_revisions` precedent from `20260817_0016`: immutability here is the absence
of a privilege rather than the presence of a rule. `payment_batch_versions` gets
`UPDATE (status, superseded_at)` only, and `payment_attempts` gets
`UPDATE (status, record_version, updated_at)` only — the bank-result columns stay unwritable
until the milestone that learns those facts widens the grant deliberately.

Downgrade drops all five, composite keys first. Honest only while they are empty, on the terms
`20260801_0012:44-46` records.

Revision ID: 20260820_0017
Revises: 20260817_0016
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260820_0017"
down_revision: str | Sequence[str] | None = "20260817_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# `status_catalog.yaml`'s three aggregates, verbatim and in catalogue order. Kept as SQL text
# here and as tuples in `app/db/models/payment_batch.py`; the drift gate compares the model
# against the catalogue and `test_schema_matches_models.py` compares the model against the
# database, so a divergence in either direction fails.
ATTEMPT_STATUSES_SQL = (
    "'created', 'included_in_batch_version', 'sent_to_bank', "
    "'bank_result_pending', 'paid', 'failed', 'retry_required', "
    "'superseded', 'cancelled'"
)

BATCH_STATUSES_SQL = (
    "'draft', 'ready_for_approval', 'approved', 'approval_invalidated', "
    "'exported', 'sent_to_bank', 'result_received', 'partially_resolved', "
    "'resolved', 'rejected', 'cancelled'"
)

VERSION_STATUSES_SQL = "'draft', 'ready_for_approval', 'approved', 'rejected', 'superseded'"

# `04_Database_Schema.md:917`. Not a status: an attempt's *kind*, which never changes.
ATTEMPT_TYPES_SQL = "'original', 'split', 'retry', 'correction'"

IBAN_PATTERN_SQL = "^IR[0-9]{24}$"

# Whole-table UPDATE goes to nothing here. Every mutable column is named, because a table-level
# grant on `payment_attempts` would also permit rewriting the frozen beneficiary snapshot, and
# the snapshot is the evidence.
COLUMN_UPDATE_GRANTS: tuple[tuple[str, str], ...] = (
    ("payment_attempts", "status, record_version, updated_at"),
    (
        "payment_batches",
        "status, current_version_id, sent_to_bank_at, sent_to_bank_by_admin_user_id, "
        "cancelled_at, cancelled_reason, record_version, updated_at",
    ),
    ("payment_batch_versions", "status, superseded_at"),
)


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
            f"Migration {revision} grants on mutable tables and these roles are "
            f"not set: {', '.join(missing)}."
        )
    return tuple(str(value) for value in configured.values())


def upgrade() -> None:
    op.create_table(
        "payment_attempts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("payment_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payment_request_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("attempt_type", sa.String(length=24), nullable=False),
        sa.Column("amount_irr", sa.BigInteger(), nullable=False),
        sa.Column("beneficiary_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("beneficiary_iban_snapshot", sa.String(length=26), nullable=False),
        sa.Column("beneficiary_national_id_snapshot", sa.String(length=16), nullable=True),
        sa.Column("bank_profile_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bank_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "split_rule_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=40), nullable=False),
        # Everything below is a fact a bank teaches us later. Created because `:849-859` needs
        # the lineage for an attribution M7 and M8 make; unwritten in M6, and asserted so.
        sa.Column("bank_tracking_number", sa.String(length=128), nullable=True),
        sa.Column("bank_result_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("retry_of_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("supersedes_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confirmed_by_admin_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount_irr > 0", name=op.f("ck_payment_attempts_amount_irr_positive")),
        sa.CheckConstraint(
            "attempt_number > 0", name=op.f("ck_payment_attempts_attempt_number_positive")
        ),
        sa.CheckConstraint(
            f"attempt_type IN ({ATTEMPT_TYPES_SQL})",
            name=op.f("ck_payment_attempts_attempt_type_value"),
        ),
        sa.CheckConstraint(
            f"status IN ({ATTEMPT_STATUSES_SQL})",
            name=op.f("ck_payment_attempts_status_value"),
        ),
        sa.CheckConstraint(
            f"beneficiary_iban_snapshot ~ '{IBAN_PATTERN_SQL}'",
            name=op.f("ck_payment_attempts_iban_snapshot_shape"),
        ),
        # Document 04 states both self-reference checks at `:942-943`. An attempt that retries
        # itself is a cycle of one, and the loop that walked the lineage would not terminate.
        sa.CheckConstraint(
            "retry_of_attempt_id IS NULL OR retry_of_attempt_id <> id",
            name=op.f("ck_payment_attempts_retry_of_is_not_self"),
        ),
        sa.CheckConstraint(
            "supersedes_attempt_id IS NULL OR supersedes_attempt_id <> id",
            name=op.f("ck_payment_attempts_supersedes_is_not_self"),
        ),
        sa.ForeignKeyConstraint(
            ["payment_request_id"],
            ["payment_requests.id"],
            name="fk_payment_attempts_request",
        ),
        # The composite key of `:1564-1566`. `(revision_id, request_id)` against
        # `(id, payment_request_id)`: the second column of each side is what ties the revision
        # to *this* request rather than to any request.
        sa.ForeignKeyConstraint(
            ["payment_request_revision_id", "payment_request_id"],
            ["payment_request_revisions.id", "payment_request_revisions.payment_request_id"],
            name="fk_payment_attempts_revision_belongs_to_request",
        ),
        sa.ForeignKeyConstraint(
            ["bank_profile_version_id"],
            ["bank_profile_versions.id"],
            name="fk_payment_attempts_bank_profile_version",
        ),
        sa.ForeignKeyConstraint(
            ["bank_account_id"],
            ["bank_accounts.id"],
            name="fk_payment_attempts_bank_account",
        ),
        sa.ForeignKeyConstraint(
            ["retry_of_attempt_id"],
            ["payment_attempts.id"],
            name="fk_payment_attempts_retry_of",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_attempt_id"],
            ["payment_attempts.id"],
            name="fk_payment_attempts_supersedes",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_admin_user_id"],
            ["admin_users.id"],
            name="fk_payment_attempts_confirmed_by",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_attempts")),
        sa.UniqueConstraint(
            "payment_request_id",
            "attempt_number",
            name=op.f("uq_attempt_number_per_request"),
        ),
    )

    op.create_table(
        "payment_batches",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("batch_number", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        # No foreign key yet: the table it points at does not exist.
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_admin_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sent_to_bank_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_to_bank_by_admin_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_reason", sa.Text(), nullable=True),
        sa.Column("record_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"status IN ({BATCH_STATUSES_SQL})",
            name=op.f("ck_payment_batches_status_value"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_admin_user_id"],
            ["admin_users.id"],
            name="fk_payment_batches_created_by",
        ),
        sa.ForeignKeyConstraint(
            ["sent_to_bank_by_admin_user_id"],
            ["admin_users.id"],
            name="fk_payment_batches_sent_by",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_batches")),
        sa.UniqueConstraint("batch_number", name=op.f("uq_payment_batches_batch_number")),
    )

    op.create_table(
        "payment_batch_versions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("payment_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("bank_profile_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bank_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bank_mapping_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("total_amount_irr", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "validation_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by_admin_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("row_count > 0", name=op.f("ck_payment_batch_versions_row_count")),
        sa.CheckConstraint(
            "total_amount_irr > 0", name=op.f("ck_payment_batch_versions_total_positive")
        ),
        sa.CheckConstraint(
            "version_number > 0", name=op.f("ck_payment_batch_versions_version_number_positive")
        ),
        sa.CheckConstraint(
            f"status IN ({VERSION_STATUSES_SQL})",
            name=op.f("ck_payment_batch_versions_status_value"),
        ),
        sa.ForeignKeyConstraint(
            ["payment_batch_id"],
            ["payment_batches.id"],
            name="fk_batch_versions_batch",
        ),
        sa.ForeignKeyConstraint(
            ["bank_profile_version_id"],
            ["bank_profile_versions.id"],
            name="fk_batch_versions_bank_profile_version",
        ),
        sa.ForeignKeyConstraint(
            ["bank_account_id"],
            ["bank_accounts.id"],
            name="fk_batch_versions_bank_account",
        ),
        sa.ForeignKeyConstraint(
            ["bank_mapping_id"],
            ["bank_mappings.id"],
            name="fk_batch_versions_bank_mapping",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_admin_user_id"],
            ["admin_users.id"],
            name="fk_batch_versions_created_by",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_batch_versions")),
        sa.UniqueConstraint(
            "payment_batch_id", "version_number", name=op.f("uq_version_number_per_batch")
        ),
        # `:1000`. A replacement version whose content is byte-identical to one this batch
        # already holds is refused by the database rather than by a service check.
        sa.UniqueConstraint(
            "payment_batch_id", "content_hash", name=op.f("uq_version_content_per_batch")
        ),
        # The pair the composite foreign key below needs. Document 04 names it at `:1555`.
        sa.UniqueConstraint("id", "payment_batch_id", name=op.f("uq_batch_version_pair")),
    )

    op.create_table(
        "payment_batch_items",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("payment_batch_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payment_attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("row_order", sa.Integer(), nullable=False),
        sa.Column("amount_irr", sa.BigInteger(), nullable=False),
        sa.Column("beneficiary_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("beneficiary_iban_snapshot", sa.String(length=26), nullable=False),
        sa.Column("description_snapshot", sa.Text(), nullable=True),
        sa.Column(
            "attempt_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("row_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("row_order > 0", name=op.f("ck_payment_batch_items_row_order")),
        sa.CheckConstraint("amount_irr > 0", name=op.f("ck_payment_batch_items_amount_positive")),
        sa.CheckConstraint(
            f"beneficiary_iban_snapshot ~ '{IBAN_PATTERN_SQL}'",
            name=op.f("ck_payment_batch_items_iban_snapshot_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["payment_batch_version_id"],
            ["payment_batch_versions.id"],
            name="fk_batch_items_version",
        ),
        sa.ForeignKeyConstraint(
            ["payment_attempt_id"],
            ["payment_attempts.id"],
            name="fk_batch_items_attempt",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_batch_items")),
        sa.UniqueConstraint(
            "payment_batch_version_id",
            "payment_attempt_id",
            name=op.f("uq_item_attempt_per_version"),
        ),
        sa.UniqueConstraint(
            "payment_batch_version_id", "row_order", name=op.f("uq_item_row_order_per_version")
        ),
        # The pair the allocation's composite foreign key needs, so an allocation cannot name
        # an item belonging to a different version than the one it records.
        sa.UniqueConstraint(
            "id", "payment_batch_version_id", name=op.f("uq_batch_item_version_pair")
        ),
    )

    # Now both tables exist, so the container's pointer can be constrained. `:1557-1561`.
    op.create_foreign_key(
        op.f("fk_batch_current_version"),
        "payment_batches",
        "payment_batch_versions",
        ["current_version_id", "id"],
        ["id", "payment_batch_id"],
        deferrable=True,
        initially="DEFERRED",
    )

    op.create_table(
        "payment_attempt_allocations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("payment_attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payment_batch_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payment_batch_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "allocated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("allocated_by_admin_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Release is slice 4's, and the grant that would permit writing these is slice 4's too.
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_reason", sa.Text(), nullable=True),
        # A release with no reason is evidence that answers "when" and not "why", and the
        # baseline asks for evidence. Enforced as a pair so neither can arrive alone.
        sa.CheckConstraint(
            "(released_at IS NULL) = (release_reason IS NULL)",
            # The convention's name, not a shorter one. `named_check` in the model produces
            # `ck_%(table_name)s_%(constraint_name)s`, and
            # `tests/integration/test_constraint_names_match_the_models.py` — written in this
            # slice, and this is what it caught first — requires the two to agree.
            name=op.f("ck_payment_attempt_allocations_release_pair_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["payment_attempt_id"],
            ["payment_attempts.id"],
            name="fk_allocation_attempt",
        ),
        # Composite: the item and the version it belongs to, checked together.
        sa.ForeignKeyConstraint(
            ["payment_batch_item_id", "payment_batch_version_id"],
            ["payment_batch_items.id", "payment_batch_items.payment_batch_version_id"],
            name="fk_allocation_item_belongs_to_version",
        ),
        sa.ForeignKeyConstraint(
            ["allocated_by_admin_user_id"],
            ["admin_users.id"],
            name="fk_allocation_allocated_by",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_attempt_allocations")),
    )

    # The whole point of the table, and the reason a service-level check is "insufficient"
    # (`FINANCIAL_INTEGRITY_BASELINE.md:39-40`). No version predicate: the uniqueness is global
    # across every active version, which the baseline states as a warning against the narrower
    # reading. Partial rather than a plain unique constraint so released rows stay queryable —
    # the same sentence that asks for the constraint also asks for the history.
    op.create_index(
        "uq_active_allocation_per_attempt",
        "payment_attempt_allocations",
        ["payment_attempt_id"],
        unique=True,
        postgresql_where=sa.text("released_at IS NULL"),
    )
    op.create_index(
        "idx_allocations_by_version",
        "payment_attempt_allocations",
        ["payment_batch_version_id"],
        postgresql_where=sa.text("released_at IS NULL"),
    )

    # Document 04's own indexes, at `:944-947` and `:1003-1005`.
    op.create_index(
        "idx_payment_attempts_request_status",
        "payment_attempts",
        ["payment_request_id", "status", "attempt_number"],
    )
    op.create_index(
        "idx_payment_attempts_match",
        "payment_attempts",
        ["amount_irr", "beneficiary_iban_snapshot", "bank_tracking_number"],
    )
    op.create_index(
        "idx_batch_versions_approval_queue",
        "payment_batch_versions",
        ["status", "created_at"],
        postgresql_where=sa.text("status = 'ready_for_approval'"),
    )

    # Document 04 states two **more** indexes on these tables in section 18.1, and each is a
    # near-duplicate of one above. `tests/integration/test_schema_matches_the_specification.py`
    # found them, which is what that gate is for.
    #
    # `idx_batch_manager_queue` (`:1654-1656`) is `(created_at)` with the same predicate as
    # `idx_batch_versions_approval_queue`. Since the predicate pins `status`, the leading
    # `status` column in the §11.5 version answers nothing the §18.1 version does not — so this
    # one is arguably the better of the two and the other is the redundant one.
    #
    # `idx_attempt_match_amount_iban` (`:1666-1668`) is `idx_payment_attempts_match` without
    # `bank_tracking_number` and with a status predicate, for M8's matching workflow.
    #
    # **Both created as specified.** This is the same decision `20260817_0016:264-274` recorded
    # for the request queue's third index, and the reason has not changed: dropping a schema
    # document's index is a performance judgement, this repository refuses performance claims
    # without evidence (`PERF-QUEUE-001` is a recorded gap for exactly that reason), and there
    # is no traffic to measure. Consolidating any of these is a one-line migration for whoever
    # has the measurement.
    op.create_index(
        "idx_batch_manager_queue",
        "payment_batch_versions",
        ["created_at"],
        postgresql_where=sa.text("status = 'ready_for_approval'"),
    )
    op.create_index(
        "idx_attempt_match_amount_iban",
        "payment_attempts",
        ["amount_irr", "beneficiary_iban_snapshot"],
        postgresql_where=sa.text(
            "status IN ('sent_to_bank','bank_result_pending','failed','retry_required')"
        ),
    )

    bind = op.get_bind()
    for role in _runtime_roles():
        for table, columns in COLUMN_UPDATE_GRANTS:
            bind.execute(sa.text(f'GRANT UPDATE ({columns}) ON public."{table}" TO "{role}"'))


def downgrade() -> None:
    op.drop_constraint(op.f("fk_batch_current_version"), "payment_batches", type_="foreignkey")
    op.drop_index("idx_attempt_match_amount_iban", table_name="payment_attempts")
    op.drop_index("idx_batch_manager_queue", table_name="payment_batch_versions")
    op.drop_index("idx_batch_versions_approval_queue", table_name="payment_batch_versions")
    op.drop_index("idx_payment_attempts_match", table_name="payment_attempts")
    op.drop_index("idx_payment_attempts_request_status", table_name="payment_attempts")
    op.drop_index("idx_allocations_by_version", table_name="payment_attempt_allocations")
    op.drop_index("uq_active_allocation_per_attempt", table_name="payment_attempt_allocations")
    op.drop_table("payment_attempt_allocations")
    op.drop_table("payment_batch_items")
    op.drop_table("payment_batch_versions")
    op.drop_table("payment_batches")
    op.drop_table("payment_attempts")
