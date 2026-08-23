#!/usr/bin/env bash
# Negative controls for screens slice 3 — the export screens and the three prohibitions.
#
# The three the plan names, plus four the absences suggested. Three of slice 3's five obligations
# assert that something is *not* there, and an absence with no control behind it is a sentence
# rather than a test: it passes on an empty file.
#
# `git rev-parse` for the root, not `dirname $0` — this is run from a copy under /tmp, and
# resolving to `/` makes every control report a clean NOT CAUGHT while doing nothing.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PAGE="apps/admin-web/app/bank-exports/[exportId]/page.tsx"
SRC="apps/admin-web/src/bank-exports.ts"
BACKUP="$(mktemp -d)"

cp "$PAGE" "$BACKUP/page.tsx"
cp "$SRC" "$BACKUP/src.ts"

restore() {
  cp "$BACKUP/page.tsx" "$PAGE"
  cp "$BACKUP/src.ts" "$SRC"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

# Colour off. Vitest puts escape sequences between "Tests" and the count, which defeated the
# guard below and reported two correctly-failing controls as INVALID RUN — a harness bug that
# looks exactly like a harness bug worth having, since the alternative reading was NOT CAUGHT.
# Stripping colour at the source beats writing regexes that tolerate escapes.
export NO_COLOR=1
export FORCE_COLOR=0

OUT="$BACKUP/out.txt"

run() {
  local label="$1" expect="$2"
  (cd apps/admin-web && npx vitest run test/export-screens.test.ts) > "$OUT" 2>&1

  # Written to a file rather than captured into a variable. A failing assertion here prints the
  # whole app bundle as its diff — four thousand lines — and piping that through a shell variable
  # lost the summary line, so two correctly-failing controls reported INVALID RUN. The file is also
  # left behind for the WRONG ASSERTION branch to quote from.
  #
  # A run that never reached the tests is neither a pass nor a fail. Slice 2's harness reported
  # seven clean NOT CAUGHTs from a runner that crashed on startup, which reads as seven insensitive
  # tests instead of one broken command.
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
      grep -E '^ *(×|✗|FAIL)' "$OUT" | head -6
    fi
  else
    printf '  NOT CAUGHT  %s\n' "$label"
  fi
  restore
}

echo "== screens slice 3 negative controls =="

# 1. UI-PREVIEW-001, the plan's first named control. Paraphrase the banner — and paraphrase it the
#    way somebody actually would, by retyping it with a hyphen instead of an em dash. It still
#    reads as a warning and is no longer the words the document requires.
perl -0pi -e 's/export const PREVIEW_BANNER = ".*";/export const PREVIEW_BANNER = "PREVIEW - NOT APPROVED FOR BANK SUBMISSION";/' "$SRC"
run "the banner is retyped with a hyphen" "matches the specification character"

# 2. UI-PREVIEW-002, the plan's second. Add a mark-sent control to the preview screen. Written the
#    way it would arrive: a button calling the real endpoint.
perl -0pi -e 's/(function Cell\(\{ children, label \})/function MarkSent({ id }: { id: string }) {\n  return (\n    <button onClick={() => fetch(`\/bank-exports\/\${id}\/mark-sent-to-bank`, { method: "POST" })} type="button">\n      mark sent\n    <\/button>\n  );\n}\n\n$1/' "$PAGE"
run "a mark-sent control appears" "no mark-as-sent control anywhere"

# 3. UI-INTEGRITY-002, the plan's third. The control §14.5 forbids, spelled the obvious way.
perl -0pi -e 's/(function Cell\(\{ children, label \})/function Override() {\n  return <button data-testid="download-anyway" type="button">download anyway<\/button>;\n}\n\n$1/' "$PAGE"
run "an override control appears" "no such phrase in the whole bundle"

# 4. The same obligation, disabled rather than absent. A disabled control is a control: it is one
#    devtools edit from being a live one, and it tells the reader the platform considers the action
#    possible.
perl -0pi -e 's/(      <h3 className="mt-4 font-bold">)/      <button disabled type="button">x<\/button>\n$1/' "$PAGE"
run "quarantine disables instead of omitting" "blocks by not rendering"

# 5. UI-PREVIEW-002's second clause. Label a preview checksum as though it were the official one.
perl -0pi -e 's/preview \? t\("admin\.export\.checksumPreview"\) : t\("admin\.export\.checksum"\)/t("admin.export.checksum")/' "$PAGE"
run "a preview checksum is labelled official" "labels a preview checksum as unofficial"

# 6. UI-EXPORT-001. Drop a §14.4 label. Chosen as the one a screen would plausibly leave out,
#    because it is the only field on the page that is a comparison rather than a value.
perl -0pi -e 's/t\("admin\.export\.approvalMatch"\)/t("admin.export.reference")/' "$PAGE"
run "a §14.4 item loses its label" "renders a label for approval/hash match"

# 7. §14.3. Teach the screen a state the catalogue does not have, which is how a screen written
#    from the document rather than the system starts rendering states the API cannot return.
perl -0pi -e 's/  generation_failed: "admin\.export\.status\.generation_failed",/  generation_failed: "admin.export.status.generation_failed",\n  superseded: "admin.export.status.voided",/' "$SRC"
run "a state the catalogue lacks is added" "labels every status the bank_export"

echo "== done =="
