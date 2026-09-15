#!/usr/bin/env bash
# Negative controls for M12 slice 5b — the queue performance measurement.
#
# **A performance test is the easiest kind to write vacuously.** It can assert a threshold no
# machine would exceed, measure a query nobody runs, or bound a field that reports zero for the
# plan it exists to refuse. Every control here leaves a system that answers every request
# correctly and returns the same rows — only the *cost* changes, which is the whole point: none of
# these would be caught by any other suite in the repository.
#
# Controls 2 and 8 are the ones to read. Control 2 replaces `_rows_touched` with the naive reading
# of `Actual Rows` — the trap this file was written around, where a sequential scan of fifty
# thousand rows reports zero because none survived the filter. Control 8 records a measurement for
# the three fast queues and omits the slow one, which is the evidence set reading as complete while
# being selective.
#
# Control 0 runs the suite CLEAN FIRST. Restores with `cp`, never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

PY=services/backend/.venv/bin/python
export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql+psycopg://postgres:postgres@172.17.0.2:5432/postgres}"

QUEUES=services/backend/app/queues/payment_requests.py
CONTRACT=services/backend/app/queues/contract.py
PAGINATION=services/backend/app/db/pagination.py
EMITTER=services/backend/scripts/emit_evidence.py
PERF=tests/integration/test_queue_performance.py

WORK=$(mktemp -d)
cp "$QUEUES" "$WORK/queues.py"
cp "$CONTRACT" "$WORK/contract.py"
cp "$PAGINATION" "$WORK/pagination.py"
cp "$EMITTER" "$WORK/emitter.py"
cp "$PERF" "$WORK/perf.py"

restore_files() {
  cp "$WORK/queues.py" "$QUEUES"
  cp "$WORK/contract.py" "$CONTRACT"
  cp "$WORK/pagination.py" "$PAGINATION"
  cp "$WORK/emitter.py" "$EMITTER"
  cp "$WORK/perf.py" "$PERF"
}
trap restore_files EXIT

SUITE="tests/integration/test_queue_performance.py tests/backend/test_evidence_emitter.py tests/backend/test_traceability.py"

run_suite() {
  # shellcheck disable=SC2086
  $PY -m pytest -c services/backend/pyproject.toml $SUITE -q --no-header >"$WORK/out.txt" 2>&1
}

echo "=== CONTROL 0: clean. Anything but green here invalidates every result below. ==="
if run_suite; then
  echo "clean: green"
else
  echo "clean: NOT GREEN — stop."
  tail -20 "$WORK/out.txt"
  exit 1
fi

probe() {
  local name="$1"
  echo
  echo "=== $name ==="
  if run_suite; then
    echo "NOT CAUGHT"
  else
    echo "CAUGHT"
    grep -E '^FAILED|AssertionError' "$WORK/out.txt" | head -2
  fi
  restore_files
}

# 1. **The index stops covering the predicate.** Written as the developer mistake rather than as a
#    dropped index: wrapping the column in a function is a one-character-looking change that reads
#    as defensive normalisation and silently turns the page read into a scan of the whole table.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/payment_requests.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "from sqlalchemy import Select",
    "from sqlalchemy import Select, func",
    1,
)
s = s.replace(
    "        PaymentRequest.status == SUBMITTED_TO_CENTER,\n"
    "        PaymentRequest.review_note.is_(None),",
    "        func.lower(PaymentRequest.status) == SUBMITTED_TO_CENTER,\n"
    "        PaymentRequest.review_note.is_(None),",
    1,
)
assert s != before, "control 1 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "1. a predicate wraps the indexed column and stops using the index"

# 2. **Guard the guard.** `_rows_touched` becomes the naive reading. Nothing about the system
#    changes; the gate stops being able to see a sequential scan that returns nothing.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("tests/integration/test_queue_performance.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "    return max(\n"
    "        (node.get(\"Actual Rows\") or 0)\n"
    "        + (node.get(\"Rows Removed by Filter\") or 0)\n"
    "        + (node.get(\"Rows Removed by Index Recheck\") or 0)\n"
    "        for node in _walk(plan)\n"
    "    )",
    "    return max((node.get(\"Actual Rows\") or 0) for node in _walk(plan))",
)
assert s != before, "control 2 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "2. the row count reads only what survived the filter"

