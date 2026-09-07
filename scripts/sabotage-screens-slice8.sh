#!/usr/bin/env bash
# Negative controls for M11 Screens slice 8 — the Definition of Done gate.
#
# This gate's whole value is that it cannot be satisfied cheaply, so the controls are mostly about
# **the gate itself** rather than about the code it watches.
#
#   1. a new operation ships with no screen and no entry      — the thing it exists for
#   2. an entry loses its reason and becomes an allowlist row
#   3. the dynamic rule keeps its exemption after the mechanism goes
#   4. a recorded operation gains a screen and the entry stays
#
# Control 3 is the one to watch: `DYNAMIC` exempts sixteen operations on one sentence, and a
# sentence anybody can write about anything is not an exemption.
#
# Control 0 runs the suite CLEAN FIRST.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

GATE=tests/backend/test_every_operation_has_a_screen.py
MODULE=apps/admin-web/src/queues.ts
CONTRACT=services/backend/openapi/v1.json

BACKUP=$(mktemp -d)
cp "$GATE" "$BACKUP/gate.py"
cp "$MODULE" "$BACKUP/queues.ts"
cp "$CONTRACT" "$BACKUP/v1.json"

restore() {
    cp "$BACKUP/gate.py" "$GATE"
    cp "$BACKUP/queues.ts" "$MODULE"
    cp "$BACKUP/v1.json" "$CONTRACT"
}
trap restore EXIT

gates() {
    uv run --project services/backend --frozen \
        pytest -c services/backend/pyproject.toml "$GATE" -q 2>&1 | tail -4
}

echo "=================== CONTROL 0 — clean, must be GREEN ==================="
gates

echo
echo "=================== CONTROL 1 — an operation ships with no screen ==================="
echo "The thing this gate exists for: a backend surface nobody can reach, and nothing says so."
python3 scripts/control-operation-without-a-screen.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== CONTROL 2 — an entry loses its reason ==================="
echo "A row with no sentence is an allowlist row, and the list stops being an answer to"
echo "'how much of this system can a person use'."
python3 scripts/control-entry-loses-its-reason.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== CONTROL 3 — the dynamic mechanism disappears ==================="
echo "Sixteen operations are exempt because one module builds their paths. If that module stops"
echo "doing so and the exemption stands, sixteen surfaces are unreachable and nothing notices."
python3 scripts/control-dynamic-mechanism-removed.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== CONTROL 4 — a recorded entry goes stale ==================="
echo "An operation that gains a screen must leave the list, or the list claims part of the"
echo "system is unreachable when it is not."
python3 scripts/control-recorded-entry-goes-stale.py || { echo "EDIT DID NOT APPLY"; exit 1; }
gates
restore

echo
echo "=================== restored ==================="
git status --porcelain -- "$GATE" "$MODULE" "$CONTRACT"
echo "(empty above means every file is back)"
