"""The smallest unit of evidence. `04_Database_Schema.md` §12.4.

M8 slice 2. §12.4 calls this "the smallest evidence unit, including a Phase 1A manual crop", and
the table's whole purpose is that a segment can be **rebuilt from its own row**.

**That is why `rotation_degrees` exists here and not in document 04.** DOC-CONFLICT-057:
`08_Bank_File_and_Result_Processing.md:989` and `:1011` require it in the crop input and in stored
provenance, `15_Agent_Implementation_Plan.md:1044` requires it validated, and document 05's request
body and §12.4's column list both omit it. Rotation is a preview control, so coordinates drawn
after straightening a scan are normalized against the rotated page — without the angle the same
four numbers describe a different region of the same file.

**Provenance is unwritable, not merely write-protected-after-finalization.**
`05_API_Specification.md:1795` says provenance and source coordinates cannot be rewritten after
finalization; `20260824_0024` grants UPDATE on neither, at any time. A rectangle that could move
would retroactively falsify every reproduction claim already made from it, and there is no moment
at which that is acceptable. What a person may correct is the extracted fields — the values they
typed in — and the worker may fill `segment_file_id` once.

**A segment awaiting its crop rests in `created`.** Q-2. The catalogue's `processing` is an
unresolved alias, not a canonical state, so the *job* carries the render's progress and this row
says only that it exists. `segment_file_id IS NULL` is what "no active evidence" means, which is
how `15_Agent_Implementation_Plan.md:1069`'s "failed render leaves no active evidence" is checkable.
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
    Integer,
    Numeric,
    SmallInteger,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, named_check, uuid_primary_key

# `status_catalog.yaml`'s `receipt_segment` aggregate, all seven, in its order. `processing` and
# `archived` are unresolved aliases there and neither is admitted; the status-drift gate holds this
# CHECK to the aggregate exactly.
SEGMENT_STATUSES: tuple[str, ...] = (
    "created",
    "unmatched",
    "candidate_found",
    "confirmed_linked",
    "published",
    "superseded",
    "voided",
)

SEGMENT_CREATED = "created"
SEGMENT_UNMATCHED = "unmatched"

# The statuses that count as *resolved* for §12.1's cached counts.
#
# `confirmed_linked` and `published` are the two where somebody has decided what the evidence
# means; `voided` and `superseded` are resolved in the sense that they need no further work.
# `created`, `unmatched` and `candidate_found` are the queue — a bundle with any of them is not
# finished, which is what `close_bundle` refuses on.
#
# M9 owns `confirmed_linked` and `published`; naming them here is what lets slice 1's `recount`
# stop being a function that returns zeros.
RESOLVED_SEGMENT_STATUSES: tuple[str, ...] = (
    "confirmed_linked",
    "published",
    "superseded",
    "voided",
)

# §12.4 at `:1249`, verbatim and in its order.
CREATION_METHODS: tuple[str, ...] = (
    "manual_external_attachment",
    "manual_in_panel_crop",
    "manual_structured_result",
    "excel_row_import",
    "ai_auto_segmentation",
)

# The one slice 2 can reach. `:1259` makes `manual_in_panel_crop` Phase 1A too — slice 4 builds it
# — and keeps `ai_auto_segmentation` feature-flagged, which slice 7 asserts is unreachable.
METHOD_EXTERNAL = "manual_external_attachment"
METHOD_CROP = "manual_in_panel_crop"
METHOD_AI = "ai_auto_segmentation"

# The four angles `08_Bank_File_and_Result_Processing.md:985`'s preview can produce.
ROTATIONS: tuple[int, ...] = (0, 90, 180, 270)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class ReceiptSegment(Base):
    """One piece of evidence: a whole attached file, or a rectangle cut out of a page."""

    __tablename__ = "receipt_segments"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    # Both nullable: §12.4 says "Standalone evidence allowed". Slice 2's routes always supply a
    # bundle; the columns stay honest about the table's contract rather than about this slice.
    bank_result_bundle_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bank_result_bundles.id", name="fk_segments_bundle"),
        nullable=True,
    )
    bank_result_bundle_file_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bank_result_bundle_files.id", name="fk_segments_bundle_file"),
        nullable=True,
    )

    source_file_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("file_objects.id", name="fk_segments_source_file"),
        nullable=False,
    )
    # NULL until slice 4's worker renders it. This being NULL is what "no active evidence" means.
    segment_file_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("file_objects.id", name="fk_segments_segment_file"),
        nullable=True,
    )

    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Normalized 0..1 as `NUMERIC(10,6)`, never float. `MONEY_TIME_CONTRACT.md` is about money, but
    # the reason is the same one: a value that must reproduce a rectangle exactly cannot be stored
    # in a type whose arithmetic depends on the platform.
    bbox_x: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    bbox_y: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    bbox_width: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    bbox_height: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)

    # DOC-CONFLICT-057. See the module docstring.
    rotation_degrees: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    source_pixel_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_pixel_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    renderer_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    creation_method: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    # What a person typed, or what a later phase extracted. The only mutable content on the row.
    extracted_beneficiary_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extracted_destination_iban: Mapped[str | None] = mapped_column(String(26), nullable=True)
    extracted_amount_irr: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    extracted_tracking_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    extracted_payment_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    raw_extraction: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    extraction_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)

    created_by_actor_type: Mapped[str] = mapped_column(String(24), nullable=False)
    created_by_actor_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True
    )

    record_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        named_check("page_number IS NULL OR page_number > 0", name="page_number_positive"),
        named_check(
            "extracted_amount_irr IS NULL OR extracted_amount_irr > 0", name="amount_positive"
        ),
        named_check(
            "extraction_confidence IS NULL OR "
            "(extraction_confidence >= 0 AND extraction_confidence <= 1)",
            name="confidence_in_range",
        ),
        # §12.4's own CHECK. The all-null branch is `manual_external_attachment`: a whole file as
        # evidence, with no rectangle, which is a complete record and not a partial one.
        named_check(
            "(bbox_x IS NULL AND bbox_y IS NULL AND bbox_width IS NULL AND bbox_height IS NULL)"
            " OR "
            "(bbox_x >= 0 AND bbox_y >= 0 AND bbox_width > 0 AND bbox_height > 0"
            " AND bbox_x + bbox_width <= 1"
            " AND bbox_y + bbox_height <= 1)",
            name="bbox_normalized_or_absent",
        ),
        # §12.4's CHECK accepts three coordinates and a NULL fourth: the all-null branch is false,
        # the in-bounds branch is NULL because `bbox_height > 0` is NULL, and `false OR NULL` is
        # NULL — which a CHECK accepts. A check whose input is incomplete passes, in three-valued
        # logic. `num_nonnulls` cannot be NULL, so this one is decidable. Q-11.
        named_check(
            "num_nonnulls(bbox_x, bbox_y, bbox_width, bbox_height) IN (0, 4)",
            name="bbox_is_all_or_nothing",
        ),
        named_check(
            f"rotation_degrees IN ({', '.join(str(angle) for angle in ROTATIONS)})",
            name="rotation_is_a_right_angle",
        ),
        # Not in §12.4. A rectangle without its page reproduces nothing, and a rotation without a
        # rectangle describes nothing — both would be provenance that cannot do its one job.
        named_check("bbox_x IS NULL OR page_number IS NOT NULL", name="rectangle_needs_a_page"),
        named_check(
            "rotation_degrees = 0 OR bbox_x IS NOT NULL", name="rotation_needs_a_rectangle"
        ),
        named_check(
            f"creation_method IN ({_quoted(CREATION_METHODS)})", name="creation_method_value"
        ),
        named_check(f"status IN ({_quoted(SEGMENT_STATUSES)})", name="status_value"),
        # §12.4's predicate verbatim, `needs_review` included — a status the catalogue does not
        # have and `status_value` therefore forbids, so that disjunct can never match. Copied
        # rather than trimmed: a narrower predicate would be a differently-scoped index wearing the
        # document's name. Q-10, and the migration says more.
        Index(
            "idx_segment_match_amount_iban",
            "extracted_amount_irr",
            "extracted_destination_iban",
            postgresql_where="status IN ('unmatched','candidate_found','needs_review')",
        ),
        Index("idx_segments_by_bundle", "bank_result_bundle_id", "status"),
    )
