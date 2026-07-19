# 12 — Security, RBAC, Audit, and Operational Control Specification

## Gold Trade Settlement Platform

**Document type:** Security, identity, authorization, audit, and operational-control specification  
**Version:** `1.1`  
**Status:** Authoritative implementation baseline  
**Language:** English  
**Phase coverage:** Phase 1A mandatory controls, with forward-compatible design for later phases  
**Primary audience:** Product owner, security reviewer, technical lead, backend engineer, frontend engineer, DevOps engineer, QA engineer, and coding agents  

**Authoritative dependencies:**

- `00_Master_Implementation_Blueprint.md`
- `01_Product_Requirements_PRD.md`
- `02_Domain_Model_and_Business_Rules.md`
- `03_System_Architecture.md`
- `04_Database_Schema.md`
- `05_API_Specification.md`
- `06_Workflows_and_State_Machines.md`
- `07_UI_UX_Specification.md`
- `08_Bank_File_and_Result_Processing.md`
- `09_OCR_AI_Module_Specification.md`
- `10_Backend_Implementation_Guide.md`
- `11_Frontend_Implementation_Guide.md`

---

## Document Change Log

| Version | Summary |
|---|---|
| `1.0` | Initial security, RBAC, and audit draft. |
| `1.1` | Aligned security with the single-tenant modular monolith, separate trader/admin applications, exact immutable batch-version approval, recent authentication, mandatory idempotency, optimistic concurrency, Unit of Work, transactional audit/outbox, Phase 1A manual crop, evidence/publication separation, governed retention/legal hold, hardened file lifecycle, production incident controls, and stricter separation of duties. |

---

# 1. Purpose and Authority

This document defines the mandatory security model for the Gold Trade Settlement Platform.

The platform processes high-value outgoing payments, incoming-payment verification, gold-sale settlement, beneficiary banking data, bank exports, bank result bundles, payment evidence, trader-visible publications, and operational audit records. Security is therefore part of the business workflow itself, not a later infrastructure enhancement.

This document is authoritative for:

- identity and authentication requirements;
- session security;
- role and permission design;
- trader ownership isolation;
- separation of duties;
- financial-command authorization;
- manager approval assurance;
- file and evidence authorization;
- audit and security-event integrity;
- retention and legal-hold governance;
- security monitoring and incident response;
- DevOps security controls;
- security acceptance criteria and test coverage.

When a technical implementation conflicts with a control in this document, the implementation must be corrected. Controls must not be weakened merely to simplify code or reproduce a previous manual workflow.

The guiding security principle is:

> Preserve the required business authority, evidence, and accountability while replacing insecure manual execution patterns with explicit, versioned, permission-checked, and auditable commands.

---

# 2. Security Position

## 2.1 Manual-first does not mean control-light

Phase 1A is the manual operational core. It must work without:

- required OCR or AI;
- automatic segmentation;
- direct bank API integration;
- external messaging platforms;
- SaaS multi-company architecture;
- autonomous financial decisions.

Phase 1A still requires:

- secure authentication;
- backend authorization;
- trader isolation;
- exact manager approval of every outgoing batch version;
- idempotent financial commands;
- concurrency protection;
- private file storage;
- manual rectangular crop inside the authorized admin workspace;
- immutable evidence/publication history;
- complete auditability;
- backup and recovery readiness.

## 2.2 Human authority is mandatory

Automation may parse, render, classify, rank, suggest, or create review work. It may not exercise human financial authority.

AI, OCR, workers, and matching engines may:

- normalize files;
- render PDF pages;
- create derived previews or crops;
- extract candidate fields;
- propose matching candidates;
- identify anomalies or duplicate indicators;
- create manual-review tasks.

They must never:

- approve a payment batch version;
- mark an attempt paid or failed as a final business decision;
- create an active confirmed evidence link without an authorized human command;
- publish a result to a trader;
- mark a final bank export as sent;
- authorize gold dispatch;
- shorten retention or delete governed records.

## 2.3 Deny by default

An authenticated user has no access unless access is granted by all applicable controls:

1. authentication domain;
2. active account/session state;
3. explicit permission;
4. object ownership or business scope;
5. command/state guard;
6. concurrency and idempotency guard;
7. recent-auth or dual-control guard where required;
8. file/publication visibility guard where applicable.

## 2.4 Backend is the security authority

Frontend permission gates improve usability but are not authorization.

Every sensitive backend command must derive the actor and scope from trusted authentication context. It must not trust actor IDs, trader IDs, roles, approval state, totals, or file visibility supplied by the browser.

## 2.5 Traceability over destructive mutation

Normal application flows do not physically delete confirmed financial data.

Use:

- immutable revisions;
- immutable batch versions;
- append-only approvals;
- supersession;
- cancellation with reason;
- replacement links;
- governed correction commands;
- archival;
- retention workflows after legal-hold checks.

A generic `delete()` or unrestricted soft-delete flag is not an acceptable financial-domain control.

## 2.6 Single-tenant Phase 1A

Phase 1A is a single-center, single-tenant deployment.

Do not introduce incomplete tenant identifiers or pretend that partial multi-tenancy creates isolation. Trader isolation is ownership isolation within the single center. Multi-company/SaaS security is a Phase 4 concern and requires a separate threat model and authorization design.

---

# 3. Security Objectives

The security design must provide the following outcomes.

## 3.1 Confidentiality

- Traders see only their own business records and active/superseded publications authorized for them.
- Full bank statements, mixed result bundles, internal notes, approval context, and audit details are not trader-visible.
- Technical administrators do not receive unrestricted financial-data access by default.
- Storage keys, credentials, secrets, raw provider payloads, and backup locations are not exposed to clients.

## 3.2 Integrity

- A manager approves the exact immutable batch version and content hash.
- An approved export can be generated only from that version.
- A stale browser tab cannot overwrite a newer financial state.
- Duplicate requests and retries cannot create duplicate approvals, exports, confirmations, or publications.
- Audit records are committed with the business command and cannot be edited through application APIs.

## 3.3 Availability and recoverability

- Redis, AI, notifications, or a worker outage must not destroy committed business state.
- Manual operation remains available when AI is disabled.
- Database and file backups are protected and restore-tested.
- Failure of an asynchronous notification does not roll back an already committed financial decision.

## 3.4 Accountability

For every sensitive decision, the system must answer:

- who acted;
- under which identity, role, and session;
- what command was performed;
- which version/hash was reviewed;
- what changed;
- why it changed;
- which evidence supported it;
- whether recent authentication or secondary approval was used;
- which request, idempotency key hash, and correlation ID were involved;
- when the action occurred.

---

# 4. Threat Model and Abuse Cases

The implementation and test strategy must address at least the following threats.

## 4.1 Identity and session threats

- password guessing and credential stuffing;
- user enumeration through login/recovery errors;
- stolen or replayed sessions;
- long-lived bearer tokens in browser storage;
- session fixation;
- missing logout/revocation;
- role or account-status changes not invalidating active sessions;
- CSRF when cookie authentication is used;
- cross-use of trader credentials on admin routes;
- use of stale manager authentication for a high-risk approval.

## 4.2 Authorization threats

- insecure direct object reference by guessing UUIDs;
- accepting `trader_id` from a trader payload;
- technical admin gaining implicit financial approval authority;
- read-only users triggering hidden side effects;
- workers bypassing human authority;
- confused-deputy actions across trader/admin domains;
- permission escalation through role-management endpoints;
- broad `super_admin` use without oversight.

## 4.3 Financial-integrity threats

- approving a mutable batch;
- export generated from rows different from those approved;
- mark-as-sent applied to the wrong file;
- duplicate command caused by double-click or timeout retry;
- stale updates after another accountant changed a record;
- attempt confirmed before it was sent to the bank;
- paid totals exceeding the request amount;
- evidence linked to the wrong attempt;
- candidate matching treated as confirmed evidence;
- publication changed without preserving the previous version;
- published paid result corrected without higher assurance.

## 4.4 File and document threats

- public or predictable storage paths;
- path traversal through filenames;
- executable or polyglot uploads;
- malware in Office/PDF files;
- MIME/extension mismatch;
- oversized files or decompression bombs;
- formula injection in CSV/Excel output or preview;
- mixed bank bundles exposed to traders;
- signed URLs with excessive lifetime;
- orphaned storage objects;
- database file metadata pointing to missing or altered objects;
- unsafe browser caching of sensitive files.

## 4.5 Application threats

- XSS through names, notes, filenames, or extracted OCR text;
- SQL injection through unsafe query construction;
- mass assignment through generic update endpoints;
- excessive data returned in API responses;
- sensitive values in logs, analytics, exception traces, or browser console;
- missing rate limits on authentication, upload, search, or export operations;
- unsafe dependency or container images.

## 4.6 Insider and operational threats

