#!/usr/bin/env bash
# Negative controls for M11 Screens slice 2 — the work queue surface.
#
# The slice makes four claims that could each be false while every screen still renders:
#
#   1. which queues a person sees is the *server's* answer, filtered by their grants;
#   2. the index discloses nothing the queue pages do not — one definition of "waiting";
#   3. paging walks a cursor, and the client cannot construct an offset;
#   4. the sixteen queue names live in the backend and only the words live in the frontend.
#
# Each control breaks exactly one of them. Controls 1 and 2 are the ones worth having: a leaky
# index looks like a working screen to everybody, and a second definition of "waiting" produces two
# plausible numbers rather than an error.
#
# Control 0 runs the suite CLEAN FIRST. A test that fails against everything catches everything.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:55500/postgres}"

INDEX_MODULE=services/backend/app/queues/index.py
SUMMARY=services/backend/app/reports/queue_summary.py
DATA_MODULE=apps/admin-web/src/queues.ts
PANEL=apps/admin-web/components/queue-index.tsx
MESSAGES=packages/localization/src/messages.ts

BACKUP=$(mktemp -d)
cp "$INDEX_MODULE" "$BACKUP/index.py"
cp "$SUMMARY" "$BACKUP/summary.py"
cp "$DATA_MODULE" "$BACKUP/queues.ts"
cp "$PANEL" "$BACKUP/panel.tsx"
cp "$MESSAGES" "$BACKUP/messages.ts"

restore() {
    cp "$BACKUP/index.py" "$INDEX_MODULE"
    cp "$BACKUP/summary.py" "$SUMMARY"
    cp "$BACKUP/queues.ts" "$DATA_MODULE"
    cp "$BACKUP/panel.tsx" "$PANEL"
    cp "$BACKUP/messages.ts" "$MESSAGES"
}
trap restore EXIT

python_gates() {
    uv run --project services/backend --frozen \
        pytest -c services/backend/pyproject.toml \
        tests/integration/test_queue_index.py \
        tests/backend/test_queue_screens_exist.py \
        -q 2>&1 | tail -4
}

frontend_gates() {
    pnpm --filter @gold/admin-web test 2>&1 | tail -4
}

echo "=================== CONTROL 0 — clean, must be GREEN ==================="
python_gates
frontend_gates

echo
echo "=================== CONTROL 1 — the index stops filtering by grant ==================="
echo "The leak that looks like a working screen. Every role would see all sixteen queues, and"
echo "nothing about the rendering would say so."
python3 scripts/control-index-ignores-grants.py || { echo "EDIT DID NOT APPLY"; exit 1; }
python_gates
restore

echo
echo "=================== CONTROL 2 — the index counts for itself ==================="
echo "A second definition of 'waiting'. Not an error — two plausible numbers, and the queue page"
echo "and the landing card start to disagree under a predicate the copy did not follow."
python3 scripts/control-index-counts-separately.py || { echo "EDIT DID NOT APPLY"; exit 1; }
python_gates
restore

echo
echo "=================== CONTROL 3 — the client learns to page by offset ==================="
python3 scripts/control-queue-offset-paging.py || { echo "EDIT DID NOT APPLY"; exit 1; }
frontend_gates
restore

echo
echo "=================== CONTROL 4 — the frontend keeps its own queue list ==================="
echo "The drift the index route exists to prevent."
python3 scripts/control-frontend-queue-list.py || { echo "EDIT DID NOT APPLY"; exit 1; }
python_gates
frontend_gates
restore

echo
echo "=================== CONTROL 5 — a queue loses its Persian label ==================="
echo "Silent by construction: the screen works and shows a URL segment to a Persian reader."
python3 scripts/control-remove-queue-label.py || { echo "EDIT DID NOT APPLY"; exit 1; }
python_gates
restore

echo
echo "=================== restored ==================="
git status --porcelain -- "$INDEX_MODULE" "$SUMMARY" "$DATA_MODULE" "$PANEL" "$MESSAGES"
echo "(empty above means every file is back)"
