# Gold Trade Settlement Platform
## 17 — Future Phases Roadmap and Backlog

**Document ID:** `17_Future_Phases_Roadmap_and_Backlog`  
**Version:** `1.1`  
**Status:** `Authoritative Future-Phase and Backlog Baseline`  
**Language:** English  
**Audience:** Product Owner, Business Owner, Technical Lead, Security Lead, Engineering Lead, DevOps Lead, QA Lead, Data/AI Lead, Coding Agents, Future Maintainers  
**Phase Coverage:** Phase 1A stabilization, Phase 1B, Phase 2, Phase 3, and Phase 4  
**Primary Authority:** Future-phase boundaries, phase entry/exit gates, backlog governance, sequencing of post-Phase-1A capabilities  
**Supersedes:** `17_Future_Phases_Roadmap_and_Backlog.md` version 1.0  

---

## 1. Purpose

This document defines how the Gold Trade Settlement Platform may evolve after the Phase 1A operational core is implemented and accepted.

It is not a calendar promise, sales commitment, or authorization to begin future work automatically. It is a governed roadmap that explains:

- which capability belongs to which phase;
- which prerequisites must be proven before a phase starts;
- which controls from Phase 1A must remain unchanged in every later phase;
- how experiments move from discovery to shadow mode, limited rollout, and general availability;
- which future capabilities are optional rather than inevitable;
- how backlog items are prioritized, approved, implemented, evaluated, and retired;
- how to prevent AI, integrations, scale work, or SaaS productization from weakening financial controls.

The central roadmap principle is:

> Preserve the business need and financial control model, then modernize execution in measured layers. Do not replace a trusted manual control with automation until the automated path has been evaluated, governed, and shown to be safer or materially more useful.

---

## 2. Authority and Relationship to the Documentation Pack

### 2.1 Documents that govern this roadmap

This document must be interpreted with the authoritative version 1.1 documents `00` through `16`, especially:

| Topic | Primary authority |
|---|---|
| Product and phase boundaries | `00_Master_Implementation_Blueprint.md`, `01_Product_Requirements_PRD.md` |
| Domain entities and invariants | `02_Domain_Model_and_Business_Rules.md` |
| Architecture and extension boundaries | `03_System_Architecture.md` |
| Database representation | `04_Database_Schema.md` |
| API contracts | `05_API_Specification.md` |
| Statuses, commands, and state transitions | `06_Workflows_and_State_Machines.md` |
| Product interaction model | `07_UI_UX_Specification.md` |
| Bank-file and result processing | `08_Bank_File_and_Result_Processing.md` |
| AI/OCR boundaries and governance | `09_OCR_AI_Module_Specification.md` |
| Backend implementation constraints | `10_Backend_Implementation_Guide.md` |
| Frontend implementation constraints | `11_Frontend_Implementation_Guide.md` |
| Security, RBAC, audit, and sensitive actions | `12_Security_RBAC_Audit.md` |
| Deployment, recovery, and operations | `13_DevOps_Deployment_Operations.md` |
| Test and release evidence | `14_Testing_QA_Acceptance.md` |
| Implementation order | `15_Agent_Implementation_Plan.md` |
| Documentation governance | `16_Implementation_Documentation_Index.md` |

### 2.2 What this document may decide

This document is authoritative for:

- post-Phase-1A sequencing;
- future capability grouping;
- entry and exit gates for future phases;
- backlog priority and dependency rules;
- experiment, shadow-mode, rollout, and deprecation stages;
- future-phase non-goals;
- cross-phase risk and evidence requirements.

### 2.3 What this document may not override

This roadmap may not override:

- financial invariants in document `02`;
- database constraints in document `04`;
- exact API semantics in document `05`;
- state machines in document `06`;
- security controls in document `12`;
- release gates in document `14`.

A roadmap item that requires changing one of those authorities must first create an approved change request or ADR and update all dependent documents.

### 2.4 Source-version rule

For documents `00` through `17`, version `1.1` files are authoritative. Files without the `_v1.1` suffix are historical version 1.0 references. Diff files are review evidence only.

---

## 3. Fixed Baseline That Future Phases Must Preserve

Future work starts from the following non-negotiable Phase 1A baseline.

### 3.1 Product and deployment baseline

- Phase 1A is a single-center, single-tenant system.
- Multi-company and SaaS architecture are deferred to Phase 4.
- Trader PWA and Admin Web are separate applications and deployment targets.
- The system remains usable without AI, OCR, bank APIs, SMS, external SaaS, or native apps.
- The manual operational path remains a supported recovery path after automation is introduced.

### 3.2 Financial authority baseline

- Human confirmation remains required for financial actions.
- Every outgoing Phase 1A payment batch requires manager approval.
- The manager approves one exact immutable `PaymentBatchVersion` and its content hash.
- A material change creates a replacement version and invalidates the prior approval operationally.
- Downloading an export is not the same as marking it sent to the bank.
- AI, OCR, background workers, or external providers may not approve, confirm, publish, dispatch, or correct financial state.

### 3.3 Domain baseline

The following distinctions must remain explicit:

```text
PaymentRequest
└── immutable PaymentRequestRevision
        └── PaymentAttempt
                └── PaymentBatchVersion / PaymentBatchItem
```

```text
BankResultBundle
└── FileObject
    └── ReceiptSegment
        ├── MatchingCandidate
        └── ConfirmedEvidenceLink
            └── PaymentResult
                └── PaymentResultPublication
```

Future features may enrich these entities but must not collapse them into one generic record.

### 3.4 Data and integrity baseline

- Canonical money is integer IRR.
- The entered value and selected unit are retained.
- No financial amount uses floating-point arithmetic.
- Financial history is corrected or superseded, not generically deleted.
- Idempotency is mandatory for sensitive commands.
- Mutable aggregates use optimistic concurrency.
- Business state, audit, outbox, and idempotency results are transactionally coordinated.
- Files remain private, lifecycle-controlled, checksummed, and governed by retention/legal-hold rules.

### 3.5 Manual crop baseline

