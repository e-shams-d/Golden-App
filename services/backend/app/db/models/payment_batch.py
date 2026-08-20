"""The attempt, the container, its immutable versions, their ordered items, and the allocation.

`04_Database_Schema.md` §§11.3-11.6 plus the relation `FINANCIAL_INTEGRITY_BASELINE.md:34-49`
approves and no document names. Five tables in one module because none of them is meaningful
alone: an attempt with no item is never paid, an item with no allocation is a row two batches
could both claim, and a version with no container has no lifecycle.

**An attempt is not a request.** `:62` says so in as many words, and the whole milestone rests
on it: a request is what a trader asked for, an attempt is one transfer instruction a bank will
either execute or refuse. One request becomes several attempts the moment its amount exceeds a
transfer limit, and every attempt carries its own frozen beneficiary snapshot — frozen at the
revision it came from, not read live, because the file the bank receives has to be explainable
months later from rows alone.

**`payment_attempts` has no `payment_batch_id`.** Document 04 says that too, at `:909`: "No
mutable `payment_batch_id` column exists." Membership is the allocation, and the reason is the
whole of `FINANCIAL_INTEGRITY_BASELINE.md:34-49` — a column would let two versions both name the
same attempt with nothing at the database boundary refusing the second, which is a double
payment that reconciles to nothing.

**`payment_batches.status` is a projection, not a fact.** `status_catalog.yaml:359-370` marks
nine of its eleven states `derived: true`, with only `rejected` and `cancelled` stored; document
04 gives the container a `status` column anyway. Both are right: the column is a materialised
view of the current version's state. `CON-BATCH-004` asserts the two cannot disagree rather than
asserting what the command wrote, because a test of the write passes on a projection that has
already drifted.

**Uniqueness on the allocation is a partial index, and that is the design.**
`FINANCIAL_INTEGRITY_BASELINE.md:36` asks for a relation "whose unique/primary key is
`payment_attempt_id`", and `:42-43` asks in the next breath that "allocation/release evidence
remain immutable and queryable". A literal primary key satisfies the first and makes the second
impossible — release would have to delete the evidence. `WHERE released_at IS NULL` satisfies
both, and carries no version predicate so the constraint holds across every active version,
which `:46` states as a warning against the narrower reading. G-1 records the shape for owner
ratification.

Immutability here is the absence of a privilege: `20260820_0017` grants no UPDATE on
`payment_batch_items` or `payment_attempt_allocations` at all, and column-level UPDATE elsewhere.
Slice 4 widens the allocation to `(released_at, release_reason)` when release exists to need it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
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
from app.db.models.bank import IBAN_PATTERN

# `status_catalog.yaml`'s `payment_attempt` aggregate, which is also
# `04_Database_Schema.md:952-956`. `tests/backend/test_status_catalogue_drift.py` compares this
# tuple against the approved catalogue and requires equality, so a value added here that the
# catalogue does not list fails rather than ships.
PAYMENT_ATTEMPT_STATUSES: tuple[str, ...] = (
    "created",
    "included_in_batch_version",
    "sent_to_bank",
    "bank_result_pending",
    "paid",
    "failed",
    "retry_required",
    "superseded",
    "cancelled",
)

# `status_catalog.yaml`'s `payment_batch`, which is `06_Workflows_and_State_Machines.md:757-771`.
# Nine of these eleven are `derived: true` — see the module docstring.
PAYMENT_BATCH_STATUSES: tuple[str, ...] = (
    "draft",
    "ready_for_approval",
    "approved",
    "approval_invalidated",
    "exported",
    "sent_to_bank",
    "result_received",
    "partially_resolved",
    "resolved",
    "rejected",
    "cancelled",
)

# `status_catalog.yaml`'s `payment_batch_version`, and `04_Database_Schema.md:989`.
PAYMENT_BATCH_VERSION_STATUSES: tuple[str, ...] = (
    "draft",
    "ready_for_approval",
    "approved",
    "rejected",
    "superseded",
)

# What M6 reaches, kept beside the full sets so the difference is visible rather than
# discovered. Approval, export, mark-sent and every result state belong to M7 and M8;
# `15_Agent_Implementation_Plan.md:901` and `:934-947` assign them.
M6_REACHABLE_BATCH_STATUSES: tuple[str, ...] = ("draft", "ready_for_approval", "cancelled")
M6_REACHABLE_VERSION_STATUSES: tuple[str, ...] = (
    "draft",
    "ready_for_approval",
    "superseded",
)
M6_REACHABLE_ATTEMPT_STATUSES: tuple[str, ...] = (
    "created",
    "included_in_batch_version",
    "superseded",
    "cancelled",
)

# `04_Database_Schema.md:917`. An attempt's kind, not its state: it never changes after insert,
# which is why it has no place in the status catalogue and gets its own CHECK.
ATTEMPT_TYPES: tuple[str, ...] = ("original", "split", "retry", "correction")


class PaymentAttempt(Base):
    """One transfer instruction, frozen against the revision it came from."""

    __tablename__ = "payment_attempts"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    payment_request_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("payment_requests.id", name="fk_payment_attempts_request"),
        nullable=False,
    )
    # No `ForeignKey` here: the constraint is composite and declared in `__table_args__`, so a
    # single-column key does not also exist to be satisfied on its own.
    payment_request_revision_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=False
    )

    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_type: Mapped[str] = mapped_column(String(24), nullable=False)

    amount_irr: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Frozen at allocation from the revision, never read live. The bank file has to be
    # explainable from rows alone after the beneficiary record has moved on.
    beneficiary_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    beneficiary_iban_snapshot: Mapped[str] = mapped_column(String(26), nullable=False)
    beneficiary_national_id_snapshot: Mapped[str | None] = mapped_column(String(16), nullable=True)

    bank_profile_version_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey(
            "bank_profile_versions.id", name="fk_payment_attempts_bank_profile_version"
        ),
        nullable=False,
    )
    bank_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bank_accounts.id", name="fk_payment_attempts_bank_account"),
        nullable=True,
    )

    # The four splitting rules that produced this row's amount, as they read at the instant of
    # the split. `DB-ATTEMPT-002`: an export generated next month must be reproducible without
    # a live profile, so the rules are evidence and not a cache.
    split_rule_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    status: Mapped[str] = mapped_column(String(40), nullable=False)

    # Everything below is a fact a bank teaches us later. Created because `:849-859` requires
    # the lineage columns so a retry can be attributed; nothing in M6 writes any of them, and
    # `DB-ATTEMPT-001` asserts that rather than pretending a retry path exists.
    bank_tracking_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bank_result_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_of_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("payment_attempts.id", name="fk_payment_attempts_retry_of"),
        nullable=True,
    )
    supersedes_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("payment_attempts.id", name="fk_payment_attempts_supersedes"),
        nullable=True,
    )
    confirmed_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_payment_attempts_confirmed_by"),
        nullable=True,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    record_version: Mapped[int] = record_version_column()
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        named_check("amount_irr > 0", name="amount_irr_positive"),
        named_check("attempt_number > 0", name="attempt_number_positive"),
        named_check(
            "attempt_type IN (" + ", ".join(f"'{value}'" for value in ATTEMPT_TYPES) + ")",
            name="attempt_type_value",
        ),
        named_check(
            "status IN (" + ", ".join(f"'{value}'" for value in PAYMENT_ATTEMPT_STATUSES) + ")",
            name="status_value",
        ),
        named_check(f"beneficiary_iban_snapshot ~ '{IBAN_PATTERN}'", name="iban_snapshot_shape"),
        # `:942-943`. An attempt that retries itself is a cycle of one, and the loop walking
        # the lineage would not terminate.
        named_check(
            "retry_of_attempt_id IS NULL OR retry_of_attempt_id <> id",
            name="retry_of_is_not_self",
        ),
        named_check(
            "supersedes_attempt_id IS NULL OR supersedes_attempt_id <> id",
            name="supersedes_is_not_self",
        ),
        # `:1564-1566`: "An attempt's revision must belong to the same payment request." A
        # single-column key would let an attempt cite another trader's revision, and every
        # snapshot frozen from it would be evidence about the wrong person.
        ForeignKeyConstraint(
            ["payment_request_revision_id", "payment_request_id"],
            ["payment_request_revisions.id", "payment_request_revisions.payment_request_id"],
            name="fk_payment_attempts_revision_belongs_to_request",
        ),
        UniqueConstraint(
            "payment_request_id", "attempt_number", name="uq_attempt_number_per_request"
        ),
        Index(
            "idx_payment_attempts_request_status",
            "payment_request_id",
            "status",
            "attempt_number",
        ),
        Index(
            "idx_payment_attempts_match",
            "amount_irr",
            "beneficiary_iban_snapshot",
            "bank_tracking_number",
        ),
        # Document 04 states a near-duplicate in section 18.1 (`:1666-1668`): the same two
        # leading columns without `bank_tracking_number`, plus a status predicate, for M8's
        # matching workflow. Created as specified for the reason `20260817_0016:264-274`
        # recorded about the request queue's third index — dropping a schema document's index is
        # a performance judgement, and there is no traffic to measure.
        Index(
            "idx_attempt_match_amount_iban",
            "amount_irr",
            "beneficiary_iban_snapshot",
            postgresql_where=(
                "status IN ('sent_to_bank','bank_result_pending','failed','retry_required')"
            ),
        ),
    )


class PaymentBatch(Base):
    """The stable container. Its `status` is a projection of the current version's."""

    __tablename__ = "payment_batches"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    batch_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    # Nullable for the same reason `payment_requests.current_revision_id` is: the first version
    # does not exist yet when this row is inserted, and the composite key below is deferred so
    # both can be written in one transaction.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True
    )

    created_by_admin_user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_payment_batches_created_by"),
        nullable=False,
    )

    sent_to_bank_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_to_bank_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_payment_batches_sent_by"),
        nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    record_version: Mapped[int] = record_version_column()
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        named_check(
            "status IN (" + ", ".join(f"'{value}'" for value in PAYMENT_BATCH_STATUSES) + ")",
            name="status_value",
        ),
        ForeignKeyConstraint(
            ["current_version_id", "id"],
            ["payment_batch_versions.id", "payment_batch_versions.payment_batch_id"],
            name="fk_batch_current_version",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
    )


