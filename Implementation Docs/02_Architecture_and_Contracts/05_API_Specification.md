# Gold Trade Settlement Platform

## API Specification

**Document ID:** `05_API_Specification`  
**Version:** `1.1`  
**Status:** Authoritative implementation baseline  
**Language:** English  
**API style:** REST + JSON over HTTPS, with explicit command endpoints for workflow transitions  
**Backend:** FastAPI + SQLAlchemy 2.x  
**Clients:** Trader PWA and Admin Web App  
**Supersedes:** Version 1.0

**Authoritative dependencies:**

- `00_Master_Implementation_Blueprint.md` version 1.1
- `01_Product_Requirements_PRD.md` version 1.1
- `02_Domain_Model_and_Business_Rules.md` version 1.1
- `03_System_Architecture.md` version 1.1
- `04_Database_Schema.md` version 1.1
- `06_Workflows_and_State_Machines.md` must be revised to use the status and command contract defined here.

---

## Version History

| Version | Change |
|---|---|
| 1.0 | Initial broad API draft. |
| 1.1 | Aligns the API with request revisions, immutable batch versions, exact-version manager approval, final-export integrity, Phase 1A manual crop, confirmed evidence links, immutable trader publications, mandatory idempotency, optimistic concurrency, transactional outbox, revised file lifecycle, single-center Phase 1A, and canonical health endpoints. |

---

# 1. Purpose and Authority

This document defines the implementation contract for the platform's HTTP API.

It specifies:

- public and authenticated route groups;
- request and response DTO conventions;
- authorization and ownership rules;
- financial command endpoints;
- concurrency and idempotency requirements;
- file upload, preview, crop, and download contracts;
- asynchronous processing behavior;
- error contracts;
- Phase 1A endpoint scope.

This API is not a generic CRUD façade over database tables. Financial state changes are expressed as business commands and are executed by domain services.

The API preserves required business outcomes while standardizing and improving the former manual process. It must not reproduce messenger, spreadsheet, or paper interactions as the primary application model.

---

# 2. Non-Negotiable API Invariants

## 2.1 No generic financial status mutation

Never expose an endpoint such as:

```http
PATCH /api/v1/payment-attempts/{id}
Content-Type: application/json

{"status":"paid"}
```

Use explicit commands:

```http
POST /api/v1/payment-attempts/{attempt_id}/confirm-paid
POST /api/v1/payment-attempts/{attempt_id}/confirm-failed
POST /api/v1/payment-batches/{batch_id}/versions/{version_id}/approve
```

Each command performs permission checks, state guards, concurrency checks, audit logging, outbox creation, and idempotency handling.

## 2.2 Human authority

AI, OCR, matching suggestions, and workers may create suggestions or derived files. They may not:

- approve a batch;
- confirm an incoming payment;
- confirm an outgoing payment as paid or failed;
- publish a trader-visible financial result;
- authorize dispatch;
- execute a financial override.

## 2.3 Manager approval is exact-version approval

Every outgoing Phase 1A batch requires manager approval.

The manager approves or rejects one immutable `PaymentBatchVersion`, identified by:

- version ID and version number;
- ordered row set;
- row count;
- total amount in IRR;
- bank profile version;
- bank mapping/template version;
- source bank account;
- content hash.

Approval of a mutable batch container is invalid.

## 2.4 Trader isolation

Trader endpoints derive `trader_id` from the authenticated session. A trader-supplied `trader_id` is ignored or rejected.

Trader responses must not expose:

- another trader's records;
- mixed bank bundles;
- internal notes;
- manager/accountant-only warnings;
- raw audit data;
- storage keys;
- unrelated evidence.

## 2.5 Single-center Phase 1A

Phase 1A has one center and no tenant selector in URLs, request bodies, tokens, or UI. Multi-company behavior belongs to Phase 4.

## 2.6 Immutable financial snapshots

The API never edits immutable rows such as:

- payment request revisions;
- finalized batch versions/items;
- batch approval decisions;
- original file metadata after availability;
- used bank-profile versions/mappings;
- bank statement rows;
- historical evidence links;
- trader result publications;
- audit logs.

A correction inserts a new version/revision/link/publication and preserves the prior record.

---

# 3. Base URL, Protocol, and Media Types

## 3.1 Base path

```text
/api/v1
```

Production examples:

```text
https://trader.example.com
https://admin.example.com
https://api.example.com/api/v1
```

The actual domains are deployment configuration. API routes remain under `/api/v1`.

## 3.2 HTTPS

Production traffic must use HTTPS. Plain HTTP may be used only in local development or inside a trusted reverse-proxy network.

## 3.3 Media types

JSON:

```http
Content-Type: application/json
Accept: application/json
```

Uploads:

```http
Content-Type: multipart/form-data
```

Downloads may include:

```text
application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
application/pdf
image/jpeg
image/png
application/zip
```

## 3.4 Character and locale rules

- JSON is UTF-8.
- User-visible Persian text is accepted and returned as Unicode.
- IBAN, tracking numbers, hashes, IDs, and machine codes use canonical Latin characters.
- APIs return canonical UTC timestamps; clients render Jalali dates.
- Raw bank date strings are returned separately when relevant.

---

# 4. Standard HTTP Headers

## 4.1 Correlation

Clients may provide:

```http
X-Request-ID: 6e722a7c-23fd-4ce1-959e-e0cc20d8d51e
```

The server validates or replaces invalid values and always returns a correlation ID.

## 4.2 Idempotency

The following header is mandatory for critical commands:

```http
Idempotency-Key: 8c496df4-d356-4df6-868f-c8f9a9f1b625
```

Required operations include:

- payment-request submission;
- structured bulk draft creation, when enabled;
- batch creation;
- batch-version creation/finalization;
- manager approval/rejection;
- final export generation;
- sent-to-bank marking;
- payment result confirmation;
- evidence-link creation/replacement;
- trader result publication;
- dispatch/settlement registration;
- critical configuration version activation.

Same key and same canonical request hash return the original logical result. Same key with a different request hash returns `409 IDEMPOTENCY_KEY_REUSED`.

## 4.3 Optimistic concurrency

Mutable resources return:

```http
ETag: "rv-7"
```

A modifying command must provide:

```http
If-Match: "rv-7"
```

Missing required precondition:

```text
428 PRECONDITION_REQUIRED
```

Stale precondition:

```text
412 VERSION_CONFLICT
```

Immutable snapshots use IDs and hashes rather than `If-Match`.

## 4.4 Authentication headers/cookies

The exact session transport is finalized by `ADR-001`. The stable API contract supports:

- secure HttpOnly session/refresh cookies as the preferred browser baseline; or
- a short-lived bearer access token with server-side revocation/session records.

The API must not require clients to store long-lived tokens in browser local storage.

When cookie authentication is used, unsafe methods require CSRF protection:

```http
X-CSRF-Token: <token>
```

## 4.5 Recent authentication

Manager batch approval and other configured critical actions require a recent-auth context. The client obtains it through reauthentication and sends:

```http
X-Recent-Auth: <short-lived-reference>
```

The reference must not be logged as plaintext and is not a replacement for the normal session.

---

# 5. Common Response Contracts

## 5.1 Resource identity

Resource IDs are UUID strings.

```json
{
  "id": "6f401c7d-13c2-4ce0-8c5c-3ec3da35e481"
}
```

Human-readable numbers such as `PR-...`, `PB-...`, and `EXP-...` are display/reference values, not primary keys.

## 5.2 Timestamps

```json
{
  "created_at": "2026-07-18T09:15:21Z",
  "bank_date_raw": "1405/04/27"
}
```

## 5.3 Money and input provenance

Canonical money is integer IRR.

```json
{
  "amount_irr": 34400000000,
  "entered_amount": {
    "value": 3440000000,
    "unit": "TOMAN"
  }
}
```

Rules:

- `amount_irr` is authoritative.
- `entered_amount` records what the user entered.
- Toman conversion is exact multiplication by 10.
- The server does not infer units from magnitude.
- Floating-point money is rejected.

## 5.4 List pagination

Operational queues use cursor pagination:

