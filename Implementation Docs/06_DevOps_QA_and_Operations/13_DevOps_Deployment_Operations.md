# Gold Trade Settlement Platform
## 13 — DevOps, Deployment, and Operations

**Document type:** DevOps, deployment, release, backup, recovery, monitoring, and production-operations specification  
**Version:** 1.1  
**Language:** English  
**Status:** Authoritative operational implementation baseline  
**Primary audience:** Product owner, technical lead, DevOps engineer, backend engineer, frontend engineer, security reviewer, QA engineer, operations owner, and coding agents  
**Phase coverage:** Phase 1A mandatory production controls with forward-compatible Phase 1B–4 expansion  
**Primary deployment baseline:** Hardened Linux host, Docker Compose, Nginx, two Next.js applications, FastAPI, PostgreSQL, Redis, Celery workers, controlled scheduler, and private file storage  

---

## Document Control

### Authority and precedence

This document defines how the approved platform architecture is built, released, deployed, monitored, backed up, restored, and operated.

It must be implemented consistently with the following reviewed version 1.1 documents:

- `00_Master_Implementation_Blueprint.md`
- `01_Product_Requirements_PRD.md`
- `02_Domain_Model_and_Business_Rules.md`
- `03_System_Architecture.md`
- `04_Database_Schema.md`
- `05_API_Specification.md`
- `06_Workflows_and_State_Machines.md`
- `07_UI_UX_Specification.md`
- `08_Bank_File_and_Result_Processing.md`
- `09_OCR_AI_Module_Specification.md`
- `10_Backend_Implementation_Guide.md`
- `11_Frontend_Implementation_Guide.md`
- `12_Security_RBAC_Audit.md`

If an operational shortcut conflicts with a financial, security, audit, versioning, or ownership rule in those documents, the shortcut is invalid.

### Change log

| Version | Change |
|---|---|
| 1.0 | Initial deployment and operations draft. |
| 1.1 | Aligned operations with the single-tenant modular monolith, two separately deployed frontends, exact immutable batch-version approval, Celery selection, canonical health endpoints, explicit storage bind mounts, transactional outbox, idempotency/concurrency, Phase 1A manual crop, service-specific secrets, hardened containers, immutable release artifacts, off-server encrypted backups, restore validation, governed retention/legal hold, incident controls, and production release gates. |

### Guiding principle

> Preserve the required business authority, evidence, and accountability while replacing fragile manual operational methods with controlled, reproducible, recoverable, and auditable platform operations.

---

# 1. Purpose

This document defines the production-operating model for the Gold Trade Settlement Platform.

It covers:

- environment topology;
- Docker Compose services and network boundaries;
- Nginx and TLS;
- secrets and configuration;
- private file storage;
- PostgreSQL and Redis operation;
- Celery workers and scheduler;
- health, metrics, logs, and alerting;
- CI/CD and release promotion;
- migration and rollback safety;
- backup, restore, and disaster recovery;
- retention and legal-hold coordination;
- incident response and break-glass controls;
- capacity planning;
- operational runbooks;
- production acceptance criteria.

The system handles high-value outgoing payments, incoming-payment verification, bank exports, bank result bundles, beneficiary banking information, gold-sale settlement, evidence files, trader-visible publications, and append-only audit history. Operational correctness is therefore a financial control, not merely an infrastructure concern.

Phase 1A must remain fully usable when AI/OCR, external notification providers, banking APIs, or other external automation are disabled or unavailable.

---

# 2. Approved Operational Decisions

The following decisions are fixed for Phase 1A unless superseded by an approved ADR.

| Area | Approved decision |
|---|---|
| Architecture | Single-tenant modular monolith. |
| Frontends | Two separately built and deployed Next.js applications: Trader PWA and Admin Web. |
| API | FastAPI application. |
| Database | PostgreSQL is the authoritative business, audit, outbox, idempotency, and job-state store. |
| Worker framework | Celery. RQ is not an open implementation option. |
| Broker | Redis; Redis is non-authoritative. |
| Reverse proxy | Nginx is the only publicly exposed application service. |
| Pilot deployment | One hardened Linux server using Docker Compose, plus a separate encrypted backup destination. |
| Staging | Separate staging environment required before production. |
| Storage | Private storage abstraction; explicit backed-up bind mount or approved S3-compatible service. |
| Local pilot storage | Explicit host bind mount; not an opaque untracked Docker named volume. |
| Manual crop | Required Phase 1A capability. |
| AI/OCR | Disabled by default and never required for core workflows. |
| Manager approval | Required for every outgoing Phase 1A payment batch, tied to exact immutable batch version/hash. |
| Release artifacts | Immutable images built once and promoted by digest. |
| Backup | Database and file storage backed up together with a consistency manifest and off-server encrypted copy. |
| Kubernetes | Not required for Phase 1A. |
| Multi-company/SaaS | Phase 4, not partially implemented in Phase 1A. |

---

# 3. Operational Principles

## 3.1 Manual-first availability

Core operations must remain available without AI/OCR or external integrations:

- trader request creation and submission;
- accountant review;
- batch creation and immutable version finalization;
- manager approval;
- bank export generation;
- exact export sent marking;
- bank-result upload;
- PDF/image preview and manual rectangular crop;
- manual evidence confirmation;
- payment-result confirmation;
- trader publication;
- incoming-payment verification;
- gold dispatch or settlement;
- audit and reporting.

An AI-provider outage is a degraded optional-service condition, not a platform outage.

## 3.2 Financial authority remains human

Infrastructure, schedulers, workers, parsers, AI providers, and maintenance scripts must not:

- approve a batch version;
- confirm an outgoing payment as paid or failed;
- create an active primary confirmed evidence link without an authorized human command;
- publish a financial result to a trader;
- mark a bank export sent without an authorized command;
- confirm an incoming payment;
- dispatch gold;
- shorten retention or remove legal hold.

Workers may generate artifacts, previews, candidates, notifications, and reports. They do not possess financial decision authority.

## 3.3 PostgreSQL is authoritative

Permanent truth must not exist only in:

- Redis;
- Celery result backend;
- container filesystem layers;
- Nginx cache;
- frontend browser storage;
- local operator spreadsheets;
- untracked cron output.

Important jobs, outbox events, idempotency records, approvals, export integrity data, file metadata, and audit events are persisted in PostgreSQL.

## 3.4 Recoverability before production

Production is not approved until:

- automatic database backup exists;
- automatic file-storage backup exists;
- backups leave the production failure domain;
- backup monitoring exists;
- a complete restore has succeeded in an isolated environment;
- restored database/file consistency has been checked;
- restored RBAC, trader isolation, audit, approvals, and files have been verified;
- RPO/RTO and operational ownership are approved.

## 3.5 Immutable evidence and releases

Operational processes must preserve:

- original uploaded files;
- derived crop provenance;
- exported bank files and checksums;
- previous publication versions;
- previous approval and correction records;
- previous application release artifacts;
- migration history;
- audit and incident evidence.

Do not “fix” history by overwriting files, editing audit rows, or rebuilding a production image under the same tag.

## 3.6 Environment separation

Local, staging, and production environments must not share:

- databases;
- storage roots/buckets;
- Redis databases used as brokers;
- authentication cookies/domains;
- secrets;
- AI provider credentials;
- signing keys;
- backup destinations;
- production data unless an approved sanitized copy is used.

## 3.7 Simplicity with control

Docker Compose is preferred for the production pilot because it is understandable and maintainable by a small operations team. Simplicity does not permit:

- public database ports;
- mutable images;
- missing backups;
- shared secrets across all services;
- privileged containers;
- unknown storage volumes;
- unreviewed migrations;
- manual deployment without recorded release metadata.

---

# 4. Environments

## 4.1 Required environments

At minimum:

```text
local
staging
production
```

Optional:

```text
qa
demo
performance-test
disaster-recovery-test
```

## 4.2 Local

Local development may use Docker Compose and synthetic/demo data.

