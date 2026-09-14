#!/usr/bin/env bash
# Negative controls for M12 slice 2 — the backup and the restore drill.
#
# **A drill is the easiest thing in this repository to make vacuous.** It passes when everything
# works, which is also what it does when the comparison it performs is empty, when the world it
# backs up has nothing in it, or when it restores over a database that already held the answer.
# Every control here produces a backup that *runs* and a restore that *succeeds*, and breaks one
# thing the drill claims to prove.
#
# Control 0 runs the suite CLEAN FIRST. Restores with `cp`, never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql+psycopg://postgres:postgres@172.17.0.2:5432/postgres}"

MANIFEST=infra/scripts/backup_manifest.py
BACKUP=infra/scripts/backup.sh
RESTORE=infra/scripts/restore.sh
DRILL=tests/integration/test_backup_restore_drill.py

WORK=$(mktemp -d)
cp "$MANIFEST" "$WORK/manifest.py"
cp "$BACKUP" "$WORK/backup.sh"
cp "$RESTORE" "$WORK/restore.sh"
cp "$DRILL" "$WORK/drill.py"

restore_files() {
  cp "$WORK/manifest.py" "$MANIFEST"
  cp "$WORK/backup.sh" "$BACKUP"
  cp "$WORK/restore.sh" "$RESTORE"
  cp "$WORK/drill.py" "$DRILL"
}
trap restore_files EXIT

run_suite() {
  $PY -m pytest -c services/backend/pyproject.toml "$DRILL" -q --no-header >"$WORK/out.txt" 2>&1
}

echo "=== CONTROL 0: clean. Anything but green here invalidates every result below. ==="
if run_suite; then
  echo "clean: green"
else
  echo "clean: NOT GREEN — stop."
  tail -20 "$WORK/out.txt"
  exit 1
fi

probe() {
  local name="$1"
  echo
  echo "=== $name ==="
  if run_suite; then
    echo "NOT CAUGHT"
  else
    echo "CAUGHT"
    grep -E '^FAILED' "$WORK/out.txt" | head -3
  fi
  restore_files
}

# 1. **The comparison stops comparing.** `compare` returns no problems, ever. Every drill passes,
#    the backup still runs, the restore still succeeds — and the one assertion that makes any of it
#    mean something is gone. This is the vacuous green a restore drill is most likely to end up in.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("infra/scripts/backup_manifest.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "    problems: list[str] = []\n",
    "    problems: list[str] = []\n    return problems\n",
    1,
)
assert s != before, "control 1 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "1. the manifest comparison reports nothing, ever"

# 2. The manifest records counts and drops the digests. A restore that produced the right number of
#    rows with the wrong contents — a dump taken mid-transaction, a column silently defaulted —
#    reconciles. The count is the check people expect a backup to have, and it is the weaker half.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("infra/scripts/backup_manifest.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    '        tables[table] = {"rows": len(rows), "digest": _digest(rows)}',
    '        tables[table] = {"rows": len(rows), "digest": "constant"}',
)
assert s != before, "control 2 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "2. the manifest keeps counts and drops content digests"

# 3. **The storage tree is left out of the backup.** The database restores perfectly. Every row
#    about every receipt is there, and not one of the receipts is — a system that can name evidence
#    it cannot show, which is the failure mode a database-only backup actually has.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("infra/scripts/backup.sh")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    'tar --create --gzip --file "$work/storage.tar.gz" --directory "$storage" .',
    'tar --create --gzip --file "$work/storage.tar.gz" --directory "$storage" --files-from /dev/null',
)
assert s != before, "control 3 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "3. the backup carries the database and none of the files"

# 4. **The restore stops refusing a database that already has rows.** This is the control that
#    matters most: without the refusal, a drill run twice passes the second time by comparing a
#    manifest against rows that were already there — and a real operator running the drill against
#    production destroys it.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("infra/scripts/restore.sh")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace('if [ "${rows:-0}" -gt 0 ] && [ "$force" -eq 0 ]; then', 'if false; then')
assert s != before, "control 4 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "4. the restore overwrites a populated database without being forced"

# 5. The storage digest is taken from the database's record of the files rather than from the bytes.
#    The system then agrees with itself: `file_objects.sha256_hash` matches `file_objects.sha256_hash`
#    on both sides while the bytes on disk are truncated, missing or someone else's.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("infra/scripts/backup_manifest.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "        data = path.read_bytes()\n        total += len(data)\n"
    "        entries.append((str(path.relative_to(root)), hashlib.sha256(data).hexdigest()))",
    "        total += path.stat().st_size\n"
    "        entries.append((str(path.relative_to(root)), str(path.stat().st_size)))",
)
assert s != before, "control 5 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "5. stored files are compared by size rather than by content"

# 6. The drill backs up an empty world. Everything reconciles, in a fifth of the time, and proves
#    nothing — the vacuous pass the seeding step exists to prevent, and the one a reader skimming a
#    green test run would never notice.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("tests/integration/test_backup_restore_drill.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace("def _seed(world: dict[str, Any]) -> None:", "def _seed(world: dict[str, Any]) -> None:\n    return")
assert s != before, "control 6 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "6. the drill backs up an empty database and reconciles trivially"

echo
echo "=== restored ==="
git status --short "$MANIFEST" "$BACKUP" "$RESTORE" "$DRILL"