```json
{
  "items": [],
  "page_info": {
    "next_cursor": "opaque-or-null",
    "has_more": false,
    "page_size": 50
  }
}
```

Query example:

```text
?limit=50&cursor=opaque&sort=-created_at&status=submitted_to_center
```

Rules:

- default `limit`: 25;
- maximum `limit`: 100 unless endpoint-specific;
- cursors are opaque;
- stable tiebreaker includes the resource ID;
- total counts are optional for high-volume queues;
- report endpoints may use page/total pagination when exact totals are useful.

## 5.5 Resource version

Mutable resource bodies include:

```json
{
  "record_version": 7,
  "etag": "rv-7"
}
```

## 5.6 Allowed actions

Detail responses may include:

```json
{
  "allowed_actions": ["request_correction", "mark_eligible_for_batching"]
}
```

This field is a UI helper only. Backend authorization remains authoritative.

## 5.7 Warnings

Non-blocking validation is represented as:

```json
{
  "warnings": [
    {
      "code": "BENEFICIARY_DUPLICATE_SUSPECTED",
      "message": "A similar beneficiary already exists.",
      "related_resource_id": "uuid"
    }
  ]
}
```

Warnings do not silently change financial records.

---

# 6. Error Contract

All API errors use:

```json
{
  "error": {
    "code": "VERSION_CONFLICT",
    "message": "The record changed after it was loaded.",
    "details": [
      {
        "field": null,
        "reason": "expected rv-7 but current version is rv-8"
      }
    ],
    "request_id": "6e722a7c-23fd-4ce1-959e-e0cc20d8d51e"
  }
}
```

## 6.1 Standard errors

| HTTP | Code | Meaning |
|---:|---|---|
| 400 | `BAD_REQUEST` | Malformed or semantically invalid request |
| 400 | `INVALID_STATE_TRANSITION` | Command is not allowed from current state |
| 400 | `BUSINESS_RULE_VIOLATION` | Domain rule failed |
| 400 | `AMOUNT_UNIT_MISMATCH` | Entered amount does not equal canonical IRR |
| 400 | `IBAN_INVALID` | IBAN normalization/format failed |
| 401 | `UNAUTHENTICATED` | No valid session |
| 401 | `RECENT_AUTH_REQUIRED` | Critical action requires reauthentication |
| 403 | `FORBIDDEN` | Permission denied |
| 404 | `NOT_FOUND` | Missing or intentionally hidden resource |
| 409 | `CONFLICT` | Duplicate or incompatible command |
| 409 | `IDEMPOTENCY_KEY_REUSED` | Same key with different request hash |
| 409 | `ACTIVE_BATCH_MEMBERSHIP_EXISTS` | Attempt/request already allocated |
| 409 | `ACTIVE_PRIMARY_EVIDENCE_EXISTS` | Primary evidence cardinality conflict |
| 409 | `APPROVAL_INVALIDATED` | Approval no longer matches current version |
| 409 | `EXPORT_INTEGRITY_MISMATCH` | Export differs from approved snapshot |
| 409 | `RECONCILIATION_REQUIRED` | Paid sum exceeds or conflicts with request |
| 412 | `VERSION_CONFLICT` | `If-Match` is stale |
| 413 | `FILE_TOO_LARGE` | Size limit exceeded |
| 415 | `UNSUPPORTED_FILE_TYPE` | Type not allowed for purpose |
| 422 | `VALIDATION_ERROR` | DTO/field validation failed |
| 428 | `PRECONDITION_REQUIRED` | Required `If-Match` or idempotency key missing |
| 429 | `RATE_LIMITED` | Rate limit exceeded |
| 500 | `INTERNAL_ERROR` | Unexpected error; no sensitive details |
| 503 | `DEPENDENCY_UNAVAILABLE` | Required dependency unavailable |
| 503 | `BACKGROUND_PROCESSING_UNAVAILABLE` | Redis/worker path unavailable |

Validation errors may contain multiple field entries. Sensitive values must be masked.

---

# 7. Canonical API Status Values

These strings are part of the API contract. `06_Workflows_and_State_Machines.md` must use the same values.

## 7.1 Trader

```text
pending_approval, active, suspended, rejected, inactive, blocked
```

## 7.2 Payment request

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

## 7.3 Payment attempt

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

## 7.4 Payment batch

```text
draft
ready_for_approval
approved
approval_invalidated
exported
sent_to_bank
result_received
partially_resolved
resolved
rejected
cancelled
```

## 7.5 Payment batch version

```text
draft, ready_for_approval, approved, rejected, superseded
```

## 7.6 Bank export

```text
generating, generated, validated, downloaded,
sent_to_bank_marked, quarantined, superseded, voided, failed
```

## 7.7 Bank result bundle

```text
uploaded
files_stored
normalization_pending
normalized
manual_review_required
under_manual_review
partially_matched
matched
closed
processing_failed
archived
```

## 7.8 Receipt segment

```text
created
processing
unmatched
candidate_found
confirmed_linked
published
superseded
voided
```

## 7.9 Matching candidate

```text
proposed, accepted_for_confirmation, rejected, superseded, expired
```

## 7.10 Confirmed evidence link

```text
active, replaced, voided
```

## 7.11 Result publication

```text
active, superseded, revoked
```

## 7.12 Processing job

```text
queued, running, succeeded, failed, retry_scheduled,
cancelled, dead_lettered, fallback_to_manual
```

## 7.13 Gold sale order

```text
draft
submitted
under_center_review
priced
waiting_for_incoming_payment
payment_evidence_submitted
waiting_for_bank_statement
needs_review
incoming_payment_partially_confirmed
incoming_payment_confirmed
manager_approval_required
ready_for_dispatch
dispatched
received_by_trader
settled_or_offset
closed
rejected
cancelled
```

---

# 8. Permission Naming

Permissions use stable lowercase dot notation.

Examples:

```text
admin_user.read
admin_user.manage
role.read
role.manage
trader.read
trader.create
trader.approve
trader.suspend
beneficiary.read
beneficiary.manage
payment_request.create
payment_request.read
payment_request.review
payment_request.request_correction
payment_request.mark_eligible
payment_request.cancel
payment_batch.create
payment_batch.version.create
payment_batch.version.finalize
payment_batch.approve
payment_batch.reject
bank_export.preview
bank_export.generate_final
bank_export.download
bank_export.mark_sent
payment_attempt.read
payment_attempt.confirm_paid
payment_attempt.confirm_failed
payment_attempt.retry
bank_result_bundle.upload
bank_result_bundle.review
receipt_segment.create
receipt_segment.crop
receipt_segment.update
matching.suggest
matching.confirm_link
matching.replace_link
payment_result.publish
payment_result.correct
bank_statement.upload
incoming_payment.match
incoming_payment.confirm
gold_sale.price
gold_dispatch.create
settings.bank.read
settings.bank.manage
settings.feature_flags.manage
retention.read
retention.propose
audit.read
system.health.read
```

A role may hold multiple permissions. The API checks permissions, ownership, resource state, and scope.

---

# 9. Endpoint Group Overview

| Group | Prefix | Audience | Phase |
|---|---|---|---|
| Authentication | `/auth` | All users | 1A |
| Admin users/RBAC | `/admin-users`, `/roles`, `/permissions` | Internal | 1A |
| Traders | `/traders`, `/me/trader` | Internal/Trader | 1A |
| Beneficiaries | `/beneficiaries` | Internal/Trader | 1A |
| Files | `/files` | Authorized | 1A |
| Gold sales | `/gold-sale-orders` | Internal/Trader | 1A |
| Incoming receipts | `/incoming-payment-receipts` | Internal/Trader | 1A |
| Bank statements | `/bank-statements` | Internal | 1A |
| Payment requests | `/payment-requests` | Internal/Trader | 1A |
| Payment batches/versions | `/payment-batches` | Internal | 1A |
| Bank exports | `/bank-exports` | Internal | 1A |
| Payment attempts | `/payment-attempts` | Internal; trader-safe nested views | 1A |
| Bank result bundles | `/bank-result-bundles` | Internal | 1A |
| Receipt segments/evidence | `/receipt-segments`, `/evidence-links` | Internal | 1A |
| Result publications | `/payment-requests/{id}/publications` | Internal/Trader | 1A |
| Manual review | `/manual-review-tasks` | Internal | 1A |
| Notifications | `/notifications` | All users | 1A |
| Reports | `/reports` | Internal | 1A |
| Bank configuration | `/bank-profiles`, `/bank-profile-versions`, `/bank-mappings` | Internal | 1A |
| Settings/retention | `/settings`, `/retention-policies`, `/legal-holds` | Internal | 1A/governance |
| Audit | `/audit-logs` | Authorized internal | 1A |
| Processing jobs | `/processing-jobs` | Internal | 1A |
| AI/OCR | `/ai` | Internal | 1B+ |
| Health | `/health` | DevOps/internal | 1A |

