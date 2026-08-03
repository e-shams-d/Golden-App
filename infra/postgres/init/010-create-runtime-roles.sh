#!/bin/sh
set -eu

: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${APP_DB_USER:?APP_DB_USER is required}"
: "${APP_DB_PASSWORD:?APP_DB_PASSWORD is required}"
: "${MIGRATION_DB_USER:?MIGRATION_DB_USER is required}"
: "${MIGRATION_DB_PASSWORD:?MIGRATION_DB_PASSWORD is required}"
: "${WORKER_DB_USER:?WORKER_DB_USER is required}"
: "${WORKER_DB_PASSWORD:?WORKER_DB_PASSWORD is required}"

# The SQL lives in infra/postgres/bootstrap/ so the identical statements can be
# replayed by the db-bootstrap one-shot on an already-initialised data directory,
# by the integration fixture per disposable database, and by the native CI job.
# docker-entrypoint-initdb.d runs only on a virgin data directory; nothing that
# must reach an existing volume may live here alone.
psql \
  --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=database="$POSTGRES_DB" \
  --set=app_role="$APP_DB_USER" \
  --set=app_password="$APP_DB_PASSWORD" \
  --set=migration_role="$MIGRATION_DB_USER" \
  --set=migration_password="$MIGRATION_DB_PASSWORD" \
  --set=worker_role="$WORKER_DB_USER" \
  --set=worker_password="$WORKER_DB_PASSWORD" \
  --file /bootstrap/020-runtime-roles.sql
