#!/usr/bin/env bash
# Negative controls for M11 Screens slice 7 — dispatch and closure.
#
# **Control 1 is the one this slice exists to test.** The guard override is the only control on
# these screens that changes what the system *allows*: without a reason the server refuses to
# dispatch against an unpaid order; with one the refusal becomes a recorded override. An empty
# string sent instead of `null` records an override nobody authorised — and nothing about the
# request looks wrong.
#
#   1. the screen sends an empty override reason instead of omitting it
#   2. the trader screen invents a current dispatch
#   3. the dispatch list stops being published
#   4. a warehouse queue points somewhere else
#
# Control 0 runs the suite CLEAN FIRST.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:55500/postgres}"

ADMIN_PAGE="apps/admin-web/app/gold-orders/[orderId]/page.tsx"
TRADER_PAGE="apps/trader-pwa/app/gold-orders/[orderId]/page.tsx"
ROUTER=services/backend/app/api/v1/gold_sale_orders.py
QUEUES=services/backend/app/queues/manager_and_warehouse.py

BACKUP=$(mktemp -d)
cp "$ADMIN_PAGE" "$BACKUP/admin.tsx"
cp "$TRADER_PAGE" "$BACKUP/trader.tsx"
cp "$ROUTER" "$BACKUP/router.py"
cp "$QUEUES" "$BACKUP/queues.py"

restore() {
    cp "$BACKUP/admin.tsx" "$ADMIN_PAGE"
    cp "$BACKUP/trader.tsx" "$TRADER_PAGE"
    cp "$BACKUP/router.py" "$ROUTER"
    cp "$BACKUP/queues.py" "$QUEUES"
}
trap restore EXIT

gates() {
    uv run --project services/backend --frozen \
        pytest -c services/backend/pyproject.toml \
        tests/backend/test_dispatch_screens_exist.py \
        tests/backend/test_result_screens_exist.py \
        -q 2>&1 | tail -5
}

echo "=================== CONTROL 0 — clean, must be GREEN ==================="
gates

echo
echo "=================== CONTROL 1 — an override reason nobody wrote ==================="
echo "The only control here that changes what the system allows. An empty string records an"
echo "override as though somebody had authorised one, and nothing about the request looks wrong."
python3 scripts/control-override-sends-empty-reason.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== CONTROL 2 — the screen invents a current dispatch ==================="
echo "Six statuses including superseded, no unique constraint per order. A guess given a name."
python3 scripts/control-invents-current-dispatch.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== CONTROL 3 — the dispatch list is unpublished ==================="
echo "The acknowledge route then names an id no trader can obtain — a path parameter with no"
echo "source, which is the defect slice 7 found and slice 5's gate could not see."
python3 scripts/control-unpublish-dispatch-list.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== CONTROL 4 — a warehouse queue points elsewhere ==================="
python3 scripts/control-warehouse-queue-misdirected.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== restored ==================="
git status --porcelain -- "$ADMIN_PAGE" "$TRADER_PAGE" "$ROUTER" "$QUEUES"
echo "(empty above means every file is back)"
