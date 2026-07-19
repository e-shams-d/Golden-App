# Gold Trade Settlement Platform

## Product Requirements Document (PRD)

**Document ID:** `01_Product_Requirements_PRD`  
**Version:** `1.1`  
**Status:** Revised product baseline — pending final project-owner approval  
**Document owner:** Product Owner  
**Technical reviewers:** Technical Lead, DevOps, Security, Backend, Frontend, QA  
**Language:** English  
**Primary audience:** Product owner, technical lead, backend engineer, frontend engineer, QA engineer, DevOps engineer, AI/OCR engineer, and coding agents  
**Authoritative parent document:** `00_Master_Implementation_Blueprint.md`  

### Change Log

| Version | Summary |
|---|---|
| `1.0` | Initial product requirements baseline. |
| `1.1` | Aligned the PRD with Blueprint 1.1; clarified process modernization, batch-level approval, beneficiary management, amount policy, evidence cardinality, manual crop scope, UI/UX direction, security, gold-sale controls, notifications, concurrency, production readiness, phase boundaries, and acceptance gates. |

---

## 1. Purpose

This Product Requirements Document defines the product behavior, user roles, functional requirements, acceptance criteria, edge cases, non-functional requirements, and phase boundaries for the **Gold Trade Settlement Platform**.

The product is a standardized, role-based, multi-bank operational platform for managing gold sale, incoming-payment verification, outgoing-payment preparation, bank processing, evidence, approvals, disputes, and audit history.

Existing phone calls, messenger conversations, spreadsheets, photographed documents, and paper records are discovery inputs. They reveal business needs, exceptions, and operational risks, but they are **not** templates for the target product.

The product must preserve required business outcomes and authority boundaries while improving how work is performed through structured data, controlled workflows, work queues, validation, versioning, and traceable decisions.

The product supports two major operational domains:

1. **Gold Sale and Incoming Payment Verification**  
   The center/importer sells gold to a known trader. The expected amount is recorded, the trader submits incoming-payment evidence, the center verifies the payment against bank data, and authorized staff record dispatch or settlement.

2. **Outgoing Payment Management for Retail Gold Sellers**  
   A trader submits a structured request for the center to pay a beneficiary. The accountant validates requests and prepares an exact payment batch, the manager approves the batch snapshot, the system generates a versioned bank file, the accountant submits it manually in Phase 1A, bank results are reviewed, and confirmed results are safely published to the owning trader.

Phase 1A must not depend on AI, OCR, automatic segmentation, or bank APIs. These are optional future capabilities and must never replace human authority for financial confirmation.

---

## 2. Product Vision

The product should become the authoritative operational workspace for the center and its known traders.

It must replace fragmented, untracked execution with:

- structured requests instead of free-form operational messages;
- reusable beneficiary records instead of repeated manual entry;
- work queues instead of searching conversations and raw spreadsheets;
- exact batch snapshots instead of ambiguous approval;
- versioned bank exports instead of overwritten files;
- private evidence records instead of sharing full mixed bank documents;
- explicit corrections instead of silent edits or deletion;
- role-based decisions instead of informal confirmation;
- searchable audit history instead of relying on memory.

The product should reduce:

- repeated data entry;
- unit and zero-count mistakes;
- incorrect IBAN or beneficiary selection;
- duplicate or omitted payment rows;
- unclear payment status;
- evidence attached to the wrong payment;
- exposure of unrelated financial information;
- delays caused by manual searching;
- disputes caused by incomplete history;
- operational dependence on any single external service.

The product should increase:

- operational speed;
- financial safety;
- accountability;
- transparency for traders;
- manager confidence in outgoing payments;
- consistency across different banks;
- recoverability and production reliability;
- readiness for future automation.

---

## 3. Product Principles

### 3.1 Preserve business intent; modernize execution

Required business outcomes, accountant responsibilities, manager authority, and financial controls must be preserved.

Legacy tools and interaction patterns do not need to be preserved. The product may redesign forms, screens, queues, document handling, and operational steps when the result:

- preserves the required outcome;
- does not bypass approval;
- reduces financial error;
- reduces duplicate work;
- improves traceability;
- keeps a complete history;
- remains practical for gold-trade business users.

The product must not imitate a messenger, spreadsheet, or paper form unless that interaction is demonstrably the best operational solution.

### 3.2 Manual-first, automation-ready

The official workflow must work when AI/OCR, bank APIs, or external validation providers are unavailable. Manual operation must still produce structured records that future automation can use.

### 3.3 AI assists but does not decide

AI/OCR may extract, segment, rank, compare, warn, and suggest. It must not approve a batch, confirm a payment, publish an official result, or overwrite a human-confirmed decision.

### 3.4 Human authority is explicit

- Accountant verifies operational and bank-result evidence.
- Manager approves the exact outgoing-payment batch before it can be submitted to the bank.
- Technical administrators cannot bypass business approval merely because they manage the system.

### 3.5 Every financial record is traceable

Every sensitive action must identify:

- actor;
- timestamp;
- action;
- target record and version;
- previous and new values where relevant;
- related evidence or file;
- reason/comment where required;
- approval or correction context.

### 3.6 Financial records are corrected, not erased

Normal users must not delete financial history. Use controlled states such as `cancelled`, `voided`, `superseded`, `replaced`, or `archived`, with audit history.

### 3.7 Phase 1A is production-usable

Phase 1A is not a demo. It must include security, backup, restore testing, monitoring, rollback, and end-to-end operational acceptance in addition to business screens.

### 3.8 Role-specific user experience

The product must support experienced commercial users:

- Trader application: mobile-first, concise, status-driven.
- Accountant application: desktop-first, information-dense but controlled, queue-first, keyboard-efficient where practical.
- Manager application: decision-focused, showing exact totals, warnings, changes, and approval version.

### 3.9 Multi-bank behavior is configurable

Bank templates, mappings, limits, split rules, transfer channels, required fields, source accounts, and result-format hints must be configuration or versioned profile data—not hard-coded product logic.

---

## 4. Scope Overview

### 4.1 In scope for the overall product

The product vision includes:

- responsive Trader PWA/web application;
- responsive Admin/Accountant/Manager web application;
- trader registration, approval, suspension, and history;
- beneficiary creation, validation, reuse, blocking, and history;
- gold sale requests and incoming-payment verification;
- outgoing payment requests;
- payment attempts and bank-rule splitting;
- payment batch preparation and validation;
- immutable batch snapshots;
- batch-level manager approval;
- versioned bank Excel generation;
- bank statement upload and mapping;
- bank result bundle upload;
- image/PDF preview;
- minimal manual crop/receipt-segment creation;
- manual result registration;
- evidence attachment, visibility, replacement, and correction history;
- unmatched/manual-review queues;
- result publication and dispute handling;
- operational and management dashboards;
- audit logging;
- secure file handling;
- configurable bank profiles;
- staging, backup, restore, monitoring, deployment, and rollback;
- future AI/OCR, automatic segmentation, matching, risk signals, and banking integrations.

### 4.2 Out of scope for Phase 1A

The following are out of scope unless explicitly re-approved:

- OCR as a required step;
- automatic receipt segmentation;
- automatic financial matching or confirmation;
- automatic fraud or compliance decisions;
- bank API integration;
- automatic national-ID/IBAN ownership validation;
- real-time gold-price integration;
- full accounting-ledger replacement;
- internal two-way chat;
- SMS as an operational dependency;
- retail seller login;
- native mobile application;
- multi-company SaaS;
- subscription/billing;
- bulk import as the primary operational submission method;
- administrator impersonation of trader accounts.

### 4.3 Required Phase 1A product boundary

Phase 1A must include:

- secure authentication and revocable sessions;
- RBAC and trader data isolation;
- trader onboarding and approval;
- beneficiary management;
- outgoing payment request creation and correction;
- gold sale request basic flow;
- bank profiles and source accounts;
- bank statement upload and manual incoming-payment verification;
- payment batch preparation;
- validation and exact batch preview;
- manager approval of immutable batch snapshot;
- versioned final bank export;
- manual sent-to-bank confirmation;
- bank result bundle upload;
- image/PDF preview;
- minimal rectangular crop/segment creation plus external attachment fallback;
- manual result registration and payment-attempt confirmation;
- safe trader result publication and acknowledgement/dispute;
- work queues and basic reports;
- audit and correction history;
- Persian/RTL product behavior;
- canonical IRR handling and explicit input units;
- secure private file storage;
- idempotency and concurrency protection for critical actions;
- staging, CI gates, backups, restore test, monitoring, deployment, and rollback procedures.

