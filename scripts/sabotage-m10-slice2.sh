#!/usr/bin/env bash
# Negative controls for M10 slice 2 — the trader's claim to have paid.
#
# Controls 1 to 3 attack the one sentence this slice exists for: doc 05 §21.3, "Uploading evidence
# never confirms payment." Each is a *helpful* change — set the confirmed amount from the claim,
# mark the order paid, call the receipt confirmed — and each is the mistake somebody makes when
# the claim and the confirmation look like the same fact.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

COMMANDS="services/backend/app/commands/incoming_payment.py"
ROUTES="services/backend/app/api/v1/gold_sale_orders.py"
MIGRATION="services/backend/alembic/versions/20260905_0036_incoming_payment_receipts.py"
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
LIVE=tests/integration/test_incoming_payment_receipts.py
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

echo "== M10 slice 2 negative controls =="

# 1. Fill the confirmed amount from the claim. The most tempting change in the slice: the trader
#    said how much, so why ask twice? Because the centre has not looked at a bank statement.
perl -0pi -e 's/        status=RECEIPT_SUBMITTED,/        status=RECEIPT_SUBMITTED,\n        confirmed_amount_irr=command.amount_irr,/' "$COMMANDS"
run "the claim confirms its own amount" "test_a_claim_confirms_nothing" "$LIVE"

# 2. Move the order to a confirmed state. §10.1 puts four statuses between evidence-submitted and
#    incoming-payment-confirmed, and this jumps them.
perl -0pi -e 's/    order\.status = ORDER_EVIDENCE_SUBMITTED/    order.status = "incoming_payment_confirmed"/' "$COMMANDS"
run "the order jumps to confirmed" "test_a_claim_confirms_nothing" "$LIVE"

# 3. Record the receipt as already confirmed.
perl -0pi -e 's/        status=RECEIPT_SUBMITTED,/        status="confirmed",/' "$COMMANDS"
run "the receipt is born confirmed" "test_a_claim_confirms_nothing" "$LIVE"

# 4. Accept any file as evidence. An internal document cited as proof that a trader sent money is
#    the IDOR shape arriving through a field that looks helpful.
perl -0pi -e 's/    if evidence\.uploaded_by_actor_type != "trader_user":/    if False:/' "$COMMANDS"
run "an internal document becomes evidence" "test_a_claim_cannot_cite_an_internal_document" "$LIVE"

# 5. Drop the ownership check so any trader may claim against any order.
#
#    **Anchored at line start with `^` and `/m`.** The first version was unanchored and matched
#    the *read* route's `require_owned`, which sits at twelve spaces inside an `if` — removing the
#    last eight characters of that indent orphaned the `elif` below it and the run came back
#    INVALID rather than NOT CAUGHT. A control that leaves unparseable code tests nothing, and the
#    run banner says so rather than reporting a pass.
#
#    **Both guards, because either alone suffices.** Removing only the route's went NOT CAUGHT —
#    correctly: the command re-checks `order.trader_id != command.trader_id` and answered 404 on
#    its own. That is defence in depth rather than a hole, and its comment says why the second
#    check exists ("reaching here means a caller that did not come through the route"). The third
#    meaning of NOT CAUGHT, and the same shape M9 slice 5B met on a missing share file.
perl -0pi -e 's/^        require_owned\(order, order\.trader_id if order else None, actor\)\r?\n//m' "$ROUTES"
perl -0pi -e 's/    if order\.trader_id != command\.trader_id:/    if False:/' "$COMMANDS"
run "both owner checks are gone" "test_another_trader_cannot_claim_against" "$LIVE"

# 6. Let an internal caller submit a claim in a trader's name. The audit row would then record a
#    trader's claim made by somebody else, which is what an evidence trail must never blur.
perl -0pi -e 's/    if not actor\.is_trader or actor\.trader_id is None:/    if False:/' "$ROUTES"
run "the centre claims on the trader's behalf" "test_an_accountant_cannot_claim_on_a_traders" "$LIVE"

# 7. Let a draft order be paid for. There is no priced amount to have paid.
perl -0pi -e 's/    if order\.status not in CLAIMABLE_FROM:/    if False:/' "$COMMANDS"
run "an unpriced order can be paid for" "test_an_unpriced_order_cannot_be_paid_for" "$LIVE"

# 8. Widen the grant so the runtime may rewrite what the trader claimed. A receipt whose amount
#    can be edited afterwards is evidence of nothing — and only a privilege query sees this.
perl -0pi -e 's/GRANTED_COLUMNS = \(\r?\n    "status",/GRANTED_COLUMNS = (\n    "amount_irr",\n    "status",/' "$MIGRATION"
run "the claim becomes editable" "test_the_runtime_cannot_rewrite_a_claim" "$LIVE"

# 9. Put the confirmed amount into the audit row. It would read as though the centre had agreed
#    with a figure nobody checked.
perl -0pi -e 's/                "claimed_amount_irr": str\(receipt\.amount_irr\),/                "claimed_amount_irr": str(receipt.amount_irr),\n                "confirmed_amount_irr": str(receipt.amount_irr),/' "$COMMANDS"
run "the audit row implies a confirmation" "test_the_claim_is_audited_as_a_claim" "$LIVE"

echo "== done =="
