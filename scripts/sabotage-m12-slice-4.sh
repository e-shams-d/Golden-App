#!/usr/bin/env bash
# Negative controls for M12 slice 4 — the runbooks and the gate that keeps them true.
#
# **A runbook rots silently.** Nothing executes it, nobody reads it until the day it is needed, and
# the day it is needed is the worst possible time to discover a renamed flag. Every control here
# leaves a runbook that reads perfectly and instructs somebody to do something that will not work.
#
# The gate already caught a real one while being written: this branch carried the older `backup.sh`
# interface, and the runbooks — written against the newer one — named `--database-url` on a script
# that still took `--container`. That is exactly the failure mode, found before it shipped rather
# than during a recovery.
#
# Control 0 runs the suite CLEAN FIRST. Restores with `cp`, never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
GATE=tests/backend/test_runbooks.py
BOOKS=infra/runbooks

WORK=$(mktemp -d)
cp -r "$BOOKS" "$WORK/runbooks"
cp .env.example "$WORK/env.example"

restore_files() {
  rm -rf "$BOOKS"
  cp -r "$WORK/runbooks" "$BOOKS"
  cp "$WORK/env.example" .env.example
}
trap restore_files EXIT

run_suite() {
  $PY -m pytest -c services/backend/pyproject.toml "$GATE" -q --no-header >"$WORK/out.txt" 2>&1
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
    grep -E '^FAILED|AssertionError' "$WORK/out.txt" | head -2
  fi
  restore_files
}

# 1. **A flag is renamed in a runbook.** The prose still reads correctly and the command fails on
#    its first argument, in front of somebody restoring a lost database.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("infra/runbooks/restore.md")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace("--database-url", "--db-url")
assert s != before, "control 1 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "1. a runbook passes a flag the script does not accept"

# 2. A script is moved and the runbook keeps the old path. Indistinguishable from correct when read.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("infra/runbooks/deployment.md")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace("infra/scripts/backup.sh", "infra/scripts/take-backup.sh")
assert s != before, "control 2 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "2. a runbook names a script that does not exist"

# 3. **A column is renamed in a diagnostic query.** The audit-chain check in `incident.md` becomes a
#    syntax error — at 3am, in front of somebody who has no time to debug SQL. `event_hash` was
#    `entry_hash` in this slice's own first draft of the backup manifest, so this is not
#    hypothetical.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("infra/runbooks/incident.md")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace("a.previous_event_hash IS DISTINCT FROM b.event_hash", "a.previous_hash IS DISTINCT FROM b.hash")
assert s != before, "control 3 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "3. a diagnostic query names a column that no longer exists"

# 4. The rotation runbook names a setting nothing reads. Somebody rotates it, sees no failure, and
#    concludes the rotation worked — which is worse than it failing.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("infra/runbooks/secret-rotation.md")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace("`AUTH_CSRF_KEY_SECRET`", "`AUTH_CSRF_SIGNING_SECRET`")
assert s != before, "control 4 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "4. the rotation runbook names a setting nothing reads"

# 5. **The restore runbook drops the ownership step.** Everything else is correct; the restore runs,
#    reconciles, and the application fails on its first request with `permission denied`. Slice 2's
#    drill deliberately does not cover this, so this runbook is the only place it is recorded.
$PY - <<'EOF'
import pathlib
import re
p = pathlib.Path("infra/runbooks/restore.md")
s = p.read_text(encoding="utf-8")
before = s
s = re.sub(r"## 3\. Put ownership back.*?(?=## 4\.)", "", s, flags=re.S)
assert s != before, "control 5 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "5. the restore runbook loses the step that re-applies the grants"

# 6. A runbook stops saying how it is tested. Three of these five are executed by no test, and a
#    reader under pressure has no way to tell which — so the absence reads as verification.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("infra/runbooks/rollback.md")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace("## How this runbook is tested", "## Notes")
assert s != before, "control 6 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "6. a runbook stops saying whether it is tested"

# 7. A required runbook is deleted. The directory still holds four files and looks complete.
rm -f infra/runbooks/incident.md
probe "7. a required runbook is missing"

echo
echo "=== restored ==="
git status --short infra/runbooks .env.example