---

## 5. User Roles and Personas

### 5.1 Trader / Goldsmith

**Description:** A known business customer of the center. The trader may buy gold from the center and may ask the center to pay beneficiaries.

**Main goals:**

- submit structured requests quickly;
- reuse valid beneficiary information;
- understand the current status and next action;
- see completed, partial, failed, or disputed results;
- download/share authorized payment proof;
- reduce operational calls and messages.

**Access:** Trader PWA/responsive web application.

**Important constraints:**

- The trader sees only records belonging to their trader account.
- The trader cannot access full mixed bank bundles.
- The trader cannot confirm bank-level completion; the trader can acknowledge a published result or report an issue.
- Submitted records cannot be silently edited; correction uses a controlled return-and-resubmit flow.

### 5.2 Retail Gold Seller / Beneficiary

**Description:** A payment recipient introduced by a trader. This person does not log in.

**Access:** No system account in Phase 1A.

**Important constraints:**

- Beneficiary identity/bank data is a reusable sensitive record scoped to the owning trader or authorized center users.
- Payment amount belongs to the payment request, not the beneficiary.
- A beneficiary may be used in multiple requests with different amounts.
- The trader shares authorized payment proof externally.

### 5.3 Accountant

**Description:** Center employee responsible for daily financial operations and bank-result review.

**Main goals:**

- review and return requests for correction;
- validate beneficiary, IBAN, amount, and bank rules;
- prepare and revise batches;
- upload bank statements and result bundles;
- create manual receipt segments;
- register and confirm payment-attempt results;
- resolve unmatched, partial, failed, and disputed records;
- preserve evidence and correction history.

**Access:** Admin/Accountant web application.

**Important constraints:**

- The accountant prepares batches but does not approve outgoing money.
- The accountant cannot alter approved batch content without invalidating approval.
- Evidence-only corrections may be made through a traceable correction flow.
- Financial-outcome corrections require the authorization defined by security/workflow policy.

### 5.4 Manager

**Description:** Business decision-maker responsible for outgoing-money approval and critical overrides.

**Main goals:**

- review the exact batch snapshot;
- see bank/source account, row count, total amount, warnings, and changed rows;
- approve, reject, or request changes;
- review unusual/high-risk operations and business reports.

**Access:** Admin/Manager web application.

**Important constraints:**

- Phase 1A approval is batch-level for all outgoing batches.
- The manager is not forced to approve every ordinary row separately.
- Approval is tied to a batch version and content hash.
- Any material change invalidates the prior approval.
- Approval requires recent authentication or step-up confirmation according to security policy.

### 5.5 Warehouse / Dispatch Operator

**Description:** User responsible for registering physical gold dispatch, delivery, receipt, or supported settlement type.

**Access:** Admin web application with limited permissions.

**Important constraints:**

- No banking or approval access unless explicitly assigned.
- Dispatch records cannot be created before required payment/approval guards pass.

### 5.6 Technical Admin

**Description:** User responsible for system configuration and operational support.

**Main goals:**

- manage bank profiles, mappings, source accounts, and feature flags;
- manage technical users and operational settings;
- monitor service health;
- configure optional providers in later phases.

**Important constraints:**

- Technical administration does not imply business approval rights.
- Full financial-file access is not granted by default.
- Configuration changes are versioned and audited.
- Support must not use untracked account impersonation.

### 5.7 Read-only Auditor/User

**Description:** Authorized internal viewer who can inspect permitted reports, records, and history without changing financial state.

**Important constraints:**

- No create/update/delete/approve permissions.
- Sensitive identifiers are masked unless the assigned role explicitly allows full values.
- Audit access itself may be logged.

---

## 6. High-Level User Journeys

### 6.1 Trader submits outgoing payment requests

1. Trader logs in to the PWA/web application.
2. Trader selects an existing beneficiary or creates a new one.
3. System validates the IBAN structure and detects possible duplicate beneficiary data.
4. Trader enters amount with an explicit unit and optional description/attachment.
5. System displays the canonical IRR value, Toman equivalent, and amount-in-words where appropriate.
6. Trader saves drafts or reviews multiple requests as a submission set.
7. Trader confirms the total count and amount, then submits.
8. Submitted records become read-only for normal editing.
9. Accountant receives the requests in a work queue.
10. If correction is required, the accountant returns the affected request with a structured reason.

### 6.2 Accountant prepares a payment batch and manager approves it

1. Accountant opens eligible outgoing payment requests.
2. Accountant filters and selects requests for a bank/source account.
3. System validates request eligibility, beneficiary data, IBAN, duplicates, and bank-profile requirements.
4. System creates payment attempts according to versioned bank split rules.
5. System creates or updates a draft batch and calculates exact row count and total IRR.
6. Accountant reviews the batch, invalid rows, warnings, and draft preview.
7. Accountant submits the immutable batch version for manager approval.
8. Manager reviews bank profile, source account, rows, totals, warnings, and changes.
9. Manager approves, rejects, or requests changes.
10. Only an approved unchanged snapshot can produce the final downloadable bank export.
11. Accountant downloads and submits the file to the bank outside the platform in Phase 1A.
12. Accountant records the sent date/time and optional bank reference.

### 6.3 Accountant processes a bank result bundle

1. Accountant uploads one or more original result files.
2. System stores original files before any derived processing.
3. Accountant previews images or PDF pages inside the review workspace.
4. Accountant may create a minimal rectangular receipt segment or upload external evidence.
5. Accountant selects the related payment attempt.
6. Accountant records success, failure, pending/unknown, tracking number, date, and notes.
7. System validates that a primary confirmed evidence link is not duplicated.
8. Accountant confirms the operational result.
9. System recalculates the parent request and batch status.
10. Unmatched or ambiguous items remain in a review queue.
11. Authorized result data is published to the owning trader.

### 6.4 Trader views and shares a payment result

1. Trader opens a published result.
2. Trader sees a concise summary and only authorized evidence.
3. Trader may download/share a clean generated result card or authorized evidence.
4. Trader acknowledges the result or reports an issue with a reason.
5. A reported issue creates an accountant review item and does not automatically reverse the financial status.

### 6.5 Gold sale and incoming-payment verification

1. Trader or authorized center user creates a gold sale order.
2. Authorized center user records pricing/expected amount and required gold details.
3. Trader submits structured incoming-payment details and evidence.
4. Accountant uploads/searches bank statement data.
5. Accountant links the bank row and verifies the incoming payment.
6. Any rule-based manager approval is completed where required by the gold-sale policy.
7. Dispatch/settlement is recorded by an authorized user.
8. Trader receipt is recorded where applicable.
9. Order is closed only when no unresolved review/dispute remains.

---

## 7. Functional Requirements

Functional requirements use the following convention:

```text
FR-[MODULE]-[NUMBER]
```

Priority levels:

- **P0:** Required for Phase 1A MVP.
- **P1:** Important for Phase 1B or early enhancement.
- **P2:** Later phase.

---

## 8. Authentication and Access

### FR-AUTH-001 — Internal-user login

**Priority:** P0  
**Description:** Accountant, manager, dispatch, technical-admin, and read-only users authenticate through the Admin web application using secure credentials.

**Acceptance criteria:**

- Login identifier supports the approved username/email/phone policy.
- Passwords are stored only with an approved adaptive password hash.
- Failure response does not reveal whether an account exists.
- Disabled/suspended users cannot create new sessions.
- Successful and failed login events are audited with safe metadata.
- Default/demo credentials are not allowed in production.

### FR-AUTH-002 — Trader login

**Priority:** P0  
**Description:** Approved traders authenticate to the Trader PWA/web application without creating an SMS dependency for ordinary access.

**Acceptance criteria:**

- Approved trader can log in.
- Pending trader sees a pending-approval state without operational access.
- Rejected/suspended trader cannot use financial features.
- Authentication method supports recovery without exposing sensitive account data.
- Login events are audited.

### FR-AUTH-003 — Role-based and ownership-based authorization

**Priority:** P0  
**Acceptance criteria:**