class PaymentBatchVersion(Base):
    """An immutable ordered snapshot proposed for approval.

    Only `status` and `superseded_at` are grantable; every other column is written once.
    """

    __tablename__ = "payment_batch_versions"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    payment_batch_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("payment_batches.id", name="fk_batch_versions_batch"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # The three configuration versions an export is reproducible from. All three NOT NULL:
    # a version that cannot say which mapping produced it cannot be re-rendered, and
    # `FINANCIAL_INTEGRITY_BASELINE.md` §1 requires exactly that of a final artifact.
    bank_profile_version_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey(
            "bank_profile_versions.id", name="fk_batch_versions_bank_profile_version"
        ),
        nullable=False,
    )
    bank_account_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bank_accounts.id", name="fk_batch_versions_bank_account"),
        nullable=False,
    )
    bank_mapping_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bank_mappings.id", name="fk_batch_versions_bank_mapping"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(String(32), nullable=False)

    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount_irr: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_by_admin_user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_batch_versions_created_by"),
        nullable=False,
    )
    created_at: Mapped[datetime] = created_at_column()
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        named_check("row_count > 0", name="row_count"),
        named_check("total_amount_irr > 0", name="total_positive"),
        named_check("version_number > 0", name="version_number_positive"),
        named_check(
            "status IN ("
            + ", ".join(f"'{value}'" for value in PAYMENT_BATCH_VERSION_STATUSES)
            + ")",
            name="status_value",
        ),
        UniqueConstraint("payment_batch_id", "version_number", name="uq_version_number_per_batch"),
        # `:1000`. A replacement whose content is byte-identical to a version this batch
        # already holds is refused by the database, not by a service check.
        UniqueConstraint("payment_batch_id", "content_hash", name="uq_version_content_per_batch"),
        # The pair the container's composite key needs. `:1555` names it.
        UniqueConstraint("id", "payment_batch_id", name="uq_batch_version_pair"),
        Index(
            "idx_batch_versions_approval_queue",
            "status",
            "created_at",
            postgresql_where="status = 'ready_for_approval'",
        ),
        # §18.1's version of the same queue (`:1654-1656`): `(created_at)` with the same
        # predicate. Since the predicate pins `status`, the leading `status` column above
        # answers nothing this one does not — so this is arguably the better index and the one
        # above is the redundant one. Both created, for the reason recorded on the attempt.
        Index(
            "idx_batch_manager_queue",
            "created_at",
            postgresql_where="status = 'ready_for_approval'",
        ),
    )


