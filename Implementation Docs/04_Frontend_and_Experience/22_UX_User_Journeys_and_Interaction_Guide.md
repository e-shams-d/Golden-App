# Gold Trade Settlement Platform
# UX User Journeys and Interaction Guide

**Document ID:** `22_UX_User_Journeys_and_Interaction_Guide`  
**Version:** `1.1`  
**Supersedes:** `1.0`  
**Status:** `Authoritative UX Journey and Interaction Baseline`  
**Language:** English  
**Audience:** Product Owner, UX Designer, Frontend Developer, Backend Developer, QA Engineer, Security Reviewer, Operations Lead, Coding Agent  
**Primary Purpose:** Define user journeys, interaction contracts, decision points, failure recovery, role boundaries, and operational experience for Phase 1A and controlled later-phase assistance.

---

## 0. Document Control

### 0.1 Authority

This document is the primary authority for:

- user journeys;
- task sequencing from the user's point of view;
- interaction behavior;
- confirmation behavior;
- recovery from validation, workflow, concurrency, timeout, and processing failures;
- empty, waiting, blocked, and exceptional states;
- role-specific operational experience;
- trader-facing simplification;
- accountant and manager queue behavior;
- correction and dispute experience;
- Phase 1A manual-processing journeys;
- later AI-assisted UX boundaries.

This document does not override:

- product scope in documents `00` and `01`;
- domain invariants in document `02`;
- database representation in document `04`;
- API contracts in document `05`;
- state transitions in document `06`;
- bank-processing rules in document `08`;
- security, RBAC, audit, ownership, and separation-of-duty rules in document `12`;
- QA and release gates in document `14`;
- implementation order in document `15`;
- documentation-governance rules in document `16`;
- visual component and screen structure in document `21`.

Where a journey described here appears to conflict with a security, workflow, domain, or API rule, the higher-authority rule must be followed and this document must be corrected.

### 0.2 Change Summary from Version 1.0

Version 1.1:

- makes internal manual rectangular crop mandatory in Phase 1A;
- removes request-level manager approval language;
- introduces immutable `PaymentRequestRevision` journeys;
- introduces immutable `PaymentBatchVersion` journeys;
- binds manager approval to an exact version and content hash;
- separates preview export, final export, download, and mark-as-sent;
- separates `MatchingCandidate`, `ConfirmedEvidenceLink`, payment-result confirmation, and publication;
- introduces immutable `PaymentResultPublication` journeys;
- adds recent-authentication interaction;
- adds `Idempotency-Key`, ETag, and timeout-recovery UX;
- adds explicit stale-version and concurrent-update behavior;
- adds export-integrity and file-quarantine recovery;
- adds overpayment blocking and reconciliation journeys;
- adds retry-attempt journeys;
- adds sensitive correction and superseding-publication journeys;
- expands incoming-payment, gold-settlement, and dispatch-guard journeys;
- removes unsafe local persistence of financial drafts and commands;
- adds maintenance, session-expiry, worker-failure, and storage-failure recovery;
- aligns journeys to the two-application architecture.

### 0.3 Version Use Rule

When both files exist:

```text
22_UX_User_Journeys_and_Interaction_Guide.md
22_UX_User_Journeys_and_Interaction_Guide.md
```

use the `.md` file for implementation.

The original file is historical.

A `.diff` file is review evidence, not implementation authority.

---

## 1. Purpose

The platform replaces scattered messenger messages, uncontrolled spreadsheets, unclear bank-result images, repeated phone follow-up, and undocumented financial decisions with structured, auditable, permission-controlled journeys.

The UX must preserve the real business need while modernizing execution.

> Preserve business intent and operational controls, not the limitations of the current manual tools.

The platform is financially sensitive. A fast journey is not successful if it hides:

- the amount;
- the beneficiary;
- the exact bank row;
- the current version;
- the approval scope;
- the evidence source;
- the next responsible person;
- the effect of the action;
- the correction history.

The user should always understand:

```text
What is this item?
What is the current status?
Which exact version am I viewing?
Who owns the next action?
What can I safely do now?
What is blocked, and why?
What evidence supports the decision?
What happens after I confirm?
Can this action be audited later?
```

---

## 2. Fixed Phase 1A UX Baseline

Phase 1A is a complete manual operational core.

It must work without:

- OCR;
- external AI providers;
- automatic segmentation;
- automatic candidate generation;
- bank APIs;
- open banking;
- identity-validation APIs;
- native Android or Windows applications;
- internal chat;
- multi-company or SaaS features.

Phase 1A must include:

- Trader PWA, mobile-first;
- Admin Web App, desktop-first;
- explicit IRR/Toman entry;
- server-side draft and revision handling;
- accountant request review;
- eligibility for batching;
- deterministic server-side split preview;
- immutable batch versions;
- manager approval of the exact immutable version;
- preview and final exports;
- exact export mark-as-sent;
- secure bank-result bundle upload;
- secure PDF/image preview;
- internal manual rectangular crop;
- external manually prepared evidence fallback;
- manual matching and evidence confirmation;
- manual paid/failed confirmation;
- partial-payment and retry handling;
- immutable trader-facing publications;
- acknowledgement and dispute;
- governed correction;
- gold-sale, incoming-payment, settlement, and dispatch controls where included in the Phase 1A release;
- audit, idempotency, concurrency, file privacy, backup, and restore behavior.

### 2.1 Manual-first Does Not Mean Primitive

Manual-first means a human performs the decision.

It does not mean:

- copying a messenger conversation;
- editing approved rows in a spreadsheet;
- hiding who approved a payment;
- attaching a mixed screenshot directly to a trader;
- allowing generic status edits;
- using manual work as a reason to skip validation;
- postponing internal rectangular crop;
- silently overwriting confirmed data.

Correct modernization examples:

```text
Free-text payment message
→ structured request and immutable revision

Editable spreadsheet batch
→ immutable ordered batch version and content hash

Manager approval in chat
→ exact-version approval command with recent authentication

Mixed bank screenshot
→ private source file, controlled crop, evidence confirmation, safe publication

Manual correction in a message
→ governed correction with before/after comparison and audit
```

---

## 3. UX Principles

### 3.1 Structured Workflow, Not Chat

Use:

- forms;
- return reasons;
- correction requests;
- queue ownership;
- decision notes;
- issue reports;
- workflow timelines;
- task notifications.

Do not create a messenger clone in Phase 1A.

### 3.2 Human Financial Authority

No OCR model, AI provider, matching engine, client application, background worker, or scheduled job may:

- approve a batch;
- confirm an attempt paid;
- confirm an attempt failed;
- create an active authoritative evidence link;
- publish a result to a trader;
- dispatch gold;
- execute a retention deletion decision.

The UX must never imply otherwise.

### 3.3 Work Queue First

Accountants and managers should open a queue that answers:

- what needs attention;
- how old it is;
- why it needs attention;
- who currently owns it;
- what the next safe action is.

Raw tables are supporting views, not the primary operational journey.

### 3.4 Financial Safety Over Convenience

Sensitive actions require an explicit review step.