- Accountant, manager, dispatch, technical admin, read-only/auditor, and trader permissions are distinct.
- Backend enforces action permission and record ownership/scope.
- Trader isolation applies to APIs, files, search, exports, notifications, and indirect identifiers.
- Technical admin has no implicit manager approval or unrestricted financial-file access.
- Unauthorized access returns safe errors and may create a security event.
- Role/permission changes are audited.

### FR-AUTH-004 — Secure session lifecycle

**Priority:** P0  
**Acceptance criteria:**

- User can log out and active session is invalidated.
- Sessions expire according to role/configuration.
- Password reset, deactivation, or high-risk security action revokes relevant sessions.
- Refresh/session rotation and replay protection are supported by the selected ADR.
- Session/cookie/token secrets are never available to frontend JavaScript unless explicitly required by the approved design.

### FR-AUTH-005 — Login abuse protection

**Priority:** P0  
**Acceptance criteria:**

- Rate limiting or equivalent protection applies to login/recovery endpoints.
- Repeated failures trigger controlled delay, temporary lock, or alert according to policy.
- Lock behavior cannot be abused to disclose accounts.
- Security events are observable without logging passwords or tokens.

### FR-AUTH-006 — Step-up/recent authentication for sensitive actions

**Priority:** P0  
**Description:** Manager approval and selected high-risk actions require a recent authenticated context or step-up verification.

**Acceptance criteria:**

- Approval is blocked when the authentication context is too old or invalid.
- Re-authentication does not lose the reviewed batch context.
- Successful/failed step-up attempts are audited.
- Exact technical method is defined in the authentication ADR.

### FR-AUTH-007 — Account recovery and credential administration

**Priority:** P0  
**Acceptance criteria:**

- Recovery/reset is performed only through an approved secure process.
- Administrative reset forces credential change or session revocation as appropriate.
- Recovery cannot depend on an unavailable external provider without a controlled fallback.
- Recovery actions are audited.

---

## 9. Trader and Beneficiary Management

### FR-TRADER-001 — Trader registration

**Priority:** P0  
**Description:** Traders must be able to register or be created by the center.

**Acceptance criteria:**

- Trader can submit basic registration information.
- Newly registered trader status is `pending_approval`.
- Pending trader cannot create operational requests.
- Admin can create trader manually.

### FR-TRADER-002 — Trader approval

**Priority:** P0  
**Description:** Manager or authorized admin can approve, reject, suspend, or reactivate traders.

**Acceptance criteria:**

- Approved traders can use the PWA.
- Rejected traders cannot log into operational areas.
- Suspended traders cannot submit new requests.
- Status changes are audited.

### FR-TRADER-003 — Trader profile

**Priority:** P0  
**Description:** Admin users can view and edit trader profile information.

**Suggested fields:**

- display name;
- business name;
- mobile number;
- status;
- notes;
- allowed bank accounts/IBANs if applicable;
- risk label;
- created date;
- last activity.

**Acceptance criteria:**

- Admin can search traders.
- Admin can view trader history.
- Sensitive edits are audited.

### FR-TRADER-004 — Future support for multiple trader users

**Priority:** P2  
**Description:** Phase 1A may allow only one login per trader, but the data model should not prevent future sub-users.

**Acceptance criteria:**

- Database design can later support multiple users under one trader account.
- Phase 1A UI may expose only one user per trader.

---

### FR-BEN-001 — Create and reuse beneficiary

**Priority:** P0  
**Description:** Trader or authorized accountant can create a reusable beneficiary record.

**Required fields:**

- full name;
- destination IBAN;
- optional bank name;
- optional national ID;
- optional phone;
- notes/status where authorized.

**Acceptance criteria:**

- Beneficiary is scoped to its owning trader unless an authorized center policy allows controlled sharing.
- The same beneficiary can be reused in multiple payment requests.
- Amount is not stored on the beneficiary record.
- IBAN is normalized for comparison while preserving the user-entered representation where needed.
- Creation and sensitive edits are audited.

### FR-BEN-002 — Beneficiary validation and duplicate warning

**Priority:** P0  
**Description:** The system validates beneficiary data before a request becomes eligible for batching.

**Acceptance criteria:**

- IBAN structure and checksum are validated locally where possible.
- Duplicate or near-duplicate beneficiary records produce a warning.
- A warning does not automatically merge records.
- Blocked/inactive beneficiaries cannot be used without an authorized override and reason.
- External ownership validation is not required for Phase 1A.

### FR-BEN-003 — Beneficiary correction and history

**Priority:** P0  
**Description:** Beneficiary corrections must preserve the effect on existing payment records.

**Acceptance criteria:**

- Editing a beneficiary does not silently rewrite historical requests or approved batches.
- Payment requests retain a snapshot/reference of the beneficiary data used for that request.
- Material beneficiary changes invalidate any affected pending batch approval.
- Previous values remain available in audit history.

---

## 10. Outgoing Payment Request Management

### FR-PAYREQ-001 — Create outgoing payment request

**Priority:** P0  
**Description:** Trader can create a structured payment request for a beneficiary.

**Required Phase 1A fields:**

- beneficiary reference;
- requested amount;
- explicit input unit (`Toman` or `IRR`);
- optional purpose/description;
- optional national-ID snapshot where policy requires it;
- optional attachment.

**Acceptance criteria:**

- Trader can save a draft.
- Trader can submit the request to the center.
- Required fields are validated.
- Canonical amount is stored as integer IRR.
- Original entered value and unit are retained.
- UI shows the converted canonical amount before submission.
- Unit is never inferred silently.
- Duplicate-submit protection prevents accidental duplicate requests.

### FR-PAYREQ-002 — Controlled request lifecycle

**Priority:** P0  
**Description:** Payment request status is controlled and represents the aggregate business state, not the state of an individual bank row.

**Minimum internal statuses:**

- `draft`;
- `submitted_to_center`;
- `under_accountant_review`;
- `needs_trader_correction`;
- `eligible_for_batching`;
- `included_in_batch`;
- `bank_result_pending`;
- `partially_paid`;
- `paid`;
- `failed`;
- `needs_retry`;
- `result_ready_for_trader`;
- `confirmed_by_trader`;
- `disputed_by_trader`;
- `cancelled`;
- `closed`.

**Acceptance criteria:**

- Invalid transitions are blocked on the backend.
- Request approval is not confused with manager batch approval.
- Status derived from attempts is recalculated consistently.
- Every transition is audited.
- Trader sees simplified Persian labels and next action.
- Admin users see detailed operational state and blocking reason.

### FR-PAYREQ-003 — Multi-request review before submission

**Priority:** P0  
**Description:** Trader can review one or more drafts before submitting them.

**Acceptance criteria:**

- Trader sees count and total in both relevant units.
- Invalid drafts are clearly identified.
- Trader can edit draft items.
- Submission requires explicit confirmation of count and total.
- After submission, normal editing is blocked.

### FR-PAYREQ-004 — Accountant review

**Priority:** P0  
**Description:** Accountant validates submitted requests before they become eligible for batching.

**Acceptance criteria:**

- Filter by trader, status, amount, date, beneficiary, bank, and warning state.
- Open request detail without losing queue context.
- Mark valid request `eligible_for_batching`.
- Return for correction with structured reason.
- Cancel/void only with authorization and reason.
- Request review does not constitute manager approval.
- Actions are audited.

### FR-PAYREQ-005 — Payment request splitting

**Priority:** P0  
**Description:** A request may generate multiple payment attempts according to the selected versioned bank rules.

**Acceptance criteria:**

- Original request remains one business request.
- Each payment attempt has its own amount, status, bank row, result, and evidence.
- Sum of active attempts for a batch version must equal the request amount allocated to that batch.
- Manual amount divergence is not allowed as an untracked edit.
- Any required amount correction uses an audited request amendment and invalidates affected approval.
- System records the bank-rule version that caused each split.
- Trader sees an understandable aggregate and attempt-level result.

### FR-PAYREQ-006 — Present payment attempts as child records

**Priority:** P0  
**Description:** UI may show split attempts as child rows/cards but must never replace or duplicate the parent business request.

**Acceptance criteria:**

- Child records link to the original request.
- Parent status and totals are calculated from attempts.
- Reports can show request-level and attempt-level data.
- Child-row identifiers are not presented as separate trader requests.

### FR-PAYREQ-007 — Request amendment and cancellation

**Priority:** P0  
**Description:** Changes after submission use explicit amendment/correction rules.

