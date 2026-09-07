#!/usr/bin/env bash
# Negative controls for M11 Screens slice 3 — the trader's published result.
#
# The slice makes four claims, and the two that matter are about **agreement** rather than about
# behaviour: a screen and a server that disagree both work, and the disagreement is only visible
# to the person holding the phone.
#
#   1. `allowed_actions` offers the two responses exactly where the commands accept them;
#   2. the centre is never offered a trader's response;
#   3. the screen's precondition is the ETag it rendered, not a fresh one;
#   4. the screen invents no dispute-reason taxonomy the backend refused to write.
#
# Control 0 runs the suite CLEAN FIRST. A test that fails against everything catches everything.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:55500/postgres}"

PROJECTION=services/backend/app/commands/payment_request.py
PAGE="apps/trader-pwa/app/requests/[requestId]/result/page.tsx"
SWEEP=apps/trader-pwa/tests/a11y/shell.spec.ts

BACKUP=$(mktemp -d)
cp "$PROJECTION" "$BACKUP/payment_request.py"
cp "$PAGE" "$BACKUP/page.tsx"
cp "$SWEEP" "$BACKUP/shell.spec.ts"

restore() {
    cp "$BACKUP/payment_request.py" "$PROJECTION"
    cp "$BACKUP/page.tsx" "$PAGE"
    cp "$BACKUP/shell.spec.ts" "$SWEEP"
}
trap restore EXIT

python_gates() {
    uv run --project services/backend --frozen \
        pytest -c services/backend/pyproject.toml \
        tests/integration/test_trader_publications.py \
        tests/backend/test_review_transitions.py \
        tests/backend/test_publication_screen_exists.py \
        -q 2>&1 | tail -5
}

frontend_gates() {
    pnpm --filter @gold/trader-pwa test 2>&1 | tail -4
}

echo "=================== CONTROL 0 — clean, must be GREEN ==================="
python_gates
frontend_gates

echo
echo "=================== CONTROL 1 — the projection keeps offering after an answer ==================="
echo "The screen would show a customer a button the command then refuses with a 400. Nothing"
echo "fails on the server; the failure is a person pressing a button that does not work."
python3 scripts/control-projection-ignores-answer.py || { echo "EDIT DID NOT APPLY"; exit 1; }
python_gates
restore

echo
echo "=================== CONTROL 2 — the centre is offered a trader's response ==================="
echo "An offer the 403 withdraws, and on an internal screen it reads as a permission fault"
echo "rather than as a category error."
python3 scripts/control-projection-offers-staff.py || { echo "EDIT DID NOT APPLY"; exit 1; }
python_gates
restore

echo
echo "=================== CONTROL 3 — the screen re-reads before acting ==================="
echo "The subtlest of the five: it makes the precondition always current, so a correction that"
echo "landed while the trader was reading is silently agreed to. No error, ever."
python3 scripts/control-result-screen-refreshes-etag.py || { echo "EDIT DID NOT APPLY"; exit 1; }
python_gates
restore

echo
echo "=================== CONTROL 4 — the screen invents a reason taxonomy ==================="
echo "The one that nearly shipped. The server accepts anything, so the screen's list becomes the"
echo "closed list the backend deliberately refused to write."
python3 scripts/control-result-screen-invents-reasons.py || { echo "EDIT DID NOT APPLY"; exit 1; }
python_gates
restore

echo
echo "=================== CONTROL 5 — a trader screen leaves the sweep ==================="
echo "Silent by construction: the page still works and nothing checks it for accessibility."
python3 scripts/control-unsweep-trader-login.py || { echo "EDIT DID NOT APPLY"; exit 1; }
python_gates
frontend_gates
restore

echo
echo "=================== restored ==================="
git status --porcelain -- "$PROJECTION" "$PAGE" "$SWEEP"
echo "(empty above means every file is back)"