class PaymentBatchItem(Base):
    """One row of one version. Insert-only: the migration grants no UPDATE on this table."""

    __tablename__ = "payment_batch_items"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    payment_batch_version_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("payment_batch_versions.id", name="fk_batch_items_version"),
        nullable=False,
    )
    payment_attempt_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("payment_attempts.id", name="fk_batch_items_attempt"),
        nullable=False,
    )

    row_order: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_irr: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Copied from the attempt rather than joined at render time. `:1021-1023` calls these the
    # "Exact approved/exported value": what the manager approved and what the bank received
    # must be the same bytes, and a join could not promise that after the attempt moved on.
    beneficiary_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    beneficiary_iban_snapshot: Mapped[str] = mapped_column(String(26), nullable=False)
    description_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        named_check("row_order > 0", name="row_order"),
        named_check("amount_irr > 0", name="amount_positive"),
        named_check(f"beneficiary_iban_snapshot ~ '{IBAN_PATTERN}'", name="iban_snapshot_shape"),
        UniqueConstraint(
            "payment_batch_version_id", "payment_attempt_id", name="uq_item_attempt_per_version"
        ),
        UniqueConstraint(
            "payment_batch_version_id", "row_order", name="uq_item_row_order_per_version"
        ),
        # The pair the allocation's composite key needs, so an allocation cannot name an item
        # belonging to a version other than the one it records.
        UniqueConstraint("id", "payment_batch_version_id", name="uq_batch_item_version_pair"),
    )


