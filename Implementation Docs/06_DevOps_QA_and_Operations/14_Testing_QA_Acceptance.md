# 14 — Testing, QA, and Acceptance Specification

## Gold Trade Settlement Platform

**Document type:** Testing, quality assurance, validation, and release-gate specification  
**Version:** 1.1  
**Status:** Reviewed implementation baseline  
**Language:** English  
**Primary audience:** QA engineers, backend engineers, frontend engineers, DevOps engineers, security reviewers, technical leads, business owners, product owners, UAT participants, and coding agents  
**Applies to:** Phase 1A mandatory scope, with explicit gates for Phase 1B, Phase 2, Phase 3, and Phase 4  
**Authoritative dependencies:** Documents `00` through `13`, version 1.1

---

## Change Control

| Version | Summary |
|---|---|
| 1.0 | Initial testing, QA, and acceptance guide |
| 1.1 | Aligns all test layers and release gates with immutable batch versions, exact manager approval, payment-request revisions, mandatory idempotency, optimistic concurrency, transactional audit/outbox, secure file lifecycle, Phase 1A manual crop, evidence/publication versioning, single-tenant deployment, backup consistency, restore drills, and separation of duties |

This document is the authoritative test baseline for implementation and release decisions. When a test in this document conflicts with an older test assumption, this version controls unless an approved ADR or later implementation document explicitly supersedes it.

---

# 1. Purpose and Quality Position

The Gold Trade Settlement Platform handles high-value outgoing payments, incoming-payment verification, gold-sale settlement, bank files, bank evidence, trader records, beneficiary data, approvals, and dispute-sensitive audit history.

Testing must prove more than whether pages render or endpoints return `200`. It must prove that:

1. financial commands cannot bypass human authority;
2. manager approval is bound to the exact immutable batch version and content hash;
3. retries, corrections, and duplicate submissions cannot create untraceable financial effects;
4. traders cannot access another trader's information or mixed bank evidence;
5. files remain private, traceable, and recoverable;
6. audit and outbox records are committed atomically with financial state;
7. the platform remains usable with AI/OCR disabled;
8. backup and restore preserve database/file consistency;
9. deployment, migration, rollback, and incident procedures are testable;
10. the Persian/RTL interfaces reduce rather than introduce operational risk.

The central Phase 1A acceptance principle is:

> The center must be able to complete the operational gold and payment workflows inside the platform, with manual review and manual rectangular crop, without OCR, AI, automatic segmentation, direct bank APIs, external messaging applications, or SaaS dependencies.

---

# 2. Quality Principles

## 2.1 Business intent over imitation of manual tools

Tests must verify that the platform preserves the business need and control logic without reproducing unsafe spreadsheet, messaging, or copy/paste behavior.

Examples:

- a batch is not approved merely because an operator uploaded an Excel file;
- a screenshot is not automatically financial proof merely because it resembles a bank receipt;
- a result is not visible to a trader until an authorized publication is created;
- a manager does not approve a mutable list of rows;
- a correction creates a revision or replacement history rather than silently overwriting the prior record.

## 2.2 Human authority for financial finality

No OCR result, matching candidate, worker, scheduled task, rule engine, or provider response may directly:

- approve a payment batch;
- confirm an outgoing payment as paid or failed;
- create an active primary confirmed-evidence link without authorized human action;
- publish a payment result to a trader;
- dispatch gold;
- close a financial record.

Tests must fail any implementation that permits those actions through automation alone.

## 2.3 Exactness over tolerance

Financial tests use exact integer arithmetic.

```text
Canonical monetary unit: integer IRR
Floating-point arithmetic: prohibited
Unit inference from magnitude: prohibited
Implicit amount tolerance: prohibited
Complete payment condition: authoritative_paid_sum == requested_amount_irr
Overpayment condition: authoritative_paid_sum > requested_amount_irr -> reconciliation required
```

## 2.4 Traceability over destructive change

Confirmed or externally consequential financial records must be corrected through:

- revisions;
- replacement versions;
- retry attempts;
- correction records;
- superseded publications;
- replacement evidence links;
- audit events.

Normal application APIs must not hard-delete financial, approval, evidence, publication, bank-export, or audit history.

## 2.5 Backend authority

The frontend is a usability and safety layer. The backend remains authoritative for:

- authentication;
- authorization;
- ownership scope;
- state transitions;
- amount validation;
- content-hash validation;
- manager approval;
- idempotency;
- concurrency;
- file visibility;
- evidence cardinality;
- audit/outbox creation.

Every permission and workflow test must include direct API negative cases, not only hidden-button checks.

## 2.6 Risk-based test priority

Test priority follows potential harm:

1. unauthorized data exposure;
2. unauthorized money movement;
3. wrong amount, IBAN, beneficiary, source account, or bank mapping;
4. incorrect payment result or publication;
5. loss of evidence or audit history;
6. irrecoverable deployment or backup failure;
7. operational blockage;
8. performance and usability degradation;
9. cosmetic defects.

## 2.7 Production-like verification

Database, locking, partial unique indexes, transactions, and migrations must be tested against PostgreSQL. SQLite is not an acceptable substitute for repository, constraint, concurrency, or migration acceptance tests.

---

# 3. Phase Scope and Test Boundaries

## 3.1 Phase 1A — Operational Manual Core

Phase 1A testing is mandatory for:

- separate Trader PWA and Admin Web applications;
- authentication and revocable sessions;
- RBAC and trader ownership isolation;
- trader registration, approval, suspension, and reactivation;
- beneficiary reuse, normalization, duplicate warnings, and historical snapshots;
- outgoing payment request creation and immutable revisions;
- explicit IRR/Toman entry and canonical IRR storage;
- accountant review and `eligible_for_batching` decision;
- split/retry payment attempts;
- payment batch container and immutable batch versions;
- manager approval of the exact version and content hash;
- preview export and final export separation;
- export checksum and integrity verification;
- marking the exact bank export as sent;
- bank-result bundle upload;
- image/PDF preview and manual rectangular crop;
- receipt-segment provenance;
- matching candidate review;
- confirmed-evidence links;
- paid, failed, partial, retry, correction, and reconciliation flows;
- immutable trader-result publications;
- trader acknowledgement and dispute;
- gold-sale pricing, incoming-payment verification, settlement, and dispatch guards;
- secure file lifecycle and authorized downloads;
- audit, transactional outbox, idempotency, and optimistic concurrency;
- notifications and work queues;
- migration, deployment, monitoring, backup, restore, and incident procedures.

Phase 1A must pass with all AI/OCR feature flags disabled.

## 3.2 Phase 1B — Assisted Operations

Phase 1B adds optional assistance and must test:

- OCR on manually selected pages or crops;
- explainable matching candidates;
- provider abstraction;
- shadow-mode evaluation;
- human review of extracted fields;
- manual fallback during provider failure;
- provider cost and latency controls;
- prompt/model/schema versioning.

## 3.3 Phase 2 — Advanced Intelligence and Risk Controls

Phase 2 may include:

- automatic segmentation proposals;
- advanced duplicate/anomaly detection;
- richer explainable matching;
- controlled external verification providers;
- formal AI release gates.

Automatic proposals must continue to require authorized human confirmation.

## 3.4 Phase 3 — Integrations and Operational Scale

Phase 3 adds contract, resilience, and reconciliation tests for:

- bank APIs;
- accounting integrations;
- external notification providers;
- scaled workers and storage;
- higher availability and stronger operational monitoring.

## 3.5 Phase 4 — Productization and Multi-company

Multi-company/SaaS isolation is Phase 4. Phase 1A tests must not assume a partially implemented `organization_id` tenancy model.

---

# 4. Test Governance, Ownership, and Evidence

## 4.1 Required owners

| Responsibility | Required owner |
|---|---|
| Overall QA plan and release recommendation | QA lead or assigned technical lead |
| Financial workflow acceptance | Business owner and operational accountant |
| Manager-approval acceptance | Authorized manager representative |
| Security acceptance | Security reviewer or designated technical owner |
| Deployment, backup, and restore acceptance | DevOps/operations owner |
| Trader usability acceptance | Representative trader/UAT participant |
| Final production authorization | Named release authority |

A developer who implements a high-risk feature may contribute test evidence but must not be the sole approver of that feature's production acceptance.

## 4.2 Test evidence

For every release candidate, retain:

- test-run identifier;
- application commit and image digests;
- Alembic revision;
- environment identifier;
- feature-flag snapshot;
- bank-profile/mapping fixture versions;
- test data-set version;
- automated test reports;
- failed-test details;
- manual QA evidence;
- UAT sign-off;
- security review result;
- backup/restore drill result;
- known-risk acceptance records.

## 4.3 Test-case identifiers

Use stable identifiers:

```text
UT-*       Unit tests
DB-*       Database and migration tests
SVC-*      Backend command/service tests
API-*      API contract tests
FE-*       Frontend tests
E2E-*      End-to-end workflows
SEC-*      Security tests
CON-*      Concurrency/idempotency tests
FILE-*     File and storage tests
BANK-*     Bank file/export tests
AUD-*      Audit/outbox tests
OPS-*      Deployment/backup/restore tests
PERF-*     Performance/capacity tests
AI-*       AI/OCR tests
UAT-*      User acceptance tests
```

## 4.4 Traceability requirement

Every mandatory requirement must map to at least one test. Critical financial requirements should map to more than one layer, normally:

```text
Domain/unit test
+ service/database test
+ API negative/positive test
+ E2E or UAT scenario
```

---

# 5. Test Environments

## 5.1 Local development

Local development must provide:

- PostgreSQL;
- Redis;
- Backend API;
- Celery worker;
- both frontend applications;
- private local storage adapter;
- test mail/notification adapter if needed;
- AI/OCR disabled or mock-only;
- synthetic seed data.

## 5.2 Automated integration environment

CI integration tests must use disposable PostgreSQL and Redis services. It must support:

- clean-database migration;
- upgrade from the previous supported schema;
- transaction and locking tests;
- worker/outbox tests;
- storage adapter tests;
- both frontend builds.

## 5.3 Staging

Staging is mandatory and must resemble production in:

- Docker Compose topology;
- Nginx routing;
- two frontend deployments;
- Backend/Worker images;
- PostgreSQL major version;
- Redis major version;
- storage interface;
- session/cookie behavior;
- TLS behavior;
- health endpoints;
- backup jobs;
- logging and monitoring.

Staging must not contain production credentials or uncontrolled real financial data.

## 5.4 Production verification

Production smoke tests must avoid creating actual outgoing-payment or bank-submission records unless a formally isolated production test identity and bank profile exist.

Preferred production verification is:

- health/readiness checks;
- authentication with controlled test users;
- read-only dashboard and queue checks;
- authorized access to a designated non-sensitive fixture;
- worker heartbeat;
- storage and backup status;
- audit/event generation only for explicitly approved non-financial test actions.

---

# 6. Test Data and Fixture Strategy

## 6.1 Synthetic data only by default

Test data must be synthetic, anonymized, or explicitly approved for controlled use. Real bank files, phone numbers, IBANs, names, and payment evidence must never be committed to source control.

## 6.2 Required users

At minimum:

| Fixture | Purpose |
|---|---|
| Trader A | Active trader and ownership baseline |
| Trader B | Cross-trader isolation tests |
| Pending Trader | Approval-state tests |
| Suspended Trader | Blocked-operation tests |
| Accountant A | Request, batching, evidence, and result operations |
| Accountant B | Concurrency and separation tests |
| Manager A | Approval and sensitive-correction tests |
| Warehouse Operator | Dispatch-only tests |
| Business Admin | Business settings and account governance |
| Technical Admin | Technical settings without implicit financial authority |
| Read-only Auditor | Read-only and masking tests |
| Break-glass identity | Emergency-access tests, disabled by default |

## 6.3 Required bank configuration fixtures

Do not hard-code a real bank as the universal default. Maintain versioned synthetic fixtures:

- `BANK_A_PROFILE_V1`;
- `BANK_A_MAPPING_V1`;
- `BANK_A_MAPPING_V2`;
- `BANK_B_PROFILE_V1`;
- source account A;
- source account B;
- one invalid mapping fixture;
- one inactive profile fixture;
- one profile with split limits;
- one profile with time/cutoff rules.

## 6.4 Required financial fixtures

Include:

- single request, single attempt;
- request requiring split attempts;
- request revision changing IBAN;
- request revision changing amount/unit;
- failed attempt and retry lineage;
- partial payment;
- exact full payment;
- overpayment candidate;
- same amount for multiple beneficiaries;
- same beneficiary and amount on different dates;
- duplicate IBAN/name warning;
- blocked/superseded beneficiary;
- batch with multiple traders;
- mixed bank-result bundle;
- result received before sent marker;
- publication corrected after trader visibility;
- trader dispute;
- gold sale with partial incoming payments;
- physical dispatch and offset settlement examples.

## 6.5 Required file fixtures

Include versioned fixtures for:

- valid JPEG and PNG;
- valid multi-page PDF;
- rotated PDF page;
- low-resolution image;
- large but allowed file;
- oversized file;
- extension/MIME mismatch;
- corrupt PDF;
- corrupt Excel file;
- spreadsheet with formula-injection text;
- multi-row bank statement;
- export template fixture;
- mixed bank-result image;
- manually cropped segment;
- crop containing unrelated private information;
- file with duplicate checksum;
- simulated suspicious/malware-scanner result.

## 6.6 Golden files

Bank exports, result publications, and crop renderings may use golden fixtures, but comparisons must distinguish:

- meaningful business content;
- stable row ordering;
- exact integer values;
- expected metadata;
- file checksum where deterministic;
- acceptable renderer metadata variation where deterministic checksums are not guaranteed.

---

# 7. Test Pyramid and Mandatory Layers

The test suite must include:

1. domain/unit tests;
2. database/repository tests;
3. backend command/service tests;
4. API contract tests;
5. frontend unit/component/integration tests;
6. E2E workflow tests;
7. security tests;
8. concurrency/idempotency tests;
9. file/storage tests;
10. deployment, migration, backup, and restore tests;
11. manual QA and UAT.

A critical invariant is not considered covered merely because one E2E happy-path test passes.

---

# 8. Domain and Unit Tests

## 8.1 Money and unit rules

Mandatory tests:

| ID | Test |
|---|---|
| UT-MONEY-001 | Integer IRR is preserved exactly |
| UT-MONEY-002 | Toman input converts to IRR by exact multiplication by 10 |
| UT-MONEY-003 | Entered value and entered unit are retained |
| UT-MONEY-004 | Unit is never inferred from number magnitude |
| UT-MONEY-005 | Decimal/floating input is rejected |
| UT-MONEY-006 | Amount overflow bounds are enforced |
| UT-MONEY-007 | Formatted Persian/Latin digits normalize without changing value |
| UT-MONEY-008 | `paid_sum == requested_amount` produces paid |
| UT-MONEY-009 | `paid_sum < requested_amount` produces partial/failed based on attempts |
| UT-MONEY-010 | `paid_sum > requested_amount` produces reconciliation-required, never paid |

## 8.2 Payment splitting and retry

Test:

- below-limit amount creates one attempt;
- equal-to-limit creates one attempt;
- above-limit creates the exact configured split;
- sum of active attempts equals the request amount;
- bank profile version determines the rule;
- changing a bank rule does not reinterpret historical attempts;
- retry creates a new attempt linked to the failed attempt;
- superseded/cancelled attempts are excluded from authoritative paid sum;
- material beneficiary change requires a new request revision before retry.

## 8.3 State transition policies

For each state machine, test all allowed and forbidden transitions.

### Payment request states

```text
draft
submitted_to_center
under_accountant_review
needs_trader_correction
eligible_for_batching
batched
sent_to_bank
partially_paid
paid
failed
retry_required
result_ready_for_trader
result_published
trader_acknowledged
trader_disputed
cancelled
closed
```

### Payment attempt states

```text
created
included_in_batch_version
sent_to_bank
bank_result_pending
paid
failed
retry_required
superseded
cancelled
```

### Batch-version states

```text
draft
ready_for_approval
approved
rejected
superseded
```

### File states

```text
pending
quarantined
available
processing_failed
archived
retention_pending
deleted
```

## 8.4 Batch content hash

Test canonical hashing for:

- ordered rows;
- amount;
- beneficiary snapshot;
- IBAN snapshot;
- request revision;
- bank-profile version;
- mapping version;
- source account;
- relevant bank-reference fields.

The same canonical content must yield the same hash. Any material change must yield a different hash.

## 8.5 Evidence cardinality

Test:

- one active primary evidence per attempt;
- one active primary target per transaction segment;
- multiple supplementary links allowed;
- replacement deactivates/supersedes the old primary atomically;
- rejected matching candidates have no financial effect.

## 8.6 Publication rules

Test:

- publication snapshot is immutable;
- unsafe/internal evidence cannot be included;
- publication N+1 supersedes N;
- old publication remains traceable;
- trader acknowledgement/dispute applies to the correct publication version;
- masked IBAN rules are applied consistently.

## 8.7 Gold-sale guards

Test:

- pricing version is immutable after acceptance;
- incoming receipts do not equal confirmed funds until bank verification;
- partial incoming payments are represented correctly;
- overpayment requires review;
- dispatch cannot occur before settlement guard passes;
- physical dispatch and offset settlement use explicit settlement types.

---

# 9. Database, Repository, and Migration Tests

## 9.1 PostgreSQL requirement

Repository, locking, index, partial unique, migration, JSONB, and transaction tests must run against PostgreSQL.

## 9.2 Mandatory constraints

Test the database rejects:

- duplicate active primary evidence links;
- duplicate active batch allocation for an attempt;
- duplicate bank-profile version numbers;
- duplicate mapping version within profile scope;
- duplicate idempotency key scope with conflicting request hash;
- invalid negative/zero financial amount where prohibited;
- missing foreign-key relations;
- an export referencing approval/version from another batch;
- an approval that references a mismatched batch/version pair;
- a batch item referencing a non-current or invalid attempt where forbidden.

## 9.3 Cascade safety

Verify financial, audit, file, approval, export, and publication data are not removed by unsafe `ON DELETE CASCADE` operations.

## 9.4 Immutable records

Repository tests must reject normal updates to:

- finalized batch-version rows;
- approval decisions;
- final bank-export content metadata;
- historical payment-request revisions;
- active/previous publication snapshots;
- audit events.

## 9.5 Optimistic concurrency

Test `record_version` increments and stale updates fail without losing the newer user's change.

## 9.6 Work-queue indexes

Use query-plan checks for representative data volumes on:

- submitted payment requests;
- requests eligible for batching;
- manager approval queue;
- unresolved bank-result segments;
- failed/retry attempts;
- unpublished results;
- incoming-payment review queue;
- outbox dispatch queue;
- job retry queue.

## 9.7 Migration tests

CI must test:

1. migrate a clean database to head;
2. migrate the previous supported schema to head;
3. run a representative data migration;
4. start the new application against migrated data;
5. verify critical queries and constraints;
6. verify migration is safe to retry or has documented recovery behavior;
7. test downgrade only where explicitly supported;
8. test expand-and-contract compatibility when used.

---

# 10. Backend Command and Service Tests

## 10.1 Unit of Work atomicity

For each sensitive command, inject failures at each write boundary and prove there is no partial commit.

The following must commit or roll back together:

```text
Business state
Revision/version/history
Audit event
Outbox event
Idempotency result
```

## 10.2 Payment-request commands

Test:

- create draft;
- add immutable revision;
- submit current revision;
- reject stale revision submission;
- request trader correction;
- mark eligible for batching;
- cancel only from allowed states;
- prevent financial field mutation outside revision command.

## 10.3 Batch commands

Test:

- preview selection without mutation;
- create batch container;
- create draft version;
- deterministic split preview;
- finalize exact immutable version;
- reject invalid rows;
- create replacement version;
- mark older version superseded;
- invalidate prior approval after material change.

## 10.4 Manager approval command

Mandatory cases:

| ID | Case | Expected result |
|---|---|---|
| SVC-APR-001 | Correct manager, recent auth, current version, matching hash | Approved |
| SVC-APR-002 | Accountant attempts approval | Denied |
| SVC-APR-003 | Finalizer attempts self-approval | Denied by separation of duties |
| SVC-APR-004 | Stale version | Conflict/invalid |
| SVC-APR-005 | Hash mismatch | Denied and security/audit event |
| SVC-APR-006 | Missing recent authentication | Denied |
| SVC-APR-007 | Duplicate identical idempotent request | Original result returned |
| SVC-APR-008 | Same idempotency key, changed payload | `IDEMPOTENCY_KEY_REUSED` |
| SVC-APR-009 | Validation warning configured as blocking | Denied |
| SVC-APR-010 | Approval already decided | No second conflicting decision |