A confirmation must show the effect of the action, not only a generic question such as “Are you sure?”

### 3.5 Exact Version Awareness

Whenever a record is versioned, the user must know:

- the version number;
- whether it is current;
- whether it is immutable;
- whether an approval applies to it;
- whether a newer replacement exists.

### 3.6 Trader Simplicity

The trader sees business meaning, not internal processing complexity.

The trader does not need to see:

- internal batch versions;
- content hashes;
- mixed bank bundles;
- internal audit logs;
- worker jobs;
- internal matching scores;
- account-level source-bank details;
- internal manager notes.

The trader must still see enough information to understand:

- what was requested;
- what was paid;
- whether payment is partial;
- what publication version is current;
- whether action is required;
- how to dispute the result.

### 3.7 Privacy Before Convenience

A fast share button is not acceptable if it can disclose another trader or beneficiary.

Trader-visible information must come from a reviewed publication, not from unrestricted access to the bank-result source.

### 3.8 No Unsafe Optimistic Finality

The UI must not display a financial action as complete before the server confirms it.

This applies to:

- approval;
- rejection;
- final export generation;
- mark-as-sent;
- evidence confirmation;
- paid/failed confirmation;
- publication;
- dispatch;
- sensitive correction.

### 3.9 Recovery Must Be Designed

Every critical journey must define what happens when:

- the network fails;
- the request times out;
- the session expires;
- another user changes the record;
- the worker fails;
- the file is quarantined;
- the current version changes;
- a command may have committed but the response was lost.

### 3.10 No Sensitive Offline Queue

The applications may cache a non-sensitive shell.

They must not queue offline:

- payment submissions;
- batch finalization;
- approval;
- export generation;
- mark-as-sent;
- evidence confirmation;
- paid/failed confirmation;
- publication;
- dispatch.

---

## 4. Applications and Personas

## 4.1 Trader PWA

Primary characteristics:

- mobile-first;
- Persian-first;
- RTL-first;
- card-based;
- low cognitive load;
- minimal internal terminology;
- no mixed-bank exposure;
- no administrative controls.

## 4.2 Admin Web App

Primary characteristics:

- desktop-first;
- queue-first;
- dense but controlled;
- side-by-side review;
- explicit version context;
- role-specific actions;
- strong warning and conflict states;
- no dangerous bulk financial actions.

## 4.3 Persona: Trader

Goals:

- submit accurate requests quickly;
- know the current status;
- understand correction requests;
- receive a safe payment result;
- share a result with the retail seller;
- report a problem;
- track gold purchase or settlement.

Main risks:

- wrong amount unit;
- wrong IBAN;
- duplicate request;
- misunderstanding internal statuses;
- sharing outdated or superseded publication;
- assuming a partial payment is complete.

## 4.4 Persona: Accountant

Goals:

- process work from queues;
- review exact request revisions;
- prepare deterministic bank batches;
- process mixed bank-result files safely;
- create controlled crops;
- confirm evidence and results separately;
- identify unresolved or exceptional cases;
- preserve an audit trail.

Main risks:

- duplicate batching;
- using a stale revision;
- selecting the wrong attempt;
- confirming a candidate as paid without evidence review;
- exposing unrelated bank data;
- creating overpayment;
- retrying a command that already committed;
- silently correcting a published result.

## 4.5 Persona: Manager

Goals:

- approve outgoing money with complete context;
- review one exact immutable version;
- see total exposure and warnings;
- avoid approving unrelated routine records;
- review exceptional corrections when policy requires it.

Main risks:

- approving a stale version;
- approving a different hash than reviewed;
- self-approving a version they finalized;
- assuming preview export is final;
- approving without recent authentication.

## 4.6 Persona: Warehouse or Dispatch User

Goals:

- see orders cleared for dispatch;
- register physical dispatch or receipt;
- avoid unnecessary financial detail;
- know why dispatch is blocked.

Main risks:

- dispatch before verified settlement;
- overriding a financial block;
- confusing physical and offset settlement;
- editing financial records.

## 4.7 Persona: Business Admin

Goals:

- manage users and business configuration;
- approve controlled configuration changes where authorized;
- monitor operational policy.

Business Admin is not automatically allowed to perform every financial command.

## 4.8 Persona: Technical Admin

Goals:

- maintain platform health;
- manage technical settings;
- investigate operational failures;
- manage infrastructure access.

Technical Admin must not gain implicit authority to:

- approve batches;
- confirm paid results;
- publish trader results;
- dispatch gold;
- modify confirmed financial history.

## 4.9 Persona: Auditor or Read-only Reviewer

Goals:

- inspect authorized records;
- review history and audit events;
- export approved reports where permitted.

This role must not see unrestricted sensitive file content merely because it can read audit metadata.

---

## 5. Standard Journey Anatomy

Every implemented journey should define:

1. Trigger;
2. Entry conditions;
3. Actor and permission;
4. Current record/version;
5. User-visible context;
6. Primary steps;
7. Server-side command;
8. Idempotency behavior;
9. Concurrency behavior;
10. Confirmation behavior;
11. Success state;
12. Recoverable errors;
13. Blocking errors;
14. Audit and notification result;
15. Exit state and next owner.

### 5.1 Standard Sensitive Command Pattern

```text
Open current record
→ verify version and permission
→ review exact effect
→ enter reason when required
→ satisfy recent authentication when required
→ submit one logical command with stable idempotency key
→ wait for authoritative result
→ reconcile unknown outcome before retrying
→ show committed state and audit reference
```

### 5.2 Confirmation Levels

| Level | Example | Required UX |
|---|---|---|
| Informational | Retry file preview | Plain action with status feedback |
| Reversible operational | Assign task | Confirmation only when impact is non-obvious |
| Sensitive business | Return request for correction | Summary and required reason |
| Financial | Confirm paid, mark exact export sent | Exact amount, target, effect, idempotency, server result |
| High-risk financial | Approve batch version | Exact version/hash, recent auth, separation-of-duty check |
| Sensitive correction | Supersede published result | Before/after comparison, reason, policy review, notification |

### 5.3 Disabled vs Hidden Actions

Hide an action when the user has no business reason to know it exists.

Show it disabled with an explanation when:

- the user has general responsibility for the workflow;
- the current state blocks the action;
- a prerequisite is missing;
- another version is current;
- recent authentication is required.

Do not reveal protected data in the explanation.

---

## 6. Global Interaction Contracts

## 6.1 Version and ETag Contract

A mutable resource returned by the server includes a version or ETag.

A command that requires current state sends `If-Match`.

The UX must handle:

```text
Missing precondition → 428 PRECONDITION_REQUIRED
Stale precondition   → 412 VERSION_CONFLICT
```

The client must not silently fetch the new version and replay a financial command.

The user must review the new state first.

## 6.2 Idempotency Contract

A logical sensitive action receives one stable idempotency key.

The key remains the same across:

- safe network retry;
- timeout recovery;
- page-level retry after unknown outcome.

A new key must not be generated until the system has established that the previous logical command did not commit or the user intentionally starts a new action.

### 6.2.1 Same Key, Same Payload

The server returns the original result.

