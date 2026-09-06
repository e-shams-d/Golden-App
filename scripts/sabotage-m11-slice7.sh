#!/usr/bin/env bash
# Negative controls for M11 slice 7 — the queue summary report and the milestone walk.
#
# The report's one real property is that it is permission-aware, so most controls make it leak.
# Control 5 attacks the walk itself: if the queue and the command disagree, an item stays in a
# queue after somebody took it, and only a walk notices.
#
# Control 0 runs the suite CLEAN FIRST. Restores with `cp`, never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:55500/postgres}"

SUMMARY=services/backend/app/reports/queue_summary.py
ROUTE=services/backend/app/api/v1/reports.py
REQUESTS=services/backend/app/queues/payment_requests.py

BACKUP=$(mktemp -d)
cp "$SUMMARY" "$BACKUP/queue_summary.py"
cp "$ROUTE" "$BACKUP/reports.py"
cp "$REQUESTS" "$BACKUP/payment_requests.py"

restore() {
  cp "$BACKUP/queue_summary.py" "$SUMMARY"
  cp "$BACKUP/reports.py" "$ROUTE"
  cp "$BACKUP/payment_requests.py" "$REQUESTS"
}
trap restore EXIT

SUITE="tests/integration/test_queue_summary_report.py tests/integration/test_m11_definition_of_done.py"

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

# 1. The report counts every queue regardless of the caller's grants. The leak §19 :1298 forbids,
#    and the one a single-role test cannot see.
# The first version of this control replaced a string that did not exist in the file — there is a
# comment between the `if` and the `continue` — so it silently changed nothing and reported NOT
# CAUGHT. **A sabotage that does not apply looks exactly like a gap in the tests.** Every control
# here now asserts its own edit landed before running the suite.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/reports/queue_summary.py")
s = p.read_text()
before = s
s = s.replace(
    "        if definition.permission not in actor.permissions:",
    "        if False:",
)
assert s != before, "control 1 did not modify the file; the sabotage is stale"
p.write_text(s)
EOF
probe "1. the report counts queues the caller may not read"

# 2. A queue the caller cannot read is reported as zero rather than omitted. Subtler: the numbers
#    are all correct and the *list* discloses which queues exist.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/reports/queue_summary.py")
s = p.read_text()
s = s.replace(
    "        if definition.permission not in actor.permissions:",
    "        if False:",
)
s = s.replace(
    "        page = read_queue_page(",
    "        if definition.permission not in actor.permissions:\n"
    "            counts.append(QueueCount(queue=name, waiting=0))\n"
    "            continue\n"
    "        page = read_queue_page(",
)
p.write_text(s)
EOF
probe "2. an unreadable queue is reported as zero instead of omitted"

# 3. The route's own grant goes, so anyone with a session can ask.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/reports.py")
s = p.read_text()
s = s.replace('    dependencies=[requires("report.read")],\n', "")
p.write_text(s)
EOF
probe "3. the report is reachable without report.read"

# 4. The report counts with its own query instead of the queue's predicate, so the two can drift.
#    Written as a plausible-looking reimplementation rather than an obvious break.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/reports/queue_summary.py")
s = p.read_text()
s = s.replace(
    "        page = read_queue_page(\n"
    "            session,\n"
    "            definition,\n"
    "            select(definition.entity),\n"
    "            actor=actor,\n"
    "            limit=1,\n"
    "        )\n"
    "        counts.append(QueueCount(queue=name, waiting=page.total))",
    "        from sqlalchemy import func as _f\n"
    "        total = session.execute(\n"
    "            select(_f.count()).select_from(definition.entity)\n"
    "        ).scalar_one()\n"
    "        counts.append(QueueCount(queue=name, waiting=int(total)))",
)
p.write_text(s)
EOF
probe "4. the report counts rows the queue's predicate excludes"

# 5. The queue stops excluding the adjacent state, so an item a person has taken stays listed. Only
#    the walk notices: every static assertion about the queue still holds.
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
probe "5. work stays in the queue after somebody takes it"

echo
echo "=== restored ==="
git status --short