## 10.5 Export commands

Test:

- preview export can be generated before approval and is marked non-sendable;
- final export cannot be generated without valid approval;
- final export reads immutable row snapshots, not current beneficiary data;
- generated row count and total match the approved version;
- checksum is stored;
- content/hash mismatch quarantines export;
- final export cannot reference an approval from another version;
- formula-injection content is encoded or rejected per policy;
- exact export, not batch container, is marked sent.

## 10.6 Payment-result commands

Test:

- attempt must have been sent before ordinary result confirmation;
- unknown early bank result creates review task rather than silent success;
- candidate acceptance does not confirm payment;
- evidence-link confirmation does not itself set paid status;
- paid confirmation validates exact amount and evidence policy;
- failed confirmation records reason;
- partial aggregate status is recalculated centrally;
- overpayment blocks confirmation;
- retry preserves lineage;
- correction of published paid result follows sensitive-review/dual-control policy.

## 10.7 Publication commands

Test:

- preview does not make data trader-visible;
- publication requires authorized user and valid current financial result;
- publication includes only privacy-approved evidence;
- publication is immutable after creation;
- correction creates a new publication version;
- superseded publication is not presented as current;
- trader notification is emitted through outbox.

---

# 11. API Contract Tests

## 11.1 General contract

Verify:

- versioned `/api/v1` routes;
- Pydantic/OpenAPI schema consistency;
- standard error envelope;
- request/correlation ID;
- no ORM/internal fields in responses;
- trader and admin response schemas differ appropriately;
- raw storage keys are never returned.

## 11.2 Idempotency

For every mandatory command endpoint:

1. missing key returns the defined validation/precondition error;
2. first request succeeds;
3. identical replay returns the same logical result;
4. same key with different canonical payload returns `409 IDEMPOTENCY_KEY_REUSED`;
5. concurrent identical requests create one logical effect;
6. retry after simulated timeout-after-commit returns the original result.

## 11.3 ETag and `If-Match`

Test:

- mutable resource returns ETag;
- valid `If-Match` succeeds;
- missing header returns `428 PRECONDITION_REQUIRED` where required;
- stale header returns `412 VERSION_CONFLICT`;
- stale request does not overwrite current state;
- immutable snapshots use exact IDs/hash rather than mutable ETag semantics.

## 11.4 Authentication and CSRF

Based on the approved ADR, test:

- secure login/logout;
- revoked session rejection;
- session expiry;
- password-change session revocation;
- trader/admin authentication-domain isolation;
- CSRF enforcement for cookie-authenticated state-changing requests;
- recent-auth issuance, expiry, scope, and replay behavior.

## 11.5 Error codes

At minimum test stable handling of:

```text
VERSION_CONFLICT
PRECONDITION_REQUIRED
IDEMPOTENCY_KEY_REUSED
INVALID_STATE_TRANSITION
PERMISSION_DENIED
RECENT_AUTH_REQUIRED
APPROVAL_HASH_MISMATCH
EXPORT_INTEGRITY_MISMATCH
AMOUNT_UNIT_MISMATCH
RECONCILIATION_REQUIRED
FILE_NOT_AVAILABLE
FILE_QUARANTINED
EVIDENCE_CARDINALITY_CONFLICT
```

---

# 12. Frontend Tests

## 12.1 Two-app isolation

Test that:

- Trader PWA build excludes admin pages and privileged forms;
- Admin Web rejects trader sessions;
- route middleware does not flash protected content;
- shared packages do not expose admin-only DTOs to trader routes inadvertently;
- service-worker configuration is active only where intended.

## 12.2 Financial money components

Test:

- amount is handled as string/BigInt-safe integer;
- explicit `IRR`/`TOMAN` selection;
- live exact conversion;
- large amounts do not lose precision;
- copy/paste digits normalize correctly;
- decimal input is rejected;
- confirmation views show entered unit and canonical IRR.

## 12.3 Command submission safety

Test:

- double-click creates one logical command;
- timeout displays “checking completion” behavior;
- same idempotency key is reused for the same logical retry;
- a changed payload uses a new logical action/key;
- sensitive mutations do not use optimistic UI success;
- button state recovers correctly after server conflict.

## 12.4 Concurrency UX

For `412 VERSION_CONFLICT`:

- stale action is disabled;
- latest server state can be loaded;
- user's safe form input is preserved when possible;
- no automatic financial merge occurs;
- before/after comparison appears where specified.

## 12.5 Manager approval UI

Test display and behavior for:

- exact batch/version reference;
- exact total and row count;
- bank-profile version;
- mapping version;
- source account;
- hash fingerprint;
- warnings;
- ordered rows;
- stale approval banner;
- recent-auth dialog;
- rejection reason;
- no generic status dropdown.

## 12.6 Manual crop UI

Mandatory Phase 1A tests:

- image and PDF preview;
- page navigation;
- zoom/pan/rotation;
- rectangular selection;
- normalized coordinate creation;
- keyboard/non-drag controls;
- crop preview;
- worker processing state;
- retry after render failure;
- original file preservation;
- privacy-review checklist;
- external evidence fallback.

## 12.7 Publication UI

Test:

- trader sees only current publication by default;
- superseded publication is clearly labeled in history;
- masked IBAN displays correctly;
- full mixed bundle is never loaded;
- acknowledge/dispute targets exact publication;
- share/download uses the approved publication artifact.

## 12.8 Accessibility

Test at minimum:

- keyboard navigation;
- visible focus;
- dialog focus trap and return focus;
- semantic table headers;
- RTL tab order;
- status meaning not conveyed by color alone;
- screen-reader names for financial actions;
- crop controls usable without pointer drag;
- touch targets suitable for Trader PWA;
- reduced-motion compatibility.

---

# 13. End-to-End Phase 1A Workflows

## 13.1 Trader registration and approval — `E2E-TRADER-001`

**Given:** a new trader account.  
**When:** the trader registers.  
**Then:** the account is `pending_approval`, financial actions are unavailable, approval is audited, and activation permits only owned-data access.

Negative variants:

- pending trader attempts request creation;
- suspended trader attempts request creation;
- Trader A requests Trader B resource by ID.

## 13.2 Payment request with explicit unit — `E2E-PAY-001`

1. Trader enters amount in Toman.
2. UI shows exact IRR conversion.
3. Draft retains entered value/unit.
4. Trader submits the current revision.
5. Accountant sees the immutable revision snapshot.

Acceptance:

- no precision loss;
- no unit inference;
- canonical amount is integer IRR;
- duplicate warning does not silently block unless policy says so;
- audit records creation/submission.

## 13.3 Request correction and revision — `E2E-PAY-002`

1. Accountant requests correction.
2. Trader creates revision N+1 with corrected IBAN.
3. Revision N remains unchanged.
4. New attempt uses revision N+1.
5. historical attempt still displays revision N snapshot where applicable.

## 13.4 Accountant marks eligible for batching — `E2E-PAY-003`

Acceptance:

- accountant decision is not manager approval;
- invalid request cannot become eligible;
- correction-needed request cannot be selected;
- transition is audited.

## 13.5 Batch preview and immutable version — `E2E-BATCH-001`

1. Accountant selects eligible requests.
2. Server returns split preview.
3. Accountant creates batch and draft version.
4. Version is validated and finalized.
5. Content hash, total, row count, bank/mapping/source account are fixed.

Acceptance:

- duplicate allocation prevented;
- exact sum validated;
- finalized rows cannot be edited;
- later change requires replacement version.

## 13.6 Exact manager approval — `E2E-BATCH-002`

1. Different manager opens exact approval view.
2. Manager completes recent authentication.
3. Manager approves expected version/hash.
4. Approval record is append-only.

Negative variants:

- finalizer self-approval;
- stale version;
- changed hash;
- changed source account;
- duplicate click;
- expired recent authentication.

## 13.7 Stale approval invalidation — `E2E-BATCH-003`

1. Manager opens version 1.
2. Accountant creates replacement version 2 before decision.
3. Manager tries to approve version 1.
4. System blocks stale approval and points to current version.

No approval is transferred automatically.

## 13.8 Preview and final bank export — `E2E-EXPORT-001`

Acceptance:

- preview is clearly non-sendable;
- final export requires exact approval;
- row count/total/hash/mapping/source account match;
- file checksum is recorded;
- spreadsheet injection is neutralized;
- mismatch produces quarantine.

## 13.9 Mark exact export sent — `E2E-EXPORT-002`

1. Accountant downloads final export.
2. Download alone does not alter sent state.
3. Accountant records actual manual bank upload against exact export.
4. Attempts and batch move to sent/waiting states atomically.

## 13.10 Bank-result bundle and manual crop — `E2E-RESULT-001`

1. Accountant uploads mixed PDF/image bundle.
2. Files pass lifecycle validation.
3. Accountant opens authorized preview.
4. Accountant selects page and normalized rectangle.
5. Worker creates immutable derived crop.
6. Segment retains provenance and checksum.

Acceptance:

- AI disabled;
- original remains unchanged;
- crop failure does not confirm evidence;
- unrelated personal information blocks publication.

## 13.11 Candidate, evidence, and paid confirmation separation — `E2E-RESULT-002`

1. Candidate is created or selected manually.
2. Candidate is accepted for confirmation.
3. Authorized accountant creates primary evidence link.
4. Separate command confirms attempt paid.
5. Parent request recalculates.

Each step has separate permission, audit, and state effect.

## 13.12 Partial, failed, and retry — `E2E-RESULT-003`

Test:

- one split attempt paid, one failed -> partial/retry-required;
- retry attempt links to failed attempt and current request revision;
- successful retry produces exact requested total;
- failed and retry history remain visible.

## 13.13 Overpayment block — `E2E-RESULT-004`

A paid confirmation that would make authoritative paid sum exceed the request amount must:

- fail the ordinary command;
- create/identify reconciliation work;
- show excess amount;
- provide no “confirm anyway” path.

## 13.14 Publication to trader — `E2E-PUB-001`

1. Accountant previews publication.
2. Privacy-approved evidence is selected.
3. Publication version 1 is created.
4. Trader sees only version 1 data and own safe evidence.
5. Trader acknowledges or disputes.

## 13.15 Correct published result — `E2E-PUB-002`

1. A paid published result is found incorrect.
2. Sensitive correction task is created.
3. Replacement evidence/result is reviewed under approved dual-control policy.
4. Publication version 2 is created.
5. Version 1 becomes superseded, not deleted.
6. Trader is notified.

## 13.16 Gold-sale incoming payment — `E2E-GOLD-001`

Test:

- center sets pricing version;
- trader uploads receipt;
- bank statement is imported through versioned run;
- accountant confirms exact incoming payment match;
- partial and excess receipts are reviewed;
- dispatch guard blocks unsettled order;
- settlement/dispatch history is audited.

---

# 14. Bank File and Export QA

## 14.1 Bank mapping fixtures

Every supported production bank/mapping version must have:

- valid example input/output fixture;
- field mapping tests;
- required-column tests;
- row-order tests;
- amount-format tests;
- Persian/English encoding tests;
- formula-injection tests;
- maximum-length tests;
- source-account tests;
- business-owner validation record.

## 14.2 Final export integrity

Mandatory tests:

```text
approved version ID equality
approval content-hash equality
export content-hash equality
row-count equality
total-amount equality
mapping-version equality
source-account equality
file-checksum equality
```

## 14.3 Statement import runs

Test:

- original file retained;
- import run is versioned;
- reparse creates a new run;
- raw and normalized values retained;
- invalid rows are reported without corrupting accepted rows;
- duplicate fingerprint is flagged;
- prior run remains unchanged;
- bank dates retain raw values and normalized interpretation.

## 14.4 Mixed result bundles

Verify:

- one bundle may relate to multiple batches;
- unknown items are retained for review;
- processing one segment does not close unresolved segments;
- trader never receives the full mixed bundle;
- bundle processing remains possible without AI.

---

# 15. File, Storage, and Crop QA

## 15.1 Upload lifecycle

Test transitions:

```text
selected
uploading
pending validation
quarantined or available
processing preview
preview ready or processing_failed
archived/retention_pending/deleted only through governed flows
```

## 15.2 Validation

Test:

- extension and MIME agreement;
- content signature;
- size limits;
- image/PDF readability;
- spreadsheet parser safety;
- server-generated storage key;
- original filename treated as metadata only;
- suspicious file quarantine;
- unavailable file cannot become evidence.

## 15.3 Authorization

Test every category against every relevant role. Direct object-reference tests must prove that knowing `file_id` is insufficient.

## 15.4 Storage reconciliation

Simulate and detect:

- storage object without DB record;
- DB record without object;
- stale pending upload;
- derivative without source;
- checksum mismatch;
- stuck processing job;
- duplicate object write after retry.

Reconciliation must not automatically delete financial evidence.

## 15.5 Crop provenance

Verify persisted:

- source file;
- page number;
- normalized coordinates;
- source dimensions;
- rotation;
- renderer name/version;
- render parameters;
- derived file;
- checksum;
- actor/time.

---

# 16. Security and RBAC QA

## 16.1 Permission matrix

Maintain positive and negative tests for every permission in the security specification. Role-name checks alone are insufficient.

## 16.2 Trader isolation

Mandatory IDOR tests:

- Trader A reads Trader B request;
- Trader A reads Trader B beneficiary;
- Trader A downloads Trader B publication file;
- Trader A guesses mixed bank-bundle file ID;
- Trader A submits `trader_id` belonging to B;
- Trader A accesses Admin endpoint;
- Admin response accidentally includes unrelated trader data.

Every case must be denied without disclosing whether the target exists where appropriate.

## 16.3 Separation of duties

Test:

- batch finalizer cannot approve same version;
- technical admin cannot approve or confirm payment by default;
- read-only auditor cannot trigger hidden side effects;
- manager cannot bypass batch validation;
- worker cannot execute human financial commands;
- emergency access cannot be used after expiry.