A simple internal manual rectangular crop tool is part of Phase 1A. It supports authorized image/PDF preview, page selection, zoom, pan, rotation, normalized coordinates, derived-file creation, checksum, and provenance.

Automatic segmentation is a future capability. Basic manual crop is not a Phase 1B dependency.

---

## 4. Roadmap Governance Model

### 4.1 The roadmap is evidence-driven

A capability does not move to a later maturity stage because it is technically impressive or appears in a demo. It moves only when its evidence gate is met.

Required evidence may include:

- validated business problem;
- operational volume and pain measurements;
- approved ADR;
- privacy and security review;
- representative fixtures or evaluation dataset;
- test results;
- shadow-mode comparison;
- cost and capacity evidence;
- failure and fallback evidence;
- accountable business owner;
- rollback or kill-switch plan.

### 4.2 Capability maturity stages

Every future capability moves through these stages:

```text
Idea
→ Discovery
→ Approved backlog
→ Design/ADR
→ Prototype or offline evaluation
→ Shadow mode
→ Limited rollout
→ General availability
→ Sustained operation
→ Deprecation or replacement
```

A stage may be skipped only when the capability is non-sensitive and the technical lead, product owner, security owner, and QA owner agree in writing.

### 4.3 Required backlog fields

Every roadmap item must have:

```text
Backlog ID
Title
Target phase
Business outcome
Problem evidence
Primary owner
Dependencies
Blocking ADRs
Security/privacy impact
Financial authority impact
Data requirements
Operational requirements
Acceptance metrics
Fallback/kill switch
Test requirements
Documentation updates
Release stage
Current status
```

### 4.4 Priority definitions

| Priority | Meaning |
|---|---|
| Critical | Required to preserve financial safety, legal/contractual obligations, or production recoverability |
| High | Strong operational value or major risk reduction; should be considered early in the target phase |
| Medium | Useful improvement with measurable value but not required for phase viability |
| Low | Optional enhancement, research item, or product differentiation |
| Parked | Insufficient evidence, blocked externally, or not aligned with current strategy |

### 4.5 Phase assignment is not automatic authorization

Listing an item under a phase means it is eligible for planning in that phase. It does not mean the item is approved, funded, or safe to implement.

---

## 5. Phase Overview

| Phase | Name | Primary goal | Automation level | Tenant model |
|---|---|---|---|---|
| 1A | Operational Manual Core | Safe real operations with structured manual workflows | Manual, with asynchronous non-authoritative processing | Single center |
| 1B | Assisted Operations | Reduce repetitive review work without changing human authority | Optional OCR/extraction and explainable suggestions | Single center |
| 2 | Advanced Intelligence and Risk Control | Improve segmentation, matching, validation, and risk visibility | Advanced assistance, still human-authorized | Single center |
| 3 | Integrations and Operational Scale | Reduce external re-entry and support higher operational scale | Provider integrations and scaled operations | Single center or separate deployments |
| 4 | Productization, Multi-company, and SaaS | Turn the platform into a reusable product where justified | Product-level capabilities | Explicitly designed tenant model |

No phase removes the supported manual fallback unless a later separately approved operating model provides an equally controlled alternative.

---

# Part I — Phase 1A Stabilization

## 6. Phase 1A — Operational Manual Core

### 6.1 Objective

Deliver a production-usable operational core that replaces scattered messaging, uncontrolled spreadsheets, untracked file sharing, and ambiguous approvals with structured workflows.

### 6.2 Phase 1A capabilities that are already required

Phase 1A includes:

- trader onboarding, approval, suspension, and ownership isolation;
- beneficiary reuse and historical snapshots;
- outgoing payment request revisions;
- accountant review and correction flow;
- payment attempts and configurable splitting;
- immutable payment batch versions;
- exact manager approval with recent authentication and separation-of-duty policy;
- preview and final bank exports;
- exact export integrity and mark-as-sent action;
- bank-result bundle upload and mixed-file handling;
- internal manual crop and external evidence fallback;
- matching-candidate review separated from confirmed evidence;
- manual paid/failed confirmation with overpayment blocking;
- immutable trader result publication and correction history;
- trader acknowledgement and dispute;
- basic gold sale, incoming settlement, and dispatch guard where included in approved scope;
- work queues, audit, outbox, processing jobs, backup, restore, monitoring, and runbooks.

### 6.3 Phase 1A is not complete merely because screens exist

Before Phase 1A is considered stable, evidence must show:

- exact manager approval cannot be bypassed;
- stale versions and stale approvals are blocked;
- export hashes, row counts, totals, mappings, accounts, and file checksums are verified;
- duplicate sensitive commands are idempotent;
- concurrent actions do not create duplicate batches, evidence links, confirmations, or publications;
- traders cannot access other traders’ data or mixed bank bundles;
- manual crop provenance and privacy review work;
- backup and full restore have been tested;
- daily operators can complete the workflow without AI/OCR.

### 6.4 Phase 1A stabilization backlog

| ID | Item | Priority | Outcome |
|---|---|---:|---|
| STAB-001 | Close unresolved Critical/High financial defects | Critical | Safe production baseline |
| STAB-002 | Complete exact batch-version approval tests | Critical | No approval drift |
| STAB-003 | Complete export-integrity and quarantine tests | Critical | No wrong bank file submission |
| STAB-004 | Complete cross-trader and file-isolation tests | Critical | Privacy protection |
| STAB-005 | Complete idempotency and concurrency test suite | Critical | No duplicate financial effects |
| STAB-006 | Complete full backup/restore drill | Critical | Proven recoverability |
| STAB-007 | Validate manual crop and privacy review with real-like files | High | Reliable result publication |
| STAB-008 | Establish baseline operational metrics | High | Evidence for Phase 1B decisions |
| STAB-009 | Establish incident and support ownership | High | Controlled pilot operations |
| STAB-010 | Complete documentation and ADR register | High | Governed future change |

### 6.5 Phase 1A exit gate

Phase 1B planning may begin only when:

1. Phase 1A has passed the release gates in document `14`.
2. A controlled pilot has completed enough real operational cycles to expose workflow problems.
3. The manual result workflow, including internal crop, is accepted by accountants.
4. Audit, outbox, idempotency, and file provenance are functioning in production-like conditions.
5. Backup and restore evidence is current.
6. No unresolved Critical defect exists.
7. High defects have either been fixed or explicitly accepted by authorized owners.
8. Operational metrics are available to justify the next backlog items.

---

# Part II — Phase 1B

## 7. Phase 1B — Assisted Operations

### 7.1 Objective

Reduce repetitive accountant work using optional extraction and explainable suggestions while preserving the Phase 1A commands, human decisions, evidence model, and fallback path.

Phase 1B should be an additive assistance layer. It must not redesign the financial state machine.

### 7.2 Phase 1B non-goals

Phase 1B does not include:

- automatic payment confirmation;
- automatic evidence confirmation;
- automatic publication;
- automatic batch approval;
- automatic bank submission;
- automatic mixed-document segmentation as a general production capability;
- ungoverned training on production data;
- provider-dependent core workflows;
- SaaS or multi-company architecture.

### 7.3 Phase 1B capability groups

#### 7.3.1 AI/OCR provider governance foundation

Implement or complete:

- provider abstraction;
- provider approval record;
- data-processing and residency review;
- external-provider disabled-by-default configuration;
- provider-specific budgets and rate limits;
- payload minimization;
- redacted or crop-first input preference;
- model, adapter, prompt, schema, and normalization versioning;
- provider circuit breaker;
- immediate kill switch;
- audit and cost records.

A real external provider may not receive production financial files until security, privacy, contractual, and business approval are complete.

#### 7.3.2 OCR on controlled input

Initial production assistance should prefer:

1. human-created transaction crop;
2. redacted page;
3. one required page;
4. full document only with explicit policy approval.

Candidate extracted fields may include:

- amount and detected unit;
- IBAN;
- beneficiary name;
- tracking/reference number;
- bank name;
- date/time text;
- result text;
- bank-specific reference fields.

Raw and normalized values must remain separate.

#### 7.3.3 Explainable matching suggestions

The matching engine may rank `PaymentAttempt` candidates using reproducible features such as:

- exact amount;
- exact or normalized IBAN;
- beneficiary-name similarity;
- tracking-number equality;
- batch/export context;
- bank-profile compatibility;
- date distance;
- split-attempt context;
- existing-evidence conflicts;
- duplicate fingerprints.

The output is a `MatchingCandidate`. It is not a confirmed evidence link and does not change payment status.

#### 7.3.4 Enhanced review queue

Add operational queues for:

- failed extraction;
- ambiguous unit;
- low-confidence field extraction;
- multiple plausible attempts;
- no plausible attempt;
- candidate conflicts;
- possible duplicate evidence;
- provider-policy blocks;
- budget exhaustion;
- stale AI runs after source-file replacement.

#### 7.3.5 AI run observability

Persist and expose:

- logical `AIRun`;
- technical `AIJobAttempt` history;
- input-manifest hash;
- provider/model/adapter versions;
- prompt and output-schema versions;
- latency;
- estimated and actual cost where available;
- policy decision;
- result status;
- human review outcome;
- correction rate.

### 7.4 Phase 1B entry gate

Phase 1B implementation may start only when:

- Phase 1A exit gate is met;
- a real and measurable accountant pain point is documented;
- representative approved test data exists;
- external-provider use, if any, has an approved security/privacy decision;
- the AI evaluation owner and business review owner are named;
- a cost budget and kill-switch owner are defined;
- manual fallback has current regression coverage;
- no AI code path can invoke financial commands.

### 7.5 Phase 1B rollout stages

#### Stage A — Offline evaluation

- use synthetic, anonymized, redacted, or explicitly approved samples;
- compare providers and configurations;
- record field-level accuracy and ambiguity detection;
- do not expose results to normal operators.

#### Stage B — Shadow mode

- run alongside manual operation;
- do not change queue ordering unless explicitly approved;
- do not create confirmed evidence;
- compare suggestions with human outcomes;
- measure cost, latency, correction rate, and risky false positives.

#### Stage C — Limited assisted rollout

- limited users and bank layouts;
- preferably manual-crop input;
- prominent assistant labeling;
- no automatic acceptance;
- active monitoring and rapid disablement.

#### Stage D — General assisted availability

- only after approved evaluation thresholds are met;
- fallback remains visible and tested;
- model/configuration changes repeat the release process.

### 7.6 Phase 1B acceptance evidence

A Phase 1B capability is acceptable only when:

1. AI can be disabled without breaking the workflow.
2. Manual crop and manual confirmation still work.
3. The system never presents confidence as payment certainty.
4. Suggestions are explainable and versioned.
5. Human decisions are separate commands.
6. Provider failures, timeouts, and malformed output are handled safely.
7. Cost and budget enforcement work.
8. Sensitive payloads do not appear in normal logs or analytics.
9. Shadow-mode evidence is reviewed and approved.
10. The release has a rollback and kill-switch procedure.

### 7.7 Phase 1B backlog

| ID | Item | Priority | Dependencies |
|---|---|---:|---|
| AIOPS-101 | Provider policy and approval registry | Critical | Security/privacy ADRs |
| AIOPS-102 | AIRun and AIJobAttempt operational implementation | High | Durable job framework |
| AIOPS-103 | Input manifest and configuration versioning | High | File provenance |
| AIOPS-104 | Crop-first OCR adapter | High | Manual crop stable |
| AIOPS-105 | Field normalization and ambiguity handling | High | Money/date policy |
| AIOPS-106 | Explainable matching-candidate generator | High | Confirmed historical labels |
| AIOPS-107 | Shadow-mode evaluation pipeline | Critical | Golden dataset/evaluation plan |
| AIOPS-108 | AI cost budgets and circuit breaker | High | Provider integration |
| AIOPS-109 | Assisted-review queue | High | Candidate APIs/UI |
| AIOPS-110 | Model/configuration release workflow | Critical | QA and security ownership |
| AIOPS-111 | Provider comparison report | Medium | Offline evaluation |
| AIOPS-112 | Redaction/preprocessing experiments | Medium | Privacy approval |