- unauthorized mass download of bank files;
- accountant approving their own prepared batch through a second role;
- role changes without oversight;
- retention shortened to remove evidence;
- backup copied to an insecure location;
- production data used in test environments;
- direct database changes bypassing audit;
- emergency access used without review.

## 4.7 AI/provider threats

- sensitive full bundles sent externally without approval;
- provider retention or training on financial documents;
- prompt injection text inside a bank document;
- AI output treated as business truth;
- raw provider payloads copied to ordinary logs;
- model or prompt changes deployed without evaluation.

---

# 5. Identity Domains

## 5.1 Separate trader and internal identity domains

The platform has two security domains:

1. **Trader domain** — external users of the Trader PWA.
2. **Internal domain** — accountants, managers, warehouse users, technical administrators, auditors, and business administrators using the Admin Web App.

The domains may share authentication infrastructure, but must maintain separate:

- login routes and application audiences;
- account records or explicit identity types;
- session audiences;
- permission evaluation;
- route middleware;
- response DTOs;
- navigation and frontend bundles;
- rate-limit policies where appropriate.

A trader session must not be accepted as an internal session. An internal session must not be treated as ownership of a trader account unless an explicitly authorized support workflow exists.

## 5.2 Identity records

The preferred Phase 1A data model has separate `trader_users` and `admin_users` records, with shared authentication/session abstractions where useful.

Identity records must include or support:

- immutable identity ID;
- login identifier and normalized form;
- password hash or approved credential reference;
- account status;
- authentication version/security stamp;
- password-changed timestamp;
- failed-login/lock metadata;
- last successful login metadata;
- created/deactivated timestamps;
- internal role assignments for admin users;
- owning trader relationship for trader users.

## 5.3 Beneficiaries are not identities

Beneficiaries/retail sellers do not receive accounts, sessions, roles, direct notifications, or file access in Phase 1A.

A beneficiary record contains business and bank details. It must not be treated as an authenticated principal.

## 5.4 System and worker actors

Workers and automated processes use a controlled `system` actor identity for audit attribution. A worker is not a human user and must not inherit a human role.

System actors may execute only pre-authorized technical tasks such as:

- preview/render generation;
- crop rendering;
- import parsing;
- export file rendering after an authorized command;
- outbox delivery;
- notification delivery;
- maintenance reconciliation;
- AI/OCR processing under feature flags.

They do not exercise approval or confirmation authority.

---

# 6. Authentication and Session Security

## 6.1 Authentication ADR boundary

The exact session transport is finalized by `ADR-001`.

The preferred browser baseline is:

- server-side or revocable session records;
- secure, HTTP-only cookies;
- `Secure` and appropriate `SameSite` attributes;
- CSRF protection for unsafe methods;
- no long-lived credential in `localStorage`.

A short-lived bearer access token with server-side session/revocation records is acceptable only if approved by ADR and implemented without long-lived browser storage.

Domain services must remain transport-neutral. They consume an authenticated `ActorContext`, not JWT-specific claims.

## 6.2 Password storage

- Prefer Argon2id with reviewed parameters; bcrypt is acceptable only when explicitly selected and configured safely.
- Passwords and recovery secrets are never stored or logged in plaintext.
- Password hashes are never returned by APIs.
- Password comparison is performed through an approved library.
- A password change revokes or invalidates existing sessions according to policy.
- Seeded development credentials must not exist in production images or migrations.

## 6.3 Password policy

The production policy must define:

- minimum length;
- rejection of commonly compromised or trivial passwords where feasible;
- maximum length to prevent denial-of-service behavior;
- password reset and temporary credential handling;
- administrative reset requirements;
- whether forced rotation is required after an administrative reset.

Do not require arbitrary frequent rotation unless business/security policy explicitly requires it. Rotation events must never encourage predictable passwords.

## 6.4 Login response safety

Login and recovery endpoints return generic errors that do not reveal whether an account exists.

Example:

```json
{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "The login information is not valid."
  }
}
```

## 6.5 Account states

Recommended identity/account states:

```text
pending_approval
active
suspended
locked
recovery_required
deactivated
```

Rules:

- `pending_approval` trader users may access only the approved pending-account experience.
- `active` is required for normal commands.
- `suspended` blocks new financial actions and may restrict sessions while preserving authorized historical visibility.
- `locked` blocks authentication temporarily or until reviewed.
- `recovery_required` allows only the approved credential-recovery flow.
- `deactivated` prevents login and new sessions.

Account status is revalidated on protected requests; it must not rely solely on a stale token claim.

## 6.6 Session records

Each active session should have a server-side record containing at least:

- session ID;
- actor domain and actor ID;
- authentication time;
- issued and expiry timestamps;
- idle/last-seen timestamp if idle expiry is used;
- revocation timestamp and reason;
- authentication assurance level;
- device/user-agent summary where allowed;
- IP metadata where allowed;
- credential/security-stamp version;
- optional parent/replaced session reference.

## 6.7 Session lifetime

The final idle and absolute timeouts are ADR decisions. Requirements are:

- admin sessions should use a stricter policy than ordinary trader sessions where operationally reasonable;
- a session cannot outlive account deactivation or security-stamp invalidation;
- session expiry is enforced server-side;
- sensitive commands do not rely solely on a long-lived base session;
- expired sessions produce a clear `401 UNAUTHENTICATED` response.

## 6.8 Session revocation triggers

Sessions must be revocable on:

- logout;
- password change or reset;
- account suspension/deactivation;
- security incident;
- administrator-initiated revocation;
- high-risk role change according to policy;
- credential compromise;
- authentication version/security-stamp change.

## 6.9 Failed-login and rate-limit controls

At minimum:

- rate-limit by normalized account identifier and network source using privacy-conscious keys;
- track failed attempts in a durable auth/security-event record;
- add backoff and temporary lock behavior;
- avoid exposing exact thresholds to the client;
- alert on abnormal patterns;
- ensure Redis loss does not permanently erase account/security state that must be durable.

## 6.10 CSRF

When cookie authentication is selected:

- unsafe methods require CSRF protection;
- CSRF tokens are bound to the session and validated server-side;
- CORS is restricted to approved Trader PWA and Admin Web origins;
- state-changing GET endpoints are prohibited;
- signed download URLs are not substitutes for CSRF protection on commands.

## 6.11 MFA and stronger admin authentication

MFA may be introduced after Phase 1A, but production approval must explicitly decide whether internal administrators and managers require MFA at launch.

Even when full MFA is deferred, manager approval requires recent authentication as described below.

---

# 7. Recent Authentication and Step-Up Assurance

## 7.1 Purpose

A valid base session is insufficient assurance for selected high-impact actions. The user must prove recent possession of an approved authentication factor.

## 7.2 Required Phase 1A uses

Recent authentication is mandatory for:

- manager approval of a payment batch version;
- configured cancellation or invalidation of an approved batch/version;
- role/permission changes that grant high-risk financial authority;
- break-glass activation;
- correction of a published paid result when the security policy requires manager/dual control;
- other commands classified as critical by the approved policy.

## 7.3 Recent-auth record

A recent-auth record must be:

- bound to actor ID;
- bound to the current session;
- bound to an action class or approved scope;
- short-lived;
- revocable;
- stored server-side;
- referenced by an opaque value;
- audit-linked without logging the secret reference in plaintext.

## 7.4 Recent-auth flow

```text
User starts a critical action
→ server requires/recommends recent authentication
→ user reauthenticates through approved factor
→ server creates short-lived recent-auth context
→ client submits the original command with the same idempotency key
→ server validates actor, session, action scope, expiry, and replay policy
→ command executes or is rejected
```

Reauthentication does not itself approve a batch. It only raises session assurance for the subsequent exact command.

## 7.5 Expiry and reuse

The exact timeout is an ADR decision. It must be short enough for high-risk financial use.

Policy may choose one-time use or limited reuse within the same action class. Cross-action or cross-session reuse is prohibited.

---

# 8. Authorization Model

## 8.1 RBAC plus ownership and state guards

The platform uses explicit permissions combined with object scope and domain guards.

```text
Identity
  → Role assignments
    → Permissions
      + Ownership/business scope
      + Current state/version/hash
      + Command-specific policy
```

Role names alone are not sufficient for sensitive service authorization.

## 8.2 Permission naming

Permission format:

```text
resource.action
```

Examples:

```text
payment_request.read
payment_request.review
payment_request.mark_eligible
payment_batch.create
payment_batch_version.finalize
payment_batch_version.approve
bank_export.generate_final
bank_export.mark_sent
evidence_link.confirm
evidence_link.replace
payment_attempt.confirm_paid
payment_publication.publish
audit.read
role.manage
retention.propose
retention.approve
legal_hold.manage
```

## 8.3 Role baseline

