#!/usr/bin/env bash
# Ruff and mypy with exactly the arguments `infra/scripts/verify-native.sh` uses.
#
# Running `ruff check services/backend tests` by hand reports hundreds of findings this repository
# does not gate on: a different config and a different target list. Three CI failures have come from
# verifying with a subset or a different invocation, so this exists to make the short loop identical
# to the gate.
set -euo pipefail

cd "$(dirname "$0")/.."

lint_targets=$(grep -vE '^\s*(#|$)' infra/verification/lint_targets.txt | tr '\n' ' ')
if [ -z "$lint_targets" ]; then
    printf '%s\n' "infra/verification/lint_targets.txt is empty or unreadable." >&2
    exit 1
fi

# shellcheck disable=SC2086
uv run --project services/backend --frozen \
    ruff check --config services/backend/pyproject.toml $lint_targets
uv run --project services/backend --frozen \
    mypy --config-file services/backend/pyproject.toml services/backend/app
