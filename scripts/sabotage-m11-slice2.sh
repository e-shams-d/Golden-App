#!/usr/bin/env bash
# Negative controls for M11 slice 2 — the queue contract.
#
# §19 `:1298` lists six query rules. Controls 1 to 7 break them one at a time, because a suite that
# asserts "the queue paginates" passes against an implementation missing four of them. Controls 8
# to 10 attack the contract itself: the permission, the count's scope, and the registry that makes
# the twenty-three unbuilt queues visible.
#
# Control 0 runs the suite CLEAN FIRST. "CAUGHT" from an already-red suite is not evidence.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:55500/postgres}"

CONTRACT=services/backend/app/queues/contract.py
QUEUE=services/backend/app/queues/payment_requests.py
ROUTE=services/backend/app/api/v1/queues.py
REGISTRY=services/backend/app/queues/registry.py

BACKUP=$(mktemp -d)
cp "$CONTRACT" "$BACKUP/contract.py"
cp "$QUEUE" "$BACKUP/queue.py"
cp "$ROUTE" "$BACKUP/route.py"
cp "$REGISTRY" "$BACKUP/registry.py"

restore() {
  cp "$BACKUP/contract.py" "$CONTRACT"
  cp "$BACKUP/queue.py" "$QUEUE"
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

# 1. Rule 3: an unallowlisted sort is ignored instead of refused. The caller receives a different
#    page than they asked for and is told nothing.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/queues.py")
s = p.read_text()
s = s.replace("            sort=sort,\n", "            sort=None,\n")
p.write_text(s)
EOF
probe "1. an unallowlisted sort is silently ignored"

# 2. Rule 3 again, from the other side: the filter allowlist is not consulted at all.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/contract.py")
s = p.read_text()
s = s.replace("        definition.spec.require_filterable(name)\n", "")
p.write_text(s)
EOF
probe "2. the filter allowlist is never consulted"

# 3. Rule 2: the unique tiebreak is moved onto a column that is not unique. `ListSpec` refuses a
#    spec with no unique sort at all, so the sabotage has to lie about which one it is.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/payment_requests.py")
s = p.read_text()
s = s.replace('SortField("id", PaymentRequest.id, unique=True),', 'SortField("id", PaymentRequest.id),')
s = s.replace(
    'SortField("created_at", PaymentRequest.created_at),',
    'SortField("created_at", PaymentRequest.created_at, unique=True),',
)
p.write_text(s)
EOF
probe "3. created_at is claimed unique, so the sort has no real tiebreak"

# 4. Rule 6: the limit cap is removed, so a caller can load the whole table.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/queues.py")
s = p.read_text()
s = s.replace("            limit=limit,\n", "            limit=None,\n")
s = s.replace(
    "    with runtime.uow_factory() as uow:",
    "    limit = 10_000 if limit is not None else None\n    with runtime.uow_factory() as uow:",
)
p.write_text(s)
EOF
probe "4. the limit cap is bypassed"

# 5. Rule 5: the count is taken before the queue predicate, so it counts rows the queue excludes.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/contract.py")
s = p.read_text()
s = s.replace(
    "    total = session.scalar(select(func.count()).select_from(narrowed.subquery())) or 0",
    "    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0",
)
p.write_text(s)
EOF
probe "5. the count is taken before the queue's own predicate"

# 6. Rule 5 again: the count reports the page size, which is a number the caller already knows.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/contract.py")
s = p.read_text()
s = s.replace(
    "    return QueuePage(rows=page.rows, next_cursor=page.next_cursor, total=int(total))",
    "    return QueuePage(rows=page.rows, next_cursor=page.next_cursor, total=len(page.rows))",
)
p.write_text(s)
EOF
probe "6. the count is the page size rather than the work waiting"

# 7. The queue's defining state is widened to include the adjacent one, so two people are handed
#    the same request. This is the exclusion half that an inclusion-only test cannot see.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/payment_requests.py")
s = p.read_text()
s = s.replace(
    "    return statement.where(PaymentRequest.status == SUBMITTED_TO_CENTER)",
    "    return statement.where(\n"
    "        PaymentRequest.status.in_((SUBMITTED_TO_CENTER, 'under_accountant_review'))\n"
    "    )",
)
p.write_text(s)
EOF
probe "7. the queue returns work somebody has already started"

# 8. The queue is ordered newest-first, which starves the oldest request in the queue.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/queues.py")
s = p.read_text()
s = s.replace("            descending=False,\n", "            descending=True,\n")
p.write_text(s)
EOF
probe "8. the work queue is drained from the wrong end"

# 9. The route's guard is dropped, so an authenticated caller with no grant — and any trader —
#    reaches an internal work surface. This is the assertion the ownership-scope exemption rests on.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/api/v1/queues.py")
s = p.read_text()
s = s.replace("    dependencies=[requires(NEW_REQUESTS.permission)],\n", "")
p.write_text(s)
EOF
probe "9. the queue is reachable without the grant"

# 10. The registry stops naming the unbuilt queues, so a forgotten queue becomes silent again.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/registry.py")
s = p.read_text()
head, sep, _tail = s.partition("PLANNED: dict[str, str] = {")
p.write_text(head + sep + "\n}\n")
EOF
probe "10. the twenty-three unbuilt queues stop being tracked"

echo
echo "=== restored ==="
git status --short
