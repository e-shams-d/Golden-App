#!/usr/bin/env bash
# Negative controls for M11 Screens slice 9 — the review task screen.
#
# The slice closes a gap slice 8's gate made visible, so **control 1 is the gate's own claim**: a
# queue that shows rows and opens nothing. It was true for eleven milestones and nothing said so
# until a gate asked.
#
#   1. the queue's destination goes back to None
#   2. the screen offers resolution codes of its own
#   3. a command stops echoing the read's ETag
#
# Control 0 runs the suite CLEAN FIRST.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

QUEUES=services/backend/app/queues/money_movement.py
PAGE="apps/admin-web/app/review-tasks/[taskId]/page.tsx"
MODULE=apps/admin-web/src/review-tasks.ts

BACKUP=$(mktemp -d)
cp "$QUEUES" "$BACKUP/queues.py"
cp "$PAGE" "$BACKUP/page.tsx"
cp "$MODULE" "$BACKUP/module.ts"

restore() {
    cp "$BACKUP/queues.py" "$QUEUES"
    cp "$BACKUP/page.tsx" "$PAGE"
    cp "$BACKUP/module.ts" "$MODULE"
}
trap restore EXIT

gates() {
    uv run --project services/backend --frozen \
        pytest -c services/backend/pyproject.toml \
        tests/backend/test_review_task_screen_exists.py \
        tests/backend/test_result_screens_exist.py \
        tests/backend/test_every_operation_has_a_screen.py \
        -q 2>&1 | tail -5
}

echo "=================== CONTROL 0 — clean, must be GREEN ==================="
gates

echo
echo "=================== CONTROL 1 — the queue opens nothing again ==================="
echo "The state this slice found: rows on the dashboard, and nowhere to go. True for eleven"
echo "milestones, and nothing said so until slice 8's gate asked."
python3 scripts/control-review-queue-opens-nothing.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== CONTROL 2 — the screen invents resolution codes ==================="
echo "The server publishes the vocabulary on the row. A list written in the screen is the copy"
echo "that drifts, and a resolution nothing can group defeats the point of a queue."
python3 scripts/control-review-invents-resolutions.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== CONTROL 3 — a command computes its precondition ==================="
python3 scripts/control-review-computes-precondition.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== restored ==================="
git status --porcelain -- "$QUEUES" "$PAGE" "$MODULE"
echo "(empty above means every file is back)"
