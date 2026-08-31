#!/usr/bin/env bash
# Negative controls for M9 slice 3B — retry.
#
# Control 1 is the one that matters: it makes the decision command create the attempt as well,
# which is the exact shortcut §17.4 forbids in its own words and the reason the test counts
# attempts rather than reading a status.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

COMMANDS="services/backend/app/commands/payment_retry.py"
ROUTES="services/backend/app/api/v1/payment_attempts.py"
BACKUP="$(mktemp -d)"

cp "$COMMANDS" "$BACKUP/commands.py"
cp "$ROUTES" "$BACKUP/routes.py"

restore() {
  cp "$BACKUP/commands.py" "$COMMANDS"
  cp "$BACKUP/routes.py" "$ROUTES"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
LIVE=tests/integration/test_payment_retry.py
UNIT=tests/backend/test_batch_schema.py
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
    printf '  CAUGHT   %-52s' "$label"
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

echo "== M9 slice 3B negative controls =="

# 1. Make the decision helpful: marking retry-required also creates the retry attempt. §17.4 says
#    in as many words that it must not, and a status-only test would pass against this.
perl -0pi -e 's/(    previous_status = attempt\.status\r?\n)/$1    session.add(\n        PaymentAttempt(\n            payment_request_id=attempt.payment_request_id,\n            payment_request_revision_id=attempt.payment_request_revision_id,\n            attempt_number=attempt.attempt_number + 1,\n            attempt_type=ATTEMPT_TYPE_RETRY,\n            amount_irr=attempt.amount_irr,\n            beneficiary_name_snapshot=attempt.beneficiary_name_snapshot,\n            beneficiary_iban_snapshot=attempt.beneficiary_iban_snapshot,\n            bank_profile_version_id=attempt.bank_profile_version_id,\n            bank_account_id=attempt.bank_account_id,\n            split_rule_snapshot={},\n            status=ATTEMPT_CREATED,\n            record_version=1,\n        )\n    )\n/' "$COMMANDS"
run "the decision also creates the retry" "test_marking_retry_required_creates_no_attempt" "$LIVE"

# 2. Take the beneficiary from the original attempt instead of the referenced revision. §17.5's
#    corrected destination would then never reach the bank, silently.
perl -0pi -e 's/        beneficiary_name_snapshot=revision\.beneficiary_name_snapshot,\r?\n        beneficiary_iban_snapshot=revision\.beneficiary_iban_snapshot,/        beneficiary_name_snapshot=original.beneficiary_name_snapshot,\n        beneficiary_iban_snapshot=original.beneficiary_iban_snapshot,/' "$COMMANDS"
run "the retry keeps the old beneficiary" "test_a_retry_takes_its_beneficiary_from_the" "$LIVE"

# 3. Accept a revision belonging to another request — the free-form beneficiary change §17.5
#    forbids, arriving through a field that looks legitimate.
perl -0pi -e 's/    if revision\.payment_request_id != request\.id:/    if False:/' "$COMMANDS"
run "a foreign revision is accepted" "test_a_revision_from_another_request_is_refused" "$LIVE"

# 4. Leave the original active instead of superseding it. Two retries of one failure could then
#    exist, and the request would carry two live attempts for one failed payment.
perl -0pi -e 's/        values=\{"status": ATTEMPT_SUPERSEDED\},/        values={"status": ATTEMPT_RETRY_REQUIRED},/' "$COMMANDS"
run "the original stays retryable" "test_a_second_retry_of_one_failure_is_refused" "$LIVE"

# 5. Allow a retry without the decision. §17.4 and §17.5 are separate acts, and skipping the first
#    removes the record of why a second attempt exists.
perl -0pi -e 's/    if original\.status != ATTEMPT_RETRY_REQUIRED:/    if False:/' "$COMMANDS"
run "an unmarked attempt can be retried" "test_an_unmarked_attempt_cannot_be_retried" "$LIVE"

# 6. Let a paid attempt be marked for retry. Document 06 draws no such arrow, and retrying a
#    payment the bank already made sends the money twice.
perl -0pi -e 's/    if attempt\.status not in RETRY_REQUIRABLE_FROM:/    if False:/' "$COMMANDS"
run "a paid attempt can be retried" "test_a_paid_attempt_cannot_be_marked_for_retry" "$LIVE"

# 7. Drop the lineage pointer. The retry would exist with nothing saying what it retries, which is
#    the whole content of `new_attempt_preserves_retry_lineage`.
perl -0pi -e 's/        retry_of_attempt_id=original\.id,\r?\n//' "$COMMANDS"
run "the retry records no lineage" "test_a_retry_carries_its_lineage" "$LIVE"

# 8. Add a second writer of `retry_of_attempt_id`, which the narrowed lineage exemption must
#    refuse — it names exactly one module.
perl -0pi -e 's/(def _request_status\(session: Any, request_id: uuid\.UUID\) -> str:)/def _tamper(attempt: Any) -> None:\n    attempt.retry_of_attempt_id = None\n\n\n$1/' "$ROUTES"
run "a second module writes the lineage" "test_each_exempted_lineage_column_is_written" "$UNIT"

echo "== done =="