The UX should state that the existing action was recovered, not performed twice.

### 6.2.2 Same Key, Different Payload

The server returns an idempotency conflict.

The UX must:

- block automatic retry;
- preserve the conflict reference;
- tell the user that the previous request must be reconciled;
- avoid exposing raw keys.

## 6.3 Timeout with Unknown Outcome

When a critical request times out:

1. do not assume failure;
2. do not show success;
3. keep the logical idempotency key;
4. query command or resource status where supported;
5. retry only with the same key and same payload;
6. show the committed result if recovered;
7. create a support/reconciliation path if the outcome remains unknown.

Suggested message:

```text
The system did not receive a final response.
Do not repeat this action as a new request.
We are checking whether it was already recorded.
```

## 6.4 Session Expiry

If the session expires before submission:

- preserve only non-sensitive in-memory form state where safe;
- request login;
- re-read the current record after login;
- revalidate permissions and version;
- require the user to review before submitting.

If the session expires after submission but before response:

- treat the outcome as unknown;
- reconcile using the original idempotency key after reauthentication;
- never submit a new logical command automatically.

## 6.5 Recent Authentication

Recent authentication may be required for:

- manager approval;
- sensitive published-result correction;
- break-glass access;
- other policy-defined commands.

Recent authentication:

- is tied to the current session;
- expires;
- does not itself perform the financial command;
- must not hide a version change that occurred during reauthentication.

After recent authentication, the client must re-check the current version/hash before enabling final confirmation.

## 6.6 Permission Change During a Journey

If the user's role or permission changes while a screen is open:

- the server remains authoritative;
- the command is rejected safely;
- the UI refreshes capability state;
- no partial financial change is shown.

## 6.7 Maintenance Mode

Maintenance states may include:

- normal;
- read-only;
- financial writes blocked;
- full maintenance.

The UX must explain:

- which actions remain available;
- whether existing records can be viewed;
- whether uploads are paused;
- whether a submitted action is still being reconciled.

## 6.8 File Processing State

File-related UX must distinguish:

```text
pending
quarantined
available
processing_failed
archived
retention_pending
deleted_by_policy
```

A file that is not `available` cannot be used as active evidence or published to a trader.

---

## 7. Journey 1 — Trader Registration and Approval

### Trigger

A trader wants operational access.

### Entry Conditions

- Trader PWA is available.
- Registration is enabled.
- The user is not already authenticated as an active trader.

### Steps

1. Trader enters the required identity and contact information.
2. Client normalizes Persian, Arabic, and Latin digits where applicable.
3. Server creates a trader account in a pending state.
4. Trader sees a calm pending-approval screen.
5. Authorized internal user opens the trader-approval queue.
6. Reviewer checks required business information.
7. Reviewer approves, rejects, or requests a governed correction according to policy.
8. Trader receives an in-app status update.
9. Active operational access begins only after approval.

### UX Rules

- Pending traders cannot open operational deep links.
- Suspension preserves history.
- Rejection does not expose internal notes automatically.
- Approval is a business command with audit, not a generic user-table edit.
- Technical Admin does not gain trader-approval authority by default.

### Recovery

| Situation | Behavior |
|---|---|
| Duplicate mobile/contact | Guide to login or controlled account-recovery flow |
| Registration request timeout | Reconcile account existence before allowing another registration |
| Pending trader deep link | Redirect to pending state without leaking the target record |
| Suspended trader session | Revoke operational access and display restricted status |

---

## 8. Journey 2 — Trader Creates an Outgoing Payment Request

### Trigger

The trader needs the center to pay a beneficiary.

### Entry Conditions

- Trader is active.
- Trader owns the request context.
- Financial writes are allowed.

### Steps

1. Trader opens `Create Payment Request`.
2. Trader selects an existing beneficiary or creates a new beneficiary record.
3. Beneficiary record stores identity and bank details, not the requested amount.
4. Trader enters amount value.
5. Trader explicitly selects `Toman` or `Rial`.
6. UI shows the canonical IRR equivalent and a second-unit helper.
7. Trader enters description and allowed attachments.
8. Trader saves a server-side draft or submits.
9. Submission confirmation shows beneficiary, IBAN, entered value/unit, and canonical IRR.
10. Server creates the request and immutable current revision.
11. Trader sees `submitted_to_center`.

### Money UX Rules

- No unit inference from magnitude.
- No unlabeled input.
- No floating-point canonical arithmetic.
- Large values receive an informational warning, not an arbitrary block unless policy requires it.
- The confirmation shows both the entered unit and canonical IRR.

### Draft Rules

- Server-side drafts are preferred.
- Sensitive drafts must not be stored persistently in browser storage.
- An unsent form may remain in memory during the current page session.
- Offline submission is not allowed.

### Duplicate Warning

Potential duplicates may be shown using:

- same trader;
- same beneficiary;
- same amount;
- close submission time.

A warning does not automatically block a legitimate repeated request.

### Recovery

| Situation | Behavior |
|---|---|
| Invalid IBAN structure | Field-level error before submit |
| Network failure before command | Keep in-memory form and allow retry |
| Timeout after submit | Reconcile using same idempotency key |
| Trader opens old submitted form | Show read-only revision and current state |
| Another tab changes draft | Show version conflict and require review |

---

## 9. Journey 3 — Trader Corrects and Resubmits a Request

### Trigger

The accountant returns the request for correction.

### Steps

1. Trader sees `needs_trader_correction` and the structured correction reason.
2. Trader opens the current revision.
3. Editable fields are clearly distinguished from immutable history.
4. Trader changes allowed fields.
5. UI shows a before/after summary.
6. Trader confirms the corrected amount, unit, beneficiary, and IBAN.
7. Server creates a new immutable `PaymentRequestRevision`.
8. Previous revision remains visible in history.
9. Request returns to the accountant queue.

### Rules

- The previous revision is never overwritten.
- Existing bank attempts remain linked to the historical revision they used.
- A correction that affects an already finalized batch does not mutate that version.
- The trader cannot correct a record already sent to bank through the ordinary correction flow.

### Recovery

A stale correction form must not overwrite a newer revision.

The user must compare the latest version and re-enter changes if necessary.

---

## 10. Journey 4 — Accountant Reviews Submitted Requests

### Trigger

New or corrected requests enter the accountant queue.

### Queue Groups

- new submissions;
- corrected resubmissions;
- possible duplicates;
- requests missing required business information;
- requests blocked by configuration;
- requests ready to become eligible for batching.

### Steps

1. Accountant opens a queue item.
2. UI shows the current request revision prominently.
3. Historical revisions remain available but visually secondary.
4. Accountant checks beneficiary, IBAN, amount, entered unit, and attachments.
5. Accountant returns the request for correction or marks it `eligible_for_batching`.
6. The server records the command, audit event, and outbox event atomically.

### Critical Rule

The accountant does not “approve” an individual request on behalf of the manager.

The accountant marks the current revision eligible for batching.

The manager approves an exact batch version later.

### Bulk Action Rules

Bulk actions may be used only where:

- the action is safe;
- each item is independently validated;
- the result is clearly previewed;
- no financial status is silently changed.

