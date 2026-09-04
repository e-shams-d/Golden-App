#!/usr/bin/env bash
# Negative controls for M11 slice 4 — the manager's approval queue and the warehouse's three.
#
# Control 1 is the slice's central claim: G-2 answered as a computation. Controls 5 and 6 attack
# the grant split, which is the part that would be invisible in a suite testing one role.
#
# Control 0 runs the suite CLEAN FIRST. Restores with `cp`, never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:55500/postgres}"

MW=services/backend/app/queues/manager_and_warehouse.py
REGISTRY=services/backend/app/queues/registry.py

BACKUP=$(mktemp -d)
cp "$MW" "$BACKUP/mw.py"
cp "$REGISTRY" "$BACKUP/registry.py"

restore() {
  cp "$BACKUP/mw.py" "$MW"
  cp "$BACKUP/registry.py" "$REGISTRY"
}
trap restore EXIT

SUITE="tests/integration/test_queue_contract.py"

echo "=== CONTROL 0: clean. Anything but green here invalidates every result below. ==="
$PY -m pytest $SUITE tests/backend -q --no-header 2>&1 | tail -3

probe() {
  local name="$1"
  echo
  echo "=== $name ==="
  if $PY -m pytest $SUITE tests/backend -q --no-header >"$BACKUP/out.txt" 2>&1; then
    echo "NOT CAUGHT"
  else
    echo "CAUGHT: $(grep -c '^FAILED' "$BACKUP/out.txt") failing"
    grep '^FAILED' "$BACKUP/out.txt" | head -4
  fi
  restore
}

# 1. G-2 answered wrongly: the queue reads the status nothing writes, so it is always empty. This
#    is the failure the derived reading exists to prevent, and an empty queue looks like calm.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/manager_and_warehouse.py")
s = p.read_text()
s = s.replace(
    "    return _internal(statement, actor).where(GoldSaleOrder.status == ORDER_PAYMENT_CONFIRMED)",
    "    return _internal(statement, actor).where(GoldSaleOrder.status == 'ready_for_dispatch')",
)
p.write_text(s)
EOF
probe "1. ready-for-dispatch reads the status nothing writes, so the queue is always empty"

# 2. Partial confirmation is offered for dispatch — releasing gold against part of the money.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/manager_and_warehouse.py")
s = p.read_text()
s = s.replace(
    "    return _internal(statement, actor).where(GoldSaleOrder.status == ORDER_PAYMENT_CONFIRMED)",
    "    return _internal(statement, actor).where(\n"
    "        GoldSaleOrder.status.in_((ORDER_PAYMENT_CONFIRMED,\n"
    "                                  'incoming_payment_partially_confirmed'))\n"
    "    )",
)
p.write_text(s)
EOF
probe "2. an order with only part of the money arrived is offered for dispatch"

# 3. The blocked queue and the ready queue return the same orders.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/manager_and_warehouse.py")
s = p.read_text()
s = s.replace(
    "        GoldSaleOrder.status == ORDER_MANAGER_APPROVAL_REQUIRED",
    "        GoldSaleOrder.status == ORDER_PAYMENT_CONFIRMED",
)
p.write_text(s)
EOF
probe "3. blocked-dispatches returns the orders that are ready"

# 4. The manager's queue takes the accountant's states, so approving and preparing collide.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/manager_and_warehouse.py")
s = p.read_text()
s = s.replace(
    "        PaymentBatchVersion.status == VERSION_READY_FOR_APPROVAL",
    "        PaymentBatchVersion.status.in_((VERSION_READY_FOR_APPROVAL, 'draft'))",
)
p.write_text(s)
EOF
probe "4. the manager's queue shows versions the accountant is still preparing"

# 5. The warehouse queues are guarded by `gold_sale.read`, which includes `trader_owner`. Every
#    trader could then read every business's dispatch work. This is the control that a
#    single-role suite cannot see.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/manager_and_warehouse.py")
s = p.read_text()
s = s.replace('permission="gold_sale.dispatch"', 'permission="gold_sale.read"')
p.write_text(s)
EOF
probe "5. the warehouse queues are opened to every trader"

# 6. The accountant is given the warehouse's queues, collapsing the role split.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/manager_and_warehouse.py")
s = p.read_text()
s = s.replace('permission="gold_sale.dispatch"', 'permission="payment_request.read"')
p.write_text(s)
EOF
probe "6. the accountant can reach the warehouse's queues"

# 7. Metal the trader already acknowledged is queued for confirmation again.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/manager_and_warehouse.py")
s = p.read_text()
s = s.replace(
    "    return _internal(statement, actor).where(GoldDispatch.status == DISPATCH_DISPATCHED)",
    "    return _internal(statement, actor).where(\n"
    "        GoldDispatch.status.in_((DISPATCH_DISPATCHED, 'delivered'))\n"
    "    )",
)
p.write_text(s)
EOF
probe "7. a dispatch the trader already acknowledged is queued again"

# 8. A blocked queue is quietly served under a borrowed permission — which is exactly what its
#    recorded reason forbids.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/registry.py")
s = p.read_text()
s = s.replace(
    'BUILT: dict[str, QueueDefinition[Any]] = {\n'
    '    queue.name: queue for queue in (*_ACCOUNTANT, *_MANAGER_AND_WAREHOUSE)\n'
    '}',
    'import dataclasses as _dc\n'
    'BUILT: dict[str, QueueDefinition[Any]] = {\n'
    '    queue.name: queue for queue in (*_ACCOUNTANT, *_MANAGER_AND_WAREHOUSE)\n'
    '}\n'
    'BUILT["approved-exception-tasks"] = _dc.replace(\n'
    '    RECONCILIATION_TASKS, name="approved-exception-tasks"\n'
    ')',
)
p.write_text(s)
EOF
probe "8. a queue recorded as blocked is served anyway"

echo
echo "=== restored ==="
git status --short
