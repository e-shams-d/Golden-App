#!/usr/bin/env bash
# Negative controls for M10 slice 8 — the end of the chain.
#
# Control 1 is the one this slice exists for: it re-creates the defect slice 6 merged, and the gate
# added here is what catches it. Every other control attacks an edge of document 06 §8.2 — closing
# something still moving, acknowledging something that never moved, or letting the wrong audience
# do either.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

REGISTRY="services/backend/app/audit/registry.py"
CONFIRM="services/backend/app/commands/incoming_confirmation.py"
CLOSURE="services/backend/app/commands/gold_sale_closure.py"
ROUTES="services/backend/app/api/v1/gold_sale_orders.py"
PROJECTION="services/backend/app/notifications/projection.py"
GOLDSALE="services/backend/app/commands/gold_sale.py"
BACKUP="$(mktemp -d)"

for pair in "REGISTRY:registry" "CONFIRM:confirm" "CLOSURE:closure" "ROUTES:routes" \
            "PROJECTION:projection" "GOLDSALE:goldsale"; do
  var="${pair%%:*}"; name="${pair##*:}"
  cp "${!var}" "$BACKUP/$name.py"
done

restore() {
  cp "$BACKUP/registry.py" "$REGISTRY"
  cp "$BACKUP/confirm.py" "$CONFIRM"
  cp "$BACKUP/closure.py" "$CLOSURE"
  cp "$BACKUP/routes.py" "$ROUTES"
  cp "$BACKUP/projection.py" "$PROJECTION"
  cp "$BACKUP/goldsale.py" "$GOLDSALE"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
LIVE=tests/integration/test_gold_sale_closure.py
CONF=tests/integration/test_incoming_confirmation.py
GATE=tests/backend/test_name_registry_and_errors.py
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
    printf '  CAUGHT   %-56s' "$label"
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

echo "== M10 slice 8 negative controls =="

# 1. **Re-create slice 6's defect**: declare no outbox event on the confirmation. This is the exact
#    change that merged green before, and the gate added in this slice is what refuses it now.
perl -0pi -e 's/    outbox_event_type="GoldOrderReadyForDispatch",/    outbox_event_type=None,/' "$REGISTRY"
run "the confirmation declares no outbox event" "test_a_command_row_that_names_an_event" "$GATE"

# 2. Publish on every confirmation rather than on the transition. "Ready for dispatch" while money
#    is outstanding makes the event useless as a trigger.
perl -0pi -e 's/    if order\.status == ORDER_CONFIRMED and previous\["order_status"\] != ORDER_CONFIRMED:/    if True:/' "$CONFIRM"
run "a partial confirmation announces readiness" "test_a_partial_confirmation_publishes_nothing" "$CONF"

# 3. Publish nothing at all. The declaration stays and the emission goes — a name with no caller,
#    which is the shape this repository has shipped five times.
perl -0pi -e 's/        OutboxWriter\(session, policy\)\.enqueue\(/        _unused = (/' "$CONFIRM"
run "the event is declared and never emitted" "test_a_completed_order_publishes_the_event" "$CONF"

# 4. Drop the projection entry. The event fires and nobody is told — silent in exactly the way the
#    missing declaration was.
perl -0pi -e 's/    "GoldOrderReadyForDispatch": TYPE_GOLD_ORDER_READY,\r?\n//' "$PROJECTION"
run "the trader is never told" "test_the_trader_is_told_their_order_is_ready" "$CONF"

# 5. Close an order with metal still in transit — **both guards removed together.**
#
#    Removing either alone went NOT CAUGHT, and that was the third meaning: the status check
#    refuses a `dispatched` order and the sweep refuses an order with metal moving, so each masked
#    the other on every existing case. Defence in depth hiding which layer is load-bearing, which
#    is the same finding slice 7 met. Document 06 §8.2 draws no edge from `dispatched` to `closed`.
perl -0pi -e 's/    if order\.status not in CLOSEABLE_FROM:/    if False:/' "$CLOSURE"
perl -0pi -e 's/    _refuse_an_unacknowledged_movement\(session, order\)/    pass/' "$CLOSURE"
run "an order in transit closes" "test_an_order_still_in_transit_cannot_close" "$LIVE"

# 6. Drop only the sweep. `test_a_second_dispatch_in_transit_blocks_closing` was written for this
#    control: an order at `received_by_trader` — so the status check is satisfied — with a second
#    physical dispatch still moving. Nothing else can refuse it.
perl -0pi -e 's/    _refuse_an_unacknowledged_movement\(session, order\)/    pass/' "$CLOSURE"
run "a second dispatch in transit is ignored" "test_a_second_dispatch_in_transit_blocks_closing" "$LIVE"

# 7. Let a settlement be acknowledged. Nothing moved, so there is nothing to confirm arriving.
perl -0pi -e 's/    if dispatch\.status != DISPATCH_DISPATCHED:/    if False:/' "$CLOSURE"
run "a settlement is acknowledged" "test_a_settlement_cannot_be_acknowledged" "$LIVE"

# 8. Drop the ownership check on the acknowledgement. A second trader could then confirm receipt of
#    somebody else's gold.
perl -0pi -e 's/    if order\.trader_id != command\.trader_id:/    if False:/' "$CLOSURE"
run "any trader acknowledges any gold" "test_a_second_trader_cannot_acknowledge" "$LIVE"

# 9. Let the centre acknowledge on a trader's behalf. "The trader says it arrived" is a different
#    assertion from "the centre says so", and the audit row is where that difference survives.
perl -0pi -e 's/    if not actor\.is_trader or actor\.trader_id is None:\r?\n        # The centre cannot acknowledge/    if False:\n        # The centre cannot acknowledge/' "$ROUTES"
run "the centre acknowledges for the trader" "test_the_centre_cannot_acknowledge_on_a_traders_behalf" "$LIVE"

# 10. Guard the close route by ownership instead of a permission. The trader could then decide
#     their own order is finished.
perl -0pi -e 's/    dependencies=\[requires\(declare\("gold_sale\.review"\)\)\],\r?\n\)\r?\ndef close_gold_sale_order\(/    dependencies=[owned_or_permitted("gold_sale.read", "gold_sale.review")],\n)\ndef close_gold_sale_order(/' "$ROUTES"
run "a trader closes their own order" "test_no_trader_can_close_their_own_order" "$LIVE"

# 11. Edit the superseded pricing row instead of leaving it. §18 `:1246` requires corrections to
#     preserve prior history, and `row_to_json` is what sees a single changed column.
#     The first version of this pattern named `superseded`; the variable is `previous`, so it
#     matched nothing and reported NOT CAUGHT against an untouched file — the second meaning, and
#     the reason the rule is to diff before concluding.
perl -0pi -e 's/        previous\.superseded_at = now/        previous.superseded_at = now\n        previous.unit_price_irr = command.unit_price_irr/' "$GOLDSALE"
run "a repricing rewrites the old price" "test_a_correction_preserves_the_superseded_pricing_row" "$LIVE"

# 12. Leave the order open after closing. The DoD's last hop is `closed`, and a walk that ended
#     anywhere else would not be one.
perl -0pi -e 's/    order\.status = ORDER_CLOSED\r?\n    order\.closed_at = now/    order.closed_at = now/' "$CLOSURE"
run "closing does not close" "test_the_milestone_walks_end_to_end" "$LIVE"

echo "== done =="
