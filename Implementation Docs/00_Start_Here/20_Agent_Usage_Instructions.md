# 20 — Agent Usage Instructions

## Gold Trade Settlement Platform

**Document type:** Coding Agent Operating Protocol  
**Document ID:** `20_Agent_Usage_Instructions`  
**Version:** `1.1`  
**Status:** Authoritative agent-execution baseline  
**Language:** English  
**Primary audience:** AI coding agents, implementation agents, software engineers, technical leads, reviewers, QA engineers, security reviewers, and release engineers  
**Primary phase:** Phase 1A — Operational Manual Core  
**Last revision purpose:** Align agent behavior with authoritative documents `00` through `22` version 1.1 and the governed historical archive `23`

---

# 1. Purpose

This document defines how a coding agent must read, interpret, plan, implement, test, report, and hand over changes for the Gold Trade Settlement Platform.

It is not a product specification, schema specification, API specification, or replacement for the specialized documents. It is the execution protocol that prevents an agent from:

- choosing the wrong source of truth;
- inventing financial rules;
- implementing future-phase automation inside Phase 1A;
- creating unsafe generic CRUD for financial records;
- bypassing exact batch-version approval;
- skipping idempotency, concurrency, audit, or outbox behavior;
- exposing private files or cross-trader data;
- treating AI output as financial truth;
- creating database migrations before understanding the domain and workflow;
- reporting a task as complete without implementation evidence.

The governing principle is:

> **Preserve the business need and control logic, not the limitations of the previous manual tool.**

The agent must modernize execution while preserving financial authority, traceability, privacy, and human control.

---

# 2. Authority and Document Status

## 2.1 Canonical documents

For documents already revised, the canonical implementation source is the file ending in `.md`.

Examples:

```text
02_Domain_Model_and_Business_Rules.md
05_API_Specification.md
12_Security_RBAC_Audit.md
```

Files without the `_v1.1` suffix are historical version 1.0 baselines unless the documentation index explicitly states otherwise.

Files ending in `.diff` are review evidence only. They are not implementation authority.

## 2.2 Current package status

At the time of this revision:

```text
00–22 v1.1  → authoritative implementation and execution package
23 v1.1     → governed historical Persian discovery archive only
*.diff      → review evidence only
unsuffixed  → historical version 1.0 files
```

A supporting, historical, original, or review-evidence document must not override the topic owner identified by the documentation index.

## 2.3 Topic authority

The agent must use the document that owns the topic.

| Topic | Primary authority |
|---|---|
| Product scope and fixed decisions | `00`, `01` |
| Domain entities and financial invariants | `02` |
| Architecture and service boundaries | `03` |
| Database representation and constraints | `04` |
| HTTP contract and command semantics | `05` |
| Statuses, transitions, and workflow guards | `06` |
| High-level UI/UX direction | `07` |
| Bank files, imports, exports, results, evidence | `08` |
| AI/OCR governance and provider abstraction | `09` |
| Backend coding architecture | `10` |
| Frontend coding architecture | `11` |
| Security, RBAC, audit, ownership, file access | `12` |
| Deployment and operations architecture | `13` |
| Testing, UAT, and release gates | `14` |
| Milestones, dependencies, and implementation order | `15` |
| Documentation governance and conflict ownership | `16` |
| Future phases and backlog | `17` |
| Production commands and operational runbooks | `18` |
| Client packaging and distribution | `19` |
| Coding-agent execution behavior | `20` |
| Detailed UI design system and screens | `21` |
| UX journeys, interaction, and recovery | `22` |
| Historical Persian discovery reasoning | `23` — context only, never implementation authority |

## 2.4 No “highest file number wins” rule

A later-numbered document does not automatically override an earlier authoritative document.

Examples:

- file `20` cannot redefine a domain invariant owned by file `02`;
- file `19` cannot weaken security owned by file `12`;
- file `17` cannot move a Phase 2 feature into Phase 1A without a formally approved scope change;
- files `21` and `22` cannot introduce workflow transitions that conflict with file `06`.

---

# 3. Required Reading Protocol

## 3.1 Before the first task in the repository

The agent must read in this order:

1. `16_Implementation_Documentation_Index.md`
2. `15_Agent_Implementation_Plan.md`
3. `20_Agent_Usage_Instructions.md`
4. `00_Master_Implementation_Blueprint.md`
5. `01_Product_Requirements_PRD.md`
6. `02_Domain_Model_and_Business_Rules.md`
7. `06_Workflows_and_State_Machines.md`
8. `03_System_Architecture.md`
9. `04_Database_Schema.md`
10. `05_API_Specification.md`
11. `12_Security_RBAC_Audit.md`
12. `14_Testing_QA_Acceptance.md`
13. the specialized documents relevant to the task.

The agent does not need to reread every document in full before every small task, but it must identify and reread the controlling sections for that task.

## 3.2 Specialized reading by task

### Backend financial command

Read at minimum:

```text
02, 04, 05, 06, 10, 12, 14, 15, 20
```

