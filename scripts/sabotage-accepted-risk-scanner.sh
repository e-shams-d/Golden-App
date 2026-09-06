#!/usr/bin/env bash
# Negative controls for the accepted-risk scan adapter.
#
# The change's whole value is that the risk is *announced*. So the controls remove each
# announcement in turn: the readiness note, the startup flag, the honest name, and the closed set
# that made adding an adapter a decision in the first place.
#
# Control 0 runs the suite CLEAN FIRST. Restores with `cp`, never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python

SCAN=services/backend/app/files/scanning.py
HEALTH=services/backend/app/api/v1/health.py
RUNTIME=services/backend/app/core/runtime.py
GATE=tests/backend/test_scan_adapters.py

BACKUP=$(mktemp -d)
cp "$SCAN" "$BACKUP/scanning.py"
cp "$HEALTH" "$BACKUP/health.py"
cp "$RUNTIME" "$BACKUP/runtime.py"
cp "$GATE" "$BACKUP/gate.py"

# Restored from copies, never `git checkout --`: a working tree with other uncommitted work in it
# is exactly where that command destroys something nobody meant to lose.
restore() {
  cp "$BACKUP/scanning.py" "$SCAN"
  cp "$BACKUP/health.py" "$HEALTH"
  cp "$BACKUP/runtime.py" "$RUNTIME"
  cp "$BACKUP/gate.py" "$GATE"
}
trap restore EXIT

echo "=== CONTROL 0: clean. Anything but green here invalidates every result below. ==="
$PY -m pytest tests/backend -q --no-header 2>&1 | tail -3

probe() {
  local name="$1"
  echo
  echo "=== $name ==="
  if $PY -m pytest tests/backend -q --no-header >"$BACKUP/out.txt" 2>&1; then
    echo "NOT CAUGHT"
  else
    echo "CAUGHT: $(grep -c '^FAILED' "$BACKUP/out.txt") failing"
    grep '^FAILED' "$BACKUP/out.txt" | head -4
  fi
  restore
}

# 1. The readiness note is removed, so an operator checking the system is never told that
#    nothing scans uploads.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/files/scanning.py")
s = p.read_text()
start = s.find("    readiness_note = (")
end = s.find("    )\n", start) + len("    )\n")
p.write_text(s[:start] + s[end:])
EOF
probe "1. the accepted risk stops telling the readiness endpoint about itself"

# 2. The startup flag is removed, so the warning never fires.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/files/scanning.py")
s = p.read_text()
s = s.replace("    is_accepted_risk = True\n", "")
p.write_text(s)
EOF
probe "2. the accepted risk stops flagging itself at startup"

# 3. A real control starts claiming to be an accepted risk. The warning then fires for a
#    configuration that *is* safe, and a warning that fires when nothing is wrong is one people
#    learn to ignore.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/files/scanning.py")
s = p.read_text()
s = s.replace(
    '    name = POLICY_NONE\n',
    '    name = POLICY_NONE\n    is_accepted_risk = True\n',
)
p.write_text(s)
EOF
probe "3. the fail-closed adapter claims to be an accepted risk"

# 4. The development bypass is allowed into production — the shortcut this whole change exists to
#    avoid. Nothing about behaviour changes; only the name lies.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/files/scanning.py")
s = p.read_text()
start = s.find('        if app_env == "production":')
end = s.find("        self._app_env = app_env", start)
p.write_text(s[:start] + s[end:])
EOF
probe "4. the development bypass is permitted in production"

# 5. A fourth adapter appears, with the gate left intact.
#
# The first version of this control weakened the gate *and* added the adapter, then checked
# whether anything failed. Of course nothing did — it had disabled the detector and the subject in
# the same breath, which proves only that a broken test does not fail. Sabotage one thing.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/files/scanning.py")
s = p.read_text()
s = s.replace(
    "POLICY_NAMES: Final = (POLICY_NONE, POLICY_DEVELOPMENT_BYPASS, POLICY_ACCEPTED_RISK)",
    'POLICY_NAMES: Final = (POLICY_NONE, POLICY_DEVELOPMENT_BYPASS, POLICY_ACCEPTED_RISK, "ghost")',
)
p.write_text(s)
EOF
probe "5. a fourth adapter is added without anybody deciding"

echo
echo "=== restored ==="
git status --short