class PaymentAttemptAllocation(Base):
    """The relation `FINANCIAL_INTEGRITY_BASELINE.md:34-49` approves and no document names.

    One active row per attempt, enforced by a partial unique index rather than a primary key,
    for the reason the module docstring gives: the same baseline paragraph that asks for the
    constraint also asks that release evidence stay queryable, and a primary key on
    `payment_attempt_id` makes the second impossible.
    """

    __tablename__ = "payment_attempt_allocations"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    payment_attempt_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("payment_attempts.id", name="fk_allocation_attempt"),
        nullable=False,
    )
    # Denormalised from the item, and safe because the composite key below checks the pair.
    # Carried so "every active allocation in this version" is one table scan, which is the
    # question finalization has to ask of every item at once.
    payment_batch_version_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=False
    )
    payment_batch_item_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=False
    )

    allocated_at: Mapped[datetime] = created_at_column()
    allocated_by_admin_user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_allocation_allocated_by"),
        nullable=False,
    )

    # Slice 4's, and the grant that would permit writing them is slice 4's too. Today the
    # runtime role cannot set either, which is what makes "release does not exist yet" a
    # property of the database rather than a promise about the code.
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # A release that answers "when" and not "why" is not the evidence the baseline asks
        # for. Enforced as a pair so neither can arrive alone.
        named_check(
            "(released_at IS NULL) = (release_reason IS NULL)",
            name="release_pair_complete",
        ),
        ForeignKeyConstraint(
            ["payment_batch_item_id", "payment_batch_version_id"],
            ["payment_batch_items.id", "payment_batch_items.payment_batch_version_id"],
            name="fk_allocation_item_belongs_to_version",
        ),
        # The constraint the baseline calls the database boundary. No version predicate: it
        # holds across every active version, which `:46` states as a warning against the
        # narrower reading. `unique=True` with a `WHERE` is a partial unique index.
        Index(
            "uq_active_allocation_per_attempt",
            "payment_attempt_id",
            unique=True,
            postgresql_where="released_at IS NULL",
        ),
        Index(
            "idx_allocations_by_version",
            "payment_batch_version_id",
            postgresql_where="released_at IS NULL",
        ),
    )
