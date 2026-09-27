#!/usr/bin/env bash
# Negative controls for M12 slice 5 — the injection surfaces and the origin check.
#
# **Two of these protections were already true and untested**, which is the weakest state a control
# can be in: it holds today and nothing notices the day it stops. The controls below each remove one
# and leave a system that starts, serves, and logs.
#
# Control 5 is the one to read. It does not remove the origin check — it makes it refuse
# *everything*, which is what "tightening" it looks like from the inside and which breaks every
# non-browser caller while appearing stricter.
#
# Control 0 runs the suite CLEAN FIRST. Restores with `cp`, never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql+psycopg://postgres:postgres@172.17.0.2:5432/postgres}"

LOGGING=services/backend/app/core/logging.py
AUTH=services/backend/app/api/v1/auth.py
CANVAS=apps/admin-web/components/crop-canvas.tsx

WORK=$(mktemp -d)
cp "$LOGGING" "$WORK/logging.py"
cp "$AUTH" "$WORK/auth.py"
cp "$CANVAS" "$WORK/canvas.tsx"

restore_files() {
  cp "$WORK/logging.py" "$LOGGING"
  cp "$WORK/auth.py" "$AUTH"
  cp "$WORK/canvas.tsx" "$CANVAS"
}
trap restore_files EXIT

SUITE="tests/backend/test_injection_surfaces.py tests/integration/test_authentication_flow.py"

run_suite() {
  # shellcheck disable=SC2086
  $PY -m pytest -c services/backend/pyproject.toml $SUITE -q --no-header >"$WORK/out.txt" 2>&1
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

# 1. **A component renders a bank's message as HTML.** It looks like a feature — the bank sends
#    formatted text and this displays it — and it is the one hole React's default closes.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/admin-web/components/crop-canvas.tsx")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "export function CropCanvas(",
    "function RenderBankMessage({ html }: { html: string }) {\n"
    "  return <div dangerouslySetInnerHTML={{ __html: html }} />;\n"
    "}\n\n"
    "export function CropCanvas(",
    1,
)
assert s != before, "control 1 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "1. a component renders supplied text as HTML"

# 2. The same hole without React's warning label — a direct DOM write, in a file that already
#    manipulates DOM geometry for legitimate reasons.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/admin-web/components/crop-canvas.tsx")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "export function CropCanvas(",
    "function showNote(element: HTMLElement, note: string) {\n"
    "  element.innerHTML = note;\n"
    "}\n\n"
    "export function CropCanvas(",
    1,
)
assert s != before, "control 2 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "2. a note is written straight into the DOM"

# 3. **The U+2028 escaping goes.** Logs still parse as JSON, still contain everything, and a
#    browser-based viewer renders one record as two — the defect this slice actually found, put
#    back.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/core/logging.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    '        return line.replace("\\u2028", "\\\\u2028").replace("\\u2029", "\\\\u2029")',
    "        return line",
)
assert s != before, "control 3 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "3. a unicode line separator reaches the log output"

# 4. Redaction is dropped from the message text while the field path keeps it. Every structured
#    call is still redacted; the one place somebody interpolates a connection string is not.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/core/logging.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace('"message": redact_text(record.getMessage()),', '"message": record.getMessage(),')
assert s != before, "control 4 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "4. the log message text stops being redacted"

# 5. **The origin check is "tightened" into refusing an absent Origin.** Stricter by every reading,
#    and it breaks every non-browser caller — a migration script, an operator with curl — while
#    closing nothing a browser could do. This is what the permissive half of the test is for.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/auth.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "    origin = request.headers.get(\"origin\")\n    if origin is None:\n        return\n",
    "    origin = request.headers.get(\"origin\")\n    if origin is None:\n        raise CsrfRequiredError()\n",
)
assert s != before, "control 5 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "5. the origin check refuses an absent Origin as well as a foreign one"

# 6. The origin check goes entirely. Everything works; the CSRF token carries the whole weight
#    again, and the boundary SameSite cannot draw between admin. and trader. is gone.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/auth.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace("    _refuse_a_foreign_origin(request)\n", "")
assert s != before, "control 6 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "6. the origin check is removed entirely"

echo
echo "=== restored ==="
git status --short "$LOGGING" "$AUTH" "$CANVAS"
