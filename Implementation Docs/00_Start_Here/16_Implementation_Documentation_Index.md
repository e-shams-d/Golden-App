# Gold Trade Settlement Platform
# 16 — Implementation Documentation Index and Authority Registry

**Document ID:** `16_Implementation_Documentation_Index`  
**Version:** `1.1`  
**Revision Date:** `2026-07-18`  
**Status:** `Authoritative documentation-governance baseline`  
**Language:** English  
**Primary Audience:** Product owner, business owner, technical lead, security lead, backend and frontend engineers, DevOps, QA, release manager, coding agents, and future maintainers  
**Primary Purpose:** Define the canonical documentation set, version authority, topic ownership, dependency order, conflict-resolution process, ADR registry, and implementation-readiness state for the Gold Trade Settlement Platform.

---

## 1. Purpose and Authority of This Index

This document is the package-level registry for the Gold Trade Settlement Platform implementation documentation.

It does not replace the detailed product, domain, architecture, API, workflow, security, operations, or QA specifications. Its authority is limited to documentation governance, including:

- which files belong to the package;
- which version of each file is authoritative;
- which document owns each implementation topic;
- which documents are supporting, provisional, historical, or generated artifacts;
- the required reading order for each role;
- the dependency relationship between documents;
- how conflicts must be identified and resolved;
- which Architecture Decision Records remain open;
- which documents may be handed to a coding agent;
- which package state is safe for implementation, QA, UAT, pilot, or production use.

A coding agent or engineer must not use an older unsuffixed file when an approved `.md` file exists for the same document number.

A `.diff` file is review evidence only. It is never an implementation source of truth.

---

## 2. Package-Level Product Summary

The product is a standalone, Persian-first Gold Trade Settlement Platform for a single center/company in Phase 1A.

It replaces fragmented operational work performed through messaging applications, spreadsheets, manual bank portal activity, uncontrolled file sharing, and informal status communication.

The platform covers two related but distinct operational domains:

1. **Outgoing settlement:** a trader asks the center to pay one or more beneficiaries, the center reviews the request, creates exact bank execution attempts, prepares a versioned payment batch, obtains manager approval for the exact immutable version, generates a final bank export, records the exact export sent to the bank, reviews bank results, confirms evidence and payment outcomes, and publishes a safe immutable result to the trader.
2. **Gold sale and incoming settlement:** a trader requests gold from the center, the center prices the order, the trader provides incoming-payment information, the accountant verifies the incoming amount against bank evidence or statement data, and authorized staff dispatch and settle the physical or offset transaction.

The system is a financial-operations product, not an OCR tool, a chat application, a generic CRUD system, or a spreadsheet replica.

---

## 3. Non-Negotiable Package Baseline

The following decisions are fixed across the implementation package unless changed through an approved ADR and coordinated document revision.

### 3.1 Phase 1A operating model

- Phase 1A is a manual operational core.
- AI, OCR, bank APIs, SaaS tenancy, native applications, internal chat, and external messaging integrations are not required for core operation.
- Manual rectangular crop inside the authorized PDF/image preview is part of Phase 1A.
- Automatic segmentation is deferred.
- Human confirmation is required for financial decisions.
- Every outgoing Phase 1A payment batch requires manager approval.
- The manager approves the exact immutable current `PaymentBatchVersion`, not a mutable batch container or individual request.
- Material change invalidates operational use of the previous approval and requires a replacement version and new approval.

### 3.2 Financial data model

- Canonical money is stored as integer IRR.
- The original entered value and entered unit are retained.
- Toman conversion is exact multiplication or division by ten where valid.
- The system never infers the unit from the size of a number.
- Floating-point money is forbidden.
- Paid aggregation must be exact.
- Overpayment is a reconciliation exception, not a successful completion shortcut.

### 3.3 Traceability model

- Financial records are corrected, replaced, superseded, voided, or cancelled; they are not generically overwritten or hard-deleted.
- Request material changes create immutable `PaymentRequestRevision` records.
- Attempt retries and corrections preserve lineage.
- Evidence candidates are not confirmed evidence.
- Confirmed evidence is not the same as a paid confirmation.
- Paid confirmation is not the same as trader publication.
- Published trader results are immutable `PaymentResultPublication` versions.
- File originals and derived files remain separately traceable.

### 3.4 Security and consistency model

- Authorization is deny-by-default and enforced by the backend.
- Trader ownership is derived from authenticated context, never trusted from a client-supplied trader ID.
- Technical administration does not imply financial authority.
- Separation of duties applies to preparation and approval of outgoing batches.
- Critical commands require idempotency.
- Mutable aggregates require optimistic concurrency where defined.
- Transactional audit and outbox records are part of the same transaction as sensitive business changes.
- Files are private and accessed only through authorized routes or short-lived controlled URLs.
- Production backups require a separate destination and a tested restore procedure.

### 3.5 Product execution principle

> Preserve the business need and business logic, not the limitations or imitation of the current manual tool.

The system may reproduce required outcomes, controls, evidence, and accountability. It should not reproduce messaging threads, spreadsheet weaknesses, or uncontrolled manual practices as the product architecture.

---

## 4. Documentation Status Vocabulary

Every file in the package must use one of the following governance states.

