#!/usr/bin/env bash
# Backend lint and types, invoked the way `infra/verification/verify-native.sh` invokes them.
#
# Written because linting `app/` alone passed while CI failed on a long line in `tests/`. The
# verifier reads its target list from `infra/verification/lint_targets.txt`, which covers more than
# the application package — so any subset of it is a different check with the same name.
#
# This is the third CI failure in this repository from verifying with a narrower command than the
# one that gates the merge.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

PYTHON=services/backend/.venv/bin/python
targets=$(grep -vE '^[[:space:]]*(#|$)' infra/verification/lint_targets.txt | tr '\n' ' ')

if [ -z "$targets" ]; then
    printf '%s\n' "lint_targets.txt is empty; a check over nothing passes." >&2
    exit 1
fi

printf 'ruff over: %s\n' "$targets"
# shellcheck disable=SC2086
"$PYTHON" -m ruff check --config services/backend/pyproject.toml $targets
"$PYTHON" -m mypy --config-file services/backend/pyproject.toml services/backend/app
printf '%s\n' "backend lint and types clean, over the verifier's own target list."