There is no bulk manager approval through a generic checkbox list.

### Recovery

| Situation | Behavior |
|---|---|
| Trader submits newer revision while review is open | Block stale action and show newer revision |
| Request already batched | Remove from eligible selection and explain |
| Required bank configuration missing | Keep request eligible only when policy permits; block batch finalization later |
| Duplicate warning | Allow documented continuation or return for clarification |

---

## 11. Journey 5 — Accountant Builds and Finalizes a Batch Version

### Trigger

Eligible request revisions are ready for a bank submission grouping.

### Steps

1. Accountant opens eligible revisions.
2. Accountant selects the bank profile version.
3. Accountant selects the source bank account.
4. Accountant selects or confirms the export mapping version.
5. Accountant selects eligible request revisions.
6. Client requests a server-side deterministic split preview.
7. Server returns proposed payment attempts and ordered rows.
8. UI shows:
   - original request revision;
   - beneficiary snapshot;
   - original amount;
   - generated attempt rows;
   - row count;
   - total IRR;
   - warnings;
   - source account;
   - bank and mapping versions.
9. Accountant resolves blocking validation errors.
10. Accountant creates a draft `PaymentBatchVersion`.
11. Accountant reviews the exact ordered rows.
12. Accountant finalizes the version.
13. Server makes the version immutable and returns a content hash.
14. Version enters `ready_for_approval`.

### UX Rules

- Splitting is calculated by the server.
- The UI never becomes the business source of truth for totals.
- The version number and hash are visible after finalization.
- Finalized rows cannot be edited.
- Material changes require a replacement version.
- Requests cannot be selected twice for active bank processing.
- Preview export may be available, but must be visibly non-sendable.

### Example Split Display

The UX may show a configured split example, but must not hard-code a universal threshold.

```text
Original request: 450,000,000 Toman
Canonical amount: 4,500,000,000 IRR
Configured split preview:
- Attempt 1: 2,000,000,000 IRR
- Attempt 2: 2,000,000,000 IRR
- Attempt 3:   500,000,000 IRR
```

### Recovery

| Situation | Behavior |
|---|---|
| A selected revision is no longer eligible | Remove it and require preview regeneration |
| Bank rule changes during draft | Draft shows stale configuration and requires regeneration |
| Two accountants select same request | Server prevents double allocation; second user refreshes |
| Finalize times out | Reconcile version status using same idempotency key |
| Finalized version needs a row change | Create replacement version; do not edit |

---

## 12. Journey 6 — Manager Approves an Exact Batch Version

### Trigger

An immutable batch version is ready for approval.

### Entry Conditions

- User has approval permission.
- User is not prohibited by separation-of-duty policy.
- Version is current and ready for approval.
- Recent authentication is valid or can be completed.

### Manager Review Screen

The manager must see:

- batch identifier;
- exact version number;
- current/superseded indicator;
- content hash;
- total IRR and optional Toman equivalent;
- row count;
- request count;
- trader count;
- beneficiary count;
- bank profile version;
- mapping version;
- source account;
- ordered rows or a complete reviewable representation;
- warnings;
- finalizer identity;
- separation-of-duty status.

### Steps

1. Manager opens the exact version from the approval queue.
2. Client verifies that the viewed version is still current.
3. Manager reviews totals, rows, configuration, and warnings.
4. Manager chooses approve or reject.
5. Reject requires a reason.
6. Approval requires recent authentication when policy requires it.
7. After reauthentication, client re-checks version and hash.
8. Manager confirms the exact version/hash.
9. Server records an append-only approval decision.
10. Approved version becomes eligible for final export.

### Stale Approval Behavior

If a replacement version exists:

- approval controls are disabled;
- a stale-version banner is shown;
- the user is linked to the current version;
- the prior review is not transferred to the new version;
- recent authentication may need to be repeated according to policy.

### Recovery

| Situation | Behavior |
|---|---|
| Manager is also finalizer and policy prohibits it | Block with separation-of-duty explanation |
| Recent auth expires | Reauthenticate, then re-read version/hash |
| Concurrent manager decision | Show committed decision; do not create a second conflicting decision |
| Hash mismatch | Block and create a security/operational event |
| Timeout after approval | Reconcile using same idempotency key |

---

## 13. Journey 7 — Preview Export, Final Export, Download, and Mark Sent

### 13.1 Preview Export

Preview export may be generated before approval for validation.

It must show a persistent warning:

```text
PREVIEW — NOT APPROVED FOR BANK SUBMISSION
```

Preview export:

- is not the final export;
- cannot be marked sent;
- must not look identical to the final sendable artifact without a clear watermark or equivalent distinction.

### 13.2 Final Export Generation

Steps:

1. Accountant opens the approved exact batch version.
2. Accountant requests final export generation.
3. Server validates:
   - exact approved version;
   - approval hash;
   - content hash;
   - row count;
   - total;
   - mapping version;
   - source account.
4. Export job runs.
5. UI shows processing state.
6. On success, export checksum and integrity state are displayed.
7. On mismatch, export is quarantined.

### 13.3 Download

Download is allowed only for an available, integrity-valid final export and an authorized user.

The UI must state:

> Downloading the file does not mean it has been sent to the bank.

### 13.4 Mark Exact Export Sent

Steps:

1. Accountant opens the exact final export.
2. UI shows filename, checksum, version, total, row count, source account, and generation time.
3. Accountant enters or confirms sent time and channel.
4. User confirms that this exact file was submitted.
5. Server revalidates integrity.
6. Server atomically updates export, batch, attempts, requests, audit, outbox, and idempotency state.

### Recovery

| Situation | Behavior |
|---|---|
| Export checksum mismatch | Quarantine; no “download anyway” |
| Export generation worker fails | Show retry without creating a new financial version |
| Download succeeds but user did not send | Leave unsent |
| Mark-sent times out | Reconcile same logical command |
| Wrong file was sent externally | Open incident/reconciliation journey; do not silently relabel another export |

---

## 14. Journey 8 — Bank Result Bundle Upload

### Trigger

The bank provides result images, screenshots, PDFs, scans, spreadsheets, or a mixed set.

### Steps

1. Accountant opens bundle upload.
2. Selects bank profile where known.
3. Optionally links known batches or exports.
4. Uploads one or more files.
5. Adds received time and note where needed.
6. Files enter private pending state.
7. System validates size, signature, type, and security status.
8. Available files are added to the bundle.
9. Bundle enters manual-processing queue.

### Rules

- A bundle may contain multiple traders.
- A bundle may relate to multiple batches or none known initially.
- Upload does not confirm payment.
- Bundle status is separate from attempt status.
- Source files remain private.
- The trader never sees the mixed bundle.

### File State UX

| State | UX |
|---|---|
| pending | Show validation/scan in progress |
| quarantined | Block preview and use; show safe operational message |
| available | Allow authorized preview and processing |
| processing_failed | Allow controlled retry or alternate evidence |
| archived | Read-only access where permitted |

### Recovery

- Partial multi-file upload should show per-file results.
- Retrying a failed upload must not duplicate already accepted files.
- A file stored without finalized metadata must enter reconciliation, not active processing.