| Role | Domain | Baseline purpose |
|---|---|---|
| `trader_owner` | Trader | Own trader records, requests, publications, acknowledgement/dispute. |
| `accountant` | Internal | Daily financial review, batching preparation, bank result review, evidence and confirmation. |
| `manager` | Internal | Exact batch-version approval and configured high-risk decisions. |
| `warehouse_operator` | Internal | Authorized dispatch/receipt operations only. |
| `business_admin` | Internal | Trader/user administration and approved business configuration. |
| `technical_admin` | Internal | Technical configuration, mappings, feature flags, health/processing support; no implicit financial authority. |
| `read_only_auditor` | Internal | Read-only approved records/reports/audit with masking policy. |
| `support_operator` | Internal optional | Limited issue visibility and support workflow; no financial mutation. |
| `system_worker` | System | Technical asynchronous tasks only. |

A broad everyday `super_admin` role is not recommended. Emergency privilege is implemented as controlled break-glass access.

## 8.4 Permission source of truth

- Backend permission definitions are authoritative.
- Frontend consumes permissions for UX only.
- Role assignments are stored and audited.
- Permissions should be reviewed as code/configuration and tested.
- Unknown permissions fail closed.
- Production should not allow arbitrary permission strings created through UI without governance.

## 8.5 Role changes

Role/permission changes require:

- `role.manage` or equivalent permission;
- recent authentication for high-risk grants;
- reason;
- before/after audit;
- session invalidation or authorization-version refresh where required;
- separation from the recipient where policy requires;
- alerting for grants of manager approval, role management, audit export, retention approval, or break-glass capability.

---

# 9. Separation of Duties

## 9.1 Minimum Phase 1A control

The identity that finalizes/prepares an outgoing `PaymentBatchVersion` must not be the identity that approves that same version.

The common Phase 1A chain is:

```text
Accountant prepares/finalizes exact version
→ Different manager reviews exact version/hash
→ Manager approves or rejects
→ Accountant generates/downloads final export
→ Accountant marks exact export sent after manual bank submission
```

## 9.2 Technical administration boundary

A `technical_admin` does not automatically receive permissions to:

- approve batches;
- confirm payment attempts;
- publish results;
- mark exports sent;
- approve incoming payments;
- dispatch gold;
- read every financial file.

Temporary access must be explicit, time-limited where possible, justified, and audited.

## 9.3 Approval independence

The approver must not:

- approve a version they created or finalized;
- alter the version after approval;
- approve a stale/superseded version as current;
- approve through a generic status update;
- transfer approval to a replacement version automatically.

## 9.4 Sensitive correction independence

A correction that changes a published `paid` result should require a second authorized human—normally manager approval or dual control—before the replacement result/publication becomes active.

The exact permission and threshold policy is an ADR/business decision, but single-person silent correction of a published paid result is not an acceptable default.

## 9.5 Break-glass exception

Any exception to normal separation of duties requires the break-glass process defined in Section 27. It must not be implemented as a permanently enabled broad role.

---

# 10. Permission Catalogue

The following catalogue is the minimum naming baseline. Implementations may add narrower permissions but must not merge unrelated high-risk actions into one broad permission.

## 10.1 Identity and access

```text
auth.session.read_own
auth.session.revoke_own
auth.session.read_all
auth.session.revoke_all
user.read
user.create
user.update
user.deactivate
role.read
role.manage
permission.read
break_glass.activate
break_glass.review
```

## 10.2 Trader and beneficiary

```text
trader.read
trader.create
trader.approve
trader.reject
trader.suspend
trader.reactivate
trader.update_business
beneficiary.read
beneficiary.create
beneficiary.create_own
beneficiary.update_future
beneficiary.deactivate
```

## 10.3 Gold sale and incoming payment

```text
gold_sale.read
gold_sale.create_own
gold_sale.review
gold_sale.price
gold_sale.cancel
gold_sale.dispatch
incoming_receipt.create_own
incoming_receipt.read
incoming_payment.match
incoming_payment.confirm
incoming_payment.correct
bank_statement.upload
bank_statement.import
bank_statement.read
```

## 10.4 Outgoing payment request

```text
payment_request.create_own
payment_request.read_own
payment_request.read
payment_request.create_internal
payment_request.create_revision_own
payment_request.create_revision_internal
payment_request.submit
payment_request.review
payment_request.request_correction
payment_request.mark_eligible
payment_request.cancel
```

## 10.5 Batch/version/approval/export

```text
payment_batch.read
payment_batch.create
payment_batch.cancel_draft
payment_batch_version.create
payment_batch_version.finalize
payment_batch_version.read_approval_view
payment_batch_version.approve
payment_batch_version.reject
payment_batch_version.invalidate_approval
bank_export.generate_preview
bank_export.generate_final
bank_export.read
bank_export.download
bank_export.mark_sent
bank_export.quarantine
```

## 10.6 Results, evidence, and publication

```text
bank_result_bundle.upload
bank_result_bundle.read
bank_result_bundle.link_batch
bank_result_bundle.close
receipt_segment.create_external
receipt_segment.create_crop
receipt_segment.read
matching_candidate.create
matching_candidate.review
evidence_link.confirm
evidence_link.replace
evidence_link.revoke
payment_attempt.read
payment_attempt.confirm_paid
payment_attempt.confirm_failed
payment_attempt.create_retry
payment_attempt.correct_result
payment_publication.preview
payment_publication.publish
payment_publication.correct
payment_publication.read_own
payment_publication.acknowledge_own
payment_publication.dispute_own
```

## 10.7 Files and operations

```text
file.upload
file.read_metadata
file.preview
file.download
file.download_bank_export
file.read_sensitive_bundle
file.quarantine_review
manual_review.read
manual_review.assign
manual_review.resolve
report.read
report.export
audit.read
audit.export
security_event.read
```

## 10.8 Configuration and governance

```text
bank_profile.read
bank_profile.create_version
bank_mapping.create_version
source_bank_account.manage
feature_flag.read
feature_flag.update
ai_configuration.read
ai_configuration.update
retention.read
retention.propose
retention.approve
retention.activate
legal_hold.read
legal_hold.manage
backup_status.read
```

---

# 11. Baseline RBAC Matrix

The matrix below is intentionally conservative. `Own` always requires ownership derived from authenticated context.

Legend:

- `R` — read;
- `C` — create;
- `X` — execute command;
- `A` — approve;
- `Own` — own scope only;
- `Masked` — read with approved masking;
- `-` — denied by default.

## 11.1 Identity, trader, and beneficiary

| Capability | Trader | Accountant | Manager | Business admin | Technical admin | Auditor | Warehouse |
|---|---:|---:|---:|---:|---:|---:|---:|
| Read own profile | Own | - | - | - | - | - | - |
| Read trader records | Own | R | R | R | Limited | R/Masked | Limited order context |
| Approve/reject trader | - | - | A | X | - | - | - |
| Suspend/reactivate trader | - | - | A | X | - | - | - |
| Create own beneficiary | C | - | - | - | - | - | - |
| Read own beneficiaries | Own | R | R | R | - | R/Masked | - |
| Create/update future beneficiary for trader | Own before submission | X | R | R | - | - | - |
| Deactivate duplicate/future beneficiary | - | X | X | X | - | - | - |

Historical beneficiary snapshots in submitted requests and attempts are never rewritten by beneficiary-profile updates.

## 11.2 Payment requests

| Capability | Trader | Accountant | Manager | Business admin | Technical admin | Auditor |
|---|---:|---:|---:|---:|---:|---:|
| Create request | Own | C internal where permitted | - | - | - | - |
| Read request | Own | R | R | R | - | R/Masked |
| Create revision before/rework | Own allowed states | X | R | - | - | - |
| Submit request | Own | - | - | - | - | - |
| Start/review request | - | X | R | - | - | - |
| Request trader correction | - | X | R | - | - | - |
| Mark eligible for batching | - | X | R | - | - | - |
| Cancel request | Own draft/allowed | X allowed states | A exception | - | - | - |

Accountant eligibility is not manager approval.

## 11.3 Batch versions and exports

| Capability | Trader | Accountant | Manager | Business admin | Technical admin | Auditor |
|---|---:|---:|---:|---:|---:|---:|
| Read batch/version | - | R | R | R | Limited metadata | R/Masked |
| Create batch/version | - | C/X | - | - | - | - |
| Finalize version | - | X | - | - | - | - |
| Read approval view | - | R | R | R if granted | - | R/Masked |
| Approve/reject exact version | - | - | A | - by default | - | - |
| Generate preview export | - | X | R | - | - | - |
| Generate final export | - | X after valid approval | R | - | - | - |
| Download final bank export | - | X | R if policy | - | Support only by explicit grant | - by default |
| Mark exact export sent | - | X | R | - | - | - |
| Cancel draft batch | - | X | R | - | - | - |
| Invalidate approved flow | - | - | A | - | - | - |

The identity that finalized the version cannot approve it.

## 11.4 Results, evidence, and publications

