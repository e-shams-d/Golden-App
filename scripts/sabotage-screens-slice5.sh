#!/usr/bin/env bash
# Negative controls for M11 Screens slice 5 — gold orders, and the precondition gate it built.
#
# The slice's own claims are ordinary. **The control worth running is number 2**, because the gate
# added here is the one that generalises: if it can be undone by a change nobody would think twice
# about, the two defects it was built for come back.
#
#   1. the gold order read stops issuing an ETag         — the defect that started the slice
#   2. a recorded gap is quietly promoted to an exemption — the gate defeating itself
#   3. the pricing screen calculates the expected amount  — two answers to one question about money
#   4. a weight is parsed to a number                     — rounding the string type exists to stop
#   5. an unpriced order renders as zero                  — quoting a trader nothing
#
# Control 0 runs the suite CLEAN FIRST. A test that fails against everything catches everything.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:55500/postgres}"

ROUTER=services/backend/app/api/v1/gold_sale_orders.py
GATE=tests/backend/test_preconditions_have_a_source.py
PRICING="apps/admin-web/app/gold-orders/[orderId]/page.tsx"
TRADER_LIST=apps/trader-pwa/app/gold-orders/page.tsx

BACKUP=$(mktemp -d)
cp "$ROUTER" "$BACKUP/router.py"
cp "$GATE" "$BACKUP/gate.py"
cp "$PRICING" "$BACKUP/pricing.tsx"
cp "$TRADER_LIST" "$BACKUP/trader-list.tsx"

restore() {
    cp "$BACKUP/router.py" "$ROUTER"
    cp "$BACKUP/gate.py" "$GATE"
    cp "$BACKUP/pricing.tsx" "$PRICING"
    cp "$BACKUP/trader-list.tsx" "$TRADER_LIST"
}
trap restore EXIT

gates() {
    uv run --project services/backend --frozen \
        pytest -c services/backend/pyproject.toml \
        tests/backend/test_gold_screens_exist.py \
        tests/backend/test_preconditions_have_a_source.py \
        -q 2>&1 | tail -5
}

echo "=================== CONTROL 0 — clean, must be GREEN ==================="
gates

echo
echo "=================== CONTROL 1 — the gold order read drops its ETag ==================="
echo "The defect that started this slice. The route still answers 200 with the version in the"
echo "body; four commands simply have no source for their precondition again."
python3 scripts/control-gold-read-drops-etag.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== CONTROL 2 — a recorded gap becomes an exemption ==================="
echo "The gate defeating itself, and the one control that matters. An exemption says 'the"
echo "precondition comes from elsewhere'; a gap says 'it comes from nowhere'. Moving an entry"
echo "between them turns a defect into a design with one line and no code change."
python3 scripts/control-gap-becomes-exemption.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== CONTROL 3 — the pricing screen computes the amount ==================="
echo "Two answers to one question about money. Both plausible, and which one a trader was"
echo "quoted depends on which surface they read."
python3 scripts/control-pricing-computes-amount.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== CONTROL 4 — a weight is parsed to a number ==================="
echo "Silent by construction: the value renders, and differs from the stored one in the digit"
echo "that matters."
python3 scripts/control-gold-weight-parsed.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== CONTROL 5 — an unpriced order renders as zero ==================="
echo "Zero is a price. A trader would read it as the centre having quoted them nothing."
python3 scripts/control-unpriced-renders-zero.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== restored ==================="
git status --porcelain -- "$ROUTER" "$GATE" "$PRICING" "$TRADER_LIST"
echo "(empty above means every file is back)"
