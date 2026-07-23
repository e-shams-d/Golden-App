# Repository and Runtime Baseline

Status: APPROVED FOR CANONICAL LAYOUT AND POSTGRESQL VERSION; REMAINING ITEMS PARTIAL
Last reviewed: 2026-07-20
Decision evidence: workspace owner approval via conversation; legal name/organizational role not supplied

## Approved canonical layout

~~~text
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
    adr/
    governance/
    generated/
  tests/
    contract/
    e2e/
    security/
~~~

The approved layout selects `services/backend` and `infra` as the canonical names because
they match the kickoff checklist and keep deployable applications separate from backend
services. `apps/backend` and `ops` are rejected alternatives, not additional roots or
runtime aliases. CI, CODEOWNERS, build contexts, documentation links, and generated tasks
must use only the approved paths. This resolves `DOC-CONFLICT-009`.

## Runtime baseline

| Area | Proposed baseline | Approval state |
|---|---|---|
| Backend language | Python 3.12+ | Consistent with docs |
| API | FastAPI and Pydantic v2 | Consistent with docs |
| ORM/migrations | Synchronous SQLAlchemy 2.x and Alembic | Consistent with docs |
| Database | PostgreSQL 16 | Approved for local, CI, staging, and production; resolves `DOC-CONFLICT-022` |
| Worker | Celery 5+ | Consistent with docs |
| Broker | Redis 7+, non-authoritative | Consistent with docs |
| Frontend | Next.js App Router, React, TypeScript | Consistent with docs |
| Frontend workspace | pnpm workspace plus Turborepo | Proposed from frontend guide |
| Styling/data/forms | Tailwind, TanStack Query/Table, React Hook Form, Zod | Consistent with docs |
| E2E | Playwright | Consistent with docs |
| Deployment | Docker Compose behind Nginx | Phase 1A baseline |
| Storage | Private storage interface; local adapter only for development/pilot | Production ADR open |

## Boundary rules

- Trader PWA and Admin Web are independently buildable/deployable applications.
- Shared packages contain contracts and UI/config primitives, not business authority.
- Backend remains a modular monolith with one database and explicit module boundaries.
- PostgreSQL is the durable business, audit, outbox, idempotency, and job source of truth.
- Redis/Celery state is never the only copy of a business fact.
- No organization_id or tenant_id is added before the Phase 4 tenancy design.
- Nginx is the only public ingress; PostgreSQL and Redis are private.
- Sensitive API/file routes are never cached by a service worker.

## Still open

- Exact Python dependency/lock tool.
- Exact Node/Next.js versions and supported LTS policy.
- Repository name and default branch.
- CI provider and artifact registry.
- Production operating system/image base and CPU architecture.
- Container image pinning/update cadence.
- Production host/storage topology.

The open items above do not reopen the approved repository paths or PostgreSQL major
version. Exact patch versions and image digests remain lockfile/deployment responsibilities.

## Approval record

- Approval date: 2026-07-20
- Approval evidence: workspace owner approval via conversation; legal name/organizational role not supplied
- Approved decisions: `services/backend` plus `infra` canonical layout; PostgreSQL 16 in every environment
- Unapproved by this record: the remaining version/tool/provider/production-topology items listed above

## Sources

- Implementation Docs/00_Start_Here/Implementation_Kickoff_Checklist.md:21
- Implementation Docs/00_Start_Here/15_Agent_Implementation_Plan.md:421
- Implementation Docs/02_Architecture_and_Contracts/03_System_Architecture.md:173
- Implementation Docs/04_Frontend_and_Experience/11_Frontend_Implementation_Guide.md:307
- Implementation Docs/05_Backend_and_Security/10_Backend_Implementation_Guide.md:198
