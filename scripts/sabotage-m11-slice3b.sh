#!/usr/bin/env bash
# Negative controls for M11 slice 3B — the queue fixtures slice 3 could not build.
#
# The slice adds no production code. Its whole claim is that three queue predicates now have rows
# to select, so every control here attacks a predicate that slice 3 could not reach at all.
#
# Control 1 is slice 3's control 6, re-run. It is still expected NOT CAUGHT, and the reason is now
# known and different from what slice 3 recorded: `mark_sent` moves the status and the timestamp
# together, so the status filter already excludes every sent export. Control 2 asserts that
# assumption directly, which is the honest way to keep a redundant guard.
#
# Control 0 runs the suite CLEAN FIRST. Restores with `cp`, never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:55500/postgres}"

MONEY=services/backend/app/queues/money_movement.py
EXPORTCMD=services/backend/app/commands/bank_export.py

BACKUP=$(mktemp -d)
cp "$MONEY" "$BACKUP/money.py"
cp "$EXPORTCMD" "$BACKUP/bank_export.py"

restore() {
  cp "$BACKUP/money.py" "$MONEY"
  cp "$BACKUP/bank_export.py" "$EXPORTCMD"
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

# 1. Slice 3's control 6, re-run with rows present. Expected NOT CAUGHT: the condition is
#    redundant while `mark_sent` moves both facts together.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/money_movement.py")
s = p.read_text()
s = s.replace("        .where(BankExcelExport.sent_to_bank_marked_at.is_(None))\n", "")
p.write_text(s)
EOF
probe "1. the sent-timestamp condition is dropped (expected NOT CAUGHT: it is redundant)"

# 2. The assumption control 1 rests on. If `mark_sent` stops moving the status, the redundant
#    condition becomes load-bearing and nothing else would notice.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/commands/bank_export.py")
s = p.read_text()
s = s.replace("    export.status = STATUS_SENT\n", "")
p.write_text(s)
EOF
probe "2. marking sent no longer moves the status"

# 3. The status filter is widened to every active final status, so an export already sent is
#    offered for sending again. This is what control 1 would have caught if it were the real guard.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/money_movement.py")
s = p.read_text()
s = s.replace(
    ".where(BankExcelExport.status.in_((EXPORT_VALIDATED, EXPORT_DOWNLOADED)))",
    ".where(BankExcelExport.status.in_((EXPORT_VALIDATED, EXPORT_DOWNLOADED, 'sent_to_bank_marked')))",
)
p.write_text(s)
EOF
probe "3. an export already sent to the bank is offered for sending again"

# 4. The export type filter goes, so unsendable previews enter the queue.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/money_movement.py")
s = p.read_text()
s = s.replace('        .where(BankExcelExport.export_type == "final")\n', "")
p.write_text(s)
EOF
probe "4. previews appear in a queue of files to send to a bank"

# 5. The two attempt queues are given the same predicate, so every attempt is worked twice.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/money_movement.py")
s = p.read_text()
s = s.replace(
    "        PaymentAttempt.status.in_((ATTEMPT_FAILED, ATTEMPT_RETRY_REQUIRED))",
    "        PaymentAttempt.status.in_((ATTEMPT_SENT, ATTEMPT_RESULT_PENDING))",
)
p.write_text(s)
EOF
probe "5. the two attempt queues return the same rows"

# 6. A superseded attempt — work a retry already carries — re-enters the decision queue.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/money_movement.py")
s = p.read_text()
s = s.replace(
    "        PaymentAttempt.status.in_((ATTEMPT_FAILED, ATTEMPT_RETRY_REQUIRED))",
    "        PaymentAttempt.status.in_((ATTEMPT_FAILED, ATTEMPT_RETRY_REQUIRED, 'superseded'))",
)
p.write_text(s)
EOF
probe "6. a superseded attempt is queued for a decision again"

# 7. The receipt queue waits on a bank rather than on a person.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/money_movement.py")
s = p.read_text()
s = s.replace(
    "        IncomingPaymentReceipt.status.in_((RECEIPT_NEEDS_REVIEW, RECEIPT_DUPLICATE_SUSPECTED))",
    "        IncomingPaymentReceipt.status.in_((RECEIPT_NEEDS_REVIEW, 'waiting_for_bank_statement'))",
)
p.write_text(s)
EOF
probe "7. the receipt queue returns claims waiting on a bank, not on a person"

# 8. A suspected duplicate silently stops being anybody's work.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/money_movement.py")
s = p.read_text()
s = s.replace(
    "        IncomingPaymentReceipt.status.in_((RECEIPT_NEEDS_REVIEW, RECEIPT_DUPLICATE_SUSPECTED))",
    "        IncomingPaymentReceipt.status == RECEIPT_NEEDS_REVIEW",
)
p.write_text(s)
EOF
probe "8. a suspected duplicate is nobody's work"

# 9. Both guards at once, and this is the control the other two make necessary.
#
#    Controls 1 and 3 each remove one of the two conditions that exclude a sent export, and both
#    are NOT CAUGHT — **correctly**, because the other condition still holds the property. Two
#    guards enforcing one rule mask each other one at a time, which is the shape M10 hit twice.
#    Without this control nothing would prove the property is guarded at all rather than by
#    accident: a suite where every single-guard removal passes is indistinguishable from one where
#    no guard is tested.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/money_movement.py")
s = p.read_text()
s = s.replace("        .where(BankExcelExport.sent_to_bank_marked_at.is_(None))\n", "")
s = s.replace(
    ".where(BankExcelExport.status.in_((EXPORT_VALIDATED, EXPORT_DOWNLOADED)))",
    ".where(BankExcelExport.status.in_((EXPORT_VALIDATED, EXPORT_DOWNLOADED, 'sent_to_bank_marked')))",
)
p.write_text(s)
EOF
probe "9. BOTH guards removed, so a sent export really is offered for sending again"

echo
echo "=== restored ==="
git status --short
