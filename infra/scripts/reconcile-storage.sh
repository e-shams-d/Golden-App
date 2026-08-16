#!/usr/bin/env sh
# Report disagreements between the file records and the stored objects.
#
# Run against the compose stack:  sh infra/scripts/reconcile-storage.sh
#
# THERE IS NO LOCAL MODE, and the reason is worth knowing before adding one. `Settings()`
# reads a `.env` from the working directory, and this repository's `.env` is docker
# compose's — it carries `POSTGRES_USER`, `COMPOSE_PROJECT_NAME` and a dozen more keys the
# backend model forbids. Running any backend CLI from the repository root therefore dies
# with thirteen validation errors about fields nobody asked for. That trap predates this
# script and belongs to every CLI here; a `LOCAL=1` flag that hit it would just be a
# documented way to fail.
#
# Exit 0 means the two agree. Exit 1 means something was found and the output names it;
# nothing is ever repaired, because a checksum mismatch may be corruption or tampering and
# that difference is a person's to judge (12_Security_RBAC_Audit.md:1571).
#
# The output carries storage keys, so it is operator material and does not belong in a
# ticket a trader can read.
set -eu

COMPOSE_FILE="${COMPOSE_FILE:-infra/compose/compose.local.yml}"
PROJECT_NAME="${PROJECT_NAME:-golden-demo}"
SERVICE="${SERVICE:-backend}"

exec docker compose --project-name "$PROJECT_NAME" --env-file .env -f "$COMPOSE_FILE" \
    exec -T "$SERVICE" python -m app.cli.reconcile_storage "$@"
