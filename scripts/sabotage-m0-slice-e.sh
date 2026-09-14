#!/usr/bin/env bash
# Negative controls for M0 slice E — the candidate drawer and the attempt search it needed.
#
# Controls 1 and 2 are the ones worth reading. This drawer is the only place in the system where a
# person could believe money had moved because a button implied it: accepting a candidate marks
# nothing paid, and `05_API_Specification.md:1810` says so in terms. Both controls leave a working,
# usable drawer and remove only the sentence that says what has *not* happened.
#
# Control 0 runs the suite CLEAN FIRST. Restores with `cp`, never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@172.17.0.2:5432/postgres}"

ROUTE=services/backend/app/api/v1/payment_attempts.py
DRAWER=apps/admin-web/components/segment-candidates.tsx
WORKSPACE=apps/admin-web/app/bank-result-bundles/\[bundleId\]/page.tsx
BUNDLES=apps/admin-web/src/bundles.ts
RESULTS=apps/admin-web/src/payment-results.ts
MESSAGES=packages/localization/src/messages.ts
BATCHLINK=apps/admin-web/components/bundle-batch-link.tsx

BACKUP=$(mktemp -d)
cp "$ROUTE" "$BACKUP/payment_attempts.py"
cp "$DRAWER" "$BACKUP/drawer.tsx"
cp "$WORKSPACE" "$BACKUP/workspace.tsx"
cp "$BUNDLES" "$BACKUP/bundles.ts"
cp "$RESULTS" "$BACKUP/results.ts"
cp "$MESSAGES" "$BACKUP/messages.ts"
cp "$BATCHLINK" "$BACKUP/batch-link.tsx"

restore() {
  cp "$BACKUP/payment_attempts.py" "$ROUTE"
  cp "$BACKUP/drawer.tsx" "$DRAWER"
  cp "$BACKUP/workspace.tsx" "$WORKSPACE"
  cp "$BACKUP/bundles.ts" "$BUNDLES"
  cp "$BACKUP/results.ts" "$RESULTS"
  cp "$BACKUP/messages.ts" "$MESSAGES"
  cp "$BACKUP/batch-link.tsx" "$BATCHLINK"
}
trap restore EXIT

SUITE="tests/backend tests/integration/test_payment_results.py"

run_suite() {
  # shellcheck disable=SC2086
  $PY -m pytest -c services/backend/pyproject.toml $SUITE -q --no-header >"$BACKUP/out.txt" 2>&1
  local backend=$?
  (cd apps/admin-web && pnpm vitest run test/segment-candidates.test.ts test/workspace-screens.test.ts >>"$BACKUP/out.txt" 2>&1)
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
    grep -E '^FAILED' "$BACKUP/out.txt" | head -4
    grep -E 'Tests .*failed|FAIL ' "$BACKUP/out.txt" | head -3
  fi
  restore
}

# 1. **The sentence that says what has not happened, removed.** The drawer still lists candidates,
#    still accepts, still rejects. Only the line telling an operator that acceptance marks nothing
#    paid is gone — a working screen with one honest sentence missing.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/admin-web/components/segment-candidates.tsx")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    '                      <p className="text-xs text-[var(--muted)]">{t("candidate.acceptNotPaid")}</p>\n',
    "",
)
assert s != before, "control 1 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "1. the drawer stops saying that accepting marks nothing paid"

# 2. The same claim attacked through the *string* rather than the markup. The key still exists, the
#    screen still renders it, and the sentence now describes what acceptance does instead of what it
#    does not — which is how this guarantee would actually be lost in practice, to a rewrite.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("packages/localization/src/messages.ts")
s = p.read_text(encoding="utf-8")
before = s
start = s.index('"candidate.acceptNotPaid":')
end = s.index('"candidate.rejectReason"')
s = s[:start] + '"candidate.acceptNotPaid":\n    "این رسید به این پرداخت نسبت داده می‌شود.",\n  ' + s[end:]
assert s != before, "control 2 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "2. the Persian sentence describes what acceptance does, not what it does not"

# 3. **A filter is added to the route and not to the spec.** This control replaces an earlier one
#    that removed a `require_filterable` call from the request path; that was NOT CAUGHT, and
#    correctly so — every name in the loop is a literal already in the spec, so the call could not
#    fail. The mistake it was aimed at is this one, and it arrives at a different moment: a new
#    parameter works, and the record of what this read can be narrowed by silently stops being true.
#
#    `trader_id` is the field chosen because it is one §17.1 lists and the route records as not
#    built — so this is the exact shape of somebody implementing a documented filter in a hurry.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/payment_attempts.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "    bank_tracking_number: Annotated[str | None, Query(max_length=128)] = None,\n",
    "    bank_tracking_number: Annotated[str | None, Query(max_length=128)] = None,\n"
    "    trader_id: Annotated[uuid.UUID | None, Query()] = None,\n",
)
assert s != before, "control 3 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "3. a filter is added to the route and not to the allowlist"

