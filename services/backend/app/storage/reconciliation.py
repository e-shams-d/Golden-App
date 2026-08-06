"""Detecting the seven ways storage and the database can disagree. Detection only.

**Nothing here deletes, quarantines, repairs or reconciles anything.** Every
function returns findings and returns them to an operator. That is not timidity: an
automated repair for "a storage object with no database record" is a routine that
deletes files whose row is temporarily missing, and the first time it is wrong it
destroys financial evidence that no backup restores selectively. ADR-005 is open,
no governed procedure authorises a deletion, and
`tests/backend/test_no_deletion_machinery.py` fails the build if a DELETE appears in
this package.

The seven conditions are not arbitrary — each is a specific failure that has a
specific cause and a specific consequence:

1. **A storage object with no record.** An upload that wrote bytes and then lost the
   transaction. Consequence: bytes nobody is accounting for, growing forever.
2. **A record with no object.** The mirror image, and worse: a row that says evidence
   exists when it does not, which is discovered at the moment someone needs it.
3. **A stale pending upload.** A row stuck before completion. Usually harmless,
   occasionally the only trace of a crash mid-command.
4. **A derivative with no derivation.** A file marked `derived` with nothing saying
   what produced it, so its provenance is unreconstructible.
5. **A checksum mismatch.** The bytes changed under a row that records their digest.
   The one condition on this list that means "something is wrong that should be
   impossible".
6. **A stuck processing job.** Claimed, heartbeating stopped, never finished.
7. **A duplicate object write after a retry.** Two rows, two keys, identical
   content — a retry that wrote before recording.

`stale_pending_uploads` and `stuck_processing_jobs` take their cutoffs as arguments
rather than reading a setting. A detector that decides its own threshold is one
whose findings change when a configuration file does, and an operator comparing this
week's report to last week's needs the threshold to be part of the question rather
than part of the machinery.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.time import ensure_utc
from app.storage.interface import StorageBackend

# The condition identifiers, stable so a report from two releases apart is
# comparable. These are the FILE-RECON-001..007 obligations in order.
CONDITIONS: tuple[str, ...] = (
    "storage_object_without_a_record",
    "record_without_a_storage_object",
    "stale_pending_upload",
    "derivative_without_a_derivation",
    "checksum_mismatch",
    "stuck_processing_job",
    "duplicate_object_write",
)


@dataclass(frozen=True)
class Finding:
    """One disagreement, addressed to a human.

    `storage_key` is present because an operator resolving a mismatch needs to know
    which object it is. That is the reason this type is internal and never a
    response model: FILE-META-001 requires that a raw key never reach a client, and
    a finding is an operator artifact, not an API payload.
    """

    condition: str
    detail: str
    file_id: uuid.UUID | None = None
    storage_key: str | None = None
    job_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if self.condition not in CONDITIONS:
            raise ValueError(
                f"unknown condition {self.condition!r}; add it to CONDITIONS so a "
                "report stays comparable across releases."
            )


def _recorded_keys(connection: Connection) -> dict[str, tuple[uuid.UUID, str | None, int]]:
    """Every recorded key with the digest and size the row claims for it.

    Read in one pass rather than queried per storage object: reconciliation runs
    over the whole bucket, and a query per object turns a five-minute job into an
    overnight one.
    """

    rows = connection.execute(
        text(
            "SELECT id, storage_key, sha256_hash, size_bytes FROM file_objects "
            "WHERE physically_deleted_at IS NULL"
        )
    ).all()
    return {row.storage_key: (row.id, row.sha256_hash, row.size_bytes) for row in rows}


def storage_objects_without_a_record(
    connection: Connection, storage: StorageBackend
) -> list[Finding]:
    """FILE-RECON-001. Bytes in storage that no surviving row claims."""

    recorded = _recorded_keys(connection)
    return [
        Finding(
            condition="storage_object_without_a_record",
            detail=(
                "storage holds an object that no file_objects row references; a "
                "write survived a transaction that did not"
            ),
            storage_key=key,
        )
        for key in storage.iter_keys()
        if key not in recorded
    ]


def records_without_a_storage_object(
    connection: Connection, storage: StorageBackend
) -> list[Finding]:
    """FILE-RECON-002. A row promising evidence that is not there.

    Worse than its mirror image, because the promise is only tested at the moment
    somebody needs the file — which is to say during an audit or a dispute.
    """

    findings: list[Finding] = []
    for key, (file_id, _digest, _size) in sorted(_recorded_keys(connection).items()):
        if storage.stat(key) is None:
            findings.append(
                Finding(
                    condition="record_without_a_storage_object",
                    detail="a file_objects row references an object storage does not hold",
                    file_id=file_id,
                    storage_key=key,
                )
            )
    return findings


def stale_pending_uploads(
    connection: Connection, *, now: datetime, older_than: timedelta
) -> list[Finding]:
    """FILE-RECON-003. Rows that never left `pending`.

    `now` is a parameter so the query is reproducible: a detector reading the clock
    gives a different answer on a re-run, and an operator re-running a report to
    confirm a finding needs the same answer.
    """

    cutoff = ensure_utc(now) - older_than
    rows = connection.execute(
        text(
            "SELECT id, storage_key, created_at FROM file_objects "
            "WHERE storage_status = 'pending' AND created_at < :cutoff "
            "ORDER BY created_at"
        ),
        {"cutoff": cutoff},
    ).all()
    return [
        Finding(
            condition="stale_pending_upload",
            detail=f"pending since {row.created_at.isoformat()}, past the {older_than} cutoff",
            file_id=row.id,
            storage_key=row.storage_key,
        )
        for row in rows
    ]


def derivatives_without_a_derivation(connection: Connection) -> list[Finding]:
    """FILE-RECON-004. A file marked derived with nothing recording what produced it.

    `NOT EXISTS` rather than a `LEFT JOIN ... IS NULL`: it stops at the first match
    per row, and it says what it means.
    """

    rows = connection.execute(
        text(
            "SELECT f.id, f.storage_key FROM file_objects f "
            "WHERE f.original_or_derived_relation = 'derived' "
            "AND NOT EXISTS (SELECT 1 FROM file_derivations d WHERE d.derived_file_id = f.id) "
            "ORDER BY f.created_at"
        )
    ).all()
    return [
        Finding(
            condition="derivative_without_a_derivation",
            detail=(
                "marked derived with no file_derivations row, so its provenance "
                "cannot be reconstructed"
            ),
            file_id=row.id,
            storage_key=row.storage_key,
        )
        for row in rows
    ]


def checksum_mismatches(connection: Connection, storage: StorageBackend) -> list[Finding]:
    """FILE-RECON-005. The bytes changed under a row that records their digest.

    Rows without a recorded digest are skipped rather than reported: a `pending`
    upload legitimately has none, and reporting it here would bury the real finding
    under the ordinary ones. Size is compared too, because it is free once the
    object has been read and it makes a truncation obvious in the report.
    """

    findings: list[Finding] = []
    for key, (file_id, recorded_digest, recorded_size) in sorted(
        _recorded_keys(connection).items()
    ):
        if recorded_digest is None:
            continue
        measured = storage.stat(key)
        if measured is None:
            # Reported by records_without_a_storage_object; not double-counted.
            continue
        if measured.sha256_hash != recorded_digest or measured.size_bytes != recorded_size:
            findings.append(
                Finding(
                    condition="checksum_mismatch",
                    detail=(
                        f"recorded {recorded_digest} at {recorded_size} bytes; "
                        f"storage holds {measured.sha256_hash} at "
                        f"{measured.size_bytes} bytes"
                    ),
                    file_id=file_id,
                    storage_key=key,
                )
            )
    return findings


def stuck_processing_jobs(
    connection: Connection, *, now: datetime, silent_for: timedelta
) -> list[Finding]:
    """FILE-RECON-006. Claimed, stopped heartbeating, never finished.

    The status is `running` — `processing_jobs` has no `processing` value, and a
    detector filtering on one that does not exist returns nothing while looking
    correct, which is the failure mode worth naming.

    `COALESCE(heartbeat_at, started_at)` is **not** for a claim that never
    heartbeat: `ck_processing_jobs_lease_fields_move_together` makes that
    unrepresentable. It is for a row that is `running` while holding no lease at
    all — both lease columns null — where `started_at` is the only signal of age.
    """

    cutoff = ensure_utc(now) - silent_for
    rows = connection.execute(
        text(
            "SELECT id, job_type, locked_by, COALESCE(heartbeat_at, started_at) AS last_seen "
            "FROM processing_jobs "
            "WHERE status = 'running' AND finished_at IS NULL "
            "AND COALESCE(heartbeat_at, started_at) < :cutoff "
            "ORDER BY last_seen"
        ),
        {"cutoff": cutoff},
    ).all()
    return [
        Finding(
            condition="stuck_processing_job",
            detail=(
                f"{row.job_type} held by {row.locked_by!r} last seen "
                f"{row.last_seen.isoformat() if row.last_seen else 'never'}"
            ),
            job_id=row.id,
        )
        for row in rows
    ]


def duplicate_object_writes(connection: Connection) -> list[Finding]:
    """FILE-RECON-007. Identical content stored twice under different keys.

    Not an error to correct automatically — the same document legitimately arrives
    twice — but a signal that a retry wrote before recording. Grouped on digest and
    size together: a digest collision is not a practical concern, and comparing both
    makes the report state the whole basis for the claim.
    """

    rows = connection.execute(
        text(
            "SELECT sha256_hash, size_bytes, count(*) AS copies, "
            "array_agg(storage_key ORDER BY created_at) AS keys "
            "FROM file_objects "
            "WHERE sha256_hash IS NOT NULL AND physically_deleted_at IS NULL "
            "GROUP BY sha256_hash, size_bytes HAVING count(*) > 1"
        )
    ).all()
    return [
        Finding(
            condition="duplicate_object_write",
            detail=(
                f"{row.copies} rows share digest {row.sha256_hash} at "
                f"{row.size_bytes} bytes: {', '.join(row.keys)}"
            ),
        )
        for row in rows
    ]


def detect_all(
    connection: Connection,
    storage: StorageBackend,
    *,
    now: datetime,
    pending_older_than: timedelta = timedelta(hours=6),
    job_silent_for: timedelta = timedelta(minutes=30),
) -> list[Finding]:
    """Run all seven and return every finding.

    Defaults are stated here rather than in the individual detectors so a caller
    reads one place to see what "stale" currently means, and so overriding it is a
    visible argument at the call site.
    """

    groups: Iterable[Sequence[Finding]] = (
        storage_objects_without_a_record(connection, storage),
        records_without_a_storage_object(connection, storage),
        stale_pending_uploads(connection, now=now, older_than=pending_older_than),
        derivatives_without_a_derivation(connection),
        checksum_mismatches(connection, storage),
        stuck_processing_jobs(connection, now=now, silent_for=job_silent_for),
        duplicate_object_writes(connection),
    )
    return [finding for group in groups for finding in group]
