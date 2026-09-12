#!/usr/bin/env bash
# Negative controls for M0 slice B — the bank configuration read, and the catalogue gate.
#
# The gate is the interesting half. It was written because `bank_profile.activate_version`'s
# catalogue row said `"permission": []` for three days after the owner granted it, and nothing in
# the repository could notice. A gate written for a drift that already happened has to be shown to
# catch that drift, and to catch it in both directions.
#
# Control 0 runs the suite CLEAN FIRST. Restores with `cp`, never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@172.17.0.2:5432/postgres}"

ROUTE=services/backend/app/api/v1/bank_config.py
CATALOG=docs/governance/command_catalog.yaml

BACKUP=$(mktemp -d)
cp "$ROUTE" "$BACKUP/bank_config.py"
cp "$CATALOG" "$BACKUP/command_catalog.yaml"

restore() {
  cp "$BACKUP/bank_config.py" "$ROUTE"
  cp "$BACKUP/command_catalog.yaml" "$CATALOG"
}
trap restore EXIT

SUITE="tests/backend tests/integration/test_bank_version_resolution.py"

echo "=== CONTROL 0: clean. Anything but green here invalidates every result below. ==="
$PY -m pytest -c services/backend/pyproject.toml $SUITE -q --no-header 2>&1 | tail -3

probe() {
  local name="$1"
  echo
  echo "=== $name ==="
  if $PY -m pytest -c services/backend/pyproject.toml $SUITE -q --no-header >"$BACKUP/out.txt" 2>&1; then
    echo "NOT CAUGHT"
  else
    echo "CAUGHT: $(grep -c '^FAILED' "$BACKUP/out.txt") failing"
    grep '^FAILED' "$BACKUP/out.txt" | head -4
  fi
  restore
}

# 1. **The drift this gate was written for, reproduced exactly.** The activation row goes back to
#    claiming no permission exists, which is what it said for three days while the route was
#    guarded by one.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("docs/governance/command_catalog.yaml")
s = p.read_text()
before = s
s = s.replace('      "permission": ["bank_profile.activate_version"],', '      "permission": [],')
assert s != before, "control 1 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "1. the catalogue claims the activation needs no permission"

# 2. The other direction: the *route* drops its guard while the catalogue still names one. A
#    document describing a control that is not there, which is the more dangerous half.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/bank_config.py")
s = p.read_text()
before = s
s = s.replace(
    '    dependencies=[requires(declare("bank_profile.activate_version"))],\n',
    "",
)
assert s != before, "control 2 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "2. the activation route loses its guard"

# 3. A row requires a permission that does not exist — plausible, adjacent to a real name, held by
#    nobody. Every behavioural test still passes, because no route asks for it.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("docs/governance/command_catalog.yaml")
s = p.read_text()
before = s
s = s.replace(
    '      "permission": ["bank_profile.activate_version"],',
    '      "permission": ["bank_profile.activate"],',
)
assert s != before, "control 3 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "3. a command requires a permission the catalogue never declared"

# 4. The new read loses its guard, so anybody with a session can read a bank's transfer limits and
#    cutoff times.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/bank_config.py")
s = p.read_text()
before = s
s = s.replace(
    '    operation_id="getBankProfile",\n'
    "    response_model=BankProfileDetail,\n"
    '    dependencies=[requires(declare("bank_profile.read"))],\n',
    '    operation_id="getBankProfile",\n    response_model=BankProfileDetail,\n',
)
assert s != before, "control 4 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "4. the bank profile read is reachable without a permission"

# 5. The read returns the version rows but not the profile's own pointer, so a screen must infer
#    which version is in force by scanning statuses — and would then agree with itself while the
#    profile pointer said something else.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/bank_config.py")
s = p.read_text()
before = s
s = s.replace("            current_version_id=profile.current_version_id,\n", "            current_version_id=None,\n")
assert s != before, "control 5 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "5. the read never says which version is in force"

echo
echo "=== restored ==="
git status --short
