#!/usr/bin/env python3
"""Verify or regenerate the recorded hashes in the M0 governance manifest.

The manifest is the checksum chain behind every M0 citation. It records, for each
governed document, the SHA-256 of its raw bytes plus a byte and line count. When a
governance document changes without the manifest being regenerated, every citation
that points at it silently loses its provenance.

Convention, recovered from the entries that still verified and asserted by
``--check``: the digest is SHA-256 over the file's raw bytes with no newline
normalisation, ``bytes`` is the byte length, and ``lines`` is the number of newline
characters. ``manifest_self_included`` is false, so the manifest never hashes itself.

``--write`` only touches computed fields: per-file digests and counts, and the
summary totals derived from them. Editorial fields such as ``decision_state`` and
``manifest_status`` are governance statements and are left to a human edit, so this
script can never quietly restate an approval.

Usage:
    python infra/scripts/m0_manifest.py            # check, exit 1 on drift
    python infra/scripts/m0_manifest.py --write     # regenerate computed fields
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "docs" / "governance" / "M0_MANIFEST.json"


def serialize(manifest: dict[str, Any]) -> bytes:
    """Render the manifest the way the committed file is formatted."""
    return (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def measure(path: Path) -> tuple[str, int, int]:
    raw = path.read_bytes()
    return hashlib.sha256(raw).hexdigest(), len(raw), raw.count(b"\n")


def load() -> tuple[dict[str, Any], bytes]:
    original = MANIFEST_PATH.read_bytes()
    return json.loads(original.decode("utf-8")), original


def assert_round_trip(manifest: dict[str, Any], original: bytes) -> list[str]:
    """A regeneration that reformats the whole file would hide the real change."""
    if serialize(manifest) == original:
        return []
    return [
        "manifest formatting is not reproducible by this script; regenerating would "
        "rewrite unrelated lines. Reconcile the formatting before using --write."
    ]


def check(manifest: dict[str, Any]) -> tuple[list[str], int]:
    problems: list[str] = []
    entries = manifest.get("files") or []
    for entry in entries:
        relative = entry.get("path")
        if not relative:
            problems.append("a file entry has no path")
            continue
        target = ROOT / relative
        if not target.is_file():
            problems.append(f"{relative}: recorded in the manifest but missing on disk")
            continue
        digest, size, lines = measure(target)
        if entry.get("sha256", "").lower() != digest:
            problems.append(
                f"{relative}: digest drift\n"
                f"    recorded {entry.get('sha256')}\n"
                f"    actual   {digest}"
            )
        if entry.get("bytes") != size:
            problems.append(
                f"{relative}: byte count drift, recorded {entry.get('bytes')}, actual {size}"
            )
        if entry.get("lines") != lines:
            problems.append(
                f"{relative}: line count drift, recorded {entry.get('lines')}, actual {lines}"
            )
    return problems, len(entries)


def rewrite(manifest: dict[str, Any]) -> int:
    changed = 0
    total_bytes = 0
    total_lines = 0
    for entry in manifest.get("files") or []:
        target = ROOT / entry["path"]
        digest, size, lines = measure(target)
        if (
            entry.get("sha256", "").lower() != digest
            or entry.get("bytes") != size
            or entry.get("lines") != lines
        ):
            changed += 1
        entry["sha256"] = digest
        entry["bytes"] = size
        entry["lines"] = lines
        total_bytes += size
        total_lines += lines

    summary = manifest.setdefault("summary", {})
    summary["file_count"] = len(manifest.get("files") or [])
    summary["total_bytes"] = total_bytes
    summary["total_lines"] = total_lines
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="regenerate the computed fields instead of only reporting drift",
    )
    arguments = parser.parse_args()

    manifest, original = load()

    formatting = assert_round_trip(manifest, original)
    if formatting:
        for problem in formatting:
            print(f"  {problem}", file=sys.stderr)
        return 1

    if arguments.write:
        changed = rewrite(manifest)
        MANIFEST_PATH.write_bytes(serialize(manifest))
        noun = "entry" if changed == 1 else "entries"
        print(f"M0 manifest regenerated: {changed} {noun} corrected.")
        print(
            "Editorial fields were not touched. Review decision_state, manifest_status "
            "and generated_on by hand, and record owner re-approval of this baseline."
        )
        return 0

    problems, count = check(manifest)
    if problems:
        print(
            f"M0 manifest verification failed: {len(problems)} problem(s) across "
            f"{count} recorded files.",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            "\nRegenerate with: python infra/scripts/m0_manifest.py --write\n"
            "A governance document must never change without its manifest entry.",
            file=sys.stderr,
        )
        return 1

    print(f"M0 manifest verified: {count} files match their recorded hashes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