| Status | Meaning | May drive implementation? |
|---|---|---:|
| `Authoritative` | Approved source of truth for its declared topic | Yes |
| `Supporting authoritative` | Approved implementation detail subordinate to higher-level topic owners | Yes |
| `Provisional pending alignment review` | Useful draft that has not yet been reconciled with the current v1.1 baseline | Only where it does not conflict |
| `Historical reference` | Preserves discovery or superseded decisions | No |
| `Review evidence` | Diff, checklist, report, or comparison artifact | No |
| `Generated contract/artifact` | OpenAPI, generated client, migration output, release manifest, or test report produced from authoritative sources | Yes, within its generated scope |
| `Deprecated` | Intentionally replaced and retained only for traceability | No |

The presence of a file in the repository does not by itself make that file authoritative.

---

## 5. Canonical Package Inventory

The full planning and implementation package contains files `00` through `23` inclusive.

### 5.1 Authoritative implementation and execution set

Documents `00` through `22` have completed individual v1.1 alignment review. Each is authoritative only for its declared topic and remains subordinate to the topic-precedence rules in this index.

| ID | Canonical authoritative file | Topic | Governance state |
|---:|---|---|---|
| 00 | `00_Master_Implementation_Blueprint.md` | Master product, phase, architecture, and fixed-decision baseline | Authoritative |
| 01 | `01_Product_Requirements_PRD.md` | Product requirements and acceptance intent | Authoritative |
| 02 | `02_Domain_Model_and_Business_Rules.md` | Domain language, aggregates, invariants, business rules | Authoritative |
| 03 | `03_System_Architecture.md` | Runtime architecture, boundaries, selected stack, ADRs | Authoritative |
| 04 | `04_Database_Schema.md` | PostgreSQL relational model, constraints, indexes, migration guidance | Authoritative specification |
| 05 | `05_API_Specification.md` | HTTP commands, queries, headers, errors, contract behavior | Authoritative contract specification |
| 06 | `06_Workflows_and_State_Machines.md` | Canonical states, transitions, guards, recovery paths | Authoritative |
| 07 | `07_UI_UX_Specification.md` | High-level product UX direction | Authoritative UX baseline |
| 08 | `08_Bank_File_and_Result_Processing.md` | Bank import/export, result bundle, crop, evidence, publication | Authoritative |
| 09 | `09_OCR_AI_Module_Specification.md` | Optional AI/OCR boundaries, providers, evaluation, privacy | Authoritative for optional AI scope |
| 10 | `10_Backend_Implementation_Guide.md` | FastAPI, SQLAlchemy, Celery, transactions, backend structure | Supporting authoritative |
| 11 | `11_Frontend_Implementation_Guide.md` | Two Next.js apps, API transport, frontend safety | Supporting authoritative |
| 12 | `12_Security_RBAC_Audit.md` | Authentication constraints, RBAC, ownership, audit, file security | Authoritative |
| 13 | `13_DevOps_Deployment_Operations.md` | Deployment architecture, backup/restore, observability, release operations | Authoritative operations baseline |
| 14 | `14_Testing_QA_Acceptance.md` | Test strategy, UAT, release evidence, acceptance gates | Authoritative QA baseline |
| 15 | `15_Agent_Implementation_Plan.md` | Milestones, dependencies, task contract, execution plan | Authoritative execution plan |
| 16 | `16_Implementation_Documentation_Index.md` | Version registry, topic authority, conflict governance | Authoritative documentation governance |
| 17 | `17_Future_Phases_Roadmap_and_Backlog.md` | Phase 1B–4 gates and governed future backlog | Authoritative future-phase baseline |
| 18 | `18_Production_Setup_and_Runbook.md` | Concrete production installation and operational runbooks | Authoritative production-runbook baseline |
| 19 | `19_Client_Packaging_and_Distribution_Guide.md` | PWA and optional packaged-client distribution | Authoritative packaging baseline |
| 20 | `20_Agent_Usage_Instructions.md` | Coding-agent operating protocol | Authoritative agent-execution baseline |
| 21 | `21_UI_Design_System_and_Screen_Specification.md` | Detailed design tokens, components, and screen contracts | Authoritative UI-design baseline |
| 22 | `22_UX_User_Journeys_and_Interaction_Guide.md` | Role journeys, interaction, confirmation, and recovery | Authoritative UX-interaction baseline |

### 5.2 Governed historical discovery archive

| ID | Canonical governed file | Governance state | Use |
|---:|---|---|---|
| 23 | `23_Discovery_Questions_and_Answers_FA.md` | Governed historical evidence only | Preserve original Persian discovery answers and map superseded decisions to current authorities |

File `23` is not an implementation authority. Its original answers remain unchanged for traceability, while its governance addendum identifies refined, superseded, deferred, or ADR-dependent conclusions.

### 5.3 Historical originals and review evidence

- Unsuffixed files `00` through `23` are retained as version 1.0 historical originals.
- Files ending in `.diff` are review evidence showing the change from the original to the revised file.
- Neither originals nor diff files may drive implementation when a canonical `.md` file exists.
- Generated artifacts such as OpenAPI, migrations, clients, test reports, release manifests, and checksums become authoritative only within their generated scope and only after validation.

## 6. Version Resolution Rules

### 6.1 Canonical selection

For a document number with both an unsuffixed file and a `.md` file:

```text
Use:    NN_Document_Name.md
Ignore: NN_Document_Name.md for implementation
```

The unsuffixed file remains only as the original v1.0 historical source used for comparison.

### 6.2 Filename precision

