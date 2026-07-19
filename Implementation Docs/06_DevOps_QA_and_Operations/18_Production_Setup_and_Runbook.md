# Gold Trade Settlement Platform
# 18 — Production Setup and Operational Runbook

**Document ID:** `18_Production_Setup_and_Runbook`  
**Version:** `1.1`  
**Language:** English  
**Status:** `Authoritative production-runbook baseline`  
**Primary Audience:** DevOps engineer, backend lead, security lead, release manager, operations maintainer, QA lead, incident commander, coding agent  
**Phase Focus:** Phase 1A production first; later-phase services remain optional and isolated  
**Supersedes:** Version 1.0 of this document  

**Authoritative dependencies:**

- `03_System_Architecture.md`
- `04_Database_Schema.md`
- `05_API_Specification.md`
- `06_Workflows_and_State_Machines.md`
- `08_Bank_File_and_Result_Processing.md`
- `09_OCR_AI_Module_Specification.md`
- `10_Backend_Implementation_Guide.md`
- `11_Frontend_Implementation_Guide.md`
- `12_Security_RBAC_Audit.md`
- `13_DevOps_Deployment_Operations.md`
- `14_Testing_QA_Acceptance.md`
- `15_Agent_Implementation_Plan.md`
- `16_Implementation_Documentation_Index.md`
- `17_Future_Phases_Roadmap_and_Backlog.md`

---

## 1. Purpose and Authority

This document provides the concrete operating procedure for installing, configuring, validating, releasing, backing up, restoring, monitoring, maintaining, and recovering the Gold Trade Settlement Platform in production.

Document `13` defines the operational architecture and mandatory controls. This document turns those controls into runbook steps, command templates, evidence requirements, stop conditions, and verification checklists.

This runbook does not authorize an operator to invent unresolved production values. Values controlled by an ADR or business decision must remain placeholders until approved.

The following phrase governs all production operations:

> Preserve business need and control intent; do not reproduce unsafe manual tools or shortcuts.

### 1.1 Non-negotiable operational rules

1. Phase 1A must remain fully usable with AI, OCR, external validation providers, and bank APIs disabled.
2. Every outgoing Phase 1A payment batch requires manager approval of the exact immutable `PaymentBatchVersion`.
3. A final bank export must be bound to the exact approved version, hash, mapping version, source account, row count, total, and file checksum.
4. Downloading an export is not equivalent to sending it to the bank.
5. Marking an export as sent must identify the exact export artifact.
6. A worker may render, parse, normalize, or notify; it may not approve, confirm a payment, or publish a trader result.
7. PostgreSQL is the authoritative state store. Redis is not a business source of truth.
8. Database state, audit, outbox, and idempotency result must be committed atomically for sensitive commands.
9. Original files are immutable. Derived previews and crops are separate artifacts.
10. Manual rectangular crop is required in Phase 1A.
11. Candidate matching, confirmed evidence, payment result, and trader publication are separate decisions.
12. Production data must be recoverable together with its referenced files.
13. A backup stored only on the production server is not disaster recovery.
14. Financial records are corrected, superseded, revoked, cancelled, or archived; they are not generically deleted.
15. Retention deletion requires governance, legal-hold checks, dry run, approval, and audit.
16. Multi-company or SaaS behavior is not part of the Phase 1A deployment.

---

## 2. Scope, Assumptions, and Blocking Decisions

### 2.1 Runbook scope

This runbook covers:

- single-center Phase 1A deployment;
- two separate Next.js frontend applications;
- FastAPI backend;
- PostgreSQL;
- Celery workers and scheduler;
- Redis broker;
- private local-file storage for the pilot or an approved object-storage adapter;
- Nginx reverse proxy and TLS;
- database migrations;
- release and rollback;
- backup and restore;
- monitoring and alerting;
- file lifecycle and reconciliation;
- incident response;
- maintenance and retention operations.

### 2.2 This runbook does not decide

The following values require approved ADRs or production decisions:

- hosting provider and region;
- final CPU, memory, storage, and bandwidth sizing;
- authentication/session transport;
- manager strong-authentication method;
- recent-authentication expiry;
- production file-storage adapter;
- malware scanning implementation;
- maximum upload sizes and bundle limits;
- RPO and RTO;
- backup frequency and retention;
- legal-hold authority;
- audit/log retention;
- initial banks, source accounts, templates, and mapping versions;
- bank amount unit and date formats;
- administrator network restrictions;
- text-only payment confirmation policy;
- paid-result correction approval policy;
- IBAN masking policy;
- production monitoring and escalation owners;
- external AI provider approval.

### 2.3 Blocking ADR gate

Production launch is blocked while any unresolved decision can materially affect:

- schema or migration design;
- authentication security;
- financial authority;
- bank-export correctness;
- file privacy;
- restore feasibility;
- legal retention;
- incident ownership.

The release record must list every unresolved ADR and explicitly state whether it is launch-blocking.

---

## 3. Phase 1A Production Topology

### 3.1 Recommended pilot topology

The recommended Phase 1A pilot uses one hardened Linux host and one separate encrypted backup destination.

```text
Users
  |
  v
Nginx / TLS
  |----------------------|
  |                      |
Trader PWA           Admin Web
  |                      |
  |---------- Backend API -----------|
                                     |
             |-----------|-----------|-----------|
             |           |           |           |
         PostgreSQL    Redis      Celery      Private File
                                Workers       Storage
                                     |
                                  Scheduler

Separate destination:
Encrypted database + file + release-manifest backups
```

This topology is not highly available. The accepted RPO/RTO must reflect that limitation.

### 3.2 Required services

| Service | Phase 1A | Authority / purpose |
|---|---:|---|
| `nginx` | Required | Only public ingress, TLS, routing, request limits, security headers |
| `frontend-trader` | Required | Trader PWA only |
| `frontend-admin` | Required | Accountant, manager, warehouse, admin interfaces |
| `backend-api` | Required | Synchronous API and command/query boundary |
| `worker-files` | Required | Preview, PDF/image rendering, crop rendering, file jobs |
| `worker-exports` | Required | Preview/final bank export generation and integrity validation |
| `worker-notifications` | Required or shared | Notification and outbox side effects |
| `worker-maintenance` | Required or shared | Reconciliation, retention dry runs, maintenance jobs |
| `scheduler` | Required | Periodic dispatch, heartbeat, reconciliation, maintenance schedules |
| `postgres` | Required | Authoritative business, audit, outbox, idempotency, job metadata |
| `redis` | Required | Celery broker and non-authoritative short-lived coordination |
| private file storage | Required | Originals, derivatives, exports, publications, evidence |
| monitoring agent | Required | Host/service/backup/queue observability |
| `worker-ai` | Disabled by default | Future optional AI/OCR assistance only |

A small pilot may run several logical Celery queues in one worker process. Queue names and routing must still remain separate.

### 3.3 Network boundaries

Use three logical Docker networks:

```text
public_net
  nginx only

app_net
  nginx
  frontend-trader
  frontend-admin
  backend-api

data_net
  backend-api
  workers
  scheduler
  postgres
  redis
  approved internal storage endpoint
```

