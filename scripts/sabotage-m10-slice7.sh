#!/usr/bin/env bash
# Negative controls for M10 slice 7 — the dispatch guard.
#
# This is the guard the milestone was built toward, so every control is a way of letting gold leave
# the building when it should not. Control 5 is the sharpest: it grants the override to the
# warehouse operator, which no branch in the command can refuse — the separation is a property of
# the seed, and only a seed change can break it.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

COMMANDS="services/backend/app/commands/gold_dispatch.py"
ROUTES="services/backend/app/api/v1/gold_sale_orders.py"
MIGRATION="services/backend/alembic/versions/20260911_0042_gold_dispatches.py"
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
LIVE=tests/integration/test_gold_dispatch.py
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

echo "== M10 slice 7 negative controls =="

# 1. Let an unpaid order dispatch. §18 `:1236` in one line, and the whole milestone leads here.
perl -0pi -e 's/    guard_passes = expected is not None and paid >= expected/    guard_passes = True/' "$COMMANDS"
run "an unpaid order dispatches freely" "test_an_unpaid_order_is_refused" "$LIVE"

# 2. Compare against the claimed amount rather than the confirmed one. A trader who says they paid
#    would then release the gold themselves, which is what slice 2 exists to prevent.
#
#    **NOT CAUGHT on the first run, and it was the fourth meaning.** The fixture wrote
#    `amount_irr` and `confirmed_amount_irr` equal on every order, so both readings agreed and the
#    test could not fail. `an_order` now takes a `claimed` argument, and the refusal test covers a
#    trader claiming the full amount against nothing confirmed.
perl -0pi -e 's/            IncomingPaymentReceipt\.confirmed_amount_irr\.is_not\(None\),/            IncomingPaymentReceipt.amount_irr.is_not(None),/' "$COMMANDS"
perl -0pi -e 's/select\(func\.coalesce\(func\.sum\(IncomingPaymentReceipt\.confirmed_amount_irr\), 0\)\)/select(func.coalesce(func.sum(IncomingPaymentReceipt.amount_irr), 0))/' "$COMMANDS"
run "the guard reads the claim, not the confirmation" "test_an_unpaid_order_is_refused" "$LIVE"

# 3. Accept a partial payment as enough. Half the money and all the gold.
perl -0pi -e 's/    guard_passes = expected is not None and paid >= expected/    guard_passes = expected is not None and paid > 0/' "$COMMANDS"
run "a partial payment releases the gold" "test_an_unpaid_order_is_refused" "$LIVE"

# 4. Drop the override permission check. The warehouse operator can then release gold against
#    unconfirmed money by supplying any reason.
perl -0pi -e 's/    if OVERRIDE_PERMISSION not in actor_permissions:/    if False:/' "$COMMANDS"
run "any dispatcher may override" "test_a_warehouse_operator_cannot_override" "$LIVE"

# 5. **Grant the override to the warehouse operator in the seed.** No branch in the command
#    changes; the separation `permission_catalog.yaml`'s dispatch_control constraint states is
#    simply gone. Only a test that reads the grant sees it.
perl -0pi -e 's/    \("manager", "gold_sale\.dispatch_override"\),/    ("manager", "gold_sale.dispatch_override"),\n    ("warehouse_operator", "gold_sale.dispatch_override"),/' "$MIGRATION"
run "the seed grants the override to warehouse" "test_the_override_permission_is_the_managers_alone" "$LIVE"

# 6. Accept an override with no reason. §18 `:1236` requires it recorded *with reason*.
perl -0pi -e 's/    if not \(command\.guard_override_reason or ""\)\.strip\(\):/    if False:/' "$COMMANDS"
run "an override needs no reason" "test_an_override_without_a_reason_is_refused" "$LIVE"

# 7. Record the override columns on every dispatch, guard or no guard. The overridden ones then
#    cannot be found — and the partial index exists precisely so they can be.
perl -0pi -e 's/    override_at: datetime \| None = None\r?\n    override_by: uuid\.UUID \| None = None\r?\n    if not guard_passes:/    override_at: datetime | None = now\n    override_by: uuid.UUID | None = actor.actor_id\n    if not guard_passes:/' "$COMMANDS"
run "every dispatch records an override" "test_a_paid_order_dispatches_without_an_override" "$LIVE"