The full canonical filename is authoritative. The numeric prefix alone is not sufficient when multiple versions exist.

The misspelled original filename reference `00_Master_Implementation_Blprint.md` is deprecated. The canonical file is:

```text
00_Master_Implementation_Blueprint.md
```

### 6.3 Repository deployment copy

A project repository may remove the `_v1.1` suffix only as part of a controlled documentation release that copies the approved v1.1 content into canonical unsuffixed repository names.

That operation must:

1. preserve the version metadata inside each file;
2. record the source checksum;
3. archive the previous files;
4. generate a documentation release manifest;
5. ensure no old v1.0 content remains under the same canonical name.

### 6.4 Generated artifacts

The following generated artifacts become implementation contracts only after generation from the approved sources and validation in CI:

- OpenAPI schema;
- generated TypeScript API client;
- Alembic migration files;
- database schema snapshots;
- permission catalogue exports;
- status catalogue exports;
- test traceability matrix;
- release manifest;
- deployment image digest manifest.

Generated artifacts do not retroactively change the business specification. A mismatch must be treated as a defect or documentation conflict.

---

## 7. Topic Authority Matrix

There is no safe single global rule such as “the highest-numbered document always wins.” Authority is topic-specific.

| Topic | Primary authority | Required supporting documents |
|---|---|---|
| Product vision and fundamental scope | 00 | 01, 15 |
| Functional requirements and actor needs | 01 | 00, 02, 07, 14 |
| Domain terminology and invariants | 02 | 01, 06, 08 |
| Runtime and module architecture | 03 | 02, 10, 12, 13 |
| Relational schema and database constraints | 04 | 02, 06, 10, 12 |
| HTTP API and command/query contract | 05 | 02, 06, 10, 11, 12 |
| Canonical state machines and transition guards | 06 | 02, 05, 08, 12 |
| Product UX direction and screen-level behavior | 07 | 05, 06, 11, 12 |
| Bank statement/import/export/result processing | 08 | 02, 04, 05, 06, 12 |
| Optional OCR/AI behavior and authority limits | 09 | 02, 08, 12, 14 |
| Backend coding patterns | 10 | 03, 04, 05, 06, 12 |
| Frontend coding patterns | 11 | 05, 06, 07, 12 |
| Authentication, authorization, ownership, audit, security | 12 | 02, 05, 06, 13 |
| Deployment, backup, restore, monitoring, operational security | 13 | 03, 10, 12, 14 |
| Tests, UAT, severity, acceptance, release gates | 14 | 01, 02, 05, 06, 08, 12, 13 |
| Milestones, task ordering, coding-agent delivery | 15 | 00–14 |
| Documentation versions and authority resolution | 16 | All package files |
| Future roadmap | 17 after revision | 00, 01, 09, 15 |
| Concrete production runbooks | 18 after revision | 13, 14, 15 |
| Client packaging and distribution | 19 after revision | 03, 07, 11, 12, 13 |
| Agent operating instructions | 20 after revision | 15, 16 |
| Detailed UI screen/component system | 21 after revision | 05, 06, 07, 11, 12 |
| Detailed UX journeys and recovery | 22 after revision | 02, 05, 06, 07, 12 |
| Discovery history | 23 | Never authoritative for implementation |

---

## 8. Conflict Resolution Protocol

### 8.1 No silent interpretation

When two authoritative documents appear inconsistent, an engineer or coding agent must not silently choose the easier interpretation.

The implementation task must be paused at the conflicting decision point and a documentation conflict must be recorded.

### 8.2 Conflict record

Use a record with at least:

```text
Conflict ID: DOC-CONFLICT-NNN
Detected by:
Date:
Affected topic:
Affected documents and sections:
Observed contradiction:
Potential financial/security impact:
Proposed resolution:
Decision owner:
Decision status:
Required document updates:
Required code/test/migration updates:
```

### 8.3 Topic-specific resolution order

Apply the following only within the relevant topic:

1. **Security restriction:** document 12 may impose a stricter control than a general product or UI description.
2. **Financial invariant:** document 02 controls the invariant; document 06 controls its state transition implementation.
3. **State and command:** document 06 controls allowed transitions; document 05 controls the HTTP command surface.
4. **Database representation:** document 04 controls the approved relational representation, but it may not weaken documents 02, 06, or 12.
5. **Bank workflow:** document 08 controls bank processing details, but it may not weaken approval, evidence, privacy, or audit rules.
6. **Implementation pattern:** documents 10 and 11 explain how to implement approved behavior; they may not introduce new financial rules.
7. **Operations:** document 13 controls operational execution; it may not weaken security or QA release gates.
8. **Test acceptance:** document 14 controls release evidence; passing an incomplete test cannot override a missing product or security requirement.
9. **Sequence:** document 15 controls implementation order, not product behavior.
10. **Documents 17–22:** are authoritative for their declared future-roadmap, production-runbook, packaging, agent, UI, and UX topics, but may not weaken product, domain, workflow, API, security, or QA authorities.

### 8.4 Resolution output

A resolved conflict must result in all of the following where applicable:

- an ADR or approved decision record;
- updates to every affected authoritative document;
- updated API and schema contracts;
- updated tests and traceability entries;
- migration or data-reconciliation plan if implementation already exists;
- release note describing the behavior change.

---

## 9. Required Reading Order

### 9.1 Universal first pass

Every implementation participant should read:

1. `16_Implementation_Documentation_Index.md`
2. `00_Master_Implementation_Blueprint.md`
3. `01_Product_Requirements_PRD.md`
4. `02_Domain_Model_and_Business_Rules.md`
5. `06_Workflows_and_State_Machines.md`
6. `12_Security_RBAC_Audit.md`
7. `15_Agent_Implementation_Plan.md`

This establishes package authority, product intent, domain rules, workflow safety, security boundaries, and implementation order.

### 9.2 Product owner and business owner

1. 16 — package authority and open decisions
2. 00 — scope and fixed principles
3. 01 — requirements and acceptance intent
4. 02 — domain and business invariants
5. 06 — operational state machines
6. 07 — product experience
7. 14 — UAT and release acceptance
8. 15 — delivery milestones and pilot gates

### 9.3 Technical lead and architect

1. 16
2. 00
3. 01
4. 02
5. 03
6. 04
7. 05
8. 06
9. 08
10. 10
11. 11
12. 12
13. 13
14. 14
15. 15

### 9.4 Backend engineer

1. 16
2. 02
3. 03
4. 04
5. 06
6. 05
7. 08
8. 10
9. 12
10. 14
11. 15

Read 09 only when implementing optional AI/OCR infrastructure.

### 9.5 Frontend engineer

1. 16
2. 01
3. 02
4. 06
5. 05
6. 07
7. 11
8. 12
9. 14
10. 15

Files `21` and `22` are required detailed authorities for frontend work: file `21` owns screen/component structure and file `22` owns journeys, interaction, and recovery. They remain subordinate to files `02`, `05`, `06`, and `12` for domain, API, workflow, and security rules.

### 9.6 Security reviewer

1. 16
2. 00
3. 02
4. 03
5. 04
6. 05
7. 06
8. 08
9. 09
10. 10
11. 11
12. 12
13. 13
14. 14

### 9.7 DevOps and operations engineer

1. 16
2. 03
3. 04
4. 10
5. 12
6. 13
7. 14
8. 15

File 18 may be used only after reconciling its commands and paths with 13 v1.1.

### 9.8 QA engineer

1. 16
2. 01
3. 02
4. 04
5. 05
6. 06
7. 07
8. 08
9. 12
10. 13
11. 14
12. 15

### 9.9 Coding agent

Before coding any task, the agent must read:

1. 16 — authority and version rules
2. 15 — milestone and task contract
3. the exact primary authority documents for the task
4. 12 — security requirements
5. 14 — required tests and acceptance evidence

The agent must not start from file 20 alone, from a UI document alone, or from the discovery archive.

---

## 10. Document Dependency Matrix

| Document | Must be consistent with | May define implementation detail for |
|---:|---|---|
| 00 | Approved business decisions | All documents |
| 01 | 00 | 02, 06, 07, 14 |
| 02 | 00, 01 | 04, 05, 06, 08, 10, 12 |
| 03 | 00, 02 | 10, 11, 13 |
| 04 | 02, 03, 06, 12 | Alembic migrations and repositories |
| 05 | 02, 04, 06, 12 | Generated OpenAPI/client contracts |
| 06 | 01, 02, 04, 05, 12 | Workflow tests and orchestration |
| 07 | 01, 05, 06, 12 | 11, 21, 22 |
| 08 | 02, 04, 05, 06, 12 | Bank-processing code and fixtures |
| 09 | 02, 03, 08, 12, 14 | Optional AI adapters and evaluation |
| 10 | 03, 04, 05, 06, 08, 12 | Backend implementation |
| 11 | 05, 06, 07, 12 | Frontend implementation |
| 12 | 00, 02, 03, 04, 05, 06, 08 | Security implementation and tests |
| 13 | 03, 04, 10, 12, 14 | Deployment and operations |
| 14 | 01, 02, 04, 05, 06, 07, 08, 12, 13 | CI, QA, UAT, release gates |
| 15 | 00–14 | Tasks, milestones, implementation sequence |
| 16 | 00–23 | Package governance and authority registry |
| 17 | 00, 01, 09, 15, 16 | Future roadmap after revision |
| 18 | 13, 14, 15, 16 | Concrete runbook after revision |
| 19 | 03, 07, 11, 12, 13, 16 | Packaging after revision |
| 20 | 15, 16 | Agent operating instructions after revision |
| 21 | 05, 06, 07, 11, 12, 16 | Detailed screens after revision |
| 22 | 02, 05, 06, 07, 12, 16 | Detailed journeys after revision |
| 23 | None; historical | Background context only |

---

## 11. Canonical Phase Boundaries

### 11.1 Phase 1A — Operational Manual Core

Phase 1A includes:

- single-center, single-tenant operation;
- multiple center-side users with RBAC;
- Trader PWA and Admin Web as separate applications;
- trader onboarding, approval, suspension, and profile management;
- reusable trader-owned beneficiaries;
- outgoing payment requests and immutable request revisions;
- accountant review and correction workflow;
- payment attempts and bank-aware splitting;
- payment batch containers and immutable versions;
- exact manager approval for every outgoing batch version;
- preview and final bank export separation;
- integrity validation and exact export sent-to-bank recording;
- bank result bundle upload and mixed-content preservation;
- manual PDF/image preview and rectangular crop;
- matching candidates as advisory records;
- confirmed evidence links with replacement history;
- human paid/failed confirmation;
- retry and reconciliation workflows;
- immutable trader result publications;
- trader acknowledge and dispute workflow;
- gold sale pricing, incoming-payment confirmation, and guarded dispatch;
- secure private file lifecycle;
- audit, outbox, idempotency, optimistic concurrency, and durable jobs;
- Docker Compose deployment, monitoring, backup, and tested restore;
- complete QA, UAT, and pilot evidence.

