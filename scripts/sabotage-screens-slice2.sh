#!/usr/bin/env bash
# Negative controls for screens slice 2.
#
# Each sabotage is a change a reviewer could plausibly wave through, and each must make exactly
# one obligation's test fail. A test that survives its sabotage is proving nothing.
#
# Restores from a byte copy, not `git checkout --`, which does nothing for a file git has never
# seen and silently leaves the sabotage in place.

set -uo pipefail
# Not `dirname $0`: this script is normally run from a line-ending-stripped copy under /tmp, which
# would resolve the repo root to `/` and then silently do nothing at all — the failure mode reads
# as seven clean NOT CAUGHTs.
cd "$(git rev-parse --show-toplevel)" || exit 1

PAGE="apps/admin-web/app/batches/[batchId]/versions/[versionId]/page.tsx"
DIALOG="apps/admin-web/components/decision-dialog.tsx"
BATCHES="apps/admin-web/src/batches.ts"
BACKUP="$(mktemp -d)"

cp "$PAGE" "$BACKUP/page.tsx"
cp "$DIALOG" "$BACKUP/dialog.tsx"
cp "$BATCHES" "$BACKUP/batches.ts"

restore() {
  cp "$BACKUP/page.tsx" "$PAGE"
  cp "$BACKUP/dialog.tsx" "$DIALOG"
  cp "$BACKUP/batches.ts" "$BATCHES"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

run() {
  local label="$1" expect="$2"
  local out
  out="$(cd apps/admin-web && npx vitest run test/decision-dialog.test.ts 2>&1)"

  # A run that never reached the tests is neither a pass nor a fail, and must not be reported as
  # one. `--reporter=basic` was removed in vitest 4 and crashed the runner before it collected
  # anything; every sabotage then read as NOT CAUGHT, which is the most misleading answer available.
  if ! printf '%s' "$out" | grep -qE 'Tests +[0-9]+'; then
    printf '  INVALID RUN  %s\n' "$label"
    printf '%s\n' "$out" | tail -3
    restore
    return
  fi

  if printf '%s' "$out" | grep -qE 'Tests +.*[0-9]+ failed'; then
    printf '  CAUGHT   %-46s' "$label"
    if printf '%s' "$out" | grep -q "$expect"; then
      echo "(on: $expect)"
    else
      echo "*** WRONG ASSERTION *** expected to see: $expect"
      printf '%s\n' "$out" | grep -E '(×|✗)' | head -8
    fi
  else
    printf '  NOT CAUGHT  %s\n' "$label"
  fi
  restore
}

echo "== screens slice 2 negative controls =="

# 1. UI-APPROVE-001. Read the hash at submit time instead of the captured one. `view` is in scope,
#    so this typechecks and the happy path passes: the server is quoted a hash that matches, just
#    not the one the manager read.
perl -0pi -e 's/expectedContentHash: captured\.hash/expectedContentHash: view.version.content_hash/g' "$PAGE"
run "hash re-read at submit" "submits the captured hash"

# 2. UI-APPROVE-002. Announce success before the request. The screen reloads either way, so a
#    manual click looks identical — until the command fails.
perl -0pi -e 's/(setBusy\(true\);\n    setError\(null\);)/$1\n    onDecided();/' "$PAGE"
run "UI updated before the server answered" "calls onDecided after the command resolves"

# 3. UI-STALE-002. Keep the decision section rendered next to the banner. A tidy-looking change:
#    the banner warns, the buttons stay, and the open dialog is now pointed at the replacement.
perl -0pi -e 's/(\{t\("admin\.decide\.staleLink"\)\}\n                <\/Link>\n              <\/div>)/$1\n            \/\/ SABOTAGE\n            <Decide batchId={phase.view.batch.id} onDecided={() => void load()} view={phase.view} \/>/' "$PAGE"
run "decision section survives the stale branch" "does not render the decision section"

# 4. UI-STALE-001. Drop the link to the current version. The banner still warns; the manager has
#    to go find the replacement themselves.
perl -0pi -e 's/data-testid="stale-current-link"/data-testid="stale-link"/' "$PAGE"
run "no link to the current version" "links to the current version"

# 5. UI-REJECT-001. Let a rejection through without a reason. The server still requires one, so
#    this shows up as a refusal after the button was pressed.
perl -0pi -e 's/\(kind === "approve" \|\| reason\.trim\(\)\.length > 0\)/true/' "$DIALOG"
run "rejection needs no reason" "requires the reason before the button enables"

# 6. The staleness comparison. Remembered rather than derived: correct on first load, wrong after.
perl -0pi -e 's/return current\.version\.id !== renderedVersionId;/return false;/' "$BATCHES"
run "staleness always false" "decides staleness from the rendered id"

# 7. S-1. Round a fractional Toman to zero — the bug this slice found in slice 1's code.
perl -0pi -e 's/const whole = digits\.length > 1 \? digits\.slice\(0, -1\) : "0";/const whole = digits.slice(0, -1);\n  if (digits.length <= 1) return "0";/' "$BATCHES"
run "fractional Toman rounded away" "divides by ten without floating point"

echo "== done =="