Requirements:

- no production secrets;
- no real production bank documents unless explicitly approved and protected;
- mock AI adapter by default;
- AI disabled unless testing a specific adapter;
- deterministic seed data;
- developer accounts clearly non-production;
- local storage path separate from repository source;
- database reset scripts must refuse production-like environment values.

## 4.3 Staging

Staging is required and should reproduce production behavior:

- same service inventory;
- same image artifacts/digests intended for production;
- same Nginx routing and security-header behavior;
- same authentication transport and CSRF behavior;
- same storage adapter class where practical;
- same Celery queue names and scheduler behavior;
- same migration chain;
- representative bank profiles and fixtures;
- synthetic or authorized sanitized files;
- production-like monitoring and alert checks;
- no shared production database or file storage.

Staging must support full workflow testing, including batch version approval, export integrity, manual crop, evidence replacement, publication supersession, and restore verification.

## 4.4 Production

Production requires:

- HTTPS;
- hardened host;
- restricted SSH;
- strong service-specific secrets;
- private database, Redis, and storage;
- automatic backups and off-server copy;
- structured logs with redaction;
- health/readiness checks;
- metrics and alerting;
- release and rollback records;
- controlled migration execution;
- incident ownership;
- approved RPO/RTO;
- no demo accounts or demo financial records;
- AI/external providers disabled unless separately approved.

---

# 5. Phase 1A Deployment Topology

## 5.1 Default topology

The default production pilot is one hardened Linux server running Docker Compose, with a physically or logically separate encrypted backup destination.

```text
Internet / approved client networks
              |
           HTTPS
              |
           Nginx
     _________|_________
    |         |         |
Trader     Admin      Backend
Frontend   Frontend     API
                        |
               -------------------
               |        |        |
           PostgreSQL  Redis   Private Storage
               |        |
               |      Celery Workers
               |        |
               |     Scheduler
               |
          Backup/Manifest
               |
    Separate encrypted destination
```

## 5.2 Availability limitation

A single-server pilot is not highly available. It is acceptable only when the business explicitly accepts:

- host failure causing temporary outage;
- recovery from backup or server replacement;
- planned maintenance windows;
- agreed RTO/RPO;
- no claim of zero downtime.

Do not describe the single-host pilot as highly available.

## 5.3 Scale-out trigger

Consider separating services when measured capacity or availability requires it, for example:

- API CPU/memory saturation;
- file rendering delaying normal API traffic;
- worker backlog violating operational targets;
- PostgreSQL resource contention;
- storage capacity or I/O constraints;
- RTO/RPO requiring database replication or faster recovery;
- business requirement for reduced single-host failure risk.

Kubernetes is considered only when operational capability and justified scale exist. It is not a default maturity milestone.

---

# 6. Service Inventory

| Service | Purpose | Public exposure | Authoritative data |
|---|---|---:|---|
| `nginx` | TLS, routing, request limits, security headers | Yes, ports 80/443 | No |
| `frontend_trader` | Trader PWA | Via Nginx only | No |
| `frontend_admin` | Admin Web App | Via Nginx only | No |
| `backend_api` | Auth, query, command, file authorization | Via Nginx only | PostgreSQL/storage through controlled APIs |
| `worker_default` | Celery worker consuming Phase 1A queues | No | Writes through backend persistence rules |
| `scheduler` | Celery Beat or controlled scheduler | No | Schedule definitions; no financial authority |
| `postgres` | Business, audit, outbox, idempotency, jobs | No | Yes |
| `redis` | Celery broker, short-lived rate/session/cache support | No | No |
| `backup` | Backup orchestration and manifest creation | No | Backup artifacts only |
| `monitoring_agent` | Host/container metrics/log forwarding | No or restricted | No |
| `malware_scanner` | Optional approved file scanning | No | Scan outcome persisted in PostgreSQL |

A dedicated AI worker is not required in Phase 1A. If later enabled, it uses the `ai` queue and separate provider secrets.

---

# 7. Docker Compose Baseline

## 7.1 Compose file separation

Recommended repository layout:

```text
ops/
  compose/
    compose.base.yml
    compose.local.yml
    compose.staging.yml
    compose.production.yml
  docker/
    nginx/
    backend/
    frontend-trader/
    frontend-admin/
  env/
    examples/
  scripts/
  runbooks/
  monitoring/
  backup/
```

Production deployment should combine a reviewed base file with a production override or use one explicit production file. Avoid undocumented command-line overrides.

## 7.2 Illustrative production Compose structure

The following is an architectural example, not copy-paste production credentials:

```yaml
services:
  nginx:
    image: nginx:1.27-alpine@sha256:<approved-digest>
    restart: unless-stopped
    depends_on:
      frontend_trader:
        condition: service_healthy
      frontend_admin:
        condition: service_healthy
      backend_api:
        condition: service_healthy
    ports:
      - "80:80"
      - "443:443"
    read_only: true
    tmpfs:
      - /var/cache/nginx
      - /var/run
    volumes:
      - ./ops/docker/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ops/docker/nginx/conf.d:/etc/nginx/conf.d:ro
      - /srv/gold-platform/tls:/etc/nginx/tls:ro
    networks:
      - public_net
      - app_net
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE

  frontend_trader:
    image: registry.example/gold/frontend-trader@sha256:<approved-digest>
    restart: unless-stopped
    env_file:
      - /etc/gold-platform/env/frontend-trader.env
    read_only: true
    tmpfs:
      - /tmp
    expose:
      - "3000"
    networks:
      - app_net
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:3000/health"]
      interval: 30s
      timeout: 5s
      retries: 3

  frontend_admin:
    image: registry.example/gold/frontend-admin@sha256:<approved-digest>
    restart: unless-stopped
    env_file:
      - /etc/gold-platform/env/frontend-admin.env
    read_only: true
    tmpfs:
      - /tmp
    expose:
      - "3000"
    networks:
      - app_net
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:3000/health"]
      interval: 30s
      timeout: 5s
      retries: 3

  backend_api:
    image: registry.example/gold/backend@sha256:<approved-digest>
    restart: unless-stopped
    env_file:
      - /etc/gold-platform/env/backend.env
    read_only: true
    tmpfs:
      - /tmp
    expose:
      - "8000"
    volumes:
      - /srv/gold-platform/storage:/app/storage
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - app_net
      - data_net
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:8000/api/v1/health/ready"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s

  worker_default:
    image: registry.example/gold/backend@sha256:<approved-digest>
    restart: unless-stopped
    command:
      - celery
      - -A
      - app.workers.celery_app
      - worker
      - --queues=files,exports,notifications,reports,maintenance
      - --loglevel=INFO
    env_file:
      - /etc/gold-platform/env/worker.env
    read_only: true
    tmpfs:
      - /tmp
    volumes:
      - /srv/gold-platform/storage:/app/storage
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - data_net
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL

  scheduler:
    image: registry.example/gold/backend@sha256:<approved-digest>
    restart: unless-stopped
    command:
      - celery
      - -A
      - app.workers.celery_app
      - beat
      - --loglevel=INFO
    env_file:
      - /etc/gold-platform/env/scheduler.env
    read_only: true
    tmpfs:
      - /tmp
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - data_net
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL

  postgres:
    image: postgres:16.4-alpine@sha256:<approved-digest>
    restart: unless-stopped
    env_file:
      - /etc/gold-platform/env/postgres.env
    volumes:
      - /srv/gold-platform/postgres:/var/lib/postgresql/data
    expose:
      - "5432"
    networks:
      - data_net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 10s
      timeout: 5s
      retries: 10
    security_opt:
      - no-new-privileges:true

  redis:
    image: redis:7.4-alpine@sha256:<approved-digest>
    restart: unless-stopped
    command: ["redis-server", "/usr/local/etc/redis/redis.conf"]
    volumes:
      - ./ops/docker/redis/redis.conf:/usr/local/etc/redis/redis.conf:ro
    expose:
      - "6379"
    networks:
      - data_net
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 10
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL

networks:
  public_net:
  app_net:
    internal: true
  data_net:
    internal: true
```