Add `08` for bank, evidence, export, result, or publication work.

### Frontend financial screen

Read at minimum:

```text
01, 05, 06, 07, 11, 12, 14, 15, 20, 21, 22
```

File `21` owns detailed screen/component behavior and file `22` owns journeys, interaction, and recovery. Neither may override domain, workflow, API, or security authorities.

### Database migration

Read at minimum:

```text
02, 04, 06, 10, 12, 14, 15, 20
```

### File-processing or manual-crop task

Read at minimum:

```text
03, 04, 05, 08, 10, 11, 12, 13, 14, 18, 20
```

### AI/OCR task

Read at minimum:

```text
02, 03, 05, 08, 09, 10, 12, 13, 14, 17, 20
```

### Deployment or operational task

Read at minimum:

```text
03, 10, 12, 13, 14, 15, 18, 19, 20
```

## 3.3 Reading evidence

Before coding, the agent must list:

- documents read;
- exact sections used;
- authority owner for each major decision;
- conflicts found;
- unresolved ADRs;
- assumptions that remain.

A vague statement such as “I read the docs” is not sufficient.

---

# 4. Phase Boundary

## 4.1 Phase 1A definition

Phase 1A is a complete manual operational core.

It must work without:

- OCR;
- AI;
- automatic segmentation;
- automatic matching;
- bank API integration;
- open banking;
- native Android or Windows applications;
- in-app chat;
- subscription billing;
- multi-company/SaaS architecture.

## 4.2 Phase 1A required capabilities

Phase 1A includes, at minimum:

- separate Trader PWA and Admin Web applications;
- authentication, revocable sessions, RBAC, and ownership checks;
- trader onboarding and status management;
- beneficiary management;
- outgoing payment requests with immutable revisions;
- accountant review and eligibility for batching;
- deterministic split preview and payment attempts;
- logical payment batches with immutable batch versions;
- manager approval of an exact batch version and content hash;
- preview and final bank exports;
- exact final-export integrity checks;
- explicit mark-as-sent action for the exact export;
- bank-result bundle upload and review;
- internal manual image/PDF preview;
- **manual rectangular crop inside the admin application**;
- receipt segments with provenance and checksums;
- matching candidates separated from confirmed evidence;
- human confirmation of paid or failed attempts;
- retry attempts;
- immutable trader result publications;
- gold-sale and incoming-settlement operational flow;
- secure private files;
- audit, idempotency, optimistic concurrency, outbox, backup, and restore.

## 4.3 Future features must not leak into Phase 1A

The agent may add an interface, port, disabled feature flag, or clearly isolated extension point for a later feature only when it does not:

- add unnecessary tenant fields to Phase 1A tables;
- create a second implementation path;
- require a provider SDK in the core domain;
- create an unfinished user-facing workflow;
- weaken the manual fallback;
- delay a required Phase 1A control;
- add operational complexity without current value.

## 4.4 Manual-first does not mean imitating manual tools

The agent must not reproduce messaging-app or spreadsheet behavior merely because the previous process used those tools.

Correct modernization examples:

- replace free-form chat approvals with explicit commands and reasons;
- replace mutable spreadsheet rows with immutable batch versions;
- replace shared bank screenshots with private source files and trader-safe publication artifacts;
- replace manual retry confusion with explicit new payment attempts;
- replace silent correction with governed replacement and supersession.

---

# 5. Non-Negotiable Domain and Financial Rules

## 5.1 Money

- Canonical money is integer Iranian Rial.
- Python/backend money uses integer types.
- Database money uses `BIGINT` or the approved integer representation.
- Frontend must not use JavaScript floating-point for financial calculation.
- Original entered value and unit must be retained.
- Unit must be explicit: IRR or Toman.
- The system must not infer unit from magnitude.
- Toman-to-IRR conversion must be exact multiplication by ten.

## 5.2 Payment Request and Revision

A Payment Request represents business intent.

A material change creates a new immutable request revision.

Material fields include, at minimum:

- beneficiary;
- beneficiary identity snapshot;
- destination IBAN snapshot;
- amount;
- original entered unit and value;
- description when financially relevant;
- relevant attachments.

An existing attempt remains linked to the exact revision used for that attempt.

## 5.3 Payment Attempt

A Payment Attempt represents a bank execution unit.

One request may have one or many attempts.

A retry creates a new attempt. It does not rewrite the previous attempt.

## 5.4 Payment Batch and Batch Version

A Payment Batch is a logical container.

A Payment Batch Version is the exact ordered financial snapshot.

After finalization:

- the version is immutable;
- ordered items are immutable;
- row count and total are authoritative;
- bank profile version is fixed;
- mapping version is fixed;
- source account is fixed;
- content hash is fixed.

A material change requires a replacement version.

## 5.5 Manager approval

The manager approves:

```text
exact PaymentBatchVersion
+ exact content hash
+ exact total
+ exact row count
+ exact ordered rows
+ exact bank/mapping/source-account context
```

The manager does not approve a mutable request or a generic batch container.