**Acceptance criteria:**

- A trader edits only after the center returns the request for correction.
- An authorized administrator may correct a request only with a reason and permission.
- Changes affecting an approved batch invalidate that approval.
- Requests already executed by the bank are not cancelled; correction/reversal records are used.
- Previous versions remain auditable.

---

## 11. Payment Batch and Bank Excel Generation

### FR-BATCH-001 — Create and version a draft payment batch

**Priority:** P0  
**Description:** Accountant creates a draft batch from eligible requests for one bank profile and source account context.

**Acceptance criteria:**

- Accountant can select eligible requests/attempts.
- Ineligible, already-active-batched, blocked, or invalid items are rejected with reasons.
- Batch has unique ID and monotonically increasing version.
- Batch records bank profile, source account, transfer channel, creator, creation time, row count, and total IRR.
- Batch creation is idempotent against accidental repeated submission.
- Batch creation and item changes are audited.

### FR-BATCH-002 — Apply versioned bank rules

**Priority:** P0  
**Description:** The system applies the selected bank-profile/template version when creating attempts and export rows.

**Acceptance criteria:**

- Rules are not hard-coded.
- Required fields and template mappings are validated.
- Split rules may use amount, time, transfer channel, or configured limit.
- Each generated attempt stores rule/profile/template provenance.
- Changing a bank profile does not alter an existing batch snapshot silently.

### FR-BATCH-003 — Validate and preview exact approval content

**Priority:** P0  
**Description:** Accountant and manager must see the exact batch content before approval.

**Acceptance criteria:**

- Preview shows row count, total IRR, Toman equivalent, source account, bank, and transfer channel.
- Invalid rows are blocked from submission for approval.
- Warnings and exceptional rows are highlighted.
- Preview identifies changed rows since the previous submitted version.
- A content hash is calculated for the approval snapshot.
- A draft/non-submittable export, if provided, is visibly marked as draft.

### FR-BATCH-004 — Manager approval of immutable batch snapshot

**Priority:** P0  
**Description:** All Phase 1A outgoing batches require manager approval before final bank export.

**Acceptance criteria:**

- Manager can approve, reject, or request changes with an optional/required comment according to action.
- Approval stores batch ID, version, row count, total IRR, content hash, approver, and timestamp.
- Approval requires recent authentication or step-up confirmation.
- Manager is not required to approve every ordinary row separately.
- Any material change to rows, amounts, beneficiary, IBAN, source account, bank profile, or attempts invalidates approval.
- Invalidated batch returns to `ready_for_approval` or draft/change-request state.
- Approval actions are idempotent and audited.

### FR-BATCH-005 — Generate versioned final bank export

**Priority:** P0  
**Description:** System generates a final Excel file only from a valid approved snapshot.

**Acceptance criteria:**

- No final downloadable export is released before approval.
- Export uses the exact approved content hash/version.
- Required bank columns are present and validated.
- File includes internal reference where the bank format supports it, but matching does not depend on that reference.
- Export is stored immutably with template version and checksum.
- Regeneration creates a new export version; it does not overwrite history.
- Authorized users can download the final export.

### FR-BATCH-006 — Mark export/batch as sent to bank

**Priority:** P0  
**Description:** Accountant records manual submission of the approved export to the bank.

**Acceptance criteria:**

- Only an approved final export can be marked sent.
- User records sent date/time and optional external reference/note.
- Related attempts move to `sent_to_bank` and request aggregate state updates.
- Repeated submission of the same action does not duplicate events.
- Action is audited.

### FR-BATCH-007 — Batch correction, rejection, and cancellation

**Priority:** P0  
**Description:** Batch changes must preserve prior versions and approval history.

**Acceptance criteria:**

- Manager rejection/change request records a reason.
- Accountant creates a revised batch version rather than overwriting approved content.
- A sent batch cannot be cancelled as if nothing happened; unresolved attempts use result/retry/correction flows.
- Non-sent draft batches may be cancelled with authorization and reason.

---

## 12. Bank Result Bundle Management

### FR-BUNDLE-001 — Upload and preserve bank result bundle

**Priority:** P0  
**Description:** Accountant uploads one or more files received from a bank as a Bank Result Bundle.

**Supported Phase 1A types:**

- images;
- PDFs;
- Excel files where applicable;
- multiple mixed files per bundle.

**Acceptance criteria:**

- Original files are persisted before preview, crop, parsing, or normalization.
- Bundle can link to zero, one, or many batches.
- Bundle can be marked mixed/unknown.
- File hashes are stored and possible duplicate uploads are warned.
- Files are private and downloads are authorized.
- Upload is resumable or safely retryable where feasible.
- Upload event is audited.

### FR-BUNDLE-002 — Bundle metadata and provenance

**Priority:** P0  
**Fields:** bank profile, received date/time, source description, related batches if known, notes, mixed flag, uploader, original filenames, checksums, and processing state.

**Acceptance criteria:**

- Bundle may exist before a related batch is known.
- Later links do not overwrite original provenance.
- Metadata changes are audited.

### FR-BUNDLE-003 — In-application document preview

**Priority:** P0  
**Description:** Accountant can inspect supported images and PDFs inside the review workspace.

**Acceptance criteria:**

- Preview supports zoom, pan, page navigation, and rotation where applicable.
- Original file remains available to authorized users.
- Preview failure does not prevent secure download/manual processing.
- Preview does not expose the file through a public URL.

### FR-BUNDLE-004 — Manual result registration

**Priority:** P0  
**Description:** Accountant can register a result for a payment attempt from reviewed bank evidence.

**Acceptance criteria:**

- Accountant selects a payment attempt, not an ambiguous parent request.
- Result supports success, failure, pending/unknown, or needs-review states.
- Tracking/reference number, date/time, bank, amount, and note can be entered where available.
- Confirming the result requires explicit confirmation and current-version validation.
- Action is audited.

### FR-BUNDLE-005 — Unknown/unmatched records

**Priority:** P0  
**Description:** Unmatched content is retained for review rather than silently rejected.

**Acceptance criteria:**

- Unmatched items remain in a review queue.
- Authorized user can mark an item unrelated/archived only with reason.
- A later match or correction preserves history.

### FR-BUNDLE-006 — Future OCR processing entry point

**Priority:** P1  
**Description:** Bundle data model supports asynchronous provider-independent OCR/AI processing without changing the manual workflow.

---

## 13. Receipt Segment and Evidence Management

### FR-SEGMENT-001 — Create minimal manual receipt segment

**Priority:** P0  
**Description:** Accountant can create a rectangular segment from an image/PDF preview or upload an externally prepared evidence file.

**Acceptance criteria:**

- User can zoom/pan/rotate and select a rectangular area where supported.
- Segment stores original bundle/file/page reference and coordinates.
- Original document is never replaced.
- Segment can be saved without publishing.
- External evidence attachment remains available as fallback.
- Action is audited.

### FR-SEGMENT-002 — Evidence metadata and visibility

**Priority:** P0  
**Acceptance criteria:**

- Evidence stores origin, file key, checksum, creator, timestamp, visibility, and related attempt.
- Trader visibility is explicit and defaults to private until publication rules are satisfied.
- Full mixed bundle is never made trader-visible.
- Sensitive downloads may be audited.

### FR-SEGMENT-003 — Candidate and confirmed evidence links

**Priority:** P0  
**Description:** Suggested matches and confirmed evidence links are distinct concepts.

**Acceptance criteria:**

- A segment may have multiple candidate attempts.
- By default, one transaction segment has one active primary confirmed link to one payment attempt.
- A payment attempt may have supplementary evidence in addition to the primary link.
- Database/service rules prevent duplicate active primary links.
- Confirmation requires an authorized accountant action.

### FR-SEGMENT-004 — Replace or correct evidence link

**Priority:** P0  
**Description:** Incorrect evidence linkage is corrected without deletion.

**Acceptance criteria:**

- Previous link becomes `replaced`/inactive and remains in history.
- New link records reason, actor, timestamp, and source evidence.
- Published-result changes notify the owning trader in-app.
- If correction changes amount, beneficiary, IBAN, or financial outcome, required manager re-approval is triggered.

### FR-SEGMENT-005 — Automatic segmentation

**Priority:** P2  
**Description:** Future AI may propose segments, but generated segments are marked with provider/version/confidence and require human confirmation.

