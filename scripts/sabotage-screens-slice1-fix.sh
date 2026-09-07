#!/usr/bin/env bash
# Negative controls for the slice 1 CI repair.
#
# The repair widened a floor that had just fired — the move
# `tests/integration/test_navigation_is_not_a_control.py` explicitly names as the wrong one — and
# justified it with "there is no notification permission to gate on". These controls ask whether
# that justification is actually enforced or merely written down.
#
# Control 0 runs CLEAN FIRST. "CAUGHT" from a suite that was already red is not evidence.
#
# The catalogue is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

export INTEGRATION_ADMIN_DATABASE_URL="${INTEGRATION_ADMIN_DATABASE_URL:-postgresql://postgres:postgres@127.0.0.1:55500/postgres}"

CATALOGUE=docs/governance/permission_catalog.yaml
NAVIGATION=apps/admin-web/src/navigation.ts
TARGET=tests/integration/test_navigation_is_not_a_control.py

BACKUP=$(mktemp -d)
cp "$CATALOGUE" "$BACKUP/catalogue.yaml"
cp "$NAVIGATION" "$BACKUP/navigation.ts"

restore() {
    cp "$BACKUP/catalogue.yaml" "$CATALOGUE"
    cp "$BACKUP/navigation.ts" "$NAVIGATION"
}
trap restore EXIT

run_target() {
    uv run --project services/backend --frozen \
        pytest -c services/backend/pyproject.toml "$TARGET" -q 2>&1 | tail -4
}

echo "=================== CONTROL 0 — clean, must be GREEN ==================="
run_target

echo
echo "=================== CONTROL 1 — a notification permission is approved ==================="
echo "The exemption's whole reason is that no such permission exists. If one is added and the"
echo "suite stays green, the reason was never enforced and the widening was just a widening."
python3 scripts/control-add-notification-permission.py || { echo "EDIT DID NOT APPLY"; exit 1; }
run_target
restore

echo
echo "=================== CONTROL 2 — a third item goes ungated ==================="
echo "The floor must still be an equality, not an allowlist that has stopped counting."
python3 scripts/control-ungate-a-third-item.py || { echo "EDIT DID NOT APPLY"; exit 1; }
run_target
restore

echo
echo "=================== CONTROL 3 — the catalogue pattern stops matching ==================="
echo "Guard the guard. A parse that finds nothing would report 'no notification permission'"
echo "for the wrong reason, and control 1 would go quiet with it."
python3 scripts/control-break-catalogue-indent.py || { echo "EDIT DID NOT APPLY"; exit 1; }
run_target
restore

echo
echo "=================== restored ==================="
git status --porcelain -- "$CATALOGUE" "$NAVIGATION"
echo "(empty above means both files are back)"
