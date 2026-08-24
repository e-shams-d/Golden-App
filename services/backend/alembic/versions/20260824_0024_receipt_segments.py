"""The smallest unit of evidence. `04_Database_Schema.md` §12.4.

M8 slice 2. Twenty-five columns, §12.4's own CHECK verbatim, and one column document 04 does not
list.

**`rotation_degrees` is added on document 08's authority, and it is DOC-CONFLICT-057.**
`08_Bank_File_and_Result_Processing.md:989` puts `rotation_degrees` in the crop input and `:1011`
lists it among the provenance a manual crop stores; `15_Agent_Implementation_Plan.md:1044` requires
crop creation to validate it. `05_API_Specification.md:1756`'s request body omits it and §12.4's
column list has no place for it.

Without it a crop is **not reproducible from its own provenance**, which is the one property this
table exists to have: rotation is a preview control (`08:985`), so an operator straightening a
sideways scan and then drawing a rectangle produces coordinates normalized against the *rotated*
page. Store the four numbers alone and the same record describes a different region of the same
file — and the derived file still looks right on screen, so the loss only surfaces when somebody
tries to verify the evidence, which is exactly when evidence matters.

The precedent is DOC-CONFLICT-055's: M6 added `payment_batch_versions.finalized_by_admin_user_id`
on an approved baseline's authority against a silent document 04, recorded as a named deviation so
it could not spread or be mistaken for a transcription error. `NOT NULL DEFAULT 0` because an
unrotated page is the overwhelming majority and `NULL` would mean "unknown rotation", which is the
one thing a reproduction record must never say.

**The bbox CHECK is §12.4's, character for character**, including the all-null branch. That branch
is not a loophole: `manual_external_attachment` attaches a whole file as evidence and has no
rectangle, so a segment with no coordinates is a real and complete record rather than a partial one.

**Grants: `status`, the extracted fields, `segment_file_id` and `record_version`.** Not
`source_file_id`, not the four bbox columns, not `rotation_degrees`, not `creation_method`, not
`renderer_version`, and not the two source pixel dimensions. `05_API_Specification.md:1795` says
provenance and source coordinates "cannot be rewritten after finalization" and a replacement
segment is created instead — this migration makes them unwritable *at any time*, which is stronger
and simpler: a rectangle that could move would make every earlier reproduction claim false
retroactively, and there is no moment at which that is acceptable.

`segment_file_id` is writable because the crop worker fills it after the row exists —
`08:1031` creates the segment before the file, which is slice 4's whole shape.

Revision ID: 20260824_0024
Revises: 20260823_0023
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0024"
down_revision: str | Sequence[str] | None = "20260823_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `status_catalog.yaml`'s `receipt_segment` aggregate, all seven, in its order. `processing` and
# `archived` are recorded there as unresolved aliases and neither is admitted: Q-2 explains why a
# segment awaiting its render rests in `created` and the *job* carries the progress.
SEGMENT_STATUSES = (
    "created",
    "unmatched",
    "candidate_found",
    "confirmed_linked",
    "published",
    "superseded",
    "voided",
)

# §12.4 at `:1249`, verbatim. `manual_in_panel_crop` is Phase 1A per `:1259`;
# `ai_auto_segmentation` stays feature-flagged and no route this milestone adds can reach it.
CREATION_METHODS = (
    "manual_external_attachment",
    "manual_in_panel_crop",
    "manual_structured_result",
    "excel_row_import",
    "ai_auto_segmentation",
)

# What a person may correct after the fact, plus the file the worker attaches and the row's own
# version. Everything else on this table is provenance and is frozen at insert.
GRANTED_COLUMNS = (
    "status",
    "segment_file_id",
    "extracted_beneficiary_name",
    "extracted_destination_iban",
    "extracted_amount_irr",
    "extracted_tracking_number",
    "extracted_payment_at",
    "raw_extraction",
    "extraction_confidence",
    "record_version",
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
        "receipt_segments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Both nullable: §12.4 says "Standalone evidence allowed", so a segment may exist without a
        # bundle at all. Slice 2's routes always supply one; the column stays honest about the
        # table's own contract rather than about this slice's callers.
        sa.Column(
            "bank_result_bundle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bank_result_bundles.id", name="fk_segments_bundle"),
            nullable=True,
        ),
        sa.Column(
            "bank_result_bundle_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bank_result_bundle_files.id", name="fk_segments_bundle_file"),
            nullable=True,
        ),
        # Required. The original page this evidence came from, and the thing
        # `08_Bank_File_and_Result_Processing.md:137` forbids overwriting.
        sa.Column(
            "source_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("file_objects.id", name="fk_segments_source_file"),
            nullable=False,
        ),
        # The derived crop. NULL until the worker renders it, which is why Q-2 leaves a pending
        # segment in `created` — this column being NULL is what "no active evidence" means.
        sa.Column(
            "segment_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("file_objects.id", name="fk_segments_segment_file"),
            nullable=True,
        ),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("bbox_x", sa.Numeric(10, 6), nullable=True),
        sa.Column("bbox_y", sa.Numeric(10, 6), nullable=True),
        sa.Column("bbox_width", sa.Numeric(10, 6), nullable=True),
        sa.Column("bbox_height", sa.Numeric(10, 6), nullable=True),
        # DOC-CONFLICT-057. See the module docstring: two documents require this value and two have
        # nowhere to put it, and without it a rotated crop cannot be rebuilt from its own record.
        sa.Column(
            "rotation_degrees",
            sa.SmallInteger(),
            nullable=False,
        ),
        sa.Column("source_pixel_width", sa.Integer(), nullable=True),
        sa.Column("source_pixel_height", sa.Integer(), nullable=True),
        sa.Column("renderer_version", sa.String(64), nullable=True),
        sa.Column("creation_method", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("extracted_beneficiary_name", sa.String(255), nullable=True),
        sa.Column("extracted_destination_iban", sa.String(26), nullable=True),
        sa.Column("extracted_amount_irr", sa.BigInteger(), nullable=True),
        sa.Column("extracted_tracking_number", sa.String(128), nullable=True),
        sa.Column("extracted_payment_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "raw_extraction",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("extraction_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("created_by_actor_type", sa.String(24), nullable=False),
        sa.Column("created_by_actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("record_version", sa.BigInteger(), nullable=False),
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
        sa.CheckConstraint("page_number IS NULL OR page_number > 0", name="page_number_positive"),
        sa.CheckConstraint(
            "extracted_amount_irr IS NULL OR extracted_amount_irr > 0", name="amount_positive"
        ),
        sa.CheckConstraint(
            "extraction_confidence IS NULL OR "
            "(extraction_confidence >= 0 AND extraction_confidence <= 1)",
            name="confidence_in_range",
        ),
        # §12.4's CHECK, character for character. The all-null branch is what makes
        # `manual_external_attachment` a complete record rather than a partial one.
        sa.CheckConstraint(
            "(bbox_x IS NULL AND bbox_y IS NULL AND bbox_width IS NULL AND bbox_height IS NULL)"
            " OR "
            "(bbox_x >= 0 AND bbox_y >= 0 AND bbox_width > 0 AND bbox_height > 0"
            " AND bbox_x + bbox_width <= 1"
            " AND bbox_y + bbox_height <= 1)",
            name="bbox_normalized_or_absent",
        ),
        # **§12.4's CHECK admits a partial rectangle, and this is the constraint that closes it.**
        #
        # Found by testing that CHECK at its edges. Set three coordinates and leave the fourth
        # NULL: the all-null branch is false, and the in-bounds branch contains `bbox_height > 0`,
        # which is NULL rather than false. `false OR NULL` is NULL — and **a CHECK constraint
        # accepts NULL**, because SQL only rejects on false. So a row claiming three quarters of a
        # rectangle satisfies the documented constraint exactly as written.
        #
        # That row would sit in the table looking like a crop and be impossible to reproduce, which
        # is the one thing this table exists to prevent. `num_nonnulls` is exact and cannot be NULL,
        # so this branch is decidable where the documented one is not.
        #
        # This is the familiar shape in three-valued logic: a check whose input is incomplete
        # passes. Document 04 is owed the correction; Q-11 records it.
        sa.CheckConstraint(
            "num_nonnulls(bbox_x, bbox_y, bbox_width, bbox_height) IN (0, 4)",
            name="bbox_is_all_or_nothing",
        ),
        # DOC-CONFLICT-057's other half. Only the four angles document 08's preview can produce
        # (`:985` gives clockwise and counter-clockwise rotation), so a value nothing could have
        # created cannot be stored and then cited as provenance.
        sa.CheckConstraint(
            "rotation_degrees IN (0, 90, 180, 270)", name="rotation_is_a_right_angle"
        ),
        # A rectangle is meaningless without the page it is on, and a rotation is meaningless
        # without a rectangle. Not in §12.4, and added for the reason the docstring gives: this
        # table's purpose is reproduction, and a partial coordinate set reproduces nothing.
        sa.CheckConstraint(
            "bbox_x IS NULL OR page_number IS NOT NULL", name="rectangle_needs_a_page"
        ),
        sa.CheckConstraint(
            "rotation_degrees = 0 OR bbox_x IS NOT NULL", name="rotation_needs_a_rectangle"
        ),
        sa.CheckConstraint(
            f"creation_method IN ({_quoted(CREATION_METHODS)})", name="creation_method_value"
        ),
        sa.CheckConstraint(f"status IN ({_quoted(SEGMENT_STATUSES)})", name="status_value"),
    )

    # §12.4's own index at `04_Database_Schema.md:1670-1672`, for the matching M9 will do — with
    # its partial predicate copied exactly, including a status the catalogue does not have.
    #
    # **`needs_review` is not a `receipt_segment` state.** The catalogue's aggregate holds
    # `created`,
    # `unmatched`, `candidate_found`, `confirmed_linked`, `published`, `superseded` and `voided`,
    # and
    # records `processing` and `archived` as unresolved aliases. `needs_review` appears in neither
    # list, so `ck_receipt_segments_status_value` makes it unreachable and this disjunct can never
    # match a row.
    #
    # It is written anyway, and that is deliberate. Dropping it would make the index a
    # differently-scoped object wearing the document's name — which is the failure
    # `test_schema_matches_the_specification.py` exists to catch, and it says so in those words.
    # Copying the predicate keeps the divergence **visible in the schema** rather than hidden in a
    # test exemption: the day M0 either adds the state or corrects the document, this line is where
    # somebody looks. Q-10 records it. The index covers exactly the rows §12.4 intends; the extra
    # literal costs one comparison Postgres never performs.
    op.create_index(
        "idx_segment_match_amount_iban",
        "receipt_segments",
        ["extracted_amount_irr", "extracted_destination_iban"],
        postgresql_where=sa.text(
            "status IN ('unmatched','candidate_found','needs_review')"
        ),
    )
    op.create_index(
        "idx_segments_by_bundle",
        "receipt_segments",
        ["bank_result_bundle_id", "status"],
    )

    bind = op.get_bind()
    columns = ", ".join(GRANTED_COLUMNS)
    for role in _runtime_roles():
        bind.execute(
            sa.text(f'GRANT UPDATE ({columns}) ON public."receipt_segments" TO "{role}"')
        )


def downgrade() -> None:
    op.drop_index("idx_segments_by_bundle", table_name="receipt_segments")
    op.drop_index("idx_segment_match_amount_iban", table_name="receipt_segments")
    op.drop_table("receipt_segments")