---

## 9.1 Resource-to-Persistence Mapping

The HTTP resource model maps to the version 1.1 database schema as follows. This is not permission to expose tables directly.

| API resource/command area | Primary persistence tables |
|---|---|
| Authentication/session | `admin_users`, `trader_users`, `auth_sessions`, `auth_events` |
| Trader/beneficiary | `traders`, `beneficiaries`, `trader_bank_accounts` |
| Files | `file_objects`, `file_links`, `file_derivations` |
| Payment request | `payment_requests`, `payment_request_revisions` |
| Payment execution | `payment_attempts` |
| Batch/approval/export | `payment_batches`, `payment_batch_versions`, `payment_batch_items`, `batch_approvals`, `bank_excel_exports` |
| Bank result/evidence | `bank_result_bundles`, `bank_result_bundle_files`, `bank_result_bundle_batch_links`, `receipt_segments`, `matching_candidates`, `confirmed_evidence_links` |
| Trader result | `payment_result_publications` |
| Incoming payment | `gold_sale_orders`, `gold_sale_pricing_versions`, `incoming_payment_receipts`, `bank_statement_files`, `bank_statement_import_runs`, `bank_statement_rows`, `incoming_payment_matches`, `gold_dispatches` |
| Operations | `manual_review_tasks`, `comments`, `notifications`, `processing_jobs` |
| Integrity/governance | `idempotency_records`, `outbox_events`, `audit_logs`, `retention_policies`, `legal_holds` |
| Bank configuration | `bank_profiles`, `bank_profile_versions`, `bank_accounts`, `bank_mappings` |

Polymorphic queue/comment references are navigation aids. Authoritative financial relationships use explicit foreign-key-backed tables.

---

# 10. Authentication and Session API

This section is transport-neutral until `ADR-001` is approved. Cookie-based browser sessions are the preferred baseline.

## 10.1 Login

```http
POST /api/v1/auth/login
```

Request:

```json
{
  "identifier": "accountant1",
  "password": "string",
  "user_type": "admin"
}
```

`user_type`: `admin` or `trader`.

Response `200`:

```json
{
  "session": {
    "id": "uuid",
    "expires_at": "2026-07-18T17:15:21Z",
    "authentication_level": "normal"
  },
  "user": {
    "id": "uuid",
    "user_type": "admin",
    "display_name": "Accountant User",
    "status": "active",
    "roles": ["accountant"],
    "permissions": ["payment_request.review"]
  }
}
```

For cookie auth, session credentials are set through secure cookies and are not returned as raw refresh tokens in JSON.

Rules:

- generic invalid-credential message;
- rate limiting and progressive delay/temporary lock;
- failed/successful events audited in `auth_events`;
- pending/suspended/blocked trader has only the limited response allowed by policy;
- deactivated internal users cannot create a session.

## 10.2 Current session/user

```http
GET /api/v1/auth/me
```

Returns session, actor profile, roles, permissions, and own `trader_id` when applicable.

## 10.3 Logout current session

```http
POST /api/v1/auth/logout
```

Idempotent by definition; revokes the current server-side session.

## 10.4 List own sessions

```http
GET /api/v1/auth/sessions
```

## 10.5 Revoke one own session

```http
POST /api/v1/auth/sessions/{session_id}/revoke
```

## 10.6 Reauthenticate for critical action

```http
POST /api/v1/auth/reauthenticate
```

Request:

```json
{
  "password": "string",
  "purpose": "payment_batch_approval"
}
```

Response:

```json
{
  "recent_auth_reference": "opaque",
  "expires_at": "2026-07-18T09:20:21Z",
  "authentication_level": "recent_password"
}
```

The reference is short-lived and purpose-bound.

## 10.7 Change password

```http
POST /api/v1/auth/change-password
```

Changing a password revokes other sessions according to security policy.

## 10.8 Admin reset initiation

```http
POST /api/v1/admin-users/{admin_user_id}/password-reset
```

An administrator may initiate a reset but must not retrieve or view the user's current password.

---

# 11. Admin Users and RBAC API

## 11.1 Endpoint catalog

| Method | Path | Permission | Concurrency |
|---|---|---|---|
| GET | `/admin-users` | `admin_user.read` | none |
| POST | `/admin-users` | `admin_user.manage` | idempotency required |
| GET | `/admin-users/{id}` | `admin_user.read` | none |
| PATCH | `/admin-users/{id}` | `admin_user.manage` | `If-Match` required |
| POST | `/admin-users/{id}/suspend` | `admin_user.manage` | `If-Match` + idempotency |
| POST | `/admin-users/{id}/reactivate` | `admin_user.manage` | `If-Match` + idempotency |
| GET | `/roles` | `role.read` | none |
| GET | `/permissions` | `role.read` | none |
| POST | `/roles` | `role.manage` | idempotency required |
| PUT | `/roles/{id}/permissions` | `role.manage` | `If-Match` + idempotency |

Role changes, suspension, and reactivation create audit and outbox events. Technical administrators do not receive financial approval permissions by default.

---

# 12. Traders and Trader Self-Service API

## 12.1 Trader management

| Method | Path | Audience/permission |
|---|---|---|
| GET | `/traders` | internal `trader.read` |
| POST | `/traders` | internal `trader.create` |
| POST | `/traders/register` | public, rate-limited |
| GET | `/traders/{id}` | internal `trader.read` |
| PATCH | `/traders/{id}` | internal, `If-Match` |
| POST | `/traders/{id}/approve` | `trader.approve`, idempotent |
| POST | `/traders/{id}/reject` | `trader.approve`, reason required |
| POST | `/traders/{id}/suspend` | `trader.suspend`, reason required |
| POST | `/traders/{id}/reactivate` | `trader.suspend` |

The API must not expose a mutable `balance_irr` field unless a separately approved ledger/balance model exists.

## 12.2 Trader approval example

```http
POST /api/v1/traders/{trader_id}/approve
Idempotency-Key: ...
If-Match: "rv-2"
```

```json
{
  "reason": "Identity and business relationship verified."
}
```

## 12.3 Trader self-service

| Method | Path | Purpose |
|---|---|---|
| GET | `/me/trader/profile` | own profile |
| PATCH | `/me/trader/profile` | allowed non-sensitive fields, `If-Match` |
| GET | `/me/trader/dashboard` | own operational summary |
| GET | `/me/trader/payment-requests` | own requests |
| GET | `/me/trader/gold-sale-orders` | own orders |
| GET | `/me/trader/publications` | own published results |

Phone/login changes require a controlled identity workflow, not a normal profile patch.

---

# 13. Beneficiary API

Beneficiaries are reusable trader-owned records. They are not users and do not own payment amounts.

## 13.1 Endpoints

| Method | Path | Rules |
|---|---|---|
| GET | `/beneficiaries` | trader sees own; internal may filter by trader |
| POST | `/beneficiaries` | normalizes fields, warns on duplicates |
| GET | `/beneficiaries/{id}` | ownership/permission enforced |
| PATCH | `/beneficiaries/{id}` | `If-Match`; historical snapshots unchanged |
| POST | `/beneficiaries/{id}/block` | internal permission, reason required |
| POST | `/beneficiaries/{id}/reactivate` | internal permission |

Create request:

```json
{
  "trader_id": "uuid-only-for-internal-actor",
  "full_name": "Ali Example",
  "iban": "IR000000000000000000000000",
  "national_id": null,
  "phone_number": null,
  "notes": null
}
```

