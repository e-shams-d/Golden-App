"""What the bank returned, as records. `04_Database_Schema.md` §12.1-12.3.

M8 slice 1. Three tables that between them say "this arrived", "these files are in it" and
"somebody thinks it relates to that batch" — and the third is the one that has to be careful.

**A batch link proves nothing about payment.** §12.3: "This association does not prove payment
completion. Attempt/segment confirmation remains authoritative." The enforcement is that there is
nothing here to mean otherwise: no amount, no `confirmed_at`, no attempt reference. `link_method`
records how somebody reached the belief so a later reader can weigh it, and `replaced_at` means a
wrong guess leaves evidence instead of disappearing.

**The counts are cached read values.** §12.1 says so and says they are "not independent financial
truth". They are recomputed from segments in the same transaction that changes one, never
incremented — an increment is correct until the first retry. `ck_bundles_counts_reconcile` holds
the two parts to the whole, because a rule that lives only in a command is a rule the next writer
can miss.

**`uploaded` is where a bundle lands and, in Phase 1A, not where it stays.**
`06_Workflows_and_State_Machines.md:995` draws `uploaded --> ready_for_manual_review: direct manual
mode`, and Phase 1A has no normalization job to take the other branch — so upload *is* the direct
manual mode. The command moves the bundle in one transaction rather than leaving it in a state
nothing can leave, which is what the alternative would be: `05_API_Specification.md:1693`'s
`start-review` route has no permission in `permission_catalog.yaml` at all, so a bundle waiting for
it would wait forever. Recorded as Q-7 in the M8 plan with the conflict row it needs.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, named_check, uuid_primary_key

# `status_catalog.yaml`'s `bank_result_bundle` aggregate, all eight, in its order.
#
# The catalogue also records `files_stored`, `normalized`, `under_manual_review`,
# `needs_attention` and `archived` as **unresolved aliases** — names other documents use that no
# canonical state covers. None is admitted here, because the status-drift gate holds every enforced
# CHECK to its aggregate exactly.
BUNDLE_STATUSES: tuple[str, ...] = (
    "uploaded",
    "processing",
    "ready_for_manual_review",
    "partially_matched",
    "matched",
    "closed",
    "failed",
    "voided",
)

BUNDLE_UPLOADED = "uploaded"
BUNDLE_READY_FOR_REVIEW = "ready_for_manual_review"
BUNDLE_CLOSED = "closed"

# §12.2, verbatim. `source` is what the bank sent; the other three are derived, and slices 4 and 5
# are what create them.
FILE_ROLES: tuple[str, ...] = ("source", "normalized", "preview", "structured_result")

FILE_ROLE_SOURCE = "source"

# What kind of thing arrived. Not a status and not a lifecycle — how it reached the centre, which
# is what an operator needs to know before opening it.
SOURCE_TYPES: tuple[str, ...] = (
    "bank_portal_download",
    "bank_email_attachment",
    "branch_handover",
    "internal_reconstruction",
)

LINK_STATUSES: tuple[str, ...] = ("active", "replaced")
LINK_ACTIVE = "active"
LINK_REPLACED = "replaced"

# How somebody decided a bundle relates to a batch. The route to the belief, not a score: a link
# made because the bank file quotes an export reference is worth more than one made because an
# operator recognised a total, and a reader can only weigh that if the row says which.
LINK_METHODS: tuple[str, ...] = ("manual_selection", "export_reference", "bundle_note")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class BankResultBundle(Base):
    """One delivery of bank-returned evidence. §12.1."""

    __tablename__ = "bank_result_bundles"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    bundle_number: Mapped[str] = mapped_column(String(64), nullable=False)

    # Nullable, and Q-5 records why: a bundle can arrive before anybody has established which bank
    # sent it. Filled from a batch link when one supplies it.
    bank_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bank_profiles.id", name="fk_bundles_bank_profile"),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)

    uploaded_by_admin_user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_bundles_uploaded_by"),
        nullable=False,
    )
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # §12.1's three cached counts. Recomputed, never incremented.
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resolved_segment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unresolved_segment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    record_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)

    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_bundles_closed_by"),
        nullable=True,
    )

    created_at: Mapped[datetime] = created_at_column()
    # `now()` here as well as on `created_at`, because every row starts unmodified and an
    # `updated_at` that could be NULL is one every reader has to special-case.
    updated_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint("bundle_number", name="uq_bundles_bundle_number"),
        named_check(f"status IN ({_quoted(BUNDLE_STATUSES)})", name="status_value"),
        named_check("segment_count >= 0", name="segment_count_non_negative"),
        named_check("resolved_segment_count >= 0", name="resolved_count_non_negative"),
        named_check("unresolved_segment_count >= 0", name="unresolved_count_non_negative"),
        # Not in §12.1. Added because `:1179` says the three are one fact counted three ways, and
        # a CHECK is the only place that holds for every writer including a future one.
        named_check(
            "resolved_segment_count + unresolved_segment_count = segment_count",
            name="counts_reconcile",
        ),
        # A closed bundle has both closing facts; nothing else has either. The separation shape M7
        # slice 1 used for `batch_approvals`, which is a CHECK on one row precisely because a CHECK
        # cannot reach another table.
        named_check(
            "(status = 'closed' AND closed_at IS NOT NULL AND closed_by_admin_user_id IS NOT NULL)"
            " OR "
            "(status <> 'closed' AND closed_at IS NULL AND closed_by_admin_user_id IS NULL)",
            name="closed_requires_closer",
        ),
        Index(
            "idx_bundle_review_queue",
            "status",
            "uploaded_at",
            postgresql_where=(
                "status IN ('ready_for_manual_review','partially_matched','failed')"
            ),
        ),
    )


class BankResultBundleFile(Base):
    """One file inside a bundle, at one position, in one role. §12.2.

    **No UPDATE grant at all**, which is the point: none of those three facts can change. A file
    that turns out to belong elsewhere is a row to remove, not a row to edit.
    """

    __tablename__ = "bank_result_bundle_files"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    bank_result_bundle_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bank_result_bundles.id", name="fk_bundle_files_bundle"),
        nullable=False,
    )
    # M4's file. A bundle file is a *link* to an uploaded object, never a copy —
    # `08_Bank_File_and_Result_Processing.md:137` forbids overwriting an original, and the cheapest
    # way to honour that is never to have a second copy to confuse it with.
    file_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("file_objects.id", name="fk_bundle_files_file"),
        nullable=False,
    )

    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    file_role: Mapped[str] = mapped_column(String(32), nullable=False)

    # Nullable: meaningful for a PDF, not for a spreadsheet, and only slice 5 can measure it.
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint("bank_result_bundle_id", "file_id", name="uq_bundle_files_file"),
        # Both, and they are not redundant. The first stops one file being attached twice; the
        # second stops two files claiming one position *in the same role*, while leaving a source
        # and its preview free to share a sequence number. §12.2 states both.
        UniqueConstraint(
            "bank_result_bundle_id",
            "sequence_number",
            "file_role",
            name="uq_bundle_files_sequence_in_role",
        ),
        named_check("sequence_number > 0", name="sequence_positive"),
        named_check(f"file_role IN ({_quoted(FILE_ROLES)})", name="role_value"),
        named_check("page_count IS NULL OR page_count > 0", name="page_count_positive"),
    )


class BankResultBundleBatchLink(Base):
    """An operational belief that a bundle relates to a batch. §12.3.

    **Read the class docstring above about what this is not.** There is no amount here, no
    `confirmed_at`, and no attempt reference, because §12.3 says this association "does not prove
    payment completion" — and a column that could be mistaken for proof would make that sentence
    false no matter what any comment said.
    """

    __tablename__ = "bank_result_bundle_batch_links"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    bank_result_bundle_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bank_result_bundles.id", name="fk_bundle_links_bundle"),
        nullable=False,
    )
    payment_batch_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("payment_batches.id", name="fk_bundle_links_batch"),
        nullable=False,
    )
    # Nullable per §12.3: naming the batch without committing to a version is the honest record
    # when somebody recognises a batch number and cannot tell which version produced the file.
    payment_batch_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("payment_batch_versions.id", name="fk_bundle_links_version"),
        nullable=True,
    )

    link_method: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    created_by_admin_user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_bundle_links_created_by"),
        nullable=False,
    )
    created_at: Mapped[datetime] = created_at_column()
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        named_check(f"link_method IN ({_quoted(LINK_METHODS)})", name="method_value"),
        named_check(f"status IN ({_quoted(LINK_STATUSES)})", name="status_value"),
        named_check(
            "(status = 'replaced' AND replaced_at IS NOT NULL)"
            " OR "
            "(status = 'active' AND replaced_at IS NULL)",
            name="replaced_requires_timestamp",
        ),
        # One *active* link per pair; a replaced row stays and is outside the predicate. §12.3's
        # `replaced_at` is only useful if the old row survives to carry it.
        Index(
            "uq_bundle_links_active_pair",
            "bank_result_bundle_id",
            "payment_batch_id",
            unique=True,
            postgresql_where="status = 'active'",
        ),
        Index("idx_bundle_links_by_batch", "payment_batch_id", "status"),
    )