---

## 14. Payment Result Publishing to Trader

### FR-RESULT-001 — Safe trader result summary

**Priority:** P0  
**Description:** Trader sees an understandable, authoritative result only after accountant publication.

**Visible fields:** beneficiary, amount, payment status, payment date/time, bank, tracking number if available, masked/full IBAN according to permission/policy, and authorized evidence.

**Acceptance criteria:**

- Trader sees only their own records.
- Full mixed bundle and unrelated data are never exposed.
- Result indicates partial/failed/retried attempts clearly.
- Publication records publisher, time, and result version.

### FR-RESULT-002 — Download/share output

**Priority:** P0  
**Description:** Trader can download/share a clean generated result card/document and authorized evidence.

**Acceptance criteria:**

- Output contains no unrelated transactions.
- Output is generated from the published result version.
- Branding can be applied through configuration without changing financial content.
- Sensitive identifiers follow masking policy.
- Shared/downloaded file has a traceable generation record where practical.

### FR-RESULT-003 — Trader acknowledgement or dispute

**Priority:** P0  
**Acceptance criteria:**

- Trader can acknowledge a result.
- Trader can report an issue with a reason and optional attachment.
- Dispute creates an accountant review task.
- Dispute does not automatically reverse payment status.
- Resolution and re-publication are audited.

### FR-RESULT-004 — Publication correction notification

**Priority:** P0  
**Description:** If a published result is materially corrected, the owning trader receives an in-app notification and sees the current version plus correction history appropriate to their role.

---

## 15. Gold Sale Order Management

### FR-SALE-001 — Create gold sale order

**Priority:** P0  
**Description:** Trader or authorized center user creates a gold sale order representing the center selling gold to a trader.

**Required/configurable fields:**

- trader;
- gold product/type;
- weight and unit;
- purity/carat where applicable;
- pricing/expected amount information;
- order date/time;
- notes/attachments;
- settlement/dispatch type where enabled.

**Acceptance criteria:**

- Minimal Phase 1A configuration is supported without forcing unused fields.
- Weight and monetary units are explicit.
- Order creation is idempotent against accidental repeated submission.
- Order changes after pricing/payment evidence use controlled version/history.

### FR-SALE-002 — Price and expected-payment snapshot

**Priority:** P0  
**Description:** Authorized center user records the expected payment amount and the basis used for that order.

**Acceptance criteria:**

- Expected amount is canonical integer IRR.
- Original display/input unit and relevant gold values are retained.
- Published amount is visible to trader.
- Amount/price change records old/new value, actor, reason, and timestamp.
- Changing expected amount after payment evidence triggers review and does not silently preserve prior confirmation.

### FR-SALE-003 — Incoming-payment evidence submission

**Priority:** P0  
**Acceptance criteria:**

- Trader can enter structured payment details and upload one or more files.
- Unit, amount, date, source account/reference, and attachment quality are validated where possible.
- Original file is preserved and private.
- Poor/incorrect evidence can be returned for correction with reason.
- Submission is audited.

### FR-SALE-004 — Bank statement verification

**Priority:** P0  
**Description:** Accountant verifies incoming payment against bank statement rows manually in Phase 1A.

**Acceptance criteria:**

- Accountant searches by amount, date/time, reference, sender/account, and description.
- One incoming payment may be supported by one or more explicit bank-row links where partial/combined payment policy allows it.
- Matched sum and expected amount are compared.
- Underpayment/overpayment/ambiguous cases enter review rather than being silently confirmed.
- Confirmation and correction are audited.

### FR-SALE-005 — Payment confirmation and dispatch guard

**Priority:** P0  
**Acceptance criteria:**

- Dispatch/settlement cannot proceed until required incoming-payment confirmation and any configured manager approval are complete.
- Guard is enforced by backend workflow, not only UI.
- Authorized override, if business policy permits, requires explicit permission, reason, and audit.

### FR-SALE-006 — Dispatch, receipt, or settlement record

**Priority:** P0  
**Acceptance criteria:**

- Authorized user records date/time, type, weight, method, receiver/reference, notes, and optional evidence.
- Trader can acknowledge receipt where applicable.
- Physical dispatch and approved offset/settlement types are represented explicitly.
- Record cannot be silently deleted; correction/replacement preserves history.

### FR-SALE-007 — Sale cancellation, dispute, and closure

**Priority:** P0  
**Acceptance criteria:**

- Non-executed order may be cancelled only with authorization and reason.
- Executed payment/dispatch is not erased through cancellation.
- Dispute creates a review task.
- Order closes only when required payment, dispatch/settlement, and dispute conditions are resolved.

---

## 16. Bank Statement Management

### FR-BANKSTMT-001 — Upload and preserve bank statement

**Priority:** P0  
**Description:** Accountant uploads bank statement files used to verify incoming payments.

**Acceptance criteria:**

- Original file is stored securely with checksum and provenance.
- Bank profile and mapping version are selected.
- Parsing/normalization errors are visible without destroying the original.
- Parsed rows are stored or indexed for search.
- Possible duplicate statement upload is warned.
- Upload is audited.

### FR-BANKSTMT-002 — Versioned bank column mapping

**Priority:** P0  
**Description:** Each supported bank/file format uses a versioned mapping/profile.

**Acceptance criteria:**

- Technical admin can define or activate mappings with appropriate permission.
- Required fields and data types are validated.
- Mapping can support different date, amount, reference, direction, account, and description columns.
- Existing imported files retain the mapping version used.
- Mapping changes are audited and do not silently reinterpret historical rows.

### FR-BANKSTMT-003 — Search and review bank rows

**Priority:** P0  
**Search fields:** amount, date/time, reference, description, sender, source/destination account, direction, bank, and row status.

**Acceptance criteria:**

- Results are paginated and filterable.
- Matched/reserved rows are marked.
- Accountant can open the related sale/evidence context side-by-side.
- Manual link requires confirmation and is audited.

### FR-BANKSTMT-004 — Incoming payment match integrity

**Priority:** P0  
**Acceptance criteria:**

- One bank row cannot be actively confirmed against incompatible incoming payments without an authorized exception.
- Partial or combined incoming payments are represented explicitly, not hidden in notes.
- Match corrections preserve replaced links and history.

---

## 17. Matching and Review

### FR-MATCH-001 — Manual matching

**Priority:** P0  
**Description:** Authorized accountant manually confirms links between structured source evidence and target financial records.

**Supported targets:**

- bank statement row to incoming payment;
- receipt segment to payment attempt;
- manually entered bank result to payment attempt.

**Acceptance criteria:**

- Match requires explicit confirmation.
- Candidate and confirmed states are distinct.
- User can add a reason/note.
- Current-version and duplicate-link guards run before confirmation.
- Match and related status changes occur transactionally with audit.

### FR-MATCH-002 — Suggested matching

**Priority:** P1  
**Description:** Rules/AI may suggest candidates using amount, IBAN, name, bank, batch scope, date/time, and tracking reference.

**Acceptance criteria:**

- Suggestions include score, reasons, provider/rule version, and provenance.
- Suggestions never finalize automatically.
- Human accept/reject/ignore actions are stored.

### FR-MATCH-003 — Duplicate and ambiguity warnings

**Priority:** P1  
**Acceptance criteria:**

- Duplicate file hash/reference/amount/context warnings are shown.
- Ambiguous matches show multiple candidates.
- Warning does not auto-reject or auto-confirm.
- Human resolution is audited.

### FR-MATCH-004 — Manual review task

**Priority:** P0  
**Description:** The system creates actionable review items for unmatched, ambiguous, disputed, failed, partial, or corrected cases.

**Acceptance criteria:**

- Task has type, priority, owner/queue, related records, reason, status, and timestamps.
- Closing a task requires a resolution outcome.
- Task closure does not silently alter financial state.

---

## 18. Notifications and Communication

### FR-NOTIF-001 — In-app operational notifications

**Priority:** P0  
**Required events:** request returned for correction, request eligible, batch awaiting approval, batch rejected/change requested, result published, published result corrected, dispute created/resolved, unmatched/failed review assigned, trader status changed, and important security/session event where appropriate.

**Acceptance criteria:**

- Notification links to an authorized relevant screen.
- Unread/read state is stored.
- Notification does not expose sensitive data in a context where the recipient lacks access.
- Duplicate background retries do not create repeated notifications for the same event.
- Notification delivery failure does not change the underlying financial state.

