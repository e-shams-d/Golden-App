#!/usr/bin/env bash
# Negative controls for M10 slice 6 — confirming an incoming payment.
#
# Every control here is a way of treating an amount as fully paid when it is not, which is the one
# thing §21.6 forbids in its last line. Control 3 is the sharpest: it reads the receipt in front of
# the accountant instead of the order's sum, which is correct for every single-receipt test and
# wrong the moment a second payment arrives.
#
# Control 5 is the one M9 learned the hard way: the overpayment task must commit even though the
# command refuses. Rolling it back leaves a refusal nobody follows up.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

COMMANDS="services/backend/app/commands/incoming_confirmation.py"
ROUTES="services/backend/app/api/v1/incoming_matches.py"
MIGRATION="services/backend/alembic/versions/20260910_0041_incoming_confirmation.py"
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
LIVE=tests/integration/test_incoming_confirmation.py
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
    printf '  CAUGHT   %-58s' "$label"
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

echo "== M10 slice 6 negative controls =="

# 1. Mark the order confirmed whenever any receipt is confirmed. The single most tempting change:
#    this receipt was confirmed in full, so surely the order is paid? Not when it is one of two.
perl -0pi -e 's/    order\.status = \(\r?\n        ORDER_CONFIRMED\r?\n        if expected is not None and total >= expected\r?\n        else ORDER_PARTIALLY_CONFIRMED\r?\n    \)/    order.status = ORDER_CONFIRMED/' "$COMMANDS"
run "any confirmation completes the order" "test_two_partial_payments_aggregate_to_the_order" "$LIVE"

# 2. Compare this receipt's amount against the price instead of the running sum. Every
#    single-receipt test passes; two payments of 40 against 100 then complete the order.
perl -0pi -e 's/    total = already \+ command\.confirmed_amount_irr/    total = command.confirmed_amount_irr/' "$COMMANDS"
run "the sum is this receipt alone" "test_two_partial_payments_aggregate_to_the_order" "$LIVE"

# 3. Read the paid total from `final_amount_irr` rather than from the confirmed receipts. A cached
#    balance, which `04_Database_Schema.md:469` forbids — and it is stale the moment a correction
#    lands, which is exactly when nobody is checking the arithmetic.
perl -0pi -e 's/    already = _confirmed_total\(session, order\.id\)/    already = int(order.final_amount_irr or 0)/' "$COMMANDS"
run "the total comes from a cached column" "test_two_partial_payments_aggregate" "$LIVE"

# 4. Accept an overpayment. §21.6: excess is never silently treated as fully paid.
perl -0pi -e 's/    if expected is not None and total > expected:/    if False:/' "$COMMANDS"
run "an overpayment is accepted" "test_an_overpayment_is_refused_and_opens_a_task" "$LIVE"

# 5. Roll the review task back with the refusal. **M9's own mistake, reproduced.** The command
#    still refuses, so every "overpayment is rejected" assertion passes; the task disappears and
#    nobody is asked to look at the discrepancy.
perl -0pi -e 's/        except confirmation_commands\.OverpaymentRefused:\r?\n            # The task is the point of the refusal\. Commit it, then let the error become a 400\.\r?\n            uow\.commit\(\)\r?\n            raise/        except confirmation_commands.OverpaymentRefused:\n            uow.rollback()\n            raise/' "$ROUTES"
run "the overpayment task is rolled back" "test_an_overpayment_is_refused_and_opens_a_task" "$LIVE"

# 6. Open the task with the outgoing-payment discrepancy type. It files an incoming-payment
#    question in the queue an accountant filters for the other direction of money.
perl -0pi -e 's/            task_type=TASK_TYPE_INCOMING_DISCREPANCY,/            task_type="payment_result_discrepancy",/' "$COMMANDS"
run "the task borrows the outgoing type" "test_an_overpayment_is_refused_and_opens_a_task" "$LIVE"

# 7. Skip the second axis. The match then carries a confirmed amount and a confirmed time with
#    nothing saying it is the authoritative one — and slice 8 would have no column to set to
#    `replaced`.
perl -0pi -e 's/        match\.confirmation_status = CONFIRMATION_ACTIVE/        pass/' "$COMMANDS"
run "the confirmation axis is left null" "test_confirming_a_match_sets_the_second_axis" "$LIVE"

# 8. Overwrite the candidate's own status with the confirmation. One column cannot hold both
#    lifecycles: which route the candidate took to get here is lost.
perl -0pi -e 's/        match\.confirmation_status = CONFIRMATION_ACTIVE/        match.status = "accepted_for_review"\n        match.confirmation_status = CONFIRMATION_ACTIVE/' "$COMMANDS"
run "the candidate axis is overwritten" "test_confirming_a_match_sets_the_second_axis" "$LIVE"

# 9. Drop the row-reuse guard. Document 06 §11.3's third rule: one bank credit cannot pay two
#    different claims.
perl -0pi -e 's/    if conflicting is not None:/    if False:/' "$COMMANDS"
run "one credit funds two claims" "test_a_statement_row_cannot_fund_two_claims" "$LIVE"

# 10. Confirm a receipt that is already confirmed. Re-deciding a closed claim is a correction, and
#     doing it here would record two confirmations of one payment.
perl -0pi -e 's/    if receipt\.status not in CONFIRMABLE_FROM:/    if False:/' "$COMMANDS"
run "a confirmed receipt is confirmed again" "test_a_receipt_cannot_be_confirmed_twice" "$LIVE"

# 11. Ignore If-Match. Two accountants confirming one receipt would then both succeed, and the
#     second would overwrite the first without either knowing.
perl -0pi -e 's/    if receipt\.record_version != command\.expected_record_version:/    if False:/' "$COMMANDS"
run "a stale If-Match is accepted" "test_a_stale_if_match_is_refused" "$LIVE"

# 12. Open the confirm route to any authenticated caller. A trader confirming their own claim is
#     deciding that their own money arrived, which is what a bank statement exists to answer.
perl -0pi -e 's/    dependencies=\[requires\(declare\("incoming_payment\.confirm"\)\)\],\r?\n//' "$ROUTES"
run "a trader confirms their own payment" "test_no_trader_can_confirm_their_own_payment" "$LIVE"

# 13. Leave the confirmed total out of the audit entry. The row then cannot answer "was the order
#     fully paid at this moment", which is what every later reader of a partial payment asks.
perl -0pi -e 's/                "order_confirmed_total_irr": str\(total\),\r?\n//' "$COMMANDS"
run "the audit entry drops the running total" "test_the_audit_entry_carries_both_figures" "$LIVE"

# 14. Add the partial unique the migration deliberately does not create. It would answer §10.7
#     `:809`'s open cardinality question in a migration — the thing slice 5's absence test exists
#     to prevent — and this slice is the one that would have tripped it.
perl -0pi -e 's/    bind = op\.get_bind\(\)/    op.create_index(\n        "uq_incoming_matches_one_active_per_row",\n        "incoming_payment_matches",\n        ["bank_statement_row_id"],\n        unique=True,\n        postgresql_where=sa.text("confirmation_status = \x27active\x27"),\n    )\n    bind = op.get_bind()/' "$MIGRATION"
run "a partial unique answers G-2" "test_no_partial_unique_constrains_the_pair" tests/integration/test_incoming_payment_matches.py

echo "== done =="
