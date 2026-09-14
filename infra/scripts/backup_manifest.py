"""What a backup contains, recorded at the moment it is taken — and compared after a restore.

M12 slice 2. §20.5 requires that "restored files, approvals, publications, and audit records
reconcile", and this is the thing that decides whether they do.

**A backup nobody has restored is a belief.** The exit gate does not ask for a backup script; it
asks for a restore drill that passes. So the manifest is not documentation — it is the assertion the
drill makes, written before the restore so it cannot be adjusted to match the outcome.

## What is recorded, and why it is not just counts

Row counts catch a table that failed to restore. They do not catch a table that restored with the
right number of rows and the wrong contents — a `pg_restore` that silently dropped a column default,
a storage copy that truncated a file, a dump taken while a transaction was in flight.

So every table the exit gate names carries **a count and a digest over its identifying columns**,
ordered deterministically. The digest is over the columns a later reader would use to recognise a
row, not over every column: `updated_at` moves when a restore rewrites a row, and a manifest that
failed on that would fail on every correct restore.

## The four the gate names, and the others

`file_objects`, `batch_approvals`, `payment_result_publications` and `audit_logs` are named by §20.5
directly. The rest are carried because a restore that lost *them* would pass a check that only
looked at four tables — and the four would still reconcile, which is the worst kind of green.

**`audit_logs` carries its hash chain rather than a row digest.** M2 built the chain precisely so
tampering is detectable; comparing `previous_hash`/`entry_hash` of the first and last row proves the
chain survived the round trip, which a count cannot.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# Tables whose restoration §20.5 names. Ordered as the gate words it, so a reader comparing the two
# is comparing like with like.
GATE_TABLES: dict[str, tuple[str, ...]] = {
    # The gate's "files".
    "file_objects": ("id", "sha256_hash", "storage_key", "scan_status", "storage_status"),
    "file_derivations": ("id", "source_file_id", "derived_file_id", "derivation_type"),
    "file_links": ("id", "file_id", "resource_type", "resource_id", "link_role"),
    # The gate's "approvals". `approved_content_hash` is what the approval was *of*: an approval
    # restored beside different batch content is an approval of something nobody agreed to.
    "batch_approvals": (
        "id",
        "payment_batch_version_id",
        "decision",
        "decided_at",
        "approved_content_hash",
    ),
    # The gate's "publications".
    "payment_result_publications": (
        "id",
        "payment_request_id",
        "publication_version",
        "status",
        "content_hash",
        "published_at",
    ),
    # The gate's "audit records". `previous_event_hash`/`event_hash` are M2's chain, and comparing
    # them is what proves the chain survived the round trip — a count cannot, and the chain is the
    # whole reason the audit trail is evidence rather than a log.
    "audit_logs": (
        "id",
        "sequence_number",
        "action",
        "entity_type",
        "entity_id",
        "previous_event_hash",
        "event_hash",
    ),
}

# Everything else that carries state a restore could lose. **Not optional decoration**: a drill that
# reconciled only the four tables above would pass while the money moved through them was gone.
OTHER_TABLES: dict[str, tuple[str, ...]] = {
    "traders": ("id", "display_name", "operational_status", "approval_status"),
    "beneficiaries": ("id", "trader_id", "normalized_iban", "status"),
    "payment_requests": ("id", "trader_id", "status", "request_number"),
    "payment_request_revisions": (
        "id",
        "payment_request_id",
        "revision_number",
        "amount_irr",
        "content_hash",
    ),
    "payment_attempts": ("id", "payment_request_id", "attempt_number", "amount_irr", "status"),
    "payment_batches": ("id", "batch_number", "status"),
    "payment_batch_versions": (
        "id",
        "payment_batch_id",
        "version_number",
        "status",
        "content_hash",
    ),
    "payment_batch_items": ("id", "payment_batch_version_id", "payment_attempt_id", "row_hash"),
    "bank_excel_exports": ("id", "payment_batch_version_id", "status", "file_sha256_hash"),
    "bank_result_bundles": ("id", "bundle_number", "status"),
    "receipt_segments": ("id", "source_file_id", "status"),
    "confirmed_evidence_links": ("id", "payment_attempt_id", "receipt_segment_id", "status"),
    "matching_candidates": ("id", "receipt_segment_id", "payment_attempt_id", "status"),
    "bank_statement_files": ("id", "original_file_id", "status"),
    "bank_statement_rows": ("id", "bank_statement_import_run_id", "row_number", "row_fingerprint"),
    "gold_sale_orders": ("id", "trader_id", "status"),
    "incoming_payment_receipts": ("id", "trader_id", "status"),
    "admin_users": ("id", "username", "status"),
    "roles": ("id", "code"),
    "permissions": ("id", "code"),
    "bank_profiles": ("id", "code", "status"),
    "bank_profile_versions": ("id", "bank_profile_id", "version_number", "status"),
    "bank_mappings": ("id", "bank_profile_version_id", "file_type", "config_hash"),
}

ALL_TABLES = {**GATE_TABLES, **OTHER_TABLES}


def _digest(rows: list[tuple[Any, ...]]) -> str:
    """A digest over rows already ordered by the query.

    `json.dumps` with `default=str` rather than a bespoke serialiser: the values are UUIDs,
    timestamps and strings, and what matters is that the same row produces the same text on both
    sides of a restore rather than that the text is pretty.
    """

    payload = json.dumps(
        [[str(value) for value in row] for row in rows], separators=(",", ":"), sort_keys=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# The image the PostgreSQL client tools come from. Pinned by tag **and matched to the server**:
# `pg_dump` refuses a server newer than itself, and a host that upgraded its client independently
# would produce dumps this server cannot read back.
PG_IMAGE = "postgres:16.14-alpine3.24"


class NetworkPsql:
    """A `connection.execute(sql).fetchall()` that runs `psql` over the network.

    **Over the network rather than `docker exec`, and CI is what taught that.** The first version
    took a container name — `m2-itest-pg` — and the drill failed in CI with `No such container`,
    because GitHub Actions names its service containers differently. The name was an *environment*
    fact wearing the shape of a design decision.

    A throwaway container connecting to a URL works wherever that URL works: to `127.0.0.1:5432` on
    a runner, to a bridge address locally, to a database host in production. It is also what a real
    backup host does — nothing in a deployment runs `docker exec` against the database.

    **Here rather than in `backup.sh`.** The first version lived in a heredoc inside the shell
    script, which meant the manifest an operator takes in production was parsed by code no test ever
    ran. `test_the_manifest_inside_the_bundle_matches_the_source` now compares two manifests that
    differ only in *how they connect* — psycopg in the test, `psql` here — rather than in how they
    read rows.

    **CSV rather than zero-separated output.** An earlier attempt passed `--record-separator-zero`
    and `--field-separator-zero` together, which makes a record boundary and a field boundary the
    same byte: 122 rows of one column parsed as one row of 122 fields, and the manifest said
    `permissions: 1 row`. CSV has a quoting rule for every value a column can hold, and Python's
    `csv` module implements the same rule psql writes.
    """

    def __init__(self, database_url: str) -> None:
        self._url = database_url
        self._rows: list[tuple[str, ...]] = []

    def execute(self, sql: str) -> NetworkPsql:
        completed = subprocess.run(
            [
                # `--network host` so the URL means the same thing inside the container as outside.
                # Without it a `127.0.0.1` in the URL would name the throwaway container itself.
                "docker", "run", "--rm", "--network", "host", PG_IMAGE,
                "psql", self._url, "--csv", "--tuples-only", "--command", sql,
            ],
            check=True, capture_output=True, text=True,
        )
        self._rows = [tuple(row) for row in csv.reader(io.StringIO(completed.stdout)) if row]
        return self

    def fetchall(self) -> list[tuple[str, ...]]:
        return self._rows


def build(connection: Any, storage_root: Path | None = None) -> dict[str, Any]:
    """Read the database and the storage tree, and record what is there.

    Takes a live connection rather than a URL so the drill can build a manifest inside a transaction
    it controls — a manifest taken from a second connection could see a different moment.
    """

    tables: dict[str, dict[str, Any]] = {}
    for table, columns in ALL_TABLES.items():
        selected = ", ".join(columns)
        # Ordered by the first column, which is `id` everywhere here. Without a total order the
        # digest depends on whatever order the planner returns, and the same data would produce two
        # different manifests — a check that fails at random teaches people to ignore it.
        # Interpolated rather than parameterised, and safely: `table` and `columns` come from the
        # literal dictionaries at the top of this file, never from input. A placeholder cannot carry
        # an identifier anyway — `%s` binds values, not table names.
        rows = connection.execute(
            f"SELECT {selected} FROM {table} ORDER BY {columns[0]}"
        ).fetchall()
        tables[table] = {"rows": len(rows), "digest": _digest(rows)}

    manifest: dict[str, Any] = {"tables": tables}

    if storage_root is not None:
        manifest["storage"] = _storage_manifest(storage_root)

    return manifest


def _storage_manifest(root: Path) -> dict[str, Any]:
    """Every stored file, by relative path and digest.

    **The digest is of the bytes, not of the database's record of them.** `file_objects.sha256_hash`
    is what the platform believes; this is what is on disk. A restore that reconciled the two
    against each other would agree with itself while both were wrong.
    """

    if not root.is_dir():
        return {"files": 0, "digest": _digest([]), "bytes": 0}

    entries: list[tuple[Any, ...]] = []
    total = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        total += len(data)
        entries.append((str(path.relative_to(root)), hashlib.sha256(data).hexdigest()))

    return {"files": len(entries), "digest": _digest(entries), "bytes": total}


def compare(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    """Every difference, not the first.

    A restore that lost three tables should report three lines. Stopping at the first turns one
    drill into three, and the second and third are run by somebody who has already decided the
    problem is small.
    """

    problems: list[str] = []

    for table in sorted(ALL_TABLES):
        want = expected["tables"].get(table)
        got = actual["tables"].get(table)
        if want is None or got is None:
            problems.append(f"{table}: missing from a manifest (expected={want}, actual={got})")
            continue
        if want["rows"] != got["rows"]:
            problems.append(
                f"{table}: {got['rows']} rows restored, {want['rows']} expected"
                + (" — in the exit gate's named set" if table in GATE_TABLES else "")
            )
        elif want["digest"] != got["digest"]:
            problems.append(
                f"{table}: {got['rows']} rows restored and the contents differ — same count, "
                "different data, which is the failure a count alone cannot see"
            )

    want_storage = expected.get("storage")
    got_storage = actual.get("storage")
    if want_storage is not None and got_storage is not None:
        if want_storage["files"] != got_storage["files"]:
            problems.append(
                f"storage: {got_storage['files']} files restored, {want_storage['files']} expected"
            )
        elif want_storage["digest"] != got_storage["digest"]:
            problems.append(
                "storage: the same number of files with different bytes — a truncated or "
                "partially written copy"
            )
    elif (want_storage is None) != (got_storage is None):
        problems.append("storage: recorded on one side and not the other")

    return problems


def main() -> int:
    """`python backup_manifest.py <manifest.json> <other.json>` — compare two manifests.

    Exists so the runbook can reconcile a restore by hand without a test runner, which is what an
    operator at 3am actually has.
    """

    if len(sys.argv) != 3:
        print(__doc__ or "", file=sys.stderr)
        print("usage: backup_manifest.py EXPECTED.json ACTUAL.json", file=sys.stderr)
        return 2

    expected = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    actual = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    problems = compare(expected, actual)

    if not problems:
        print("restore reconciles: every table and every stored file matches the manifest")
        return 0

    print(f"the restore does not reconcile — {len(problems)} differences:", file=sys.stderr)
    for line in problems:
        print(f"  {line}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