### 11.2 Phase 1B — Assisted Operations

Phase 1B may add:

- OCR on human-selected pages or crops;
- structured extraction suggestions;
- explainable matching-candidate assistance;
- shadow-mode evaluation;
- limited provider rollout;
- enhanced operator productivity without financial authority.

Manual workflows remain available.

### 11.3 Phase 2 — Advanced Intelligence and Risk Control

Phase 2 may add:

- automatic segmentation proposals;
- advanced duplicate and anomaly detection;
- stronger matching assistance;
- controlled learning/evaluation pipelines;
- risk scoring and review prioritization;
- provider-specific optimization.

No automated model may silently gain financial decision authority.

### 11.4 Phase 3 — Integrations and Operational Scale

Phase 3 may add:

- bank API integration where contractually and technically available;
- accounting or ERP integration;
- larger-scale worker and storage topology;
- stronger SLA, observability, and operational automation;
- approved client packaging or distribution enhancements.

### 11.5 Phase 4 — Productization and Expansion

Phase 4 may add:

- multi-company or SaaS tenancy;
- complete tenant-isolation architecture;
- subscription/billing;
- configurable product packaging;
- broader organization and branch models.

Partial tenancy fields must not be introduced in Phase 1A as speculative design.

---

## 12. Fixed Technology Baseline

Unless changed through an approved architecture ADR:

| Layer | Baseline |
|---|---|
| Trader frontend | Next.js, React, TypeScript, PWA, mobile-first |
| Admin frontend | Next.js, React, TypeScript, desktop-first responsive |
| Backend API | FastAPI, Pydantic v2 |
| Persistence | SQLAlchemy 2.x, PostgreSQL 16+, Alembic |
| Background jobs | Celery with Redis broker |
| Business/job source of truth | PostgreSQL |
| Reverse proxy | Nginx |
| Pilot deployment | Docker Compose on a hardened Linux server |
| File storage | Private storage abstraction; explicit local bind mount for pilot or approved object storage |
| API contract | `/api/v1`, generated OpenAPI validation |
| Time storage | UTC `TIMESTAMPTZ`; business display conversion controlled by ADR-006 |
| Money | Integer IRR plus entered value/unit provenance |

Redis is non-authoritative and must not be the only location for financial job state, audit, idempotency, or workflow data.

---

## 13. Canonical Implementation Concepts

The following terms must be used consistently.

### 13.1 Outgoing payment

```text
PaymentRequest
PaymentRequestRevision
PaymentAttempt
PaymentBatch
PaymentBatchVersion
PaymentBatchItem
BatchApproval
BankExcelExport
BankResultBundle
ReceiptSegment
MatchingCandidate
ConfirmedEvidenceLink
PaymentResultPublication
```

### 13.2 Incoming/gold settlement

```text
GoldSaleOrder
GoldSalePricingVersion
IncomingPaymentReceipt
BankStatementFile
BankStatementImportRun
BankStatementRow
IncomingPaymentMatch
GoldDispatch
```

### 13.3 Platform integrity

```text
FileObject
FileLink
FileDerivation
IdempotencyRecord
OutboxEvent
AuditLog
ProcessingJob
ManualReviewTask
RetentionPolicy
LegalHold
AuthSession
AuthEvent
```

Generic substitutes such as `transaction`, `attachment`, `status update`, or `result file` must not collapse these distinctions in code or schema.

---

## 14. Canonical Cross-Document Rules

### 14.1 Approval

- Approval is not stored on `PaymentRequest`.
- Every outgoing Phase 1A batch requires manager approval.
- Approval targets an exact immutable `PaymentBatchVersion` and hash.
- A material replacement version requires a new decision.
- Approval records are append-only.
- Rejection requires a reason.
- Recent authentication and separation of duties apply according to documents 12 and the approved ADR.

### 14.2 Export

- Preview export is non-sendable.
- Final export requires exact approval.
- Final export is generated from immutable version items, not current mutable beneficiary records.
- Hash, row count, total, mapping version, source account, and file checksum are validated.
- A mismatch quarantines the export.
- Download is not the same as sent to bank.
- Mark-as-sent references the exact export.

### 14.3 Evidence and result

- Candidate acceptance is not financial confirmation.
- Evidence-link confirmation is separate from paid/failed confirmation.
- Primary evidence cardinality is protected by database constraints and transactions.
- Evidence correction preserves the previous link and file.
- Published results are versioned immutable snapshots.
- Correcting a published paid result requires sensitive review and, by default, dual control.

### 14.4 Files

- Original files are preserved.
- Derived crops/previews are separate files with provenance.
- Pending or quarantined files cannot support final financial actions.
- Raw storage keys are not exposed.
- Normal operations do not hard-delete financial evidence.
- Retention requires approved policy, legal-hold checks, dry run, and audit evidence.

### 14.5 AI/OCR

- AI is disabled by default in Phase 1A.
- AI output is advisory.
- Workers and AI providers cannot approve, confirm paid, publish results, or dispatch gold.
- External-provider use requires privacy, security, retention, cost, and rollout approval.