Approval must not silently transfer to a replacement version.

## 5.6 Bank export

- Preview export is visibly non-sendable.
- Final export can be generated only from the approved exact version.
- Final export must be deterministic.
- Integrity must be checked before download for submission and before marking sent.
- Download does not mean sent.
- Mark-as-sent targets the exact final export.
- Export mismatch requires quarantine, not “download anyway.”

## 5.7 Bank result concepts

The agent must preserve separation between:

```text
BankResultBundle
FileObject / DerivedArtifact
ReceiptSegment
MatchingCandidate
ConfirmedEvidenceLink
PaymentAttemptResult
PaymentResultPublication
```

These concepts must not be collapsed into one generic attachment or result table.

## 5.8 Manual crop

Manual rectangular crop is required in Phase 1A.

A crop must retain:

- source file;
- source page;
- source dimensions;
- rotation;
- normalized decimal-string coordinates;
- renderer and renderer version;
- processing parameters;
- output checksum;
- derivation relationship;
- processing status.

Creating a crop does not:

- confirm evidence;
- mark a payment paid;
- publish a result;
- approve a batch.

## 5.9 Candidate, evidence, result, publication

The required sequence is:

```text
Matching candidate
→ human selection
→ confirmed evidence link
→ human financial confirmation
→ immutable trader publication
```

Accepting a candidate must never automatically mark an attempt paid.

## 5.10 Paid amount invariant

```text
paid sum == requested amount → paid
paid sum < requested amount  → partially_paid
paid sum > requested amount  → reconciliation required
```

The agent must not implement a normal “confirm anyway” path for overpayment.

## 5.11 Publication

Trader-visible results are immutable publication snapshots.

A correction creates a new publication version and supersedes or revokes the old version according to policy.

The agent must not expose internal bank-result bundles, internal evidence records, or mutable financial state directly to the trader.

## 5.12 Financial deletion

The default correction model is:

```text
cancel
void
replace
supersede
revoke
archive
```

Generic hard delete and generic soft delete are not universal financial correction strategies.

---

# 6. Security and Authority Rules

## 6.1 Deny by default

Every protected action requires:

```text
authenticated session
+ active account
+ explicit permission
+ ownership/business scope
+ current state/version/hash
+ idempotency and concurrency checks
+ recent authentication or dual control where required
```

## 6.2 Separate security domains

Trader PWA and Admin Web are separate applications and security audiences.

A trader session must not be accepted as an admin session.

Admin functionality must not be bundled into Trader PWA and hidden only in the UI.

## 6.3 Technical admin

Technical administration does not imply financial authority.

A technical admin does not automatically receive permission to:

- approve a batch;
- confirm paid or failed;
- publish trader results;
- mark a bank export sent;
- confirm incoming settlement;
- dispatch gold;
- alter financial history.

## 6.4 Separation of duties

The agent must enforce the configured separation-of-duty rules.

The baseline rule is that the person who finalizes a batch version must not approve that same version.

## 6.5 Recent authentication

Sensitive actions may require recent authentication.

Reauthentication only establishes assurance. It does not itself execute the financial command.

## 6.6 Break-glass

There is no permanent universal super-admin financial role.

Break-glass access, if implemented, must be:

- disabled by default;
- time-limited;
- scope-limited;
- incident-bound;
- recently authenticated;
- alerted;
- fully audited;
- reviewed after use.

## 6.7 Trader isolation

A trader must never access another trader’s:

- profile data;
- beneficiaries;
- payment requests;
- revisions;
- attempts;
- publications;
- evidence;
- files;
- issue reports.

Object IDs, file IDs, signed URLs, and predictable paths do not grant access.

## 6.8 File security

- Files are private by default.
- Raw storage paths are never exposed.
- Every preview/download is authorized at access time.
- Pending or quarantined files are not usable as evidence.
- Signed URLs, if used, are short-lived and scope-limited.
- Trader-visible files must come through an approved publication path.

## 6.9 Browser storage

The agent must not persist the following in browser storage or service-worker cache:

- long-lived tokens;
- passwords;
- full financial API responses;
- IBANs and beneficiary snapshots;
- bank files;
- evidence files;
- financial command payloads;
- audit records;
- private signed URLs.

## 6.10 Audit

Sensitive business state, audit event, outbox event, and idempotency result must be committed atomically where required by the backend guide.

A log line is not a substitute for an audit event.

---

# 7. Architecture Rules for the Agent

## 7.1 Phase 1A architecture

Use a single-tenant modular monolith.

Do not add `organization_id` or `tenant_id` to every table for hypothetical future SaaS.

Multi-company/SaaS is Phase 4 and requires a complete tenancy architecture.

## 7.2 Two frontends

The repository must preserve independent applications:

```text
apps/trader-pwa
apps/admin-web
```

Shared packages may contain:

- generated API types;
- design tokens;
- low-level UI primitives;
- money display utilities;
- localization utilities;
- secure API-client primitives.

Shared packages must not merge admin and trader security boundaries.