### FR-NOTIF-002 — No SMS dependency

**Priority:** P0  
**Acceptance criteria:**

- All essential workflows and recovery procedures have a path that does not rely exclusively on SMS.
- SMS/email/push may be added later behind adapters and configuration.

### FR-COMM-001 — Structured communication, not internal chat

**Priority:** P0  
**Acceptance criteria:**

- Correction requests, rejection/change reasons, dispute notes, and resolution notes are structured record fields/events.
- Comments are permission-scoped and audited where sensitive.
- No general-purpose two-way messenger is implemented in Phase 1A.
- Phone/contact information may be displayed only to roles permitted to contact the user.

---

## 19. Reporting and Dashboards

### FR-REPORT-001 — Accountant operational dashboard

**Priority:** P0  
**Description:** Dashboard is queue-first and optimized for daily work, not a decorative analytics page.

**Required queues:** submitted requests, correction returns, eligible requests, draft/approval batches, sent batches, result bundles, unmatched evidence, failed/partial attempts, disputes, and incoming-payment reviews.

**Acceptance criteria:**

- Counts link to filtered work queues.
- Queues show aging/priority and blocking reason.
- Search/filter context is preserved when opening and returning from details.
- Bulk actions are limited to safe operations with validation and confirmation.

### FR-REPORT-002 — Manager decision dashboard

**Priority:** P0  
**Required information:** pending batch count, total IRR and Toman equivalent, row count, source bank/account, warnings/exceptions, changed versions, recent approvals/rejections, unresolved high-risk issues.

**Acceptance criteria:**

- Manager enters an approval detail screen before irreversible action.
- Summary values match the exact batch version.
- Approval cannot be performed from stale data.

### FR-REPORT-003 — Trader dashboard

**Priority:** P0  
**Required information:** drafts, submitted requests, action-needed items, pending/partial/paid/failed results, disputes, recent published evidence, and gold sale status.

**Acceptance criteria:**

- Trader sees only own data.
- Labels are Persian, clear, and action-oriented.
- Dashboard prioritizes next required action over raw totals.

### FR-REPORT-004 — Operational exports

**Priority:** P1  
**Acceptance criteria:**

- Exports respect permissions, active filters, masking rules, and tenant/trader isolation.
- Sensitive export requires explicit permission and confirmation.
- Export is logged with requester, filters, time, and checksum where appropriate.

### FR-REPORT-005 — Audit and record timeline

**Priority:** P0  
**Description:** Authorized users can view a chronological timeline of status changes, approvals, corrections, file actions, and publications for a record.

---

## 20. Audit and History

### FR-AUDIT-001 — Audit every sensitive action

**Priority:** P0  
**Description:** Financial, permission, configuration, file-access, approval, publication, and correction actions must be audited.

**Acceptance criteria:**

- Event includes actor, role, timestamp, action, target, record version, request/session metadata where allowed, previous/new values, and reason where relevant.
- Audit write is part of the same transaction or reliable outbox flow as the sensitive state change.
- Normal users cannot edit/delete audit events.
- Audit search is permission-controlled.

### FR-AUDIT-002 — Correction and version history

**Priority:** P0  
**Acceptance criteria:**

- Previous amount, beneficiary snapshot, IBAN, evidence link, batch version, approval, and publication version remain traceable.
- Reverted or replaced records require a reason.
- Financial corrections use explicit events/states rather than generic soft deletion.

### FR-AUDIT-003 — Audit retention and integrity

**Priority:** P0  
**Acceptance criteria:**

- Audit retention is at least as strict as the approved financial-record policy.
- Retention reduction does not immediately delete existing records.
- Legal hold/incident hold can prevent deletion.
- Integrity controls/checksums or append-only protections are used according to architecture.

---

## 21. Settings and Configuration

### FR-SETTINGS-001 — Versioned bank profile management

**Priority:** P0  
**Fields:** bank, active state, source accounts, transfer channels, Excel template/mapping, statement mapping, result hints, split/limit/time rules, reference format, required/optional fields, and effective version.

**Acceptance criteria:**

- Adding a supported bank/profile does not require changing core business logic.
- Publishing a profile version requires authorized review.
- Historical batches/files retain their original profile version.
- Changes are audited.

### FR-SETTINGS-002 — Feature flags

**Priority:** P0 for infrastructure; P1 for optional feature activation  
**Examples:** OCR, AI extraction, auto-segmentation, matching suggestions, external validation, SMS, advanced exports.

**Acceptance criteria:**

- Disabled optional features do not break manual flow.
- Backend and workers enforce flags, not only UI.
- Flag changes are audited.
- Minimal manual crop is part of Phase 1A and is not treated as AI auto-segmentation.

### FR-SETTINGS-003 — Retention governance

**Priority:** P0  
**Description:** Retention values are governed business/security settings, not ordinary technical preferences.

**Acceptance criteria:**

- Approved default is documented before production.
- No automatic financial-document deletion in Phase 1A.
- Reducing retention requires privileged approval and does not retroactively delete immediately.
- Future deletion jobs support dry-run/preview, legal hold, audit, and failure reporting.

### FR-SETTINGS-004 — Configuration separation

**Priority:** P0  
**Acceptance criteria:**

- Secrets are not stored as ordinary application settings.
- Environment-specific configuration is separate from business configuration.
- Sensitive settings are masked and access-controlled.

---

## 22. Amount, Localization, and UI/UX Requirements

### FR-LOCAL-001 — Canonical money storage

**Priority:** P0  
**Acceptance criteria:**

- Money is stored as integer IRR; floating point is prohibited.
- Original entered amount and unit are retained for audit.
- Conversion is deterministic and tested.

### FR-LOCAL-002 — Explicit amount input and confirmation

**Priority:** P0  
**Description:** Trader-facing forms default to a product-configured unit and allow only explicit `Toman` or `IRR` selection. Bank and settlement calculations remain IRR-authoritative.

**Acceptance criteria:**

- Unit is adjacent to every amount input.
- Thousands separators are applied while typing/displaying.
- Before submission, show canonical IRR, Toman equivalent, and amount in words where useful.
- Manager approval shows both IRR and Toman.
- No silent unit inference or unformatted raw amount in financial action screens.

### FR-LOCAL-003 — Persian/RTL and mixed-direction identifiers

**Priority:** P0  
**Acceptance criteria:**

- User-facing UI is Persian/RTL.
- IBAN, tracking numbers, hashes, and technical IDs render LTR.
- Jalali date is used for display where appropriate.
- Backend stores timezone-aware canonical timestamps.
- Persian/Arabic digit variants and text normalization are handled in search/input validation.

### FR-UX-001 — Product visual direction

**Priority:** P0  
**Description:** The interface is modern, premium, trustworthy, and FinTech-oriented, appropriate for the gold trade without decorative excess.

**Acceptance criteria:**

- Restrained gold accent; semantic colors retain clear operational meaning.
- High contrast and strong numeric hierarchy.
- No messenger imitation or spreadsheet-like screen as the default interaction model.
- Irreversible actions are visually distinct from navigation and ordinary edits.

### FR-UX-002 — Responsive role-specific applications

**Priority:** P0  
**Acceptance criteria:**

- Trader experience is mobile-first and installable as PWA.
- Admin/accountant/manager experience is web-based, desktop-first, and responsive.
- Critical manager review remains usable on tablet/mobile but does not hide required details.

### FR-UX-003 — Accountant review workspace

**Priority:** P0  
**Acceptance criteria:**

- Document preview and payment/request context can be viewed side-by-side on desktop.
- Work queues support filters, clear status, warnings, and next action.
- Keyboard-efficient navigation/actions are supported where practical.
- Dense information uses hierarchy/progressive disclosure rather than excessive empty space.

### FR-UX-004 — Safe action and stale-data behavior

**Priority:** P0  
**Acceptance criteria:**

- Sensitive confirmation shows exact amount, beneficiary/batch, bank, and consequences.
- Double-click/retry cannot duplicate the action.
- Stale version conflict is explained; the user must refresh/review before retry.
- Success/failure states are explicit and do not rely only on color.

---

## 23. File Handling Requirements

### FR-FILE-001 — Secure private upload

**Priority:** P0  
**Acceptance criteria:**