Response may include duplicate warnings. It never auto-merges records.

---

# 14. File API

## 14.1 Principles

- Binary objects are private.
- Storage keys are never returned to normal clients.
- Upload purpose determines type/size rules.
- Files may remain `pending` or `quarantined` until validation completes.
- Original files are immutable after becoming available.
- Derived preview/crop/share files reference the source through `file_derivations`.
- No normal hard-delete endpoint exists.

## 14.2 Upload generic attachment

```http
POST /api/v1/files
Content-Type: multipart/form-data
```

Fields:

```text
file
purpose
client_filename_optional
```

Allowed Phase 1A purposes:

```text
payment_request_source
incoming_payment_receipt
bank_statement
bank_result_bundle_source
gold_dispatch_evidence
manual_external_evidence
misc_internal
```

Response `201` or `202`:

```json
{
  "id": "uuid",
  "status": "pending",
  "original_filename": "receipt.jpg",
  "mime_type": "image/jpeg",
  "size_bytes": 123456,
  "sha256": null,
  "processing_job_id": "uuid-or-null"
}
```

A pending/quarantined file cannot be used in a final financial command.

## 14.3 File metadata

```http
GET /api/v1/files/{file_id}
```

Returns public metadata and allowed actions, never the storage key.

## 14.4 Secure download

```http
GET /api/v1/files/{file_id}/download
```

The server:

1. resolves linked domain ownership;
2. enforces actor permission/ownership;
3. checks file status and visibility;
4. streams the file or issues a short-lived signed URL;
5. adds cache/privacy headers appropriate to sensitive data.

## 14.5 Preview

```http
GET /api/v1/files/{file_id}/preview
GET /api/v1/files/{file_id}/pages/{page_number}/preview
```

Preview endpoints are authorized separately from original downloads. A trader cannot preview an internal mixed bundle.

## 14.6 File integrity status

```http
GET /api/v1/files/{file_id}/integrity
```

Internal-only endpoint returning checksum/availability/derivation status. It is useful for support and restore validation.

---

# 15. Payment Request and Revision API

A payment request is the stable aggregate. Financial content lives in immutable revisions.

## 15.1 List requests

```http
GET /api/v1/payment-requests
```

Filters:

```text
status, trader_id, beneficiary_id, beneficiary_search,
amount_min_irr, amount_max_irr, created_from, created_to,
submitted_from, submitted_to, bank_profile_id, has_dispute
```

Trader scope is always inferred.

## 15.2 Create draft request and revision 1

```http
POST /api/v1/payment-requests
Idempotency-Key: ...
```

Request:

```json
{
  "beneficiary_id": "uuid",
  "amount": {
    "value": 3440000000,
    "unit": "TOMAN",
    "amount_irr": 34400000000
  },
  "description": "Retail gold seller settlement",
  "source_attachment_file_id": null
}
```

Response `201`:

```json
{
  "id": "uuid",
  "request_number": "PR-14050427-0001",
  "status": "draft",
  "record_version": 1,
  "current_revision": {
    "id": "uuid",
    "revision_number": 1,
    "content_hash": "sha256",
    "beneficiary_snapshot": {
      "full_name": "Ali Example",
      "iban": "IR000000000000000000000000",
      "national_id": null
    },
    "amount_irr": 34400000000,
    "entered_amount": {"value": 3440000000, "unit": "TOMAN"}
  },
  "warnings": []
}
```

The server resolves and snapshots beneficiary data. The client cannot provide a beneficiary name that conflicts with the selected beneficiary without an explicit revision/create-beneficiary path.

## 15.3 Get request

```http
GET /api/v1/payment-requests/{request_id}
```

Includes current revision, aggregate state, attempts, current publication summary, warnings, record version, and allowed actions. Trader responses omit internal-only data.

## 15.4 List revisions

```http
GET /api/v1/payment-requests/{request_id}/revisions
```

## 15.5 Create a new draft/correction revision

```http
POST /api/v1/payment-requests/{request_id}/revisions
Idempotency-Key: ...
If-Match: "rv-3"
```

Request:

```json
{
  "beneficiary_id": "uuid",
  "amount": {
    "value": 34400000000,
    "unit": "IRR",
    "amount_irr": 34400000000
  },
  "description": "Corrected by trader",
  "source_attachment_file_id": null,
  "revision_reason": "Corrected IBAN after center request."
}
```

Rules:

- allowed in `draft` or `needs_trader_correction` for trader;
- internal material correction uses explicit permission;
- inserts a new immutable revision;
- updates `current_revision_id` transactionally;
- invalidates affected unsent batch versions/approvals;
- never changes historical attempts or exports.

## 15.6 Submit request

```http
POST /api/v1/payment-requests/{request_id}/submit
Idempotency-Key: ...
If-Match: "rv-4"
```

```json
{
  "expected_revision_id": "uuid",
  "note": "Ready for center review."
}
```

The command rejects a stale/non-current revision.

## 15.7 Start accountant review

```http
POST /api/v1/payment-requests/{request_id}/start-review
```

Requires `payment_request.review`, idempotency, and `If-Match`.

## 15.8 Request trader correction

```http
POST /api/v1/payment-requests/{request_id}/request-correction
```

```json
{
  "reason_code": "invalid_iban",
  "message_to_trader": "Please correct the destination IBAN.",
  "internal_note": null
}
```

Reason and trader notification are required.

## 15.9 Mark eligible for batching

```http
POST /api/v1/payment-requests/{request_id}/mark-eligible-for-batching
```

This is accountant review completion. It is not manager approval.

Request:

```json
{
  "review_note": "Validated beneficiary, IBAN, and amount.",
  "expected_revision_id": "uuid"
}
```

## 15.10 Cancel request

```http
POST /api/v1/payment-requests/{request_id}/cancel
```

- Trader may cancel only before active batch allocation.
- Internal cancellation after allocation uses controlled invalidation/correction.
- Executed attempts are never erased.

## 15.11 Structured bulk draft creation

Optional Phase 1B or Phase 1A enhancement:

```http
POST /api/v1/payment-requests/bulk-drafts
```

This accepts structured JSON, not an uploaded spreadsheet as the primary workflow. Each item has its own idempotency sub-key and validation result.

---

# 16. Payment Batch, Version, Approval, and Export API

## 16.1 Batch flow

```text
preview selection
  -> create batch container + draft version
  -> modify by creating/replacing draft version
  -> finalize exact version
  -> manager approve/reject exact version
  -> generate final export from approved version
  -> authorized download
  -> mark exact export sent to bank
```

## 16.2 Selection preview

```http
POST /api/v1/payment-batches/preview
```

Request:

```json
{
  "items": [
    {
      "payment_request_id": "uuid",
      "expected_revision_id": "uuid",
      "expected_record_version": 5
    }
  ],
  "bank_profile_version_id": "uuid",
  "bank_account_id": "uuid",
  "bank_mapping_id": "uuid",
  "apply_split_rules": true
}
```

Response:

```json
{
  "proposed_rows": [
    {
      "source_request_id": "uuid",
      "source_revision_id": "uuid",
      "row_order": 1,
      "amount_irr": 2000000000,
      "beneficiary_name": "Ali Example",
      "beneficiary_iban": "IR000000000000000000000000",
      "split_reason": "bank_limit_after_cutoff"
    }
  ],
  "row_count": 3,
  "total_amount_irr": 4500000000,
  "validation": {
    "errors": [],
    "warnings": []
  }
}
```

Preview is advisory and not approvable. The create command revalidates everything.

## 16.3 Create batch and draft version

```http
POST /api/v1/payment-batches
Idempotency-Key: ...
```

Request uses the same selection/configuration contract as preview.

Response `201`:

```json
{
  "batch": {
    "id": "uuid",
    "batch_number": "PB-14050427-0001",
    "status": "draft",
    "record_version": 1
  },
  "current_version": {
    "id": "uuid",
    "version_number": 1,
    "status": "draft",
    "row_count": 3,
    "total_amount_irr": 4500000000,
    "content_hash": "sha256",
    "validation_summary": {"errors": [], "warnings": []}
  }
}
```