## 7.3 Backend dependency direction

The required direction is:

```text
API adapters
→ application commands and queries
→ domain policies/entities
→ ports
← infrastructure adapters
```

Provider SDKs, file libraries, Celery, Redis, and storage drivers belong in infrastructure adapters.

## 7.4 No generic financial CRUD

The agent must implement explicit commands such as:

- create request draft;
- create request revision;
- submit request;
- return for correction;
- mark eligible for batching;
- preview batch;
- finalize batch version;
- create replacement version;
- approve exact version;
- reject exact version;
- generate preview export;
- generate final export;
- mark exact export sent;
- create manual crop;
- create candidate;
- confirm evidence;
- confirm paid or failed;
- create retry;
- publish result;
- supersede or revoke publication.

The agent must not replace these with a generic endpoint such as:

```http
PATCH /resource/{id} { "status": "paid" }
```

## 7.5 Unit of Work

A financial command should normally execute in one database transaction owned by the application Unit of Work.

Repositories must not independently commit.

Route handlers must not perform direct ORM writes.

## 7.6 PostgreSQL authority

PostgreSQL is authoritative for:

- financial state;
- job state that matters operationally;
- idempotency;
- audit;
- outbox;
- configuration versions;
- file metadata.

Redis is not an authoritative financial data store.

## 7.7 Background workers

Workers may:

- render previews and crops;
- generate approved artifacts;
- process files;
- send notifications;
- build reports;
- dispatch outbox events;
- perform optional AI jobs.

Workers may not:

- approve a batch;
- make a final payment decision;
- create active confirmed evidence without human command;
- publish a result as a human substitute;
- dispatch gold without the authorized command.

---

# 8. Idempotency, Concurrency, and Transaction Rules

## 8.1 Idempotency

Sensitive commands require an `Idempotency-Key` according to the API specification.

The implementation must distinguish:

- new key;
- replay with same canonical payload;
- reuse with a different payload;
- concurrent in-progress request;
- timeout after commit;
- abandoned or expired processing record.

The idempotency record must be durable. Redis-only idempotency is not sufficient.

## 8.2 Optimistic concurrency

Material changes require the expected record version or ETag.

Expected behavior:

```text
missing precondition → 428
stale precondition   → 412
```

The frontend must not automatically retry a stale financial command using a new version.

## 8.3 Critical locking

Use database constraints and targeted locking for critical races, including:

- request/attempt allocation to batch;
- batch finalization;
- manager approval;
- primary evidence uniqueness;
- paid confirmation;
- publication replacement;
- outbox claiming.

## 8.4 Transactional outbox

External side effects must not occur before the business transaction commits.

Required pattern:

```text
business state
+ audit
+ outbox
+ idempotency result
→ commit
→ asynchronous side effect
```

## 8.5 Timeout ambiguity

A timeout does not prove that a command failed.

The agent must design the client and API so a repeated request with the same idempotency key returns the original result when the first command committed.

---

# 9. Planning Before Coding

## 9.1 Definition of Ready

A task is ready only when the agent can identify:

- target phase;
- target milestone;
- authoritative documents and sections;
- affected bounded contexts;
- commands and queries;
- entities and immutable snapshots;
- status transitions and guards;
- permissions and ownership;
- idempotency requirement;
- concurrency strategy;
- audit events;
- outbox events;
- migration impact;
- frontend routes/components;
- background jobs;
- observability;
- test IDs and acceptance criteria;
- rollback or forward-fix strategy;
- blocking ADRs;
- out-of-scope work.

## 9.2 Required implementation plan

Before coding, produce this plan:

```text
Task ID:
Task name:
Phase:
Milestone:
Business outcome:
Authoritative documents and sections:
Supporting or historical documents consulted:
Blocking ADRs:
Affected bounded contexts:
Affected entities/aggregates:
Commands:
Queries/read models:
Status transitions and guards:
Permissions:
Ownership/scope checks:
Recent-auth/dual-control requirements:
Idempotency scope:
Concurrency and locking:
Audit events:
Outbox events:
Database migrations:
API changes:
Frontend changes:
Background jobs:
File/storage impact:
Observability:
Tests and test IDs:
Acceptance criteria:
Rollback/forward-fix:
Explicit out of scope:
Assumptions:
Conflicts found:
```

## 9.3 Agent must not code around an unresolved decision

When a decision is explicitly assigned to an ADR, the agent must not silently choose an option that becomes difficult to reverse.

Examples:

- selecting JWT versus server-side sessions;
- selecting production object storage;
- deciding recent-auth duration;
- deciding text-only payment confirmation policy;
- deciding IBAN masking policy;
- deciding production retention periods;
- deciding a real bank mapping or source account.

The agent may implement an interface or placeholder only when the placeholder is safe, reversible, and not misleadingly production-ready.

---

# 10. Conflict and Ambiguity Protocol

## 10.1 First determine whether a conflict is real

A difference is not always a conflict.

Examples:

- domain document defines meaning, while database document defines storage;
- workflow document defines legal transition, while UI document defines how it is displayed;
- security document adds a stricter guard without redefining the domain state.

## 10.2 Conflict resolution order

Use topic ownership, not a universal list.

General rules:

1. Security restrictions cannot be weakened by UI convenience.
2. Workflow transitions cannot be invented by frontend code.
3. Domain invariants cannot be changed by a repository or schema shortcut.
4. API naming cannot redefine domain meaning.
5. Future roadmap cannot silently expand Phase 1A.
6. A supporting, historical, original, or review-evidence document cannot override the authoritative topic owner.

## 10.3 Conflict record

When a material conflict exists, create:

```text
Conflict ID:
Documents and sections:
Observed contradiction:
Affected feature:
Financial/security/privacy impact:
Temporary safe behavior:
Decision owner:
Proposed resolution:
Documents requiring update:
Code/tests/migrations requiring update:
Implementation blocked: yes/no
```

## 10.4 Stop conditions

The agent must stop the affected implementation and request a decision when:

- the conflict changes money movement;
- the conflict changes manager authority;
- the conflict changes paid/failed semantics;
- the conflict changes trader visibility;
- the conflict changes retention or deletion;
- the conflict changes tenant or ownership boundaries;
- an ADR is required and no safe reversible default exists;
- a real bank file format is missing but production output is requested;
- a production secret or credential is required but unavailable.

The agent may continue unrelated work that is not affected by the blocked decision.

---

# 11. Database and Migration Rules

## 11.1 Schema follows domain

Do not design tables before identifying:

- the domain concept;
- immutability requirements;
- correction history;
- uniqueness and cardinality;
- state ownership;
- concurrency behavior;
- audit and retention impact.

## 11.2 Migration discipline

- One migration has one coherent purpose.
- Do not edit an applied shared migration.
- Test empty database to head.
- Test previous supported version to head.
- Use PostgreSQL for constraints, locks, and migration tests.
- Use expand/migrate/contract for risky changes.
- Backfills must be bounded, restartable, and idempotent.
- Destructive changes require a separate later release and explicit approval.

## 11.3 Runtime roles

Application runtime credentials must not be schema-owner credentials.

Migration, runtime, worker, backup, and read-only operations roles must remain separated according to the DevOps and security documents.

## 11.4 Database invariants

Prefer database constraints for critical invariants when feasible, including:

- active primary evidence uniqueness;
- immutable finalized-version item relationships;
- valid foreign-key ownership;
- nonnegative or positive integer amounts where appropriate;
- unique idempotency scope;
- append-only audit and approval behavior.

---

# 12. API Rules

## 12.1 Command-oriented API

Financial changes use explicit commands.

The agent must follow `/api/v1` and the API error contract.

## 12.2 Client-provided values are untrusted

Do not trust client-provided:

- status;
- role;
- total amount;
- row count;
- content hash;
- approval state;
- ownership;
- paid aggregate;
- export integrity result.

The server recalculates or verifies authoritative values.

## 12.3 Error behavior

Use stable error codes and correct status semantics, including:

```text
400 invalid command/request
401 unauthenticated
403 forbidden
404 not found or inaccessible
409 state/idempotency conflict
412 stale version
422 validation failure
428 missing precondition
429 rate limited
503 dependency unavailable
```

Do not catch all exceptions and return HTTP 200.

## 12.4 OpenAPI

OpenAPI is the source for generated frontend DTOs.

A contract change requires:

- API implementation update;
- OpenAPI update;
- generated client update;
- frontend adaptation;
- contract tests;
- documentation update where material.

---

# 13. Frontend Rules

## 13.1 Two applications

Maintain separate Trader and Admin applications.

## 13.2 Server authority

The frontend guides and previews. It does not decide financial truth.

Do not implement optimistic financial completion for:

- approval;
- paid confirmation;
- mark sent;
- publication;
- dispatch;
- correction.

Wait for the authoritative server response.

## 13.3 Money safety

Use string or BigInt-safe handling.

Display both entered unit/value and canonical IRR where required.

## 13.4 ETag and idempotency

The shared API client must manage:

- ETag extraction;
- `If-Match`;
- `Idempotency-Key`;
- timeout recovery with the same key;
- normalized errors;
- correlation/request IDs;
- CSRF and session transport according to ADR.

## 13.5 No scattered fetch

Financial components must not issue ungoverned direct `fetch` calls.

Use the shared API client and command hooks.

## 13.6 Offline boundary

The PWA may cache shell and non-sensitive static assets.

It must not queue financial commands or cache private files and financial responses.

## 13.7 Workflow-specific UI

Do not generate generic CRUD screens where the workflow requires:

- accountant queue;
- split preview;
- immutable version comparison;
- exact approval review;
- export integrity panel;
- side-by-side bank-result review;
- manual crop;
- evidence replacement;
- publication supersession;
- overpayment reconciliation.

---

# 14. File, Bank, Evidence, and Publication Rules

## 14.1 File lifecycle

Respect:

```text
pending
quarantined
available
processing_failed
archived
retention_pending
deleted
```

