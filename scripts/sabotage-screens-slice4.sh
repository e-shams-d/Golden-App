#!/usr/bin/env bash
# Negative controls for screens slice 4 — download, mark sent, and §14.6's sentence.
#
# The three the plan names, plus four the obligations suggested.
#
# `git rev-parse` for the root, not `dirname $0` — this is run from a copy under /tmp, and
# resolving to `/` makes every control report a clean NOT CAUGHT while doing nothing at all.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PAGE="apps/admin-web/app/bank-exports/[exportId]/page.tsx"
DIALOG="apps/admin-web/components/mark-sent-dialog.tsx"
SRC="apps/admin-web/src/bank-exports.ts"
SWEEP="apps/admin-web/tests/a11y/shell.spec.ts"
BACKUP="$(mktemp -d)"

cp "$PAGE" "$BACKUP/page.tsx"
cp "$DIALOG" "$BACKUP/dialog.tsx"
cp "$SRC" "$BACKUP/src.ts"
cp "$SWEEP" "$BACKUP/sweep.ts"

restore() {
  cp "$BACKUP/page.tsx" "$PAGE"
  cp "$BACKUP/dialog.tsx" "$DIALOG"
  cp "$BACKUP/src.ts" "$SRC"
  cp "$BACKUP/sweep.ts" "$SWEEP"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

# Colour off, and output to a file. Slice 3 taught both: escape sequences between "Tests" and the
# count defeated the guard, and a four-thousand-line failure diff piped through a shell variable
# lost the summary line entirely — reporting two correctly-failing controls as INVALID RUN.
export NO_COLOR=1
export FORCE_COLOR=0
OUT="$BACKUP/out.txt"

run() {
  local label="$1" expect="$2"
  (cd apps/admin-web && npx vitest run test/download-and-sent.test.ts) > "$OUT" 2>&1

  if ! grep -qE '^ *Tests +[0-9]+' "$OUT"; then
    printf '  INVALID RUN  %s\n' "$label"
    tail -4 "$OUT"
    restore
    return
  fi

  if grep -qE '^ *Tests +.*[0-9]+ failed' "$OUT"; then
    printf '  CAUGHT   %-46s' "$label"
    if grep -q "$expect" "$OUT"; then
      echo "(on: $expect)"
    else
      echo "*** WRONG ASSERTION *** expected: $expect"
      grep -E '^ *(×|✗)' "$OUT" | head -6
    fi
  else
    printf '  NOT CAUGHT  %s\n' "$label"
  fi
  restore
}

echo "== screens slice 4 negative controls =="

# 1. UI-DOWNLOAD-001, the plan's first named control. Paraphrase the sentence — and do it the way
#    somebody actually would, by tightening the wording. It still says the right thing and is no
#    longer the words §14.6 gives.
perl -0pi -e 's/^export const DOWNLOAD_IS_NOT_SENDING =\n  ".*";$/export const DOWNLOAD_IS_NOT_SENDING = "Downloading does not mean the file was sent to the bank.";/m' "$SRC"
run "the sentence is tightened" "matches the specification character"

# 2. UI-SENT-002, the plan's second. Derive the reminder from the timestamps. This is the change a
#    reviewer waves through — it looks like the same condition, and it silently omits `export_type`,
#    so a downloaded preview grows a reminder to confirm sending a file nobody may send.
perl -0pi -e 's/  return view\.awaiting_send_confirmation;/  return view.downloaded_at !== null \&\& view.sent_to_bank_marked_at === null;/' "$SRC"
run "the reminder is inferred client-side" "ignores the timestamps entirely"

# 3. UI-SENT-003, the plan's third. Let the command take a batch as well, which is all it takes for
#    a later edit to send the wrong one.
perl -0pi -e 's/export async function markSentToBank\(input: \{\n  exportId: string;/export async function markSentToBank(input: {\n  exportId: string;\n  batchId: string;/' "$SRC"
run "the command accepts a batch id" "the command.s signature offers no other"

# 4. UI-DOWNLOAD-001's placement. Move the sentence after the control: still verbatim, still on the
#    page, and read only by somebody who already has the file.
perl -0pi -e 's/(      <p\n        className="font-black"\n        data-testid="download-is-not-sending"\n        dir="ltr"\n        lang="en"\n      >\n        \{DOWNLOAD_IS_NOT_SENDING\}\n      <\/p>\n)//' "$PAGE"
perl -0pi -e 's/(      \{open \? \()/      <p data-testid="download-is-not-sending" dir="ltr" lang="en">{DOWNLOAD_IS_NOT_SENDING}<\/p>\n$1/' "$PAGE"
run "the sentence moves below the control" "beside the download control"

# 5. UI-SENT-001. Drop one of §14.7's ten from the summary — the checksum, which is the field that
#    identifies *which file* and the one a tidier dialog would lose first.
perl -0pi -e 's/t\("admin\.export\.checksumAndIntegrity"\)/t("admin.export.reference")/' "$DIALOG"
run "a §14.7 field leaves the summary" "shows checksum/integrity state"

# 6. UI-SENT-001's ordering. Show the summary after the submit button, which is a confirmation that
#    confirms nothing.
perl -0pi -e 's/data-testid="mark-sent-summary"/data-testid="summary-moved"/' "$DIALOG"
run "the summary is no longer identifiable" "shows them before the command"

# 7. TRACE-SCREENS-001. Remove a screen from the sweep. This is the control that matters most,
#    because the obligation exists to catch exactly this and it already caught two real omissions.
perl -0pi -e 's/^  "\/bank-exports\/00000000-0000-4000-8000-000000000002",$//m' "$SWEEP"
run "a screen leaves the a11y sweep" "covers every route"

echo "== done =="
