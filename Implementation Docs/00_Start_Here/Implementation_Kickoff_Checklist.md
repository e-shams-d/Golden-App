# Implementation Kickoff Checklist

This checklist is the operational entry gate for the development team. Complete Milestone M0 before freezing irreversible implementation decisions.

## Gate 1 — Milestone M0 ownership

- [ ] Assign an owner and target date to every blocking ADR in `Open_ADR_Register.md`.
- [ ] Approve the ADR template and decision-log location.
- [ ] Freeze the canonical status catalogue from `06_Workflows_and_State_Machines.md`.
- [ ] Freeze the canonical permission catalogue from `12_Security_RBAC_Audit.md`.
- [ ] Freeze the API error-code catalogue from `05_API_Specification.md`.
- [ ] Freeze audit-action names and outbox-event names.
- [ ] Approve money serialization: canonical integer-string IRR plus entered value/unit provenance.
- [ ] Approve date/time serialization, business timezone, and Jalali/Gregorian display rules.
- [ ] Approve OpenAPI generation and generated-client strategy.
- [ ] Approve Alembic naming, migration review, and forward-fix policy.
- [ ] Approve branch protection, CODEOWNERS, PR review, release tagging, and artifact-promotion policy.

## Gate 2 — Repository bootstrap

Recommended repository shape:

```text
gold-trade-platform/
  apps/
    trader-pwa/
    admin-web/
  services/
    backend/
  packages/
    api-client/
    ui/
    config/
  infra/
    compose/
    nginx/
    scripts/
  docs/
    specifications/
    adrs/
    generated/
  tests/
    contract/
    e2e/
    security/
```

- [ ] Initialize Git repository and protected default branch.
- [ ] Add CODEOWNERS for domain, security, database, frontend, and operations.
- [ ] Configure secret scanning and dependency scanning.
- [ ] Configure formatting, linting, type checking, and unit-test commands.
- [ ] Configure separate builds for Trader PWA and Admin Web.
- [ ] Configure the FastAPI service skeleton and typed settings.
- [ ] Configure PostgreSQL, Redis, Celery, Nginx, and Docker Compose local stack.
- [ ] Add `/api/v1/health/live`, `/api/v1/health/ready`, and controlled dependency checks.
- [ ] Record release/build metadata in every service.

## Gate 3 — Foundation exit evidence

- [ ] A clean clone builds successfully.
- [ ] Docker Compose starts without publicly exposing PostgreSQL or Redis.
- [ ] Both frontend applications build independently.
- [ ] Backend and workers run as non-root where supported.
- [ ] Health and readiness checks pass.
- [ ] CI runs lint, type checks, tests, builds, secret scan, and dependency scan.
- [ ] No financial workflow shortcut is introduced before the integrity foundation.

## Gate 4 — Integrity foundation before financial workflows

- [ ] Alembic migrations run on PostgreSQL.
- [ ] Unit of Work owns commits and rollbacks.
- [ ] Transactional audit and outbox are implemented.
- [ ] Durable idempotency records handle replay and payload mismatch.
- [ ] Optimistic concurrency and required locks are tested.
- [ ] PostgreSQL roles separate runtime, migration, backup, and read-only operations.
- [ ] Failure-injection tests prove atomic rollback.

## Stop conditions

Stop implementation and escalate when a task depends on an unresolved financial, security, privacy, bank-mapping, retention, authentication, or production ADR. Independent foundation work may continue only when it does not freeze the unresolved choice.