Only Nginx publishes host ports.

The following must not be published to the public network:

- PostgreSQL;
- Redis;
- backend application port;
- Celery worker ports;
- internal storage administration endpoint;
- metrics endpoints containing internal details;
- database administration tools.

### 3.4 Separate frontend boundary

The Trader PWA and Admin Web are separate deployment artifacts.

They must have separate:

- image names and digests;
- runtime environment files;
- route configuration;
- health checks;
- CSP and browser policies where needed;
- release verification;
- error reporting context.

Admin functionality must not be bundled into the Trader PWA and merely hidden by role checks.

---

## 4. Host Preparation and Hardening

### 4.1 Supported host baseline

The exact operating system version must be approved and supported by the operations team. A current supported Ubuntu LTS release is an acceptable default.

Minimum pilot sizing is a planning estimate, not a guarantee:

| Resource | Initial planning value | Required validation |
|---|---:|---|
| CPU | 4–8 vCPU | load and export/render tests |
| RAM | 8–16 GB | worker concurrency and PDF rendering tests |
| Primary storage | 150 GB+ SSD | expected file growth and backup window |
| Backup storage | separate destination | RPO/RTO and retention calculation |
| Network | stable domestic connectivity | user, backup, certificate, and provider needs |

### 4.2 Dedicated operating account

Create a dedicated non-root operating user, for example:

```bash
sudo adduser --disabled-password --gecos "" goldops
sudo usermod -aG docker goldops
```

Do not use a shared personal account for routine production operations.

Access must be attributable to a named person through individual SSH keys or an approved access gateway.

### 4.3 Required host packages

Install only approved packages. Typical requirements include:

```bash
sudo apt-get update
sudo apt-get install -y \
  ca-certificates \
  curl \
  git \
  jq \
  openssl \
  rsync \
  ufw
```

Install Docker Engine and the Docker Compose plugin from an approved package source.

Record installed versions in the deployment evidence.

### 4.4 Firewall baseline

Example baseline:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from <APPROVED_ADMIN_CIDR> to any port 22 proto tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status verbose
```

Do not use unrestricted SSH access when an approved network restriction is available.

### 4.5 Host security checklist

- SSH password authentication disabled where operationally feasible.
- Direct root login disabled.
- Sudo access limited and reviewed.
- Administrative access logged.
- Automatic security-update policy approved.
- Time synchronization enabled.
- Host timezone may be local, but application timestamps remain UTC.
- Docker socket not mounted into application containers.
- Host backups do not contain plaintext secrets unless explicitly encrypted.
- Swap and core-dump handling reviewed for sensitive data.
- Disk encryption decision documented.
- Certificate renewal ownership documented.

---

## 5. Production Directory Layout

Use explicit host paths so backup and restore scope is visible.

```text
/srv/gold-platform/
  releases/
  current -> releases/<release-id>/
  storage/
    pending/
    quarantine/
    originals/
    derivatives/
    exports/
    publications/
    archived/
  postgres/
  backup-staging/
  restore-staging/
  tls/
  logs/
  manifests/

/etc/gold-platform/
  frontend-trader.env
  frontend-admin.env
  backend.env
  worker.env
  scheduler.env
  postgres.env
  backup.env
```

Example creation:

```bash
sudo install -d -o goldops -g goldops -m 0750 /srv/gold-platform
sudo install -d -o goldops -g goldops -m 0750 /srv/gold-platform/{releases,storage,postgres,backup-staging,restore-staging,tls,logs,manifests}
sudo install -d -o goldops -g goldops -m 0750 /srv/gold-platform/storage/{pending,quarantine,originals,derivatives,exports,publications,archived}
sudo install -d -o root -g goldops -m 0750 /etc/gold-platform
```

Actual ownership must match the non-root UID/GID used by containers.

Do not use anonymous Docker volumes for business-critical file storage in production.

---

## 6. Release Artifacts and Image Governance

### 6.1 Immutable artifact rule

Production uses images identified by immutable digest.

Allowed example:

```text
registry.example/gold/backend@sha256:<digest>
```

Not allowed:

```text
registry.example/gold/backend:latest
```

A human-readable version tag may accompany the digest, but deployment authority comes from the digest recorded in the release manifest.

### 6.2 Artifact promotion

```text
Source commit
→ build once
→ test and scan
→ deploy same digests to staging
→ staging verification
→ approve
→ promote same digests to production
```

Do not rebuild production images after staging approval.

### 6.3 Release manifest

Each release must contain:

```yaml
release_id: "<version-or-change-id>"
commit_sha: "<git-sha>"
alembic_revision: "<revision>"
images:
  backend: "registry/...@sha256:..."
  trader_frontend: "registry/...@sha256:..."
  admin_frontend: "registry/...@sha256:..."
  nginx: "nginx@sha256:..."
  postgres: "postgres@sha256:..."
  redis: "redis@sha256:..."
feature_flags:
  manual_crop: true
  ai_ocr: false
  auto_segmentation: false
  auto_matching: false
  bank_api: false
migrations:
  - "<revision>"