### 7.8 Phase 1B exit gate

Phase 2 planning may start when:

- assisted features are stable under real daily use;
- approved evaluation results exist by bank layout/use case;
- high-risk false-positive patterns are understood;
- correction and fallback data are being captured safely;
- configuration changes are versioned and reversible;
- cost and operational burden are acceptable;
- no evidence shows degradation of manual financial controls.

---

# Part III — Phase 2

## 8. Phase 2 — Advanced Intelligence and Risk Control

### 8.1 Objective

Improve document segmentation, matching quality, duplicate detection, validation, risk visibility, and operational reporting without granting autonomous financial authority.

### 8.2 Phase 2 non-goals

Phase 2 does not authorize:

- autonomous payment confirmation;
- autonomous manager approval;
- automatic publication without human command;
- silent rejection based only on anomaly or risk score;
- uncontrolled online learning from production corrections;
- direct bank instruction submission without Phase 3 integration governance;
- multi-company/SaaS architecture.

### 8.3 Phase 2 capability groups

#### 8.3.1 Automatic segmentation proposals

The system may propose transaction regions for images and PDFs, including multi-page documents.

Requirements:

- original file remains immutable;
- each proposed segment records source page, normalized coordinates, rotation, renderer/preprocessor version, model version, and confidence;
- proposals remain distinguishable from human-created segments;
- a human can adjust, reject, or replace a proposal;
- low-quality or unsupported layouts fall back to manual crop;
- automatic segmentation does not create confirmed evidence.

#### 8.3.2 Advanced matching engine

Enhancements may include:

- bank-specific feature sets;
- configurable scoring versions;
- candidate ranking calibration;
- split-payment reasoning;
- export/batch context;
- normalized Persian and Arabic text handling;
- duplicate and evidence-conflict penalties;
- explanation codes and feature contribution display.

No opaque score may be presented as a guarantee.

#### 8.3.3 Duplicate and conflict detection

Potential signals:

- tracking/reference reuse;
- original-file checksum reuse;
- derived-crop checksum reuse;
- perceptual similarity;
- same amount/IBAN/date combination;
- same segment linked elsewhere;
- conflicting active primary evidence;
- repeated publication correction.

A duplicate signal creates a review task. It does not automatically reject a legitimate payment.

#### 8.3.4 Risk and anomaly signals

Potential operational signals:

- unusual request volume;
- repeated failed attempts;
- frequent beneficiary changes;
- repeated corrections after approval;
- many unmatched result segments;
- suspicious evidence-replacement patterns;
- source-account or mapping anomalies;
- abnormal delay between export and result;
- repeated access-denied or break-glass activity.

Risk outputs must be explainable, reviewable, and non-authoritative.

#### 8.3.5 Optional validation-provider integrations

Potential providers may validate:

- IBAN format and status;
- account-owner name;
- national ID;
- consistency among IBAN, name, and national ID.

Requirements:

- provider abstraction;
- explicit user-facing status that distinguishes “not checked,” “provider unavailable,” “inconclusive,” and “verified by provider”;
- no blocking dependency unless an approved business policy explicitly requires it;
- manual exception and review path;
- data-minimization and contractual approval.

#### 8.3.6 Advanced operational reporting

Possible dashboards:

- request-to-payment cycle time;
- accountant queue age and workload;
- manager approval age;
- export-integrity incidents;
- retry and failure reasons;
- evidence-replacement rate;
- publication correction rate;
- AI-assisted versus manual processing;
- model/provider performance by bank layout;
- validation-provider availability;
- cost by use case;
- risk-signal review outcomes.

### 8.4 Data governance for learning and evaluation

Human corrections may be retained as governed evaluation labels, but they must not automatically retrain or reconfigure a production model.

Any training or fine-tuning requires:

- lawful and contractual basis;
- approved dataset scope;
- anonymization or minimization strategy;
- dataset version;
- access control;
- retention policy;
- model evaluation;
- security review;
- deployment approval;
- rollback plan.

Production files and labels must not be copied into source control.

### 8.5 Phase 2 entry gate

- Phase 1B exit gate is met.
- Representative labeled data exists for the target bank layouts.
- Evaluation methodology is approved.
- Human review capacity exists for pilot results.
- Risk owners define acceptable alert behavior.
- Privacy and retention rules cover new derived data.
- Compute, storage, and provider cost are budgeted.
- Operational dashboards can detect degradation.

### 8.6 Phase 2 release gate

A capability may enter general availability only when:

- evaluation is use-case and layout specific;
- thresholds are tied to an approved evaluation report rather than universal numbers;
- high-risk false positives are within approved limits;
- ambiguity and unsupported-layout detection work;
- manual fallback remains available;
- review queues do not create unmanageable operational load;
- model/configuration drift is monitored;
- privacy and retention controls cover all derived artifacts;
- the capability can be disabled without corrupting workflow state.

### 8.7 Phase 2 backlog

| ID | Item | Priority | Dependencies |
|---|---|---:|---|
| INTEL-201 | Automatic segmentation proposals | High | Representative labeled pages |
| INTEL-202 | Segment-adjustment and review UX | High | Segmentation proposal API |
| INTEL-203 | Advanced configurable matching engine | High | Candidate feature history |
| INTEL-204 | Candidate calibration and explanation report | High | Evaluation framework |
| INTEL-205 | Duplicate evidence detection | Critical | File/segment fingerprints |
| INTEL-206 | Duplicate-review workflow | Critical | Review tasks and permissions |
| INTEL-207 | Operational risk-signal framework | Medium | Risk-owner policy |
| INTEL-208 | Optional IBAN/name validation adapter | Medium | Provider/contract approval |
| INTEL-209 | Validation exception workflow | High | Provider adapter |
| INTEL-210 | Advanced workload and cycle-time dashboards | High | Trusted metrics |
| INTEL-211 | Model/configuration drift monitoring | High | Versioned AI runs |
| INTEL-212 | Governed evaluation-label export | Medium | Retention/privacy approval |

### 8.8 Phase 2 exit gate

Phase 3 planning may start when:

- the platform has stable operational ownership;
- external integration pain is measured and prioritized;
- data and workflow quality are sufficient for reliable reconciliation;
- observability, incident response, and restore practices are mature;
- integration failures can be isolated from the manual core;
- the business has contractual access to target providers.

---

# Part IV — Phase 3

## 9. Phase 3 — Integrations and Operational Scale

### 9.1 Objective

Reduce external re-entry, improve reconciliation, and support higher operational volume through controlled adapters and operational scaling.

Phase 3 is not a license to remove manual fallback or to let an external provider become the source of truth for internal financial history.

### 9.2 Phase 3 capability groups

#### 9.2.1 Read-only or inbound bank integrations

Preferred initial integration order:

1. fetch account statement data;
2. receive or query payment-result status;
3. import bank-side references;
4. reconcile imported data with internal export and attempts;
5. consider instruction submission only after separate approval.

Imported data must create versioned import runs and preserve raw provider payload references according to policy.

#### 9.2.2 Bank instruction submission

Submitting payment instructions through an API is a separate high-risk capability.

It requires:

- separate ADR and threat model;
- exact approved `PaymentBatchVersion` binding;
- exact approved bank profile, mapping, source account, row count, total, and content hash;
- strong/recent manager authentication;
- separation of duties;
- provider idempotency and internal idempotency;
- submission receipt and provider reference;
- uncertain-outcome recovery;
- reconciliation against bank status;
- manual submission fallback;
- explicit kill switch.

A provider timeout must not cause an automatic resubmission with a new logical request.

#### 9.2.3 Accounting-system integration

Potential capabilities:

- export confirmed settlements;
- import approved trader balances or reference data;
- synchronize reconciliation references;
- link gold-sale orders and incoming settlements;
- post correction or reversal references.

Requirements:

- system-of-record ownership matrix;
- versioned mapping;
- idempotent exchange;
- reconciliation report;
- conflict workflow;
- no silent overwrite of financial history.

#### 9.2.4 Notification integrations

Potential channels:

- in-app notifications;
- email;
- SMS;
- controlled webhooks;
- internal operations tools.

Sensitive financial details must be minimized. Delivery failure must not roll back financial state.

#### 9.2.5 Operational scale

Scale work may include:

- separate worker pools by queue;
- dedicated file and AI workers;
- object-storage migration;
- read replicas for reporting where justified;
- query and index tuning;
- bounded archival workflows;
- higher-volume audit and outbox processing;
- capacity testing;
- improved deployment automation;
- blue/green or canary deployment where operationally maintainable.

#### 9.2.6 Disaster-recovery maturity

Phase 1A already requires backup and restore. Phase 3 may strengthen this with:

- approved RPO/RTO evidence;
- more frequent database recovery points;
- object-storage versioning or replication;
- scheduled full restore drills;
- regional or provider failure scenarios;
- documented recovery decision authority;
- reconciliation of bank actions after restore.

### 9.3 Phase 3 entry gate

- provider contracts and sandbox access exist;
- ownership of credentials and incidents is defined;
- target integration has measurable business value;
- manual workflow and reconciliation are stable;
- sandbox and contract-test fixtures exist;
- provider outage and uncertain-outcome behavior are designed;
- data residency and privacy are approved;
- rollback and kill-switch plans exist;
- capacity evidence supports scale work.

### 9.4 Phase 3 release gate

- integration adapters pass contract tests;
- provider outages do not block manual operations;
- duplicate callbacks and retries are idempotent;
- imported and submitted data reconcile with internal records;
- uncertain submission outcomes create explicit review tasks;
- credentials are isolated and rotatable;
- provider-specific raw data is access-controlled;
- monitoring and alerts have named owners;
- rollback or disablement is tested;
- user-facing status distinguishes internal state from provider state.

### 9.5 Phase 3 backlog

| ID | Item | Priority | Dependencies |
|---|---|---:|---|
| INTEG-301 | Bank statement API adapter | High | Contract/sandbox access |
| INTEG-302 | Versioned inbound import run | High | Bank adapter |
| INTEG-303 | Provider-result reconciliation | High | Attempts/export context |
| INTEG-304 | Uncertain-outcome review workflow | Critical | Provider submission design |
| INTEG-305 | Bank instruction submission pilot | Parked/High-risk | Separate approval and threat model |
| INTEG-306 | Accounting export adapter | Medium | System-of-record matrix |
| INTEG-307 | Accounting reconciliation report | High | Accounting adapter |
| INTEG-308 | Notification adapter framework | Medium | Outbox/event contracts |
| SCALE-309 | Object-storage migration | High when volume requires | Storage ADR and migration plan |
| SCALE-310 | Queue-specific worker pools | Medium | Capacity evidence |
| SCALE-311 | Reporting/read scaling | Medium | Query evidence |
| OPS-312 | Advanced DR and RPO/RTO validation | High | Recovery ADR |
| OPS-313 | Release canary/rollback automation | Medium | Operational maturity |

### 9.6 Phase 3 exit gate

Phase 4 planning may start only when productization is a confirmed business strategy and not merely a technical possibility.

---

# Part V — Phase 4

## 10. Phase 4 — Productization, Multi-company, and SaaS

### 10.1 Objective

Convert the internal single-center platform into a product for multiple independent companies only when there is a validated commercial and operational need.

This phase is optional.

### 10.2 No partial tenancy before Phase 4

Do not add `organization_id` or `tenant_id` selectively to Phase 1A tables as a “future-proofing” shortcut.

Phase 4 must design tenancy end to end across:

- identity and session audience;
- roles and permissions;
- business records;
- bank profiles and accounts;
- files and storage keys;
- processing jobs;
- audit and security events;
- outbox and notifications;
- backups and restores;
- reports and analytics;
- encryption and secrets;
- support access;
- retention and legal holds;
- billing and entitlements.

### 10.3 Deployment-model decision

Phase 4 must explicitly choose among:

1. one isolated deployment per company;
2. shared application with isolated databases;
3. shared database with strict tenant isolation;
4. hybrid model.

The decision must consider financial sensitivity, operational capability, cost, data residency, backup/restore, support, and incident blast radius.