Do not treat storage write success alone as file availability.

## 14.2 Derivation graph

Original files must be preserved.

Derived artifacts must point to source artifacts and store their processing provenance.

## 14.3 Bank configuration

Bank profile, bank profile version, mapping version, template, source account, and splitting rules are distinct concepts.

Do not hard-code observed spreadsheet columns as global universal columns.

## 14.4 Import behavior

Statement or result import must preserve:

- original file;
- import run;
- raw row values;
- normalized row values;
- fingerprints;
- duplicate warnings;
- reprocessing history.

Reprocessing creates a new run. It does not silently overwrite the old run.

## 14.5 Evidence replacement

Evidence is replaced or revoked with history. It is not generically deleted.

## 14.6 Privacy review

Before publication, evidence must be reviewed so unrelated people, transactions, identifiers, or files are not exposed.

---

# 15. AI/OCR Rules

## 15.1 Phase 1A

AI/OCR must be disabled by default and must not be needed to complete any workflow.

## 15.2 Allowed AI effects in future phases

AI may:

- extract fields;
- propose segments;
- normalize text;
- generate matching candidates;
- flag anomalies;
- rank review work.

AI may not:

- approve a batch;
- mark paid or failed;
- create active confirmed evidence as final authority;
- publish to a trader;
- dispatch gold;
- mutate an approved batch version;
- authorize a final bank export;
- decide retention deletion.

## 15.3 Provider isolation

Provider SDKs stay in infrastructure adapters.

External provider transmission requires approved policy, data minimization, budget, retention, region, security, and legal review.

## 15.4 Human corrections

Human corrections may become evaluation data only under approved governance.

Do not implement automatic online learning from production corrections.

---

# 16. Testing Protocol

## 16.1 Test with the feature

Tests are part of the task, not a later cleanup milestone.

## 16.2 Required test categories

Depending on the task, include:

- domain unit tests;
- application-command tests;
- PostgreSQL repository and constraint tests;
- API contract tests;
- permission and ownership tests;
- idempotency tests;
- concurrency tests;
- ETag/precondition tests;
- audit/outbox atomicity tests;
- file-lifecycle tests;
- import/export golden tests;
- frontend component tests;
- end-to-end workflow tests;
- accessibility tests;
- backup/restore tests;
- migration upgrade tests.

## 16.3 Mandatory negative tests

For a sensitive feature, include at least the relevant negative cases:

- wrong role;
- wrong trader/ownership;
- stale version;
- missing precondition;
- duplicate idempotency key with different payload;
- concurrent conflicting command;
- invalid state transition;
- missing recent authentication;
- hash mismatch;
- quarantined file;
- duplicate primary evidence;
- overpayment;
- cross-trader file access.

## 16.4 No SQLite substitution

Do not use SQLite as proof that PostgreSQL constraints, locking, partial indexes, or migrations work.

## 16.5 Production smoke tests

Do not create real financial records, approvals, final exports, paid confirmations, or publications in production unless an approved production fixture procedure exists.

Full financial end-to-end testing belongs in staging/UAT.

---

# 17. Implementation Evidence and Handoff

## 17.1 Required change report

After implementation, provide:

```text
Task ID and milestone:
Business outcome delivered:
Documents and sections followed:
Files created:
Files modified:
Migrations added:
Commands/API endpoints added or changed:
Frontend routes/components added or changed:
Permissions and ownership checks:
Idempotency behavior:
Concurrency/locking behavior:
Audit events:
Outbox events:
Background jobs:
Feature flags:
Observability:
Tests added and results:
Manual verification steps:
Security/privacy impact:
Migration/rollback/forward-fix notes:
Assumptions:
Known limitations:
Future-phase items intentionally skipped:
Remaining blockers:
```

## 17.2 Evidence matrix

For sensitive tasks, attach or summarize evidence for:

| Control | Evidence |
|---|---|
| Authorized success | test/log/screenshot/reference |
| Permission denial | test result |
| Ownership denial | test result |
| Idempotent replay | test result |
| Different-payload key conflict | test result |
| Stale version | test result |
| Concurrent conflict | test result |
| Audit event | database/test assertion |
| Outbox event | database/test assertion |
| Transaction rollback | failure-injection result |
| Migration upgrade | test result |
| Manual verification | exact steps and outcome |

## 17.3 Claims must match evidence

The agent must not claim:

- “production ready” without production gates;
- “secure” without security tests and unresolved ADR disclosure;
- “idempotent” without replay and conflict tests;
- “concurrency safe” without concurrent test evidence;
- “backup complete” without restore evidence;
- “OpenAPI complete” when only a prose specification exists;
- “migration complete” when only a schema document exists.

## 17.4 Unfinished work

Use explicit labels:

```text
implemented
partially implemented
scaffold only
documentation only
blocked by ADR
blocked by missing fixture
not tested in production
future phase
```

---

# 18. Pull Request and Review Protocol

## 18.1 Pull request size

Keep changes small enough to review and test.