| Capability | Trader | Accountant | Manager | Technical admin | Auditor |
|---|---:|---:|---:|---:|---:|
| Upload bank result bundle | - | C | - | - | - |
| Read full bundle | - | R | R | Temporary support only | R if explicitly permitted |
| Create manual crop | - | X | R | - | - |
| Create matching candidate | - | X/manual or system | R | - | - |
| Confirm primary evidence link | - | X | R | - | - |
| Confirm paid/failed attempt | - | X | R | - | - |
| Replace active evidence | - | X with reason | A for configured high-risk case | - | - |
| Publish result | - | X | R | - | - |
| Correct published paid result | - | Prepare correction | A/dual control | - | - |
| Read publication | Own | R | R | - | R/Masked |
| Acknowledge/dispute publication | Own | R | R | - | R |

## 11.5 Gold/incoming payment

| Capability | Trader | Accountant | Manager | Warehouse | Auditor |
|---|---:|---:|---:|---:|---:|
| Create gold-sale request | Own | C if permitted | - | - | - |
| Read gold-sale order | Own | R | R | Required dispatch scope | R/Masked |
| Set/version price | - | X | A if configured | - | R |
| Upload incoming receipt | Own | C | - | - | - |
| Match statement row | - | X | A exception | - | R |
| Confirm incoming payment | - | X | A exception/policy | - | R |
| Mark ready for dispatch | - | X | A if configured | R | R |
| Register dispatch | - | - | R | X | R |

## 11.6 Administration and governance

| Capability | Accountant | Manager | Business admin | Technical admin | Auditor |
|---|---:|---:|---:|---:|---:|
| Read bank profiles | R | R | R | R | R |
| Create bank business-rule version | - | A | X | Technical validation only | R |
| Create bank mapping version | - | R | R | X | R |
| Manage source bank account metadata | - | A | X | Technical support only | R/Masked |
| Manage roles | - | A/review | X | - by default | R |
| Manage technical feature flags | - | R | R | X | R |
| Configure external AI provider | - | - | R/approval policy | X | R/Masked |
| Read audit | Limited related | R | R | Technical subset | R |
| Export audit | - | X if granted | X if granted | - by default | X if granted |
| Propose retention | - | R | X | Technical input | R |
| Approve retention reduction | - | A/business/legal authority | - alone | - | R |
| Manage legal hold | - | A/authorized | Authorized governance | Technical execution only | R |

---

# 12. Command Authorization Contract

Every sensitive command must perform the following server-side checks in this order or an equivalent fail-closed order:

1. validate session and authentication domain;
2. validate account status and session revocation/security stamp;
3. resolve actor roles and permissions from authoritative storage/cache policy;
4. validate ownership or business scope;
5. validate required recent-auth/dual-control context;
6. resolve idempotency record and canonical request hash;
7. validate `If-Match` or immutable version/hash preconditions;
8. lock/load affected aggregates where necessary;
9. evaluate state-machine and domain guards;
10. apply business changes;
11. write audit and outbox records in the same transaction;
12. persist idempotency completion result;
13. commit once through the Unit of Work.

A partial result in which business state changes without audit/outbox/idempotency state is unacceptable.

---

# 13. Idempotency and Replay Protection

## 13.1 Mandatory commands

`Idempotency-Key` is mandatory for at least:

- payment-request submission;
- batch creation;
- batch-version creation/finalization;
- manager approval/rejection;
- final export generation;
- mark exact export sent;
- payment-attempt paid/failed confirmation;
- retry attempt creation;
- active evidence-link creation/replacement;
- payment-result publication/correction;
- incoming-payment confirmation;
- gold dispatch;
- retention activation/deletion execution;
- other commands designated sensitive by the API specification.

## 13.2 Idempotency identity

An idempotency record is scoped by:

- authenticated actor/client identity;
- operation identity;
- idempotency key;
- canonical request hash.

## 13.3 Required behavior

| Situation | Required result |
|---|---|
| New key | Execute normally. |
| Same key and same canonical request | Return the stored result/status. |
| Same key and different request | Reject with `409 IDEMPOTENCY_KEY_REUSED`. |
| Network timeout after commit | Retry returns the original committed result. |
| Two simultaneous requests | Only one logical execution succeeds. |
| Failed validation before execution | Store/handle according to API policy without permitting a conflicting replay. |

## 13.4 Security handling

- Store a hash of the key where practical rather than logging the raw key.
- Never expose another actor's idempotency result.
- Do not let a client choose the actor or operation scope.
- Retain critical command records according to approved operational policy.

---

# 14. Optimistic Concurrency and Locking

## 14.1 Mutable aggregates

Mutable resources expose `record_version` through an ETag.

```http
ETag: "rv-7"
If-Match: "rv-7"
```

Required errors:

```text
Missing required If-Match → 428 PRECONDITION_REQUIRED
Stale If-Match            → 412 VERSION_CONFLICT
```

## 14.2 Immutable snapshots

Immutable objects such as finalized `PaymentBatchVersion` use exact IDs and content hashes rather than arbitrary updates.

The client must submit the expected content hash for approval/export commands where specified.

## 14.3 Locking

Use database constraints and targeted row locks for:

- request/attempt allocation to a batch;
- batch-version finalization;
- manager approval;
- final export generation/mark-sent coordination;
- payment-attempt result confirmation;
- payment-request paid-total recalculation;
- primary evidence replacement;
- publication supersession;
- retention execution.

Locks must not be held while waiting on user interaction, file upload, external AI, or other network calls.

---

# 15. Exact Batch-Version Approval Security

## 15.1 Approval subject

The manager approves exactly:

- `PaymentBatchVersion` ID and number;
- ordered immutable payment rows;
- row count;
- total IRR amount;
- request/attempt/revision snapshots;
- bank profile version;
- bank mapping version;
- source bank account;
- content hash;
- validation summary and warnings.

The manager does not approve a mutable batch container.

## 15.2 Approval guards

Before approval, the backend must verify:

- actor has `payment_batch_version.approve`;
- recent-auth is valid for the current actor/session/action;
- actor is not the version finalizer/preparer;
- version belongs to the batch;
- version is current and `ready_for_approval`;
- version is immutable;
- submitted expected hash equals stored/recomputed hash;
- row count and total are internally consistent;
- bank profile, mapping, and source account are active/allowed for that exact snapshot;
- no prior conflicting decision exists;
- no blocking validation/security task exists;
- idempotency and concurrency checks pass.

## 15.3 Approval record

Approval/rejection records are append-only and include:

- decision ID;
- batch/version IDs;
- content hash;
- actor ID and role;
- session and recent-auth references;
- reason/note;
- decision time;
- request/correlation ID;
- idempotency-key hash;
- source IP/device metadata where allowed;
- separation-of-duty evaluation result.

## 15.4 Invalidation

Any material change requires a new version and prevents use of the previous approval for future execution.

Material changes include:

- row membership/order;
- amount;
- beneficiary/account-holder snapshot;
- IBAN;
- source bank account;
- bank profile/mapping version;
- reference/description that affects bank output;
- payment attempt/revision selection.

Approval is never copied automatically to a replacement version.

---

# 16. Bank Export Security

## 16.1 Preview versus final

A preview export may be generated before approval only when it is technically and visibly non-sendable.

A preview must not:

- satisfy the mark-sent command;
- be presented as the final bank file;
- use the final approval reference;
- be silently renamed into a final export.

## 16.2 Final export inputs

A final export is generated only from:

- exact approved batch version;
- valid approval record for the same hash;
- exact mapping/profile versions;
- exact source account;
- immutable ordered items.

The renderer must not re-read mutable current beneficiary data to replace approved snapshots.

## 16.3 Integrity checks

Before final download and mark-sent, verify:

```text
Export version == approved version
Export content hash == version content hash
Approval hash == version content hash
Export total == version total
Export row count == version row count
Export mapping == approved mapping
Export source account == approved source account
Actual file checksum == stored file checksum
```

A mismatch sets the export to `quarantined`, blocks operational download/send marking, creates a high-priority review task, and writes audit/security events.

## 16.4 Exact mark-sent command

Marking an export sent applies to the exact final export, not the general batch.

Record:

- export ID;
- batch/version ID;
- actor;
- submission channel;
- sent timestamp;
- note;
- integrity result;
- file checksum;
- request/idempotency context.

Downloading a file does not mean it was sent to the bank.

## 16.5 Spreadsheet injection

Untrusted names, descriptions, references, and notes must not create executable spreadsheet formulas.

For generated Excel/CSV:

- use typed cells where supported;
- reject or safely encode unexpected formula prefixes in untrusted text;
- do not copy raw user strings into formula-capable cells without policy;
- test values beginning with `=`, `+`, `-`, and `@`;
- preserve bank-required formatting without enabling formula injection.

---

# 17. Payment Result, Evidence, and Publication Security

## 17.1 Distinct decisions

These are separate security-relevant operations:

```text
Create/accept matching candidate
Create confirmed evidence link
Confirm payment attempt result
Create trader publication
```

One operation must not implicitly perform the others unless the API explicitly defines a reviewed composite command with all permissions and guards. Phase 1A should prefer separate commands.