---

## 15. Architecture Decision Record Registry

Open ADRs do not permit arbitrary implementation assumptions. Each ADR must be resolved before the affected production gate.

### 15.1 Core ADRs

| ADR | Decision | Affected documents | Blocks |
|---|---|---|---|
| ADR-001 | Browser authentication/session transport | 03, 05, 10, 11, 12, 13, 15 | Auth implementation finalization |
| ADR-002 | Production hosting/topology | 03, 13, 18 | Production environment |
| ADR-003 | Production storage adapter and location | 03, 08, 10, 12, 13, 18 | Production file deployment |
| ADR-004 | RPO, RTO, backup schedule, restore ownership | 03, 13, 14, 18 | Production release |
| ADR-005 | Retention, deletion, and legal-hold governance | 02, 04, 08, 12, 13, 14 | Retention activation |
| ADR-006 | Business timezone, Jalali/Gregorian input and display rules | 02, 04, 05, 07, 11, 13 | Date-sensitive workflows |
| ADR-007 | Initial bank profiles, real templates, mappings, limits, source accounts | 02, 04, 05, 08, 13, 14 | Final bank export UAT |
| ADR-008 | Malware scanning and quarantine policy | 03, 08, 10, 12, 13, 14 | Production file acceptance |
| ADR-009 | Manager strong-auth/recent-auth factor and timeout | 05, 06, 07, 11, 12, 14 | Manager approval production use |

### 15.2 Business/security policy decisions

| Decision | Default until approved | Affected areas |
|---|---|---|
| Text-only payment confirmation | Disabled | 05, 06, 08, 10, 11, 12, 14 |
| Published paid-result correction control | Manager/dual control required | 06, 08, 12, 14 |
| IBAN masking policy | Least disclosure by role; exact policy open | 05, 07, 11, 12 |
| Gold dispatch override policy | No ungoverned override | 02, 06, 12, 14 |
| Break-glass authority | Disabled by default | 12, 13, 14 |
| File size/type limits | Configurable but production values open | 05, 08, 12, 13, 14 |
| Formal accessibility target | Must be selected before production acceptance | 07, 11, 14 |

### 15.3 AI ADRs

These ADRs are not Phase 1A launch blockers while AI remains disabled.

| ADR | Decision |
|---|---|
| ADR-AI-001 | Approved provider or deployment model |
| ADR-AI-002 | Allowed input scope and data minimization |
| ADR-AI-003 | Raw provider-output retention |
| ADR-AI-004 | Evaluation thresholds and release criteria |
| ADR-AI-005 | Shadow and limited rollout policy |
| ADR-AI-006 | Training-data and fine-tuning governance |
| ADR-AI-007 | AI interaction with text-only exception policy |
| ADR-AI-008 | Production cost limits and alert ownership |

---

## 16. Documentation Change Management

### 16.1 Change categories

| Category | Example | Required review |
|---|---|---|
| Editorial | Grammar, formatting, broken internal reference | Document owner |
| Clarification | Explain existing behavior without changing it | Topic owner and QA |
| Compatible extension | Add optional field or endpoint without weakening controls | Architecture, security, QA |
| Material business change | Change approval, amount, status, evidence, publication, dispatch rule | Product/business owner, domain owner, security, QA |
| Breaking technical change | Change schema, API, auth, storage, migration, deployment contract | Technical lead, affected owners, QA, operations |
| Production policy change | Retention, RPO/RTO, bank template, MFA, break-glass | Business owner, security, operations, QA |

### 16.2 Required revision process

1. Create a change request or ADR.
2. Identify all affected authoritative documents.
3. Update the highest-level authority first.
4. Update downstream schema, API, workflow, UI, security, operations, and tests.
5. Generate a diff for human review.
6. Update the traceability matrix.
7. Record migration and compatibility impact.
8. Approve the new documentation release.
9. Generate a new package manifest.
10. Only then implement or release the changed behavior.

### 16.3 Prohibited document changes

- Do not edit an approved document silently after code has been implemented from it.
- Do not change one status name in only one document.
- Do not add a financial permission only to a frontend guide.
- Do not change a database constraint without updating domain, workflow, API, tests, and migration guidance.
- Do not update an applied migration specification by rewriting history.
- Do not use discovery notes to justify bypassing a revised control.

---

## 17. Documentation-to-Code Traceability

The implementation repository should maintain a machine-readable or tabular traceability map.

Minimum fields:

```text
Requirement ID
Domain rule/invariant
Workflow transition
API command/query
Permission
Database tables/constraints
Frontend screen/component
Audit action
Outbox event
Test case IDs
Milestone/task ID
Release introduced
```

Examples:

| Requirement | Workflow | API | Persistence | Test |
|---|---|---|---|---|
| Every outgoing batch requires exact manager approval | Finalize → approve exact version | `POST .../versions/{version_id}/approve` | `payment_batch_versions`, `batch_approvals` | `CON-APP-*`, `SEC-APP-*`, `E2E-BATCH-*` |
| Manual crop is available in Phase 1A | Create segment → render derivative | Receipt-segment crop command | `receipt_segments`, `file_derivations`, `processing_jobs` | `FILE-CROP-*`, `E2E-RESULT-*` |
| Trader sees only immutable safe publication | Publish version → trader view | Publication command/query | `payment_result_publications` | `SEC-TRADER-*`, `E2E-PUB-*` |

