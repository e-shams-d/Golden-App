#!/usr/bin/env bash
# Negative controls for M11 Screens slice 6 — the incoming payment claim and its review.
#
# **Control 1 is the one this slice exists to test.** Slice 5 recorded both incoming-payment gaps
# as needing the receipt's version; only one does. The sabotage reproduces that belief — echo the
# receipt's version into the reject — and asks whether anything notices, because a recorded gap
# that names the wrong aggregate is closed by a read that does not satisfy it.
#
#   1. the reject echoes the receipt's version instead of the match's
#   2. the receipt read drops its ETag
#   3. the trader bundle learns the centre's matching path
#   4. an unconfirmed claim renders as zero
#   5. the receipt queue points at the wrong screen
#
# Control 0 runs the suite CLEAN FIRST. A test that fails against everything catches everything.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:55500/postgres}"

ROUTER=services/backend/app/api/v1/incoming_matches.py
QUEUES=services/backend/app/queues/money_movement.py
WAREHOUSE=services/backend/app/queues/manager_and_warehouse.py
PAGE="apps/admin-web/app/incoming-payments/[receiptId]/page.tsx"
TRADER_MODULE=apps/trader-pwa/src/incoming-receipts.ts

BACKUP=$(mktemp -d)
cp "$ROUTER" "$BACKUP/router.py"
cp "$QUEUES" "$BACKUP/queues.py"
cp "$WAREHOUSE" "$BACKUP/warehouse.py"
cp "$PAGE" "$BACKUP/page.tsx"
cp "$TRADER_MODULE" "$BACKUP/trader.ts"

restore() {
    cp "$BACKUP/router.py" "$ROUTER"
    cp "$BACKUP/queues.py" "$QUEUES"
    cp "$BACKUP/warehouse.py" "$WAREHOUSE"
    cp "$BACKUP/page.tsx" "$PAGE"
    cp "$BACKUP/trader.ts" "$TRADER_MODULE"
}
trap restore EXIT

gates() {
    uv run --project services/backend --frozen \
        pytest -c services/backend/pyproject.toml \
        tests/backend/test_incoming_screens_exist.py \
        tests/backend/test_preconditions_have_a_source.py \
        tests/backend/test_result_screens_exist.py \
        -q 2>&1 | tail -5
}

echo "=================== CONTROL 0 — clean, must be GREEN ==================="
gates

echo
echo "=================== CONTROL 1 — the reject echoes the wrong aggregate ==================="
echo "Slice 5's mistaken belief, made real. The header is present and well-formed and names the"
echo "receipt's version for a command that edits the match row."
python3 scripts/control-reject-echoes-receipt-version.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== CONTROL 2 — the receipt read drops its ETag ==================="
python3 scripts/control-receipt-read-drops-etag.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== CONTROL 3 — the trader bundle learns the matching path ==================="
echo "A trader who could name the proving row would be deciding their own case. The server"
echo "refuses; the path should not be in that bundle to try."
python3 scripts/control-trader-learns-matching.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== CONTROL 4 — an unconfirmed claim renders as zero ==================="
echo "On this screen the difference decides whether the accountant still has work: a claim"
echo "showing 0 reads as reviewed and settled at nothing."
python3 scripts/control-unconfirmed-renders-zero.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== CONTROL 5 — the queue points at the wrong screen ==================="
echo "The warehouse's confirmation queue is over gold orders. Pointing it at the receipt screen"
echo "is the wrong screen for the right row — what detail_path exists to prevent."
python3 scripts/control-queue-points-at-wrong-screen.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== restored ==================="
git status --porcelain -- "$ROUTER" "$QUEUES" "$WAREHOUSE" "$PAGE" "$TRADER_MODULE"
echo "(empty above means every file is back)"