## 17.2 Matching candidate

A candidate is a suggestion. It can have:

- score;
- reason codes;
- warnings;
- source method;
- provider/config version.

It is not evidence confirmation and must not change financial status.

## 17.3 Confirmed evidence link

Default cardinality:

- at most one active primary evidence link per attempt;
- at most one active primary attempt target per transaction-level segment;
- supplementary links may exist;
- partial unique constraints enforce active primary uniqueness.

Evidence is replaced/revoked through append-only history, not deleted or silently detached.

## 17.4 Manual crop

Phase 1A manual crop security requirements:

- source file authorization before preview;
- source file must be available/clean under file policy;
- page and normalized rectangle validation;
- derived crop linked to original source and renderer version;
- original file remains immutable;
- worker cannot publish or confirm payment;
- derived object checksum recorded;
- failed render does not create an active evidence link;
- accountant performs privacy review before trader publication.

## 17.5 Confirm paid/failed

Before confirming an attempt result, verify:

- actor permission;
- attempt belongs to an exact sent export or approved exception path;
- attempt is not cancelled/superseded;
- amount equals the authoritative attempt amount for a normal paid result;
- required evidence or approved text-only exception exists;
- duplicate/tracking/evidence conflicts are resolved;
- `If-Match` and idempotency pass;
- paid total will not exceed request amount.

```text
paid_sum == request amount → paid
0 < paid_sum < request amount → partially_paid
paid_sum > request amount → block and create reconciliation review
```

There is no normal `confirm anyway` path for overpayment.

## 17.6 Text-only confirmation

Text-only confirmation is an exception policy, not the default evidence model.

If enabled, it requires:

- explicit permission;
- mandatory reason;
- strong warning;
- audit flag;
- reporting visibility;
- optional manager/dual-control rule based on risk.

## 17.7 Publication

A trader sees an immutable `PaymentResultPublication`, not an unrestricted bank bundle or mutable internal evidence record.

Publication contains a reviewed snapshot of:

- trader and request scope;
- beneficiary display;
- amount;
- safe/masked IBAN policy result;
- attempt/result summary;
- bank/tracking data;
- selected safe evidence;
- share-file reference;
- publication version and content hash.

## 17.8 Privacy review

Before publication, an authorized user confirms that evidence:

- relates to the selected attempt;
- does not reveal another trader or beneficiary;
- does not reveal unrelated IBAN, amount, tracking number, or transaction;
- is readable enough for its stated purpose;
- is not a full mixed bank bundle.

## 17.9 Correction after publication

Corrections create a new result/publication version and supersede the old one.

For a published paid result, default security posture is:

```text
Accountant prepares correction
→ second authorized human reviews/approves
→ previous evidence/result preserved
→ aggregates recalculated
→ publication N+1 created
→ publication N superseded
→ trader notified
→ complete audit/outbox record
```

---

# 18. Trader Ownership and Data Isolation

## 18.1 Ownership derivation

Trader scope is derived from the authenticated trader identity.

Unsafe:

```json
{
  "trader_id": "client-selected-uuid"
}
```

Safe:

```text
trader_id = authenticated_actor.trader_id
```

## 18.2 Ownership paths

Examples:

```text
PaymentRequest.trader_id
GoldSaleOrder.trader_id
Beneficiary.trader_id
PaymentAttempt → PaymentRequest → trader_id
PaymentResultPublication → PaymentRequest → trader_id
Published FileLink → Publication → PaymentRequest → trader_id
```

A trader's access is evaluated through authoritative relationships, not a generic file visibility flag alone.

## 18.3 Trader-visible resources

Traders may access only:

- their profile/account status;
- their requests and allowed revisions/history;
- their gold-sale orders;
- their own publications, including clearly marked superseded versions when policy allows;
- safe files explicitly linked to their publication or own receipt submission;
- their acknowledgements/disputes;
- their notifications.

## 18.4 Never trader-visible

- full incoming bank statements;
- full outgoing bank export files;
- mixed bank result bundles;
- unconfirmed receipt segments;
- candidate scores and AI/provider logs;
- internal notes;
- manager approval details not approved for trader display;
- other traders' beneficiaries or requests;
- raw audit/security events;
- storage keys.

## 18.5 IDOR protection

Every read/download endpoint is tested with:

- another trader's valid object ID;
- random UUID;
- superseded/revoked file ID;
- internal bundle ID;
- direct file ID without parent scope;
- publication from another trader.

Responses should not leak unnecessary existence information.

---

# 19. File Security Model

## 19.1 Private storage

All files are private by default.

Allowed storage backends:

- controlled private local filesystem through authorized backend endpoints for pilot deployments;
- private S3-compatible object storage with short-lived signed access.

Prohibited:

- public static directories;
- predictable user-controlled paths;
- permanent public object URLs;
- raw storage keys in ordinary API responses;
- browser caching of sensitive files as PWA offline assets.

## 19.2 File lifecycle

```text
pending
quarantined
available
processing_failed
archived
retention_pending
deleted
```

Only `available` files may be used by normal business commands unless an explicit controlled exception exists.

## 19.3 Required metadata

At minimum:

```text
file_id
category
original_filename
server_generated_storage_key
mime_type
size_bytes
sha256_checksum
storage_backend
storage_state
scan_status
uploaded_by_actor
created_at
available_at
retention_policy_id
legal_hold_state
original_or_derived_relation
```

Business ownership is represented through explicit file links/derivations rather than trusting a polymorphic client field.

## 19.4 Upload validation

Validate:

- category-specific allowed MIME type;
- extension;
- file signature/content type;
- size and bundle limits;
- image/PDF/Excel structural readability;
- maximum page/sheet/row limits where appropriate;
- malicious or unsupported embedded content where tooling supports it;
- checksum and duplicate indicators;
- server-generated storage key;
- original filename only as metadata.

Unknown executable/binary formats are rejected.

## 19.5 Malware scanning

Production must make an explicit ADR decision for malware scanning.

The schema and lifecycle support:

```text
pending
clean
suspicious
failed
skipped_by_approved_policy
```

A `skipped` decision must not be implicit. It must reflect an approved deployment policy with compensating controls.

## 19.6 Download authorization

Every download/preview request re-evaluates:

- valid session/account state;
- permission;
- object ownership/scope;
- file category;
- file lifecycle/scan state;
- publication state for trader access;
- legal/security restriction;
- whether signed access is permitted.

## 19.7 Signed URLs

When signed URLs are used:

- issue only after authorization;
- keep lifetime short;
- use non-public bucket/object policy;
- avoid embedding secrets in filename/query logs;
- do not reuse as permanent links;
- prevent caching where feasible;
- record sensitive download events according to policy.

## 19.8 Browser behavior

- Do not place sensitive files or full API responses in `localStorage`, IndexedDB, or service-worker cache.
- Use `Cache-Control: no-store` or approved equivalent for sensitive responses.
- Revoke object URLs created in the browser after use.
- Do not send files or bank data to third-party analytics/error services.

## 19.9 Orphan and checksum reconciliation

Maintenance jobs detect:

- storage object without database record;
- database record without storage object;
- checksum mismatch;
- stale pending upload;
- derivative without source;
- missing approved export file.

Reconciliation does not automatically delete financial evidence. It creates controlled repair/quarantine work.

---

# 20. Audit Architecture

## 20.1 Audit is part of the transaction

For a sensitive business command, the following are committed atomically:

- business state;
- revision/version/history records;
- audit event;
- outbox event;
- idempotency result.

If the audit insert fails, the financial command fails and rolls back.

## 20.2 Audit actor

Audit actor types:

```text
trader_user
admin_user
system_worker
system_maintenance
```

An external AI provider is not a business actor. Provider/model information belongs in AI-run metadata. The responsible system actor and requesting human context are recorded separately.

## 20.3 Audit fields

Minimum fields:

```text
id
occurred_at
action
actor_type
actor_id
actor_role_snapshot
session_id
authentication_assurance
recent_auth_id_hash_or_reference
entity_type
entity_id
parent_entity_type
parent_entity_id
before_data_redacted
after_data_redacted
reason
metadata
request_id
correlation_id
idempotency_key_hash
entity_record_version
immutable_snapshot_hash
ip_address
user_agent
```

Not every field is populated for every event, but the schema must support them.

## 20.4 Audit action naming

Use stable names such as:

```text
auth.login_succeeded
auth.login_failed
auth.session_revoked
user.role_changed
trader.approved
payment_request.submitted
payment_request.revision_created
payment_request.marked_eligible
payment_batch.created
payment_batch_version.finalized
payment_batch_version.approved
payment_batch_version.rejected
payment_batch_approval.invalidated
bank_export.preview_generated
bank_export.final_generated
bank_export.integrity_failed
bank_export.sent_marked
receipt_segment.crop_created
evidence_link.confirmed
evidence_link.replaced
payment_attempt.paid_confirmed
payment_attempt.failed_confirmed
payment_attempt.retry_created
payment_publication.created
payment_publication.superseded
payment_publication.disputed
retention.policy_proposed
retention.policy_approved
legal_hold.created
break_glass.activated
```