## 7.3 Important Compose rules

- Pin images by immutable digest for production.
- Do not use `latest`.
- Do not mount `/var/run/docker.sock` into application containers.
- Do not run API, worker, or frontend as root.
- Do not publish PostgreSQL or Redis ports to the host.
- Do not store secrets directly in Compose YAML committed to source control.
- Do not use `docker compose down -v` in production automation.
- Do not depend only on `depends_on`; services must tolerate dependency startup delays and expose health checks.
- Configure graceful shutdown for API and Celery workers.
- Set resource limits/reservations after load testing and host sizing.
- Configure Docker log rotation.

## 7.4 Explicit persistent paths

Recommended Phase 1A host paths:

```text
/srv/gold-platform/postgres
/srv/gold-platform/storage
/srv/gold-platform/tls
/srv/gold-platform/releases
/srv/gold-platform/backup-staging
/var/log/gold-platform or approved log destination
/etc/gold-platform/env
```

The exact paths may differ, but every persistent path must be documented in the backup manifest and restore runbook.

An untracked Docker named volume is not an acceptable sole location for business evidence.

---

# 8. Network and Host Security

## 8.1 Public exposure

Only Nginx exposes host ports for application traffic.

Allowed public ports:

```text
80/tcp  HTTP redirect or certificate challenge
443/tcp HTTPS
```

SSH should be restricted by source IP or VPN where practical.

Do not expose:

```text
5432 PostgreSQL
6379 Redis
8000 Backend API directly
3000 Frontend services directly
Celery/monitoring admin ports
Object-storage administration ports
```

## 8.2 Host hardening

Minimum controls:

- supported Linux distribution;
- timely security updates;
- SSH key authentication;
- password SSH login disabled;
- root SSH login disabled;
- minimal sudo users;
- host firewall;
- time synchronization;
- disk monitoring;
- automatic or scheduled security updates with maintenance policy;
- administrative access logs;
- no daily use of shared root credentials;
- separate operational accounts where practical;
- backup credentials not readable by ordinary application users.

## 8.3 Time synchronization

The platform stores system timestamps in UTC. Host, containers, PostgreSQL, and logging must use synchronized time.

Monitor clock drift because approval, audit, sent time, result time, backup age, and session expiry depend on accurate time.

## 8.4 Container hardening

Production containers should use:

- non-root UID/GID;
- `no-new-privileges`;
- dropped Linux capabilities;
- read-only root filesystem where feasible;
- temporary writable `tmpfs` only where required;
- minimal base images;
- no package managers or shells in final images where operationally feasible;
- dependency and image scans;
- explicit writable storage mounts;
- controlled process signals and shutdown timeouts.

API and worker must use a compatible non-root UID/GID for shared local storage without granting world-writable permissions.

---

# 9. Nginx, Routing, TLS, and Headers

## 9.1 Routing model

Preferred subdomain model:

```text
app.example.com    -> Trader PWA
admin.example.com  -> Admin Web
api.example.com    -> Backend API
```

A single-domain path model is acceptable if authentication cookies, CSRF, CSP, and caching are carefully tested. The two frontend applications remain separate deployments regardless of domain strategy.

## 9.2 Nginx responsibilities

- TLS termination;
- HTTP-to-HTTPS redirect;
- routing to both frontends and API;
- request body-size limits;
- upstream timeouts;
- rate limiting for selected public endpoints;
- request ID forwarding/generation;
- security headers;
- safe access logging;
- protection from direct storage-path exposure;
- static asset caching only for public non-sensitive assets.

## 9.3 TLS

- Use trusted certificates.
- Automate renewal where possible.
- Alert before expiry.
- Use modern TLS configuration.
- Enable HSTS only after HTTPS behavior is verified and rollback implications are understood.
- Private keys are secrets and included in controlled backup/rotation plans if self-managed.

## 9.4 Security headers

Baseline, adjusted and tested per frontend needs:

```text
Strict-Transport-Security
Content-Security-Policy
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy
frame-ancestors in CSP
```

Prefer CSP `frame-ancestors` over relying only on `X-Frame-Options`.

Do not permit unsafe inline script broadly merely to resolve a deployment issue without security review.

## 9.5 Sensitive cache rules

Responses containing financial or personal data should use appropriate private/no-store cache headers.

Nginx/CDN/browser caching must not cache:

- authenticated API responses;
- bank result files;
- bank exports;
- evidence images;
- trader publications with sensitive data unless explicitly designed;
- audit pages;
- signed download responses.

## 9.6 Upload behavior

Upload limits are configured consistently at Nginx and backend. Final values are production decisions based on approved file requirements and capacity tests.

The UI must receive a clear controlled error when a request exceeds the limit.

Long upload timeouts should not be unbounded.

---

# 10. Configuration and Secret Management

## 10.1 Configuration classes

Separate:

1. public frontend build/runtime configuration;
2. backend secrets;
3. worker-only/provider secrets;
4. scheduler configuration;
5. PostgreSQL initialization credentials;
6. backup credentials;
7. monitoring credentials;
8. business configuration stored as versioned database records.

## 10.2 Service-specific environment files

Example:

```text
/etc/gold-platform/env/frontend-trader.env
/etc/gold-platform/env/frontend-admin.env
/etc/gold-platform/env/backend.env
/etc/gold-platform/env/worker.env
/etc/gold-platform/env/scheduler.env
/etc/gold-platform/env/postgres.env
/etc/gold-platform/env/backup.env
```

Do not give frontend containers backend database, storage, session-signing, or provider secrets.

## 10.3 Public frontend variables

Any variable exposed to browser JavaScript must be treated as public.

Never expose:

- session secrets;
- database URLs;
- Redis URLs;
- storage credentials;
- AI keys;
- backup paths/credentials;
- internal admin endpoints;
- signed URL secrets.

## 10.4 Example configuration categories

```text
APP_ENV
RELEASE_VERSION
DATABASE_URL
REDIS_URL
STORAGE_BACKEND
LOCAL_STORAGE_ROOT
SESSION_SECRET or approved session configuration
CSRF_SECRET/configuration
ALLOWED_ORIGINS
TRUSTED_HOSTS
FILE_SIZE_LIMITS
LOG_LEVEL
AI_ENABLED=false
AI_EXTERNAL_PROVIDER_ENABLED=false
OCR_ENABLED=false
AUTO_SEGMENTATION_ENABLED=false
MANUAL_CROP_ENABLED=true
```

The exact authentication variables depend on ADR-001. Do not prematurely lock domain code to JWT-specific configuration.

## 10.5 Secret storage

Preferred order:

1. approved secret manager;
2. protected host files mounted/read by only the required service;
3. carefully controlled environment injection.

Never:

- commit `.env` production files;
- place secrets in frontend images;
- print secrets in CI logs;
- pass secrets as ordinary command-line arguments where visible in process listings;
- share one broad secret file with every service.

## 10.6 Rotation

Maintain runbooks for rotating:

- session/signing secrets;
- database runtime credential;
- database migration credential;
- backup credential;
- object-storage credential;
- AI provider key;
- monitoring/error-tracker key;
- TLS key/certificate;
- emergency/break-glass credentials.

Rotation must state whether sessions are invalidated and how multiple active key versions are handled during transition.

## 10.7 Default credentials

Production installation must not retain:

- default passwords;
- demo users;
- seed API keys;
- test storage credentials;
- sample bank credentials;
- broad super-admin account.

Initial business administrator creation is a controlled command or migration task, with temporary credential delivery outside logs and required password change if applicable.

---

# 11. PostgreSQL Operations

## 11.1 Role separation

Use distinct database roles where practical:

| Role | Capabilities |
|---|---|
| Application runtime | Read/write required business tables; no schema ownership; no audit/approval UPDATE/DELETE. |
| Worker runtime | Required job/file/report access only; no extra financial authority. |
| Migration role | Schema migration permissions; not used by normal API. |
| Backup role | Read/backup permissions required for backup method. |
| Operations/read-only | Controlled diagnostic access. |

The application runtime role must not own the database schema.

## 11.2 Append-only protections

Runtime roles must not update/delete:

- audit events;
- security events where append-only;
- batch approvals;
- finalized immutable batch-version rows;
- outbox history beyond controlled dispatcher status fields;
- immutable publication snapshots;
- immutable file records after finalization except lifecycle fields through controlled commands.

Use database permissions, constraints, triggers where justified, and tests.

## 11.3 Connection pooling

Total possible connections from API, workers, scheduler, migrations, backup, and operations must remain below PostgreSQL limits with safety margin.

Document:

```text
API process count × pool size
Worker process count × pool size
Scheduler connections
Migration/maintenance reserve
Monitoring reserve
```

Do not increase pool size to hide slow queries.

## 11.4 Migrations

All schema changes use Alembic.

Production rules:

- migration committed with release;
- generated migration reviewed manually;
- clean-database migration test passes;
- upgrade from current production schema passes;
- representative data migration tests pass;
- staging migration succeeds using production artifact;
- lock/downtime risk documented;
- backup/prechecks completed;
- release records schema version;
- no manual production DDL outside controlled incident process.

## 11.5 Expand-and-contract

Risky changes should use phases:

```text
expand schema
→ deploy compatible code
→ backfill in bounded/resumable jobs
→ switch reads/writes
→ verify
→ remove obsolete structure in later release
```

Avoid a large table rewrite and application behavior change in one unbounded migration.

## 11.6 Data migration jobs

Large backfills must be:

- resumable;
- idempotent;
- bounded by batch size;
- observable;
- safe under restart;
- separated from request transactions;
- documented in release notes;
- auditable when they alter sensitive records.

## 11.7 Maintenance

Operational tasks may include:

- `VACUUM`/autovacuum monitoring;
- `ANALYZE` health;
- index bloat review;
- slow-query review;
- connection monitoring;
- disk growth forecasting;
- PostgreSQL minor-version updates after staging verification.

Do not run ad-hoc destructive SQL directly against production without approved change/incident control.

---

# 12. Redis and Celery Operations

## 12.1 Redis role

Redis is used for:

- Celery broker;
- bounded rate-limiting data;
- short-lived session/cache support if approved;
- temporary coordination where loss is acceptable.

Redis is not the source of truth for:

- financial status;
- approvals;
- file metadata;
- outbox delivery state;
- idempotency result;
- important job status;
- audit history.

A Redis loss may cause queue recovery work but must not erase committed business truth.

## 12.2 Approved queue names

Phase 1A configuration includes logical queues:

```text
files
exports
notifications
reports
maintenance
```

Reserved and disabled by default until later approval:

```text
ai
```

One worker process may consume multiple queues in a small pilot. Queue names remain separate for scaling and incident isolation.

## 12.3 Scheduler

Celery Beat or an equivalent controlled scheduler runs as a separate process/container.

Scheduled work may trigger:

- outbox dispatch;
- stale-job recovery;
- file reconciliation;
- backup verification checks;
- notification delivery;
- report generation;
- retention dry-run or execution only after approved policy and explicit job authorization;
- AI jobs only when enabled and approved.

The scheduler must not approve or confirm financial actions.

## 12.4 Task requirements

Every important task:

- receives stable entity/job IDs, not ORM objects;
- opens its own database session/Unit of Work;
- rechecks current state;
- is idempotent under at-least-once execution;
- records attempt count/status in PostgreSQL;
- distinguishes transient from permanent failures;
- has bounded retries/backoff;
- propagates correlation ID;
- records worker identity/release version;
- cannot inherit human financial authority;
- does not rely on Celery result backend as authoritative history.

## 12.5 Worker shutdown

During deployment:

- stop accepting new tasks when signaled;
- allow bounded completion of safe in-progress tasks;
- requeue or recover interrupted jobs;
- avoid duplicate artifact generation through idempotency;
- do not terminate during a non-idempotent external operation without recovery design.

## 12.6 Queue monitoring

Monitor:

- queue depth by queue;
- oldest queued task age;
- task throughput;
- success/failure/retry rate;
- worker heartbeat;
- stale running jobs;
- task duration percentiles;
- dead-letter/manual-recovery counts where implemented.

Queue depth alone is insufficient; “no progress” and oldest-task age are important.

---

# 13. File Storage Operations

## 13.1 Storage baseline

Storage must be private and accessed through the application authorization layer.

Phase 1A options:

- explicit host bind mount;
- approved private S3-compatible service.

If local storage is used:

```text
/srv/gold-platform/storage:/app/storage
```

or an equivalent explicit documented path is required.

## 13.2 Storage directory/object structure

Do not use original filenames as storage paths. Use server-generated keys.

A possible logical structure:

```text
original/
derived/
exports/
publications/
quarantine/
pending/
temporary/
```

Directory names do not replace database lifecycle and authorization metadata.

## 13.3 File lifecycle

Operational states:

```text
pending
quarantined
available
processing_failed
archived
retention_pending
deleted
```

A file is not usable as evidence, crop source, export, or publication until its state and scan/validation policy allow it.

## 13.4 Upload flow

```text
stream to pending private location
→ enforce size/type/signature limits
→ calculate checksum
→ malware/validation decision
→ finalize metadata in short transaction
→ mark available or quarantined
→ enqueue preview/normalization through outbox
```

Do not keep a database transaction open while streaming a large upload.

## 13.5 Manual crop operations

Manual rectangular crop is Phase 1A.

Operational requirements:

- source file/page authorized and available;
- render task persisted;
- normalized coordinates stored;
- source dimensions and rotation stored;
- renderer name/version stored;
- derived file checksum stored;
- original file preserved;
- failed render retryable;
- derived file cannot become active evidence automatically;
- privacy review required before trader publication.

## 13.6 File reconciliation

A scheduled maintenance job identifies:

- storage object without database record;
- database record without storage object;
- stale pending upload;
- orphan derivative;
- checksum mismatch;
- quarantined file awaiting review;
- processing job stuck beyond threshold;
- duplicate object created after retry.

Reconciliation reports discrepancies. It does not delete financial evidence automatically.

## 13.7 Permissions

Host permissions must ensure:

- API and worker can read/write required storage through shared non-root UID/GID;
- frontend and Nginx cannot browse storage directly;
- backup process can read storage;
- ordinary host users cannot read sensitive files;
- no world-writable storage;
- quarantine and backup paths are protected.

## 13.8 Storage capacity

Monitor:

- total/free bytes;
- growth per day/week/month;
- original vs derived storage;
- pending/quarantine usage;
- backup destination usage;
- largest bundles/files;
- forecast date for warning/critical capacity.

Disk-full protection must alert before writes fail.

---

# 14. Canonical Health Contract

## 14.1 Backend endpoints

The approved endpoints are:

```http
GET /api/v1/health/live
GET /api/v1/health/ready
GET /api/v1/health/dependencies
GET /api/v1/health/workers
```

Older paths such as `/health` and `/health/deep` are not the canonical contract.

## 14.2 Liveness

`/api/v1/health/live`:

- minimal;
- public or infrastructure-accessible;
- verifies the process can respond;
- does not perform expensive dependency checks;
- exposes no credentials or internal topology.

## 14.3 Readiness

`/api/v1/health/ready` verifies with strict timeouts:

- required configuration loaded;
- PostgreSQL usable;
- storage available for required operation;
- Redis/broker condition according to required readiness policy;
- application is not in a state that must reject normal traffic;
- migrations/schema compatibility valid.

Readiness should fail during unsafe migration/restore states.

## 14.4 Dependency diagnostics

`/api/v1/health/dependencies` is restricted to authorized operational access or internal network.