---

## 15. Journey 9 — Internal Manual Rectangular Crop

### Trigger

The accountant identifies a transaction inside a source image or PDF page and needs a privacy-safe segment.

### Phase

Required in Phase 1A.

### Steps

1. Accountant opens a bank-result bundle.
2. Selects an available source file.
3. For PDF, selects the source page.
4. Uses zoom, pan, and rotation.
5. Draws a rectangular selection.
6. May adjust numeric normalized coordinates for accessibility or precision.
7. UI previews the selected crop.
8. Accountant performs a privacy check:
   - no unrelated transaction is visible;
   - no unrelated name or IBAN is visible;
   - correct page and transaction are selected;
   - content is readable.
9. Accountant requests crop creation.
10. Server records source file, page, source dimensions, rotation, normalized decimal coordinates, renderer version, and parameters.
11. Background worker creates a derived file.
12. UI shows processing state.
13. On success, the segment becomes available for later evidence review.

### Critical Separation

```text
Create crop
≠ accept match
≠ confirm evidence
≠ confirm payment
≠ publish result
```

### External Evidence Fallback

If internal rendering fails or the source format is unsupported:

- authorized user may upload an externally prepared evidence fragment;
- the external file is recorded as a distinct source type;
- privacy review remains required;
- original source relationship is retained where known;
- this fallback does not bypass evidence or result confirmation.

### Recovery

| Situation | Behavior |
|---|---|
| Renderer fails | Retry job or use controlled external fallback |
| Coordinates invalid | Reject before processing |
| Source file quarantined | Block crop creation |
| Crop reveals unrelated data | Reject and create a new crop |
| User leaves while processing | Job continues; queue shows status later |
| Duplicate crop | Warn using checksum/context; do not auto-confirm |

---

## 16. Journey 10 — Matching Candidate Review

### Trigger

The accountant needs to associate a receipt segment, result row, or manually structured result with a payment attempt.

In Phase 1A, candidates may be created manually or deterministically without AI.

### Steps

1. Accountant selects a segment or result row.
2. Searches attempts by trader, amount, IBAN, beneficiary, batch, and date.
3. System presents possible targets with explainable context.
4. Accountant compares the source and attempt details side by side.
5. Accountant may select a candidate for the next confirmation step.
6. Selection is recorded as a candidate decision, not as payment confirmation.

### Candidate UX Rules

- Show exact amount and unit.
- Show IBAN in LTR with appropriate masking based on permission.
- Show beneficiary snapshot and request revision.
- Show attempt amount and aggregate request effect.
- Show duplicate or conflict warnings.
- Do not label a score as “probability paid.”
- Do not change financial state.

### AI-assisted Later Phase

AI may propose candidates later.

Labels must communicate suggestion:

- Suggested match;
- Needs human review;
- Ambiguous;
- Possible duplicate;
- Low-confidence extraction.

Never use:

- Verified by AI;
- Automatically approved;
- Guaranteed match.

---

## 17. Journey 11 — Confirmed Evidence Link

### Trigger

The accountant has reviewed a source and an exact payment attempt and wants to establish authoritative evidence.

### Steps

1. Accountant opens the selected source/segment and target attempt.
2. UI shows side-by-side comparison.
3. Accountant chooses evidence type:
   - primary;
   - supplementary.
4. UI warns if the attempt already has active primary evidence.
5. Accountant enters a reason or note where required.
6. Accountant confirms the exact source and target.
7. Server creates an immutable link/history event.
8. Replacement of an active primary link supersedes or revokes the old link according to policy; it does not delete it.

### Rules

- Candidate acceptance alone is not enough.
- Evidence link creation does not automatically mark paid.
- Active primary-evidence uniqueness is enforced by the database.
- A source already used as active primary evidence elsewhere is blocked or escalated.
- Supplementary evidence is clearly distinguished.

### Recovery

Concurrent attempts to create two active primary links must result in one committed link and one clear conflict state.

---

## 18. Journey 12 — Confirm Attempt Paid or Failed

### Trigger

Authoritative evidence or an allowed controlled exception is ready for financial result confirmation.

### Paid Confirmation Steps

1. Accountant opens the exact attempt.
2. UI displays:
   - attempt amount;
   - request amount;
   - current confirmed paid sum;
   - resulting paid sum;
   - remaining amount;
   - resulting request status;
   - active evidence;
   - request revision;
   - prior attempts.
3. System checks evidence policy.
4. Accountant confirms paid with an explicit command.
5. Server validates exact amount and aggregate effect.
6. Server records result, request aggregate status, audit, outbox, and idempotency atomically.

### Failed Confirmation Steps

1. Accountant opens the attempt.
2. Selects failure reason.
3. Reviews evidence or bank-result context.
4. Confirms failed.
5. System determines whether retry is required.
6. Request aggregate status updates according to all attempts.

### Aggregate Rules

```text
paid sum == requested amount → paid
paid sum < requested amount  → partially_paid or unresolved
paid sum > requested amount  → blocked; reconciliation required
```

### Overpayment UX

When confirmation would exceed the request amount:

- block confirmation;
- show excess amount;
- show contributing attempts;
- create or link a reconciliation task;
- do not offer “confirm anyway” in the ordinary flow.

### Text-only Exception

Text-only paid confirmation is not the default.

If policy enables it:

- show an exception warning;
- require reason;
- show the policy basis;
- apply any required elevated permission or review;
- audit the exception distinctly.

### Recovery

| Situation | Behavior |
|---|---|
| Another user confirmed the attempt | Show committed result and stop |
| Evidence replaced during confirmation | Block stale command and reload |
| Timeout after confirm | Reconcile with same idempotency key |
| Aggregate changed due to concurrent attempt | Show version conflict and updated totals |

---

## 19. Journey 13 — Partial Payment and Retry

### Trigger

A request is not fully paid because one or more attempts failed or only part of the amount was confirmed.

### Steps

1. Accountant opens the request aggregate.
2. UI shows:
   - requested amount;
   - paid sum;
   - failed sum;
   - unresolved sum;
   - remaining amount;
   - all attempt histories.
3. Accountant selects `Create Retry` where allowed.
4. UI shows the exact current request revision and previous attempt snapshot.
5. Any beneficiary, IBAN, or amount correction is performed through a governed request revision before retry.
6. Server creates a new attempt for the remaining valid amount.
7. The new attempt enters a later draft batch version.
8. The new batch version requires manager approval.

### Rules

- A retry never reuses the old failed attempt as a mutable bank row.
- A new bank action requires a new attempt.
- A retry does not inherit old manager approval.
- The UI must not allow changing beneficiary or IBAN inside a small retry modal.

---

## 20. Journey 14 — Create and Publish Trader Result

### Trigger

One or more attempt results are confirmed and safe trader-facing information is ready.

### Publication Preview

The publisher sees:

- publication version;
- request summary;
- attempt summaries;
- paid/partial status;
- safe beneficiary details;
- masked bank information;
- selected evidence or generated safe card;
- privacy review state;
- prior publication history.

### Steps