## 20.5 Before/after data

Store only fields necessary to explain the action.

- Do not store password hashes, credentials, session secrets, CSRF tokens, API keys, raw file contents, or unrestricted provider payloads.
- Mask sensitive values where full values are not required for audit.
- Immutable snapshots may be referenced by ID/hash rather than copied completely.
- If an IBAN change must be explained, store an approved masked representation and immutable revision references unless full audit access is explicitly required.

## 20.6 Immutability

- No application endpoint updates or deletes audit events.
- Application database roles have INSERT/SELECT as appropriate but no UPDATE/DELETE on append-only audit tables.
- Schema ownership is separate from runtime application roles.
- Archival/export follows controlled maintenance procedures.
- Optional tamper-evidence such as chained hashes or signed audit exports may be added after Phase 1A, but database permissions and backup integrity are mandatory from launch.

## 20.7 Audit access

Audit read/export is a separate permission.

Audit views should support:

- target entity;
- actor;
- action;
- date range;
- request/correlation ID;
- security-relevant events;
- approved redaction/masking.

Technical support should not automatically receive unrestricted business-audit access.

---

# 21. Security Event Logging

## 21.1 Difference from business audit

Business audit explains authorized business changes. Security events record security-relevant behavior, including denied or failed attempts.

They may share infrastructure, but must remain conceptually distinguishable.

## 21.2 Events

Record at least:

- login success/failure;
- session creation/revocation/expiry;
- account lock/suspension;
- failed recent-auth attempt;
- rate-limit event;
- CSRF failure;
- unauthorized route/object access;
- cross-domain token/session use;
- invalid state transition attempt;
- stale `If-Match`/approval attempt where security-relevant;
- idempotency-key conflict;
- file validation/scan/quarantine event;
- denied sensitive file download;
- export integrity mismatch;
- repeated duplicate/overpayment override attempt;
- high-risk role/permission change;
- break-glass activation;
- retention/legal-hold violation attempt;
- abnormal worker/job behavior.

## 21.3 Log protection

Security logs must not contain:

- passwords or reset secrets;
- raw session tokens;
- raw idempotency keys;
- full CSRF tokens;
- storage credentials;
- full sensitive document payloads;
- raw bank files;
- provider API keys;
- unrestricted PII where not needed.

---

# 22. API and Web Security

## 22.1 Authentication by default

All endpoints require authentication except explicitly approved public endpoints such as:

- login;
- approved registration/recovery operations;
- liveness endpoint with minimal output.

Readiness/dependency endpoints must be internal or permission-restricted when they expose dependency state.

## 22.2 Command endpoints

Financial transitions use explicit command endpoints. Generic mass-assignment or `PATCH {status: ...}` endpoints are prohibited.

## 22.3 Validation

Validate:

- type and length;
- integer money strings/IRR consistency;
- explicit input unit;
- IBAN structure;
- enum values;
- date/time/timezone;
- ownership of referenced objects;
- file category and lifecycle;
- expected ETag/hash;
- command state guards;
- reason fields for corrections/rejections;
- pagination/filter limits.

## 22.4 Rate limiting

Apply rate limits to:

- login and recovery;
- recent-auth attempts;
- registration;
- file upload/finalization;
- expensive searches;
- report/export generation;
- AI/OCR triggers;
- signed URL generation;
- repeated failed commands.

Limits should use actor/account and network context, not only IP.

## 22.5 Error handling

Errors are structured and do not expose stack traces, SQL, filesystem paths, storage keys, provider secrets, or internal network addresses.

Security-relevant errors include a request/correlation ID.

## 22.6 CORS

- Allow only approved application origins.
- Do not use wildcard origin with credentials.
- Separate production, staging, and development origin lists.
- Reject unexpected origins for cookie-authenticated requests.

## 22.7 Security headers

Production reverse proxy/application should set an approved policy including:

- HSTS after HTTPS readiness;
- Content Security Policy;
- `X-Content-Type-Options: nosniff`;
- frame-ancestor/frame protections;
- referrer policy;
- permissions policy as appropriate;
- secure cache controls for sensitive responses.

CSP must be tested with PDF/image preview components and should not be disabled globally to fix one integration.

## 22.8 XSS

- Render names, notes, filenames, bank descriptions, and OCR text as text, not raw HTML.
- Strictly sanitize any future rich text.
- Avoid `dangerouslySetInnerHTML` for financial data.
- Treat provider/OCR output as untrusted input.

---

# 23. Frontend Security

## 23.1 No security through hiding

Frontend permission gates prevent confusing actions, but the backend enforces all access.

## 23.2 Sensitive storage

Do not persist in browser storage:

- long-lived auth tokens;
- bank files or receipt images;
- complete financial API responses;
- beneficiary/IBAN caches;
- financial command payloads;
- raw audit/security data;
- recent-auth references beyond the approved short-lived in-memory flow.

## 23.3 PWA caching

Trader PWA may cache:

- application shell;
- static icons/fonts/assets allowed by policy;
- non-sensitive public resources.

It must not offline-cache:

- payment requests/results;
- publications/evidence;
- IBANs;
- files;
- bank data;
- authenticated API responses.

Critical financial commands are never queued for offline replay.

## 23.4 Stale-data behavior

The UI must block stale approval or financial commands and handle:

- `412 VERSION_CONFLICT`;
- `428 PRECONDITION_REQUIRED`;
- approval version no longer current;
- evidence already replaced;
- attempt already confirmed;
- export quarantined.

It must not silently retry with a newer ETag or hash.

## 23.5 Timeout behavior

After a timeout on an idempotent command, the UI checks/retries with the same idempotency key. It must not immediately create a new logical command.

## 23.6 Sensitive confirmation dialogs

Dialogs display server-authoritative values such as:

- exact amount in IRR and Toman equivalent;
- actor/action;
- trader/beneficiary;
- exact batch version and hash fingerprint;
- row count;
- source bank account;
- evidence/publication impact;
- required reason.

A dialog does not replace recent authentication or backend authorization.

## 23.7 Third-party telemetry

Analytics and client error-reporting tools must not receive:

- IBAN;
- beneficiary identity;
- transaction amount/details;
- filenames or file URLs;
- receipt/bank images;
- audit data;
- raw request/response bodies.

Use allowlisted event metadata and redaction.

---

# 24. Worker and Asynchronous Security

## 24.1 Job payloads

Pass stable IDs and configuration-version references, not ORM objects, raw secrets, or large sensitive payloads through the queue.

## 24.2 Revalidation

A worker opens its own database session and revalidates:

- target exists;
- file is authorized/available;
- current state permits processing;
- expected version/config remains valid;
- job is not already completed/superseded;
- feature flag/provider policy is enabled.

## 24.3 Least privilege

Worker database/storage credentials grant only the permissions required for assigned queues. Worker containers do not receive manager/session signing secrets unless technically required by the approved design.

## 24.4 No human authority

Workers may render or propose. They cannot approve, confirm, publish, dispatch, or mark sent.

## 24.5 Retry safety

Tasks are idempotent, use bounded retries, distinguish transient/permanent errors, and persist important job state in PostgreSQL.

## 24.6 Queue separation

Logical queues:

```text
files
exports
notifications
reports
maintenance
ai
```

A low-volume deployment may use one worker process, but routing and credentials should remain reviewable.

---

# 25. Configuration and Secret Security

## 25.1 Configuration categories

Separate:

1. deployment secrets;
2. technical environment configuration;
3. versioned business configuration;
4. governed policy configuration.

Examples:

- Database credentials are deployment secrets.
- File-size limits are technical/business configuration with audit.
- Bank mappings and split rules are versioned business configuration.
- Retention and legal hold are governed policy, not an ordinary setting.

## 25.2 Secrets

Secrets are stored in environment-specific secret mechanisms and never:

- committed to source control;
- placed in frontend bundles;
- returned by APIs;
- written to logs;
- copied into support tickets;
- shared across services without need.

Use separate production credentials for:

- backend;
- worker;
- database runtime roles;
- backup process;
- object storage;
- external providers.

## 25.3 Secret rotation

The design must support rotation of:

- session/signing secrets;
- database credentials;
- storage credentials;
- backup credentials;
- AI/provider keys;
- optional notification credentials.

Rotation procedures must account for active sessions and staged key overlap where required.

## 25.4 Bank configuration

Bank profile/mapping/source-account changes:

- create new immutable versions;
- require appropriate business/technical permissions;
- do not reinterpret historical exports;
- create audit events;
- may require manager/business approval depending on risk.

## 25.5 Feature flags

Feature flags do not bypass authorization or audit.

Enabling AI, external providers, text-only confirmation, or sensitive download behavior requires an approved security/business decision, not just a technical-admin toggle.

---

