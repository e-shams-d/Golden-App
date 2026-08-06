"""File metadata, attachments and derivations. Metadata only — no bytes here.

This is the one M2 table the dependency graph feeds directly: M4 processes files,
M8 attaches them to bank results, M9 publishes them, and all three reference a
`FileObject` that must not change shape underneath them. So the columns that look
premature — checksum, quarantine, retention, legal hold — are here in the first
migration rather than added later, because the required duplicate-checksum and
suspicious-scanner fixtures are otherwise unrepresentable and the reconciliation
queries unwritable.

**`storage_key` is server-generated and never a client contract.** A caller
supplies a filename; the server decides where the bytes live. A key that a client
could predict or supply is a path-traversal surface and an enumeration surface at
once, and ADR-003 leaves the provider free — so a local-filesystem key format must
not leak into the API either, or moving to object storage becomes a breaking
change.

**`mime_type_declared` and `mime_type_detected` are separate columns**, never
reconciled into one. The declared value is what the uploader claimed and the
detected value is what the bytes are; a mismatch is exactly the signal the
extension/MIME-mismatch fixture exists to exercise. Storing one column would
require choosing which to keep, and both choices destroy the comparison.

**`size_bytes >= 0`, not `> 0`.** An empty file is a real thing that a caller can
upload, and refusing it at the database boundary would turn a validation problem
into a constraint violation with no useful message. This is deliberately *not* the
money convention, where zero is usually a defect.

Two conditional constraints carry the weight of this slice:

`available_requires_hash` — doc 04 states the checksum is "required before
`available`" and gives no constraint, so without this the rule lives only in
application code, and the first code path that forgets it produces a file serving
as evidence with nothing to verify it against.

`available_requires_clean_scan` — a file whose scan is not clean cannot reach
`available` **at the database boundary**. This is stricter than any candidate
`scan_status` enum, in the direction ADR-008's safe default requires: never treat
an unchecked file as available evidence. It is written as a whitelist of the one
scan value that permits availability rather than as a blacklist of the values that
do not, so a scan status nobody has thought of yet fails closed instead of open.

**There is no `deleted_at` and no soft-delete mixin.** `archived_at` and
`physically_deleted_at` are specific, named states with specific meanings, and
nothing in M2 sets the second one — ADR-005 is open, so the retention process that
would is not written. `tests/backend/test_no_deletion_machinery.py` enforces that
across the whole package.

**`file_links` is scoped to non-critical attachments and must not be promoted.**
Critical financial relationships use explicit foreign keys. A reusable generic
polymorphic link primitive would let a mutable direct reference become the sole
source of a financial history, which is precisely the prohibition. Supersession is
`replaced_at`/`replaced_by_file_link_id`, never a delete, so the chain of what was
attached when survives the replacement.

**`file_derivations` is unique over a canonical `parameters_hash`, not raw JSONB.**
A unique index over a JSONB column treats `{"x":1,"y":2}` and `{"y":2,"x":1}` as
different derivations, so crop and preview reproducibility would silently depend
on dict ordering and on how a Persian filename happened to be spelled.
`app.core.hashing.parameters_hash` is the sanctioned alternative and its output
form is enforced by a constraint here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, named_check, updated_at_column, uuid_primary_key

# Seven of the eight spellings `status_catalog.yaml` records for `file_object`.
#
# The catalogue sets `canonical: null` and forbids canonicalising `deleted` against
# `deleted_by_policy`, and this CHECK does not: it keeps `deleted` and simply does
# not permit `deleted_by_policy`, because the only writer of that value would be a
# policy-driven deletion, and ADR-005 is open so no such process exists or may be
# written. Refusing a value whose sole author is prohibited is not the same as
# deciding that the two words mean one thing.
#
# When ADR-005 lands, permitting it takes a visible widening migration — which is
# the right amount of friction for the state that means "a policy erased this".
STORAGE_STATUSES: tuple[str, ...] = (
    "pending",
    "quarantined",
    "available",
    "processing_failed",
    "archived",
    "retention_pending",
    "deleted",
)

# The one scan outcome that permits availability. A whitelist, so an outcome
# nobody has enumerated yet cannot make a file available by default.
CLEAN_SCAN_STATUS = "clean"

# Reserved while ADR-008 is Open: recordable, so a genuine skip is not lost, but
# it can never yield availability — the constraint above sees to that — and no
# code path may set it. `tests/backend/test_reserved_scan_status.py` enforces the
# second half, because a skip that application code can produce is a skip that
# happens implicitly.
RESERVED_SCAN_STATUS = "skipped_by_approved_policy"

# The column name is itself the enumeration, which is why a CHECK here decides
# nothing that is open.
FILE_RELATIONS: tuple[str, ...] = ("original", "derived")

ACTOR_TYPES: tuple[str, ...] = (
    "trader_user",
    "admin_user",
    "system_worker",
    "system_maintenance",
)

# Raw lower-case hex, matching `idempotency_records.request_hash` and the audit
# hash columns. Distinct from `parameters_hash` below, which is the versioned
# canonical form.
_SHA256_HEX = "^[0-9a-f]{64}$"

# `v1:<sha256 hex>`, the output of `app.core.hashing.parameters_hash`. The pattern
# admits a future `v2:` without a migration, and refuses both a bare digest and a
# JSON dump — either of which would reintroduce the ordering fragility the
# canonical form exists to remove.
_VERSIONED_DIGEST = "^v[0-9]+:[0-9a-f]{64}$"


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class FileObject(Base):
    __tablename__ = "file_objects"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    # ADR-003 leaves the provider free, so the triple is the address and none of
    # its three parts assumes a filesystem.
    storage_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    storage_bucket: Mapped[str] = mapped_column(String(120), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)

    # For display only. Sanitised on the way in; never used to build a path.
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)

    # Never reconciled into one column. The comparison is the signal.
    mime_type_declared: Mapped[str] = mapped_column(String(160), nullable=False)
    mime_type_detected: Mapped[str | None] = mapped_column(String(160), nullable=True)

    # `>= 0`: an empty upload is a real thing, not a defect.
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Nullable until the bytes have been read, and required before `available` by
    # the conditional constraint below.
    sha256_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # No value CHECK on any of the four below: no approved catalogue enumerates
    # them, and inventing a set here would decide questions this slice is not
    # allowed to decide. POL-006 also puts file limits in configuration rather
    # than in a constraint, so nothing about size or type is fixed here.
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    visibility_scope: Mapped[str] = mapped_column(String(60), nullable=False)
    retention_class: Mapped[str | None] = mapped_column(String(80), nullable=True)
    legal_hold_state: Mapped[str | None] = mapped_column(String(40), nullable=True)

    storage_status: Mapped[str] = mapped_column(String(32), nullable=False)

    # No value CHECK. DOC-CONFLICT-029 and ADR-008 are both Open, and enumerating
    # the outcomes would resolve them from a migration. What is enforced instead
    # is the consequence: availability requires `clean`.
    scan_status: Mapped[str] = mapped_column(String(48), nullable=False)

    uploaded_by_actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Polymorphic and deliberately without a foreign key, like the audit actor: a
    # worker-created derivative has no row in either identity table.
    uploaded_by_actor_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True
    )

    # Structure only, per ADR-005 and OPS-005. Nothing reads either of these to
    # decide anything, and nothing acts on them.
    retention_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("retention_policies.id"), nullable=True
    )

    original_or_derived_relation: Mapped[str] = mapped_column(String(16), nullable=False)

    metadata_payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Retention process only, and no retention process exists.
    physically_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # The address is unique. Two rows claiming the same object is how a
        # duplicate write after a retry becomes two competing metadata records.
        UniqueConstraint(
            "storage_provider",
            "storage_bucket",
            "storage_key",
            name="uq_file_objects_storage_location",
        ),
        named_check(f"storage_status IN ({_quoted(STORAGE_STATUSES)})", name="storage_status"),
        named_check(
            f"original_or_derived_relation IN ({_quoted(FILE_RELATIONS)})",
            name="original_or_derived_relation",
        ),
        named_check(f"uploaded_by_actor_type IN ({_quoted(ACTOR_TYPES)})", name="actor_type"),
        # Zero is allowed. Negative is not a small file, it is a bug upstream.
        named_check("size_bytes >= 0", name="size_is_not_negative"),
        named_check("length(btrim(storage_key)) > 0", name="storage_key_not_blank"),
        named_check("length(btrim(original_filename)) > 0", name="original_filename_not_blank"),
        named_check(
            f"sha256_hash IS NULL OR sha256_hash ~ '{_SHA256_HEX}'",
            name="sha256_is_lowercase_hex",
        ),
        # FILE-META-002. Doc 04 states the rule in prose and gives no constraint.
        named_check(
            "storage_status <> 'available' OR sha256_hash IS NOT NULL",
            name="available_requires_hash",
        ),
        # FILE-META-003, and the reason this slice needs no `scan_status` enum.
        # A whitelist rather than a blacklist: an unrecognised scan outcome must
        # fail closed, and a blacklist would let it through.
        named_check(
            f"storage_status <> 'available' OR scan_status = '{CLEAN_SCAN_STATUS}'",
            name="available_requires_clean_scan",
        ),
        # A row cannot claim its bytes are gone while still offering them. Written
        # against `deleted` alone because that is the only deletion state the
        # status CHECK admits; widening one means widening both.
        named_check(
            "physically_deleted_at IS NULL OR storage_status = 'deleted'",
            name="physical_deletion_implies_deleted_status",
        ),
        # Doc 04's names, used verbatim, so an index this codebase creates and one
        # a reviewer looks for by name are the same index.
        Index("idx_file_objects_hash", "sha256_hash"),
        Index("idx_file_objects_status_category", "storage_status", "category"),
    )


class FileLink(Base):
    """A non-critical attachment of a file to some resource. Scoped on purpose.

    Polymorphic because attachments are genuinely open-ended — a note, a photo, a
    scanned letter — and because the alternative is a nullable foreign key column
    per attachable resource. That openness is also the danger, so this pattern
    stays here: a critical financial relationship gets its own explicit foreign
    key, and this table must not be promoted into a general link primitive.
    """

    __tablename__ = "file_links"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    file_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("file_objects.id"), nullable=False
    )

    # No foreign key, by definition: the resource may live in any of a dozen
    # tables, most of which do not exist yet.
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)

    # What the attachment is for. No value CHECK: the roles arrive with the
    # resources, and none of those is in this milestone.
    link_role: Mapped[str] = mapped_column(String(80), nullable=False)

    attached_by_actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    attached_by_actor_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=True
    )

    # Supersession, not deletion. The replaced row stays, so "what was attached to
    # this on the day it was approved" remains answerable afterwards.
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_file_link_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("file_links.id"), nullable=True
    )

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        named_check(f"attached_by_actor_type IN ({_quoted(ACTOR_TYPES)})", name="actor_type"),
        named_check("length(btrim(resource_type)) > 0", name="resource_type_not_blank"),
        # A replacement that does not say what replaced it is indistinguishable
        # from a deletion with extra steps.
        named_check(
            "(replaced_at IS NULL AND replaced_by_file_link_id IS NULL) "
            "OR (replaced_at IS NOT NULL AND replaced_by_file_link_id IS NOT NULL)",
            name="replacement_fields_move_together",
        ),
        named_check(
            "replaced_by_file_link_id IS NULL OR replaced_by_file_link_id <> id",
            name="replacement_is_not_self",
        ),
        # Partial, so superseded links leave the index rather than being filtered
        # out of every query that reads it.
        Index(
            "idx_file_links_active",
            "resource_type",
            "resource_id",
            "link_role",
            postgresql_where=text("replaced_at IS NULL"),
        ),
        Index("idx_file_links_file", "file_id"),
    )


class FileDerivation(Base):
    """A derived artifact and the exact inputs that produced it.

    The second unique constraint is the reproducibility claim: the same source,
    the same derivation type, the same parameters and the same renderer produce
    one row, so a crop or preview cannot exist twice with two different results.
    Over `parameters_hash` rather than raw JSONB, because a JSONB unique index
    would call two identical derivations different whenever a dict happened to
    serialise in another order.
    """

    __tablename__ = "file_derivations"

    id: Mapped[uuid.UUID] = uuid_primary_key()

    source_file_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("file_objects.id"), nullable=False
    )
    derived_file_id: Mapped[uuid.UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("file_objects.id"), nullable=False
    )

    derivation_type: Mapped[str] = mapped_column(String(60), nullable=False)

    # The canonical digest from `app.core.hashing.parameters_hash`.
    parameters_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    # Which code produced it. Two renderers can agree on parameters and disagree
    # on output, so a version change is a new derivation rather than a conflict.
    renderer_version: Mapped[str] = mapped_column(String(60), nullable=False)
    # The source's content digest at the moment of derivation. If the source is
    # ever re-uploaded, this says whether the derivative still matches it.
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_by_job_id: Mapped[uuid.UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("processing_jobs.id"), nullable=True
    )

    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint(
            "source_file_id",
            "derived_file_id",
            name="uq_file_derivations_source_derived",
        ),
        # The reproducibility unique. A differing renderer_version is a different
        # row, deliberately: it records that the output changed because the code
        # changed, which is the question an auditor asks.
        UniqueConstraint(
            "source_file_id",
            "derivation_type",
            "parameters_hash",
            "renderer_version",
            name="uq_file_derivations_reproducibility",
        ),
        named_check("source_file_id <> derived_file_id", name="derivation_is_not_self"),
        named_check(
            f"parameters_hash ~ '{_VERSIONED_DIGEST}'",
            name="parameters_hash_is_a_versioned_digest",
        ),
        named_check(f"source_hash ~ '{_SHA256_HEX}'", name="source_hash_is_lowercase_hex"),
        named_check("length(btrim(derivation_type)) > 0", name="derivation_type_not_blank"),
        named_check("length(btrim(renderer_version)) > 0", name="renderer_version_not_blank"),
        Index("idx_file_derivations_source", "source_file_id", "derivation_type"),
        Index("idx_file_derivations_derived", "derived_file_id"),
    )