- Validate category, extension, MIME signature, size, and filename.
- Apply malware scanning/quarantine according to production security decision.
- Store outside public static paths.
- Downloads require current authorization.
- Failed/incomplete uploads do not create misleading completed records.

### FR-FILE-002 — File metadata and integrity

**Priority:** P0  
**Metadata:** original filename, storage key, MIME, size, uploader, timestamps, category, related entity, visibility, checksum, scan status, and original/derived relationship.

**Acceptance criteria:**

- Duplicate checksum may warn but does not automatically discard a legitimate file.
- Storage key is not a user-controlled public path.
- Metadata changes are audited.

### FR-FILE-003 — Original preservation and immutable derived history

**Priority:** P0  
**Acceptance criteria:**

- Original upload is preserved before normalization/crop/OCR.
- Derived files reference the original and processing version.
- Reprocessing creates new derived versions.
- Normal user operations cannot physically delete financial evidence.

### FR-FILE-004 — Authorized preview and download

**Priority:** P0  
**Acceptance criteria:**

- Preview/download uses backend authorization or short-lived signed access.
- Trader cannot retrieve a file by guessing/changing an identifier.
- Full bundle access is restricted to authorized internal roles.
- Sensitive download logging is supported.

---

## 24. AI/OCR Product Requirements

### FR-AI-001 — AI is optional

**Priority:** P1  
**Description:** System can call AI/OCR providers when enabled, but core workflows do not require it.

**Acceptance criteria:**

- AI feature can be disabled globally.
- Manual workflow still works.
- AI failures create review tasks, not system failure.

### FR-AI-002 — Standard AI output contract

**Priority:** P1  
**Description:** AI/OCR output must follow a provider-independent schema.

**Acceptance criteria:**

- Backend receives normalized JSON output.
- Provider-specific details are isolated.
- Result includes confidence and reasons.
- Human confirmation is required.

### FR-AI-003 — AI job queue

**Priority:** P1  
**Description:** AI/OCR processing must run asynchronously.

**Acceptance criteria:**

- UI does not wait synchronously for long AI jobs.
- Job status is visible.
- Failed jobs can be retried.
- Errors are logged.

### FR-AI-004 — Learning from corrections

**Priority:** P2  
**Description:** Human corrections should be stored for future improvement.

**Acceptance criteria:**

- Corrected value is stored separately from AI value.
- Correction reason/user/time is stored.
- Future AI tuning can use correction history.

---

## 25. Edge Cases and Required Behavior

### EC-001 — Mixed bank result bundle
**Behavior:** Preserve original bundle, allow links to multiple batches, and keep unmatched segments in review.

### EC-002 — Overlapping/rotated/low-quality documents
**Behavior:** Allow preview, rotate, manual crop, external attachment fallback, and needs-review status; never force OCR.

### EC-003 — AI/OCR unavailable
**Behavior:** Manual operation continues without blocking core workflow.

### EC-004 — Request split into several attempts
**Behavior:** Track attempts separately; aggregate parent totals/status exactly.

### EC-005 — Some attempts succeed and others fail
**Behavior:** Request becomes partial; failed amount is retried through new traceable attempts.

### EC-006 — Wrong evidence link
**Behavior:** Replace link through correction workflow; preserve old link; notify trader if published content changes.

### EC-007 — Trader disputes a published result
**Behavior:** Create review task; do not automatically reverse bank result; publish resolution as a new result version.

### EC-008 — Duplicate request/file/reference
**Behavior:** Warn and require review; idempotency prevents duplicate system action; do not auto-reject a legitimate case.

### EC-009 — Repeated identical amount/name
**Behavior:** Matching uses broader context; ambiguous candidates require accountant selection.

### EC-010 — Bank format changes
**Behavior:** Create a new mapping/profile version; do not reinterpret historical imports silently.

### EC-011 — Wrong IBAN before batching
**Behavior:** Return request for correction; existing historical beneficiary/request version remains traceable.

### EC-012 — Manager rejects or requests batch changes
**Behavior:** Preserve submitted version and reason; accountant creates revised version; no final export is released.

### EC-013 — Batch changes after approval
**Behavior:** Approval becomes invalid immediately; export/download is blocked until re-approval.

### EC-014 — Concurrent accountant edits
**Behavior:** Optimistic lock/version check prevents lost update and explains conflict.

### EC-015 — Retry/double-click on sensitive action
**Behavior:** Idempotency returns the existing result or safe conflict; no duplicate batch, export, confirmation, or publication.

### EC-016 — Crash during batch/export/result confirmation
**Behavior:** Transaction/outbox design prevents partial financial state; recovery is safe and auditable.

### EC-017 — File storage unavailable
**Behavior:** Do not confirm upload/result publication; show recoverable error; alert operations.

### EC-018 — Approved batch export differs from snapshot
**Behavior:** Validation fails; file is quarantined/not downloadable; security/audit event is created.

### EC-019 — Retention policy reduced
**Behavior:** No immediate deletion; require approved policy, legal-hold check, dry run, and separate deletion execution.

---

## 26. Non-Functional Product Requirements

### NFR-001 — Reliability and graceful degradation

- Core workflows work without AI, SMS, or bank API.
- Financial state transitions are transactional.
- Worker failure does not silently finalize or lose work.

### NFR-002 — Performance targets for Phase 1A pilot

Under an agreed pilot dataset and healthy production server:

- normal list/dashboard load: under 3 seconds;
- normal API CRUD p95: under 500 ms where practical;
- upload acknowledgement: under 5 seconds;
- moderate bank export generation: under 30 seconds or asynchronous with visible status;
- all large lists paginated and filterable.

Final load-test volume must be set after the business provides expected daily volume and file sizes.

### NFR-003 — Security

- Backend authorization for every sensitive action/file.
- Trader isolation is mandatory.
- Secrets never exposed to frontend or source control.
- Rate limiting and failed-login controls.
- Recent-auth/step-up control for manager approval.
- Production HTTPS and restricted administrative access.

### NFR-004 — Idempotency

Critical operations require idempotency protection:

- request submission;
- batch creation/submission;
- manager approval;
- final export generation;
- sent-to-bank action;
- payment-result confirmation;
- result publication.

### NFR-005 — Concurrency control

Use record versions/optimistic locking for requests, beneficiaries, batches, attempts, results, and configuration. Stale writes must fail safely.

### NFR-006 — Transactional integrity

Financial state change, related record creation, and audit/outbox event must commit atomically or recoverably.

### NFR-007 — Auditability

System answers who did what, when, to which version, and why. Corrections never erase prior state.

### NFR-008 — Maintainability and compatibility

- Modular boundaries and typed contracts.
- Database migrations and rollback considerations.
- Optional providers behind adapters/feature flags.
- Bank profiles/templates versioned.

### NFR-009 — Localization and accessibility

- Persian/RTL production UI.
- LTR handling for financial identifiers.
- Clear keyboard focus, labels, validation, and non-color-only status cues.
- Touch targets appropriate for mobile trader use.

### NFR-010 — Observability

Monitor API, database, Redis/queue, workers, storage, uploads, result processing, failed logins, backups, disk usage, and scheduled jobs. Health endpoints must not expose secrets.

### NFR-011 — Backup and recovery

Before production:

- automated database backup;
- automated private-file backup;
- encrypted/off-server copy according to hosting policy;
- monitored backup success/failure;
- documented restore procedure;
- at least one successful restore test;
- approved RPO and RTO.

### NFR-012 — Deployment and release safety

- Local, staging, and production environments.
- CI tests migration on clean database and builds all images.
- Production images are version-pinned, not mutable `latest` artifacts.
- Deployment, smoke test, rollback, and maintenance procedures exist.

### NFR-013 — Data retention and privacy

- Retention follows approved business/legal policy.
- Sensitive identifiers are minimized/masked by role.
- Production samples are not committed to source control.
- Test fixtures use anonymized or synthetic data.

---

## 27. Phase Definitions

### Phase 1A — Operational Manual Core

**Goal:** A secure, auditable, production-usable workflow without AI dependency.

**Must include:** authentication/RBAC, trader and beneficiary management, Trader PWA, admin/accountant/manager web application, outgoing requests, gold sale basic flow, bank statements, bank profiles, payment attempts, batch snapshot and approval, versioned export, bank result bundles, document preview, minimal manual crop, manual result confirmation, result publication/disputes, audit, private files, dashboards, CI, staging, backup/restore, monitoring, deployment, and rollback.

