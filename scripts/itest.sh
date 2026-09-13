#!/usr/bin/env bash
# Integration tests with the environment the verifier gives them.
#
# `INTEGRATION_ADMIN_DATABASE_URL` is what decides whether these run or skip, and a skipped
# integration suite reports success — so this resolves the address rather than assuming one, and
# fails loudly when it cannot.
#
# The container is `m2-itest-pg`. It has **no published port**: this daemon stopped creating new
# bindings and restarting it would stop unrelated projects' containers, so it is reached on the
# bridge address directly. That is why the 55500 and 55432 the older helper scripts use both fail
# with a connection timeout rather than a refusal.
set -euo pipefail

cd "$(dirname "$0")/.."

host=$(docker inspect m2-itest-pg \
    --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null || true)
if [ -z "$host" ]; then
    printf '%s\n' "m2-itest-pg is not running; integration tests would skip and report success." >&2
    exit 1
fi

export INTEGRATION_ADMIN_DATABASE_URL="postgresql+psycopg://postgres:postgres@${host}:5432/postgres"

uv run --project services/backend --frozen \
    pytest -c services/backend/pyproject.toml "$@"