# 3. **The total is counted over the table instead of the queue.** A plausible "optimisation": the
#    subquery looks expensive, `count(*)` on the table is one line, and the number is wrong only
#    in a way nobody reading a queue screen would notice.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/queues/contract.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "    total = session.scalar(select(func.count()).select_from(narrowed.subquery())) or 0",
    "    total = session.scalar(select(func.count()).select_from(definition.entity)) or 0",
)
assert s != before, "control 3 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "3. the queue total counts the table rather than the queue"

# 4. **Offset semantics by another name.** The cursor predicate stops being applied, so every page
#    re-reads from the top. Rows returned stay plausible and the pages still advance, because the
#    ordering is unchanged — only the cost stops falling as you go.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/app/db/pagination.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "    effective_limit = normalise_limit(limit)",
    "    effective_limit = normalise_limit(limit)\n    cursor = None",
    1,
)
assert s != before, "control 4 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "4. the cursor stops narrowing, so a deep page costs what the first page costs"

# 5. The emitter invents a figure when the run took no measurement. This is the failure the whole
#    split exists to prevent: an artifact describing a deployment nobody measured.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/scripts/emit_evidence.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "    if not QUEUE_PERFORMANCE_MEASUREMENT.exists():\n"
    "        return None, PERFORMANCE_NOT_MEASURED_BY_THIS_RUN",
    "    if not QUEUE_PERFORMANCE_MEASUREMENT.exists():\n"
    "        return {\"volume\": {}, \"environment\": {}, \"queues\": {}}, None",
)
assert s != before, "control 5 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "5. the emitter supplies an empty measurement instead of saying there is none"

# 6. The emitter flattens the record to a millisecond figure. It reads like tidying — the field is
#    called `performance_p95`, so a p95 is what belongs in it — and it reintroduces the exact gap
#    PERF-QUEUE-001 recorded, while reporting it closed.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/scripts/emit_evidence.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "        artifact[\"performance_p95\"] = measurement",
    "        artifact[\"performance_p95\"] = max(\n"
    "            (queue[\"milliseconds\"][\"p95\"] for queue in measurement[\"queues\"].values()),\n"
    "            default=None,\n"
    "        )",
)
assert s != before, "control 6 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "6. the emitter reduces the measurement to a bare millisecond figure"

# 7. A partial record is filed rather than refused. An interrupted run writes a file with a volume
#    and no environment; this accepts it, and the artifact then carries a p95 nobody can place.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("services/backend/scripts/emit_evidence.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "    missing = [key for key in (\"volume\", \"environment\", \"queues\") if key not in record]",
    "    missing: list[str] = []",
)
assert s != before, "control 7 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "7. a measurement missing its environment is filed rather than refused"

# 8. **The record covers the fast queues and omits the slow one.** Not a lie in any single field:
#    every number in it is correct. It is the shape of the omission that matters — the one read
#    whose cost tracks the whole table is the one a release reader most needs to see.
$PY - <<'EOF'
import pathlib
p = pathlib.Path("tests/integration/test_queue_performance.py")
s = p.read_text(encoding="utf-8")
before = s
s = s.replace(
    "    for queue_name in (*BOUNDED_QUEUES, UNBOUNDED_QUEUE):\n"
    "        page, _ = _what_read_queue_page_actually_runs(session, queue_name)",
    "    for queue_name in BOUNDED_QUEUES:\n"
    "        page, _ = _what_read_queue_page_actually_runs(session, queue_name)",
)
assert s != before, "control 8 did not modify the file; the sabotage is stale"
p.write_text(s, encoding="utf-8")
EOF
probe "8. the recorded measurement omits the one slow queue"

echo
echo "=== restored ==="
git status --short "$QUEUES" "$CONTRACT" "$PAGINATION" "$EMITTER" "$PERF"
