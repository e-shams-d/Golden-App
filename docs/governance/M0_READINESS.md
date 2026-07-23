# M0 Governance and Contract Readiness

Status: IN PROGRESS — seven decisions approved; M0 exit gate not yet satisfied
Last reviewed: 2026-07-20
Authority: subordinate to the authoritative implementation documents in Implementation Docs

## Purpose

This file is the operational checklist for Milestone M0. It records what is already
controlled, what is provisional, and what must be approved before financial schema,
API, or workflow implementation starts.

## Current decision

- Repository scaffolding may start using the approved `services/backend` plus `infra` layout and PostgreSQL 16 baseline.
- The approved audit, recent-auth context, active-allocation, and export job/artifact designs may enter detailed schema/API/test work; milestone implementation still requires their recorded evidence gates.
- Financial migrations, OpenAPI commands, generated clients, and financial UI flows that depend on any remaining Open conflict or unapproved catalogue remain blocked.
- AI/OCR, bank APIs, Android/Windows packaging, chat, and multi-company behavior remain disabled/out of scope.

## M0 artifacts

| Artifact | State | Approval needed |
|---|---|---|
| ADR index and alias mapping | 33 canonical rows: ADR-006 and POL-005 Approved; 31 Open | Remaining decision owners; alias governance still open |
| Conflict register | 33 total: 7 Resolved/Approved; 26 Open (5 Critical) | Topic owners for remaining conflicts; implementation evidence for resolved decisions |
| Document approval register | Drafted | Project owner |
| Status catalogue | Drafted: 23 aggregates / 156 states | Domain, backend, frontend, QA |
| Permission catalogue | Drafted: 118 permissions / 24 API aliases | Security and business owner |
| API error catalogue | Drafted: 25 codes | Backend, frontend, QA |
| Command catalogue | Drafted: 52 critical commands; remaining groups listed | Domain, security, backend |
| Audit/outbox catalogue | Drafted: 57 audit actions / 11 outbox events | Security, backend, operations |
| Money/time contract | Approved: integer IRR, UTC persistence/transport, `Asia/Tehran` business timezone | Implementation and QA evidence; remaining bank/screen policy details |
| Repository baseline | Approved: `services/backend` + `infra`; PostgreSQL 16 | Remaining lock/tool/provider/topology choices and implementation evidence |
| Financial integrity baseline | Approved: separate export job/artifact, DB active allocation, bound recent-auth context, explicit/versioned audit, mandatory SoD with break-glass disabled | Schema/API/security/QA evidence at M2/M3/M6/M7/M12 |
| OpenAPI generation strategy | Pending | Technical lead |
| Alembic naming/forward-fix policy | Pending | Database owner |
| Branch/CODEOWNERS/release policy | Pending | Technical lead and release owner |
| Traceability matrix | Drafted: M0-M13 and six required flows | QA and technical lead |
| M0 file manifest and checksums | Drafted after structural validation | Documentation owner and technical lead |

## Blocking gates

### Governance

- [ ] Named owner and due date exist for every Phase 1A blocking decision.
- [ ] Documents 00, 01, and 02 have explicit project-owner sign-off.
- [ ] Document 09 is explicitly accepted only as optional/future AI authority.
- [ ] ADR/POL/OPS/PKG and ADR-SEC/ADR-OPS aliases map to one canonical register.
- [ ] All critical conflicts have an owner and resolution record.

### Contracts

- [ ] Canonical status catalogue is approved and used by DB, API, backend, frontend, and QA.
- [ ] Canonical permission catalogue is approved and generated into seed/OpenAPI/frontend constants.
- [ ] Error codes and response envelope are frozen.
- [ ] Critical command catalogue defines permission, ownership, idempotency, concurrency, audit, and outbox behavior.
- [x] Money serialization and IRR/Toman provenance are approved — `MONEY_TIME_CONTRACT.md`.
- [x] Platform timezone/calendar boundary is approved — ADR-006; `Asia/Tehran` business rules with UTC/Gregorian canonical storage/transport. Screen-specific input and bank-holiday details remain follow-up work.
- [ ] Payment-attempt result correction has an immutable persistence model.
- [x] Recent-auth has an explicit actor-, session-, action/purpose-, and resource-bound persistence contract — `FINANCIAL_INTEGRITY_BASELINE.md` §3; factor/timeout remain ADR-009.
- [x] Active attempt allocation has a database-enforceable uniqueness design — `FINANCIAL_INTEGRITY_BASELINE.md` §2.
- [x] Async export persistence separates the durable job from the immutable final artifact — `FINANCIAL_INTEGRITY_BASELINE.md` §1.
- [x] Audit persistence uses required first-class columns plus typed versioned metadata — `FINANCIAL_INTEGRITY_BASELINE.md` §4.
- [x] Phase 1A outgoing-batch SoD requires `finalizer != approver`; break-glass is disabled — `FINANCIAL_INTEGRITY_BASELINE.md` §5.
- [ ] Crop coordinate-space version and rotation provenance are resolved.

### Delivery

- [x] Canonical monorepo layout is approved — `services/backend` plus `infra` in `REPOSITORY_BASELINE.md`.
- [x] PostgreSQL major version is approved — PostgreSQL 16 in every environment.
- [ ] Exact runtime/dependency versions and lockfile policies are approved.
- [ ] OpenAPI generation and compatibility checks are approved.
- [ ] Alembic naming, review, expand/contract, and forward-fix rules are approved.
- [ ] CI quality, security, and artifact-promotion gates are approved.

## Exit condition

M0 is complete only when the checklist above has recorded evidence, not merely verbal
agreement. Any unresolved choice must have an explicit safe default and a blocking
milestone. No unresolved choice may be silently embedded in financial code.

## Recorded decision approval

Approval date: 2026-07-20
Approval evidence: workspace owner approval via conversation; legal name/organizational role not supplied

This evidence approves only the checked decisions and their cited baselines. It is not a
blanket approval of M0, the full source-document package, any machine-readable catalogue,
production release, or implementation acceptance. The unchecked gates and all 26 Open
conflicts remain blocking where applicable.

## Primary sources

- Implementation Docs/00_Start_Here/Implementation_Kickoff_Checklist.md
- Implementation Docs/00_Start_Here/Open_ADR_Register.md
- Implementation Docs/00_Start_Here/15_Agent_Implementation_Plan.md
- Implementation Docs/00_Start_Here/16_Implementation_Documentation_Index.md
