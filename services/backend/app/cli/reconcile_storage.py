"""Run the storage reconciliation checks and report what they find.

`app/storage/reconciliation.py` shipped in M2 with seven detectors, an aggregator, and
**no caller of any kind** — no route, no CLI, no scheduled job. The platform could detect
every way its file records and its stored objects disagree, and nothing ever asked. This
is the caller.

**It repairs nothing.** `12_Security_RBAC_Audit.md:1571`: "Reconciliation does not
automatically delete financial evidence. It creates controlled repair/quarantine work."
A checksum mismatch might be a corrupted object or a tampered one, and the difference
matters more than the tidiness of fixing it automatically. So this reads, reports, and
exits — and `OPS-RECON-003` proves the read-only claim by running it against a read-only
database role rather than by trusting this paragraph.

**The exit code is the operator's branch.** Non-zero when anything was found, so a cron
entry or a runbook step can act on it without parsing the output.

**Findings carry storage keys, and this output is therefore operator-only.** `Finding`
says so itself: a key never reaches a client, and a report is not an API payload. Nothing
here goes into an HTTP response.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Sequence

from app.core.config import Settings, load_settings
from app.core.time import utc_now
from app.db.session import create_engine_and_session_factory
from app.storage.local import LocalStorageBackend
from app.storage.reconciliation import Finding, detect_all


def _render(findings: Sequence[Finding]) -> str:
    """Group by condition, because an operator triages by kind before by row."""

    if not findings:
        return "No disagreements found between the file records and stored objects."

    counts = Counter(finding.condition for finding in findings)
    lines = [f"{len(findings)} finding(s) across {len(counts)} condition(s):", ""]
    for condition, count in sorted(counts.items()):
        lines.append(f"  {condition}: {count}")
    lines.append("")

    for condition in sorted(counts):
        lines.append(f"--- {condition}")
        for finding in findings:
            if finding.condition != condition:
                continue
            parts = [finding.detail]
            if finding.file_id is not None:
                parts.append(f"file_id={finding.file_id}")
            if finding.storage_key is not None:
                parts.append(f"storage_key={finding.storage_key}")
            if finding.job_id is not None:
                parts.append(f"job_id={finding.job_id}")
            lines.append("    " + "  ".join(parts))
        lines.append("")

    lines.append(
        "Nothing was repaired. Each of these is controlled work for a person: a missing "
        "object may be a restore, a checksum mismatch may be corruption or tampering, "
        "and the difference is not this tool's to guess."
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    """Run the checks. `settings` is injectable so a test need not own the environment.

    Defaulted rather than required, because the deployment entry point below has nothing
    to inject and reading the process environment is what a CLI does.
    """

    parser = argparse.ArgumentParser(
        prog="reconcile-storage",
        description="Report disagreements between file records and stored objects.",
    )
    parser.add_argument(
        "--pending-older-than-hours",
        type=float,
        default=6.0,
        help="How old a pending upload must be before it counts as stale.",
    )
    parser.add_argument(
        "--job-silent-for-minutes",
        type=float,
        default=30.0,
        help="How long a running job may be silent before it counts as stuck.",
    )
    arguments = parser.parse_args(argv)

    from datetime import timedelta

    resolved = settings if settings is not None else load_settings()
    engine, _ = create_engine_and_session_factory(resolved)
    storage = LocalStorageBackend(resolved.local_storage_root)

    try:
        with engine.connect() as connection:
            findings = detect_all(
                connection,
                storage,
                now=utc_now(),
                pending_older_than=timedelta(hours=arguments.pending_older_than_hours),
                job_silent_for=timedelta(minutes=arguments.job_silent_for_minutes),
            )
    finally:
        storage.close()
        engine.dispose()

    print(_render(findings))
    return 1 if findings else 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
