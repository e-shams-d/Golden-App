"""File checksum verification, bounded and honest about what it did not check.
`15_Agent_Implementation_Plan.md:1318`.

M11 slice 6A. §19.5 names eight maintenance jobs; two were scheduled and this is the third.

**It lives in `app/storage/` because it reads a storage address**, and M4's
`test_no_module_outside_the_file_service_handles_a_storage_address` says only this package
and `app/files/` may. The first draft put it in `app/workers/tasks/` and that gate caught it
— correctly: a change of storage provider must touch this package and nothing else, and a
worker module reading `storage_key` would have made the worker a second place to change.
The scheduler entry point stays in `app/workers/tasks/checksums.py` and passes no address.

**`app/storage/reconciliation.py` already detects this**, and has since M2 — `checksum_mismatches`
compares each row's recorded digest against the bytes in storage. What it has never had is a
*caller on a schedule*: only `app/cli/reconcile_storage.py` runs it, which means the check happens
when somebody remembers rather than when the bytes change.

**Why this is a new function rather than a call to `detect_all`.** §19 `:1318` requires every
maintenance job to be bounded, and `checksum_mismatches` is deliberately not: it walks every
recorded key and reads every object. On a small system that is fine; on a growing one it is a job
that takes longer every night until it stops finishing, which is exactly the failure the rule
names. `detect_all` stays as it is — an operator running the CLI *wants* the exhaustive pass, and
bounding it there would take away the only complete check that exists.

**What the bound costs, stated rather than hidden.** This job reads the **newest** rows, because a
digest that disagrees on a recently written file is a broken write path and worth catching within
a day, while an old file that has sat correct for months is unlikely to change on its own. That is
a real coverage gap: a corruption in an old object is found by the CLI pass, not by this. The
report says so — `examined` and `remaining` are both returned, so a run that checked 200 of 5,000
files cannot be read as a clean bill of health for 5,000 files.

**No rotation, because rotation needs state this table does not have.** Verifying the least
recently checked rows would need a `last_verified_at` column, which is a migration and a write on
every pass. Recorded as the honest alternative rather than implemented: newest-first is the
cheaper approximation, and the CLI covers what it misses.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, func, select

from app.core.logging import get_logger, log_event
from app.core.runtime import RuntimeServices
from app.db.models.file_object import FileObject
from app.storage.interface import StorageBackend

logger = get_logger("storage.verification")

# How many objects one pass reads. Storage I/O per row, so this is a real cost rather than a
# query-planner detail. Two hundred at a daily cadence covers a system taking a few dozen uploads
# a day several times over, and leaves the exhaustive pass to the operator's CLI.
DEFAULT_LIMIT = 200


@dataclass(frozen=True, slots=True)
class ChecksumReport:
    """What one bounded pass found, and what it did not look at.

    `remaining` is the field that makes the bound honest. Without it a caller sees
    `mismatches=0` and reads "storage is intact", when what happened may be "the newest two
    hundred of nine thousand files are intact".
    """

    examined: int
    mismatches: tuple[uuid.UUID, ...]
    remaining: int

    @property
    def complete(self) -> bool:
        """Whether this pass covered every verifiable row."""

        return self.remaining == 0


def _verifiable() -> ColumnElement[bool]:
    """Rows this job can check: a recorded digest and a key to read.

    A `pending` upload legitimately has no digest, and reporting one would bury a real mismatch
    under ordinary rows — the same reasoning `checksum_mismatches` gives for skipping them.
    """

    return FileObject.sha256_hash.is_not(None)


def verify_recent_checksums(
    runtime: RuntimeServices, *, limit: int = DEFAULT_LIMIT
) -> ChecksumReport:
    """One bounded pass. Reports; changes nothing.

    **Read-only on purpose.** A mismatch means the row and the bytes disagree, and this job cannot
    know which is right: the object may have been corrupted, or the row may have been written
    wrongly. Quarantining the file would be a guess that removes evidence, and rewriting the digest
    would erase the disagreement. So it reports, and a person decides — the same choice
    `recover_stale_leases` makes for the same reason.
    """

    if limit < 1:
        raise ValueError("a checksum pass with no limit would be unbounded, which §19 forbids")

    storage: StorageBackend = runtime.storage
    mismatches: list[uuid.UUID] = []

    with runtime.uow_factory() as uow:
        total = (
            uow.session.execute(
                select(func.count()).select_from(FileObject).where(_verifiable())
            ).scalar_one()
        )
        rows = (
            uow.session.execute(
                select(
                    FileObject.id,
                    FileObject.storage_key,
                    FileObject.sha256_hash,
                    FileObject.size_bytes,
                )
                .where(_verifiable())
                # Newest first, and `id` breaks the tie: `created_at` is not unique, and without a
                # total order two passes could examine overlapping sets and miss a row between
                # them — the same reason every list in this project ends its sort on a unique
                # column.
                .order_by(FileObject.created_at.desc(), FileObject.id.desc())
                .limit(limit)
            )
            .tuples()
            .all()
        )
        uow.rollback()

    for file_id, key, recorded_digest, recorded_size in rows:
        measured = storage.stat(key)
        if measured is None:
            # Absent objects are `records_without_a_storage_object`'s finding. Counting them here
            # too would report one fault twice and make the number useless as a trend.
            continue
        if measured.sha256_hash != recorded_digest or measured.size_bytes != recorded_size:
            mismatches.append(file_id)
            log_event(
                logger,
                logging.ERROR,
                "checksum_mismatch",
                file_id=str(file_id),
                recorded_sha256=recorded_digest,
                measured_sha256=measured.sha256_hash,
                recorded_size=recorded_size,
                measured_size=measured.size_bytes,
            )

    report = ChecksumReport(
        examined=len(rows),
        mismatches=tuple(mismatches),
        remaining=max(total - len(rows), 0),
    )

    if not report.complete:
        # Logged every incomplete pass rather than once: a bound that stops being enough is a
        # thing an operator should meet repeatedly, not read in a changelog.
        log_event(
            logger,
            logging.INFO,
            "checksum_pass_incomplete",
            examined=report.examined,
            remaining=report.remaining,
            detail="raise the limit or run the exhaustive CLI pass; this is not full coverage",
        )
    return report
