# M0 Governance and Contract Readiness

Status: IN PROGRESS — twelve decisions approved; **all five Critical conflicts are now
resolved**; M0 exit gate not yet satisfied
Last reviewed: 2026-08-01
Authority: subordinate to the authoritative implementation documents in Implementation Docs

## Purpose

This file is the operational checklist for Milestone M0. It records what is already
controlled, what is provisional, and what must be approved before financial schema,
API, or workflow implementation starts.

## Current decision

- Repository scaffolding may start using the approved `services/backend` plus `infra` layout and PostgreSQL 16 baseline.
- The approved audit, recent-auth context, active-allocation, and export job/artifact designs may enter detailed schema/API/test work; milestone implementation still requires their recorded evidence gates.
- **Changed 2026-08-01.** The status and permission catalogues are approved and all
  five Critical conflicts are closed, so financial schema, enums, commands and
  generated clients may now be built *against those approved names*. What still
  blocks a given piece of work is a specific Open decision it depends on, not the
  catalogues: production hosting, storage, backup, retention, the manager
  recent-auth factor (ADR-009), IBAN masking (POL-003) and bank profiles
  (ADR-007) are all still Open, and each blocks the work that needs it.
- Two limits survive the catalogue approval. The approved names are frozen, but
  their *use* is not evidenced yet, so any schema or client that consumes them
  still owes the implementation evidence its milestone requires. And no real
  trader, bank, payment or production credential data may be used at all.
- AI/OCR, bank APIs, Android/Windows packaging, chat, and multi-company behavior remain disabled/out of scope.

## M0 artifacts

| Artifact | State | Approval needed |
|---|---|---|
| ADR index and alias mapping | 33 canonical rows: ADR-006, POL-005 and POL-002 Approved; 30 Open. Alias namespace resolved 2026-08-01; no `needs_mapping` blocks Phase 1A | Remaining decision owners |
| Conflict register | 33 total: 12 Resolved/Approved; 21 Open (**0 Critical**) | Topic owners for remaining conflicts; implementation evidence for resolved decisions |
| Document approval register | Drafted | Project owner |
| Status catalogue | **Approved 2026-08-01**: 23 aggregates / 156 states; document 06 names canonical, PRD spellings are legacy aliases | Implementation evidence that DB, API, backend, frontend and QA use these values |
| Permission catalogue | **Approved 2026-08-01**: 118 permissions / 24 API aliases; document 12 identifiers canonical, document 05 spellings deprecated aliases | Generation evidence into seed, OpenAPI and frontend constants |
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
- [x] Documents 00, 01, and 02 have explicit project-owner sign-off — recorded
  2026-08-01; scoped to establishing the baseline, not to pre-approving any
  individual financial contract (DOC-CONFLICT-004).
- [ ] Document 09 is explicitly accepted only as optional/future AI authority.
- [x] ADR/POL/OPS/PKG and ADR-SEC/ADR-OPS aliases map to one canonical register —
  resolved 2026-08-01 (DOC-CONFLICT-003). `Open_ADR_Register` IDs are the only
  canonical namespace; mapping is semantic, never numeric.
- [x] All critical conflicts have an owner and resolution record — all five closed
  2026-08-01. Resolution records carry the approval identity; per-decision
  implementation evidence is still owed at the milestones each names.

### Contracts

- [ ] Canonical status catalogue is approved and used by DB, API, backend, frontend, and QA
  — **approved 2026-08-01**; the "used by" half stays open until implementation
  evidence exists, since nothing consumes these values yet.
- [ ] Canonical permission catalogue is approved and generated into seed/OpenAPI/frontend constants
  — **approved 2026-08-01**; generation into seed, OpenAPI and frontend constants
  is still owed.
- [ ] Error codes and response envelope are frozen.
- [ ] Critical command catalogue defines permission, ownership, idempotency, concurrency, audit, and outbox behavior.
- [x] Money serialization and IRR/Toman provenance are approved — `MONEY_TIME_CONTRACT.md`.
- [x] Platform timezone/calendar boundary is approved — ADR-006; `Asia/Tehran` business rules with UTC/Gregorian canonical storage/transport. Screen-specific input and bank-holiday details remain follow-up work.
- [ ] Payment-attempt result correction has an immutable persistence model — the
  *authority* is decided (POL-002, manager or dual control, 2026-08-01), but the
  persistence model itself is still open and is what this gate asks for.
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

Approval date: 2026-07-20, extended 2026-08-01
Approval evidence: workspace owner approval via conversation; legal name/organizational role not supplied

The 2026-08-01 session added five approvals, recorded by the project owner Ehsan
Shams on their instruction under the same convention: the status catalogue
(DOC-CONFLICT-001), the permission catalogue (DOC-CONFLICT-013), the product and
domain baseline sign-off (DOC-CONFLICT-004), correction authority POL-002
(DOC-CONFLICT-002), and the ADR alias namespace (DOC-CONFLICT-003). With those,
no Critical conflict remains open. The two catalogues are now approved rather
than provisional, so the sentence below about machine-readable catalogues no
longer applies to them; it still applies to every catalogue that remains drafted.

This evidence approves only the checked decisions and their cited baselines. It is not a
blanket approval of M0, the full source-document package, any machine-readable catalogue,
production release, or implementation acceptance. The unchecked gates and the 21 Open
conflicts remain blocking where applicable.

## Primary sources

- Implementation Docs/00_Start_Here/Implementation_Kickoff_Checklist.md
- Implementation Docs/00_Start_Here/Open_ADR_Register.md
- Implementation Docs/00_Start_Here/15_Agent_Implementation_Plan.md
- Implementation Docs/00_Start_Here/16_Implementation_Documentation_Index.md
