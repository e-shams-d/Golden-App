#!/usr/bin/env bash
# Negative controls for M8 slice 3 — the review queue.
#
# Four the plan names, plus two the constraints suggested.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

MODEL="services/backend/app/db/models/manual_review_task.py"
CMD="services/backend/app/commands/manual_review_task.py"
EXPORT="services/backend/app/commands/bank_export.py"
BACKUP="$(mktemp -d)"

cp "$MODEL" "$BACKUP/model.py"
cp "$CMD" "$BACKUP/cmd.py"
cp "$EXPORT" "$BACKUP/export.py"

restore() {
  cp "$BACKUP/model.py" "$MODEL"
  cp "$BACKUP/cmd.py" "$CMD"
  cp "$BACKUP/export.py" "$EXPORT"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
UNIT=tests/backend/test_review_queue_shape.py
LIVE=tests/integration/test_review_queue.py
EXPORT_LIVE=tests/integration/test_export_download_and_sent.py
OUT="$BACKUP/out.txt"

run() {
  local label="$1" expect="$2" target="$3"
  "$PYTHON" -m pytest "$target" -q > "$OUT" 2>&1

  if ! grep -qE '[0-9]+ (passed|failed)' "$OUT"; then
    printf '  INVALID RUN  %s\n' "$label"
    tail -4 "$OUT"
    restore
    return
  fi
  if grep -qE '[0-9]+ failed' "$OUT"; then
    printf '  CAUGHT   %-46s' "$label"
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

echo "== M8 slice 3 negative controls =="

# 1. SVC-QUARANTINE-001, the plan's first named control. Make `open_task` raise instead of returning
#    the existing row, and the second revalidation of a tampered export blows up rather than finding
#    the task already in front of somebody.
# Targeted at the direct test, not the export flow. Through the quarantine route this sabotage is
# NOT CAUGHT and correctly so: `SEC-DOWNLOAD-001`'s guard refuses a second download before
# revalidation, so the repeat path is unreachable from there. Pointing the control at the export
# tests made a right control look like a weak test.
perl -0pi -e 's/        return existing\n/        raise BusinessRuleViolationError("already open")\n/' "$CMD"
run "open_task raises on a repeat" "same_task_twice_returns_the_first" "$LIVE"

# 2. SVC-TASK-001. Permit `resolved -> in_progress`, which erases the disposition `:2065` requires a
#    resolved task to carry. The most plausible sabotage in the file: "reopening" reads as a feature.
#
#    Anchored on the constant names, not on string literals. The first version of this control
#    matched `("in_progress", "cancelled")` and silently did nothing, because the transition set is
#    written with the module's status constants — a sabotage that does not apply reports NOT CAUGHT,
#    which is the reading that looks like a weak test rather than a broken control.
perl -0pi -e 's/        \(TASK_IN_PROGRESS, TASK_CANCELLED\),/        (TASK_IN_PROGRESS, TASK_CANCELLED),\n        (TASK_RESOLVED, TASK_IN_PROGRESS),/' "$CMD"
run "a resolved task can be reopened" "permitted_transitions_are_exactly_five" "$UNIT"

# 3. SVC-TASK-001. Resolve without requiring a code — the API-level half of `:2065`'s explicit
#    disposition. The table would still refuse, which is the point: this proves the *command* asks.
perl -0pi -e 's/    if command\.resolution_code == RESOLUTION_UNRESOLVED and not note:/    if False:/' "$CMD"
run "an unresolved resolution needs no reason" "requires_a_reason" "$LIVE"

# 4. SVC-TASK-002. Add a typed reference to a financial row, which is exactly the "financial
#    relationship truth" §13.1 puts in explicit tables — and exactly what slice 3's own caller would
#    have found convenient.
perl -0pi -e 's/(    task_type: Mapped\[str\] = mapped_column\(String\(64\), nullable=False\))/    bank_excel_export_id: Mapped[uuid.UUID | None] = mapped_column(\n        PostgresUUID(as_uuid=True), nullable=True\n    )\n$1/' "$MODEL"
run "the task gains a typed export reference" "no_typed_reference_to_a_financial_row" "$UNIT"

# 5. The queue index widens to cover finished work, so every queue read scans resolved tasks.
perl -0pi -e 's/            postgresql_where=f"status IN \(\{_quoted\(OPEN_STATUSES\)\}\)",\n        \),\n        Index\(\n            "idx_manual_review_assignee"/            postgresql_where="1 = 1",\n        ),\n        Index(\n            "idx_manual_review_assignee"/' "$MODEL"
run "the queue index covers finished work" "covers_exactly_the_open_states" "$UNIT"

# 6. The quarantine path stops raising a task at all — M7's original omission, restored.
perl -0pi -e 's/    open_review_task\(/    _skipped = lambda *a, **k: None\n    _skipped(/' "$EXPORT"
run "quarantine raises no task" "revalidated_before_every_download" "$EXPORT_LIVE"

echo "== done =="