### 10.4 Multi-company foundation

Requirements include:

- tenant/company lifecycle;
- tenant-scoped identity;
- tenant-aware authorization;
- complete cross-tenant isolation tests;
- tenant-specific bank profiles and source accounts;
- tenant-specific file access and storage namespaces;
- tenant-specific audit export;
- tenant-specific retention and legal hold;
- tenant-aware background jobs and idempotency;
- tenant-aware backup, export, restore, and deletion;
- migration plan from the Phase 1A single-center model.

### 10.5 Subscription, billing, and entitlements

Potential capabilities:

- plans and feature entitlements;
- usage measurement;
- invoices;
- payment state;
- grace periods;
- controlled suspension;
- AI-cost allocation;
- support tiers.

Billing must never make historical financial records inaccessible unexpectedly. Read access, evidence export, dispute handling, and retention obligations require explicit policy.

### 10.6 Support access

Generic unrestricted impersonation is not acceptable.

Support access must be:

- explicitly approved;
- time-limited;
- tenant-scoped;
- purpose-bound;
- protected by strong/recent authentication;
- visible to security/audit owners;
- fully audited;
- revocable;
- reviewed after use.

Where possible, use diagnostic views and tenant-provided exports instead of acting as a tenant user.

### 10.7 Product analytics

Analytics must avoid exposing sensitive transaction details to product analytics systems.

Allowed analytics should focus on aggregated operational behavior such as:

- active companies and users;
- feature adoption;
- processing duration;
- queue age;
- error and correction rate;
- assistant usage;
- system availability;
- subscription events.

IBANs, beneficiary names, raw amounts, receipts, notes, and bank files must not become analytics dimensions.

### 10.8 Public API and partner ecosystem

Potential capabilities:

- scoped API credentials;
- OAuth or equivalent delegated authorization where appropriate;
- webhooks;
- partner sandbox;
- quotas and rate limits;
- signed events;
- replay protection;
- partner audit;
- contract versioning;
- deprecation policy.

Public APIs must reuse domain commands and may not bypass financial approval or evidence rules.

### 10.9 Phase 4 entry gate

- commercial strategy is approved;
- target customer and deployment model are defined;
- tenancy threat model is complete;
- data-residency and contractual obligations are known;
- support and incident model is funded;
- per-tenant backup/export/restore requirements are defined;
- migration from single-center data is designed and tested;
- cross-tenant security test ownership is named;
- billing and suspension policy protects historical records.

### 10.10 Phase 4 release gate

- cross-tenant isolation tests pass at API, database, file, job, cache, analytics, and backup layers;
- tenant-scoped idempotency and audit are proven;
- tenant onboarding/offboarding is governed;
- support access is controlled and audited;
- per-tenant export and restore are tested;
- billing failure cannot corrupt or hide financial history;
- data deletion respects retention and legal hold;
- noisy-neighbor and capacity risks are controlled;
- incident response can identify affected tenants accurately.

### 10.11 Phase 4 backlog

| ID | Item | Priority | Dependencies |
|---|---|---:|---|
| PROD-401 | Commercial productization discovery | Critical | Business strategy |
| PROD-402 | Tenant/deployment architecture ADR | Critical | Threat model and cost model |
| PROD-403 | Single-center-to-tenant migration design | Critical | Chosen architecture |
| PROD-404 | Tenant identity and authorization | Critical | Tenant model |
| PROD-405 | Tenant-scoped file/storage isolation | Critical | Storage model |
| PROD-406 | Tenant-scoped jobs, audit, and outbox | Critical | Tenant context propagation |
| PROD-407 | Cross-tenant security test suite | Critical | Complete tenant implementation |
| PROD-408 | Tenant backup/export/restore | Critical | Operations model |
| PROD-409 | Billing and entitlement engine | Medium | Commercial policy |
| PROD-410 | Controlled support access | High | Security policy |
| PROD-411 | Privacy-safe product analytics | Medium | Analytics governance |
| PROD-412 | Public API and webhooks | Medium | Partner strategy |

---

# Part VI — Cross-Phase Backlog

## 11. Cross-Phase Backlog by Domain

### 11.1 Bank and settlement processing

| ID | Capability | Target phase | Priority | Key gate |
|---|---|---:|---:|---|
| BANK-001 | Versioned bank profiles and mappings | 1A | Critical | Approved real fixtures |
| BANK-002 | Exact final export integrity | 1A | Critical | Hash/checksum tests |
| BANK-003 | Manual crop and result review | 1A | Critical | Privacy and provenance |
| BANK-104 | OCR on controlled crop/page | 1B | High | Provider/evaluation approval |
| BANK-201 | Automatic segmentation proposals | 2 | High | Labeled page dataset |
| BANK-202 | Duplicate evidence detection | 2 | Critical | Review workflow |
| BANK-301 | Inbound bank API | 3 | High | Contract and sandbox |
| BANK-302 | Bank instruction API | 3 | Parked/high risk | Separate financial threat model |
| BANK-401 | Tenant-specific bank configuration | 4 | Critical | Tenant model |

### 11.2 AI and data intelligence

| ID | Capability | Target phase | Priority | Key gate |
|---|---|---:|---:|---|
| AI-101 | Provider governance | 1B | Critical | Security/privacy approval |
| AI-102 | Shadow-mode extraction | 1B | High | Evaluation dataset |
| AI-103 | Explainable candidate suggestions | 1B | High | Human labels |
| AI-201 | Automatic segmentation | 2 | High | Layout-specific evidence |
| AI-202 | Advanced matching calibration | 2 | High | Approved evaluation report |
| AI-203 | Risk/anomaly signals | 2 | Medium | Risk policy |
| AI-204 | Governed training dataset | 2 | Medium | Legal/data governance |
| AI-301 | Scaled inference operations | 3 | Medium | Volume and cost evidence |
| AI-401 | Tenant-specific AI budgets/policies | 4 | Medium | Tenant/billing model |

### 11.3 Security and identity