# 4. The search response grows the beneficiary name. It renders, it is useful, and it discloses more
#    than the detail read it links to — while POL-003 is open.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/payment_attempts.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "    bank_tracking_number: str | None\n    bank_result_at: datetime | None\n    created_at: datetime\n    record_version: int\n",
    "    bank_tracking_number: str | None\n    bank_result_at: datetime | None\n    created_at: datetime\n    record_version: int\n    beneficiary_name_snapshot: str\n",
    1,
)
s = s.replace(
    "        created_at=attempt.created_at,\n        record_version=attempt.record_version,\n    )\n",
    "        created_at=attempt.created_at,\n        record_version=attempt.record_version,\n        beneficiary_name_snapshot=attempt.beneficiary_name_snapshot,\n    )\n",
    1,
)
assert s != before, "control 4 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "4. the search response discloses the beneficiary name"

# 5. The rejection sends an empty reason. The server refuses it, so nothing is corrupted — the
#    operator simply gets a 400 for a field the screen let them leave blank.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/admin-web/components/segment-candidates.tsx")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    '                        disabled={busy || (reasons[candidate.id] ?? "").trim() === ""}',
    "                        disabled={busy}",
)
assert s != before, "control 5 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "5. a rejection can be sent with no reason"

# 6. The amount goes through `Number` with no safety check. Works for every amount anybody will type
#    by hand, and silently searches for a *different* amount once a figure exceeds 2^53 — finding a
#    plausible wrong attempt rather than none.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/admin-web/components/segment-candidates.tsx")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    '    if (digits !== "" && !Number.isSafeInteger(Number(digits))) {\n      setNotice(t("candidate.amountTooLarge"));\n      setBusy(false);\n      return;\n    }\n',
    "",
)
assert s != before, "control 6 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "6. an amount too large for a JavaScript number is searched anyway"

# 7. The drawer stops remounting when another segment is chosen. Everything renders; the previous
#    segment's candidates and search results stay on screen, and a decision lands on the wrong
#    receipt while the operator is looking at the right one.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/admin-web/app/bank-result-bundles/[bundleId]/page.tsx")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "<SegmentCandidates key={selectedSegment.id} segment={selectedSegment} />",
    "<SegmentCandidates segment={selectedSegment} />",
)
assert s != before, "control 7 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "7. choosing another segment leaves the previous one's candidates on screen"

# 8. A refused segment list takes the whole workspace down. A role holding `bank_result_bundle.read`
#    and not the candidate grant loses the crop surface too — the thing this workspace is for.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/admin-web/app/bank-result-bundles/[bundleId]/page.tsx")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "          try {\n            setSegments(await listSegments(bundleId));\n          } catch {\n            setSegments([]);\n          }\n",
    "          setSegments(await listSegments(bundleId));\n",
)
assert s != before, "control 8 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "8. a refused segment list fails the crop surface with it"

# 9. **The file name decides instead of suggesting.** The batch is linked the moment a name matches,
#    with no confirmation. It works — and works *correctly* whenever the name is untouched, which is
#    most of the time. The failure arrives on the day a bank renames a file, and it is silent: the
#    bundle attaches to the wrong batch, and every receipt in it is matched against payments it has
#    nothing to do with. This is the half of the owner's 2026-09-13 suggestion that was not taken.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/admin-web/components/bundle-batch-link.tsx")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace('{t("batchLink.suggestionIsAGuess")}', "")
assert s != before, "control 9 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "9. the file-name suggestion stops saying it is a guess"

# 10. The pattern loosens to a bare date. Every real batch number still matches, so nothing looks
#     broken — and a file called `20260913-results.xlsx` now pre-selects a batch chosen by the
#     calendar. The operator confirms a suggestion rather than making a choice.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/admin-web/src/bundles.ts")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "/(?<![0-9A-Za-z])PB-\\d{8}-\\d{6}(?!\\d)/",
    "/(?<![0-9A-Za-z])(?:PB-)?\\d{8}(?:-\\d{6})?/",
)
assert s != before, "control 10 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "10. the batch-number pattern matches a bare date"

# 11. A superseded link disappears instead of staying visible. The screen is tidier and the question
#     "who attached this bundle to that batch, and when did it change" stops being answerable from
#     the screen that changed it — while the row is still in the database.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("apps/admin-web/components/bundle-batch-link.tsx")
s = p.read_text(encoding="utf-8")
before = s
start = s.index("      {bundle.batch_links.some((link) => link.replaced_at !== null) ? (")
end = s.index("      {batches === null ? (")
s = s[:start] + s[end:]
assert s != before, "control 11 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "11. superseded batch links vanish from the screen"

echo
echo "=== restored ==="
git status --short "$ROUTE" "$DRAWER" "$WORKSPACE" "$BUNDLES" "$RESULTS" "$MESSAGES" "$BATCHLINK"