The transaction creates attempts, batch version, ordered items, audit, outbox, and idempotency result atomically.

## 16.4 Get batch

```http
GET /api/v1/payment-batches/{batch_id}
```

Includes current version, historical versions, approval summary, exports, result progress, record version, and allowed actions.

## 16.5 Create a replacement draft version

```http
POST /api/v1/payment-batches/{batch_id}/versions
Idempotency-Key: ...
If-Match: "rv-2"
```

Creates a new version. It never edits an approved/finalized version. Previous operational approval becomes historical and the batch status becomes `approval_invalidated` or `draft` as applicable.

## 16.6 Finalize version for approval

```http
POST /api/v1/payment-batches/{batch_id}/versions/{version_id}/finalize
Idempotency-Key: ...
If-Match: "rv-3"
```

Request:

```json
{
  "note": "Validated and ready for manager review."
}
```

Server verifies:

- version belongs to batch and is current;
- no blocking validation errors;
- rows/totals/hash are internally consistent;
- selected request revisions remain current and eligible;
- attempts have no conflicting active allocation;
- bank configuration versions are active/allowed.

The version becomes immutable `ready_for_approval`.

## 16.7 Get manager approval view

```http
GET /api/v1/payment-batches/{batch_id}/versions/{version_id}/approval-view
```

Manager response includes:

- batch and version numbers;
- exact bank and source account;
- row count and total IRR/Toman helper;
- ordered rows;
- warnings and exceptions;
- content hash;
- creator and timestamps;
- prior decision if any.

## 16.8 Approve exact version

```http
POST /api/v1/payment-batches/{batch_id}/versions/{version_id}/approve
Idempotency-Key: ...
X-Recent-Auth: ...
```

Request:

```json
{
  "expected_content_hash": "sha256",
  "approval_note": "Approved for bank submission."
}
```

Response:

```json
{
  "approval": {
    "id": "uuid",
    "decision": "approved",
    "payment_batch_version_id": "uuid",
    "approved_content_hash": "sha256",
    "decided_at": "2026-07-18T09:15:21Z"
  },
  "batch_status": "approved"
}
```

No `If-Match` is needed for the immutable version itself, but the server verifies it remains the batch's current version. The command is blocked when the content hash differs.

## 16.9 Reject exact version

```http
POST /api/v1/payment-batches/{batch_id}/versions/{version_id}/reject
Idempotency-Key: ...
X-Recent-Auth: ...
```

```json
{
  "reason_code": "beneficiary_review_required",
  "reason": "One row must be corrected before approval."
}
```

Rejection reason is mandatory.

## 16.10 Generate preview export

```http
POST /api/v1/payment-batches/{batch_id}/versions/{version_id}/exports/preview
Idempotency-Key: ...
```

Preview may be generated before approval and must be visibly marked non-sendable. Response is `202` when worker processing is used.

## 16.11 Generate final export

```http
POST /api/v1/payment-batches/{batch_id}/versions/{version_id}/exports/final
Idempotency-Key: ...
```

Request:

```json
{
  "batch_approval_id": "uuid"
}
```

The server verifies version/approval/hash/mapping/account/totals and queues deterministic generation.

Response `202`:

```json
{
  "processing_job_id": "uuid",
  "export": {
    "id": "uuid",
    "export_type": "final",
    "status": "generating"
  }
}
```

## 16.12 Get export

```http
GET /api/v1/bank-exports/{export_id}
```

## 16.13 Download final export

```http
GET /api/v1/bank-exports/{export_id}/download
```

Before every final download, the server revalidates export integrity. A mismatch quarantines the export and returns `409 EXPORT_INTEGRITY_MISMATCH`.

## 16.14 Mark exact export sent to bank

```http
POST /api/v1/bank-exports/{export_id}/mark-sent-to-bank
Idempotency-Key: ...
If-Match: "rv-5"
```

Request:

```json
{
  "sent_at": "2026-07-18T09:30:00Z",
  "submission_channel": "bank_portal_manual_upload",
  "note": "Uploaded manually to the bank portal."
}
```

Only a valid final export may be marked sent. Related attempts move to `sent_to_bank`/`bank_result_pending` atomically.

## 16.15 Cancel batch

```http
POST /api/v1/payment-batches/{batch_id}/cancel
```

Cancellation before sending invalidates operational use of unsent versions/exports. After bank submission, use reconciliation/correction commands; executed attempts do not disappear.

---

# 17. Payment Attempt API

Clients do not create arbitrary normal/split attempts directly. Batch and retry domain services create them.

## 17.1 List/get attempts

```http
GET /api/v1/payment-attempts
GET /api/v1/payment-attempts/{attempt_id}
```

Filters include request, batch version, export, trader, status, amount, IBAN, tracking number, and result date.

Trader-facing request details may include safe attempt summaries but never internal bundle/evidence details not published.

## 17.2 Confirm paid

```http
POST /api/v1/payment-attempts/{attempt_id}/confirm-paid
Idempotency-Key: ...
If-Match: "rv-4"
```

Request:

```json
{
  "bank_tracking_number": "123456789",
  "bank_result_at": "2026-07-18T08:45:00Z",
  "primary_evidence_link_id": "uuid-or-null",
  "evidence_unavailable_reason": null,
  "confirmation_note": "Visually verified against bank result."
}
```

Rules:

- human accountant/authorized manager only;
- attempt must have been sent or be in an explicitly approved reconciliation path;
- evidence link must be active and point to the same attempt;
- when no evidence exists, a reason may be required by policy;
- request aggregate is recalculated under lock;
- overpayment creates a reconciliation task and blocks normal `paid` closure;
- audit, outbox, and idempotency result commit atomically.

## 17.3 Confirm failed

```http
POST /api/v1/payment-attempts/{attempt_id}/confirm-failed
Idempotency-Key: ...
If-Match: "rv-4"
```

```json
{
  "failure_code": "bank_rejected",
  "failure_reason": "Bank rejected this row.",
  "receipt_segment_id": "uuid-or-null"
}
```

## 17.4 Mark retry required

```http
POST /api/v1/payment-attempts/{attempt_id}/mark-retry-required
```

Reason required. This does not itself create or send a retry.

## 17.5 Create retry attempt

```http
POST /api/v1/payment-attempts/{attempt_id}/retry
Idempotency-Key: ...
If-Match: "rv-5"
```

Request:

```json
{
  "payment_request_revision_id": "uuid",
  "amount_irr": 2000000000,
  "reason": "Retry using corrected current request revision."
}
```

The server rejects free-form beneficiary/IBAN changes. Material beneficiary changes must exist in the referenced request revision. The retry attempt remains unbatched until included in a future batch version.

---

# 18. Bank Result Bundle API

## 18.1 Upload bundle

```http
POST /api/v1/bank-result-bundles
Idempotency-Key: ...
Content-Type: multipart/form-data
```

Fields:

```text
files: one or more source files
bank_profile_id: optional
related_payment_batch_ids: optional repeated UUID
received_at: optional timestamp
notes: optional
```

Response `201/202`:

```json
{
  "id": "uuid",
  "bundle_number": "BRB-14050427-0001",
  "status": "uploaded",
  "files": [
    {"file_id": "uuid", "status": "pending"}
  ],
  "processing_job_ids": ["uuid"]
}
```

Mixed or unknown bundles are accepted. Original files are preserved.

## 18.2 List/get bundle

```http
GET /api/v1/bank-result-bundles
GET /api/v1/bank-result-bundles/{bundle_id}
```

Detail response contains source files, authorized preview endpoints, page information, segment counts, linked batches/versions, unresolved tasks, record version, and allowed actions.

## 18.3 Link bundle to batch/version context

```http
POST /api/v1/bank-result-bundles/{bundle_id}/batch-links
```

This association is operational context only and does not prove payment completion.

## 18.4 Start manual review

```http
POST /api/v1/bank-result-bundles/{bundle_id}/start-review
If-Match: "rv-2"
```

## 18.5 Close bundle

```http
POST /api/v1/bank-result-bundles/{bundle_id}/close
Idempotency-Key: ...
If-Match: "rv-5"
```

Request:

```json
{
  "resolution_note": "All relevant content resolved or explicitly classified.",
  "unresolved_dispositions": [
    {"segment_id": "uuid", "disposition": "unknown_with_reason", "reason": "No related system request."}
  ]
}
```

The API does not silently discard unmatched content.

## 18.6 Queue optional OCR/AI

```http
POST /api/v1/bank-result-bundles/{bundle_id}/ai-extraction
```

Phase 1B+. Returns `202`; failure falls back to manual review.

---

# 19. Receipt Segment, Matching Candidate, and Evidence Link API

## 19.1 Create external manual evidence segment

```http
POST /api/v1/bank-result-bundles/{bundle_id}/receipt-segments/external
Idempotency-Key: ...
```

Request references an already available uploaded file and optional manually entered fields.

```json
{
  "source_file_id": "uuid",
  "segment_file_id": "uuid",
  "page_number": 1,
  "manual_fields": {
    "beneficiary_name": "Ali Example",
    "destination_iban": "IR000000000000000000000000",
    "amount_irr": 2000000000,
    "tracking_number": "123456"
  }
}
```

## 19.2 Create Phase 1A in-panel crop

```http
POST /api/v1/bank-result-bundles/{bundle_id}/receipt-segments/crop
Idempotency-Key: ...
```

Request:

```json
{
  "bank_result_bundle_file_id": "uuid",
  "source_file_id": "uuid",
  "page_number": 1,
  "bbox": {
    "x": "0.105000",
    "y": "0.220000",
    "width": "0.790000",
    "height": "0.160000"
  },
  "client_source_dimensions": {
    "width": 1600,
    "height": 2200
  },
  "manual_fields": {
    "amount_irr": 2000000000,
    "beneficiary_name": "Ali Example",
    "destination_iban": "IR000000000000000000000000",
    "tracking_number": "123456"
  }
}
```

Coordinates are normalized from 0 to 1. The server verifies bounds and source/page identity. Crop generation may return `202` with a processing job. The source file remains immutable.

## 19.3 Get/update segment

```http
GET /api/v1/receipt-segments/{segment_id}
PATCH /api/v1/receipt-segments/{segment_id}
```

Patch is allowed only before finalization/active confirmed link and requires `If-Match`. Provenance fields and source coordinates cannot be rewritten after finalization; a replacement segment is created instead.

## 19.4 Suggest matches

```http
POST /api/v1/receipt-segments/{segment_id}/matching-candidates
```

Phase 1B automation or Phase 1A rule/manual assistance. Response candidates are advisory.

## 19.5 Accept candidate for confirmation

```http
POST /api/v1/matching-candidates/{candidate_id}/accept-for-confirmation
```

This does not mark an attempt paid.

## 19.6 Reject candidate

```http
POST /api/v1/matching-candidates/{candidate_id}/reject
```

Reason required when rejecting a high-confidence candidate or overriding a previously accepted candidate.

## 19.7 Create confirmed evidence link

```http
POST /api/v1/evidence-links
Idempotency-Key: ...
```

Request:

```json
{
  "payment_attempt_id": "uuid",
  "receipt_segment_id": "uuid",
  "link_type": "primary",
  "confirmation_note": "Matched by visual verification of amount, IBAN, and tracking number."
}
```

The command enforces one active primary link per attempt and one active primary attempt per segment.

## 19.8 Replace primary evidence link

```http
POST /api/v1/evidence-links/{link_id}/replace
Idempotency-Key: ...
```

```json
{
  "new_receipt_segment_id": "uuid",
  "replacement_reason": "Previous segment belonged to another transaction."
}
```

In one transaction the old link becomes `replaced`, the new link becomes active, affected publication state is recalculated, and audit/outbox events are created. When a published result materially changes, a corrected publication and trader notification are required.

## 19.9 Void supplementary link

```http
POST /api/v1/evidence-links/{link_id}/void
```

Reason required. Primary links use the replacement/correction workflow unless the entire result is formally revoked.

---

# 20. Trader Result Publication API

Trader-visible results are immutable publications. A receipt segment is not independently "published" as workflow truth.

## 20.1 Preview publication

```http
POST /api/v1/payment-requests/{request_id}/publications/preview
```

Response shows the exact safe fields and evidence proposed for the trader. It is not persisted as active publication.

## 20.2 Publish result

```http
POST /api/v1/payment-requests/{request_id}/publications
Idempotency-Key: ...
If-Match: "rv-9"
```

Request:

```json
{
  "primary_evidence_link_id": "uuid-or-null",
  "include_share_file": true,
  "share_format": "image",
  "message_to_trader": "Payment result is available."
}
```

The server derives amount, beneficiary, attempts, status, bank, tracking, and dates from authoritative records. The client cannot submit arbitrary financial summary values.

Response may be `201` or `202` if share-file generation is asynchronous.

## 20.3 List publication history/current publication

```http
GET /api/v1/payment-requests/{request_id}/publications
GET /api/v1/payment-requests/{request_id}/publications/current
```

Internal users see history subject to permission. Trader endpoints expose only own active publication and allowed historical correction notices.

## 20.4 Trader view/download

```http
GET /api/v1/me/trader/payment-requests/{request_id}/publication
GET /api/v1/me/trader/publications/{publication_id}/share-file
```

## 20.5 Trader acknowledgment

```http
POST /api/v1/me/trader/payment-requests/{request_id}/acknowledge-result
Idempotency-Key: ...
If-Match: "rv-10"
```

## 20.6 Trader dispute

```http
POST /api/v1/me/trader/payment-requests/{request_id}/dispute-result
Idempotency-Key: ...
If-Match: "rv-10"
```

```json
{
  "reason_code": "beneficiary_did_not_receive",
  "description": "The recipient reports that payment has not arrived.",
  "attachment_file_ids": []
}
```

A dispute creates a visible manual review task and does not automatically reverse bank facts.

---

# 21. Gold Sale and Incoming Payment API

## 21.1 Gold sale endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/gold-sale-orders` | scoped list |
| POST | `/gold-sale-orders` | create draft/order |
| GET | `/gold-sale-orders/{id}` | details/allowed actions |
| POST | `/gold-sale-orders/{id}/submit` | trader/admin submit |
| POST | `/gold-sale-orders/{id}/pricing-versions` | create immutable price snapshot |
| POST | `/gold-sale-orders/{id}/request-payment` | publish expected amount/instructions |
| POST | `/gold-sale-orders/{id}/cancel` | controlled cancellation |
| POST | `/gold-sale-orders/{id}/close` | closure guards |

Gold weight uses a string decimal and explicit unit:

```json
{
  "gold_weight": "125.500000",
  "weight_unit": "GRAM",
  "gold_purity": "18K"
}
```

## 21.2 Pricing version

```http
POST /api/v1/gold-sale-orders/{order_id}/pricing-versions
Idempotency-Key: ...
If-Match: "rv-2"
```

Stores exact amount provenance and does not overwrite earlier pricing versions.

## 21.3 Upload incoming payment receipt

```http
POST /api/v1/gold-sale-orders/{order_id}/incoming-payment-receipts
Idempotency-Key: ...
```

Request may reference an available file and structured fields. Uploading evidence never confirms payment.

## 21.4 Bank statement upload and import runs

```http
POST /api/v1/bank-statements
GET  /api/v1/bank-statements
GET  /api/v1/bank-statements/{statement_id}
POST /api/v1/bank-statements/{statement_id}/import-runs
GET  /api/v1/bank-statements/{statement_id}/import-runs/{run_id}/rows
```

Each parse/reparse creates a new immutable import run. Rows are not overwritten.

## 21.5 Match receipt to statement row

```http
POST /api/v1/incoming-payment-receipts/{receipt_id}/matches
Idempotency-Key: ...
```

Candidate acceptance and financial confirmation remain separate.

## 21.6 Confirm incoming payment

```http
POST /api/v1/incoming-payment-receipts/{receipt_id}/confirm
Idempotency-Key: ...
If-Match: "rv-3"
```

```json
{
  "incoming_payment_match_id": "uuid-or-null",
  "confirmed_amount_irr": 85000000000,
  "confirmation_note": "Verified against bank statement row."
}
```