| ID | Capability | Target phase | Priority | Key gate |
|---|---|---:|---:|---|
| SEC-001 | RBAC, ownership, session revocation | 1A | Critical | Security tests |
| SEC-002 | Manager recent auth and separation of duty | 1A | Critical | ADR and UAT |
| SEC-101 | Provider egress/data policy | 1B | Critical | Contract/security review |
| SEC-201 | Advanced risk/security monitoring | 2 | High | Alert ownership |
| SEC-301 | Provider credential isolation/rotation | 3 | Critical | Integration launch |
| SEC-401 | Tenant isolation | 4 | Critical | Threat model and tests |
| SEC-402 | Controlled cross-tenant support access | 4 | High | Break-glass policy |

### 11.4 Frontend and operator experience

| ID | Capability | Target phase | Priority | Key gate |
|---|---|---:|---:|---|
| UX-001 | Trader mobile-first PWA | 1A | High | UAT |
| UX-002 | Dense accountant workspace | 1A | High | Real workflow UAT |
| UX-003 | Exact manager approval screen | 1A | Critical | Approval security tests |
| UX-004 | Manual crop and evidence workspace | 1A | Critical | Accessibility/privacy tests |
| UX-105 | Assisted review experience | 1B | High | Shadow-mode feedback |
| UX-201 | Segmentation review and risk explanations | 2 | High | Explainability testing |
| UX-301 | Integration/reconciliation operations | 3 | High | Provider workflows |
| UX-401 | Tenant administration and branding | 4 | Medium | Tenant model |

### 11.5 Operations and platform

| ID | Capability | Target phase | Priority | Key gate |
|---|---|---:|---:|---|
| OPS-001 | Docker Compose, monitoring, off-server backup | 1A | Critical | Restore drill |
| OPS-002 | Durable jobs and outbox monitoring | 1A | Critical | Failure-injection tests |
| OPS-103 | AI budget/circuit-breaker operations | 1B | High | Provider rollout |
| OPS-201 | Model/configuration monitoring | 2 | High | AI general availability |
| OPS-301 | Scaled worker/storage topology | 3 | High when needed | Capacity evidence |
| OPS-302 | Advanced DR | 3 | High | RPO/RTO evidence |
| OPS-401 | Per-tenant operations and recovery | 4 | Critical | Tenant launch |

### 11.6 Gold sale and incoming settlement

| ID | Capability | Target phase | Priority | Key gate |
|---|---|---:|---:|---|
| GOLD-001 | Versioned pricing and manual settlement | 1A | High | Approved workflow |
| GOLD-002 | Partial incoming receipts and dispatch guard | 1A | Critical | Financial tests |
| GOLD-201 | Enhanced statement matching | 2 | High | Incoming data quality |
| GOLD-202 | Risk signals for overpayment/duplicate receipt | 2 | Medium | Review policy |
| GOLD-301 | Accounting/warehouse integrations | 3 | Medium | Contract and reconciliation |
| GOLD-401 | Tenant-specific gold workflows | 4 | Medium | Product strategy |

---

## 12. Backlog Selection and Quarterly/Release Planning

### 12.1 Selection criteria

A backlog item should be selected using evidence from:

- operational pain and time spent;
- financial or privacy risk;
- incident history;
- customer/user demand;
- strategic fit;
- dependency readiness;
- implementation and operational cost;
- data availability;
- provider feasibility;
- ability to measure success;
- ability to roll back.

### 12.2 Suggested scoring dimensions

Teams may use a scoring model, but the score does not override safety gates.

Suggested dimensions:

```text
Business value        1–5
Risk reduction        1–5
User-frequency impact 1–5
Evidence quality      1–5
Dependency readiness  1–5
Delivery effort       1–5, inverted for ranking
Operational burden    1–5, inverted for ranking
Security/privacy risk 1–5, used as a gate rather than benefit
```

### 12.3 Mandatory capacity reservation

Each release should reserve capacity for:

- security and dependency updates;
- production defects;
- backup/restore and runbook testing;
- documentation drift;
- data-quality corrections;
- observability improvements;
- migration safety;
- accessibility and localization defects.

Future-feature delivery must not consume all capacity while operational debt grows.

---

## 13. Data Collection and Evaluation Plan

### 13.1 Collect only what is justified

Do not collect data merely because it might be useful for AI later.

Every additional retained field or artifact requires:

- defined purpose;
- owner;
- access policy;
- retention rule;
- legal/contractual basis where applicable;
- deletion/legal-hold behavior;
- security classification.

### 13.2 Phase 1A operational labels that may support future evaluation

Where already required for business operations, retain:

- original bank files and checksums;
- human-created crop provenance;
- confirmed evidence links;
- payment-result confirmations;
- candidate rejection/acceptance reasons where implemented;
- correction history;
- failure and retry reasons;
- request and attempt snapshots;
- bank profile/mapping versions;
- publication correction history.

### 13.3 Golden dataset principles

A golden dataset must be:

- representative of target banks and layouts;
- versioned;
- approved;
- access-controlled;
- synthetic, anonymized, redacted, or explicitly authorized;
- separated from production operations;
- labeled through a documented process;
- reviewed for ambiguous cases;
- accompanied by dataset limitations.

There is no universal minimum sample count. Dataset sufficiency must be justified by layout diversity, target use case, risk, and evaluation confidence.

### 13.4 Evaluation dimensions

Depending on use case, measure:

- exact amount accuracy;
- detected-unit accuracy;
- IBAN accuracy;
- tracking/reference accuracy;
- segmentation precision/recall or overlap quality;
- candidate recall at K;
- top-ranked candidate precision;
- ambiguity detection;
- high-risk false positives;
- duplicate-signal precision and review burden;
- latency;
- cost;
- manual correction rate;
- unsupported-layout rate;
- privacy incidents or blocked-policy rate.

### 13.5 Evaluation reports are configuration-specific

An approval applies only to the evaluated combination of:

- use case;
- input scope;
- bank/layout;
- provider;
- model;
- prompt;
- preprocessing;
- output schema;
- normalization;
- matching configuration;
- thresholds.

A material configuration change requires re-evaluation.

---

## 14. Technical Debt and Architecture Traps to Avoid

### 14.1 Do not bypass immutable revisions and versions

