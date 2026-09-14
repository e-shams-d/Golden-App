#!/usr/bin/env bash
# Negative controls for M12 slice 1 — the page-cache gate.
#
# **This gate was written because a list went stale in silence across three milestones.** Its whole
# value is failing when the list and the pages disagree, so each control below reproduces one of the
# ways they drifted apart in the first place: a page added and not listed, a page renamed and the old
# pattern left behind, and an exemption that outlived its page.
#
# The gate already failed five times against its author's own data while being written. That is
# encouraging and is not evidence: a test can be wrong in the direction that fails, too.
#
# Control 0 runs the suite CLEAN FIRST. Restores with `cp`, never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
GATE=tests/backend/test_authenticated_pages_are_not_cacheable.py
ADMIN=apps/admin-web/next.config.ts
TRADER=apps/trader-pwa/next.config.ts

BACKUP=$(mktemp -d)
cp "$GATE" "$BACKUP/gate.py"
cp "$ADMIN" "$BACKUP/admin.ts"
cp "$TRADER" "$BACKUP/trader.ts"
CREATED=""

restore() {
  cp "$BACKUP/gate.py" "$GATE"
  cp "$BACKUP/admin.ts" "$ADMIN"
  cp "$BACKUP/trader.ts" "$TRADER"
  [ -n "$CREATED" ] && rm -rf "$CREATED"
  CREATED=""
}
trap restore EXIT

run_suite() {
  $PY -m pytest -c services/backend/pyproject.toml "$GATE" -q --no-header >"$BACKUP/out.txt" 2>&1
}

echo "=== CONTROL 0: clean. Anything but green here invalidates every result below. ==="
if run_suite; then
  echo "clean: green"
else
  echo "clean: NOT GREEN — stop."
  tail -20 "$BACKUP/out.txt"
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
    grep -E '^FAILED|AssertionError' "$BACKUP/out.txt" | head -3
  fi
  restore
}

# 1. **The drift this gate was written for.** A new authenticated page appears and nobody adds it to
#    the list. The application works; the page is cacheable. This is exactly how thirteen admin
#    pages came to be unprotected.
mkdir -p apps/admin-web/app/settlements
CREATED=apps/admin-web/app/settlements
cat > apps/admin-web/app/settlements/page.tsx <<'EOF'
export default function SettlementsPage() {
  return <main>settlements</main>;
}
EOF
probe "1. a new authenticated page is not added to the list"

# 2. The other direction, and the one that hides the first: a page is renamed and the old pattern is
#    left behind. The list gets longer while its coverage shrinks, which is what made thirteen
#    absences unremarkable beside nine entries.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/admin-web/next.config.ts")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace('"/requests/:path*",', '"/payment-requests/:path*",')
assert s != before, "control 2 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "2. a renamed page leaves its old pattern behind"

# 3. An exemption outlives its page. The allowlist is where a gate like this rots: a name left here
#    after the page goes is inherited, silently, by whatever takes that name next.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("tests/backend/test_authenticated_pages_are_not_cacheable.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    '        "register": "self-registration, which by definition precedes an account",',
    '        "register": "self-registration, which by definition precedes an account",\n'
    '        "invoices": "a page that was deleted two milestones ago and is still excused here",',
)
assert s != before, "control 3 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "3. an exemption outlives the page it excused"

# 4. An exemption with no reason. The allowlist keeps its shape and stops carrying the one thing
#    that makes it evaluable — `an-exemption-must-name-its-mechanism`, in its cheapest form.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("tests/backend/test_authenticated_pages_are_not_cacheable.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    '        "register": "self-registration, which by definition precedes an account",',
    '        "register": "public",',
)
assert s != before, "control 4 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "4. a public page is excused without saying why"

# 5. **A sensitive trader page is quietly dropped.** `/evidence` holds the receipts a trader
#    uploaded. Removing its pattern changes nothing visible, on an application installed on a
#    personal phone where a disk-cached page outlives the session that fetched it.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/trader-pwa/next.config.ts")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace('        "/evidence/:path*",\n', "")
assert s != before, "control 5 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "5. the trader's evidence page loses its no-store pattern"

echo
echo "=== restored ==="
git status --short "$GATE" "$ADMIN" "$TRADER" apps/admin-web/app/