Partial, excess, or ambiguous amounts produce explicit order state/review tasks. They are not silently treated as fully paid.

## 21.7 Dispatch or settlement

```http
POST /api/v1/gold-sale-orders/{order_id}/dispatches
Idempotency-Key: ...
If-Match: "rv-6"
```

```json
{
  "dispatch_type": "physical_dispatch",
  "gold_weight": "125.500000",
  "weight_unit": "GRAM",
  "gold_purity": "18K",
  "recipient_name": "Trader representative",
  "dispatched_at": "2026-07-18T11:00:00Z",
  "evidence_file_ids": []
}
```

Supported types include `physical_dispatch`, `physical_receipt`, `offset_settlement`, and `manual_settlement`. Payment/override guards are enforced server-side.

---

# 22. Manual Review, Comments, and Notifications API

## 22.1 Manual review tasks

```http
GET  /api/v1/manual-review-tasks
GET  /api/v1/manual-review-tasks/{task_id}
POST /api/v1/manual-review-tasks/{task_id}/assign
POST /api/v1/manual-review-tasks/{task_id}/start
POST /api/v1/manual-review-tasks/{task_id}/resolve
POST /api/v1/manual-review-tasks/{task_id}/cancel
```

Assignment/start/resolve/cancel require `If-Match`; sensitive resolution commands require idempotency. The API cannot resolve a task without an explicit disposition/reason when the underlying item remains unresolved.

## 22.2 Structured comments

```http
GET  /api/v1/{resource}/{id}/comments
POST /api/v1/{resource}/{id}/comments
```

Comments are structured notes, not real-time chat. Scope is `internal` or `trader_visible`. Normal users cannot hard-delete financial comments; corrections use supersession/audit.

## 22.3 Notifications

```http
GET  /api/v1/notifications
POST /api/v1/notifications/{notification_id}/mark-read
POST /api/v1/notifications/mark-all-read
```

Notifications are deduplicated from outbox events and are not workflow truth.

---

# 23. Bank Configuration API

Bank operational configuration is versioned. Used versions are immutable.

## 23.1 Profiles

```http
GET  /api/v1/bank-profiles
POST /api/v1/bank-profiles
GET  /api/v1/bank-profiles/{profile_id}
PATCH /api/v1/bank-profiles/{profile_id}
```

Profile patch changes display/active metadata only; operational rules live in versions.

## 23.2 Profile versions

```http
GET  /api/v1/bank-profiles/{profile_id}/versions
POST /api/v1/bank-profiles/{profile_id}/versions
GET  /api/v1/bank-profile-versions/{version_id}
POST /api/v1/bank-profile-versions/{version_id}/activate
POST /api/v1/bank-profile-versions/{version_id}/retire
```

A version contains transfer channels, cutoff logic, split rules, permitted file types, and other bank behavior.

## 23.3 Mappings/templates

```http
GET  /api/v1/bank-profile-versions/{version_id}/mappings
POST /api/v1/bank-profile-versions/{version_id}/mappings
GET  /api/v1/bank-mappings/{mapping_id}
POST /api/v1/bank-mappings/{mapping_id}/activate
```

Activation is a critical audited command. A mapping already used by a finalized batch version/export cannot be edited.

## 23.4 Source bank accounts

```http
GET  /api/v1/bank-accounts
POST /api/v1/bank-accounts
PATCH /api/v1/bank-accounts/{id}
POST /api/v1/bank-accounts/{id}/deactivate
```

Account numbers/IBANs are masked according to permission.

---

# 24. Settings, Retention, and Legal Hold API

## 24.1 General settings

```http
GET /api/v1/settings
```

Only safe, non-secret settings are returned. Secrets are never exposed through settings APIs.

Feature flag updates:

```http
PUT /api/v1/settings/feature-flags
```

Phase 1A `manual_crop.enabled` is on unless explicitly disabled due to a documented operational issue. AI/OCR/auto-segmentation remain off by default.

## 24.2 Retention policy

```http
GET  /api/v1/retention-policies
POST /api/v1/retention-policies/proposals
POST /api/v1/retention-policies/{id}/approve
POST /api/v1/retention-policies/{id}/activate
```

A simple technical-admin `PUT retention_years=...` is prohibited.

Reduction of retention requires business/legal approval, legal-hold checks, dry-run scope, audit, and backup coordination.

## 24.3 Legal holds

```http
GET  /api/v1/legal-holds
POST /api/v1/legal-holds
POST /api/v1/legal-holds/{id}/release
```

No Phase 1A public API physically deletes financial data.

---

# 25. Audit API

```http
GET /api/v1/audit-logs
GET /api/v1/audit-logs/{audit_id}
GET /api/v1/{resource}/{resource_id}/audit
```

Filters include event type, actor, resource, request ID, idempotency record, and date range.

Rules:

- append-only;
- no update/delete endpoints;
- authorization and redaction by field sensitivity;
- audit reads may themselves be security logged;
- trader users do not access audit APIs.

---

# 26. Processing Jobs API

A generic `processing-jobs` resource covers Phase 1A file/export/notification/report jobs and future AI work.

```http
GET  /api/v1/processing-jobs
GET  /api/v1/processing-jobs/{job_id}
POST /api/v1/processing-jobs/{job_id}/retry
POST /api/v1/processing-jobs/{job_id}/cancel
```

Retry is permitted only for retryable/dead-letter/fallback states and is itself idempotent.

Worker results are not accepted through unauthenticated public callback endpoints. Workers operate through the queue/database contract and service-level credentials where needed.

---

# 27. Reports API

Phase 1A reports are operational.

```http
GET /api/v1/reports/accountant-dashboard
GET /api/v1/reports/manager-dashboard
GET /api/v1/reports/trader-operations/{trader_id}
POST /api/v1/reports/payment-requests/exports
```

Large exports return `202` with a processing job and generated file. Report exports are permission-protected and audited.

Manager dashboard includes at minimum:

- batches/versions waiting for approval;
- total amount pending approval;
- bank/source-account context;
- validation warnings;
- failed/partial/reconciliation cases;
- unresolved disputes.

---

# 28. Health and Operations API

Canonical endpoints:

```http
GET /api/v1/health/live
GET /api/v1/health/ready
GET /api/v1/health/dependencies
GET /api/v1/health/workers
```

## 28.1 Liveness

Minimal process status, no dependency probing or secrets.

```json
{
  "status": "alive",
  "service": "backend-api",
  "version": "1.1.0"
}
```

## 28.2 Readiness

Checks only dependencies required to accept normal traffic.

```json
{
  "status": "ready",
  "checks": {
    "database": "ok",
    "redis": "ok",
    "storage": "ok"
  }
}
```

## 28.3 Dependencies

Internal/authorized endpoint with structured dependency status, latency, and last successful check. AI provider is reported only when enabled and is not required for Phase 1A readiness.

## 28.4 Workers

Internal/authorized endpoint reporting heartbeat by queue:

```json
{
  "workers": [
    {
      "name": "worker-1",
      "status": "running",
      "queues": ["files", "exports", "notifications"],
      "last_heartbeat_at": "2026-07-18T09:15:21Z"
    }
  ]
}
```

Public access to dependency details should be blocked by network policy or permission.

---

# 29. Idempotency Execution Contract

For a critical command:

1. authenticate and authorize actor;
2. require and normalize `Idempotency-Key`;
3. calculate canonical request hash including path/resource/command payload;
4. lock/create `idempotency_records` row;
5. if completed with same hash, replay sanitized logical response;
6. if key exists with different hash, return conflict;
7. execute command in one transaction;
8. persist business changes, audit, outbox, and idempotency response;
9. commit;
10. return response.

An abandoned `in_progress` record is recoverable only after `locked_until` and command-specific safety checks.

Do not use idempotency as a replacement for database constraints or row locks.

---

# 30. Concurrency and Locking Contract

## 30.1 Mutable aggregates

Use ETag/`If-Match` for:

- traders and users;
- beneficiaries;
- payment request aggregate;
- payment batch aggregate;
- payment attempts;
- bundles;
- manual review tasks;
- current settings/feature flags.

## 30.2 Immutable resources

