"""The scheduler's entry point for checksum verification.

M11 slice 6A. The work is in `app/storage/verification.py`; this module exists only so the beat
schedule has a zero-argument callable to name.

**It deliberately handles no storage address.** M4's boundary keeps every storage key inside
`app/storage/` and `app/files/`, and the first draft of this slice put the whole job here and
tripped that gate. Splitting it was the right answer rather than widening the allowlist: a change
of storage provider should touch one package.
"""

from __future__ import annotations

from app.storage.verification import verify_recent_checksums


def verify_checksums_task() -> dict[str, int]:
    """One scheduled pass, reported as counts.

    Counts rather than the report object so the value stays JSON — which is what a result backend
    would need to serialise if one is ever turned on. `task_ignore_result` is set today, so
    nothing reads this; returning something meaningful anyway costs nothing and means the day it
    is read, it says something.
    """

    from app.workers.runtime import worker_runtime

    report = verify_recent_checksums(worker_runtime())
    return {
        "examined": report.examined,
        "mismatches": len(report.mismatches),
        "remaining": report.remaining,
    }
