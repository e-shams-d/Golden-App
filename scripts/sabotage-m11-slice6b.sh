#!/usr/bin/env bash
# Negative controls for M11 slice 6B — the retention dry run.
#
# The report's value is entirely in what it refuses to claim, so most controls make it claim
# something: that an unknown impact is zero, that a held row would be deleted, that a released hold
# still protects. Control 6 is the one that matters most — it makes the dry run stop being dry.
#
# Control 0 runs the suite CLEAN FIRST. Restores with `cp`, never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:55500/postgres}"

DRY=services/backend/app/retention/dry_run.py
BEAT=services/backend/app/workers/celery_app.py

BACKUP=$(mktemp -d)
cp "$DRY" "$BACKUP/dry_run.py"
cp "$BEAT" "$BACKUP/celery_app.py"

restore() {
  cp "$BACKUP/dry_run.py" "$DRY"
  cp "$BACKUP/celery_app.py" "$BEAT"
}
trap restore EXIT

SUITE="tests/integration/test_retention_dry_run.py"

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

# 1. An unresolvable policy reports zero instead of unknown. The subtlest failure here: the totals
#    look calm and nothing says why.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/retention/dry_run.py")
s = p.read_text()
s = s.replace(
    "                    resolvable=False,\n",
    "                    resolvable=False,\n"
    "                    eligible=0,\n"
    "                    protected_by_legal_hold=0,\n",
)
p.write_text(s)
EOF
probe "1. an unknown impact is reported as zero"

# 2. A legal hold stops protecting, so the report would offer a held row for deletion.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/retention/dry_run.py")
s = p.read_text()
s = s.replace("            .where(model.id.not_in(held))\n", "")
p.write_text(s)
EOF
probe "2. a legal hold no longer protects a row"

# 3. A *released* hold keeps protecting, which makes retention impossible to ever apply. The
#    opposite error to control 2 and just as wrong.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/retention/dry_run.py")
s = p.read_text()
s = s.replace("        LegalHold.released_at.is_(None),\n", "")
p.write_text(s)
EOF
probe "3. a released hold still protects"

# 4. The age cutoff is dropped, so every row of the resource type is reported eligible.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/retention/dry_run.py")
s = p.read_text()
s = s.replace("        older = aged_by < cutoff", "        older = aged_by.is_not(None)")
p.write_text(s)
EOF
probe "4. the retention period is ignored"

# 5. A policy that was never activated is treated as active — proposal and approval collapse into
#    activation, which is the separation the three actor columns exist to express.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/retention/dry_run.py")
s = p.read_text()
s = s.replace(
    "            .where(RetentionPolicy.activated_at.is_not(None))\n",
    "",
)
p.write_text(s)
EOF
probe "5. an unactivated policy is treated as active"

# 6. The dry run stops being dry: it deletes what it found. This is the control the whole slice
#    exists to keep failing.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/retention/dry_run.py")
s = p.read_text()
s = s.replace(
    "    return RetentionDryRun(impacts=tuple(impacts))",
    "    from sqlalchemy import delete as _d\n"
    "    for _i in impacts:\n"
    "        if _i.resolvable and _i.eligible:\n"
    "            _m, _a = RESOLVERS[_i.resource_type]\n"
    "            session.execute(\n"
    "                _d(_m).where(_a < now - timedelta(seconds=_i.retention_seconds))\n"
    "            )\n"
    "            session.commit()\n"
    "    return RetentionDryRun(impacts=tuple(impacts))",
)
p.write_text(s)
EOF
probe "6. the dry run deletes what it found"

# 7. The schedule entry is removed, so the reader exists and nothing runs it — the shape this
#    milestone keeps finding.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/workers/celery_app.py")
s = p.read_text()
start = s.find('    "retention-dry-run": {')
end = s.find("    },\n", start) + len("    },\n")
p.write_text(s[:start] + s[end:])
EOF
probe "7. the dry run has no caller again"

echo
echo "=== restored ==="
git status --short
