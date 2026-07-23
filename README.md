# Gold Trade Settlement Platform

Status: M1 transfer candidate, not yet accepted. Financial workflows and financial
database migrations are intentionally not implemented yet. The system-to-system
handoff and remaining acceptance gates are documented in
[`docs/handoff/M1_TRANSFER_HANDOFF_FA.md`](docs/handoff/M1_TRANSFER_HANDOFF_FA.md).

This monorepo contains two independently deployable Persian web applications, one
FastAPI modular monolith, shared frontend packages, and a Docker Compose pilot
baseline. PostgreSQL is authoritative; Redis and Celery are never the only store of a
business fact.

## Repository map

```text
apps/trader-pwa       Trader-facing PWA
apps/admin-web        Internal operations application
services/backend      FastAPI API and worker runtime
packages              Shared API/UI/config primitives
infra                 Compose, Docker, Nginx, and verification scripts
docs                   ADR and governance controls
tests                  Cross-application contract, E2E, and security tests
```

## M1 reproducible local baseline

- Python 3.12.13 and FastAPI/Pydantic v2
- PostgreSQL 16.14
- Redis 7.4.9 as a non-authoritative broker/support store
- Node.js 24.18 LTS, pnpm workspace, and Next.js App Router
- Nginx 1.30.4 stable as the only local/pilot ingress
- integer IRR money, UTC persistence, and `Asia/Tehran` business time

The repository layout, PostgreSQL 16, money/time rules, and business timezone are
approved M0 decisions. Python, Node, Redis, and Nginx patch pins are reproducible M1
implementation inputs and remain subject to the release maintenance policy. Production
images must be promoted by immutable digest; local tags are not production approval.

## Local stack

Prerequisites are Docker Engine with Compose v2. Copy `.env.example` to `.env`, keep
the values local-only, then run:

```bash
docker compose --env-file .env -f infra/compose/compose.local.yml up --build
```

Expected ingress endpoints:

- Trader: `http://trader.localhost:8080`
- Admin: `http://admin.localhost:8080`
- API liveness: `http://trader.localhost:8080/api/v1/health/live`

PostgreSQL, Redis, backend, workers, and frontend container ports are not published to
the host. Only Nginx publishes port 8080 in the local model.

Stop without deleting data:

```bash
docker compose --env-file .env -f infra/compose/compose.local.yml down
```

Do not add `-v` unless destruction of local database data is explicitly intended.

## Native development

Frontend commands run from the repository root:

```bash
pnpm install --frozen-lockfile
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm --filter @gold/trader-pwa exec playwright install chromium
pnpm test:a11y
```

Backend commands and environment setup are documented in `services/backend/README.md`.
The backend requires Python 3.12.x; CI and container builds use the exact repository
baseline in `.python-version`.

The FastAPI contract is committed at `services/backend/openapi/v1.json`, with
generated TypeScript types under `packages/api-client/src/generated`. After a route
or response-schema change, run `pnpm openapi:generate`, review both artifacts, and
run `pnpm openapi:check`.

Provider-neutral verification entry points are:

```powershell
powershell -File infra/scripts/verify-native.ps1
powershell -File infra/scripts/verify-docker.ps1
```

Equivalent POSIX scripts use the same names with `.sh`. Docker acceptance must be
repeated from a clean clone on the target system before M1 can be marked accepted.

## Safety boundary

M1 supplies runtime shells only. It must not be used for real trader data, real bank
files, real payments, or production credentials. Financial schema/API work begins only
after the relevant M2+ contracts and remaining governance conflicts are resolved.