A task may span backend, frontend, migration, and tests when they form one coherent vertical slice.

Avoid unrelated refactoring inside a financial feature PR.

## 18.2 Required PR checklist

- [ ] Correct phase and milestone identified.
- [ ] Authoritative documents and sections listed.
- [ ] No unresolved material conflict hidden.
- [ ] No generic financial CRUD introduced.
- [ ] No float money introduced.
- [ ] No Phase 1A tenant fields introduced.
- [ ] Exact batch-version approval preserved.
- [ ] Idempotency implemented where required.
- [ ] ETag/version handling implemented where required.
- [ ] Permission and ownership enforced server-side.
- [ ] Audit and outbox behavior is transactional where required.
- [ ] Private files remain private.
- [ ] AI has no financial finality.
- [ ] Migration and forward-fix path reviewed.
- [ ] Tests include negative and concurrency cases.
- [ ] OpenAPI/generated client updated when applicable.
- [ ] Documentation updated for material change.
- [ ] No secret or real bank data committed.

## 18.3 Review authority

A coding agent may prepare code and evidence. It does not self-authorize:

- production deployment;
- real bank profile activation;
- retention deletion;
- break-glass use;
- manager approval policy;
- AI-provider production enablement;
- bank API payment submission;
- multi-tenant rollout.

---

# 19. Stop, Escalate, or Continue

## 19.1 Stop and escalate

Stop the affected work when:

- financial meaning is ambiguous;
- a security boundary is unclear;
- a real bank mapping is unavailable;
- a migration could destroy or reinterpret financial history;
- a production secret is missing;
- a required ADR is unresolved;
- a proposed shortcut weakens manager approval;
- trader privacy cannot be guaranteed;
- a timeout outcome cannot be reconciled;
- test data would expose real sensitive information.

## 19.2 Continue with safe independent work

The agent may continue:

- isolated unit tests;
- interface definitions;
- reversible adapters;
- non-sensitive UI shells;
- documentation;
- synthetic fixtures;
- unrelated modules;

provided the blocked decision is not silently embedded.

## 19.3 Never fabricate completion

When blocked, report the blocker and the exact decision or input required.

Do not generate fake credentials, fake approvals, fake bank mappings, or fake production evidence and present them as real.

---

# 20. Common Failure Patterns

## 20.1 Request-level manager approval

Incorrect:

```text
manager approves each payment request
```

Correct:

```text
accountant marks request eligible
manager approves exact immutable batch version
```

## 20.2 Mutable approved batch

Incorrect:

```text
edit approved rows and keep approval
```

Correct:

```text
create replacement version and obtain new approval
```

## 20.3 Download equals sent

Incorrect:

```text
file download automatically marks batch sent
```

Correct:

```text
separate exact mark-sent command after integrity validation
```

## 20.4 Candidate equals paid

Incorrect:

```text
accept match candidate → paid
```

Correct:

```text
candidate selection → evidence confirmation → separate paid command
```

## 20.5 Crop equals publication

Incorrect:

```text
create crop → trader sees it
```

Correct:

```text
crop → privacy review/evidence → financial result → publication
```

## 20.6 Technical admin equals financial superuser

Incorrect.

Technical access and financial authority are separate.

## 20.7 Generic soft delete everywhere

Incorrect.

Use domain-specific cancellation, replacement, supersession, revocation, archival, and governed retention.

## 20.8 Redis as truth

Incorrect.

Redis may support queues and caching, but durable financial and job truth remains in PostgreSQL.

## 20.9 AI inside synchronous critical path

Incorrect.

Manual completion must remain available.

## 20.10 Premature SaaS

Incorrect for Phase 1A.

Do not contaminate the schema and authorization model with partial tenancy.

---

# 21. Recommended Implementation Sequence

Use the milestones defined in file `15`.

```text
M0  Governance and contract baseline
M1  Repository and runtime foundation
M2  Persistence and integrity foundation
M3  Authentication, RBAC and ownership
M4  Bank configuration and file lifecycle
M5  Trader, beneficiary and request revisions
M6  Attempts, splitting and batch versions
M7  Manager approval and bank export
M8  Bank-result processing and manual crop
M9  Evidence, payment result and publication
M10 Gold sale and incoming settlement
M11 Queues, reports and maintenance
M12 Security, QA and operational hardening
M13 UAT, pilot and production release
```

The agent must not defer foundational integrity controls to M12.

Audit, outbox, idempotency, Unit of Work, concurrency, and file lifecycle start in the foundation milestones.

---

# 22. Example Task Mapping

## 22.1 Finalize a payment batch version

Read:

```text
02, 04, 05, 06, 08, 10, 12, 14, 15, 20
```

Implement:

- server-side selected-request validation;
- deterministic attempt splitting;
- ordered batch items;
- immutable finalization;
- row count and total;
- bank/mapping/source-account snapshot;
- canonical content hash;
- optimistic concurrency;
- idempotency;
- audit and outbox;
- replacement-version behavior;
- tests for concurrent finalization and stale input.

