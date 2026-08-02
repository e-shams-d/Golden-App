-- Runtime role and ACL provisioning. Executed as $POSTGRES_USER by:
--   * infra/postgres/init/010-create-runtime-roles.sh (virgin data directory)
--   * the db-bootstrap Compose one-shot (every stack start)
--   * the integration fixture, against every disposable database, and the
--     native CI job's PostgreSQL service container (from M2 slice 1)
-- Safe to re-run. Requires psql variables:
--   database, app_role, app_password, migration_role, migration_password
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

GRANT CONNECT ON DATABASE :"database" TO :"migration_role", :"app_role";
GRANT USAGE, CREATE ON SCHEMA public TO :"migration_role";
GRANT USAGE ON SCHEMA public TO :"app_role";

ALTER DEFAULT PRIVILEGES FOR ROLE :"migration_role" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_role";
ALTER DEFAULT PRIVILEGES FOR ROLE :"migration_role" IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO :"app_role";
