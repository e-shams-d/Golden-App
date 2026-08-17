"""The request aggregate, and the immutable revisions that hold its content.

`04_Database_Schema.md:822-906`. Two tables in one module because neither is
meaningful alone: a request without a revision has no content, and a revision
without a request has no owner.

**The split is the milestone.** `payment_requests` carries no amount and no
beneficiary snapshot — document 04 calls it a "stable logical request aggregate" and
gives it none of those columns. Every value a reviewer reads and a bank is paid from
lives on `payment_request_revisions`, which nothing may ever update. That is what
makes "what did they submit the first time" answerable after three corrections, and
it is the half of DOC-CONFLICT-005 that document 02 contradicts — see the M5 plan
§2.2.

**`current_revision_id` is a composite foreign key, and it must be.**
`04_Database_Schema.md:1536-1547` specifies
`(current_revision_id, id) REFERENCES payment_request_revisions (id, payment_request_id)`,
deferrable. A single-column key would let request A point at request B's revision —
the pointer would be valid, the row would look correct, and the request would show
somebody else's beneficiary and amount. `bank_profiles` proved the pattern in M2 for
the same reason.

Deferrable because the request and its first revision are inserted in one
transaction and each references the other: whichever goes first would violate a
constraint checked immediately.

**A revision has no `record_version` and no `updated_at`, deliberately.** Both would
be machinery for changing a row that nothing may change. Optimistic concurrency
belongs to the request, which does move; the revision is written once and read
forever.

**`UNIQUE(payment_request_id, content_hash)`** (`:901`) means a correction that
changes nothing is refused at the database. The M5 plan first claimed the opposite
and slice 3 corrected it: a trader asked to fix something who resubmits it unchanged
has not fixed it, and a second identical revision would reach a reviewer looking
like new work.
"""

from __future__ import annotations

import uuid
from datetime import datetime

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
)
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

# `04_Database_Schema.md:863-871`, which is `status_catalog.yaml`'s `payment_request`
# aggregate. Enumerated here for the CHECK; `tests/backend/test_status_catalogue_drift.py`
# compares this set against the approved catalogue, so a value added here that the
# catalogue does not list fails rather than ships.
PAYMENT_REQUEST_STATUSES: tuple[str, ...] = (
    "draft",
    "submitted_to_center",
    "under_accountant_review",
    "needs_trader_correction",
    "eligible_for_batching",
    "batched",
    "sent_to_bank",
    "partially_paid",
    "paid",
    "failed",
    "retry_required",
    "result_ready_for_trader",
    "result_published",
    "trader_acknowledged",
    "trader_disputed",
    "cancelled",
    "closed",
)

# What M5 actually implements. The rest of `PAYMENT_REQUEST_STATUSES` exists because
# the catalogue and document 04 define seventeen and the CHECK must accept what
# later milestones will write; the commands in M5 move a request through these five
# and refuse the others. Kept next to the full set so the difference is visible
# rather than discovered.
M5_REACHABLE_STATUSES: tuple[str, ...] = (
    "draft",
    "submitted_to_center",
    "under_accountant_review",
    "needs_trader_correction",
    "eligible_for_batching",
    "cancelled",
)

# `entered_amount_unit`, per `15_Agent_Implementation_Plan.md:798`. Slice 4 owns the
# conversion; the column and its CHECK arrive with the table so a row cannot be
# written with a unit nothing understands.
AMOUNT_UNITS: tuple[str, ...] = ("IRR", "TOMAN")


class PaymentRequest(Base):
    """The stable aggregate. Carries no amount and no beneficiary snapshot."""

    __tablename__ = "payment_requests"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    trader_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("traders.id"), nullable=False
    )
    # The beneficiary the request is *for*. The revision snapshots its details; this
    # is the link back to the live record, which a screen uses to offer "use this
    # beneficiary again" and which nothing reads to decide what was submitted.
    beneficiary_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("beneficiaries.id"), nullable=False
    )

    request_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    # Nullable, and it has to be: the first revision does not exist yet when the
    # request row is inserted. Document 04 says "no initially" in as many words.
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True
    )

    status: Mapped[str] = mapped_column(String(48), nullable=False)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # M8 and M9 write these. The columns exist now because document 04 defines the
    # table once and a later ALTER to add four nullable columns would be churn with
    # no decision in it; nothing in M5 sets them.
    result_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trader_acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trader_disputed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trader_result_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    record_version: Mapped[int] = record_version_column()

    created_by_trader_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("trader_users.id"), nullable=True
    )
    created_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=True
    )

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        named_check(
            "status IN (" + ", ".join(f"'{value}'" for value in PAYMENT_REQUEST_STATUSES) + ")",
            name="status_value",
        ),
        # The composite pointer. Deferrable because the request and its first
        # revision reference each other and are written in one transaction.
        ForeignKeyConstraint(
            ["current_revision_id", "id"],
            ["payment_request_revisions.id", "payment_request_revisions.payment_request_id"],
            name="fk_request_current_revision",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        # Doc 04:856-861 names both indexes.
        Index("idx_payment_requests_trader_status", "trader_id", "status", "created_at"),
        Index(
            "idx_payment_requests_queue",
            "status",
            "submitted_at",
            postgresql_where=(
                "status IN ('submitted_to_center','under_accountant_review',"
                "'needs_trader_correction','eligible_for_batching',"
                "'retry_required','trader_disputed')"
            ),
        ),
    )