## 16.4 Session and recent-auth

Test:

- secure cookie flags;
- logout revocation;
- password-change revocation;
- role-change/security-stamp invalidation;
- suspended account behavior;
- lockout and rate limiting;
- recent-auth expiry;
- recent-auth bound to current session/action class;
- CSRF rejection;
- no token leakage in URL/log/browser storage.

## 16.5 Break-glass

Test:

- disabled by default;
- explicit incident reference;
- limited scope and duration;
- alert generated;
- audit generated;
- expiry enforced;
- post-use review evidence retained.

## 16.6 Spreadsheet and injection security

Test:

- Excel formula injection;
- CSV injection if CSV is supported;
- XSS in notes/names/file names;
- path traversal;
- content-type confusion;
- malicious PDF/image parser failures;
- log injection/control characters;
- oversized request bodies.

---

# 17. Concurrency, Idempotency, and Race Conditions

## 17.1 Required concurrency cases

| ID | Race | Required outcome |
|---|---|---|
| CON-001 | Two accountants edit same mutable request | One succeeds; stale update receives conflict |
| CON-002 | Two accountants allocate same attempt | One active allocation only |
| CON-003 | Manager approves while replacement version is created | Stale approval blocked |
| CON-004 | Two managers approve same version | One logical decision |
| CON-005 | Two accountants create primary evidence links | One active primary link |
| CON-006 | Two paid confirmations target same attempt | One logical result |
| CON-007 | Two final-export requests | One idempotent logical export per command/policy |
| CON-008 | Mark sent while export becomes quarantined | Integrity/locking policy prevents invalid send state |
| CON-009 | Publication creation and correction overlap | One authoritative current publication |
| CON-010 | Retention job races with legal hold | Legal hold wins; data preserved |

## 17.2 Timeout-after-commit

For every critical command, simulate loss of HTTP response after database commit. Retrying with the same key must return the committed result without duplicate effects.

## 17.3 Worker retries

Simulate worker crash:

- before side effect;
- after file write but before DB update;
- after DB job-state update;
- after outbox claim;
- during notification send.

The system must converge through idempotency and reconciliation.

---

# 18. Audit, Outbox, and Security-Event QA

## 18.1 Audit atomicity

Inject audit insert failure into each sensitive command. The business command must roll back.

## 18.2 Required audit fields

Verify where applicable:

- actor ID/type/role;
- session ID;
- authentication assurance;
- recent-auth reference;
- action;
- entity and parent entity;
- before/after values or safe snapshots;
- reason;
- correlation ID;
- idempotency-key hash;
- entity version;
- immutable content hash;
- IP/user agent;
- timestamp.

## 18.3 Redaction

Audit/log tests must ensure they do not contain:

- passwords;
- session secrets;
- raw idempotency keys;
- storage credentials;
- AI keys;
- raw file contents;
- unnecessarily full IBANs;
- unbounded provider payloads.

## 18.4 Append-only behavior

Application roles must not update/delete audit or approval rows. Audit APIs are read-only.

## 18.5 Transactional outbox

Test:

- event written in same transaction;
- event not written if command rolls back;
- dispatcher claims with safe locking;
- retry does not duplicate user-visible effect;
- poison event reaches failure/dead-letter handling;
- old pending outbox age triggers alert;
- notification failure does not roll back financial state.

---

# 19. Performance and Capacity QA

## 19.1 Initial performance targets

On an approved healthy production-like environment:

| Operation | Initial target |
|---|---:|
| Normal API p95 | under 500 ms where practical |
| Trader dashboard | under 3 seconds |
| Admin operational queue | under 3 seconds with pagination |
| Upload acknowledgement | under 5 seconds for normal files |
| Moderate final export | under 30 seconds or accepted async workflow |
| Manual evidence/crop command acknowledgement | under 5 seconds excluding worker completion |

These are validation targets, not unconditional guarantees. Test data volume and environment must be recorded.

## 19.2 Capacity scenarios

Test with approved pilot assumptions for:

- trader count;
- daily request count;
- attempts per request;
- rows per batch;
- pages/files per result bundle;
- concurrent accountant/manager sessions;
- file-storage growth;
- queue backlog;
- audit growth.

Unknown expected volumes remain a production decision and must not be hidden behind arbitrary hard-coded limits.

## 19.3 Degradation behavior

Test:

- Redis unavailable;
- worker unavailable;
- storage slow;
- AI provider unavailable;
- notification adapter unavailable;
- database near connection limit;
- disk warning threshold;
- large queue backlog.

Core manual operations must fail safely and show actionable states.

---

# 20. Backup, Restore, Disaster Recovery, and Operations QA

## 20.1 Backup set completeness

A valid backup set includes:

- PostgreSQL;
- original file storage;
- derived evidence and publication artifacts;
- bank exports and result bundles;
- audit/security data;
- application release/image digests;
- Alembic revision;
- configuration metadata excluding exposed secrets;
- consistency manifest.

## 20.2 Backup verification

Automated tests/checks verify:

- command success;
- non-zero plausible size;
- checksum;
- encryption status;
- off-server copy completion;
- manifest creation;
- alert on failure.

## 20.3 Full restore drill — `OPS-RESTORE-001`

Restore to a separate environment and verify:

1. database starts;
2. application starts with correct schema revision;
3. admin authentication/RBAC works;
4. trader isolation works;
5. payment request/revision can be read;
6. batch version and approval hashes match;
7. final export exists and checksum matches;
8. bank-result bundle can be read by authorized user;
9. crop/evidence provenance is intact;
10. publication version history is intact;
11. audit and outbox history are present;
12. sampled DB file references resolve;
13. no unexpected orphan/missing files exist.

## 20.4 RPO/RTO validation

Once ADR values are approved, measure actual restore performance and data-loss window. Production must not claim an RPO/RTO that has not been tested.

## 20.5 Deployment and rollback

Test:

- pinned-image deployment;
- same artifact promotion from staging;
- readiness checks instead of fixed sleeps;
- controlled maintenance mode;
- worker pause/resume;
- failed migration response;
- application rollback against compatible schema;
- forward-fix path;
- database restore escalation;
- no `down -v` or destructive volume behavior.

## 20.6 Health endpoints

Verify:

```text
/api/v1/health/live
/api/v1/health/ready
/api/v1/health/dependencies
/api/v1/health/workers
```

Public health output must not expose internal URLs, credentials, file names, or provider secrets.

---

# 21. AI/OCR QA for Phase 1B+

AI tests do not gate Phase 1A when AI is disabled. When enabled, they must include:

## 21.1 Authority boundary

- AI creates suggestions only;
- no AI-created approval;
- no AI-created paid/failed final result;
- no AI-created active primary evidence without human command;
- no AI-created trader publication.

## 21.2 Versioned reproducibility

Record and test:

- input manifest/checksum;
- provider and adapter version;
- model version;
- prompt/template version/hash;
- schema version;
- normalization version;
- segmentation version;
- matching configuration version.

## 21.3 Evaluation dataset