# 8. Give a settlement the same status as a physical movement. `SVC-SETTLEMENT-001`: four types
#    exist and two move no metal.
perl -0pi -e 's/        status=DISPATCH_DISPATCHED if physical else DISPATCH_SETTLED,/        status=DISPATCH_DISPATCHED,/' "$COMMANDS"
run "an offset settlement reads as dispatched" "test_an_offset_settlement_moves_no_metal" "$LIVE"

# 9. Stamp `dispatched_at` on a settlement. Nothing left the building, so there is no moment of
#    leaving — and a timestamp for an event that did not happen is worse than a null.
perl -0pi -e 's/        dispatched_at=\(command\.dispatched_at or now\) if physical else None,/        dispatched_at=command.dispatched_at or now,/' "$COMMANDS"
run "a settlement records a moment of leaving" "test_an_offset_settlement_moves_no_metal" "$LIVE"

# 10. Move the order to `dispatched` for a settlement too. `status_catalog.yaml` has
#     `settled_or_offset` for exactly this, and collapsing them loses which happened.
perl -0pi -e 's/    order\.status = ORDER_DISPATCHED if physical else ORDER_SETTLED/    order.status = ORDER_DISPATCHED/' "$COMMANDS"
run "an offset leaves the order dispatched" "test_an_offset_settlement_moves_no_metal" "$LIVE"

# 11. Classify `physical_receipt` by the word rather than by the list. It is a physical type even
#     though metal arrives rather than leaves, so a name-derived split misfiles it.
perl -0pi -e 's/    physical = command\.dispatch_type in PHYSICAL_TYPES/    physical = command.dispatch_type.startswith("physical_d")/' "$COMMANDS"
run "the physical split is derived from the name" "test_all_four_types_are_accepted" "$LIVE"

# 12. Accept any dispatch type the caller offers. A fifth type would be a business decision
#     arriving through a request body.
perl -0pi -e 's/    if command\.dispatch_type not in DISPATCH_TYPES:/    if False:/' "$COMMANDS"
run "an invented dispatch type is accepted" "test_an_unknown_dispatch_type_is_refused" "$LIVE"

# 13. Grant the runtime UPDATE on `dispatch_type`. Nothing behavioural changes — no command writes
#     it — and document 06 §12.3's "cannot be converted silently" stops being true.
#
#     **NOT CAUGHT on the first run: the privilege query asked about `current_user`**, which is
#     the owner this module connects as and which holds every privilege. The assertion was true of
#     a role nobody runs the application under. It reads `app_role` now, and `names_are_read`
#     refuses an empty result rather than passing vacuously.
perl -0pi -e 's/GRANTED_COLUMNS = \(\r?\n    "status",/GRANTED_COLUMNS = (\n    "dispatch_type",\n    "status",/' "$MIGRATION"
run "dispatch_type becomes rewritable" "test_the_runtime_cannot_convert_a_dispatch" "$LIVE"

# 14. Let the route admit anyone authenticated. The trader whose order it is could then record
#     their own gold as dispatched.
#
#     **NOT CAUGHT on the first run, and it was the third meaning.** Every existing test used an
#     unpaid order, so the command refused the trader for its own reason and the route guard was
#     never the thing under test, and the second version still was not: a trader is refused by the
#     audience split before any route guard runs. The accountant isolates it — an internal user
#     holding neither permission, on an order whose payment guard passes.
perl -0pi -e 's/        if declared_dispatch not in actor\.permissions and declared_override not in \(\r?\n            actor\.permissions\r?\n        \):\r?\n            raise ForbiddenError\(\)/        return None/' "$ROUTES"
run "the dispatch route admits anyone" "test_the_route_itself_refuses_an_accountant" "$LIVE"

# 15. Drop the audit entry's guard verdict. A reader then has to infer from three nullable columns
#     whether the gold was released against confirmed money.
perl -0pi -e 's/                "payment_guard_passed": guard_passed,\r?\n//' "$COMMANDS"
run "the audit entry drops the guard verdict" "test_a_manager_may_override_with_a_reason" "$LIVE"

echo "== done =="