class PaymentRequestRevision(Base):
    """One immutable snapshot of what a trader submitted.

    No column of this table may ever be updated. The migration grants no UPDATE on it
    at all — not even column-level, which is where it is stricter than
    `bank_profile_versions`, whose `status` moves. A revision has no status; the
    request does.
    """

    __tablename__ = "payment_request_revisions"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    # Both of this table's longer foreign keys are named explicitly. Under the `fk_`
    # convention they come out at 64 and 67 bytes, and PostgreSQL truncates an
    # identifier at 63 **without warning** — the model would say one name, the
    # database would hold another, and a later `DROP CONSTRAINT` by the declared name
    # would fail on a constraint that looks present. `over_length_identifiers()` and
    # `test_no_identifier_would_be_silently_truncated` are what caught it.
    payment_request_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("payment_requests.id", name="fk_request_revisions_request"),
        nullable=False,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)

    beneficiary_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("beneficiaries.id"), nullable=False
    )

    # NOT NULL, all three of the ones document 04 marks required. A revision that
    # could omit the beneficiary's name is a revision that cannot answer what was
    # submitted, which is the only thing it exists to do.
    beneficiary_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    beneficiary_iban_snapshot: Mapped[str] = mapped_column(String(26), nullable=False)
    beneficiary_national_id_snapshot: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )

    # Integer IRR, per the approved money contract. Slice 4 computes it from the
    # entered pair; the CHECK that it is positive is here because a zero or negative
    # payment is not a payment.
    amount_irr: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entered_amount_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    entered_amount_unit: Mapped[str | None] = mapped_column(String(8), nullable=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # M4's `file_objects`. Nullable: an attachment is optional, and slice 6 is what
    # refuses one that is not `available`.
    source_attachment_file_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("file_objects.id", name="fk_request_revisions_attachment"),
        nullable=True,
    )

    revision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_by_actor_type: Mapped[str] = mapped_column(String(24), nullable=False)
    created_by_actor_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True
    )

    created_at: Mapped[datetime] = created_at_column()

    # Set when a later revision replaces this one. It is the single exception to "no
    # column may be updated" *in intent* and is deliberately **not** treated as one:
    # M5 does not write it, the migration grants no UPDATE, and the current revision
    # is identified by `payment_requests.current_revision_id` instead. Document 04
    # defines the column, so it exists; nothing in this milestone may move it, and a
    # milestone that needs to must widen the grant deliberately and say why.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "payment_request_id", "revision_number", name="uq_revision_number_per_request"
        ),
        # `:901`. A correction that changes nothing is refused here rather than in a
        # command, so it cannot be bypassed by a second writer.
        UniqueConstraint(
            "payment_request_id", "content_hash", name="uq_revision_content_per_request"
        ),
        # `:1537`. The other half of the composite pointer: the FK on
        # `payment_requests` needs this exact pair to be unique.
        UniqueConstraint("id", "payment_request_id", name="uq_request_revision_pair"),
        named_check("amount_irr > 0", name="amount_irr_positive"),
        named_check(f"beneficiary_iban_snapshot ~ '{IBAN_PATTERN}'", name="iban_snapshot_shape"),
        named_check("revision_number > 0", name="revision_number_positive"),
        # Both or neither. Document 04 marks the pair nullable, and a value with no
        # unit is a number nobody can act on — slice 4 stores what was typed so a
        # dispute is answerable, and half of that is not an answer.
        named_check(
            "(entered_amount_value IS NULL) = (entered_amount_unit IS NULL)",
            name="entered_amount_pair_complete",
        ),
        named_check(
            "entered_amount_unit IS NULL OR entered_amount_unit IN ("
            + ", ".join(f"'{value}'" for value in AMOUNT_UNITS)
            + ")",
            name="entered_amount_unit_value",
        ),
    )


__all__ = [
    "AMOUNT_UNITS",
    "M5_REACHABLE_STATUSES",
    "PAYMENT_REQUEST_STATUSES",
    "PaymentRequest",
    "PaymentRequestRevision",
]