# 26. Retention, Legal Hold, and Deletion

## 26.1 No ordinary deletion

Normal UI/API flows do not physically delete:

- payment requests/revisions;
- payment attempts;
- batches/versions/items;
- approvals;
- bank exports;
- result bundles;
- receipt segments;
- confirmed evidence links;
- publications;
- bank statements/import runs/rows;
- audit records;
- gold-sale financial records.

## 26.2 Retention workflow

Retention policy changes use:

```text
Proposal
→ business/legal review
→ approval
→ legal-hold check
→ dry-run impact report
→ backup coordination
→ activation
→ separate deletion execution
→ deletion evidence/audit
```

## 26.3 Technical-admin limitation

A technical administrator cannot unilaterally shorten retention and execute deletion.

## 26.4 Legal hold

A legal hold blocks deletion of affected records/files regardless of ordinary retention eligibility.

Legal holds require:

- scope;
- authority/reason;
- created/approved actor;
- effective timestamp;
- release process;
- audit history.

## 26.5 Backup interaction

Retention documentation must describe how expired data remains in protected backups until backup rotation. Immediate destruction from historical backups must not be falsely promised unless technically implemented and legally required.

---

# 27. Emergency and Break-Glass Access

## 27.1 Purpose

Break-glass access exists only for exceptional operational/security recovery when normal role assignment cannot resolve an urgent incident.

## 27.2 Controls

- disabled by default;
- separate account or elevation workflow;
- strong authentication/recent auth;
- mandatory incident/change reference;
- explicit scope and expiry;
- alert to designated owners;
- all actions heavily audited;
- post-use review and credential/session revocation;
- no silent use to bypass separation of duties.

## 27.3 Restrictions

Break-glass should not routinely approve outgoing payments. If it is used for a financial action, the event requires immediate secondary review and incident classification.

---

# 28. DevOps and Infrastructure Security

## 28.1 Network exposure

Public:

- HTTPS reverse proxy only.

Internal/private:

- frontend application origins as designed;
- backend service network;
- PostgreSQL;
- Redis;
- Celery workers;
- object/local storage;
- monitoring components.

PostgreSQL, Redis, storage administration, and worker control interfaces are not exposed publicly.

## 28.2 Containers

Production containers should:

- run as non-root;
- use pinned versions/digests;
- avoid `latest` tags;
- have minimal images;
- use read-only filesystem where practical;
- have explicit writable mounts;
- define resource limits;
- not mount Docker socket;
- receive only required secrets;
- emit structured logs without sensitive payloads.

## 28.3 Database roles

Separate roles for:

- schema migration/owner;
- backend runtime;
- worker runtime;
- read-only reporting where needed;
- backup/restore.

Runtime roles cannot alter schema or update/delete append-only audit/approval records.

## 28.4 HTTPS/TLS

- Production uses HTTPS.
- HTTP redirects to HTTPS.
- Cookies use `Secure` and HTTP-only attributes as appropriate.
- TLS certificates are monitored and renewed.
- Internal TLS is considered based on hosting topology and threat model.

## 28.5 Backups

Backups contain sensitive financial and identity data.

Required controls:

- database and file backup;
- encrypted off-host/off-server copy;
- access limited to authorized operations personnel;
- checksums/manifest;
- backup monitoring;
- documented RPO/RTO;
- regular restore test;
- restored-environment access control;
- verification of trader isolation, audit integrity, and file consistency after restore.

## 28.6 Environment separation

Development, staging, and production use separate:

- databases;
- storage buckets/paths;
- credentials;
- domains/origins;
- provider keys;
- backup destinations.

Production financial files must not be copied into development/test without approved anonymization and authorization.

## 28.7 Dependency and supply-chain security

CI should include:

- dependency scanning;
- container scanning;
- secret scanning;
- lockfile verification;
- pinned deployment artifacts;
- reviewed update process;
- SBOM generation where practical;
- provenance/signing improvements in later maturity phases.

---

# 29. Monitoring and Alerting

## 29.1 Security metrics

Track:

- failed/successful login rates;
- locked accounts;
- session revocations;
- recent-auth failures;
- authorization denials by endpoint/permission;
- cross-trader access attempts;
- rate-limit events;
- sensitive file download counts;
- file quarantine/scan failures;
- batch approval attempts/rejections;
- separation-of-duty blocks;
- export integrity mismatches;
- idempotency conflicts;
- role/permission grants;
- break-glass usage;
- retention/legal-hold events;
- backup and restore-test status.

## 29.2 Operational metrics with security relevance

- worker backlog and stale jobs;
- storage/database/Redis availability;
- orphan/checksum reconciliation failures;
- unresolved high-priority manual-review tasks;
- repeated overpayment/duplicate conflicts;
- AI/provider failures when enabled.

## 29.3 Alerts

Alert on at least:

- unusual failed-login burst;
- repeated authorization denial from one account/session;
- attempted trader cross-scope access;
- high-risk role grant;
- break-glass activation;
- export integrity mismatch;
- backup failure;
- storage/database unavailability;
- malware/suspicious upload;
- audit insertion failure;
- retention/legal-hold policy violation;
- abnormal sensitive-file download volume.

Alerts must avoid including full sensitive data.

---

# 30. Incident Response

## 30.1 Incident categories

Examples:

- credential/session compromise;
- unauthorized data access;
- trader isolation failure;
- malicious file or malware event;
- approval/export integrity incident;
- incorrect publication/data exposure;
- audit tampering attempt;
- secret leakage;
- backup exposure/loss;
- provider data-governance incident;
- insider misuse.

## 30.2 Immediate response capabilities

The system/operations team must be able to:

- revoke user sessions;
- lock/suspend accounts;
- disable a permission/role grant;
- disable external AI/provider calls;
- quarantine files or exports;
- disable final-export download/mark-sent if integrity is questioned;
- preserve affected audit/security logs;
- identify impacted entities/traders;
- take controlled backups/snapshots for investigation;
- place records under legal hold;
- switch to manual fallback operation.

## 30.3 Response process

```text
Detect
→ classify and assign owner
→ contain
→ preserve evidence
→ assess scope and impact
→ recover through approved procedure
→ communicate according to business/legal policy
→ perform root-cause review
→ implement corrective controls
→ close with documented approval
```

## 30.4 Audit during incident

Do not destroy or rewrite evidence to make the current state appear correct. Corrections use explicit commands and supersession, preserving the incident timeline.

---

# 31. Security Testing Requirements

## 31.1 Authentication/session tests

- generic invalid-login response;
- lock/rate-limit behavior;
- session expiry and logout;
- password change invalidates sessions;
- suspended/deactivated account blocked;
- trader session rejected on admin route;
- admin session rejected on trader ownership path where inappropriate;
- CSRF rejection for unsafe cookie-auth requests;
- session fixation prevention;
- recent-auth expiry, scope, session binding, and replay.

## 31.2 RBAC tests

For every important endpoint, test allowed and denied roles.

Required examples:

- accountant cannot approve batch version;
- manager cannot bypass version/hash validation;
- technical admin cannot approve or confirm payment by default;
- read-only auditor cannot create jobs, exports, downloads, notifications, or mutations beyond explicitly allowed reads;
- warehouse user cannot access unrelated financial workflows;
- support operator cannot view full bundles or perform financial commands.

## 31.3 Ownership/IDOR tests

- Trader A cannot read/update Trader B request.
- Trader A cannot read Trader B beneficiary.
- Trader A cannot read Trader B publication.
- Trader A cannot download Trader B file by guessed ID.
- Trader cannot download full mixed bundle.
- Trader cannot access a file whose visibility flag is wrong but publication relationship is absent.
- Internal user without sensitive-file permission cannot download bank export/bundle.

## 31.4 Separation-of-duty tests

- version finalizer cannot approve same version;
- approval cannot be reused for replacement version;
- technical role assignment alone does not grant approval;
- break-glass activation is audited and expires;
- published paid correction cannot activate without required second control.

## 31.5 Idempotency and concurrency tests

- double-click approval creates one decision;
- timeout retry with same key returns original result;
- same key/different payload is rejected;
- stale `If-Match` returns 412;
- missing required `If-Match` returns 428;
- two accountants cannot create two active primary evidence links;
- two managers cannot create conflicting approval decisions;
- concurrent batch allocation does not duplicate attempts.

## 31.6 Batch/export integrity tests

- cannot approve draft/non-current version;
- wrong expected hash rejected;
- preparer cannot approve;
- no final export before valid approval;
- preview cannot be marked sent;
- changed mapping/source account invalidates flow;
- modified stored file checksum quarantines export;
- mark-sent records exact export;
- spreadsheet formula-injection cases are handled safely.

## 31.7 Evidence/publication tests

- candidate acceptance does not confirm payment;
- crop creation does not publish or confirm;
- primary evidence uniqueness enforced;
- evidence replacement preserves previous link;
- full mixed bundle cannot be trader-visible;
- privacy review blocks unsafe crop publication;
- overpayment confirmation blocked;
- superseded publication remains historical and current publication changes correctly;
- published paid correction requires configured higher assurance.

