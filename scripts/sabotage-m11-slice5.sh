#!/usr/bin/env bash
# Negative controls for M11 slice 5 — what a technical administrator may not see.
#
# Section 19 :1298's last rule is the slice's subject, so most controls are disclosure: put a
# trader, an amount or an IBAN into a technical queue's response and see whether anything notices.
# Control 6 is the registry one: a blocked queue quietly served under a borrowed grant.
#
# Control 0 runs the suite CLEAN FIRST. Restores with `cp`, never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:55500/postgres}"

TECH=services/backend/app/queues/technical.py
REGISTRY=services/backend/app/queues/registry.py
CONTRACT=services/backend/app/api/v1/queues.py

BACKUP=$(mktemp -d)
cp "$TECH" "$BACKUP/tech.py"
cp "$REGISTRY" "$BACKUP/registry.py"
cp "$CONTRACT" "$BACKUP/queues.py"

restore() {
  cp "$BACKUP/tech.py" "$TECH"
  cp "$BACKUP/registry.py" "$REGISTRY"
  cp "$BACKUP/queues.py" "$CONTRACT"
}
trap restore EXIT

SUITE="tests/integration/test_queue_contract.py"

echo "=== CONTROL 0: clean. Anything but green here invalidates every result below. ==="
$PY -m pytest $SUITE tests/backend -q --no-header 2>&1 | tail -3

probe() {
  local name="$1"
  echo
  echo "=== $name ==="
  if $PY -m pytest $SUITE tests/backend -q --no-header >"$BACKUP/out.txt" 2>&1; then
    echo "NOT CAUGHT"
  else
    echo "CAUGHT: $(grep -c '^FAILED' "$BACKUP/out.txt") failing"
    grep '^FAILED' "$BACKUP/out.txt" | head -4
  fi
  restore
}

# 1. The queue names the storage key instead of the filename. A storage key embeds nothing
#    financial here, so this should NOT be caught by the disclosure test — it is included to keep
#    the disclosure assertions honest about what they actually check.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/technical.py")
s = p.read_text()
s = s.replace("        reference=row.original_filename,", "        reference=row.storage_key,")
p.write_text(s)
EOF
probe "1. the row names the storage key rather than the filename"

# 2. The scan filter goes, so every file in the system becomes quarantine work.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/technical.py")
s = p.read_text()
s = s.replace(
    "    return _internal(statement, actor).where(FileObject.scan_status == SCAN_QUARANTINED)",
    "    return _internal(statement, actor)",
)
p.write_text(s)
EOF
probe "2. every file in the system is quarantine work"

# 3. The queue is opened to the accountant, who holds financial grants the rule keeps separate.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/technical.py")
s = p.read_text()
s = s.replace('permission="file.quarantine_review"', 'permission="payment_request.read"')
p.write_text(s)
EOF
probe "3. the technical queue is guarded by an accountant's grant"

# 4. The shared row shape grows a financial field, which every queue inherits — including the
#    technical one. This is the disclosure decision made once and paid twenty-four times.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/queues.py")
s = p.read_text()
s = s.replace(
    "    created_at: datetime\n    trader_id: uuid.UUID | None",
    "    created_at: datetime\n    trader_id: uuid.UUID | None\n    amount_irr: int | None = None",
)
p.write_text(s)
EOF
probe "4. the shared queue row grows an amount field"

# 5. A blocked queue is served under a borrowed permission — exactly what its reason forbids.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/registry.py")
s = p.read_text()
s = s.replace(
    "BUILT: dict[str, QueueDefinition[Any]] = {\n"
    "    queue.name: queue\n"
    "    for queue in (*_ACCOUNTANT, *_MANAGER_AND_WAREHOUSE, *_TECHNICAL)\n"
    "}",
    "import dataclasses as _dc\n"
    "BUILT: dict[str, QueueDefinition[Any]] = {\n"
    "    queue.name: queue\n"
    "    for queue in (*_ACCOUNTANT, *_MANAGER_AND_WAREHOUSE, *_TECHNICAL)\n"
    "}\n"
    'BUILT["backup-health-warnings"] = _dc.replace(\n'
    '    QUARANTINED_FILES, name="backup-health-warnings"\n'
    ")",
)
p.write_text(s)
EOF
probe "5. a queue recorded as blocked is served under a borrowed grant"

# 6. A blocked entry loses its reason, so the collection becomes a shrug.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/registry.py")
s = p.read_text()
# The first draft of this control replaced a *later* sentence and left "Unblocked by" standing in
# the line above, so it went NOT CAUGHT — the sabotage did not break the property it claimed to.
# It removes the phrase itself now.
s = s.replace(
    '        "no rows for a predicate to select. Unblocked by the milestone that builds the "\n',
    '        "no rows for a predicate to select. Fixed by the milestone that builds the "\n',
)
p.write_text(s)
EOF
probe "6. a blocked queue stops saying what would unblock it"

echo
echo "=== restored ==="
git status --short
