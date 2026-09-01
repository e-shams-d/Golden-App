#!/usr/bin/env bash
# Negative controls for M10 slice 1 — the gold sale order and its pricing versions.
#
# Controls 1 and 2 are the immutability pair: edit a pricing version in place, or forget to move
# the order's pointer. §10.2 requires a new row *and* a repointed order in one transaction, and a
# test that only read the new version would pass against either half alone.
#
# Control 5 is the domain one. `KILOGRAM` was in the first draft of this slice and `MITHQAL` was
# missing; the control puts the invented unit back and requires the refusal to notice.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

COMMANDS="services/backend/app/commands/gold_sale.py"
MODEL="services/backend/app/db/models/gold_sale.py"
ROUTES="services/backend/app/api/v1/gold_sale_orders.py"
BACKUP="$(mktemp -d)"

cp "$COMMANDS" "$BACKUP/commands.py"
cp "$MODEL" "$BACKUP/model.py"
cp "$ROUTES" "$BACKUP/routes.py"

restore() {
  cp "$BACKUP/commands.py" "$COMMANDS"
  cp "$BACKUP/model.py" "$MODEL"
  cp "$BACKUP/routes.py" "$ROUTES"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
LIVE=tests/integration/test_gold_sale_orders.py
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

echo "== M10 slice 1 negative controls =="

# 1. Edit the current pricing version in place instead of inserting a new one. §10.2 calls it an
#    immutable snapshot, and the migration grants `superseded_at` alone — so this must fail on the
#    privilege even if the code tries.
perl -0pi -e 's/    session\.add\(version\)/    if previous is not None:\n        previous.unit_price_irr = command.unit_price_irr\n    session.add(version)/' "$COMMANDS"
run "the old version is edited in place" "test_re_pricing_creates_a_version_and_supersedes" "$LIVE"

# 2. Create the new version and leave the order pointing at the old one. §10.2 at `:731` requires
#    both in one transaction, and a test reading only the new row would not notice.
perl -0pi -e 's/            "current_pricing_version_id": version\.id,\r?\n//' "$COMMANDS"
run "the order keeps the old pointer" "test_re_pricing_creates_a_version_and_supersedes" "$LIVE"

# 3. Take the expected amount from the caller rather than computing it. §21.2's body has no such
#    field, and adding one is a number that can disagree with the arithmetic.
perl -0pi -e 's/    expected_amount = _amount_for\(order\.gold_weight, command\.unit_price_irr\)/    expected_amount = int(command.unit_price_irr)/' "$COMMANDS"
run "the amount ignores the weight" "test_pricing_computes_the_amount_rather_than" "$LIVE"

# 4. Compute the amount through a float. The value is right for the main fixture and wrong in
#    general, which is exactly why `app/core/hashing.py` refuses floats.
#
#    **This control went NOT CAUGHT first time, and it was the test's fault, not the control's.**
#    The fixture prices `125.500000` grams, and `125.5` is exactly representable in binary — so
#    float and Decimal agreed and the assertion could not have failed. The fourth meaning of NOT
#    CAUGHT: insensitive by construction.
#    `test_the_amount_is_computed_in_decimal_and_not_through_a_float` prices `0.29` at 100 instead,
#    where Decimal gives 29 and a float gives 28, and exists because of this control.
perl -0pi -e 's/    amount = int\(weight \* Decimal\(unit_price_irr\)\)/    amount = int(float(weight) * unit_price_irr)/' "$COMMANDS"
run "the amount goes through a float" "test_the_amount_is_computed_in_decimal" "$LIVE"

# 5. Put `KILOGRAM` back and drop `MITHQAL` — the exact pair of errors this slice shipped in its
#    first draft, and the one no test would have caught before these two existed.
perl -0pi -e 's/WEIGHT_UNITS: tuple\[str, \.\.\.\] = \("GRAM", "MITHQAL"\)/WEIGHT_UNITS: tuple[str, ...] = ("GRAM", "KILOGRAM")/' "$MODEL"
run "the invented unit comes back" "test_mithqal_is_accepted" "$LIVE"

# 6. Drop the identical-content refusal. `UNIQUE(order_id, content_hash)` still refuses the row,
#    but only after the caller has been told nothing useful.
perl -0pi -e 's/        "gold_purity": order\.gold_purity,\r?\n/        "gold_purity": order.gold_purity,\n        "nonce": str(__import__("uuid").uuid4()),\n/' "$COMMANDS"
run "every re-price hashes differently" "test_re_pricing_at_identical_figures_is_refused" "$LIVE"

# 7. Let a draft be priced. Nobody has handed the order to the centre, and pricing one is quoting
#    for something that was never asked for.
perl -0pi -e 's/    if order\.status not in PRICEABLE_FROM:/    if False:/' "$COMMANDS"
run "a draft can be priced" "test_a_draft_cannot_be_priced" "$LIVE"

# 8. Drop the ownership check on the single-order read. A trader could then read any order by
#    guessing an identifier.
perl -0pi -e 's/        order = uow\.session\.get\(GoldSaleOrder, order_id\)\r?\n        if actor\.is_trader:\r?\n            require_owned\(order, order\.trader_id if order else None, actor\)\r?\n        elif order is None:\r?\n            uow\.rollback\(\)\r?\n            raise NotFoundError\(\)\r?\n        assert order is not None/        order = uow.session.get(GoldSaleOrder, order_id)\n        if order is None:\n            uow.rollback()\n            raise NotFoundError()/' "$ROUTES"
run "any trader can read any order" "test_another_trader_cannot_see_or_submit" "$LIVE"

# 9. Scope the list to nobody, so every trader sees every order.
perl -0pi -e 's/            query = scoped\(query, GoldSaleOrder\.trader_id, actor\)/            pass/' "$ROUTES"
run "the scoped list is not scoped" "test_a_traders_list_holds_only_their_own_orders" "$LIVE"

echo "== done =="