It may report safe status for:

- PostgreSQL;
- Redis;
- storage;
- outbox dispatcher;
- queue broker;
- migration/schema version;
- optional providers when enabled.

It must not expose URLs, credentials, bucket keys, filenames, trader data, or full exceptions.

## 14.5 Worker health

`/api/v1/health/workers` is restricted and reports persisted/metric-based worker state:

- worker identity;
- queue names;
- last heartbeat;
- release version;
- active job count;
- oldest queued age;
- stale-worker warnings.

A running container alone does not prove a healthy worker.

## 14.6 Frontend health

Each frontend exposes a minimal health route used by Compose/Nginx monitoring. It must not require authentication or render sensitive data.

---

# 15. Logging and Correlation

## 15.1 Structured logs

Production services emit structured logs.

Recommended fields:

```text
timestamp
level
environment
service
module
release_version
request_id
correlation_id
actor_id (internal identifier)
action
entity_type
entity_id
job_id
error_code
duration_ms
message
```

## 15.2 Redaction

Do not log:

- passwords;
- session tokens/cookies;
- CSRF secrets;
- signed URLs;
- database/storage credentials;
- full IBAN or national ID;
- raw bank rows;
- full beneficiary/trader notes;
- file contents/base64;
- raw OCR/AI payloads;
- backup encryption keys;
- provider keys.

Use masked identifiers only where operationally necessary.

## 15.3 Correlation propagation

The correlation ID flows through:

```text
Nginx request
→ frontend/backend request
→ Unit of Work audit metadata
→ outbox event
→ Celery task/job record
→ worker logs
→ notification/report/file job
```

## 15.4 Log retention and access

Operational log retention is distinct from business audit retention.

Define:

- retention duration;
- storage location;
- access roles;
- rotation/compression;
- incident preservation/hold process;
- deletion process;
- redaction verification.

Technical support does not automatically receive unrestricted business-audit access.

## 15.5 Docker log rotation

Configure limits to prevent host disk exhaustion. Example policy should set maximum size/file count or forward logs to an approved collector.

Never rely on unlimited default JSON log files.

---

# 16. Metrics, Dashboards, and Alerting

## 16.1 Infrastructure metrics

Monitor:

- host CPU/load;
- memory/swap;
- disk space and I/O;
- filesystem inode usage;
- network errors/latency;
- container restarts;
- PostgreSQL availability/connections/locks/replication if used;
- Redis availability/memory;
- TLS expiry;
- backup age/status.

## 16.2 Application metrics

Monitor:

- request count/latency/error rate;
- authentication failures and rate limits;
- permission denials;
- invalid-state/version conflicts;
- idempotency conflicts/replays;
- outbox pending/oldest age/failures;
- worker queue depth/oldest age;
- file uploads, validation failures, quarantine count;
- export generation/integrity mismatches;
- manual crop failures;
- manual review backlog;
- publication corrections/disputes;
- backup and restore-test status;
- AI cost/latency only when enabled.

Do not put trader names, IBANs, filenames, or transaction IDs into metric labels.

## 16.3 Business-operational dashboards

Operational dashboards may show aggregated counts and durations, such as:

- pending accountant review;
- batch versions awaiting approval;
- approved versions awaiting final export;
- exports downloaded but not marked sent;
- batches waiting for results;
- unresolved result segments;
- failed/retry attempts;
- incoming-payment reconciliation items;
- gold orders blocked from dispatch;
- trader disputes.

These dashboards complement, not replace, authoritative work queues.

## 16.4 Alert ownership

Every alert has:

- severity;
- owner/recipient;
- response window;
- runbook link;
- escalation route;
- acknowledgement method;
- suppression/maintenance policy.

An alert sent to nobody accountable is not an implemented control.

## 16.5 Critical alert examples

- API readiness failure;
- PostgreSQL unavailable;
- storage unavailable;
- disk critical;
- backup failure or stale backup;
- restore-test failure;
- worker heartbeat stale;
- outbox not progressing;
- export integrity mismatch;
- audit insert failure;
- repeated cross-trader access attempts;
- role/permission or break-glass change;
- TLS expiry approaching;
- unusual login/authorization failures;
- malware/quarantine spike;
- RPO threshold exceeded.

Thresholds must be tuned from measured load. Placeholder thresholds are not production policy.

---

# 17. Backup Architecture

## 17.1 Backup scope

A complete recovery set includes:

- PostgreSQL data;
- original uploaded files;
- derived files required for evidence/publications;
- generated bank exports;
- audit and security events;
- application configuration excluding plaintext secrets;
- approved bank profile/mapping/template records through database backup;
- release/version metadata;
- migration version;
- TLS material if self-managed and required;
- backup manifest and checksums.

Redis backup is not required for business recovery when it is used only as a non-authoritative broker/cache. Queue recovery behavior must still be tested.

## 17.2 Off-server rule

A copy stored only on the same production disk is not a disaster-recovery backup.

Production requires an encrypted, access-controlled backup copy on a separate server/service/device/failure domain.

## 17.3 Consistency manifest

Each backup set records:

```text
backup_set_id
start/end time UTC
database backup identifier/checksum
storage snapshot/copy identifier/checksum
application release image digests
schema/Alembic revision
file/object count and total bytes where practical
verification result
encryption method/key reference
source environment
backup software/version
```

## 17.4 Consistency model

For the Phase 1A pilot, choose and document one model:

- low-activity/maintenance window with coordinated database and storage backup;
- database snapshot plus storage snapshot with defined time boundary;
- WAL/PITR plus versioned/object storage strategy;
- another reviewed method that provides an explainable recovery point.

Do not claim transaction-perfect database/file consistency without implementing it.

## 17.5 Backup schedule

The exact schedule follows approved RPO and volume.

A provisional pilot baseline may include:

- daily full logical database backup;
- more frequent database incremental/WAL or snapshot when RPO requires it;
- daily or more frequent file-storage backup;
- encrypted off-server copy;
- automated daily verification;
- scheduled restore drills.

These are planning defaults, not a substitute for approved ADR-004.

## 17.6 Backup encryption and access

- encrypt backup at rest and in transit;
- restrict restore credentials;
- separate backup access from normal application access;
- protect encryption-key material separately;
- log backup/restore access;
- do not expose backup locations in public health endpoints;
- test key recovery/rotation.

## 17.7 Backup retention

Backup retention is separate from application data retention.

Document:

- daily/weekly/monthly retention;
- immutable/offline copy if required;
- legal-hold implications;
- expired-backup destruction;
- credentials/key lifecycle;
- capacity forecast.

Do not promise immediate deletion from historical backups unless technically implemented and approved.

## 17.8 Automated verification

For every backup:

- command exit code successful;
- artifact exists;
- size plausible;
- checksum matches;
- age within policy;
- manifest complete;
- off-server copy confirmed;
- alert emitted on failure.

Verification without restore is necessary but not sufficient.

---

# 18. Restore and Disaster Recovery

## 18.1 Restore ownership

Before production, identify:

- incident commander;
- technical restore owner;
- business validation owner;
- security/audit owner;
- communication owner;
- authority to enable maintenance mode;
- authority to select recovery point.

## 18.2 Restore drill

At least one complete restore must succeed before production launch. Repeat at the approved cadence.

A restore drill uses an isolated environment and must not overwrite production.

## 18.3 Restore sequence

```text
1. Declare restore test or incident and choose recovery point.
2. Preserve incident evidence and current-state snapshots when appropriate.
3. Provision clean isolated host/environment.
4. Restore PostgreSQL.
5. Restore private file storage.
6. Restore compatible configuration and release artifacts.
7. Confirm schema/release compatibility.
8. Run migrations only according to the selected recovery plan.
9. Start dependencies, API, workers, and frontends in controlled order.
10. Run readiness and dependency checks.
11. Validate data/file consistency.
12. Validate security and business workflows.
13. Record actual RPO/RTO and discrepancies.
```