**Must not depend on:** OCR, AI matching, auto-segmentation, bank API, SMS, advanced analytics, multi-company, or billing.

### Phase 1B — Assisted Processing

**Goal:** Reduce manual effort while preserving human authority.

**Candidates:** OCR infrastructure, extraction suggestions, stronger crop/review tools, match candidates, confidence/provenance, duplicate assistance, and AI cost/reliability monitoring.

### Phase 2 — Advanced Intelligence and Risk Control

**Candidates:** auto-segmentation, mixed-bundle automation, advanced duplicate detection, weighted matching, anomaly/risk signals, approved external beneficiary validation, correction-based evaluation, and advanced reports.

### Phase 3 — Integrations and Operational Scale

**Candidates:** bank API/open-banking where feasible, accounting integration, service scaling, mature monitoring/SLA, and higher availability. Manual upload remains available.

### Phase 4 — Productization and Expansion

**Optional candidates:** multi-company deployment, tenant isolation, subscription/billing, product analytics, support tooling, and reusable customer onboarding. Do not implement early.

---

## 28. Acceptance Criteria for Phase 1A

Phase 1A is acceptable only when all end-to-end and production gates pass.

### AC-001 — Trader and beneficiary onboarding

- Authorized user approves trader.
- Trader logs in and creates/reuses beneficiary.
- Pending/suspended trader cannot submit.
- Trader cannot access another trader's beneficiary or request.

### AC-002 — Structured outgoing payment submission

- Trader enters amount with explicit unit.
- System shows canonical conversion and total.
- Duplicate submission does not create duplicate requests.
- Accountant returns an invalid request with reason or marks it eligible.

### AC-003 — Batch preparation and immutable approval

- Accountant creates attempts using a versioned bank profile.
- Invalid rows are blocked.
- Manager sees exact version, total, row count, bank/source account, and warnings.
- Manager approves the snapshot.
- Changing any material row invalidates approval and blocks export.

### AC-004 — Versioned bank export

- Final Excel matches approved snapshot/hash.
- Export is stored with version/template/checksum.
- Only authorized user downloads it.
- Sent-to-bank action is idempotent and audited.

### AC-005 — Bank result review and manual crop

- Accountant uploads mixed image/PDF bundle.
- Original is preserved.
- Accountant previews and creates a rectangular segment or uploads external evidence.
- Accountant links it to one payment attempt and confirms result.
- Duplicate active primary link is blocked.

### AC-006 — Trader-safe result publication

- Trader sees only own published summary/evidence.
- Full mixed bundle is inaccessible.
- Trader downloads/shares clean result and can acknowledge/dispute.

### AC-007 — Partial payment and retry

- Request splits into attempts.
- Mixed success/failure produces correct aggregate state.
- Retry creates traceable new attempt and does not erase prior result.

### AC-008 — Gold sale and incoming-payment verification

- Sale order and expected amount are recorded.
- Trader submits evidence.
- Accountant links bank statement row and confirms incoming payment.
- Dispatch/settlement guard and status work.

### AC-009 — Correction and concurrency

- Wrong evidence link is replaced with history.
- Published material correction notifies trader.
- Concurrent stale edit is blocked without data loss.

### AC-010 — Security and audit

- RBAC and trader isolation pass automated tests.
- Unauthorized file download fails.
- Critical actions produce complete audit events.
- Technical admin cannot bypass manager approval by default.

### AC-011 — Production readiness

- CI gates pass.
- Staging smoke/UAT passes.
- Database and file backups run.
- Restore test succeeds.
- Monitoring, health checks, logs, deployment, rollback, and incident ownership are documented.
- No unresolved critical or high security defect remains.

---

## 29. Implementation Notes for Coding Agents

Coding agents must implement one approved milestone at a time and use the specialized documents as sources of detail without overriding this PRD or Blueprint 1.1.

### Mandatory rules

1. Preserve required business outcomes; do not imitate legacy messaging/spreadsheet execution.
2. Do not make AI/OCR required in Phase 1A.
3. Do not auto-finalize financial decisions.
4. Manager approval is for the exact batch snapshot.
5. Do not generate/release final bank export before valid approval.
6. Do not collapse request, attempt, batch, export, bundle, and segment concepts.
7. Do not store money as float or infer amount unit.
8. Do not expose full mixed bank documents to traders.
9. Do not use frontend-only authorization.
10. Do not erase financial history or overwrite approved/exported versions.
11. Add idempotency, version checks, transactions, and audit to critical actions.
12. Preserve original files before derived processing.
13. Keep manual fallback when optional services fail.
14. Add tests with every critical workflow.

### Preferred Phase 1A implementation order

1. Repository, environments, CI, database migration, private storage skeleton.
2. Authentication, sessions, RBAC, trader isolation, audit foundation.
3. Trader and beneficiary management.
4. Outgoing payment request workflow and amount handling.
5. Bank profiles/source accounts and payment attempts.
6. Batch versioning, validation, manager approval, final export.
7. Bank statements and gold-sale incoming-payment verification.
8. Bank result bundle preview and minimal manual crop.
9. Manual result confirmation, evidence links, correction flow.
10. Trader publication/share/dispute.
11. Dashboards, notifications, reports.
12. Security, concurrency, idempotency, E2E/UAT, backup/restore, release hardening.

---

## 30. Decisions Required Before Production Commitment

These do not change the approved product direction but must be resolved and recorded before production launch or the affected milestone:

1. Approved legal/accounting retention duration and audit retention.
2. Production hosting provider and data-location constraints.
3. Production storage adapter and off-server backup destination.
4. RPO and RTO.
5. Exact initial bank profiles, source accounts, templates, and supported result formats.
6. Maximum expected daily request count, batch rows, bundle size, and file size.
7. Final branding/logo and share-card branding policy.
8. Trader-visible IBAN masking policy.
9. Exact supported gold dispatch/offset settlement types in Phase 1A.
10. Authentication ADR: session/cookie/token implementation and manager step-up method.
11. Production malware scanning method.
12. Named owners for alerts, restore drills, SSH access, and production approval.

Resolved product decisions:

- All Phase 1A outgoing batches require batch-level manager approval.
- Minimal manual crop is Phase 1A; automatic segmentation is not.
- Administrator impersonation is not included in Phase 1A.
- Bulk Excel import is not the primary Phase 1A trader submission path.
- Published material corrections notify the owning trader in-app.
- SaaS/multi-company is Phase 4, not Phase 3.

---

## 31. Glossary

### Trader
Known goldsmith/business customer using the Trader PWA/web application.

### Center
The company operating the settlement platform and admin applications.

### Beneficiary
Reusable sensitive recipient data introduced by a trader. Not a system user; does not own the payment amount.

### Payment Request
Business request by a trader for the center to pay a beneficiary.

### Payment Attempt
Concrete bank transfer row/attempt generated from a request, including split/retry attempts.

### Payment Batch
Versioned group of attempts prepared for one approval/export context.

### Batch Snapshot
Immutable approval content including batch version, rows, totals, bank/source account, and content hash.

### Bank Excel Export
Versioned file generated from an approved batch snapshot for manual bank submission.

### Bank Statement File
Bank-provided account movement file used mainly for incoming-payment verification.

### Bank Result Bundle
One or more original files returned by a bank after outgoing-payment processing; may be mixed.

### Receipt Segment
Specific transaction evidence derived from or attached to a bank result bundle.

### Matching Candidate
Unconfirmed possible link between evidence/data and a target record.

### Confirmed Evidence Link
Human-confirmed primary relation between transaction evidence and one payment attempt.

### Manual Review Task
Actionable work item for unmatched, ambiguous, partial, failed, disputed, or corrected cases.

### Incoming Payment
Payment from trader to center, usually related to gold purchase.

### Outgoing Payment
Payment from center to a beneficiary on behalf of a trader.

---

## 32. Final Product Baseline

Phase 1A is a standardized, secure, auditable, production-ready gold trade operations and settlement platform.

It preserves required business flows and authority while improving their execution through structured records, reusable beneficiaries, explicit units, work queues, immutable batch approval, versioned bank files, private evidence, correction history, and recoverable operations.

AI/OCR and integrations are optional enhancements. Product success in Phase 1A is measured by data integrity, usability, financial control, traceability, security, and operational reliability—not by the amount of automation.