Use versioned synthetic/redacted datasets covering:

- rotated/blurred scans;
- multi-page PDFs;
- ambiguous amount units;
- same-amount candidates;
- split attempts;
- missing fields;
- duplicate evidence;
- privacy-risk regions;
- adversarial document text/prompt injection.

## 21.4 Metrics and release gates

Measure:

- exact amount accuracy;
- IBAN accuracy;
- tracking-number accuracy;
- segmentation precision/recall or IoU;
- candidate recall@K;
- top-1 precision;
- ambiguity detection;
- high-risk false-positive count;
- latency;
- cost;
- human correction rate.

Thresholds must be approved against a named dataset and configuration. A generic confidence percentage is not sufficient.

## 21.5 Shadow and limited rollout

Test shadow mode before operational suggestions. AI failure or budget exhaustion must leave manual processing available.

---

# 22. Manual QA and Persian/RTL Validation

Manual QA must cover:

- Persian labels and terminology;
- RTL layout and navigation;
- numeric LTR fields inside RTL forms;
- IBAN/tracking/hash readability;
- Jalali display with exact UTC-backed timestamps;
- large amount readability;
- responsive Trader PWA;
- dense but usable accountant workspace;
- manager approval clarity;
- crop controls under realistic documents;
- privacy review;
- keyboard operation;
- low-bandwidth behavior;
- error and conflict messages;
- no messaging-app-like ambiguity.

---

# 23. User Acceptance Testing

## 23.1 Required UAT participants

At minimum:

- representative trader;
- operational accountant;
- approving manager;
- warehouse/settlement operator when gold dispatch is in scope;
- business owner/product owner;
- technical/operations representative.

## 23.2 Mandatory UAT scenarios

| ID | Scenario |
|---|---|
| UAT-001 | Trader registration and approval |
| UAT-002 | IRR/Toman request creation and correction revision |
| UAT-003 | Accountant review and eligible-for-batching decision |
| UAT-004 | Split preview and immutable batch-version finalization |
| UAT-005 | Manager exact-version approval with recent authentication |
| UAT-006 | Preview/final export and exact sent marker |
| UAT-007 | Mixed result bundle and manual crop |
| UAT-008 | Evidence confirmation and paid result |
| UAT-009 | Partial failure and retry |
| UAT-010 | Overpayment/reconciliation block |
| UAT-011 | Trader publication, acknowledgement, and dispute |
| UAT-012 | Wrong evidence/result correction and publication N+1 |
| UAT-013 | Cross-role denial and trader isolation |
| UAT-014 | Incoming payment and gold dispatch guard |
| UAT-015 | Backup/restore evidence review by operations owner |

## 23.3 UAT sign-off

Sign-off must identify:

- release candidate;
- scenarios executed;
- results;
- unresolved findings;
- approved workarounds;
- named approvers;
- date;
- environment;
- bank fixture/config versions.

UAT cannot waive critical security or financial-integrity defects.

---

# 24. Defect Severity and Release Policy

## 24.1 Critical — release blocker

Examples:

- cross-trader data exposure;
- unauthorized approval or payment confirmation;
- approval not bound to exact version/hash;
- wrong export rows/amount/source account;
- undetected export-integrity mismatch;
- financial state committed without audit;
- loss/corruption of financial records or files;
- failed restore of required records;
- overpayment accepted as normal paid result;
- full mixed bank bundle exposed to trader;
- production secret exposure;
- core manual workflow unavailable with AI disabled.

## 24.2 High — normally release blocker

Examples:

- broken batch/retry/publication workflow;
- stale concurrency update overwrites current data;
- idempotency duplicates a financial effect;
- required permission not enforced;
- primary evidence uniqueness failure;
- upload/download failure for core evidence;
- missing sensitive-action audit metadata;
- manager recent-auth or separation-of-duty bypass;
- backup or monitoring not functioning.

A High defect may only be accepted through a formal, time-bounded risk decision by authorized business, technical, and security owners. It must not concern unauthorized money movement or data exposure.

## 24.3 Medium

A workaround exists and financial integrity, confidentiality, and recoverability remain intact.

## 24.4 Low

Cosmetic or non-blocking improvement with no material operational risk.

---

# 25. Release Gates

## 25.1 Development-complete gate

Required:

- implementation matches current docs;
- no arbitrary status mutation;
- migrations included;
- developer tests pass;
- OpenAPI regenerated;
- both frontend apps build;
- code review complete;
- no critical TODO or disabled security control hidden in code.

## 25.2 QA-ready gate

Required:

- staging deployed from immutable artifacts;
- fixture versions recorded;
- health/readiness passing;
- test users/permissions configured;
- workers and storage available;
- audit/outbox observable;
- known-issues list prepared.

## 25.3 UAT-ready gate

Required:

- all critical automated suites pass;
- no open Critical defect;
- security negative tests pass;
- migration test passes;
- backup job works;
- manual QA smoke passes;
- UAT scripts and data are prepared.

## 25.4 Production-release gate

All of the following are mandatory:

- no open Critical defect;
- no unaccepted High defect;
- signed UAT approval;
- security review complete;
- separation-of-duty tests pass;
- idempotency and concurrency tests pass;
- export-integrity suite passes;
- file/trader isolation suite passes;
- clean and upgrade migration tests pass;
- encrypted off-server backup configured;
- successful full restore drill recorded;
- monitoring/alerts assigned to named owners;
- runbooks reviewed;
- rollback/forward-fix plan approved;
- initial bank profiles, mappings, and source accounts validated;
- production secrets and session controls configured;
- AI disabled unless separately approved;
- release artifacts/digests recorded.

## 25.5 Post-deployment gate

Before declaring deployment complete:

- all health endpoints pass;
- both frontends load;
- controlled authentication tests pass;
- worker heartbeat and queue flow pass;
- storage access check passes;
- DB schema revision verified;
- monitoring shows no unexpected errors;
- backup schedule remains active;
- deployment outcome is recorded.

---

# 26. CI/CD Quality Gates

CI must fail on:

- backend lint/format/type failures;
- frontend lint/format/TypeScript failures;
- unit or integration test failure;
- PostgreSQL migration failure;
- OpenAPI compatibility/generation failure;
- unhandled status mapping;
- both-app build failure;
- Docker image build failure;
- secret scan finding;
- critical dependency/container vulnerability under approved policy;
- security test failure;
- required accessibility smoke failure;
- documentation/contract mismatch for changed API or state machine.

A recommended pipeline:

```text
Static analysis
→ unit tests
→ PostgreSQL integration tests
→ API contract tests
→ frontend component tests
→ security/concurrency tests
→ clean and upgrade migration tests
→ build immutable images
→ container/dependency/secret scans
→ deploy ephemeral environment
→ E2E smoke
→ publish signed test artifacts
```

---

# 27. Smoke Test Checklist

## 27.1 Staging smoke