## 18.4 Restore validation checklist

Validate:

- admin and trader authentication;
- session/security behavior;
- role and permission assignments;
- trader isolation;
- representative payment request/revision;
- payment attempt and retry history;
- batch/version/items/approval hash;
- final export metadata/checksum/file availability;
- bank result bundle and manual crop;
- active/replaced evidence links;
- trader publication history;
- gold order and incoming-payment matching;
- audit and security events;
- outbox state and duplicate-safe recovery;
- important job records;
- file metadata-to-object consistency;
- no public storage access;
- backup manifest consistency.

## 18.5 Point-in-time recovery

If PITR/WAL archiving is adopted, the runbook must explain:

- restore target selection;
- relation between database target time and file-storage state;
- verification of post-target files;
- handling of orphan/missing storage objects;
- replay/outbox implications;
- approval/export/publication integrity.

## 18.6 Disaster recovery limitation

Until multi-host replication/failover is implemented, recovery may require provisioning a replacement server. State this honestly in business continuity planning.

---

# 19. CI/CD and Artifact Supply Chain

## 19.1 Pull-request gates

CI must fail on:

- backend lint/format/type failures;
- frontend lint/format/type failures;
- unit/component/integration/workflow/security test failures;
- OpenAPI generation/compatibility failure;
- status mapping mismatch;
- migration failure on clean PostgreSQL;
- migration upgrade failure from supported current schema;
- production build failure for either frontend;
- backend/worker image build failure;
- secret scan failure;
- prohibited mutable production tags;
- dependency/container vulnerability above approved threshold;
- missing required documentation/release note for schema/API/security changes.

## 19.2 Immutable build artifacts

Build once and promote the same digests:

```text
source commit
→ backend image digest
→ trader frontend image digest
→ admin frontend image digest
→ migration revision
→ SBOM/dependency inventory
→ signed/attested release metadata where practical
```

Do not rebuild a different production artifact after staging approval.

## 19.3 Registry

- private or access-controlled registry;
- least-privilege push/pull credentials;
- immutable tags where supported;
- retention policy preserving rollback artifacts;
- vulnerability scanning;
- audit of production pulls/deploys where possible.

## 19.4 Release record

Every release records:

- release version;
- source commit;
- image digests;
- schema revision;
- configuration/feature-flag changes;
- migration plan;
- backup/precheck result;
- staging test result;
- approver;
- deployment time/operator;
- smoke-test result;
- rollback/forward-fix instructions;
- known issues.

---

# 20. Deployment Process

## 20.1 Pre-deployment checklist

Before production deployment:

- change approved;
- release artifacts built and scanned;
- staging deployment uses same digests;
- staging migrations successful;
- automated tests successful;
- security/QA/UAT approvals complete as required;
- release notes prepared;
- feature flags reviewed;
- migration lock/downtime assessed;
- database connection/storage/disk capacity checked;
- backup completed and verified;
- rollback/forward-fix path reviewed;
- operations and business owners notified;
- maintenance mode decision recorded.

## 20.2 Deployment sequence

```text
1. Record current release and health.
2. Confirm backup/prechecks.
3. Enable maintenance mode or write restrictions if required.
4. Pause selected workers/scheduler when required by migration plan.
5. Run controlled migration with migration role.
6. Deploy pinned backend/frontends/worker/scheduler images.
7. Start dependencies and services in approved order.
8. Wait for readiness; do not rely on fixed sleeps.
9. Run automated smoke tests.
10. Run targeted business/security verification.
11. Resume workers/scheduler.
12. Disable maintenance mode.
13. Monitor error, queue, outbox, DB, storage, and audit signals.
14. Record deployment outcome.
```

## 20.3 Production smoke tests

Production smoke tests should avoid creating real financial transactions unless an approved isolated test identity/workflow exists.

Minimum safe checks:

- HTTPS and both frontend shells;
- admin/trader login with designated test accounts if approved;
- readiness endpoint;
- restricted dependency/worker health;
- read-only dashboard/query;
- private file authorization using approved non-production test file;
- queue/outbox progress;
- audit event generation for a safe test action;
- no unexpected cross-role access;
- release version/digest visible to operators.

Full financial workflow tests run in staging.

## 20.4 Maintenance mode

Maintenance mode must be explicit and audited.

Possible behavior:

- public/trader writes blocked;
- read-only access allowed where safe;
- admin access limited to approved maintenance roles;
- selected command endpoints rejected with a stable maintenance error;
- workers paused or restricted by queue;
- health endpoints distinguish intentional maintenance from process failure;
- emergency access uses controlled break-glass, not a permanent super-admin.

Maintenance mode must not silently discard submissions.

## 20.5 Deployment failure

If readiness or smoke checks fail:

- keep or re-enable maintenance restrictions;
- stop rollout;
- preserve logs and release state;
- decide application rollback vs forward fix vs database restore;
- do not automatically downgrade database without plan;
- document incident/change outcome.

---

# 21. Rollback and Forward-Fix Strategy

## 21.1 Application rollback

Application rollback uses previously approved image digests and compatible configuration.

Do not retag/rebuild old source as “previous.”

## 21.2 Database compatibility

Database downgrade is not assumed safe.

Each release declares:

- whether previous application version can run against new schema;
- compatibility window;
- downgrade migration availability, if any;
- forward-fix strategy;
- restore threshold.

## 21.3 Expand-and-contract advantage

Backward-compatible migrations allow application rollback without immediate database restore. Prefer this for high-risk schema changes.

## 21.4 Restore threshold

Database restore is a major incident decision because it may lose committed transactions after the selected recovery point.

Before restore:

- estimate data loss relative to RPO;
- preserve current evidence/snapshot;
- involve business/security owners;
- reconcile external bank actions that may have occurred;
- plan post-restore idempotency/outbox/export checks.

## 21.5 File rollback

Deployments do not delete or overwrite business files. File cleanup and retention are separate governed operations.

## 21.6 Feature-flag rollback

Optional features may be disabled rapidly when safe, including:

- AI/OCR;
- automatic segmentation;
- external provider use;
- non-core reports/integrations.

Feature flags cannot bypass or disable mandatory controls such as manager approval, audit, idempotency, authorization, or manual crop required by Phase 1A.

---

# 22. Retention, Deletion, and Legal Hold Operations

## 22.1 Separate policies

Distinguish:

- application-record retention;
- file/evidence retention;
- audit/security-event retention;
- operational-log retention;
- backup retention;
- temporary-processing retention.

## 22.2 No simple retention setting

Retention is not a technical-admin-only integer setting.

A reduction follows:

```text
proposal
→ business/legal review
→ approval
→ legal-hold check
→ dry run
→ backup-impact review
→ activation
→ separate deletion execution
→ verification/audit report
```

## 22.3 Legal hold

Legal hold blocks deletion/expiration for affected records/files/backups as defined by policy.

Operations must be able to:

- apply hold by authorized role;
- identify affected scope;
- prevent cleanup jobs;
- audit application/removal;
- preserve incident/dispute evidence;
- report held records.

## 22.4 Deletion job controls

When eventually approved, deletion jobs must be:

- explicitly authorized;
- dry-run capable;
- idempotent;
- bounded;
- resumable;
- legal-hold aware;
- backup-policy aware;
- fully audited;
- reversible only where technically possible and clearly stated.

Do not implement broad `find ... -delete` or storage lifecycle rules detached from database policy.

## 22.5 Temporary files

Temporary render/upload artifacts may have shorter retention only when:

- not authoritative evidence;
- not referenced by a business record;
- not under hold;
- cleanup state is verified;
- deletion is logged/observable;
- original/required derivative remains available.

---

# 23. Security Operations

## 23.1 Administrative access

- named accounts;
- MFA where approved/available;
- SSH keys;
- minimal sudo;
- session logging where appropriate;
- periodic access review;
- immediate removal on role departure;
- no shared everyday root password.

## 23.2 Break-glass

Emergency access is:

- disabled by default;
- time-limited;
- reason/incident-linked;
- recent-authenticated;
- alerted;
- fully audited;
- reviewed after use.

Break-glass should not routinely approve outgoing payments. Financial use requires immediate secondary review and incident classification.

## 23.3 Vulnerability and dependency management

Maintain reviewed update procedures for:

- host OS;
- Docker Engine/Compose;
- Nginx;
- PostgreSQL;
- Redis;
- Python dependencies;
- Node dependencies;
- base images;
- PDF/image/Excel parsing libraries;
- malware scanner;
- monitoring agents.

Security fixes are tested in staging and deployed according to severity and compatibility.

## 23.4 File-security incident controls

Operators must be able to:

- quarantine a file/export;
- revoke access/signed URLs;
- disable preview processing;
- identify downloads/access attempts;
- preserve original/checksum;
- notify security/business owner;
- prevent trader publication;
- create replacement evidence/publication through normal correction workflow.

## 23.5 Audit protection

- application audit APIs are read-only;
- runtime DB role cannot update/delete audit rows;
- backup includes audit;
- audit insert failure is a financial-command failure;
- audit export is permission-controlled;
- incident preservation may extend retention/hold;
- operations must not edit audit to “correct” history.

---

# 24. Incident Management

## 24.1 Incident classes

Examples:

- platform outage;
- database/storage outage;
- disk full;
- backup/restore failure;
- worker/outbox stuck;
- deployment regression;
- cross-trader exposure;
- unauthorized role/permission grant;
- lost or exposed secret;
- public file access;
- export integrity mismatch;
- wrong batch version/export sent;
- incorrect payment confirmation;
- wrong evidence/publication;
- audit insertion/tampering issue;
- malware upload;
- AI/provider data-governance issue;
- suspicious authentication activity.

## 24.2 Severity

Define an approved severity model considering:

- financial impact;
- data exposure;
- number of traders/records;
- active misuse;
- availability impact;
- recoverability;
- legal/contractual notification requirement;
- evidence integrity.

## 24.3 General response

```text
1. Detect and acknowledge.
2. Assign incident commander and severity.
3. Contain damage.
4. Preserve logs, audit, files, database snapshots, and release state.
5. Revoke sessions/credentials or quarantine artifacts where needed.
6. Inform business/security owners.
7. Apply safe fix, rollback, or restore.
8. Validate financial, security, and ownership state.
9. Communicate status and resolution.
10. Complete incident report and prevention actions.
```

## 24.4 Financial mistake response

Do not delete or silently rewrite the record.

Use:

- correction command;
- replacement/supersession;
- manager/dual control where required;
- aggregate recalculation;
- publication N+1;
- trader notification;
- incident and audit trail;
- reconciliation with actual bank action.

## 24.5 Data exposure response

Potential steps:

- revoke affected sessions/URLs;
- disable affected endpoint/feature;
- quarantine files;
- rotate credentials;
- preserve access logs;
- identify scope and affected users;
- verify ownership filters;
- complete required notifications according to approved policy.

## 24.6 Incident evidence

Incident handling must preserve:

- release/image digest;
- configuration version;
- audit/security events;
- relevant database snapshot;
- file checksums;
- Nginx/API/worker logs;
- access/role changes;
- backup state;
- external provider/bank interaction metadata.

---

# 25. Operational Runbooks

The repository must contain reviewed runbooks under `ops/runbooks`.

Minimum runbooks:

```text
deploy-production.md
rollback-production.md
migration-failed.md
restore-database-and-files.md
backup-failed.md
restore-test.md
rotate-session-secret.md
rotate-database-credential.md
rotate-storage-credential.md
create-initial-admin.md
revoke-user-sessions.md
break-glass-access.md
worker-or-outbox-stuck.md
redis-unavailable.md
postgres-unavailable.md
storage-unavailable.md
disk-space-low.md
file-quarantine.md
export-integrity-mismatch.md
wrong-result-or-evidence.md
security-data-exposure.md
ai-provider-down.md
certificate-renewal.md
retention-dry-run.md
legal-hold.md
```

Each runbook includes:

- purpose;
- trigger/when to use;
- severity;
- required role/access;
- prechecks;
- exact commands or UI steps;
- expected output;
- safety warnings;
- verification;
- rollback/recovery;
- escalation;
- audit/change/incident record requirements;
- last tested date and owner.

Runbooks must be exercised, not merely written.

---

# 26. AI/OCR Operational Controls

## 26.1 Default state

```text
AI enabled: false
External provider enabled: false
OCR enabled: false
Automatic segmentation enabled: false
AI matching enabled: false
Manual crop enabled: true
Manual review required: true
```

## 26.2 External provider approval

Before sending production financial documents externally, approve:

- provider/security review;
- contractual/data-processing terms;
- residency and retention;
- subprocessor policy;
- training-use restrictions;
- input scope/minimization;
- cost budget;
- incident owner;
- feature flags and rollback;
- shadow/limited rollout plan.

## 26.3 Provider outage

- core workflow remains available;
- jobs fail to manual fallback;
- no payment status changes;
- provider circuit breaker prevents repeated cost/failure;
- operator alert according to optional-service severity;
- existing evidence/publications remain accessible.

## 26.4 AI secrets and workers

Provider keys are accessible only to the AI worker/adapter that needs them, not to frontend, Nginx, or unrelated workers.

## 26.5 Cost controls

When enabled, monitor per provider/use case/environment:

- request count;
- pages/tokens;
- cost;
- latency;
- failure rate;
- budget remaining;
- manual fallback/correction rate.

Budget exhaustion disables paid provider calls, not manual business operations.

---

# 27. Capacity and Performance Operations

## 27.1 Approved targets

Initial Phase 1A targets:

- normal list/dashboard under 3 seconds under approved pilot data;
- normal API p95 under 500 ms where practical;
- upload acknowledgement under 5 seconds;
- moderate export under 30 seconds or asynchronous with visible state;
- paginated/filterable large lists;
- bounded preview/crop rendering.

## 27.2 Capacity inputs required

Before final host sizing, approve:

- active traders;
- daily/peak requests;
- average/max batch rows;
- bank-result bundle size/page count;
- upload concurrency;
- evidence retention volume;
- generated crop/publication volume;
- report volume;
- worker task duration;
- backup window and destination bandwidth;
- RPO/RTO.

## 27.3 Load tests

Test:

- representative API read/write load;
- accountant work queues;
- manager approval view with large batch;
- final export generation;
- concurrent uploads;
- multi-page PDF preview/crop;
- worker queue backlog/recovery;
- outbox dispatch;
- file download streaming;
- backup duration;
- restore duration;
- database connection saturation.

Do not use production sensitive files in load-test tooling.

## 27.4 Resource limits

Set container concurrency and memory/CPU limits after measurement.

Avoid:

- Celery concurrency that exhausts DB connections;
- too many PDF render processes causing memory pressure;
- frontend/backend worker counts exceeding host RAM;
- backups consuming all disk I/O during peak operations;
- unbounded report/export jobs.

---

# 28. Initial Production Setup

## 28.1 Required initial data

Production requires approved:

- roles and permission catalogue;
- initial business admin/manager/accountant accounts;
- source bank accounts;
- bank profile versions;
- bank mapping/template fixtures validated against real requirements;
- file categories and limits;
- business timezone/cutoff configuration;
- feature flags;
- notification settings;
- retention/legal-hold policy status;
- monitoring/alert recipients.

Do not assume a specific bank such as Resalat is the production default unless the business explicitly approves and validates it.

## 28.2 Seed rules

- production seeds are idempotent;
- no fake financial records;
- no default passwords;
- bank rules are versioned records, not hidden constants;
- initial data execution is logged;
- rerun does not overwrite approved production configuration.

## 28.3 Pre-go-live verification

