-- Cluster provisioning for the local Compose stack, CI, and the integration
-- test harness. Executed by the db-bootstrap one-shot on EVERY stack start, as
-- $POSTGRES_USER (the database owner). Safe to re-run.
--
-- This file deliberately does NOT touch template1: DB-MIG-001 requires an empty
-- database, and migration 20260801_0002's own create path must stay exercised.
--
-- This file deliberately does NOT grant CREATE ON DATABASE to any role. The
-- migration role's privileges are unchanged by this provisioning step.
--
-- Production provisioning is deferred to ADR-002 (hosting/topology) and OPS-001.
-- On managed PostgreSQL these extensions are enabled by the provider; migration
-- 20260801_0002 reports the exact statement to run when they are not.
\set ON_ERROR_STOP 1

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA public;