known_issues: []
rollback_or_forward_fix: "<reference>"
approved_by: "<role/person>"
```

The manifest must not contain secrets.

---

## 7. Configuration and Secret Management

### 7.1 Service-specific environment files

Use separate environment files:

```text
/etc/gold-platform/frontend-trader.env
/etc/gold-platform/frontend-admin.env
/etc/gold-platform/backend.env
/etc/gold-platform/worker.env
/etc/gold-platform/scheduler.env
/etc/gold-platform/postgres.env
/etc/gold-platform/backup.env
```

Set permissions:

```bash
sudo chown root:goldops /etc/gold-platform/*.env
sudo chmod 0640 /etc/gold-platform/*.env
```

A single shared `.env.production` file is not the preferred production pattern.

### 7.2 Frontend public configuration

Frontend environment files may contain only non-secret values such as:

```env
NEXT_PUBLIC_APP_ENV=production
NEXT_PUBLIC_API_BASE_URL=https://api.example.ir/api/v1
NEXT_PUBLIC_APP_NAME=Gold Trade Settlement Platform
NEXT_PUBLIC_RELEASE_ID=<release-id>
```

They must not contain:

- database credentials;
- Redis credentials;
- session secrets;
- storage keys;
- signing secrets;
- backup keys;
- AI provider keys;
- bank credentials.

### 7.3 Backend configuration template

Exact names may differ in implementation, but the categories are mandatory.

```env
APP_ENV=production
APP_RELEASE_ID=<release-id>
APP_PUBLIC_URL=https://api.example.ir
APP_BUSINESS_TIMEZONE=<approved-iana-timezone>

DATABASE_URL=<secret-reference-or-runtime-value>
REDIS_BROKER_URL=<secret-reference-or-runtime-value>

STORAGE_BACKEND=local
STORAGE_ROOT=/app/storage
STORAGE_PENDING_PREFIX=pending
STORAGE_QUARANTINE_PREFIX=quarantine
STORAGE_ORIGINAL_PREFIX=originals
STORAGE_DERIVATIVE_PREFIX=derivatives
STORAGE_EXPORT_PREFIX=exports
STORAGE_PUBLICATION_PREFIX=publications

MANUAL_CROP_ENABLED=true
AI_ENABLED=false
OCR_ENABLED=false
AUTO_SEGMENTATION_ENABLED=false
AUTO_MATCHING_ENABLED=false
BANK_API_ENABLED=false
TEXT_ONLY_CONFIRMATION_ENABLED=false
BREAK_GLASS_ENABLED=false

MAX_UPLOAD_BYTES=<approved-value>
MAX_BUNDLE_FILES=<approved-value>
SIGNED_DOWNLOAD_TTL_SECONDS=<approved-value>

LOG_LEVEL=INFO
LOG_FORMAT=json
AUDIT_REQUIRED=true
OUTBOX_ENABLED=true
IDEMPOTENCY_REQUIRED=true

SESSION_MODE=<approved-adr-value>
SESSION_SECRET=<secret>
CSRF_SECRET=<secret-if-required>
RECENT_AUTH_TTL_SECONDS=<approved-value>
```

### 7.4 Worker configuration

Workers receive only permissions and secrets needed for their queue.

A file-rendering worker does not need financial approval credentials.

A backup process does not need application-session secrets.

### 7.5 Secret rotation

Every secret must have:

- owner;
- creation date;
- rotation method;
- rollback method;
- affected services;
- incident procedure;
- evidence of last test.

Rotation of a session or signing secret must define whether existing sessions are revoked.

### 7.6 Secret exposure response

When a secret may have been exposed:

1. classify the affected secret;
2. disable or restrict affected access;
3. rotate the secret;
4. revoke sessions or credentials as required;
5. inspect access and audit logs;
6. preserve incident evidence;
7. record impact and remediation;
8. verify the new secret in all dependent services.

---

## 8. Production Docker Compose Baseline

The repository must contain an environment-specific Compose file. The following is a structural template, not a copy-paste production guarantee.

```yaml
name: gold-platform

services:
  nginx:
    image: ${NGINX_IMAGE_DIGEST}
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    read_only: true
    tmpfs:
      - /var/cache/nginx
      - /var/run
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE
    volumes:
      - ./ops/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - /srv/gold-platform/tls:/etc/nginx/tls:ro
    depends_on:
      frontend-trader:
        condition: service_healthy
      frontend-admin:
        condition: service_healthy
      backend-api:
        condition: service_healthy
    networks:
      - public_net
      - app_net
    logging: &json_logging
      driver: json-file
      options:
        max-size: "20m"
        max-file: "5"

  frontend-trader:
    image: ${TRADER_FRONTEND_IMAGE_DIGEST}
    restart: unless-stopped
    env_file:
      - /etc/gold-platform/frontend-trader.env
    read_only: true
    tmpfs:
      - /tmp
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    healthcheck:
      test: ["CMD", "node", "healthcheck.js"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 20s
    networks:
      - app_net
    logging: *json_logging

  frontend-admin:
    image: ${ADMIN_FRONTEND_IMAGE_DIGEST}
    restart: unless-stopped
    env_file:
      - /etc/gold-platform/frontend-admin.env
    read_only: true
    tmpfs:
      - /tmp
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    healthcheck:
      test: ["CMD", "node", "healthcheck.js"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 20s
    networks:
      - app_net
    logging: *json_logging

  backend-api:
    image: ${BACKEND_IMAGE_DIGEST}
    restart: unless-stopped
    env_file:
      - /etc/gold-platform/backend.env
    read_only: true
    tmpfs:
      - /tmp
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    volumes:
      - /srv/gold-platform/storage:/app/storage
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-m", "app.healthcheck", "ready"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 30s
    stop_grace_period: 45s
    networks:
      - app_net
      - data_net
    logging: *json_logging

  worker-files:
    image: ${BACKEND_IMAGE_DIGEST}
    restart: unless-stopped
    command: ["celery", "-A", "app.worker", "worker", "-Q", "files", "--loglevel=INFO"]
    env_file:
      - /etc/gold-platform/worker.env
    read_only: true
    tmpfs:
      - /tmp
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    volumes:
      - /srv/gold-platform/storage:/app/storage
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    stop_grace_period: 90s
    networks:
      - data_net
    logging: *json_logging

  worker-exports:
    image: ${BACKEND_IMAGE_DIGEST}
    restart: unless-stopped
    command: ["celery", "-A", "app.worker", "worker", "-Q", "exports", "--loglevel=INFO"]
    env_file:
      - /etc/gold-platform/worker.env
    read_only: true
    tmpfs:
      - /tmp
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    volumes:
      - /srv/gold-platform/storage:/app/storage
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    stop_grace_period: 90s
    networks:
      - data_net
    logging: *json_logging

  worker-notifications:
    image: ${BACKEND_IMAGE_DIGEST}
    restart: unless-stopped
    command: ["celery", "-A", "app.worker", "worker", "-Q", "notifications", "--loglevel=INFO"]
    env_file:
      - /etc/gold-platform/worker.env
    read_only: true
    tmpfs:
      - /tmp
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - data_net
    logging: *json_logging

  worker-maintenance:
    image: ${BACKEND_IMAGE_DIGEST}
    restart: unless-stopped
    command: ["celery", "-A", "app.worker", "worker", "-Q", "maintenance,reports", "--loglevel=INFO"]
    env_file:
      - /etc/gold-platform/worker.env
    read_only: true
    tmpfs:
      - /tmp
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    volumes:
      - /srv/gold-platform/storage:/app/storage
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - data_net
    logging: *json_logging

  scheduler:
    image: ${BACKEND_IMAGE_DIGEST}
    restart: unless-stopped
    command: ["celery", "-A", "app.worker", "beat", "--loglevel=INFO"]
    env_file:
      - /etc/gold-platform/scheduler.env
    read_only: true
    tmpfs:
      - /tmp
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - data_net
    logging: *json_logging

  postgres:
    image: ${POSTGRES_IMAGE_DIGEST}
    restart: unless-stopped
    env_file:
      - /etc/gold-platform/postgres.env
    volumes:
      - /srv/gold-platform/postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U \"$${POSTGRES_USER}\" -d \"$${POSTGRES_DB}\""]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 30s
    stop_grace_period: 90s
    networks:
      - data_net
    logging: *json_logging

  redis:
    image: ${REDIS_IMAGE_DIGEST}
    restart: unless-stopped
    command: ["redis-server", "/usr/local/etc/redis/redis.conf"]
    volumes:
      - ./ops/redis/redis.conf:/usr/local/etc/redis/redis.conf:ro
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 10
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    networks:
      - data_net
    logging: *json_logging

networks:
  public_net: {}
  app_net:
    internal: true
  data_net:
    internal: true
```

### 8.1 Compose validation

Before use:

```bash
docker compose --env-file /etc/gold-platform/release.env \
  -f compose.production.yml config --quiet
```

The rendered configuration must be reviewed for:

- unintended host-port publication;
- incorrect image tags or missing digests;
- secret exposure;
- wrong bind mounts;
- missing read-only and security settings;
- incorrect networks;
- missing health checks.

### 8.2 Prohibited Compose actions

Never run the following in production without an approved destructive change plan:

```bash
docker compose down -v
```

Do not prune volumes, images, or build cache indiscriminately on the production host.

---

## 9. Nginx, TLS, and Routing

### 9.1 Recommended routing

```text
https://app.example.ir    → frontend-trader
https://admin.example.ir  → frontend-admin
https://api.example.ir    → backend-api
```

Separate subdomains provide clearer session, CSP, routing, and incident boundaries.

### 9.2 Nginx responsibilities

- TLS termination;
- HTTP-to-HTTPS redirect;
- routing to two frontend services and API;
- request body-size limit;
- timeouts suitable for asynchronous upload acknowledgement;
- rate limiting for authentication and upload entry points;
- security headers;
- correlation/request ID propagation;
- rejection of unsupported methods and malformed requests;
- no direct serving of private application files.

### 9.3 Security headers

Headers must be tested with both frontends and secure file previews.

At minimum, evaluate:

```text
Strict-Transport-Security
Content-Security-Policy
X-Content-Type-Options
Referrer-Policy
Permissions-Policy
frame-ancestors through CSP
```

Avoid relying only on deprecated or redundant headers.

### 9.4 Upload handling

Nginx and backend limits must match the approved upload policy.

The reverse proxy must not buffer an unbounded request to disk without capacity planning.

The API should acknowledge accepted uploads and process expensive rendering asynchronously.

### 9.5 TLS runbook

The certificate owner must document:

- issuance method;
- renewal schedule;
- alert threshold;
- key-storage location;
- emergency replacement procedure;
- verification command;
- fallback if automated renewal fails.

---

## 10. Health and Readiness Contract

The canonical endpoints are:

```http
GET /api/v1/health/live
GET /api/v1/health/ready
GET /api/v1/health/dependencies
GET /api/v1/health/workers
```

### 10.1 Liveness

`/live` confirms that the process can answer requests.

It must not fail merely because an optional provider is unavailable.

### 10.2 Readiness

`/ready` confirms that the API is ready to accept normal traffic.

Required checks may include:

- application initialization complete;
- PostgreSQL reachable;
- schema compatible;
- essential storage metadata access available;
- write barrier or maintenance state considered.

Redis failure may make the system partially degraded. The exact readiness behavior must match the approved operational policy.

### 10.3 Dependency health

`/dependencies` is restricted to authorized internal or administrative access.

It may summarize:

- PostgreSQL;
- Redis;
- storage;
- outbox age;
- optional provider status.

It must not expose credentials, internal URLs, stack traces, or sensitive file paths.

### 10.4 Worker health

`/workers` reports PostgreSQL-backed heartbeat summaries and queue health.

Celery result backend state alone is not authoritative.

---

## 11. First-Time Production Installation

### 11.1 Required approvals before installation

The installation ticket must include:

- approved host and region;
- approved domains;
- approved release manifest and image digests;
- approved authentication configuration;
- approved storage configuration;
- approved backup destination;
- RPO/RTO owner;
- initial business and technical administrators;
- approved bank-profile setup owner;
- monitoring and incident contacts;
- maintenance window;
- rollback/forward-fix decision owner.

### 11.2 Prepare directories and configuration

1. create the host directories from Section 5;
2. create service-specific environment files;
3. verify ownership and permissions;
4. place the release manifest in `/srv/gold-platform/manifests/`;
5. load or pull only approved image digests;
6. verify the image digests against the manifest.

Example verification:

```bash
docker image inspect "${BACKEND_IMAGE_DIGEST}" --format '{{json .RepoDigests}}'
```

### 11.3 Validate configuration

Run:

```bash
docker compose --env-file /etc/gold-platform/release.env \
  -f compose.production.yml config --quiet
```

Then manually inspect the rendered output without printing secret values into ticket systems.

### 11.4 Start PostgreSQL and Redis

```bash
docker compose --env-file /etc/gold-platform/release.env \
  -f compose.production.yml up -d postgres redis
```

Wait for health checks. Do not use a fixed sleep as the only readiness mechanism.

### 11.5 Create database roles

Create and verify separate roles for:

- runtime application;
- workers, if separately restricted;
- migrations;
- backup;
- read-only operations.

The runtime role must not own the schema and must not have permission to update or delete append-only audit and approval history.

### 11.6 Run migrations

Use the dedicated migration role and the exact release image.

Example template:

```bash
docker compose --env-file /etc/gold-platform/release.env \
  -f compose.production.yml run --rm \
  --env-file /etc/gold-platform/migration.env \
  backend-api alembic upgrade head
```

Record:

- start and end time;
- previous and new revision;
- command exit status;
- migration logs;
- lock or downtime observed;
- verification result.

### 11.7 Seed only approved reference data

Production seed scripts may create:

- canonical roles;
- canonical permissions;
- required file categories;
- approved system defaults that do not encode unresolved business policy.

Production seed scripts must not create:

- fake financial records;
- fake traders presented as real;
- placeholder bank mappings;
- guessed source accounts;
- a permanent unrestricted super-admin account;
- automatic retention deletion policy.

### 11.8 Create initial administrators

Use a secure management command.

The command must:

- avoid printing passwords;
- create a named account;
- apply only approved permissions;
- require credential change or secure activation;
- create an audit/security event;
- avoid granting financial authority to a technical administrator by default.

### 11.9 Configure bank profiles manually

Before outgoing payments can be processed, authorized users must configure and validate:

- bank profile;
- bank profile version;
- source account;
- mapping/template version;
- amount unit;
- date format;
- required columns;
- splitting rules;
- sample input/output fixtures;
- activation approval.

No bank profile is considered production-ready merely because it exists in the database.

### 11.10 Start the full stack

```bash
docker compose --env-file /etc/gold-platform/release.env \
  -f compose.production.yml up -d
```

### 11.11 Verify health

```bash
curl --fail --silent https://api.example.ir/api/v1/health/live
curl --fail --silent https://api.example.ir/api/v1/health/ready
```

Restricted checks must be run through an approved authenticated channel.

### 11.12 Initial non-financial production smoke test

Production smoke testing must avoid creating real payment requests, approvals, exports, or payment confirmations unless an approved production fixture and cleanup/correction plan exist.

Required smoke checks:

1. Trader PWA loads over HTTPS.
2. Admin Web loads over HTTPS.
3. Authorized test/operator account can log in.
4. Logout and session revocation work.
5. Read-only dashboard or approved fixture loads.
6. A known authorized file fixture can be accessed.
7. Unauthorized file access is rejected.
8. Worker heartbeat is visible.
9. Outbox dispatcher is progressing.
10. Monitoring receives health data.
11. Backup job is scheduled.
12. Release ID and schema revision match the manifest.

Full financial workflow tests belong in staging or a formally isolated production test context.

### 11.13 Installation evidence

Capture:

- release manifest;
- image digests;
- schema revision;
- health results;
- permission test results;
- TLS verification;
- backup schedule evidence;
- monitoring screenshots or event references;
- named approvers;
- known limitations.

---

## 12. Database Migration Runbook

### 12.1 Migration principles

- Every schema change uses Alembic.
- Applied migrations are not edited.
- Migrations are tested from a clean database and from the current production-equivalent revision.
- Destructive change is separated from code rollout.
- Large backfills are bounded, resumable, observable, and idempotent.
- Application rollback is not assumed to reverse database changes.

### 12.2 Pre-migration checklist

- migration reviewed by backend/database owner;
- staging upgrade successful;
- representative data tested;
- lock and runtime impact measured;
- current backup verified;
- restore decision owner available;
- maintenance/write-barrier decision made;
- workers to pause identified;
- forward-fix plan documented;
- post-migration verification prepared.

### 12.3 Expand-and-contract sequence

```text
1. Expand schema with backward-compatible structures.
2. Deploy compatible application version.
3. Backfill in bounded batches.
4. Verify data and performance.
5. Switch reads/writes.
6. Observe.
7. Remove old structures in a later release.
```

### 12.4 Migration failure

On migration failure:

1. stop further deployment steps;
2. preserve migration logs;
3. determine whether the transaction rolled back;
4. inspect schema revision and partial side effects;
5. do not blindly run downgrade;
6. choose forward fix, application rollback, or restore with the incident owner;
7. record the decision and financial-data risk.

---

## 13. Release and Update Runbook

### 13.1 Pre-release gate

A production release is blocked unless:

- CI and QA gates pass;
- staging uses the exact image digests;
- migrations pass in staging;
- security findings are resolved or formally accepted;
- bank-export integrity tests pass when affected;
- idempotency and concurrency tests pass when affected;
- file-isolation tests pass when affected;
- backup is current and verified;
- release and incident owners are present;
- rollback/forward-fix plan exists;
- feature flags are explicitly recorded.

### 13.2 Pre-deployment operational checks

Check:

- no unresolved final-export integrity incident;
- no ambiguous bank-submission state requiring reconciliation;
- no active destructive retention execution;
- no legal-hold breach risk;
- no critical file reconciliation error;
- disk capacity sufficient for release and backup;
- certificate valid;
- database connection headroom sufficient;
- queue backlog understood;
- long-running rendering/export jobs identified.

### 13.3 Create deployment backup set

Create a consistent backup set and manifest as described in Section 17.

A successful command exit alone is not sufficient; verify checksums and destination transfer.

### 13.4 Enable write restriction when required

Use a controlled maintenance or write-barrier mechanism for risky migrations or restores.

The barrier must block financial commands, not merely hide frontend buttons.

### 13.5 Drain or pause queues

Pause only queues affected by the release.

Before stopping workers:

- identify running jobs;
- allow safe jobs to finish;
- mark interrupted jobs for retry/recovery;
- preserve heartbeat and attempt history;
- avoid acknowledging a job before its durable result is committed.

### 13.6 Run migration

Run the approved migration command with the migration role.

### 13.7 Deploy approved images

```bash
docker compose --env-file /etc/gold-platform/release.env \
  -f compose.production.yml up -d --no-build
```

The host should not build unreviewed production images.

### 13.8 Verify readiness

- all required containers healthy;
- `/live` passes;
- `/ready` passes;
- schema revision correct;
- storage available;
- outbox dispatcher active;
- worker heartbeats current;
- no unexpected 5xx increase;
- no permission or session regression.

### 13.9 Run safe smoke tests

Use the production-safe checklist in Section 11.12.

### 13.10 Resume queues and writes

Resume queues in a controlled order:

1. outbox/notifications;
2. file workers;
3. export workers;
4. maintenance/report workers;
5. optional AI workers only if separately approved.

Disable maintenance/write restriction only after verification.

### 13.11 Observe release

Monitor for the agreed observation window:

- API errors and latency;
- login/session failures;
- queue age;
- outbox age;
- file failures;
- export integrity alerts;
- database locks/connections;
- storage growth;
- audit insertion failures.

### 13.12 Close release

The release record must include:

- actual start/end time;
- deployed digests;
- migration revision;
- backup set ID;
- smoke-test result;
- alerts observed;
- deviations;
- approver;
- follow-up tasks.

---

## 14. Rollback, Forward Fix, and Database Restore

These are three different decisions.

### 14.1 Application rollback

Use when:

- previous application image remains compatible with the current schema;
- no unsafe business-state mutation requires reconciliation;
- rollback is faster and safer than forward fix.

Deploy the previous approved digests without rebuilding.

### 14.2 Forward fix

Prefer a forward fix when:

- schema downgrade is unsafe;
- the issue is localized;
- business records have already been created under the new release;
- restoration would lose valid post-backup actions.

### 14.3 Database restore

Database restore is a major financial incident, not a routine rollback.

Before restore, determine:

- transactions recorded after the selected recovery point;
- exports generated or downloaded;
- exports actually submitted to a bank;
- results confirmed or published;
- external bank actions not represented in the restore point;
- files uploaded after the restore point;
- idempotency/outbox events that may replay;
- legal-hold implications.

### 14.4 Emergency stop condition

If system behavior may create duplicate bank submission, unauthorized approval, wrong trader publication, or data corruption:

1. enable write barrier;
2. disable affected command or integration with a kill switch;
3. preserve evidence;
4. notify the incident owner;
5. reconcile external actions before resuming.

---

## 15. Maintenance and Write-Barrier Mode

### 15.1 Required behavior

Maintenance mode must be enforced by backend command guards.

Possible modes:

```text
normal
read_only
financial_writes_blocked
full_maintenance
```

At minimum, a financial write barrier must block:

- request submission;
- request correction submission;
- batch finalization;
- manager approval;
- final export generation;
- mark as sent;
- payment result confirmation;
- evidence replacement;
- publication;
- gold dispatch;
- retention deletion.

### 15.2 Allowed operations during maintenance

Depending on mode:

- health checks;
- authorized read-only access;
- backup and restore operations;
- incident review;
- controlled migration command;
- break-glass action when explicitly activated.

### 15.3 Maintenance audit

Enabling or disabling maintenance mode is a security-sensitive audited action.

Record:

- actor;
- reason;
- mode;
- start time;
- expected end time;
- incident/change reference;
- actual end time.

---

## 16. File Storage and Processing Operations

### 16.1 File lifecycle

```text
pending
→ quarantined or available
→ archived or retention_pending
→ deleted only through governed execution

processing failure may produce:
processing_failed
```

### 16.2 File categories

- bank statement import;
- bank export preview;
- final bank export;
- bank result bundle original;
- manual evidence;
- receipt segment crop;
- trader attachment;
- publication/share artifact;
- audit/report export;
- temporary processing derivative.

### 16.3 Required metadata

- original filename;
- normalized safe filename;
- MIME type;
- extension;
- magic/signature result;
- size;
- SHA-256 checksum;
- category;
- lifecycle state;
- storage backend and key;
- source file for derivatives;
- renderer/parser version;
- actor and timestamps;
- retention/legal-hold state.

### 16.4 Manual crop operations

Phase 1A must support:

- authorized source file and page;
- normalized `x`, `y`, `width`, `height` in `[0,1]`;
- rotation;
- source dimensions;
- renderer name/version;
- output checksum;
- privacy-review state;
- retry after technical failure;
- immutable original source.

A crop render failure must not create an active evidence link.

### 16.5 Storage reconciliation

Scheduled reconciliation detects:

- file object without database record;
- database record without object;
- stale pending upload;
- derivative without source;
- checksum mismatch;
- object in wrong lifecycle path;
- processing job stuck;
- duplicate write after retry.

Reconciliation creates review tasks. It must not automatically delete financial evidence.

### 16.6 Storage outage

When storage is unavailable:

- block new uploads and generated artifacts;
- do not mark export generation successful;
- do not create evidence/publication links to missing files;
- keep metadata and job state consistent;
- preserve retry capability;
- alert operations;
- consider a financial write barrier if essential workflows cannot remain safe.

---

## 17. Backup Strategy and Consistency Manifest

### 17.1 Backup scope

A complete backup set includes:

- PostgreSQL database;
- original uploaded files;
- derived evidence and crop files;
- final and preview bank exports where retention requires them;
- bank result bundles;
- publication/share artifacts;
- audit and security records;
- release manifest and image digests;
- Alembic revision;
- non-secret configuration metadata;
- backup consistency manifest.

Redis is not the authoritative backup source.

### 17.2 Backup destination

At least one encrypted backup copy must be outside the production server and outside the same failure domain.

A local staging copy is acceptable only as an intermediate step.

### 17.3 Backup set ID

Use a unique backup set ID:

```text
backup-YYYYMMDDTHHMMSSZ-<short-random-id>
```

### 17.4 Consistency manifest

Example:

```json
{
  "backup_set_id": "backup-...",
  "started_at": "...Z",
  "completed_at": "...Z",
  "application_release_id": "...",
  "alembic_revision": "...",
  "database": {
    "filename": "database.dump",
    "sha256": "...",
    "size_bytes": 0
  },
  "storage": {
    "snapshot_or_archive": "storage.tar.zst",
    "sha256": "...",
    "file_count": 0,
    "total_bytes": 0
  },
  "verification": {
    "database_dump_verified": true,
    "storage_checksums_verified": true,
    "offsite_copy_verified": true
  }
}
```

### 17.5 Backup command template

The implementation repository should provide reviewed scripts rather than ad-hoc shell commands.

A database backup script must:

- run with the backup role;
- fail on errors;
- write to a new backup-set directory;
- calculate checksum;
- avoid embedding credentials in command history;
- upload/copy to the separate destination;
- verify remote object existence and checksum;
- emit a monitored success/failure event.

A file backup must preserve relative paths or object keys and metadata needed for restoration.

### 17.6 Schedule and retention

Backup frequency is derived from approved RPO and operational volume.

Retention is derived from business, legal, and recovery requirements.

Do not treat values such as `30 days` or `5 years` as automatically approved production policy.

### 17.7 Backup monitoring

Alert immediately on:

- missed schedule;
- command failure;
- checksum failure;
- offsite transfer failure;
- unusual backup-size change;
- insufficient destination capacity;
- manifest creation failure.

### 17.8 Restore testing

A backup is not accepted until restored and validated.

Restore drills must occur at the approved cadence and after material changes to:

- database version;
- storage adapter;
- encryption method;
- backup tooling;
- deployment topology;
- file lifecycle.

---

## 18. Restore Runbook

### 18.1 Restore authorization

A production restore requires:

- incident/change reference;
- selected backup set ID;
- recovery-point approval;
- expected data-loss statement;
- business reconciliation owner;
- operations owner;
- security owner when relevant;
- rollback/abort criteria.

### 18.2 Restore to isolated environment first

Before a production restore, restore the selected set to an isolated environment whenever time and incident severity allow.

Validate:

- database dump;
- storage archive/snapshot;
- manifest checksums;
- schema revision;
- application compatibility;
- login and permissions;
- representative financial records and files.

### 18.3 Production restore sequence

1. enable full maintenance/write barrier;
2. stop API writes and affected workers;
3. capture current failed-state evidence and, if possible, a final forensic backup;
4. provision clean database/storage targets or move current targets aside;
5. restore PostgreSQL;
6. restore file storage from the same backup set;
7. verify checksums and counts;
8. deploy the release compatible with the restored schema;
9. run only approved migrations required for compatibility;
10. start API in restricted mode;
11. validate consistency;
12. reconcile external bank actions after the recovery point;
13. resume workers carefully;
14. disable maintenance only after business and technical approval.

### 18.4 Restore validation matrix

Verify:

- users, sessions, and RBAC;
- trader isolation;
- payment requests and immutable revisions;
- attempts and aggregates;
- batch versions, ordered items, and hashes;
- manager approvals;
- final exports and checksums;
- sent-export history;
- bank result bundles;
- manual crop provenance;
- confirmed evidence links;
- payment results;
- publication versions;
- audit and security events;
- outbox and idempotency records;
- storage/database reference consistency;
- legal holds.

### 18.5 Post-restore idempotency and outbox review

Before normal operation:

- identify pending outbox events;
- prevent duplicate external notifications or submissions;
- inspect idempotency records around the incident window;
- reconcile any bank action performed after the recovery point;
- document events intentionally suppressed or replayed.

---

## 19. Celery, Outbox, and Queue Operations

### 19.1 Logical queues

```text
files
exports
notifications
reports
maintenance
ai  # disabled unless approved
```

### 19.2 Durable job state

Important processing jobs are recorded in PostgreSQL with:

- logical job ID;
- entity ID;
- operation;
- idempotency identity;
- status;
- attempt history;
- heartbeat;
- worker identity;
- error code;
- timestamps;
- result artifact reference.

### 19.3 Outbox dispatcher

Monitor:

- oldest unpublished event age;
- pending count;
- failure count;
- repeated-delivery count;
- last successful dispatch.

Outbox processing must be idempotent.

### 19.4 Worker restart

Before restart:

1. identify current tasks;
2. determine acknowledgement behavior;
3. allow graceful completion when safe;
4. stop with configured grace period;
5. restart;
6. verify heartbeat;
7. inspect jobs left in `running` state;
8. recover stale jobs according to policy.

### 19.5 Stuck job response

- inspect durable job state and logs;
- check source entity current state;
- verify artifact existence/checksum;
- distinguish transient from permanent error;
- do not manually set a financial result to compensate for a worker error;
- retry using the same logical operation identity where appropriate;
- create manual review task when automated recovery is unsafe.

### 19.6 AI queue

The AI queue remains disabled in Phase 1A unless separately approved.

Enabling it requires provider, privacy, cost, evaluation, shadow-mode, and kill-switch approval.

---

## 20. Monitoring and Alerting

### 20.1 Host metrics

- CPU;
- memory;
- disk usage and growth forecast;
- inode usage;
- network errors;
- time synchronization;
- certificate expiry.

### 20.2 Service metrics

- API availability, latency, and 5xx rate;
- frontend availability;
- database connections, locks, replication/backup status if applicable;
- Redis availability;
- queue depth and oldest task;
- worker heartbeat;
- outbox age;
- job failures;
- storage read/write errors;
- file quarantine count;
- checksum mismatches;
- backup and restore status.

### 20.3 Security metrics

- login failures;
- session revocations;
- permission denials;
- cross-trader access attempts;
- CSRF failures;
- recent-auth failures;
- break-glass use;
- secret-rotation failures;
- unusual secure-download denial spikes.

### 20.4 Financial-integrity metrics

- stale approval attempts;
- approval hash mismatches;
- export integrity mismatches;
- quarantined final exports;
- duplicate idempotency conflicts;
- overpayment reconciliation tasks;
- unresolved sent-status uncertainty;
- publication correction count.

Metrics must not use full IBAN, beneficiary name, phone number, or other sensitive data as labels.

### 20.5 Alert ownership

Every alert must define:

- severity;
- recipient/rotation;
- response time;
- escalation path;
- linked runbook;
- auto-resolution rule;
- last test date.

---

## 21. Logging and Audit Operations

### 21.1 Structured logs

Production application logs should be structured JSON and include:

- timestamp;
- service;
- release ID;
- level;
- request/correlation ID;
- actor ID where appropriate;
- operation;
- entity type and opaque ID;
- duration;
- safe error code.

### 21.2 Prohibited log content

Do not log:

- passwords;
- session tokens;
- CSRF secrets;
- private keys;
- AI keys;
- database credentials;
- raw idempotency keys;
- full sensitive request payloads;
- complete IBAN/account numbers unless specifically approved and protected;
- file contents;
- raw provider payloads by default;
- signed download URLs.

### 21.3 Audit immutability

Application runtime roles must not update or delete audit records.

Audit insertion failure for a sensitive command must fail the command transaction.

### 21.4 Log retention

Log retention is separate from business audit retention.

It must be approved based on:

- incident investigation needs;
- privacy minimization;
- storage cost;
- legal requirements;
- access controls.

---

## 22. Security Operations and Break-Glass Access

### 22.1 Routine access

- named accounts only;
- least privilege;
- separate technical and financial roles;
- periodic access review;
- immediate revocation on role change or departure;
- session revocation support.

### 22.2 Break-glass access

Break-glass is disabled by default.

Activation requires:

- incident reference;
- named approver;
- limited scope;
- short expiry;
- recent/strong authentication;
- immediate alert;
- full audit;
- post-use review.

Break-glass must not become a normal method for approving payments or bypassing separation of duties.

### 22.3 Security incident preservation

When unauthorized access or data exposure is suspected:

- revoke affected sessions;
- restrict accounts;
- preserve logs and audit data;
- quarantine affected files/exports if needed;
- avoid destructive cleanup;
- apply legal hold when required;
- record timeline and scope;
- notify the approved incident owner.

---

## 23. Incident Runbooks

### 23.1 Export integrity mismatch

Symptoms:

- export checksum differs;
- version/hash/approval mismatch;
- row count or total mismatch;
- mapping/source account mismatch.

Actions:

1. quarantine the export;
2. block download and mark-as-sent;
3. preserve artifact and logs;
4. create urgent review task;
5. determine whether the file was externally submitted;
6. reconcile bank-side state;
7. generate a replacement only through the governed command;
8. document root cause.

### 23.2 Uncertain bank submission state

Example: operator submitted a file but the application did not record `sent`, or the API timed out after a future bank submission.

Actions:

1. do not generate or submit a replacement automatically;
2. place the batch/export in reconciliation review;
3. inspect bank portal/provider receipt;
4. record evidence of actual submission;
5. use a controlled correction command;
6. preserve idempotency and audit history.

### 23.3 Wrong evidence or result published

1. do not delete the old evidence/publication;
2. block further sharing if privacy risk exists;
3. open sensitive correction workflow;
4. apply required dual control;
5. replace/revoke evidence link;
6. recalculate result aggregates;
7. create publication `N+1`;
8. supersede or revoke old publication;
9. notify the affected trader under approved policy;
10. investigate cross-trader exposure.

### 23.4 Cross-trader data exposure

Treat as a critical security incident.

- revoke exposed links/sessions;
- block the affected route/file;
- preserve access logs;
- identify records and users affected;
- apply legal hold;
- notify security/business owner;
- remediate authorization logic;
- run regression tests before reopening.

### 23.5 PostgreSQL unavailable

- enable financial write barrier;
- inspect host, disk, process, and connection state;
- do not repeatedly restart without diagnosis;
- verify data directory and permissions;
- fail over only if an approved topology exists;
- restore only after recovery-point approval.

### 23.6 Redis unavailable

- core PostgreSQL records remain authoritative;
- block or degrade asynchronous operations safely;
- do not assume queued messages remain available;
- inspect outbox for undispatched events;
- restore broker and replay through idempotent dispatcher;
- verify no duplicate external side effects.

### 23.7 Storage unavailable or full

- block upload/export/crop/publication artifact creation;
- enable write barrier if operations cannot remain safe;
- stop nonessential rendering;
- expand or restore storage;
- run storage reconciliation;
- verify checksums before resuming.

### 23.8 Worker or outbox stuck

- inspect heartbeat and oldest event/job;
- confirm database connectivity;
- inspect lock and retry state;
- restart gracefully;
- recover stale jobs;
- avoid direct status edits;
- verify idempotent replay.

### 23.9 Backup failure

- alert immediately;
- identify whether database, storage, encryption, or transfer failed;
- preserve the last known valid backup;
- retry only after capacity/credential/root-cause check;
- escalate if RPO is at risk;
- record failure and recovery evidence.

### 23.10 Malware or malicious upload

- keep file quarantined;
- do not render or expose it;
- block dependent evidence/publication actions;
- preserve metadata and scan result;
- notify security;
- review uploader/session;
- follow approved deletion/legal-hold policy.

### 23.11 Secret exposure

Use Section 7.6 and review all dependent sessions, integrations, backup access, and signed URLs.

### 23.12 AI provider outage

When AI is enabled in a later phase:

- disable affected provider/use case;
- preserve manual workflow;
- stop cost-generating retry loops;
- route work to manual review;
- do not change financial status.

---

## 24. Retention and Legal Hold Operations

### 24.1 Retention workflow

```text
proposal
→ business/legal review
→ approval
→ legal-hold check
→ dry run
→ backup-impact review
→ activation
→ separate deletion execution
→ audit report
```

### 24.2 Dry run

A retention dry run must report:

- records/files in scope;
- categories;
- age/rule;
- references from active financial records;
- legal-hold exclusions;
- estimated storage recovered;
- unexpected dependencies.

### 24.3 Deletion execution

Deletion runs separately from policy approval.

It must:

- re-check legal holds;
- use bounded batches;
- be resumable;
- record each result;
- stop on integrity error;
- never delete referenced active evidence;
- produce a signed/approved execution report as required.

### 24.4 Legal hold

A legal hold has:

- scope;
- reason;
- authority;
- start date;
- review date;
- release authority;
- audit history.

It blocks deletion for matching records and files.

---

## 25. Initial Production Data and Configuration

### 25.1 Required reference data

- center profile;
- roles;
- permissions;
- role-permission assignments;
- file categories;
- approved system defaults;
- business timezone;
- approved bank profile versions;
- approved source accounts;
- approved bank mapping/template versions;
- approved splitting rules.

### 25.2 Bank activation checklist

A bank configuration is active only after:

- sample template imported;
- required headers validated;
- amount unit confirmed;
- leading-zero identifiers tested;
- date/time format confirmed;
- large integer amount tested;
- formula-injection handling tested;
- deterministic export tested;
- reopen-and-compare test passed;
- business owner approved;
- version/hash recorded.

### 25.3 No guessed production data

Do not seed placeholder banks, accounts, credentials, mappings, or limits as active production data.

---

## 26. Production Acceptance Gate

Production is not accepted until the following evidence exists.

### 26.1 Deployment

- approved immutable image digests;
- two frontend services deployed separately;
- only Nginx publicly exposed;
- PostgreSQL/Redis/private storage not public;
- containers run non-root where supported;
- health checks pass;
- release ID and schema revision match manifest.

### 26.2 Security

- authentication/session ADR implemented;
- RBAC and trader isolation tested;
- separation of duties tested;
- manager recent-authentication implemented as approved;
- file authorization tested;
- audit append-only restrictions tested;
- secrets stored outside source and frontend;
- break-glass disabled or governed;
- TLS active;
- firewall reviewed.

### 26.3 Financial integrity

- immutable request revisions work;
- immutable batch versions work;
- exact manager approval works;
- stale/hash-mismatch approval is blocked;
- final export integrity checks pass;
- preview cannot be marked sent;
- exact export mark-as-sent works;
- idempotency replay works;
- optimistic concurrency works;
- overpayment is blocked and reconciled;
- candidate/evidence/result/publication boundaries are enforced.

### 26.4 Files and manual result processing

- upload lifecycle works;
- quarantine works;
- PDF/image preview works;
- manual rectangular crop works;
- crop provenance and checksum work;
- privacy review works;
- trader cannot access mixed bundles;
- publication serves only approved evidence;
- storage reconciliation works.

### 26.5 Operations

- monitoring and alert owners assigned;
- outbox/worker monitoring active;
- off-server encrypted backup succeeds;
- consistency manifest created;
- full restore drill succeeds;
- runbooks tested;
- maintenance/write barrier works;
- release and rollback drill performed;
- incident escalation contacts available.

### 26.6 Phase boundary

- AI/OCR disabled by default;
- bank API disabled;
- multi-company behavior absent;
- core workflow works without optional providers.

---

## 27. Coding-Agent and Operator Prohibitions

Do not:

1. use `latest` image tags in production;
2. rebuild production images after staging approval;
3. expose PostgreSQL, Redis, backend, workers, or storage administration publicly;
4. share one secret file with all services without need;
5. put backend secrets into frontend environment variables;
6. use a single combined frontend for Trader and Admin as the production baseline;
7. run `docker compose down -v` as a routine operation;
8. use unnamed or untracked production volumes for business files;
9. run migrations with the normal application role;
10. assume database downgrade is a safe rollback;
11. restore the database without restoring and reconciling files;
12. restore without evaluating bank actions after the recovery point;
13. use a database-only backup as a complete backup;
14. retain backups only on the production host;
15. hard-code retention periods without approval;
16. seed placeholder bank mappings as active production configuration;
17. make Manual Crop optional in Phase 1A;
18. enable AI/OCR by default;
19. allow a worker to approve, confirm, or publish financial outcomes;
20. expose raw storage paths or permanent public URLs;
21. mark an export sent merely because it was downloaded;
22. generate a final export from a mutable or unapproved batch;
23. bypass hash/version integrity on approval or export;
24. edit audit history;
25. delete financial evidence through generic administration;
26. execute retention while a legal hold applies;
27. perform real financial smoke tests in production without explicit approval;
28. retry an uncertain bank submission as a new logical operation;
29. hide incidents by directly editing statuses;
30. claim production readiness without a successful restore drill.

---

## 28. Required Repository Operations Structure

```text
ops/
  compose/
    compose.local.yml
    compose.staging.yml
    compose.production.yml
  nginx/
    nginx.conf
    conf.d/
  redis/
    redis.conf
  scripts/
    validate-release.sh
    deploy-production.sh
    backup-create.sh
    backup-verify.sh
    restore-isolated.sh
    restore-production.sh
    check-health.sh
    drain-workers.sh
    resume-workers.sh
    storage-reconcile.sh
    retention-dry-run.sh
  runbooks/
    first-install.md
    deploy-production.md
    migration-failed.md
    rollback-or-forward-fix.md
    restore-database-and-files.md
    backup-failed.md
    worker-or-outbox-stuck.md
    database-unavailable.md
    redis-unavailable.md
    storage-unavailable.md
    disk-space-low.md
    export-integrity-mismatch.md
    uncertain-bank-submission.md
    wrong-result-or-evidence.md
    cross-trader-data-exposure.md
    malware-upload.md
    rotate-secrets.md
    break-glass-access.md
    retention-and-legal-hold.md
  monitoring/
    alerts/
    dashboards/
  manifests/
    release-manifest.schema.json
    backup-manifest.schema.json
```

Each runbook must state:

- purpose;
- trigger;
- severity;
- owner;
- required access;
- prerequisites;
- exact steps;
- stop conditions;
- verification;
- rollback/escalation;
- evidence to retain;
- last-tested date.

---

## 29. Open Production Decisions

Before launch, resolve or explicitly classify:

1. hosting provider, region, and access restrictions;
2. supported host OS and patch policy;
3. production storage adapter;
4. disk-encryption requirements;
5. authentication/session mode;
6. manager MFA/recent-authentication method and timeout;
7. separation-of-duty assignments;
8. RPO and RTO;
9. backup destination, encryption, schedule, and retention;
10. legal-hold and retention authorities;
11. malware scanner and quarantine behavior;
12. file-size and bundle limits;
13. expected daily/peak transaction and file volume;
14. monitoring platform and alert owners;
15. log and audit retention;
16. initial banks, source accounts, units, templates, and mappings;
17. business timezone and bank date rules;
18. text-only confirmation policy;
19. paid-result correction dual-control policy;
20. IBAN masking;
21. production support hours and incident escalation;
22. release approval authority;
23. certificate ownership and renewal;
24. external AI policy, if later enabled.

---

## 30. Final Operational Statement

The production environment is acceptable only when it preserves the same controls defined by the product and domain model:

```text
Exact financial authority
+ immutable history
+ private evidence
+ deterministic exports
+ recoverable database/file state
+ manual operational continuity
```

Operational convenience must never bypass manager approval, exact-version integrity, audit, trader isolation, evidence privacy, or recovery controls.