The exact route names and test IDs must match the generated API and QA artefacts.

---

## 18. Repository Documentation Layout

Recommended layout:

```text
docs/
  
    00_Master_Implementation_Blueprint.md
    ...
    22_UX_User_Journeys_and_Interaction_Guide.md
  historical/
    23_Discovery_Questions_and_Answers_FA.md
    originals-v1.0/
  review-evidence/
    diffs/
    review-checklists/
  governance/
    README_FIRST.md
    OPEN_ADR_REGISTER.md
    PACKAGE_MANIFEST.json
    SHA256SUMS
    QUALITY_REPORT.md
  generated/
    openapi/
    migrations/
    permissions/
    statuses/
    traceability/
    release-manifests/
```

A simpler layout is acceptable if version authority remains unambiguous.

---

## 19. Coding-Agent Package Use Protocol

### 19.1 Before accepting a task

The agent must identify:

- the task ID and milestone;
- the exact authoritative files and sections;
- any supporting or historical document being consulted;
- affected aggregates and invariants;
- commands, permissions, ownership checks, and statuses;
- idempotency and concurrency requirements;
- audit and outbox events;
- database and migration impact;
- file and privacy impact;
- required tests and release evidence;
- open ADRs that block implementation.

### 19.2 During implementation

The agent must not:

- invent a new status;
- add generic financial `PATCH status` endpoints;
- use floating-point money;
- approve a request instead of a batch version;
- mutate a finalized batch version;
- generate a final export from mutable current data;
- treat file download as sent-to-bank;
- let a candidate mark an attempt paid;
- publish a raw bank bundle to a trader;
- overwrite evidence or publications;
- rely on frontend authorization;
- enqueue external side effects before the business transaction commits;
- use Redis as the only durable job state;
- add partial multi-tenancy;
- enable AI or break-glass by default.

### 19.3 Required delivery report

Every completed task must report:

```text
Task and milestone
Authoritative sections followed
ADRs assumed or resolved
Files changed
Migrations added
API contract changes
Permissions and ownership controls
Audit and outbox events
Idempotency/concurrency behavior
Tests added and results
Manual verification
Operational impact
Known limitations
Rollback or forward-fix plan
Documentation updates
```

---

## 20. Implementation Readiness Gates

### 20.1 Documentation gate for coding kickoff

Coding may begin only when:

- documents 00–16 v1.1 are available to the team;
- the task references the correct v1.1 filenames;
- M0 governance outputs from document 15 are assigned;
- unresolved ADRs are mapped to blocked tasks;
- canonical status and permission catalogues are prepared or scheduled;
- OpenAPI generation and migration ownership are assigned;
- branch, review, and change-control policies are agreed.

### 20.2 Feature implementation gate

A financial feature is not implementation-ready until its:

- domain invariant;
- state transition;
- API command;
- permission;
- persistence model;
- audit event;
- idempotency behavior;
- concurrency behavior;
- test cases;

are identifiable in the authoritative package.

### 20.3 UAT gate

UAT requires:

- approved bank fixtures and mappings;
- realistic synthetic users and files;
- exact batch-version approval flow;
- manual crop and evidence workflow;
- publication privacy checks;
- RBAC and trader-isolation evidence;
- backup and restore evidence;
- known-issues register;
- UAT sign-off owners.

### 20.4 Production gate

The documentation package alone does not authorize production launch.

Production also requires execution evidence defined by documents 13 and 14, including:

- resolved production-blocking ADRs;
- security validation;
- successful migration rehearsal;
- approved bank templates and source accounts;
- encrypted off-server backup;
- successful full restore drill;
- monitoring and alert ownership;
- operational runbooks;
- UAT and business sign-off;
- no unresolved critical defect;
- controlled pilot plan.

---

## 21. Final Review and Integration Status

### 21.1 Completed v1.1 alignment review

- [x] Documents `00` through `22` individually reviewed and revised to v1.1.
- [x] Document `23` converted to a governed historical archive without changing the original discovery body.
- [x] Manual rectangular crop fixed as Phase 1A functionality.
- [x] Exact immutable batch-version approval and export integrity aligned across product, domain, API, workflow, security, UI, UX, QA, and operations.
- [x] Single-center Phase 1A and Phase 4 tenancy boundary aligned.
- [x] Two independent frontend applications aligned across architecture, frontend, packaging, UI, UX, and operations.
- [x] Agent reading, planning, conflict, migration, test, and evidence protocols aligned.

### 21.2 Package integration state

The documentation package is ready for controlled implementation kickoff after the package-level manifest, checksum file, ADR register, and quality report are generated.

This status does **not** mean:

- unresolved ADRs are approved;
- production credentials or bank mappings exist;
- OpenAPI or Alembic migrations have been generated;
- backup/restore has been tested;
- UAT or production acceptance has passed.

### 21.3 Production status

Production launch remains blocked until the security, infrastructure, bank-configuration, QA, UAT, backup/restore, and operational evidence gates defined by documents `12`, `13`, `14`, and `18` are satisfied.

---

## 22. Required Next Execution Sequence

The next controlled sequence is:

1. publish the immutable documentation release package and checksum;
2. approve Milestone `M0` governance outputs and blocking ADR ownership;
3. create the implementation repository and branch-protection policy;
4. generate canonical status, permission, error, and event catalogues;
5. implement Milestone `M1` runtime foundation;
6. implement Milestone `M2` persistence, Unit of Work, audit, outbox, idempotency, and concurrency foundations;
7. continue through the milestone gates in document `15`;
8. generate OpenAPI, Alembic migrations, clients, test evidence, and release manifests from the implementation.

No future-phase capability is authorized merely because the documentation package is complete.

---

## 23. Package Handover Rules

Before handing the package to a development team or coding agent:

1. Include the authoritative v1.1 files.
2. Place originals and diffs in clearly named historical/review directories.
3. Keep historical originals and review evidence outside the authoritative directory.
4. Include the ADR register.
5. Include a checksum manifest.
6. Include the canonical status and permission catalogues when generated.
7. Include OpenAPI only after contract validation.
8. Include no production secret, real bank credential, private key, or unredacted production file.
9. Include synthetic or approved redacted fixtures only.
10. Include a README explaining which package release is being used.

Recommended archive name:

```text
Gold_Trade_Settlement_Development_Documentation-YYYYMMDD.zip
```

The archive should be immutable after release. Corrections require a new package release.

---

## 24. Common Dangerous Misreadings

The following interpretations are explicitly incorrect:

| Incorrect interpretation | Correct rule |
|---|---|
| “Manual-first means no internal crop.” | Manual rectangular crop is required in Phase 1A. |
| “A manager can approve the request.” | The manager approves the exact immutable batch version. |
| “An approved batch can be edited.” | A replacement version must be created and approved. |
| “Any generated Excel after approval is final.” | Final export must match the exact approved version, mapping, source account, totals, rows, and checksum. |
| “Downloaded means sent.” | Sent-to-bank is a separate command on the exact export. |
| “Candidate accepted means paid.” | Candidate, evidence, paid result, and publication are separate decisions. |
| “Trader may see the crop as soon as it exists.” | Trader sees only an authorized immutable publication. |
| “Technical admin can see or approve everything.” | Technical authority does not imply financial authority or unrestricted file access. |
| “Soft delete is sufficient for every record.” | Financial records use explicit cancellation, voiding, replacement, superseding, and governed retention. |
| “Redis job success is authoritative.” | PostgreSQL is the durable source of truth. |
| “Multi-company fields should be added now for the future.” | Multi-company/SaaS is Phase 4 after a complete tenancy design. |
| “File 23 records what the user wanted, so it overrides the English docs.” | File 23 is historical; revised authoritative specifications win. |
| “The latest numbered file always wins.” | Topic-specific authority and conflict governance apply. |

---

## 25. Documentation Quality Acceptance Criteria

This index is acceptable only if:

1. every package file is listed;
2. every file has a governance state;
3. canonical v1.1 filenames are explicit;
4. original and diff files are not mistaken for implementation authority;
5. topic authority is defined;
6. conflict resolution is explicit;
7. Phase 1A includes manual crop and exact batch-version approval;
8. single-tenant Phase 1A and Phase 4 tenancy are explicit;
9. all production-blocking ADRs are visible;
10. reading orders are role-specific;
11. documents 00–22 are present as canonical v1.1 files;
12. file 23 is visibly governed historical evidence and outside the authoritative directory;
13. coding-agent use rules are explicit;
14. package handover and versioning rules are explicit;
15. the implementation-kickoff sequence and package-release evidence are recorded.

---

## Appendix A — External Manifest Authority

The release package must contain machine-readable and human-readable manifests generated after all canonical files are finalized:

```text
governance/PACKAGE_MANIFEST.json
governance/PACKAGE_MANIFEST.csv
governance/SHA256SUMS
governance/QUALITY_REPORT.md
```

These external files are the checksum authority for the packaged release, including this index. Checksums embedded inside this index are intentionally avoided because a document cannot stably contain its own final hash.

The manifest must record at least:

- relative path;
- governance class;
- document ID where applicable;
- version;
- byte size;
- line count;
- SHA-256;
- UTF-8 validation result;
- Markdown-fence validation result.

---

## Appendix B — Canonical Delivery Layout

```text
Gold_Trade_Settlement_Development_Documentation/
  README_FIRST.md
  README_FIRST_FA.md
  
    00_....md
    ...
    22_....md
  historical/
    23_Discovery_Questions_and_Answers_FA.md
    originals-v1.0/
      00_....md
      ...
      23_....md
  review-evidence/
    diffs/
      00_....diff
      ...
      23_....diff
  governance/
    RELEASE_NOTES.md
    OPEN_ADR_REGISTER.md
    IMPLEMENTATION_KICKOFF_CHECKLIST.md
    PACKAGE_MANIFEST.json
    PACKAGE_MANIFEST.csv
    SHA256SUMS
    QUALITY_REPORT.md
```

The root must not contain ambiguous duplicate versions of the same numbered document.

---

## Appendix C — Final Package Statement

At the completion of the v1.1 integration pass:

- documents `00` through `22` v1.1 are the authoritative implementation and execution package within their declared topics;
- document `23` v1.1 is governed historical evidence only;
- unsuffixed originals and diff files are retained outside the authoritative directory for traceability;
- documentation completion authorizes implementation kickoff only after Milestone `M0` governance and blocking ADR ownership are in place;
- documentation completion does not authorize production launch;
- all code, migrations, generated contracts, tests, release artifacts, and operational evidence must still be produced and validated.