- Trader PWA loads.
- Admin Web loads.
- Trader/Admin session separation works.
- Accountant queue loads.
- Manager approval queue loads.
- Test request/revision can be created.
- Test batch version can be finalized.
- Test manager approval succeeds with exact hash.
- Preview and final export behavior is correct.
- Test bundle upload works.
- Manual crop works.
- Evidence/result/publication test works.
- Audit/outbox records appear.
- Authorized and unauthorized file download tests pass.
- Worker heartbeat and queues pass.
- health endpoints pass.

## 27.2 Production smoke

Use non-financial/read-only verification unless a formal production test scope exists:

- HTTPS and both apps;
- controlled login/logout;
- read-only queues/dashboard;
- authorized fixture download;
- session and permission behavior;
- health/readiness;
- worker heartbeat;
- monitoring and backup status;
- release/schema version.

---

# 28. Regression Checklist

Before each release, cover:

- auth/session/CSRF/recent-auth;
- RBAC and trader isolation;
- money and unit conversion;
- request revision workflow;
- split/retry logic;
- batch version/hash/approval;
- preview/final export integrity;
- sent marker;
- bank-result bundle;
- manual crop and provenance;
- candidate/evidence/result separation;
- paid/failed/partial/overpayment;
- publication and correction;
- incoming payment and dispatch guard;
- file lifecycle/authorization;
- audit/outbox/idempotency/concurrency;
- migration;
- backup/restore;
- health/monitoring;
- Persian/RTL/accessibility;
- AI-disabled manual fallback.

---

# 29. Phase 1A Final Acceptance Criteria

Phase 1A is accepted only when all statements below are demonstrated by test evidence.

## 29.1 Financial integrity

- Money uses exact integer IRR.
- Entered amount and unit are retained.
- Request revisions preserve history.
- Attempts preserve split/retry lineage.
- Paid sum rules are exact.
- Overpayment is blocked for reconciliation.
- Finalized batch versions are immutable.
- Manager approves exact version/hash.
- Every outgoing batch requires manager approval.
- Final export matches approved snapshot.
- Exact export sent to bank is recorded.

## 29.2 Result and evidence integrity

- Manual crop works with AI disabled.
- Original bank files remain immutable.
- Candidate, confirmed evidence, financial result, and publication are separate decisions.
- Evidence cardinality is enforced.
- Wrong evidence/result correction preserves history.
- Publications are versioned and privacy-safe.

## 29.3 Security

- Trader ownership isolation is proven.
- Backend RBAC is proven.
- Technical admin has no implicit financial authority.
- Separation of duties is enforced.
- Sessions are revocable.
- Recent authentication protects manager approval.
- Files are private and authorized per request.
- Audit is append-only for application roles.

## 29.4 Reliability

- Idempotency prevents duplicate financial effects.
- Optimistic concurrency prevents lost updates.
- Transactional outbox prevents lost side effects.
- Worker retries are safe.
- Redis loss does not lose business truth.
- storage reconciliation detects inconsistencies.

## 29.5 Operations

- staging matches production architecture sufficiently;
- migrations pass;
- immutable release artifacts are promoted;
- off-server backup exists;
- full restore succeeds;
- health/monitoring/alerts work;
- deployment, rollback, restore, and incident runbooks exist and are assigned.

## 29.6 User experience

- Trader PWA is mobile-first and Persian/RTL;
- Admin Web supports dense controlled work queues;
- manager sees exact approval snapshot;
- amount/unit display reduces zero-count mistakes;
- conflict, timeout, and file-processing states are understandable;
- accessibility minimums are met.

---

# 30. Non-acceptable Implementation Patterns

Reject the release if it includes any of the following:

1. generic `PATCH status` for financial transitions;
2. manager approval of a mutable batch container;
3. final export generated from current mutable beneficiary data;
4. approval transferred automatically to a replacement version;
5. optional idempotency on required financial commands;
6. silent retry with a new key after timeout;
7. floating-point money;
8. inferred IRR/Toman unit;
9. direct publishing of a receipt segment instead of publication snapshot;
10. AI/worker final financial authority;
11. full mixed bank bundle visible to traders;
12. evidence deletion instead of replacement history;
13. application role able to edit/delete audit records;
14. public storage paths or unprotected signed links;
15. SQLite used as the only database acceptance environment;
16. production deployment without restore proof;
17. production named storage volume with no documented host path/backup coverage;
18. partial multi-tenancy in Phase 1A;
19. technical admin granted broad financial permissions by default;
20. tests that use uncontrolled real financial data.

---

# 31. Open Decisions and ADR-dependent Tests

Before production, finalize and test:

1. authentication/session transport;
2. session idle/absolute timeout;
3. manager MFA/strong-auth mechanism;
4. recent-auth duration and action scope;
5. exact separation-of-duty policy;
6. text-only confirmation policy;
7. evidence requirement for paid/publication;
8. dual control for correction of published paid result;
9. IBAN masking by role and publication;
10. production malware scanner behavior;
11. upload and bundle size limits;
12. expected pilot volume;
13. initial bank profiles/mappings/source accounts;
14. hosting/storage adapter;
15. RPO/RTO;
16. backup and restore cadence;
17. retention/legal-hold authority and periods;
18. alert ownership and support hours;
19. production UAT signatories;
20. AI provider/privacy/evaluation policy when enabled.

An unresolved ADR may be acceptable for implementation only when the corresponding feature remains disabled or a secure temporary policy is explicitly documented. It is not acceptable to silently choose a weaker behavior in code.

---

# 32. Instructions for Coding Agents

A coding agent must:

1. derive tests from current domain/API/workflow documents;
2. create negative tests before relying on frontend controls;
3. use PostgreSQL for database acceptance tests;
4. test exact version/hash approval;
5. test mandatory idempotency and stale `If-Match` behavior;
6. test audit/outbox atomicity;
7. test manual crop in Phase 1A;
8. keep Candidate, Evidence, Result, and Publication tests separate;
9. preserve historical records in fixtures and assertions;
10. test trader file isolation by direct guessed IDs;
11. test timeout-after-commit and duplicate-click behavior;
12. use synthetic/redacted bank fixtures;
13. never place production secrets or real financial files in tests;
14. update traceability when requirements or endpoints change;
15. fail CI when state/API/schema documentation diverges;
16. avoid brittle tests based only on localized text when semantic selectors are available;
17. retain business-critical golden fixture versions;
18. include recovery and cleanup for test-created files/jobs;
19. test AI-off mode as a first-class configuration;
20. never mark a release accepted based only on happy paths.

---

# 33. Final QA Position

```text
Test strategy direction: Approved
Phase 1A test scope: Finalized
Financial integrity test baseline: Ready
Security/RBAC test baseline: Ready
Idempotency/concurrency test baseline: Ready
Manual crop and evidence test baseline: Ready
Backup/restore acceptance baseline: Ready
UAT and release gates: Ready
Production release approval: Pending execution evidence and unresolved ADR decisions
```

A release is not production-ready because the code compiles or the main workflow works once. It is production-ready only when financial invariants, authorization boundaries, exact approval, traceability, recoverability, and operational fallback have been demonstrated under positive, negative, concurrent, failure, and recovery conditions.
