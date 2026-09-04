#!/usr/bin/env bash
# Negative controls for M11 slice 3 — the accountant's eleven queues.
#
# The slice's substance is *which rows each queue names*, so most controls widen or shift a
# predicate by one state. Control 1 re-creates the defect slice 2 merged, which is the reason this
# slice touches `new-requests` at all.
#
# Control 0 runs the suite CLEAN FIRST. "CAUGHT" from an already-red suite is not evidence.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:55500/postgres}"

REQUESTS=services/backend/app/queues/payment_requests.py
MONEY=services/backend/app/queues/money_movement.py
ROUTE=services/backend/app/api/v1/queues.py
REGISTRY=services/backend/app/queues/registry.py

BACKUP=$(mktemp -d)
cp "$REQUESTS" "$BACKUP/requests.py"
cp "$MONEY" "$BACKUP/money.py"
cp "$ROUTE" "$BACKUP/route.py"
cp "$REGISTRY" "$BACKUP/registry.py"

restore() {
  cp "$BACKUP/requests.py" "$REQUESTS"
  cp "$BACKUP/money.py" "$MONEY"
  cp "$BACKUP/route.py" "$ROUTE"
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

# 1. The defect slice 2 merged: `new-requests` filters on status alone, so it returns correction
#    responses too and the two queues overlap.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/payment_requests.py")
s = p.read_text()
s = s.replace(
    """    return _no_scope(statement, actor).where(
        PaymentRequest.status == SUBMITTED_TO_CENTER,
        PaymentRequest.review_note.is_(None),
    )""",
    "    return _no_scope(statement, actor).where(PaymentRequest.status == SUBMITTED_TO_CENTER)",
)
p.write_text(s)
EOF
probe "1. new-requests returns correction responses as well (the slice-2 defect)"

# 2. The other half of the partition: correction-responses returns everything submitted.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/payment_requests.py")
s = p.read_text()
s = s.replace(
    """    return _no_scope(statement, actor).where(
        PaymentRequest.status == SUBMITTED_TO_CENTER,
        PaymentRequest.review_note.is_not(None),
    )""",
    "    return _no_scope(statement, actor).where(PaymentRequest.status == SUBMITTED_TO_CENTER)",
)
p.write_text(s)
EOF
probe "2. correction-responses returns first submissions too"

# 3. A queue includes the adjacent state a person already has.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/payment_requests.py")
s = p.read_text()
s = s.replace(
    "        PaymentRequest.status == SUBMITTED_TO_CENTER,\n"
    "        PaymentRequest.review_note.is_(None),",
    "        PaymentRequest.status.in_((SUBMITTED_TO_CENTER, UNDER_ACCOUNTANT_REVIEW)),\n"
    "        PaymentRequest.review_note.is_(None),",
)
p.write_text(s)
EOF
probe "3. new-requests hands out work somebody has already started"

# 4. `eligible-for-batching` names the state before it.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/payment_requests.py")
s = p.read_text()
s = s.replace(
    "    return _no_scope(statement, actor).where(PaymentRequest.status == ELIGIBLE_FOR_BATCHING)",
    "    return _no_scope(statement, actor).where(PaymentRequest.status == SUBMITTED_TO_CENTER)",
)
p.write_text(s)
EOF
probe "4. eligible-for-batching returns the wrong state"

# 5. Trader disputes becomes a status filter, which cannot express a dispute at all.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/payment_requests.py")
s = p.read_text()
s = s.replace(
    "    return _no_scope(statement, actor).where(PaymentRequest.trader_disputed_at.is_not(None))",
    "    return _no_scope(statement, actor).where(PaymentRequest.status == ELIGIBLE_FOR_BATCHING)",
)
p.write_text(s)
EOF
probe "5. trader-disputes is built on a status instead of the timestamp"

# 6. `approved-exports-awaiting-send` drops the sent check, so an export already carried to the
#    bank stays in the queue. M7's rule: downloading does not mean sent.
#
#    **This one is expected to be NOT CAUGHT, and that is the recorded finding rather than a
#    failure of the script.** `bank_excel_exports` needs five foreign keys to seed and
#    `test_queue_contract.py` does not build that chain, so no row ever reaches this predicate.
#    The same is true of `payment_attempts` and `incoming_payment_receipts`. `SVC-QUEUE-001` is
#    therefore left PENDING with those queues named, instead of discharged on the six that are
#    genuinely covered — a gate whose input is incomplete passes, and this is the input being
#    incomplete. Keep this control: it is what will go green when the fixtures are built.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/money_movement.py")
s = p.read_text()
s = s.replace("        .where(BankExcelExport.sent_to_bank_marked_at.is_(None))\n", "")
p.write_text(s)
EOF
probe "6. an export already sent to the bank stays in the send queue"

# 7. The unified row grows a field, which is the disclosure decision inherited twenty-four times.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/queues.py")
s = p.read_text()
s = s.replace(
    "    created_at: datetime\n    trader_id: uuid.UUID | None",
    "    created_at: datetime\n    trader_id: uuid.UUID | None\n    note: str | None = None",
)
p.write_text(s)
EOF
probe "7. the queue row grows a field nobody decided to disclose"

# 8. A queue loses its guard, so an ungranted admin and every trader reach it.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/queues.py")
s = p.read_text()
s = s.replace("        dependencies=[requires(definition.permission)],\n", "")
p.write_text(s)
EOF
probe "8. the queues are reachable without their grants"

# 9. Every queue is guarded by one permission the accountant does not hold — the mirror of 8, and
#    the one two 403 sweeps alone cannot see.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/queues.py")
s = p.read_text()
s = s.replace(
    "        dependencies=[requires(definition.permission)],",
    '        dependencies=[requires("gold_sale.dispatch")],',
)
p.write_text(s)
EOF
probe "9. every queue is guarded by a permission its own role lacks"

# 10. A queue is registered without a route, so the registry claims more than exists.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/queues.py")
s = p.read_text()
s = s.replace(
    "for _definition in BUILT.values():",
    "for _definition in list(BUILT.values())[:-1]:",
)
p.write_text(s)
EOF
probe "10. a registered queue has no route"

echo
echo "=== restored ==="
git status --short
