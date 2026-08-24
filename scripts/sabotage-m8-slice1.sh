#!/usr/bin/env bash
# Negative controls for M8 slice 1 — the bundle, its files, and the batches it may point at.
#
# The three the plan names, plus four the constraints suggested. Every control targets a claim that
# would otherwise be a sentence in a docstring.
#
# `git rev-parse` for the root, not `dirname $0`; colour off; output to a file. Slices 2-4 of the
# screens plan taught each of those, in that order.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

MODEL="services/backend/app/db/models/bank_result_bundle.py"
CMD="services/backend/app/commands/bank_result_bundle.py"
API="services/backend/app/api/v1/bank_result_bundles.py"
BACKUP="$(mktemp -d)"

cp "$MODEL" "$BACKUP/model.py"
cp "$CMD" "$BACKUP/cmd.py"
cp "$API" "$BACKUP/api.py"

restore() {
  cp "$BACKUP/model.py" "$MODEL"
  cp "$BACKUP/cmd.py" "$CMD"
  cp "$BACKUP/api.py" "$API"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
UNIT=tests/backend/test_bundle_schema.py
LIVE=tests/integration/test_bundle_intake.py
OUT="$BACKUP/out.txt"

run() {
  local label="$1" expect="$2" target="$3"
  "$PYTHON" -m pytest "$target" -q > "$OUT" 2>&1

  if ! grep -qE '[0-9]+ (passed|failed)' "$OUT"; then
    printf '  INVALID RUN  %s\n' "$label"
    tail -4 "$OUT"
    restore
    return
  fi
  if grep -qE '[0-9]+ (passed, )?[0-9]* *skipped' "$OUT" && ! grep -qE '[0-9]+ (passed|failed)' "$OUT"; then
    printf '  SKIPPED — INVALID  %s\n' "$label"
    restore
    return
  fi

  if grep -qE '[0-9]+ failed' "$OUT"; then
    printf '  CAUGHT   %-44s' "$label"
    if grep -q "$expect" "$OUT"; then
      echo "(on: $expect)"
    else
      echo "*** WRONG ASSERTION *** expected: $expect"
      grep -E '^FAILED' "$OUT" | head -4
    fi
  else
    printf '  NOT CAUGHT  %s\n' "$label"
  fi
  restore
}

echo "== M8 slice 1 negative controls =="

# 1. SVC-BUNDLE-003, the plan's first named control. Increment a count instead of recomputing. The
#    happy path still reports the right number; only a retry diverges — and the CHECK that holds
#    the parts to the whole is what turns the divergence into a refusal rather than a wrong figure.
perl -0pi -e 's/    bundle\.segment_count = total\n    bundle\.resolved_segment_count = resolved\n    bundle\.unresolved_segment_count = total - resolved/    bundle.segment_count += 1\n    bundle.resolved_segment_count = resolved\n    bundle.unresolved_segment_count = total - resolved/' "$CMD"
run "a count is incremented, not recomputed" "counts_are_recomputed_and_reconcile" "$LIVE"

# 2. SVC-BUNDLE-001, the plan's second. Let the link touch the batch. Written the way it would
#    arrive: a status nudge that looks like helpful bookkeeping.
perl -0pi -e 's/(    if bundle\.bank_profile_id is None:)/    batch.record_version += 1\n$1/' "$CMD"
run "linking alters the batch" "changes_nothing_about_the_batch" "$LIVE"

# 3. SEC-BUNDLE-001, the plan's third. Drop the permission from the list route.
perl -0pi -e 's/    dependencies=\[requires\(declare\("bank_result_bundle\.read"\)\)\],\n\)\ndef list_bank_result_bundles/)\ndef list_bank_result_bundles/' "$API"
run "the list route loses its permission" "no_bundle_route_answers_a_caller" "$LIVE"

# 4. The counts CHECK. Without it three integers drift independently and nothing refuses the
#    result — this is the constraint document 04 does not state and §12.1's own prose asks for.
perl -0pi -e 's/            "resolved_segment_count \+ unresolved_segment_count = segment_count",\n            name="counts_reconcile",/            "resolved_segment_count >= 0",\n            name="counts_reconcile",/' "$MODEL"
run "the counts may disagree with each other" "counts_cannot_disagree" "$UNIT"

# 5. The closing CHECK's second direction. A bundle carrying a closer while still open reads as
#    closed to anything that checks the timestamp rather than the status.
perl -0pi -e 's/            "\(status = .closed. AND closed_at IS NOT NULL AND closed_by_admin_user_id IS NOT NULL\)"\n            " OR "\n            "\(status <> .closed. AND closed_at IS NULL AND closed_by_admin_user_id IS NULL\)",/            "status <> \x27closed\x27 OR closed_at IS NOT NULL",/' "$MODEL"
run "a bundle may carry a closer while open" "must_say_who_closed_it" "$UNIT"

# 6. A column that makes a link readable as proof of payment. This is the control for the claim
#    that matters most in the slice, and the sabotage is exactly what somebody would add for a
#    good-sounding reason.
perl -0pi -e 's/(    link_method: Mapped\[str\] = mapped_column\(String\(32\), nullable=False\))/    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)\n$1/' "$MODEL"
run "a link gains a confirmation column" "read_as_proof_of_payment" "$UNIT"

# 7. Accept a file that has not been scanned clean. A bundle of unscanned files is evidence nobody
#    may open, and M4's lifecycle is the authority the command must consult rather than assume.
perl -0pi -e 's/        if record\.scan_status != CLEAN_SCAN_STATUS:/        if False:/' "$CMD"
run "an unscanned file is accepted" "must_be_scanned_clean" "$LIVE"

echo "== done =="
