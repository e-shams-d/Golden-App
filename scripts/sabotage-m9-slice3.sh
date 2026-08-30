#!/usr/bin/env bash
# Negative controls for M9 slices 3 and 4 — payment results and the request aggregate.
#
# The seven validations are not interchangeable, so there is one control per validation rather
# than one for "it refused". Controls 8 and 9 are the pair worth reading: one makes the
# overpayment refusal keep its block and lose its record, the other grants the runtime a column it
# must never write.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

COMMANDS="services/backend/app/commands/payment_result.py"
ROUTES="services/backend/app/api/v1/payment_attempts.py"
MIGRATION="services/backend/alembic/versions/20260830_0030_attempt_result_grant.py"
BACKUP="$(mktemp -d)"

cp "$COMMANDS" "$BACKUP/commands.py"
cp "$ROUTES" "$BACKUP/routes.py"
cp "$MIGRATION" "$BACKUP/migration.py"

restore() {
  cp "$BACKUP/commands.py" "$COMMANDS"
  cp "$BACKUP/routes.py" "$ROUTES"
  cp "$BACKUP/migration.py" "$MIGRATION"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
LIVE=tests/integration/test_payment_results.py
UNIT=tests/backend/test_payment_result_shape.py
OUT="$BACKUP/out.txt"

run() {
  local label="$1" expect="$2" target="$3"
  "$PYTHON" -m pytest -c services/backend/pyproject.toml "$target" -q > "$OUT" 2>&1

  if ! grep -qE '[0-9]+ (passed|failed)' "$OUT"; then
    printf '  INVALID RUN  %s\n' "$label"
    tail -4 "$OUT"
    restore
    return
  fi
  if grep -qE '[0-9]+ failed' "$OUT"; then
    printf '  CAUGHT   %-54s' "$label"
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

echo "== M9 slices 3+4 negative controls =="

# 1. Confirm an attempt that was never sent. The bank was never asked to do anything.
perl -0pi -e 's/    if attempt\.status not in CONFIRMABLE_FROM:/    if False:/' "$COMMANDS"
run "an unsent attempt can be confirmed" "test_an_attempt_that_was_never_sent" "$LIVE"

# 2. Accept a retired attempt. Cancelled and superseded are provoked separately in the suite, so
#    this one control must fail both parametrised cases.
perl -0pi -e 's/    if attempt\.status in RETIRED_STATUSES:/    if False:/' "$COMMANDS"
run "a retired attempt can be confirmed" "test_a_retired_attempt_cannot_be_confirmed" "$LIVE"

# 3. Let an evidence-free confirmation through with no reason. Doc 05 requires one "by policy" and
#    no approved document states the policy, so it is required in every such case.
perl -0pi -e 's/        if not \(command\.evidence_unavailable_reason or ""\)\.strip\(\):/        if False:/' "$COMMANDS"
run "no reason is needed without evidence" "test_confirming_with_no_evidence_requires_a_reason" "$LIVE"

# 4. Accept an evidence link that points at a different attempt — a paid result citing somebody
#    else's evidence.
perl -0pi -e 's/    if link\.payment_attempt_id != attempt\.id:/    if False:/' "$COMMANDS"
run "evidence for another attempt is accepted" "test_an_evidence_link_must_be_active" "$LIVE"

# 5. Drop the duplicate-tracking-number check. One bank transfer would then pay two attempts and
#    double the paid sum.
perl -0pi -e 's/    if clash is not None:/    if False:/' "$COMMANDS"
run "one transfer can pay two attempts" "test_one_bank_tracking_number_pays_one" "$LIVE"

# 6. Make any payment at all read as fully paid.
#
#    **The first version of this control was too weak and reported NOT CAUGHT**: it subtracted a
#    fixed margin from the requested amount, and the suite's split of 400M against 900M requested
#    still fell below the loosened threshold. A control that does not break the property proves
#    nothing about the test — the third of NOT CAUGHT's four meanings, and the one that looks
#    exactly like a weak assertion.
perl -0pi -e 's/    request\.status = REQUEST_PAID if paid == requested else REQUEST_PARTIALLY_PAID/    request.status = REQUEST_PAID/' "$COMMANDS"
run "any payment reads as fully paid" "test_the_request_becomes_paid_only_when" "$LIVE"

# 7. Remove the overpayment block entirely. Money above the requested amount would be recorded as
#    paid, which `04_Database_Schema.md:961` calls a reconciliation error and never a normal paid.
perl -0pi -e 's/    if already_paid \+ attempt\.amount_irr > requested:/    if False:/' "$COMMANDS"
run "an overpayment is accepted" "test_an_overpayment_is_blocked_and_opens_a_task" "$LIVE"

# 8. Keep the block and lose the record: the route stops committing before it re-raises, so the
#    reconciliation task is rolled back with the refused request. **This is the defect the suite
#    found in the first version of this slice**, and the control is what keeps it found.
#    Surgical: only the commit goes, leaving the `except` clause and its `raise` intact. The first
#    version deleted the whole clause and left a `try` with no handler, which pytest reported as
#    sixteen collection errors — an INVALID RUN rather than a control, and indistinguishable from
#    a broken harness if the runner had not said so.
perl -0pi -e 's/            uow\.commit\(\)\r?\n            raise\r?\n/            raise\n/' "$ROUTES"
run "the refusal discards its own task" "test_an_overpayment_is_blocked_and_opens_a_task" "$LIVE"

# 9. Grant UPDATE on the amount. A confirmation could then restate what was sent to the bank,
#    which is the one thing the column-level grant exists to prevent.
perl -0pi -e 's/GRANTED_COLUMNS = \(\r?\n    "status",/GRANTED_COLUMNS = (\n    "amount_irr",\n    "status",/' "$MIGRATION"
run "the runtime can rewrite the amount" "test_the_runtime_cannot_rewrite_what_was_sent" "$LIVE"

# 10. Add an amount field to the confirmation body. "Amount is exact" is enforced by there being
#     no number a client can send that disagrees with the attempt.
perl -0pi -e 's/(class ConfirmPaidRequest\(BaseModel\):(?:.|\n)*?    bank_tracking_number: str = Field\(min_length=1, max_length=128\))/$1\n    amount_irr: int | None = None/' "$ROUTES"
run "the body accepts an amount" "test_no_confirmation_body_accepts_an_amount" "$UNIT"

# 11. Make the replay re-apply the confirmation by ignoring the stored record. An
#     idempotent-looking route that repeats its effect passes a status-code assertion.
perl -0pi -e 's/    if claim\.is_replay:\r?\n        attempt, request = _replayed\(session, claim\)\r?\n        return ResultConfirmation\(\r?\n            attempt=attempt, request_status=request\.status, replayed=True\r?\n        \)\r?\n\r?\n    attempt = _locked_attempt\(session, command\.payment_attempt_id\)\r?\n    request = _locked_request\(session, attempt\.payment_request_id\)\r?\n\r?\n    _refuse_unless_sent\(attempt\)\r?\n    _refuse_evidence/    attempt = _locked_attempt(session, command.payment_attempt_id)\n    request = _locked_request(session, attempt.payment_request_id)\n\n    _refuse_unless_sent(attempt)\n    _refuse_evidence/' "$COMMANDS"
run "a replay re-applies the confirmation" "test_a_replayed_confirmation_does_not_move" "$LIVE"

echo "== done =="