1. Authorized user opens publication preview.
2. System builds an immutable snapshot from confirmed records.
3. User checks privacy and accuracy.
4. User confirms publication.
5. Server creates `PaymentResultPublication`.
6. Publication becomes trader-visible.
7. Trader receives an in-app update.

### Rules

- Trader visibility is based on the publication, not raw evidence tables.
- Publication is immutable.
- Internal notes are excluded.
- Mixed source bundles are excluded.
- Share/download uses a publication artifact, not a private source URL.

### Recovery

Publication timeout follows idempotency recovery.

A publication created successfully but not acknowledged by the client is recovered and shown as committed.

---

## 21. Journey 15 — Trader Views, Shares, Acknowledges, or Disputes

### Steps

1. Trader opens Results.
2. Trader sees the current publication version.
3. Superseded versions are hidden from the default view but may be represented in history where appropriate.
4. Trader reviews:
   - request amount;
   - paid amount;
   - partial/complete state;
   - beneficiary;
   - safe tracking/bank information;
   - approved evidence or result card.
5. Trader may download or share the approved artifact.
6. Trader may acknowledge the result.
7. Trader may dispute the exact publication version.

### Share Rules

- Share artifact contains no private storage URL.
- Share artifact does not expose unrelated bank information.
- Current/superseded state is handled so an outdated artifact is not presented as the active system record.
- The platform cannot revoke a file already shared externally; correction UX must acknowledge this limitation.

### Dispute Rules

A dispute:

- references the exact publication version;
- does not automatically reverse financial state;
- creates a structured task;
- remains visible to the trader;
- is resolved through a governed review and correction path.

### Suggested Dispute Reasons

- beneficiary reports no receipt;
- wrong amount;
- wrong beneficiary;
- evidence unclear;
- duplicate-payment concern;
- outdated/superseded result;
- other.

---

## 22. Journey 16 — Correct Confirmed Evidence or Published Result

### Trigger

A material error is discovered after evidence confirmation, payment confirmation, or trader publication.

### Classification

The system should distinguish:

- non-material metadata clarification;
- evidence replacement without financial change;
- payment-result correction;
- published-result correction;
- correction affecting approved outgoing money history.

### Sensitive Correction Steps

1. Authorized user opens the current record and correction action.
2. UI shows current state and historical state.
3. User selects correction type.
4. User enters a required reason.
5. UI displays before/after effect on:
   - evidence;
   - attempt result;
   - request aggregate;
   - publication;
   - trader visibility.
6. Policy determines whether second-person or manager approval is required.
7. Server records correction history and recalculates aggregates.
8. If trader-facing data changes, server creates publication N+1.
9. Previous publication becomes superseded or revoked according to policy.
10. Trader is notified that a newer result exists.

### Rules

- No silent edit of confirmed or published records.
- Old evidence and publications are preserved.
- The UI must warn that the trader may already have downloaded or shared the old version.
- Technical Admin cannot perform the correction merely because they administer the system.
- A financial correction does not rewrite the original approved batch version.

### Emergency Revocation

If publication contains a privacy or serious integrity issue:

- revoke trader access to the active publication where policy allows;
- preserve the record internally;
- create an incident;
- create a corrected replacement publication;
- notify affected users through the approved channel.

---

## 23. Journey 17 — Trader Issue Review and Resolution

### Steps

1. Accountant opens the issue queue.
2. Issue displays the exact publication, request, and attempt context.
3. Accountant classifies:
   - informational;
   - evidence issue;
   - bank follow-up;
   - financial correction;
   - suspected duplicate;
   - privacy issue.
4. Accountant records investigation notes.
5. If no financial change is needed, issue is resolved with a trader-visible summary.
6. If correction is needed, the governed correction journey begins.
7. Issue closure is audited.

### Rules

- Internal investigation notes are not automatically trader-visible.
- Closing an issue does not silently alter financial state.
- A trader-visible response is structured and separate from internal notes.

---

## 24. Journey 18 — Gold Sale, Incoming Payment, and Dispatch

### Trigger

The trader requests gold from the center.

### 24.1 Gold Request and Pricing

1. Trader creates a gold request.
2. Center reviews weight, type, purity, and availability.
3. Center creates a pricing version.
4. Trader sees the applicable price and expiry/conditions where relevant.
5. Material price change creates a new pricing version.

### 24.2 Incoming Payment Registration

1. Trader submits incoming-payment information or receipt.
2. Source file enters private file lifecycle.
3. Accountant imports or reviews bank statement data.
4. Statement import uses an immutable import run.
5. Candidate incoming transactions are proposed or searched manually.
6. Accountant confirms an incoming-payment match.
7. Partial payment and overpayment are shown explicitly.

### 24.3 Settlement Type

The UX distinguishes:

- physical incoming payment;
- account offset;
- mixed settlement;
- unresolved settlement.

### 24.4 Dispatch Guard

Before dispatch:

- required settlement amount is satisfied;
- incoming payment is confirmed;
- no unresolved reconciliation block exists;
- order and pricing version are valid;
- warehouse user has dispatch permission.

Warehouse may see:

- cleared/not cleared;
- dispatch quantity;
- delivery details;
- blocking reason.

Warehouse does not receive authority to override financial verification.

### 24.5 Dispatch and Receipt

1. Warehouse registers dispatch.
2. System records time, actor, quantity, and reference.
3. Trader sees dispatch status.
4. Trader confirms receipt or reports an issue.
5. Order closes only after required settlement and delivery conditions are met.

---

## 25. Journey 19 — No AI/OCR Available

### Trigger

AI is disabled, unavailable, blocked by policy, over budget, or not implemented.

### UX Behavior

- Core journeys remain available.
- Manual crop remains available.
- Manual attempt search remains available.
- Manual evidence confirmation remains available.
- Manual paid/failed confirmation remains available.
- Accountant sees an operational warning only when relevant.
- Trader does not see provider-health details.

### Rule

The product must feel complete without AI.

---

## 26. Journey 20 — Later AI-assisted Processing

Phase 1B or later may add:

- OCR on a human-selected crop or page;
- extracted-field review;
- deterministic candidate suggestions;
- shadow-mode evaluation;
- later automatic segmentation proposals.

### Assisted Journey

1. Human selects an allowed source scope.
2. Policy evaluator confirms provider and data-class permission.
3. AI job runs asynchronously.
4. UI shows provider-neutral processing state.
5. Extracted raw and normalized values are shown.
6. Human accepts, corrects, or rejects fields.
7. Candidate suggestions remain separate from evidence confirmation.
8. Human completes the ordinary authoritative journeys.

### Rules

- AI output is never the active financial decision.
- Confidence is not displayed as “94% paid.”
- Provider failure returns work to manual review.
- External transmission must follow minimization and provider policy.
- Full-document transmission is not the default when a crop or single page is sufficient.

---

## 27. Queue and Ownership UX

### 27.1 Accountant Queues

Recommended groups:

- new requests;
- corrected requests;
- requests eligible for batching;
- draft batch versions needing work;
- bank results awaiting processing;
- crop jobs failed;
- unmatched segments;
- evidence awaiting confirmation;
- attempts awaiting result confirmation;
- failed attempts needing retry;
- overpayment reconciliation;
- trader disputes;
- publication corrections;
- incoming-payment review.

### 27.2 Manager Queues

- batch versions awaiting exact approval;
- rejected/replacement version review where relevant;
- sensitive correction approval;
- exceptional reconciliation approval;
- policy-defined high-risk actions.

### 27.3 Warehouse Queues

- cleared for dispatch;
- blocked for settlement;
- dispatched awaiting trader receipt;
- receipt dispute.

### 27.4 Queue Item Requirements

Each queue item should show:

- what it is;
- amount where relevant;
- current status;
- age;
- warning/block reason;
- owner/assignee where supported;
- exact next action.

### 27.5 No Dangerous Bulk Actions

Do not provide bulk actions for:

- approve batch versions;
- confirm paid;
- publish results;
- mark exports sent;
- dispatch gold;
- correct confirmed records.

---

## 28. Notification UX

Phase 1A may use in-app notifications and status updates.

### Trader Events

- account approved or rejected;
- request returned for correction;
- request accepted for processing;
- result published;
- publication corrected;
- dispute updated;
- gold order priced;
- gold dispatched;
- gold order closed.

### Internal Events

- batch version ready for approval;
- version rejected;
- approval invalidated by replacement;
- final export ready;
- export integrity failure;
- bank-result bundle available;
- crop failed;
- evidence conflict;
- overpayment reconciliation required;
- dispute received;
- backup or operational incident alerts for authorized operators.

### Notification Rules

- Notifications are not the system of record.
- Opening a notification re-reads current state.
- Sensitive financial details are minimized.
- A notification for a superseded version must redirect to current state with context.

---

## 29. Search, Filter, and Navigation Behavior

Search should support operational retrieval without exposing unauthorized data.

### Accountant Search Examples

- request reference;
- trader;
- beneficiary;
- IBAN fragment where permitted;
- amount;
- batch/version;
- attempt;
- export;
- tracking number;
- bundle.

### Rules

- Search results apply permission and object-scope filters.
- No cross-trader result leakage through suggestions or counts.
- Deep links revalidate access.
- Search does not execute financial actions.
- Filter state may be preserved only when it contains no sensitive data.

---

## 30. Empty, Waiting, and Blocked States

### 30.1 Empty Queue

```text
No batch versions are waiting for your approval.
New exact versions will appear here after accountant finalization.
```

### 30.2 No Trader Results

```text
No payment result has been published yet.
You can follow the current request status from this page.
```

### 30.3 Crop Processing

```text
The selected area is being prepared.
You may leave this page; the result will remain in the processing queue.
```

### 30.4 Stale Version

```text
This version is no longer current.
A replacement version must be reviewed before any decision.
```

### 30.5 Financial Writes Blocked

```text
Financial changes are temporarily paused for maintenance.
You may review current records, but no new financial command can be submitted.
```

---

## 31. Error Recovery Matrix

| Error | Required UX |
|---|---|
| `400` validation | Field or form-level correction; preserve safe input |
| `401` session expired | Reauthenticate, re-read state, reconcile unknown command outcome |
| `403` forbidden | Explain lack of permission without leaking protected data |
| `404` not found/ownership-safe | Generic unavailable message |
| `409` domain conflict | Show business conflict and current state |
| `409` idempotency conflict | Stop, preserve reference, reconcile prior command |
| `412` version conflict | Show stale-state comparison and require review |
| `428` precondition required | Reload current record; do not blind retry |
| `422` workflow validation | Explain unmet domain guard |
| `503` dependency unavailable | Preserve manual fallback where possible |
| timeout | Unknown-outcome recovery with same idempotency key |

## 31.1 Upload Failure

Show:

- file name;
- file state;
- safe reason;
- retry action;
- allowed types and size;
- whether other files succeeded.

## 31.2 Quarantined File

Do not offer preview or use.

Provide an internal operational next step without revealing malware-scanner internals unnecessarily.

## 31.3 Worker Failure

The financial record remains unchanged.

Allow retry of the processing job where safe.

## 31.4 Export Integrity Failure

- quarantine export;
- block download and mark-sent;
- show mismatch categories;
- create urgent review task;
- preserve the approved version.

## 31.5 Stale Data

Show:

- what changed when safe;
- current version;
- whether the user's unsaved changes can be manually re-applied;
- no automatic merge for financial decisions.

## 31.6 Permission Denied

If the user may read the record, retain the read context and explain why the action is unavailable.

If the user may not read the record, use ownership-safe behavior.

---

## 32. Correction and Replacement Language

Use language that preserves history:

- Create correction;
- Replace evidence;
- Supersede publication;
- Create replacement batch version;
- Revoke active publication;
- Cancel request;
- Void link.

Avoid misleading generic labels:

- Edit approved batch;
- Delete paid result;
- Change history;
- Replace bank record silently.

---

## 33. Status Communication

Internal status codes must map to concise Persian user-facing language.

The UI should not expose raw enum names.

### 33.1 Trader-facing Request Groups

| Internal meaning | Trader presentation |
|---|---|
| draft | Draft |
| submitted/review | Sent to center / Under review |
| correction required | Your correction is required |
| eligible/batched/sent | Processing by center |
| partial | Partially paid |
| paid/result ready | Payment completed / Result being prepared |
| published | Result available |
| disputed | Issue under review |
| cancelled/closed | Cancelled / Closed |

### 33.2 Admin Status Detail

Admin users may see exact workflow states, but the next allowed action must be more prominent than the raw code.

### 33.3 Version Status

Clearly distinguish:

- draft;
- ready for approval;
- approved;
- rejected;
- superseded;
- approval invalidated.

---

## 34. Accessibility and RTL Interaction

### 34.1 Keyboard

All critical journeys must be usable without a pointer.

Manual crop must provide a numeric-coordinate alternative or equivalent accessible control.

### 34.2 Focus

After:

- modal close;
- command success;
- error;
- version conflict;
- recent authentication;

focus must move to a meaningful element.

### 34.3 Screen Readers

Financial summaries must be read in a stable order:

- action;
- amount and unit;
- beneficiary;
- version;
- effect;
- warning;
- confirmation control.

### 34.4 RTL and LTR Isolation

IBAN, tracking numbers, hashes, and filenames are isolated as LTR content inside the RTL interface.

### 34.5 Status

Do not use color alone.

Use text, icon/shape, and accessible labels.

### 34.6 Motion

Respect reduced-motion preferences.

Do not use celebratory animation for high-value financial completion.

---

## 35. Security and Privacy UX

- Never display raw storage paths.
- Use authorized preview and download commands.
- Do not persist private file URLs.
- Mask IBAN based on role and context.
- Do not log sensitive form values to client analytics.
- Do not place financial details in URL query strings.
- Do not show another trader in search autocomplete.
- Do not expose internal audit content to traders.
- Do not provide generic admin impersonation.
- Break-glass, if later enabled, must show a persistent warning and expiry.

---

## 36. Operational Metrics for UX Evaluation