Future automation must not update request, batch, approval, export, evidence, or publication history in place.

### 14.2 Do not create a second financial truth inside an integration

Provider state and internal state must be reconciled, not silently equated.

### 14.3 Do not use Redis, Celery results, analytics, or AI storage as authoritative business state

PostgreSQL remains the source of truth for business, audit, outbox, processing records, and financial history.

### 14.4 Do not add generic status mutation endpoints

Future features use explicit commands with permission, idempotency, concurrency, audit, and state guards.

### 14.5 Do not make external connectivity mandatory

Provider, internet, or bank API outages must not prevent controlled manual operation.

### 14.6 Do not hide uncertainty

UI and reports must distinguish:

- internal confirmed state;
- external provider state;
- proposed AI result;
- unverified extracted field;
- ambiguous match;
- stale or failed integration result.

### 14.7 Do not implement partial tenancy

Tenant architecture is an end-to-end Phase 4 program, not an extra nullable foreign key.

### 14.8 Do not treat support impersonation as a convenience feature

Support access is a sensitive, governed capability.

### 14.9 Do not let product analytics capture financial payloads

Analytics events must be privacy-safe and purpose-limited.

### 14.10 Do not retain AI inputs and raw outputs indefinitely by default

Retention must reflect operational need, privacy, debugging value, and contractual terms.

---

## 15. Cross-Phase Risk Register

| Risk | Phase(s) | Control |
|---|---|---|
| AI suggestion interpreted as financial truth | 1B–2 | Separate entities, UI labeling, human commands |
| Model/configuration drift | 1B–2 | Versioning, evaluation, monitoring, rollback |
| Provider privacy breach | 1B–3 | Minimization, contracts, egress controls, kill switch |
| Bank API duplicate submission | 3 | Dual idempotency, uncertain-outcome workflow, reconciliation |
| External provider outage | 1B–3 | Circuit breaker and manual fallback |
| Excessive review-queue load | 1B–2 | Shadow metrics, threshold tuning, rollout limits |
| False duplicate/risk signal | 2 | Explainable review, no automatic rejection |
| Integration overwrites internal history | 3 | System-of-record matrix and versioned imports |
| Scale work hides correctness defects | 3 | Capacity evidence and regression gates |
| Partial tenant isolation | 4 | End-to-end tenant architecture and testing |
| Billing blocks historical evidence | 4 | Explicit access/retention policy |
| Support access exposes tenant data | 4 | Time-limited scoped access and audit |
| Data collection exceeds purpose | All | Data inventory, retention, owner approval |

---

## 16. Change, Deprecation, and Rollback Policy

### 16.1 Feature changes

A material future feature change must update:

- primary authority document;
- roadmap/backlog record;
- ADR where required;
- domain/schema/API/workflow documents;
- security model;
- tests;
- operations/runbooks;
- release notes.

### 16.2 Deprecation

Before deprecating a manual path, provider, model, API version, or file format:

- identify all active users and records;
- provide a migration or supported fallback;
- preserve historical readability;
- test rollback;
- document the deprecation date and owner;
- avoid removing evidence needed for disputes or audit.

### 16.3 Kill switches

Future optional capabilities should have scoped disablement where applicable:

- external AI provider;
- one AI use case;
- automatic segmentation;
- one validation provider;
- one bank integration;
- instruction submission;
- notification channel;
- public API credential;
- tenant support access.

A kill switch must not disable core audit, approval, ownership, or retention controls.

---

## 17. Phase Promotion Decision Record

Before promoting a capability or starting a phase, create a record containing:

```text
Decision ID
Current phase/stage
Proposed phase/stage
Business problem and evidence
Capability scope
Authoritative documents affected
Blocking ADRs
Security/privacy review
Financial authority impact
Evaluation evidence
Operational capacity impact
Cost estimate/budget
Fallback and kill switch
Release owner
Business approver
Security approver
QA approver
Operations approver
Decision and conditions
Review date
```

A coding agent may not infer phase promotion from code availability alone.

---

## 18. Future-Agent Rules

A coding agent or future team working from this roadmap must:

1. Read `16_Implementation_Documentation_Index.md` first.
2. Read the relevant authoritative documents, not only this roadmap.
3. Confirm the target phase and maturity stage.
4. List blocking ADRs before changing schema or contracts.
5. Preserve manual fallback.
6. Preserve exact human financial authority.
7. Use explicit commands rather than generic status updates.
8. Add idempotency, concurrency, audit, outbox, and negative tests to sensitive features.
9. Keep original files and versioned derived artifacts.
10. Separate suggestions from confirmed evidence and financial results.
11. Avoid adding tenant fields before Phase 4 architecture is approved.
12. Avoid sending production data to external providers without approved policy.
13. Deliver rollback, kill-switch, and observability changes with the feature.
14. Update this roadmap when a capability changes phase, scope, or status.

The agent must not:

- auto-confirm payments;
- auto-approve batches;
- auto-publish trader results;
- bypass manager recent authentication;
- silently resend uncertain bank API instructions;
- remove manual fallback;
- copy sensitive production datasets into Git;
- create unrestricted support impersonation;
- implement partial tenancy;
- present AI confidence as payment probability.

---

## 19. Roadmap Status Summary

```text
Phase 1A:
Authoritative implementation baseline; must be stabilized and proven operationally.

Phase 1B:
Eligible only after Phase 1A exit gate; focuses on optional assisted extraction and matching.

Phase 2:
Eligible only after governed Phase 1B evidence; focuses on segmentation, advanced matching, validation, and risk visibility.

Phase 3:
Eligible only with contractual/provider readiness and mature operations; focuses on integrations and scale.

Phase 4:
Optional; begins only after approved productization strategy; includes complete multi-company/SaaS design.
```

---

## 20. Final Roadmap Principle

The correct evolution path is:

```text
Reliable manual control
→ measured assistance
→ explainable intelligence
→ controlled integrations and scale
→ optional productization
```

Automation is successful only when it reduces effort or risk without weakening human accountability, auditability, privacy, recoverability, or the ability to complete the real business workflow safely.