Do not implement:

- manager approval inside the same command;
- mutable finalized rows;
- client-authoritative totals.

## 22.2 Create a manual receipt crop

Read:

```text
03, 04, 05, 08, 10, 11, 12, 13, 14, 18, 20
```

Implement:

- source authorization;
- page/rotation/normalized rectangle validation;
- durable segment record;
- asynchronous render job;
- file derivation and checksum;
- retry/reconciliation;
- safe preview;
- audit;
- tests for invalid coordinates, inaccessible source, worker retry, and privacy boundary.

Do not implement:

- automatic paid confirmation;
- automatic publication;
- destructive replacement of the original file.

## 22.3 Correct a published paid result

Read:

```text
02, 05, 06, 08, 10, 11, 12, 14, 15, 20
```

Implement:

- sensitive correction command;
- reason and recent-auth requirements;
- configured second-person or manager control;
- replacement/revocation history;
- aggregate recalculation;
- publication N+1;
- supersession of publication N;
- trader notification through outbox;
- audit evidence;
- concurrency and idempotency tests.

Do not implement:

- in-place edit of the active publication;
- deletion of the old evidence or publication;
- silent trader-visible change.

---

# 23. Recommended Agent Start Prompt

```text
You are implementing the Gold Trade Settlement Platform.

Use only the authoritative v1.1 documentation files. Start by reading:
1. 16_Implementation_Documentation_Index.md
2. 15_Agent_Implementation_Plan.md
3. 20_Agent_Usage_Instructions.md
4. the topic-authority documents for the assigned task.

Before coding, produce the required task plan, identify blocking ADRs, and list any conflicts.

Implement only the assigned Phase 1A milestone unless a later phase is explicitly authorized.

Non-negotiable rules:
- integer IRR with original input unit retained;
- separate PaymentRequest, revision, PaymentAttempt, PaymentBatch, and PaymentBatchVersion;
- manager approval binds to the exact immutable batch version and hash;
- material changes require replacement version and reapproval;
- manual rectangular crop is required in Phase 1A;
- matching candidate, confirmed evidence, payment result, and trader publication are separate;
- financial commands require backend permissions, ownership, idempotency, concurrency, audit, and outbox controls as specified;
- no generic financial CRUD;
- no public file paths;
- no AI financial finality;
- no multi-tenancy in Phase 1A;
- no claims of completion without test and handoff evidence.

After coding, provide the complete change report and evidence matrix.
```

---

# 24. Final Agent Rules

The agent must always:

1. identify topic authority before coding;
2. implement Phase 1A as a complete manual core;
3. preserve human financial authority;
4. treat money as integer IRR;
5. preserve original entered value and unit;
6. preserve immutable revisions and snapshots;
7. bind manager approval to the exact batch version and hash;
8. invalidate approval after material replacement;
9. separate preview export, final export, download, and sent state;
10. preserve original bank and evidence files;
11. implement manual rectangular crop in Phase 1A;
12. separate candidates, confirmed evidence, results, and publications;
13. enforce paid-sum and overpayment rules;
14. use explicit financial commands, not generic status CRUD;
15. enforce RBAC and ownership on the backend;
16. keep trader and admin security domains separate;
17. keep technical administration separate from financial authority;
18. use recent authentication and separation of duties where required;
19. use durable idempotency for sensitive commands;
20. use optimistic concurrency and critical database constraints;
21. commit audit and outbox atomically with financial state where required;
22. keep Redis non-authoritative;
23. keep workers non-authoritative for final financial decisions;
24. keep files private and access-controlled;
25. prevent sensitive browser caching and offline command queues;
26. use PostgreSQL for integration and concurrency tests;
27. add tests with each feature;
28. include negative, replay, stale-version, and concurrent cases;
29. use safe migrations and forward-fix planning;
30. avoid committing secrets or real sensitive bank data;
31. stop when a material ADR or financial rule is unresolved;
32. document assumptions and limitations honestly;
33. provide implementation evidence before claiming completion;
34. keep future-phase automation isolated and disabled by default;
35. never allow AI to approve, confirm, publish, or dispatch;
36. never add partial multi-tenancy to Phase 1A;
37. never silently delete or overwrite financial history;
38. never expose full mixed bank result bundles to traders;
39. never treat UI hiding as security;
40. optimize for correctness, traceability, security, and operational usability.

---

# 25. Completion Standard

A task is complete only when:

- the required behavior is implemented;
- authoritative contracts are aligned;
- migrations are tested;
- permissions and ownership are tested;
- idempotency and concurrency are tested when applicable;
- audit and outbox behavior is verified;
- frontend handles server authority and errors correctly;
- file privacy is verified;
- documentation is updated for material changes;
- the handoff report and evidence matrix are complete;
- no unresolved blocker is hidden.

A visually working demo is not sufficient.

A successful Phase 1A implementation is a reliable financial operations platform that can run daily without AI, OCR, bank APIs, native applications, messaging-app approvals, or unsafe spreadsheet-style mutation.
