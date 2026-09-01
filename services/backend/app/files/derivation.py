"""Derived files, and the record of exactly what produced them.

`08_Bank_File_and_Result_Processing.md:431`: "A derivation stores source file, operation
type, parameters, renderer version, and checksums." That list is a reproducibility claim —
given the row, the same output can be produced again, or its difference explained.

**The derived file and its derivation row commit together or not at all.** A derived
`file_object` without a `file_derivations` row is an artifact nobody can account for: it
looks like evidence, and nothing says which document it came from or how. M2 wrote the
`derivatives_without_a_derivation` reconciliation check precisely to find that state, and
this module's job is to make it unreachable through the application rather than merely
detectable afterwards.

**`source_hash` is the source's digest at the moment of derivation**, not a copy of the
derived file's. If a source is ever replaced, that column is what says whether the
derivative still corresponds to it — which a crop shown to a trader as proof of payment
absolutely needs, and which the source's own current digest cannot answer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, BinaryIO, Final

from app.core.errors import BusinessRuleViolationError
from app.core.hashing import parameters_hash
from app.db.models.file_object import FileDerivation, FileObject
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.files.states import AVAILABLE, SCAN_CLEAN
from app.storage.interface import StorageBackend
from app.storage.keys import generate_storage_key

# `file_objects.original_or_derived_relation`. The model has no value CHECK, so the two
# spellings live here rather than being written out at each call site.
DERIVED: Final = "derived"

PREVIEW: Final = "preview"
NORMALIZED_PAGE: Final = "normalized_page"
CROP: Final = "crop"
# M9 slice 5B. The trader's result card, derived from the evidence crop it displays.
#
# **A fourth derivation type rather than an eighth upload purpose**, and that difference is what
# makes this an implementation decision rather than the owner's. `05_API_Specification.md:991-997`
# enumerates seven *upload* purposes and `FILE-PURPOSE-001` parses that list, so adding one means
# amending an approved contract — tried, and the gate refused it. A share card is not uploaded: the
# platform produces it, and `record_derivation` gives a derived file its **source's** category and
# visibility rather than a purpose of its own. So the card inherits the crop's
# `incoming_payment_receipt` and its `trader_visible_after_publication` scope, both already
# approved. M4's catalogue already describes this shape for the crop itself — "a different file
# with its own row".
#
# `08_Bank_File_and_Result_Processing.md:431` lists what a derivation *records* and enumerates no
# types, which is why this tuple is ours to extend and document 05's list is not.
SHARE_CARD: Final = "share_card"
DERIVATION_TYPES: Final = (PREVIEW, NORMALIZED_PAGE, CROP, SHARE_CARD)


@dataclass(frozen=True)
class DerivationRequest:
    """One derived artifact, and the inputs that account for it."""

    source_file_id: uuid.UUID
    derivation_type: str
    renderer_version: str
    parameters: dict[str, Any]
    media_type: str
    filename: str
    body: BinaryIO
    # Which job produced it, when a job did. `08_Bank_File_and_Result_Processing.md:431` counts the
    # job among what a derivation records, and the column has existed unwritten since M4's
    # migration: nothing derived anything until M8's renderer arrived. Optional because a
    # derivation taken inline — a preview rendered on request — has no job to name, and a required
    # field would force a caller to invent one.
    created_by_job_id: uuid.UUID | None = None


@dataclass(frozen=True)
class DerivationResult:
    derived_file_id: uuid.UUID
    derivation_id: uuid.UUID
    sha256: str


def record_derivation(
    request: DerivationRequest,
    *,
    uow: SqlAlchemyUnitOfWork,
    storage: StorageBackend,
    moment: datetime,
) -> DerivationResult:
    """Store the derived bytes and both rows, atomically for the rows.

    The caller owns the transaction, which is why `uow` is passed already entered rather
    than a factory: a derivation is one step of a larger piece of work — a preview job, a
    crop — and it must commit with whatever else that work records.

    The bytes are written before the transaction's rows for the same reason the upload
    path writes them between transactions: a storage write is slow external I/O and does
    not belong under a lock. The asymmetry with the upload is deliberate. There, a crash
    should leave a `pending` row that says who was uploading; here, a crash should leave
    nothing at all, because a half-made derivative has no owner to inform and
    `storage_objects_without_a_record` will find the orphan.
    """

    if request.derivation_type not in DERIVATION_TYPES:
        raise BusinessRuleViolationError(
            f"{request.derivation_type!r} is not a derivation type; the known ones are "
            f"{', '.join(DERIVATION_TYPES)}."
        )

    source = uow.session.get(FileObject, request.source_file_id)
    if source is None:
        raise BusinessRuleViolationError("the source file does not exist")
    if source.sha256_hash is None:
        raise BusinessRuleViolationError(
            "the source file has no checksum, so a derivation could not record what it "
            "was derived from"
        )

    storage_key = generate_storage_key(category=request.derivation_type, moment=moment)
    written = storage.write(storage_key, request.body)

    derived = FileObject(
        storage_provider=source.storage_provider,
        storage_bucket=source.storage_bucket,
        storage_key=storage_key,
        original_filename=request.filename,
        mime_type_declared=request.media_type,
        mime_type_detected=request.media_type,
        size_bytes=written.size_bytes,
        sha256_hash=written.sha256_hash,
        # A derivative inherits its source's category and visibility rather than choosing
        # its own. A preview of an internal bundle is internal; letting the renderer pick
        # would put the access decision in the least considered place in the system.
        category=source.category,
        visibility_scope=source.visibility_scope,
        storage_status=AVAILABLE,
        # This platform produced these bytes from content it had already accepted, so
        # there is nothing external to scan. Recorded as `clean` rather than left pending
        # because the availability CHECK requires it, and because pending would claim a
        # scanner is coming for a file no scanner will ever see.
        scan_status=SCAN_CLEAN,
        uploaded_by_actor_type="system_worker",
        uploaded_by_actor_id=None,
        original_or_derived_relation=DERIVED,
        metadata_payload={},
    )
    uow.session.add(derived)
    uow.flush()

    derivation = FileDerivation(
        source_file_id=source.id,
        derived_file_id=derived.id,
        derivation_type=request.derivation_type,
        parameters_hash=parameters_hash(request.parameters),
        renderer_version=request.renderer_version,
        source_hash=source.sha256_hash,
        parameters=dict(request.parameters),
        created_by_job_id=request.created_by_job_id,
    )
    uow.session.add(derivation)
    uow.flush()

    return DerivationResult(
        derived_file_id=derived.id,
        derivation_id=derivation.id,
        sha256=written.sha256_hash,
    )
