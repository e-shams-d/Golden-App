"""The bank file, as a record. `04_Database_Schema.md` §11.8.

M7 slice 2. One table for both kinds of artifact, which is document 04's design and not an
economy: a preview and a final export are the *same rendering of the same version*, and the
difference between them is who may act on the result. Two tables would have made "is this file
the one that was approved" a question you answer differently depending on where you looked.

**`export_type` is the whole safety property and it is never grantable.**
`FINANCIAL_INTEGRITY_BASELINE.md` §1 forbids promoting preview output into a final artifact by
mutating it. The enforcement is not a rule in a command — it is the absence of an UPDATE grant on
this column, in this migration and in every migration after it. A later slice will need to write
`status`, `downloaded_at` and the two sent-to-bank columns; none of them will need `export_type`
or `batch_approval_id`, and granting either would make the baseline's prohibition a matter of
somebody remembering.

**The approval and the version are tied together by one composite key.** §11.8 states it:

    FOREIGN KEY (batch_approval_id, payment_batch_version_id)
        REFERENCES batch_approvals(id, payment_batch_version_id)

so a final export cannot cite an approval of a *different* version. `batch_approvals` grew
`uq_batch_approvals_version_pair` in slice 1 for exactly this reference, before there was
anything to reference it — document 04 named the pair and slice 1 created it rather than leaving
slice 2 to add a constraint to a table it does not own.

Under MATCH SIMPLE a foreign key with a NULL member is not enforced, which is what makes the same
key correct for a preview: a preview has no approval, and there is nothing to tie.
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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    created_at_column,
    named_check,
    uuid_primary_key,
)

# `status_catalog.yaml`'s `bank_export` aggregate, all eight, in its order.
#
# `05_API_Specification.md:536` lists a different five — it has `superseded`, which the catalogue
# does not, and `failed` where the catalogue says `generation_failed`. That is DOC-CONFLICT-016,
# already Open, and the catalogue wins because the status drift gate holds every enforced CHECK to
# its aggregate exactly. Document 05 is owed an editorial fix; G-3 records the one substantive
# part, which is whether an export can be `superseded` at all.
BANK_EXPORT_STATUSES: tuple[str, ...] = (
    "generating",
    "generated",
    "validated",
    "downloaded",
    "sent_to_bank_marked",
    "voided",
    "quarantined",
    "generation_failed",
)

# §11.8: "`preview`, `final`". Not a status and not a lifecycle — the *kind* of artifact, fixed at
# creation. `15_Agent_Implementation_Plan.md:936` requires a preview to be permanently
# identifiable as non-sendable, and permanence here is the absence of a grant.
EXPORT_TYPES: tuple[str, ...] = ("preview", "final")

EXPORT_PREVIEW = "preview"
EXPORT_FINAL = "final"

# The four states in which a final export still occupies its version, from §11.8's partial unique
# index. `voided`, `quarantined` and `generation_failed` are deliberately outside it: a voided
# export must not block the replacement that voided it, and a failed generation must not stop the
# next attempt.
ACTIVE_FINAL_STATUSES: tuple[str, ...] = (
    "generated",
    "validated",
    "downloaded",
    "sent_to_bank_marked",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class BankExcelExport(Base):
    """One rendering of one version — preview or final. §11.8."""

    __tablename__ = "bank_excel_exports"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    payment_batch_version_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("payment_batch_versions.id", name="fk_bank_exports_version"),
        nullable=False,
    )

    # §11.8: "conditional — Required for final". NULL for a preview, and the CHECK below is what
    # makes that true rather than this comment.
    batch_approval_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True
    )

    # The two configuration versions the file was rendered under. Both NOT NULL: an export that
    # cannot say which mapping produced it cannot be re-rendered, and
    # `FINANCIAL_INTEGRITY_BASELINE.md` §1 requires exactly that of a final artifact.
    bank_profile_version_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bank_profile_versions.id", name="fk_bank_exports_profile_version"),
        nullable=False,
    )
    bank_mapping_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bank_mappings.id", name="fk_bank_exports_mapping"),
        nullable=False,
    )

    # M4's storage. NOT NULL, and §1 is emphatic about why: "No placeholder file, hash or
    # timestamp is permitted." A row here means a file exists and verified.
    file_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("file_objects.id", name="fk_bank_exports_file"),
        nullable=False,
    )

    export_number: Mapped[str] = mapped_column(String(64), nullable=False)
    export_type: Mapped[str] = mapped_column(String(16), nullable=False)

    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount_irr: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Two different hashes, and conflating them is the mistake worth naming. `content_hash` is the
    # hash of the *normalised content* — the same value the version carries, so an export can be
    # compared to the version it claims to render. `file_sha256_hash` is the hash of the bytes on
    # disk, which changes if the writer's output changes for any reason at all. §11.8's own
    # integrity checks compare the first against the version; the second answers "is this the file
    # we wrote".
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False)

    generated_by_admin_user_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_bank_exports_generated_by"),
        nullable=False,
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # `15_Agent_Implementation_Plan.md:989`: "Downloading does not mean sent." Two separate
    # nullable columns rather than one lifecycle timestamp, because the gap between them is the
    # milestone's central human-factors risk — an accountant who downloads a file and emails it
    # without marking it sent leaves the system believing the payment was never made.
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_to_bank_marked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_to_bank_marked_by_admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("admin_users.id", name="fk_bank_exports_sent_by"),
        nullable=True,
    )

    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        named_check(f"export_type IN ({_quoted(EXPORT_TYPES)})", name="export_type_value"),
        named_check(f"status IN ({_quoted(BANK_EXPORT_STATUSES)})", name="status_value"),
        named_check("row_count > 0", name="row_count_positive"),
        named_check("total_amount_irr > 0", name="total_positive"),
        # §11.8 verbatim. A preview that carried an approval would look like a final export to
        # anything that read the column, and a final export without one could not prove which
        # decision authorised it.
        named_check(
            "(export_type = 'preview' AND batch_approval_id IS NULL)"
            " OR "
            "(export_type = 'final' AND batch_approval_id IS NOT NULL)",
            name="approval_matches_type",
        ),
        named_check("content_hash ~ '^[0-9a-f]{64}$'", name="content_hash_is_lowercase_hex"),
        named_check("file_sha256_hash ~ '^[0-9a-f]{64}$'", name="file_hash_is_lowercase_hex"),
        # The pair `batch_approvals` was given `uq_batch_approvals_version_pair` for. A final
        # export cannot cite an approval belonging to a different version.
        ForeignKeyConstraint(
            ["batch_approval_id", "payment_batch_version_id"],
            ["batch_approvals.id", "batch_approvals.payment_batch_version_id"],
            name="fk_export_approval_same_version",
        ),
        UniqueConstraint("export_number", name="uq_bank_exports_export_number"),
        # §11.8's partial unique index. One *active* final export per version — previews are
        # outside the predicate entirely, so a version may be previewed as often as somebody
        # wants without ever being able to have two live final files.
        Index(
            "uq_active_final_export_per_version",
            "payment_batch_version_id",
            unique=True,
            postgresql_where=(
                "export_type = 'final' AND status IN (" + _quoted(ACTIVE_FINAL_STATUSES) + ")"
            ),
        ),
        Index("idx_bank_exports_by_version", "payment_batch_version_id", "export_type"),
    )