Request revisions, batch versions, approvals, finalized exports, publications, and historical evidence links are addressed by ID/hash and are not patched.

## 30.3 Required server-side locks

Domain services lock the relevant rows for:

- split/retry attempt creation;
- batch membership/version finalization;
- manager decision;
- final export creation;
- sent-to-bank marking;
- payment confirmation/aggregate recalculation;
- evidence replacement;
- publication correction;
- incoming payment confirmation;
- dispatch authorization.

The API must never resolve concurrency solely in frontend state.

---

# 31. Authorization and Data-Shaping Contract

## 31.1 Not-found masking

For trader requests, a resource outside ownership scope generally returns `404 NOT_FOUND`, not a response revealing that the record exists.

## 31.2 Field-level shaping

Examples:

- full IBAN may be shown in the trader's own request input/review when operationally needed;
- shareable output may mask IBAN according to product policy;
- national ID is masked except to authorized internal roles;
- internal notes never appear in trader DTOs;
- bank source accounts are masked for roles without financial permission;
- audit before/after payloads are redacted by permission.

## 31.3 Technical admin

Technical admin access to configuration does not imply access to all financial files or approval actions.

## 31.4 Read-only user

Read-only roles never receive command endpoints in `allowed_actions`, and the backend denies all state-changing requests.

---

# 32. OpenAPI and Client Generation

FastAPI must generate OpenAPI from implementation DTOs, but this document remains the business contract.

Requirements:

- stable operation IDs;
- every endpoint documents permission, audience, idempotency, preconditions, and error codes;
- schemas separate trader and internal representations;
- generated TypeScript client/types checked into or produced for the monorepo build;
- CI detects breaking OpenAPI changes;
- examples use synthetic data only;
- OpenAPI docs are disabled or protected in production according to security policy.

Suggested operation ID convention:

```text
payment_requests_create
payment_requests_submit
payment_batches_create_version
payment_batch_versions_approve
bank_exports_generate_final
payment_attempts_confirm_paid
receipt_segments_create_crop
payment_results_publish
```

---

# 33. Phase 1A Required Endpoint Minimum

Required:

```text
/auth/login
/auth/me
/auth/logout
/auth/reauthenticate

/admin-users
/roles
/permissions
/traders
/me/trader
/beneficiaries
/files

/payment-requests
/payment-requests/{id}/revisions
/payment-requests/{id}/submit
/payment-requests/{id}/start-review
/payment-requests/{id}/request-correction
/payment-requests/{id}/mark-eligible-for-batching

/payment-batches/preview
/payment-batches
/payment-batches/{id}/versions
/payment-batches/{id}/versions/{version_id}/finalize
/payment-batches/{id}/versions/{version_id}/approval-view
/payment-batches/{id}/versions/{version_id}/approve
/payment-batches/{id}/versions/{version_id}/reject
/payment-batches/{id}/versions/{version_id}/exports/preview
/payment-batches/{id}/versions/{version_id}/exports/final
/bank-exports/{id}
/bank-exports/{id}/download
/bank-exports/{id}/mark-sent-to-bank

/payment-attempts
/payment-attempts/{id}/confirm-paid
/payment-attempts/{id}/confirm-failed
/payment-attempts/{id}/mark-retry-required
/payment-attempts/{id}/retry

/bank-result-bundles
/bank-result-bundles/{id}
/bank-result-bundles/{id}/start-review
/bank-result-bundles/{id}/close
/bank-result-bundles/{id}/receipt-segments/external
/bank-result-bundles/{id}/receipt-segments/crop
/receipt-segments/{id}
/evidence-links
/evidence-links/{id}/replace

/payment-requests/{id}/publications/preview
/payment-requests/{id}/publications
/me/trader/payment-requests/{id}/publication
/me/trader/payment-requests/{id}/acknowledge-result
/me/trader/payment-requests/{id}/dispute-result

/gold-sale-orders
/gold-sale-orders/{id}/pricing-versions
/gold-sale-orders/{id}/incoming-payment-receipts
/bank-statements
/bank-statements/{id}/import-runs
/incoming-payment-receipts/{id}/matches
/incoming-payment-receipts/{id}/confirm
/gold-sale-orders/{id}/dispatches

/manual-review-tasks
/notifications
/reports/accountant-dashboard
/reports/manager-dashboard
/bank-profiles
/bank-profile-versions
/bank-mappings
/audit-logs
/processing-jobs
/health/live
/health/ready
/health/dependencies
/health/workers
```

Not required for Phase 1A:

```text
automatic segmentation
OCR/AI extraction
AI matching suggestions
bank APIs
external IBAN/national-ID ownership validation
multi-company endpoints
billing/subscriptions
internal chat
native application APIs
spreadsheet import as the primary trader-request workflow
```

---

# 34. Critical Rules for Implementation Agents

1. Do not create a generic endpoint that accepts arbitrary financial status.
2. Do not approve a mutable batch; approve an exact immutable batch version.
3. Do not generate a sendable final export without a matching approval hash.
4. Do not allow manager approval without required recent authentication.
5. Do not place manager approval fields on payment requests.
6. Do not accept free-form beneficiary changes in a retry attempt; use a request revision.
7. Do not edit request revisions, batch versions, approvals, bank statement rows, or publications.
8. Do not treat matching candidates as confirmed evidence.
9. Do not mark an attempt paid merely by accepting a candidate.
10. Do not detach/delete primary evidence without replacement/revocation history.
11. Do not publish a segment directly as the trader result; create a result publication.
12. Do not expose mixed bundle files to traders.
13. Do not return storage keys or permanent public file URLs.
14. Do not infer Rial/Toman from amount magnitude.
15. Do not accept floating-point money.
16. Do not omit idempotency on critical commands.
17. Do not omit `If-Match` for mutable financial aggregates.
18. Do not let frontend `allowed_actions` replace backend authorization.
19. Do not let workers authorize or finalize financial decisions.
20. Do not silently discard unmatched bundle content or parse errors.
21. Do not edit used bank-profile/mapping versions.
22. Do not expose a normal financial hard-delete endpoint.
23. Do not expose real client/bank data in OpenAPI examples or tests.
24. Do not implement Phase 4 multi-tenancy fields/routes in Phase 1A.
25. Always commit business changes, audit, outbox, and idempotency result atomically for critical commands.

---

# 35. API Acceptance Checklist

The API specification is implementation-ready when all of the following are true:

- [x] Payment requests use immutable revisions.
- [x] Amount provenance supports explicit IRR/Toman input.
- [x] Accountant review ends in `eligible_for_batching`, not request-level manager approval.
- [x] Batches contain immutable ordered versions.
- [x] Manager decision targets one version/hash.
- [x] Final export is linked to the same approved version.
- [x] Critical commands require idempotency.
- [x] Mutable aggregates use ETag/`If-Match`.
- [x] Payment attempts are separate from request and batch membership.
- [x] Retry uses a request revision and preserves the failed attempt.
- [x] Candidate matching is separate from confirmed evidence.
- [x] One active primary evidence link is enforced per attempt/segment.
- [x] Phase 1A supports in-panel rectangular crop.
- [x] Trader results use immutable publications.
- [x] Corrections supersede rather than erase.
- [x] File storage paths are never exposed.
- [x] Trader ownership is backend-enforced.
- [x] Health endpoints match architecture/runbook contract.
- [x] AI/OCR remains optional and asynchronous.
- [x] Single-center Phase 1A is explicit.

Items that remain dependent on external ADR/business decisions:

- [ ] final authentication/session transport (`ADR-001`);
- [ ] manager strong-auth mechanism and recent-auth duration;
- [ ] production storage/signed-URL implementation;
- [ ] final retention policy and approval roles;
- [ ] initial bank profile/mapping samples;
- [ ] exact maximum upload sizes and expected transaction volume.

---

# 36. Next Document

The next document is:

```text
06_Workflows_and_State_Machines.md
```

It must use the exact API command names and canonical statuses in this document, and define:

- permitted transition table for every aggregate;
- command actor/permission;
- guards and lock scope;
- side effects, audit events, outbox events, and notifications;
- approval invalidation rules;
- correction and retry paths;
- terminal/non-terminal states;
- behavior after external bank execution.
