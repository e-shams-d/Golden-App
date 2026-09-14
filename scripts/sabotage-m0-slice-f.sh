#!/usr/bin/env bash
# Negative controls for M0 slice F — the recovery screen.
#
# **Controls 1 and 2 are why this file exists.** The route answers one 401 for an unknown username,
# a wrong temporary password and an account not awaiting recovery, so that it cannot be used to
# learn which of the centre's staff an administrator has just reset. A screen is where that is most
# likely to be undone, and undone with good intentions: "wrong password" is a friendlier message and
# is a claim the server deliberately refused to make. Both controls leave a screen that works and
# looks more helpful than the real one.
#
# Control 0 runs the suite CLEAN FIRST. Restores with `cp`, never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
if [ -z "${INTEGRATION_ADMIN_DATABASE_URL:-}" ]; then
    host=$(docker inspect m2-itest-pg \
        --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null || true)
    [ -n "$host" ] && export INTEGRATION_ADMIN_DATABASE_URL="postgresql+psycopg://postgres:postgres@${host}:5432/postgres"
fi

SCREEN=apps/admin-web/app/recover-password/page.tsx
LOGIN=apps/admin-web/app/login/page.tsx
MODULE=apps/admin-web/src/password.ts
MESSAGES=packages/localization/src/messages.ts
SWEEP=apps/admin-web/tests/a11y/shell.spec.ts

BACKUP=$(mktemp -d)
cp "$SCREEN" "$BACKUP/screen.tsx"
cp "$LOGIN" "$BACKUP/login.tsx"
cp "$MODULE" "$BACKUP/password.ts"
cp "$MESSAGES" "$BACKUP/messages.ts"
cp "$SWEEP" "$BACKUP/sweep.ts"

restore() {
  cp "$BACKUP/screen.tsx" "$SCREEN"
  cp "$BACKUP/login.tsx" "$LOGIN"
  cp "$BACKUP/password.ts" "$MODULE"
  cp "$BACKUP/messages.ts" "$MESSAGES"
  cp "$BACKUP/sweep.ts" "$SWEEP"
}
trap restore EXIT

run_suite() {
  $PY -m pytest -c services/backend/pyproject.toml tests/backend -q --no-header >"$BACKUP/out.txt" 2>&1
  local backend=$?
  (cd apps/admin-web && pnpm vitest run test/recover-password.test.ts >>"$BACKUP/out.txt" 2>&1)
  local frontend=$?
  [ $backend -eq 0 ] && [ $frontend -eq 0 ]
}

echo "=== CONTROL 0: clean. Anything but green here invalidates every result below. ==="
if run_suite; then
  echo "clean: green"
else
  echo "clean: NOT GREEN — stop. Every result below is meaningless."
  tail -25 "$BACKUP/out.txt"
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
    grep -E '^FAILED' "$BACKUP/out.txt" | head -3
    grep -E 'FAIL |Tests .*failed' "$BACKUP/out.txt" | head -3
  fi
  restore
}

# 1. **The screen becomes a status oracle, helpfully.** A 401 is reported as "wrong password", which
#    is friendlier, is right roughly a third of the time, and tells anybody who can reach this page
#    that the username exists and the account is awaiting recovery — which is precisely what
#    `12_Security_RBAC_Audit.md:403` keeps the single answer for.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/admin-web/app/recover-password/page.tsx")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    'setNotice(status === 429 ? t("recover.tooMany") : t("recover.refused"));',
    'setNotice(\n        status === 429\n          ? t("recover.tooMany")\n          : status === 401\n            ? t("recover.wrongPassword")\n            : t("recover.refused"),\n      );',
)
assert s != before, "control 1 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "1. a 401 is reported as a wrong password"

# 2. The same guarantee attacked through the *string* rather than the branch. The screen still shows
#    one message for every failure; the message now names one cause. This is how the guarantee would
#    actually be lost — to a rewrite by somebody making the copy friendlier.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("packages/localization/src/messages.ts")
s = p.read_text(encoding="utf-8")
before = s
start = s.index('"recover.refused":')
end = s.index('"recover.tooMany"')
s = s[:start] + '"recover.refused":\n    "گذرواژه موقت درست نیست.",\n  ' + s[end:]
assert s != before, "control 2 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "2. the refusal message names one cause instead of three"

# 3. The screen signs the person in. It cannot — the response carries no session — so the redirect
#    lands on a 401 and the recovery reads as having failed after it succeeded.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/admin-web/app/recover-password/page.tsx")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    '      setPhase({ kind: "done" });',
    '      setPhase({ kind: "done" });\n      router.replace("/");',
)
assert s != before, "control 3 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "3. the screen redirects as though a session had been issued"

# 4. The repeated-password check goes. The server has no second field to compare against, so a typo
#    is accepted — and leaves somebody holding a password they cannot reproduce with no working
#    credential to try again with. Everything still works whenever the two fields agree.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/admin-web/app/recover-password/page.tsx")
s = p.read_text(encoding="utf-8")
before = s
start = s.index("    if (next !== again) {")
end = s.index("    setBusy(true);", start)
s = s[:start] + s[end:]
assert s != before, "control 4 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "4. a mistyped new password is accepted"

# 5. The link from the login page goes. The screen still exists and still works — and the only
#    person who needs it is the one who cannot sign in to find it.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/admin-web/app/login/page.tsx")
s = p.read_text(encoding="utf-8")
before = s
start = s.index('      <p className="mt-6 text-sm">')
end = s.index("    </main>", start)
s = s[:start] + s[end:]
assert s != before, "control 5 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "5. nothing links to the recovery screen"

# 6. The temporary password field is labelled `new-password`. Renders identically; a password
#    manager now offers to save the credential somebody else chose and communicated.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/admin-web/app/recover-password/page.tsx")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace('autoComplete="current-password"', 'autoComplete="new-password"')
assert s != before, "control 6 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "6. a password manager is told to save the temporary credential"

# 7. The screen drops out of the accessibility sweep. It is the only form here an unauthenticated
#    person fills in, and the only page whose *working* state the sweep opens.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/admin-web/tests/a11y/shell.spec.ts")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace('  "/recover-password",\n', "")
assert s != before, "control 7 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "7. the recovery screen leaves the accessibility sweep"

echo
echo "=== restored ==="
git status --short "$SCREEN" "$LOGIN" "$MODULE" "$MESSAGES" "$SWEEP"