- DNS/TLS;
- backups/off-server copy;
- restore drill;
- RBAC and separation of duties;
- manager recent-auth flow;
- batch version/hash approval;
- export integrity and quarantine;
- secure file upload/download;
- manual crop and provenance;
- trader publication isolation;
- audit/outbox/idempotency;
- alert delivery;
- incident contacts/runbooks;
- capacity free space;
- no enabled unapproved AI/provider.

---

# 29. Production Acceptance Criteria

Phase 1A is not production-ready until all criteria below are met.

## 29.1 Topology and hardening

1. Only Nginx exposes public application ports.
2. PostgreSQL and Redis have no public host ports.
3. Production images are pinned by digest and run as non-root.
4. Docker socket is not mounted into application containers.
5. Persistent database and file-storage paths are explicit and documented.
6. Host firewall, SSH hardening, and time synchronization are active.
7. Staging is separate from production.

## 29.2 Application services

8. Trader and Admin frontends are separate builds/deployments.
9. Backend readiness and liveness use canonical endpoints.
10. Worker heartbeat and queue progress are visible.
11. Scheduler is separate and has no financial authority.
12. Redis loss does not erase authoritative business/job state.
13. Manual crop works with AI fully disabled.

## 29.3 Security and secrets

14. Service-specific secrets are protected and absent from Git/images/frontend variables.
15. No default/demo credentials remain.
16. Session, CSRF, recent-auth, and revocation controls match the approved security ADR.
17. RBAC, trader isolation, separation of duties, and break-glass controls are tested.
18. Runtime DB roles cannot update/delete append-only audit/approval records.
19. Sensitive logs/metrics are redacted.

## 29.4 Financial integrity

20. Manager approves exact immutable batch version/hash.
21. Final export is generated only from the approved version.
22. Export checksum/hash/row-count/total integrity is revalidated before operational use.
23. Integrity mismatch quarantines the export.
24. Mark-as-sent references the exact export.
25. Worker/scheduler cannot confirm paid, publish, approve, or dispatch.
26. Idempotency and optimistic concurrency operate in production.
27. Audit, outbox, and idempotency commit atomically with sensitive commands.

## 29.5 Files

28. Files are private and authorization-checked on every access.
29. Upload lifecycle includes pending/validation/quarantine/available states.
30. Manual crop preserves original and provenance.
31. Storage reconciliation identifies missing/orphan/mismatched objects.
32. Full mixed bank result bundles are never trader-accessible.

## 29.6 Backup and recovery

33. Database backup is automatic and monitored.
34. File-storage backup is automatic and monitored.
35. Encrypted backup copy exists outside the production failure domain.
36. Backup manifest records DB/storage/release/schema/checksum data.
37. Complete isolated restore has succeeded.
38. Restored RBAC, trader isolation, audit, approvals, exports, and files have been verified.
39. RPO/RTO, backup retention, restore owner, and alert owner are approved.

## 29.7 Release and operations

40. CI quality/security/migration gates pass.
41. Same immutable artifacts are promoted from staging.
42. Deployment, rollback, migration-failure, backup, restore, disk, worker, storage, and incident runbooks exist and have owners.
43. Monitoring and alert delivery are tested.
44. Release record and post-deployment smoke test are complete.
45. Retention deletion is disabled until governed policy/legal-hold workflow is approved.

---

# 30. Coding-Agent and DevOps Rules

1. Do not expose PostgreSQL, Redis, worker, scheduler, or storage administration publicly.
2. Do not deploy mutable `latest` images.
3. Do not rebuild production artifacts after staging approval; promote the same digest.
4. Do not run application containers as root without an approved documented exception.
5. Do not mount the Docker socket into application containers.
6. Do not commit production secrets or share one broad secret file across every service.
7. Do not expose backend secrets through frontend public variables.
8. Do not store permanent business/job truth only in Redis or Celery result storage.
9. Do not publish Celery tasks before database commit; use transactional outbox.
10. Do not allow workers or scheduler to make human financial decisions.
11. Do not use an opaque unbacked Docker volume as the sole file-evidence store.
12. Do not serve uploaded files from public static directories.
13. Do not overwrite evidence, bank exports, publications, or original uploads.
14. Do not deploy without automatic database and file backups.
15. Do not call a backup successful until it is monitored and restore-tested.
16. Do not treat a production-disk-only copy as disaster recovery.
17. Do not manually alter production schema outside controlled migration/incident process.
18. Do not assume database downgrade is safe during rollback.
19. Do not run destructive migrations/backfills without a bounded, reviewed plan.
20. Do not use old `/health` or `/health/deep` paths as the canonical health contract.
21. Do not expose dependency details publicly.
22. Do not log credentials, full sensitive identifiers, raw bank payloads, or file contents.
23. Do not use high-cardinality sensitive metric labels.
24. Do not enable AI/external providers by default in Phase 1A.
25. Do not disable manager approval, audit, authorization, idempotency, or concurrency with feature flags.
26. Do not hard-code one bank, source account, mapping, limit, or business cutoff.
27. Do not implement automatic retention deletion before approval/legal-hold/dry-run controls.
28. Do not delete audit or incident evidence to make history look correct.
29. Do not use permanent broad super-admin access; use controlled break-glass.
30. Do not claim high availability, RPO, RTO, encryption, or backup consistency that has not been implemented and tested.

---

# 31. Required ADRs and Production Decisions

The implementation baseline is approved, but the following must be resolved before production launch or activation of the related capability.

| ADR / Decision | Required outcome |
|---|---|
| `ADR-OPS-001` Hosting/topology | Provider, region, host ownership, network restrictions, availability expectations. |
| `ADR-OPS-002` Production storage | Local bind mount vs S3-compatible service, residency, encryption, migration plan. |
| `ADR-OPS-003` RPO/RTO | Approved targets, business owner, recovery owner, recovery-point selection. |
| `ADR-OPS-004` Backup design | Schedule, off-server destination, encryption, consistency model, retention, restore cadence. |
| `ADR-OPS-005` Authentication deployment | Session transport, cookie domains, CSRF, timeouts, revocation. |
| `ADR-OPS-006` Manager strong authentication | Factor, recent-auth timeout, fallback and recovery. |
| `ADR-OPS-007` Malware scanning | Scanner, failure policy, quarantine workflow, update ownership. |
| `ADR-OPS-008` File limits/capacity | Maximum file/bundle/page sizes, expected daily volume, storage forecast. |
| `ADR-OPS-009` Monitoring/alerts | Tooling, recipients, severities, response windows, incident owner. |
| `ADR-OPS-010` Retention/legal hold | Durations, authority, deletion workflow, backup implications. |
| `ADR-OPS-011` Admin/network restrictions | VPN, IP allowlist, SSH source restrictions, access review. |
| `ADR-OPS-012` Initial bank configuration | Approved banks, source accounts, mappings/templates, fixtures, validation owner. |
| `ADR-OPS-013` Log and audit retention | Duration, storage, access, export, incident hold. |
| `ADR-OPS-014` Release approval | Who may approve production release, migration, rollback, and break-glass. |
| `ADR-OPS-015` External AI/provider operations | Provider, data scope, residency, retention, cost, incident process, rollout. |

---

# 32. Final Operational Position

The approved Phase 1A operating model is:

```text
Single-tenant modular monolith
+ two separately deployed Next.js applications
+ FastAPI and PostgreSQL
+ Celery with Redis
+ private explicit file storage
+ Nginx-only public exposure
+ Docker Compose on a hardened Linux host
+ encrypted off-server database/file backups
+ tested restore and documented runbooks
+ immutable artifacts and controlled migrations
+ strict monitoring, audit, authorization, and incident controls
```

The first operational success criterion is not advanced orchestration or zero-downtime infrastructure.

It is that the center can safely run the complete manual financial and gold workflow, recover from failure, prove what happened, preserve evidence, and prevent unauthorized or ambiguous financial execution.

AI, OCR, external notifications, banking integrations, clustering, and Kubernetes may be added later only when they preserve these controls rather than bypass them.
