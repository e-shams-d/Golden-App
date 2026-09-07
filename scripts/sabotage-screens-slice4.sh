#!/usr/bin/env bash
# Negative controls for M11 Screens slice 4 — the centre's result surface.
#
# The slice makes five claims, and the ones worth controls are the two corrections it made to its
# own obligation plus the read it had to add:
#
#   1. the attempt read returns the ETag the four commands compare against;
#   2. no screen sends a step-up the server does not require;
#   3. the correction screen stays absent while its grant is unassigned;
#   4. queue rows link where the *server* says, not where the frontend guesses;
#   5. no confirmation body carries an amount.
#
# Control 3 is the one to watch: it is an *absence*, and an absence is the hardest thing to keep.
#
# Control 0 runs the suite CLEAN FIRST. A test that fails against everything catches everything.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:55500/postgres}"

ROUTER=services/backend/app/api/v1/payment_attempts.py
MODULE=apps/admin-web/src/payment-results.ts
PUBLICATION_PAGE="apps/admin-web/app/requests/[requestId]/publication/page.tsx"
TABLE=apps/admin-web/components/queue-table.tsx
CATALOGUE=docs/governance/permission_catalog.yaml

BACKUP=$(mktemp -d)
cp "$ROUTER" "$BACKUP/router.py"
cp "$MODULE" "$BACKUP/module.ts"
cp "$PUBLICATION_PAGE" "$BACKUP/publication.tsx"
cp "$TABLE" "$BACKUP/table.tsx"
cp "$CATALOGUE" "$BACKUP/catalogue.yaml"

restore() {
    cp "$BACKUP/router.py" "$ROUTER"
    cp "$BACKUP/module.ts" "$MODULE"
    cp "$BACKUP/publication.tsx" "$PUBLICATION_PAGE"
    cp "$BACKUP/table.tsx" "$TABLE"
    cp "$BACKUP/catalogue.yaml" "$CATALOGUE"
}
trap restore EXIT

python_gates() {
    uv run --project services/backend --frozen \
        pytest -c services/backend/pyproject.toml \
        tests/integration/test_payment_results.py \
        tests/backend/test_result_screens_exist.py \
        -q 2>&1 | tail -5
}

echo "=================== CONTROL 0 — clean, must be GREEN ==================="
python_gates

echo
echo "=================== CONTROL 1 — the read stops returning an ETag ==================="
echo "The commands then have no source for their precondition and a screen is back to guessing."
echo "Nothing fails on the server: the read still answers 200 with the version in the body."
python3 scripts/control-attempt-read-drops-etag.py || { echo "EDIT DID NOT APPLY"; exit 1; }
python_gates
restore

echo
echo "=================== CONTROL 2 — the publish screen asks for a step-up ==================="
echo "A control the backend does not have, and the harm is a habit: somebody taught to"
echo "reauthenticate whenever a screen asks will do it for a screen that should not have asked."
python3 scripts/control-publish-adds-step-up.py || { echo "EDIT DID NOT APPLY"; exit 1; }
python_gates
restore

echo
echo "=================== CONTROL 3 — the correction grant is assigned ==================="
echo "The deferral must expire by itself. If ADR-SEC-009 is settled and nothing notices, the"
echo "screen stays missing for a capability the centre now has."
python3 scripts/control-assign-correction-grant.py || { echo "EDIT DID NOT APPLY"; exit 1; }
python_gates
restore

echo
echo "=================== CONTROL 4 — the table guesses its own destinations ==================="
echo "The wrong screen for the right row: an accountant opening somebody else's work believing"
echo "it was theirs. Worse than no link."
python3 scripts/control-queue-table-hardcodes-destination.py || { echo "EDIT DID NOT APPLY"; exit 1; }
python_gates
restore

echo
echo "=================== CONTROL 5 — a confirmation sends an amount ==================="
echo "§17's \"amount is exact\" is honoured by the field's absence. A client figure could"
echo "disagree with the attempt, and the server would have two answers to one question."
python3 scripts/control-confirm-sends-an-amount.py || { echo "EDIT DID NOT APPLY"; exit 1; }
python_gates
restore

echo
echo "=================== restored ==================="
git status --porcelain -- "$ROUTER" "$MODULE" "$PUBLICATION_PAGE" "$TABLE" "$CATALOGUE"
echo "(empty above means every file is back)"