## 31.8 File-security tests

- MIME/extension mismatch rejected/quarantined;
- oversized/unsupported file rejected;
- filename cannot influence storage path;
- executable/polyglot sample handled according to scanner policy;
- quarantined file cannot be previewed/downloaded through normal flow;
- signed URL expires and is scope-limited;
- raw storage key not returned;
- service worker does not cache sensitive responses;
- orphan/checksum reconciliation creates controlled work.

## 31.9 Audit tests

- sensitive command and audit event commit atomically;
- failed audit insert rolls back business command;
- audit includes actor, request, version/hash, reason, and assurance where required;
- audit endpoint is read-only;
- runtime DB role cannot update/delete audit rows;
- secrets and raw file contents are absent from audit/logs;
- role, retention, legal-hold, and break-glass events are audited.

## 31.10 DevOps tests

- public network cannot reach PostgreSQL/Redis directly;
- production containers run non-root;
- secrets are absent from images/frontend bundles/logs;
- backup restore succeeds in isolated test environment;
- health endpoints do not reveal secrets;
- dependency/container/secret scans are CI gates.

---

# 32. Phase 1A Security Acceptance Criteria

Phase 1A is acceptable only when all criteria below are verified.

## 32.1 Identity and sessions

1. Trader and internal authentication domains are separated.
2. Passwords use an approved password-hashing implementation.
3. Sessions are server-revocable and have enforced expiry.
4. Suspended, locked, or deactivated accounts are blocked according to policy.
5. Login and recent-auth attempts are rate-limited and security-logged.
6. Cookie authentication, when selected, includes CSRF protection.
7. Long-lived credentials are not stored in browser local storage.

## 32.2 Authorization

8. Backend permissions are deny-by-default.
9. Trader ownership is derived from authenticated context.
10. Trader IDOR tests pass.
11. Read-only users cannot trigger side effects.
12. Technical admins have no implicit financial approval/confirmation authority.
13. Permission/role changes are audited and invalidate authorization state as required.

## 32.3 Financial controls

14. Every outgoing Phase 1A batch requires manager approval.
15. Approval is bound to exact immutable version/hash.
16. Version preparer/finalizer cannot approve the same version.
17. Approval requires valid recent authentication.
18. Material changes require a new version and reapproval.
19. Final export is generated only from the approved snapshot.
20. Export integrity is checked before download/send marking.
21. Mark-sent applies to the exact final export.
22. Sensitive commands have mandatory idempotency.
23. Mutable commands enforce optimistic concurrency.

## 32.4 Results and publications

24. AI/candidates cannot confirm financial outcomes.
25. Manual crop is authorized, traceable, and separated from confirmation/publication.
26. Primary evidence cardinality is enforced.
27. Overpayment is blocked and routed to reconciliation.
28. Traders receive only immutable controlled publications and safe evidence.
29. Mixed bank bundles are never trader-visible.
30. Published paid corrections require the approved higher-assurance flow.

## 32.5 Files

31. Files are private and use server-generated storage keys.
32. Upload type/size/signature validation exists.
33. File lifecycle includes pending/quarantine/available states.
34. Production malware-scanning policy is documented and implemented or has approved compensating controls.
35. Every preview/download is authorized.
36. Sensitive files are not stored in browser persistent cache.
37. File checksum/orphan reconciliation exists.

## 32.6 Audit and governance

38. Business state, audit, outbox, and idempotency complete atomically.
39. Audit is append-only for runtime application roles.
40. Sensitive role/configuration/security events are logged.
41. Retention reduction cannot be executed by technical admin alone.
42. Legal hold blocks deletion.
43. Break-glass is disabled by default and reviewable.

## 32.7 Operations

44. Production uses HTTPS and approved security headers.
45. PostgreSQL, Redis, workers, and private storage are not publicly exposed.
46. Runtime containers are hardened and receive least-privilege secrets.
47. Database/file backups are encrypted/protected, monitored, and restore-tested.
48. Incident response supports session revocation, quarantine, evidence preservation, and legal hold.
49. Security/RBAC/file/audit tests are CI release gates.

---

# 33. Implementation Order

Security is implemented before or alongside financial features, not after them.

Recommended order:

1. Separate identity/account models and account states.
2. Authentication/session ADR and implementation.
3. Password hashing, rate limits, lockout, session revocation.
4. Permission constants and role-assignment persistence.
5. Backend authorization and trader ownership guards.
6. Actor/request/recent-auth context.
7. Unit of Work audit/outbox/idempotency foundation.
8. Optimistic concurrency and command preconditions.
9. Append-only audit/security-event storage and DB permissions.
10. Private file lifecycle, upload validation, authorization, and storage reconciliation.
11. Payment request/revision permissions.
12. Batch-version separation of duties and exact approval.
13. Final-export integrity and exact mark-sent control.
14. Evidence-link/cardinality and manual-crop security.
15. Payment-result and immutable publication controls.
16. Role/settings/retention/legal-hold governance.
17. Monitoring, alerting, incident response, and break-glass.
18. Security tests, penetration-style abuse tests, and production review.

---

# 34. Open ADRs and Production Decisions

The architecture is implementation-ready, but these production decisions must be approved and documented:

| ID | Decision |
|---|---|
| `ADR-SEC-001` | Authentication/session transport and CSRF design. |
| `ADR-SEC-002` | Trader and admin session idle/absolute timeouts. |
| `ADR-SEC-003` | MFA requirement for manager/internal users at initial production. |
| `ADR-SEC-004` | Recent-auth factor, timeout, action scope, and replay policy. |
| `ADR-SEC-005` | Exact separation-of-duty exceptions and break-glass authority. |
| `ADR-SEC-006` | Production malware scanner and skipped-scan compensating controls. |
| `ADR-SEC-007` | IBAN masking policy by role and trader publication. |
| `ADR-SEC-008` | Evidence requirement and text-only confirmation policy. |
| `ADR-SEC-009` | Dual-control/manager policy for published paid-result correction. |
| `ADR-SEC-010` | Audit/security-event retention and export authority. |
| `ADR-SEC-011` | Financial/file retention, legal-hold authority, and deletion execution. |
| `ADR-SEC-012` | Production hosting, admin network restrictions, and optional IP allowlist. |
| `ADR-SEC-013` | RPO/RTO, backup encryption, off-site location, and restore-test cadence. |
| `ADR-SEC-014` | External AI/provider data governance and allowed input scope. |
| `ADR-SEC-015` | Security monitoring/alert destinations and incident ownership. |

Open ADRs do not permit insecure defaults. Until decided, use the conservative behavior defined in this document.

---

# 35. Coding Agent Rules

A coding agent implementing the platform must follow these rules:

1. Do not implement generic financial `PATCH status` endpoints.
2. Do not trust frontend role, actor, trader ID, totals, approval state, or file visibility.
3. Do not accept trader scope from payload.
4. Do not allow the batch-version preparer to approve the same version.
5. Do not approve a mutable or stale batch.
6. Do not generate a final bank export without exact valid approval.
7. Do not mark a general batch sent; mark the exact final export sent.
8. Do not retry sensitive commands with a new idempotency key after an ambiguous timeout.
9. Do not ignore stale `If-Match` or expected-hash checks.
10. Do not let AI, OCR, matching, or workers finalize financial decisions.
11. Do not treat matching candidates as confirmed evidence.
12. Do not delete or silently detach active financial evidence.
13. Do not expose mixed bank bundles to traders.
14. Do not expose storage keys or public permanent file URLs.
15. Do not cache sensitive authenticated data in PWA/browser persistent storage.
16. Do not log passwords, tokens, CSRF values, raw idempotency keys, secrets, raw files, or unrestricted provider payloads.
17. Do not grant technical admins implicit financial authority.
18. Do not let read-only users trigger hidden mutations or jobs.
19. Do not implement retention as a simple technical-admin setting.
20. Do not allow application runtime roles to update/delete append-only audit or approval records.
21. Do not perform external network calls inside a financial database transaction.
22. Do not merge Preview Export and Final Export.
23. Do not correct a published paid result silently or in place.
24. Do not use production financial files in development without approved controls.
25. Do not weaken a security rule to imitate the old messaging/spreadsheet process.

---

# 36. Final Security Position

The Phase 1A platform is secure enough to begin controlled implementation only when security is built into the command and data model:

```text
Authenticated identity
→ explicit permission
→ ownership/scope
→ state/version/hash guard
→ recent auth or dual control when required
→ idempotent transactional command
→ immutable history/audit/outbox
→ controlled file/publication access
```

The most important security outcome is not the presence of advanced AI, bank APIs, or a complex fraud engine.

It is that every high-value action is attributable, authorized, version-bound, replay-safe, concurrency-safe, evidence-preserving, and recoverable from the first operational release.
