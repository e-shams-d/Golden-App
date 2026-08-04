-- Runtime role and ACL provisioning. Executed as $POSTGRES_USER by:
--   * infra/postgres/init/010-create-runtime-roles.sh (virgin data directory)
--   * the db-bootstrap Compose one-shot (every stack start)
--   * the integration suite's `provisioned_database` fixture, which replays this
--     file through tests/integration/bootstrap_replay.py against a disposable
--     database so the privilege tests measure this file and not a restatement
--     of it
-- Safe to re-run. Requires psql variables:
--   database,
--   app_role, app_password,
--   migration_role, migration_password,
--   worker_role, worker_password,
--   readonly_role, readonly_password,
--   backup_role, backup_password
--
-- The ACL statements below are per-database catalog state (pg_default_acl rows
-- live in the database the ALTER ran in). A disposable test database that has
-- not replayed this file has an empty pg_default_acl and makes SEC-ROLE-006
-- pass vacuously. Replay it; do not skip it.
--
-- No statement here grants CREATE ON DATABASE to any role. Do not add one.
\set ON_ERROR_STOP 1

REVOKE CREATE ON SCHEMA public FROM PUBLIC;

SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
  :'migration_role',
  :'migration_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'migration_role')
\gexec

SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
  :'app_role',
  :'app_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_role')
\gexec

-- A separate identity for background work. The worker runs the same code as the
-- API but is reached differently and fails differently, and one shared login
-- makes an audit row written by a scheduled task indistinguishable in
-- pg_stat_activity from one written by a request.
SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
  :'worker_role',
  :'worker_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'worker_role')
\gexec

-- Read-only: operator queries and support work. No writes, ever.
SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
  :'readonly_role',
  :'readonly_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'readonly_role')
\gexec

-- Backup: reads everything including audit and security history, writes nothing.
-- The role exists; no backup or restore capability is claimed by its existence.
-- ADR-004 is open, and per its safe default a backup claim is invalid until a
-- clean full restore drill has succeeded.
SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION',
  :'backup_role',
  :'backup_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'backup_role')
\gexec

GRANT CONNECT ON DATABASE :"database"
  TO :"migration_role", :"app_role", :"worker_role", :"readonly_role", :"backup_role";
GRANT USAGE, CREATE ON SCHEMA public TO :"migration_role";
GRANT USAGE ON SCHEMA public
  TO :"app_role", :"worker_role", :"readonly_role", :"backup_role";

-- Fail-closed by default. UPDATE and DELETE are NOT granted here.
--
-- The previous rule granted all four verbs on every table the migrator creates,
-- which meant an append-only table inherited the ability to be rewritten simply
-- by existing. `audit_logs` did, and a revoke in migration 20260801_0004 had to
-- take it back after the fact. That approach does not scale: `auth_events` in
-- slice 6 and the approval tables in M7 are append-only too, and each would need
-- someone to remember the same repair.
--
-- Mutation is now granted per table by the migration that creates it, so a table
-- nobody thought about is immutable rather than writable. The cost is real and
-- deliberate: forgetting a grant breaks that table's writes at runtime. A loud
-- failure on a table that should be mutable is the better error — the opposite
-- default fails silently on a table that should not be.
ALTER DEFAULT PRIVILEGES FOR ROLE :"migration_role" IN SCHEMA public
  GRANT SELECT, INSERT ON TABLES TO :"app_role", :"worker_role";
ALTER DEFAULT PRIVILEGES FOR ROLE :"migration_role" IN SCHEMA public
  GRANT SELECT ON TABLES TO :"readonly_role", :"backup_role";
-- Sequences: USAGE and SELECT let a role consume an identity column; UPDATE
-- would let it reset the sequence, which on `audit_logs.sequence_number` would
-- let a writer replay ordering keys it has already used.
ALTER DEFAULT PRIVILEGES FOR ROLE :"migration_role" IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO :"app_role", :"worker_role";
ALTER DEFAULT PRIVILEGES FOR ROLE :"migration_role" IN SCHEMA public
  GRANT SELECT ON SEQUENCES TO :"readonly_role", :"backup_role";