Measure without collecting unnecessary sensitive data.

Useful metrics:

- queue age;
- time from submission to accountant review;
- time from batch finalization to manager decision;
- crop completion/failure rate;
- evidence-confirmation rework rate;
- version-conflict rate;
- timeout-recovery rate;
- request correction rate;
- publication correction rate;
- dispute rate;
- overpayment-block count;
- manual vs assisted processing ratio in later phases.

Do not use payment amount, IBAN, beneficiary, tracking number, or raw evidence as analytics labels.

---

## 37. Phase 1A UX Acceptance Criteria

Phase 1A UX is acceptable only if:

1. Trader can submit a request with an explicit amount unit.
2. Trader can understand correction requests and create a new revision.
3. Accountant can process work from queues.
4. Accountant marks revisions eligible for batching without request-level manager approval.
5. Server split preview is clear and deterministic.
6. Accountant can finalize an immutable batch version.
7. Manager can review and approve the exact version/hash.
8. A stale approval screen is blocked.
9. Preview export is visibly non-sendable.
10. Final export integrity is visible.
11. Download is clearly separate from mark-as-sent.
12. Bank-result upload works without OCR.
13. Internal manual rectangular crop works for image and PDF sources.
14. Crop, candidate, evidence, result, and publication are separate journeys.
15. Overpayment is blocked.
16. Failed attempts can create new retry attempts.
17. Trader sees only an immutable safe publication.
18. Trader can acknowledge or dispute a publication version.
19. Material correction creates preserved history and a replacement publication.
20. Timeout recovery does not duplicate financial commands.
21. Version conflicts do not silently overwrite newer data.
22. Sensitive browser storage and offline financial queues are absent.
23. Technical Admin has no implicit financial journey.
24. Gold dispatch is blocked until required settlement conditions are met.
25. Core work remains available with AI disabled.

---

## 38. UX QA Scenarios

QA must execute at least the following journeys.

### 38.1 Trader and Request

1. New trader registration and approval.
2. Pending trader deep-link denial.
3. Trader creates Toman request and verifies canonical IRR.
4. Trader creates Rial request.
5. Request timeout and idempotent recovery.
6. Accountant returns request for correction.
7. Trader creates revision N+1.
8. Stale revision submission is blocked.
9. Duplicate-looking request warning.

### 38.2 Batching and Approval

10. Accountant marks revision eligible.
11. Server split preview.
12. Concurrent double-selection prevention.
13. Finalize immutable batch version.
14. Attempt to edit finalized version is blocked.
15. Create replacement version.
16. Manager exact-version approval.
17. Separation-of-duty denial.
18. Recent-authentication expiry.
19. Stale approval after replacement version.
20. Concurrent manager decision.
21. Approval timeout recovery.

### 38.3 Export

22. Preview export watermark.
23. Final export from approved version.
24. Integrity mismatch quarantine.
25. Download does not change sent state.
26. Exact export mark-as-sent.
27. Mark-sent timeout recovery.

### 38.4 Bank Result and Crop

28. Mixed bank-result bundle upload.
29. Partial multi-file upload.
30. Quarantined file behavior.
31. PDF page navigation and crop.
32. Image crop.
33. Rotation and normalized coordinates.
34. Crop worker failure and retry.
35. External evidence fallback.
36. Privacy-review rejection.

### 38.5 Evidence and Result

37. Manual attempt search.
38. Candidate selection without financial effect.
39. Create primary confirmed evidence.
40. Concurrent primary-evidence conflict.
41. Confirm paid exact amount.
42. Confirm partial aggregate.
43. Block overpayment.
44. Confirm failed with reason.
45. Text-only exception denied by default.
46. Create retry attempt.

### 38.6 Publication and Correction

47. Create immutable publication.
48. Trader views only own publication.
49. Trader shares safe artifact.
50. Trader acknowledges version.
51. Trader disputes version.
52. Replace evidence after publication.
53. Sensitive payment-result correction.
54. Create publication N+1.
55. Superseded publication behavior.
56. Notification of corrected result.

### 38.7 Gold and Incoming Settlement

57. Pricing version update.
58. Incoming statement import preview.
59. Partial incoming payment.
60. Incoming overpayment reconciliation.
61. Dispatch blocked before settlement.
62. Dispatch allowed after settlement.
63. Warehouse financial override denied.

### 38.8 Security and Recovery

64. Cross-trader route denial.
65. Session expiry before command.
66. Session expiry after unknown command outcome.
67. Permission removed while page open.
68. 412 version conflict.
69. 428 precondition required.
70. Idempotency key reused with different payload.
71. Maintenance financial-write block.
72. No AI provider available.

---

## 39. Coding Agent Rules

A coding agent must:

1. Implement journeys, not generic CRUD pages.
2. Preserve the two separate frontend applications.
3. Use document `06` for allowed transitions.
4. Use document `12` for permissions and ownership.
5. Use document `21` for screen/component structure.
6. Treat Phase 1A manual rectangular crop as required.
7. Never add request-level manager approval.
8. Bind manager approval to exact immutable batch version/hash.
9. Never edit a finalized batch version.
10. Separate preview and final export.
11. Separate download and mark-as-sent.
12. Separate candidate, evidence, result, and publication.
13. Never treat candidate acceptance as paid confirmation.
14. Never expose mixed bank bundles to traders.
15. Never store canonical money as floating-point.
16. Require explicit IRR/Toman input unit.
17. Preserve entered value and unit.
18. Use `If-Match` for protected mutable commands.
19. Use a stable idempotency key for one logical command.
20. Reconcile unknown outcomes before retrying.
21. Never create a new key after a timeout without reconciliation.
22. Never use financial optimistic finality.
23. Never queue financial commands offline.
24. Never persist sensitive financial drafts in browser storage.
25. Never silently merge stale financial edits.
26. Never provide an ordinary overpayment override.
27. Never mutate a failed attempt into a retry.
28. Never edit a trader publication in place.
29. Preserve correction history.
30. Require recent authentication where policy defines it.
31. Revalidate the version after recent authentication.
32. Keep Technical Admin outside financial journeys by default.
33. Keep warehouse users outside financial confirmation.
34. Do not add generic impersonation.
35. Do not expose raw storage keys or private URLs.
36. Handle file lifecycle and quarantine states.
37. Provide accessible non-drag crop controls.
38. Test RTL, LTR isolation, keyboard, and screen-reader behavior.
39. Add negative, timeout, and concurrency tests for sensitive journeys.
40. Report unresolved ADRs rather than inventing policy.

---

## 40. Final UX Rule

The operational chain is:

```text
request
→ immutable revision
→ accountant review
→ eligible for batching
→ deterministic attempts
→ immutable batch version
→ exact manager approval
→ final export
→ exact mark-as-sent
→ private bank result
→ controlled crop or manual source
→ candidate review
→ confirmed evidence
→ payment result
→ immutable trader publication
→ acknowledgement or dispute
→ governed correction
→ complete audit history
```

Any interaction that breaks this traceability, hides the exact version, bypasses human authority, exposes unrelated bank data, or creates an unrecoverable duplicate financial command must be rejected.
