# Gold Trade Settlement Platform

## Database Schema

**Document ID:** `04_Database_Schema`  
**Version:** `1.1`  
**Status:** Revised authoritative database baseline  
**Language:** English  
**Primary audience:** Backend engineer, database engineer, technical lead, QA engineer, DevOps engineer, security engineer, and coding agents  
**Database:** PostgreSQL 16+  
**ORM and migration stack:** SQLAlchemy 2.x + Alembic

**Authoritative upstream documents:**

- `00_Master_Implementation_Blueprint.md`
- `01_Product_Requirements_PRD.md`
- `02_Domain_Model_and_Business_Rules.md`
- `03_System_Architecture.md`

### Version history

| Version | Summary |
|---|---|
| `1.0` | Initial implementation baseline. |
| `1.1` | Aligned the schema with the approved single-tenant architecture, immutable batch-version approval, bank-configuration versioning, request and attempt snapshots, amount provenance, manual crop in Phase 1A, confirmed-evidence cardinality, optimistic concurrency, idempotency, transactional outbox, retention/legal-hold governance, and production-safe constraints. |

---

# 1. Purpose and Authority

This document defines the relational persistence model for the Gold Trade Settlement Platform. It translates the approved domain model into implementation-grade PostgreSQL tables, foreign keys, constraints, indexes, immutability rules, concurrency controls, audit structures, and migration requirements.

The schema must support the following without AI, OCR, bank APIs, or external validation services:

1. trader and internal-user access;
2. reusable beneficiary records with immutable historical snapshots;
3. gold-sale orders and incoming-payment verification;
4. outgoing-payment requests, split/retry attempts, immutable payment-batch versions, and manager approval;
5. reproducible bank Excel exports;
6. bank-result bundles, document previews, minimal manual crop, receipt segments, manual matching, and payment confirmation;
7. trader-safe result publication;
8. full auditability, idempotency, concurrency protection, backup/restore, and retention governance.

The database is not a passive CRUD store. It is the authoritative persistence layer for financial invariants. Application services remain responsible for workflows, but the database must enforce every invariant that can be enforced safely at the relational level.

---

# 2. Decisions Fixed by This Version

The following decisions are no longer open in this document:

- Phase 1A is **single-center and single-tenant**.
- Do not add `center_id`, `organization_id`, or tenant-switching logic to every business table.
- Multi-company/SaaS support belongs to Phase 4 and requires a dedicated migration and isolation design.
- PostgreSQL is the authoritative business-state store.
- Binary data is stored in private file/object storage; PostgreSQL stores metadata and relationships.
- All canonical monetary values are integer IRR.
- Original user-entered value and unit are preserved where users can enter either Toman or Rial.
- Every Phase 1A outgoing batch requires manager approval.
- A manager approves one immutable `payment_batch_version`, not a mutable `payment_batch` container.
- Final bank exports must reference the exact approved version and matching content hash.
- `payment_requests` and `payment_attempts` are separate.
- Attempts do not carry one mutable `payment_batch_id`; batch membership is stored in versioned batch items.
- Candidate matching and confirmed evidence linkage are separate tables.
- Minimal manual crop is a Phase 1A feature; automatic segmentation is not.
- Generic soft deletion is not used for financial records.
- Critical write commands use idempotency records and optimistic concurrency.
- Domain changes, audit events, and outbox events are committed atomically.

---

# 3. PostgreSQL Extensions and Database Roles

## 3.1 Required extensions

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
```

Optional, when fuzzy Persian/name search is enabled:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
```

`unaccent` must not be treated as sufficient Persian normalization. Application normalization remains required.

## 3.2 Recommended database roles

Use separate credentials and least privilege:

```text
platform_migrator   DDL and Alembic migrations only
platform_app        normal API transactions
platform_worker     worker transactions; no migration rights
platform_readonly   restricted operational/reporting access when needed
platform_backup     backup/restore rights only
```

Production application roles must not own the database schema. `platform_app` and `platform_worker` must not have permission to drop tables, alter schema, or update/delete append-only audit records.

---

# 4. Global Relational Conventions

## 4.1 Primary keys

Use UUIDs for business and operational records:

```sql
id UUID PRIMARY KEY DEFAULT gen_random_uuid()
```

Use `BIGINT GENERATED ... AS IDENTITY` only for internal high-volume append-only sequence tables when a UUID is not needed externally. This version uses UUID by default for consistency.

## 4.2 Timestamps

System timestamps use timezone-aware fields:

```sql
created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
```

Backend timestamps are stored in UTC. User interfaces may render Jalali dates. Bank-provided dates preserve both normalized and raw values.

## 4.3 Optimistic concurrency

Mutable aggregates include:

```sql
record_version BIGINT NOT NULL DEFAULT 1 CHECK (record_version > 0)
```

Updates use compare-and-swap semantics:

```sql
UPDATE payment_requests
SET ..., record_version = record_version + 1
WHERE id = :id AND record_version = :expected_version;
```

Zero updated rows means a stale-write conflict. APIs must return a conflict response instead of silently overwriting newer data.

Tables that are immutable snapshots do not need `record_version`; they are superseded by inserting a new row.

## 4.4 Money and amount provenance

Canonical amounts:

```sql
amount_irr BIGINT NOT NULL CHECK (amount_irr > 0)
```

Where users may enter Toman or Rial, also store:

```sql
entered_amount_value BIGINT NULL CHECK (entered_amount_value > 0),
entered_amount_unit VARCHAR(8) NULL
  CHECK (entered_amount_unit IN ('IRR', 'TOMAN'))
```

Rules:

- Never use `FLOAT`, `REAL`, or approximate numeric types for money.
- Conversion from Toman to IRR must be exact multiplication by 10.
- The original entered value/unit is provenance, not the canonical value.
- No unit may be inferred from the magnitude of a number.
- Outgoing-payment allocation has no hidden tolerance. Exact equality is required unless a future explicitly modeled fee/rounding component is introduced.

## 4.5 Weight and purity

Gold weights use fixed precision:

```sql
gold_weight NUMERIC(20, 6) NULL CHECK (gold_weight > 0)
```

The unit must be explicit (`GRAM`, `MITHQAL`, or an approved code). Purity/carat may use a validated code or fixed decimal according to later product policy; raw descriptions may also be retained.

## 4.6 Status storage

Use `VARCHAR` with named `CHECK` constraints rather than PostgreSQL native enums during early evolution. Status constants are owned by the workflow document and must be synchronized across Python, OpenAPI, and TypeScript.

Example:

```sql
status VARCHAR(48) NOT NULL,
CONSTRAINT ck_payment_request_status CHECK (status IN (...))
```

Unknown status strings are never accepted merely for forward compatibility.

## 4.7 Foreign-key delete policy

Default policy:

- financial and audit relationships: `ON DELETE RESTRICT` or no delete action;
- pure RBAC junction rows: `ON DELETE CASCADE` is acceptable;
- optional actor references: `ON DELETE SET NULL` only if the actor table may ever be physically removed;
- normal application flows never physically delete financial users, traders, requests, attempts, versions, approvals, exports, evidence, statements, or audit records.

## 4.8 Cancellation, voiding, supersession, and archival

Do not add `deleted_at` mechanically to all tables. Use domain states:

```text
cancelled
voided
superseded
replaced
archived
```

Physical deletion is reserved for an approved retention process after legal-hold checks and must never be exposed as a normal CRUD action.

## 4.9 Raw external values

Bank rows, uploaded metadata, parser results, and AI/OCR responses preserve raw values in JSONB or explicit raw columns. Normalized values never overwrite source data.

## 4.10 Actor references

Because internal and trader users are separate identities, audit/command tables use:

```sql
actor_type VARCHAR(24) NOT NULL
  CHECK (actor_type IN ('admin_user','trader_user','system','worker')),
actor_id UUID NULL
```

Core business tables should prefer explicit foreign keys such as `created_by_admin_user_id` when only one actor class is allowed.

---

# 5. Schema Areas and Entity Map

```text
center_profile

identity
  admin_users, trader_users, auth_sessions, auth_events
  roles, permissions, role_permissions, admin_user_roles

traders
  traders, trader_bank_accounts, beneficiaries

bank configuration
  bank_profiles, bank_profile_versions, bank_accounts
  bank_mappings

gold sale and incoming payment
  gold_sale_orders, gold_sale_pricing_versions
  incoming_payment_receipts
  bank_statement_files, bank_statement_import_runs, bank_statement_rows
  incoming_payment_matches, gold_dispatches

outgoing payment
  payment_requests, payment_request_revisions
  payment_attempts
  payment_batches, payment_batch_versions, payment_batch_items
  batch_approvals, bank_excel_exports

bank result and evidence
  bank_result_bundles, bank_result_bundle_files
  receipt_segments, matching_candidates, confirmed_evidence_links
  bank_result_bundle_batch_links

files
  file_objects, file_links, file_derivations

operations
  manual_review_tasks, comments, notifications
  processing_jobs, ai_usage_logs

integrity and governance
  idempotency_records, outbox_events, audit_logs
  system_settings, feature_flags, retention_policies, legal_holds
```

---

# 6. Center and Identity Tables

## 6.1 `center_profile`

Exactly one active row is expected in Phase 1A.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK |
| `name` | VARCHAR(255) | yes | Display name |
| `legal_name` | VARCHAR(255) | no | Legal entity name |
| `default_currency` | VARCHAR(8) | yes | Must be `IRR` |
| `timezone` | VARCHAR(64) | yes | Default `Asia/Tehran` |
| `status` | VARCHAR(24) | yes | `active`, `inactive` |
| `record_version` | BIGINT | yes | Optimistic locking |
| `created_at` | TIMESTAMPTZ | yes | |
| `updated_at` | TIMESTAMPTZ | yes | |

```sql
CREATE UNIQUE INDEX uq_center_profile_one_active
ON center_profile ((status))
WHERE status = 'active';
```

This is a deployment profile, not a partial multi-tenant implementation.

## 6.2 `admin_users`

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK |
| `username` | CITEXT | yes | Globally unique in the deployment |
| `phone_number` | VARCHAR(32) | no | Normalized separately |
| `email` | CITEXT | no | |
| `password_hash` | VARCHAR(255) | yes | Argon2id preferred |
| `full_name` | VARCHAR(255) | yes | |
| `status` | VARCHAR(24) | yes | `active`, `inactive`, `suspended` |
| `failed_login_count` | INTEGER | yes | Default 0 |
| `locked_until` | TIMESTAMPTZ | no | |
| `password_changed_at` | TIMESTAMPTZ | no | |
| `last_login_at` | TIMESTAMPTZ | no | |
| `record_version` | BIGINT | yes | |
| `created_at` | TIMESTAMPTZ | yes | |
| `updated_at` | TIMESTAMPTZ | yes | |

Constraints/indexes:

```sql
UNIQUE (username);
CREATE UNIQUE INDEX uq_admin_users_email
  ON admin_users(email) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX uq_admin_users_phone
  ON admin_users(phone_number) WHERE phone_number IS NOT NULL;
CREATE INDEX idx_admin_users_status ON admin_users(status);
```

## 6.3 `trader_users`

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK |
| `trader_id` | UUID | yes | FK `traders` |
| `phone_number` | VARCHAR(32) | yes | Login identity |
| `password_hash` | VARCHAR(255) | conditional | Depends on ADR-001 |
| `full_name` | VARCHAR(255) | no | |
| `status` | VARCHAR(24) | yes | `pending`, `active`, `suspended`, `inactive` |
| `is_primary` | BOOLEAN | yes | Default false |
| `failed_login_count` | INTEGER | yes | Default 0 |
| `locked_until` | TIMESTAMPTZ | no | |
| `last_login_at` | TIMESTAMPTZ | no | |
| `record_version` | BIGINT | yes | |
| `created_at` | TIMESTAMPTZ | yes | |
| `updated_at` | TIMESTAMPTZ | yes | |

```sql
UNIQUE (phone_number);
CREATE UNIQUE INDEX uq_trader_users_one_primary
ON trader_users(trader_id)
WHERE is_primary = TRUE AND status <> 'inactive';
```

Multiple trader users are not exposed in Phase 1A UI, but the schema does not require a redesign later.

## 6.4 RBAC tables

### `roles`

`id`, `code`, `name`, `description`, `is_system`, `created_at`, `updated_at`.

```sql
UNIQUE(code)
```

### `permissions`

`id`, `code`, `description`, `created_at`.

```sql
UNIQUE(code)
```

### `role_permissions`

`role_id`, `permission_id`, `created_at`.

```sql
PRIMARY KEY(role_id, permission_id)
```

### `admin_user_roles`

`admin_user_id`, `role_id`, `granted_by_admin_user_id`, `created_at`, `revoked_at`.

Use a partial unique index for one active grant:

```sql
CREATE UNIQUE INDEX uq_admin_user_role_active
ON admin_user_roles(admin_user_id, role_id)
WHERE revoked_at IS NULL;
```

Role changes must be audited. Trader permissions are not assigned through `admin_user_roles`; trader access is determined by authenticated trader identity and ownership scope.

## 6.5 `auth_sessions`

Supports server-side sessions or hashed refresh-token records without fixing the HTTP transport decision.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK/session ID |
| `admin_user_id` | UUID | conditional | FK; exactly one user column is set |
| `trader_user_id` | UUID | conditional | FK; exactly one user column is set |
| `secret_hash` | VARCHAR(255) | yes | Never store raw session/refresh secret |
| `auth_level` | VARCHAR(24) | yes | `normal`, `step_up` |
| `authenticated_at` | TIMESTAMPTZ | yes | |
| `step_up_expires_at` | TIMESTAMPTZ | no | |
| `expires_at` | TIMESTAMPTZ | yes | |
| `revoked_at` | TIMESTAMPTZ | no | |
| `revocation_reason` | VARCHAR(128) | no | |
| `ip_address` | INET | no | |
| `user_agent` | TEXT | no | |
| `created_at` | TIMESTAMPTZ | yes | |
| `last_seen_at` | TIMESTAMPTZ | no | |

```sql
CHECK ((admin_user_id IS NOT NULL)::int + (trader_user_id IS NOT NULL)::int = 1);
CREATE INDEX idx_auth_sessions_admin_active
  ON auth_sessions(admin_user_id, expires_at)
  WHERE admin_user_id IS NOT NULL AND revoked_at IS NULL;
CREATE INDEX idx_auth_sessions_trader_active
  ON auth_sessions(trader_user_id, expires_at)
  WHERE trader_user_id IS NOT NULL AND revoked_at IS NULL;
```

## 6.6 `auth_events`

Append-only security events: login success/failure, logout, password reset, session revocation, step-up success/failure, lockout.

Required fields: `id`, `actor_type`, `actor_id`, `event_type`, `outcome`, `ip_address`, `user_agent`, `request_id`, `metadata`, `created_at`.

Do not store plaintext passwords, OTPs, tokens, or full secrets.

---

# 7. Trader and Beneficiary Tables

## 7.1 `traders`

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK |
| `display_name` | VARCHAR(255) | yes | |
| `legal_name` | VARCHAR(255) | no | |
| `primary_phone` | VARCHAR(32) | yes | |
| `operational_status` | VARCHAR(24) | yes | `active`, `inactive`, `suspended`, `blocked` |
| `approval_status` | VARCHAR(24) | yes | `pending_approval`, `approved`, `rejected` |
| `approved_at` | TIMESTAMPTZ | no | |
| `approved_by_admin_user_id` | UUID | no | FK |
| `risk_level` | VARCHAR(24) | no | Advisory label |
| `credit_limit_irr` | BIGINT | no | Must be non-negative |
| `notes_internal` | TEXT | no | Never trader-visible |
| `record_version` | BIGINT | yes | |
| `created_at` | TIMESTAMPTZ | yes | |
| `updated_at` | TIMESTAMPTZ | yes | |

Do not store an authoritative `current_balance_irr` unless a proper ledger and reconciliation model exists. A mutable cached balance without a ledger is explicitly prohibited.

```sql
UNIQUE(primary_phone);
CHECK (credit_limit_irr IS NULL OR credit_limit_irr >= 0);
CREATE INDEX idx_traders_status_approval
  ON traders(operational_status, approval_status);
```

## 7.2 `trader_bank_accounts`

Stores trader-owned accounts only when needed for incoming-payment verification or approved business controls.

Fields: `id`, `trader_id`, `bank_profile_id`, `account_number`, `iban`, `normalized_iban`, `account_owner_name`, `status`, `is_default`, `record_version`, `created_at`, `updated_at`.

```sql
UNIQUE(trader_id, normalized_iban);
CREATE UNIQUE INDEX uq_trader_bank_account_default
ON trader_bank_accounts(trader_id)
WHERE is_default = TRUE AND status = 'active';
```

## 7.3 `beneficiaries`

A reusable recipient owned by exactly one trader. Amount is not stored here.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK |
| `trader_id` | UUID | yes | FK |
| `full_name` | VARCHAR(255) | yes | |
| `normalized_name` | VARCHAR(255) | no | Search/dedup helper |
| `iban` | VARCHAR(34) | yes | Display/original normalized formatting |
| `normalized_iban` | CHAR(26) | yes | Uppercase, no spaces |
| `bank_profile_id` | UUID | no | Inferred or selected |
| `national_id` | VARCHAR(16) | no | Sensitive, optional |
| `phone_number` | VARCHAR(32) | no | |
| `status` | VARCHAR(24) | yes | `active`, `inactive`, `blocked`, `superseded` |
| `blocked_reason` | TEXT | no | |
| `notes_internal` | TEXT | no | |
| `verification_status` | VARCHAR(24) | yes | `not_checked`, `verified`, `mismatch`, `failed` |
| `verification_metadata` | JSONB | yes | Default `{}` |
| `record_version` | BIGINT | yes | |
| `created_at` | TIMESTAMPTZ | yes | |
| `updated_at` | TIMESTAMPTZ | yes | |

```sql
CHECK (normalized_iban ~ '^IR[0-9]{24}$');
CREATE INDEX idx_beneficiaries_trader_status
  ON beneficiaries(trader_id, status);
CREATE INDEX idx_beneficiaries_normalized_iban
  ON beneficiaries(trader_id, normalized_iban);
```

Do not enforce a unique beneficiary per IBAN/name because duplicates may be legitimate or incomplete. The service produces duplicate warnings; it does not auto-merge.

Historical payment requests/attempts preserve beneficiary snapshots and are unaffected by later beneficiary edits.

---

# 8. Bank Configuration and Versioning

## 8.1 `bank_profiles`

Stable bank identity.

Fields: `id`, `code`, `name`, `status`, `current_version_id`, `record_version`, `created_at`, `updated_at`.

```sql
UNIQUE(code)
```

`current_version_id` is assigned after the version row exists. Use a deferrable FK or a two-step migration/update.

## 8.2 `bank_profile_versions`

Immutable operational configuration snapshot.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK |
| `bank_profile_id` | UUID | yes | FK |
| `version_number` | INTEGER | yes | Monotonic per bank |
| `status` | VARCHAR(24) | yes | `draft`, `active`, `retired` |
| `effective_from` | TIMESTAMPTZ | no | |
| `effective_to` | TIMESTAMPTZ | no | |
| `default_transfer_limit_irr` | BIGINT | no | |
| `after_cutoff_transfer_limit_irr` | BIGINT | no | |
| `cutoff_time` | TIME | no | Evaluated in configured timezone |
| `splitting_enabled` | BOOLEAN | yes | |
| `supports_description_field` | BOOLEAN | yes | |
| `required_fields` | JSONB | yes | Stable configuration |
| `rules` | JSONB | yes | Versioned rule payload |
| `config_hash` | CHAR(64) | yes | Canonical hash |
| `created_by_admin_user_id` | UUID | yes | |
| `created_at` | TIMESTAMPTZ | yes | |

```sql
UNIQUE(bank_profile_id, version_number);
UNIQUE(bank_profile_id, config_hash);
CHECK (default_transfer_limit_irr IS NULL OR default_transfer_limit_irr > 0);
CHECK (after_cutoff_transfer_limit_irr IS NULL OR after_cutoff_transfer_limit_irr > 0);
```

Used versions are never updated. A configuration change inserts a new version.

## 8.3 `bank_accounts`

Center-owned source/destination accounts used for batches and statements.

Fields: `id`, `bank_profile_id`, `display_name`, `account_number`, `deposit_number`, `iban`, `normalized_iban`, `account_role`, `status`, `record_version`, `created_at`, `updated_at`.

`account_role` may include `outgoing_source`, `incoming_destination`, or `both`.

```sql
UNIQUE(normalized_iban);
CHECK (normalized_iban IS NULL OR normalized_iban ~ '^IR[0-9]{24}$');
```

## 8.4 `bank_mappings`

Immutable mapping/template version for a bank-profile version.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK |
| `bank_profile_version_id` | UUID | yes | FK |
| `file_type` | VARCHAR(48) | yes | Statement import, outgoing export, result import |
| `template_version` | INTEGER | yes | |
| `status` | VARCHAR(24) | yes | `draft`, `active`, `retired` |
| `mapping` | JSONB | yes | |
| `required_fields` | JSONB | yes | |
| `normalization_rules` | JSONB | yes | Default `{}` |
| `sample_header_hash` | CHAR(64) | no | |
| `config_hash` | CHAR(64) | yes | |
| `created_by_admin_user_id` | UUID | yes | |
| `approved_by_admin_user_id` | UUID | no | Required if business output changes |
| `created_at` | TIMESTAMPTZ | yes | |

```sql
UNIQUE(bank_profile_version_id, file_type, template_version);
UNIQUE(bank_profile_version_id, file_type, config_hash);
```

Once referenced by a production import/export, the row is immutable.

---

# 9. Private File and Evidence Storage Metadata

## 9.1 `file_objects`

Central metadata for every stored binary object.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK |
| `storage_provider` | VARCHAR(32) | yes | `local`, `s3`, etc. |
| `storage_bucket` | VARCHAR(255) | no | |
| `storage_key` | VARCHAR(1024) | yes | Never exposed directly |
| `original_filename` | VARCHAR(512) | no | Sanitized for display |
| `mime_type_declared` | VARCHAR(128) | no | Client declaration |
| `mime_type_detected` | VARCHAR(128) | no | Server detection |
| `size_bytes` | BIGINT | yes | Non-negative |
| `sha256_hash` | CHAR(64) | no | Required before `available` |
| `category` | VARCHAR(48) | yes | |
| `visibility_scope` | VARCHAR(32) | yes | `internal_only`, `trader_visible`, `system_only`, `manager_only` |
| `storage_status` | VARCHAR(32) | yes | `pending`, `quarantined`, `available`, `processing_failed`, `archived`, `retention_pending`, `deleted` |
| `scan_status` | VARCHAR(24) | yes | `not_scanned`, `pending`, `clean`, `suspicious`, `failed` |
| `uploaded_by_actor_type` | VARCHAR(24) | yes | |
| `uploaded_by_actor_id` | UUID | no | |
| `retention_class` | VARCHAR(48) | yes | |
| `metadata` | JSONB | yes | Default `{}` |
| `created_at` | TIMESTAMPTZ | yes | |
| `updated_at` | TIMESTAMPTZ | yes | |
| `archived_at` | TIMESTAMPTZ | no | |
| `physically_deleted_at` | TIMESTAMPTZ | no | Retention process only |

```sql
UNIQUE(storage_provider, storage_bucket, storage_key);
CHECK (size_bytes >= 0);
CREATE INDEX idx_file_objects_hash ON file_objects(sha256_hash);
CREATE INDEX idx_file_objects_status_category
  ON file_objects(storage_status, category, created_at);
```

A file may be downloaded only after authorization and only in an allowed storage/scan state. `visibility_scope` is necessary metadata but is never sufficient authorization by itself.

## 9.2 `file_links`

Use for non-critical polymorphic attachments/comments. Critical financial relationships use explicit FKs.

Fields: `id`, `file_id`, `entity_type`, `entity_id`, `link_type`, `visibility_override`, `created_by_actor_type`, `created_by_actor_id`, `created_at`, `replaced_at`, `replaced_by_file_link_id`.

```sql
CREATE INDEX idx_file_links_entity
ON file_links(entity_type, entity_id, link_type)
WHERE replaced_at IS NULL;
```

## 9.3 `file_derivations`

Records previews, thumbnails, rendered PDF pages, crops, and generated share files.

Fields: `id`, `source_file_id`, `derived_file_id`, `derivation_type`, `parameters`, `renderer_version`, `source_hash`, `created_by_job_id`, `created_at`.

```sql
UNIQUE(source_file_id, derived_file_id);
UNIQUE(source_file_id, derivation_type, parameters, renderer_version);
```

The second constraint may use a canonical `parameters_hash` instead of raw JSONB in actual migration.

---

# 10. Gold Sale and Incoming-Payment Schema

## 10.1 `gold_sale_orders`

Mutable order aggregate.

Key fields:

- `id`, `trader_id`, `order_number`;
- `status`;
- `gold_type`, `gold_weight`, `weight_unit`, `gold_purity`;
- `current_pricing_version_id`;
- `expected_amount_irr`, `final_amount_irr`;
- `created_by_actor_type`, `created_by_actor_id`;
- `cancelled_at`, `cancelled_reason`, `closed_at`;
- `record_version`, timestamps.

```sql
UNIQUE(order_number);
CHECK (expected_amount_irr IS NULL OR expected_amount_irr > 0);
CHECK (final_amount_irr IS NULL OR final_amount_irr > 0);
CREATE INDEX idx_gold_sale_orders_trader_status
  ON gold_sale_orders(trader_id, status, created_at);
```

Recommended status check:

```text
draft, submitted, under_center_review, priced,
waiting_for_incoming_payment, payment_evidence_submitted,
waiting_for_bank_statement, needs_review,
incoming_payment_partially_confirmed, incoming_payment_confirmed,
manager_approval_required, ready_for_dispatch, dispatched,
received_by_trader, settled_or_offset, closed, rejected, cancelled
```

## 10.2 `gold_sale_pricing_versions`

Immutable pricing/amount snapshot.

Fields: `id`, `gold_sale_order_id`, `version_number`, `pricing_method`, `gold_weight`, `weight_unit`, `gold_purity`, `unit_price_irr`, `expected_amount_irr`, `entered_amount_value`, `entered_amount_unit`, `pricing_note`, `content_hash`, `created_by_admin_user_id`, `created_at`, `superseded_at`.

```sql
UNIQUE(gold_sale_order_id, version_number);
CHECK (expected_amount_irr > 0);
```

Updating price creates a new row and updates `gold_sale_orders.current_pricing_version_id` transactionally.

## 10.3 `incoming_payment_receipts`

A claim/evidence submitted for a gold sale.

Fields include:

- `id`, `gold_sale_order_id`, `trader_id`;
- `amount_irr`, `entered_amount_value`, `entered_amount_unit`;
- `tracking_number`, `raw_payment_date`, `payment_at_normalized`;
- `source_bank_name`, `source_account_hint`, `destination_bank_account_id`;
- `sender_name`, `evidence_file_id`;
- `status`, `confirmed_amount_irr`;
- `confirmed_by_admin_user_id`, `confirmed_at`;
- `record_version`, timestamps.

```sql
CHECK (amount_irr > 0);
CHECK (confirmed_amount_irr IS NULL OR confirmed_amount_irr >= 0);
CREATE INDEX idx_incoming_receipts_order_status
  ON incoming_payment_receipts(gold_sale_order_id, status, created_at);
CREATE INDEX idx_incoming_receipts_tracking
  ON incoming_payment_receipts(tracking_number)
  WHERE tracking_number IS NOT NULL;
```

## 10.4 `bank_statement_files`

Represents the immutable original statement file and import context.

Fields: `id`, `bank_profile_version_id`, `bank_account_id`, `original_file_id`, `status`, `date_range_start`, `date_range_end`, `uploaded_by_admin_user_id`, `created_at`, `record_version`.

## 10.5 `bank_statement_import_runs`

Every parse/reparse is a separate run.

Fields: `id`, `bank_statement_file_id`, `bank_mapping_id`, `run_number`, `status`, `row_count`, `parser_version`, `source_hash`, `started_at`, `finished_at`, `error_summary`, `created_by_admin_user_id`, `created_by_job_id`, `created_at`.

```sql
UNIQUE(bank_statement_file_id, run_number);
```

A reparse does not update old rows; it creates a new run and row set.

## 10.6 `bank_statement_rows`

Immutable rows tied to one import run.

Fields:

- `id`, `bank_statement_import_run_id`, `row_number`;
- normalized and raw date/time;
- `amount_in_irr`, `amount_out_irr`, `balance_irr`;
- `tracking_number`, `description`, `counterparty_name`, `counterparty_account`, `counterparty_iban`;
- `raw_data`, `row_fingerprint`, `status`, `created_at`.

```sql
UNIQUE(bank_statement_import_run_id, row_number);
CREATE INDEX idx_bank_statement_rows_match
  ON bank_statement_rows(amount_in_irr, transaction_at_normalized, tracking_number);
CREATE INDEX idx_bank_statement_rows_fingerprint
  ON bank_statement_rows(row_fingerprint);
```

Do not store generic `matched_entity_type/id` or a mutable `is_matched` flag as the source of truth. Match state is derived from dedicated match records.

## 10.7 `incoming_payment_matches`

Candidate/confirmed relationship between one receipt and one bank statement row. Multiple records support partial/combined scenarios and corrections.

Fields: `id`, `incoming_payment_receipt_id`, `bank_statement_row_id`, `status`, `match_method`, `match_score`, `match_reasons`, `confirmed_amount_irr`, `confirmed_by_admin_user_id`, `confirmed_at`, `rejected_by_admin_user_id`, `rejected_at`, `rejection_reason`, `replaces_match_id`, timestamps.

```sql
UNIQUE(incoming_payment_receipt_id, bank_statement_row_id);
CHECK (match_score IS NULL OR (match_score >= 0 AND match_score <= 1));
CHECK (confirmed_amount_irr IS NULL OR confirmed_amount_irr > 0);
```

Use partial unique rules only if the business confirms strict one-row/one-receipt matching. The baseline supports traceable partial/combined payment cases.

## 10.8 `gold_dispatches`

Fields: `id`, `gold_sale_order_id`, `dispatch_type`, `status`, `weight`, `weight_unit`, `gold_purity`, `receiver_name`, `tracking_or_delivery_note`, `evidence_file_id`, `created_by_admin_user_id`, `confirmed_by_trader_user_id`, `dispatched_at`, `confirmed_at`, `record_version`, timestamps.

`dispatch_type`: `physical_dispatch`, `physical_receipt`, `offset_settlement`, `manual_settlement`.

No dispatch/settlement row may be marked completed unless the payment guard or an audited authorized override is satisfied by the service transaction.

---

# 11. Outgoing-Payment Schema

## 11.1 `payment_requests`

Stable logical request aggregate. Manager approval does not live on this table.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK |
| `trader_id` | UUID | yes | FK |
| `beneficiary_id` | UUID | yes | FK |
| `request_number` | VARCHAR(64) | yes | Human-readable unique |
| `current_revision_id` | UUID | no initially | FK to current request revision |
| `status` | VARCHAR(48) | yes | Aggregate/workflow status |
| `submitted_at` | TIMESTAMPTZ | no | |
| `reviewed_by_admin_user_id` | UUID | no | |
| `reviewed_at` | TIMESTAMPTZ | no | |
| `review_note` | TEXT | no | |
| `cancelled_at` | TIMESTAMPTZ | no | |
| `cancelled_reason` | TEXT | no | |
| `result_published_at` | TIMESTAMPTZ | no | |
| `trader_acknowledged_at` | TIMESTAMPTZ | no | |
| `trader_disputed_at` | TIMESTAMPTZ | no | |
| `trader_result_note` | TEXT | no | |
| `record_version` | BIGINT | yes | |
| `created_by_trader_user_id` | UUID | no | |
| `created_by_admin_user_id` | UUID | no | |
| `created_at` | TIMESTAMPTZ | yes | |
| `updated_at` | TIMESTAMPTZ | yes | |

```sql
UNIQUE(request_number);
CREATE INDEX idx_payment_requests_trader_status
  ON payment_requests(trader_id, status, created_at DESC);
CREATE INDEX idx_payment_requests_queue
  ON payment_requests(status, submitted_at)
  WHERE status IN ('submitted_to_center','under_accountant_review',
                   'needs_trader_correction','eligible_for_batching',
                   'retry_required','trader_disputed');
```

Statuses:

```text
draft, submitted_to_center, under_accountant_review,
needs_trader_correction, eligible_for_batching, batched,
sent_to_bank, partially_paid, paid, failed, retry_required,
result_ready_for_trader, result_published, trader_acknowledged,
trader_disputed, cancelled, closed
```

## 11.2 `payment_request_revisions`

Immutable request content snapshot. This table removes ambiguity around post-submission correction.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK |
| `payment_request_id` | UUID | yes | FK |
| `revision_number` | INTEGER | yes | |
| `beneficiary_id` | UUID | yes | Selected reusable record |
| `beneficiary_name_snapshot` | VARCHAR(255) | yes | |
| `beneficiary_iban_snapshot` | CHAR(26) | yes | |
| `beneficiary_national_id_snapshot` | VARCHAR(16) | no | |
| `amount_irr` | BIGINT | yes | |
| `entered_amount_value` | BIGINT | no | |
| `entered_amount_unit` | VARCHAR(8) | no | |
| `description` | TEXT | no | |
| `source_attachment_file_id` | UUID | no | |
| `revision_reason` | TEXT | no | |
| `content_hash` | CHAR(64) | yes | Canonical content hash |
| `created_by_actor_type` | VARCHAR(24) | yes | |
| `created_by_actor_id` | UUID | no | |
| `created_at` | TIMESTAMPTZ | yes | |
| `superseded_at` | TIMESTAMPTZ | no | |

```sql
UNIQUE(payment_request_id, revision_number);
UNIQUE(payment_request_id, content_hash);
CHECK (amount_irr > 0);
CHECK (beneficiary_iban_snapshot ~ '^IR[0-9]{24}$');
```

Material amendment inserts a new revision. If the request already appears in a batch version, affected versions/approvals must be invalidated through the batch workflow.

## 11.3 `payment_attempts`

Concrete transfer instruction/result. No mutable `payment_batch_id` column exists.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK |
| `payment_request_id` | UUID | yes | FK |
| `payment_request_revision_id` | UUID | yes | Exact source revision |
| `attempt_number` | INTEGER | yes | Sequence within request |
| `attempt_type` | VARCHAR(24) | yes | `original`, `split`, `retry`, `correction` |
| `amount_irr` | BIGINT | yes | |
| `beneficiary_name_snapshot` | VARCHAR(255) | yes | |
| `beneficiary_iban_snapshot` | CHAR(26) | yes | |
| `beneficiary_national_id_snapshot` | VARCHAR(16) | no | |
| `bank_profile_version_id` | UUID | yes | Rule version used |
| `bank_account_id` | UUID | no | Source account |
| `split_rule_snapshot` | JSONB | yes | Default `{}` |
| `status` | VARCHAR(40) | yes | |
| `bank_tracking_number` | VARCHAR(128) | no | |
| `bank_result_at` | TIMESTAMPTZ | no | |
| `failure_code` | VARCHAR(64) | no | |
| `failure_reason` | TEXT | no | |
| `retry_of_attempt_id` | UUID | no | Self FK |
| `supersedes_attempt_id` | UUID | no | Self FK |
| `confirmed_by_admin_user_id` | UUID | no | Human confirmation |
| `confirmed_at` | TIMESTAMPTZ | no | |
| `record_version` | BIGINT | yes | |
| `created_at` | TIMESTAMPTZ | yes | |
| `updated_at` | TIMESTAMPTZ | yes | |

```sql
UNIQUE(payment_request_id, attempt_number);
CHECK (amount_irr > 0);
CHECK (beneficiary_iban_snapshot ~ '^IR[0-9]{24}$');
CHECK (retry_of_attempt_id IS NULL OR retry_of_attempt_id <> id);
CHECK (supersedes_attempt_id IS NULL OR supersedes_attempt_id <> id);
CREATE INDEX idx_payment_attempts_request_status
  ON payment_attempts(payment_request_id, status, attempt_number);
CREATE INDEX idx_payment_attempts_match
  ON payment_attempts(amount_irr, beneficiary_iban_snapshot, bank_tracking_number);
```

Statuses:

```text
created, included_in_batch_version, sent_to_bank,
bank_result_pending, paid, failed, retry_required,
superseded, cancelled
```

Cross-row invariant enforced in a locked service transaction:

```text
sum(active unsuperseded attempt allocations) <= request revision amount
sum(authoritative paid attempts) == request amount  => request paid
0 < paid sum < request amount                       => partially_paid
paid sum > request amount                           => reconciliation error, never normal paid
```

## 11.4 `payment_batches`

Stable container and operational status only.

Fields: `id`, `batch_number`, `status`, `current_version_id`, `created_by_admin_user_id`, `sent_to_bank_at`, `sent_to_bank_by_admin_user_id`, `cancelled_at`, `cancelled_reason`, `record_version`, timestamps.

```sql
UNIQUE(batch_number)
```

## 11.5 `payment_batch_versions`

Immutable ordered snapshot proposed for manager approval.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK |
| `payment_batch_id` | UUID | yes | FK |
| `version_number` | INTEGER | yes | |
| `bank_profile_version_id` | UUID | yes | FK |
| `bank_account_id` | UUID | yes | Source account |
| `bank_mapping_id` | UUID | yes | Exact export mapping/template |
| `status` | VARCHAR(32) | yes | `draft`, `ready_for_approval`, `approved`, `rejected`, `superseded` |
| `row_count` | INTEGER | yes | |
| `total_amount_irr` | BIGINT | yes | |
| `content_hash` | CHAR(64) | yes | Canonical ordered content |
| `validation_summary` | JSONB | yes | Warnings/errors snapshot |
| `created_by_admin_user_id` | UUID | yes | |
| `created_at` | TIMESTAMPTZ | yes | |
| `superseded_at` | TIMESTAMPTZ | no | |

```sql
UNIQUE(payment_batch_id, version_number);
UNIQUE(payment_batch_id, content_hash);
CHECK (row_count > 0);
CHECK (total_amount_irr > 0);
CREATE INDEX idx_batch_versions_approval_queue
  ON payment_batch_versions(status, created_at)
  WHERE status = 'ready_for_approval';
```

The canonical hash includes ordered rows, attempt IDs/snapshots, amounts, beneficiary/IBAN snapshots, bank profile version, mapping version, source account, and relevant transfer channel/configuration.

## 11.6 `payment_batch_items`

Immutable rows within one batch version.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK |
| `payment_batch_version_id` | UUID | yes | FK |
| `payment_attempt_id` | UUID | yes | FK |
| `row_order` | INTEGER | yes | 1-based stable order |
| `amount_irr` | BIGINT | yes | Exact row amount |
| `beneficiary_name_snapshot` | VARCHAR(255) | yes | Exact approved/exported value |
| `beneficiary_iban_snapshot` | CHAR(26) | yes | Exact approved/exported value |
| `description_snapshot` | TEXT | no | Exact approved/exported value |
| `attempt_snapshot` | JSONB | yes | Remaining canonical row/config context |
| `row_hash` | CHAR(64) | yes | |
| `created_at` | TIMESTAMPTZ | yes | |

```sql
UNIQUE(payment_batch_version_id, payment_attempt_id);
UNIQUE(payment_batch_version_id, row_order);
CHECK (row_order > 0);
CHECK (amount_irr > 0);
CHECK (beneficiary_iban_snapshot ~ '^IR[0-9]{24}$');
```

No update/delete is allowed after the parent version leaves `draft`. Changes create a new batch version. `payment_batch_versions.total_amount_irr` is calculated from `payment_batch_items.amount_irr`, not from JSONB.

## 11.7 `batch_approvals`

Append-only manager decision for one exact version.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK |
| `payment_batch_version_id` | UUID | yes | FK |
| `decision` | VARCHAR(16) | yes | `approved`, `rejected` |
| `decided_by_admin_user_id` | UUID | yes | Must hold manager permission |
| `decided_at` | TIMESTAMPTZ | yes | |
| `reason` | TEXT | no | Required for rejection |
| `approved_content_hash` | CHAR(64) | conditional | Required for approval |
| `authentication_context` | JSONB | yes | Session ID/auth level/recent-auth metadata; no secret |
| `request_id` | UUID | no | Correlation |
| `created_at` | TIMESTAMPTZ | yes | |

```sql
UNIQUE(payment_batch_version_id);
UNIQUE(id, payment_batch_version_id);
CHECK (
  (decision = 'approved' AND approved_content_hash IS NOT NULL)
  OR
  (decision = 'rejected' AND approved_content_hash IS NULL AND reason IS NOT NULL)
);
```

A deferred database trigger or the application transaction must verify that an approval hash equals the referenced version hash. Approved/rejected rows are never updated.

## 11.8 `bank_excel_exports`

Preview or final reproducible artifact.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK |
| `payment_batch_version_id` | UUID | yes | FK |
| `batch_approval_id` | UUID | conditional | Required for final |
| `bank_profile_version_id` | UUID | yes | FK |
| `bank_mapping_id` | UUID | yes | FK |
| `file_id` | UUID | yes | FK |
| `export_number` | VARCHAR(64) | yes | Unique human-readable |
| `export_type` | VARCHAR(16) | yes | `preview`, `final` |
| `row_count` | INTEGER | yes | |
| `total_amount_irr` | BIGINT | yes | |
| `content_hash` | CHAR(64) | yes | Hash of normalized export content |
| `file_sha256_hash` | CHAR(64) | yes | Stored file hash |
| `status` | VARCHAR(32) | yes | |
| `generated_by_admin_user_id` | UUID | yes | |
| `generated_at` | TIMESTAMPTZ | yes | |
| `downloaded_at` | TIMESTAMPTZ | no | |
| `sent_to_bank_marked_at` | TIMESTAMPTZ | no | |
| `sent_to_bank_marked_by_admin_user_id` | UUID | no | |
| `created_at` | TIMESTAMPTZ | yes | |

```sql
UNIQUE(export_number);
CHECK (row_count > 0);
CHECK (total_amount_irr > 0);
CHECK (
  (export_type = 'preview' AND batch_approval_id IS NULL)
  OR
  (export_type = 'final' AND batch_approval_id IS NOT NULL)
);
```

Composite same-version integrity:

```sql
ALTER TABLE bank_excel_exports
ADD CONSTRAINT fk_export_approval_same_version
FOREIGN KEY (batch_approval_id, payment_batch_version_id)
REFERENCES batch_approvals(id, payment_batch_version_id);
```

Partial unique active final export:

```sql
CREATE UNIQUE INDEX uq_active_final_export_per_version
ON bank_excel_exports(payment_batch_version_id)
WHERE export_type = 'final'
  AND status IN ('generated','validated','downloaded','sent_to_bank_marked');
```

Before a final download or sent-to-bank action, the service verifies:

```text
export.content_hash == batch_version.content_hash
approval.approved_content_hash == batch_version.content_hash
export.row_count == batch_version.row_count
export.total_amount_irr == batch_version.total_amount_irr
```

Mismatch quarantines the export and creates audit/review events.

## 11.9 `payment_result_publications`

Immutable versions of the trader-visible result/share output. This table is required because a published result may later be corrected without erasing what was previously shown or shared.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK |
| `payment_request_id` | UUID | yes | FK |
| `publication_version` | INTEGER | yes | Monotonic per request |
| `status` | VARCHAR(24) | yes | `active`, `superseded`, `revoked` |
| `summary_payload` | JSONB | yes | Exact trader-visible fields |
| `share_file_id` | UUID | no | Generated image/PDF |
| `primary_evidence_link_id` | UUID | no | Evidence visible in this publication |
| `content_hash` | CHAR(64) | yes | Canonical publication content |
| `published_by_admin_user_id` | UUID | yes | |
| `published_at` | TIMESTAMPTZ | yes | |
| `supersedes_publication_id` | UUID | no | Self FK |
| `correction_reason` | TEXT | no | Required when superseding |
| `created_at` | TIMESTAMPTZ | yes | |

```sql
UNIQUE(payment_request_id, publication_version);
UNIQUE(payment_request_id, content_hash);

CREATE UNIQUE INDEX uq_active_publication_per_request
ON payment_result_publications(payment_request_id)
WHERE status = 'active';
```

A correction creates a new publication, marks the previous row `superseded`, updates the request aggregate state, creates an audit/outbox event, and notifies the trader. Previously generated/shareable artifacts remain retained according to policy.

---

# 12. Bank Result, Receipt Segment, and Matching Schema

## 12.1 `bank_result_bundles`

Fields: `id`, `bundle_number`, `bank_profile_id` nullable, `status`, `source_type`, `notes`, `uploaded_by_admin_user_id`, `uploaded_at`, `segment_count`, `resolved_segment_count`, `unresolved_segment_count`, `record_version`, `closed_at`, `closed_by_admin_user_id`, timestamps.

```sql
UNIQUE(bundle_number);
CHECK (segment_count >= 0);
CHECK (resolved_segment_count >= 0);
CHECK (unresolved_segment_count >= 0);
```

Counts are cached read values and must be recomputed/validated transactionally from segments/tasks; they are not independent financial truth.

## 12.2 `bank_result_bundle_files`

Fields: `id`, `bank_result_bundle_id`, `file_id`, `sequence_number`, `file_role`, `page_count`, `created_at`.

```sql
UNIQUE(bank_result_bundle_id, file_id);
UNIQUE(bank_result_bundle_id, sequence_number, file_role);
CHECK (sequence_number > 0);
```

`file_role`: `source`, `normalized`, `preview`, `structured_result`.

## 12.3 `bank_result_bundle_batch_links`

Optional many-to-many operational association between a bundle and batch/version.

Fields: `id`, `bank_result_bundle_id`, `payment_batch_id`, `payment_batch_version_id` nullable, `link_method`, `status`, `created_by_admin_user_id`, `created_at`, `replaced_at`.

This association does not prove payment completion. Attempt/segment confirmation remains authoritative.

## 12.4 `receipt_segments`

Smallest evidence unit, including a Phase 1A manual crop.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK |
| `bank_result_bundle_id` | UUID | no | Standalone evidence allowed |
| `bank_result_bundle_file_id` | UUID | no | Source within bundle |
| `source_file_id` | UUID | yes | Original/page file |
| `segment_file_id` | UUID | no | Crop/derived file |
| `page_number` | INTEGER | no | 1-based |
| `bbox_x` | NUMERIC(10,6) | no | Normalized 0..1 |
| `bbox_y` | NUMERIC(10,6) | no | Normalized 0..1 |
| `bbox_width` | NUMERIC(10,6) | no | Normalized >0..1 |
| `bbox_height` | NUMERIC(10,6) | no | Normalized >0..1 |
| `source_pixel_width` | INTEGER | no | Reproduction metadata |
| `source_pixel_height` | INTEGER | no | |
| `renderer_version` | VARCHAR(64) | no | |
| `creation_method` | VARCHAR(32) | yes | |
| `status` | VARCHAR(32) | yes | |
| `extracted_beneficiary_name` | VARCHAR(255) | no | Suggestion/manual field |
| `extracted_destination_iban` | CHAR(26) | no | |
| `extracted_amount_irr` | BIGINT | no | |
| `extracted_tracking_number` | VARCHAR(128) | no | |
| `extracted_payment_at` | TIMESTAMPTZ | no | |
| `raw_extraction` | JSONB | no | |
| `extraction_confidence` | NUMERIC(5,4) | no | 0..1 |
| `created_by_actor_type` | VARCHAR(24) | yes | |
| `created_by_actor_id` | UUID | no | |
| `record_version` | BIGINT | yes | Only until finalized |
| `created_at` | TIMESTAMPTZ | yes | |
| `updated_at` | TIMESTAMPTZ | yes | |

```sql
CHECK (page_number IS NULL OR page_number > 0);
CHECK (extracted_amount_irr IS NULL OR extracted_amount_irr > 0);
CHECK (extraction_confidence IS NULL OR
       (extraction_confidence >= 0 AND extraction_confidence <= 1));
CHECK (
  (bbox_x IS NULL AND bbox_y IS NULL AND bbox_width IS NULL AND bbox_height IS NULL)
  OR
  (bbox_x >= 0 AND bbox_y >= 0 AND bbox_width > 0 AND bbox_height > 0
   AND bbox_x + bbox_width <= 1
   AND bbox_y + bbox_height <= 1)
);
```

Creation methods:

```text
manual_external_attachment
manual_in_panel_crop
manual_structured_result
excel_row_import
ai_auto_segmentation
```

`manual_in_panel_crop` is enabled in Phase 1A; `ai_auto_segmentation` remains feature-flagged for later phases.

## 12.5 `matching_candidates`

Suggestions only. For Phase 1A outgoing-payment matching, use explicit FKs.

Fields: `id`, `receipt_segment_id`, `payment_attempt_id`, `method`, `score`, `reasons`, `status`, `provider_job_id`, `created_by_actor_type`, `created_by_actor_id`, `created_at`, `resolved_at`.

```sql
UNIQUE(receipt_segment_id, payment_attempt_id, method);
CHECK (score IS NULL OR (score >= 0 AND score <= 1));
```

Statuses: `proposed`, `accepted_for_confirmation`, `rejected`, `superseded`, `expired`.

Accepting a candidate does not itself set an attempt to paid; a human confirmation command creates/activates the confirmed link and updates the attempt in one transaction.

## 12.6 `confirmed_evidence_links`

Authoritative relationship between a receipt segment and a payment attempt.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK |
| `payment_attempt_id` | UUID | yes | FK |
| `receipt_segment_id` | UUID | yes | FK |
| `link_type` | VARCHAR(24) | yes | `primary`, `supplementary` |
| `status` | VARCHAR(24) | yes | `active`, `replaced`, `voided` |
| `confirmed_by_admin_user_id` | UUID | yes | Human actor |
| `confirmed_at` | TIMESTAMPTZ | yes | |
| `replaces_link_id` | UUID | no | Self FK |
| `replacement_reason` | TEXT | no | |
| `published_to_trader_at` | TIMESTAMPTZ | no | |
| `created_at` | TIMESTAMPTZ | yes | |

```sql
UNIQUE(payment_attempt_id, receipt_segment_id, link_type);

CREATE UNIQUE INDEX uq_attempt_active_primary_evidence
ON confirmed_evidence_links(payment_attempt_id)
WHERE link_type = 'primary' AND status = 'active';

CREATE UNIQUE INDEX uq_segment_active_primary_attempt
ON confirmed_evidence_links(receipt_segment_id)
WHERE link_type = 'primary' AND status = 'active';
```

Replacing a primary link marks the previous row `replaced` and inserts a new row in the same transaction. It never deletes or overwrites the old relationship.

---

# 13. Work Queues, Comments, and Notifications

## 13.1 `manual_review_tasks`

Fields: `id`, `task_type`, `priority`, `status`, `entity_type`, `entity_id`, `assigned_to_admin_user_id`, `title`, `description`, `due_at`, `resolved_by_admin_user_id`, `resolved_at`, `resolution_code`, `resolution_note`, `record_version`, timestamps.

```sql
CREATE INDEX idx_manual_review_open_queue
ON manual_review_tasks(status, priority DESC, created_at)
WHERE status IN ('open','in_progress');
CREATE INDEX idx_manual_review_assignee
ON manual_review_tasks(assigned_to_admin_user_id, status, created_at);
```

Use generic entity references only for queue navigation. Financial relationship truth remains in explicit tables.

## 13.2 `comments`

Structured record notes, not chat.

Fields: `id`, `entity_type`, `entity_id`, `scope`, `author_actor_type`, `author_actor_id`, `body`, `created_at`, `superseded_at`.

Sensitive comments are never physically deleted through normal UI. Corrections create superseding comments or audit records.

## 13.3 `notifications`

Fields: `id`, `recipient_actor_type`, `recipient_actor_id`, `notification_type`, `title`, `body`, `entity_type`, `entity_id`, `status`, `deduplication_key`, `read_at`, `created_at`.

```sql
CREATE UNIQUE INDEX uq_notification_dedup
ON notifications(recipient_actor_type, recipient_actor_id, deduplication_key)
WHERE deduplication_key IS NOT NULL;
```

Notifications are produced from outbox events. They are not the source of workflow truth.

---

# 14. Background Processing Tables

## 14.1 `processing_jobs`

Use one generic job table for Phase 1A file/export/notification jobs and future AI tasks. Do not call every file job an AI job.

Fields:

- `id`, `job_type`, `queue_name`, `status`;
- `input_entity_type`, `input_entity_id`;
- `provider`, `provider_version` nullable;
- `input_payload`, `output_payload`;
- `idempotency_key`, `attempt_count`, `max_attempts`;
- `available_at`, `started_at`, `heartbeat_at`, `finished_at`;
- `locked_by`, `last_error_code`, `last_error_message`;
- timestamps.

Statuses:

```text
queued, running, succeeded, failed, retry_scheduled,
cancelled, dead_lettered, fallback_to_manual
```

```sql
UNIQUE(job_type, idempotency_key)
  -- implement as a partial unique index when key is not null
```

Queue names begin with: `files`, `exports`, `notifications`, `reports`, `maintenance`, `ai`.

Workers do not authorize or finalize financial actions.

## 14.2 `ai_usage_logs`

Optional Phase 1B+ usage/cost metadata. Fields: `id`, `processing_job_id`, `provider`, `model_name`, `operation_type`, token/input/output measures, `cost_usd`, `duration_ms`, `success`, `error_code`, `metadata`, `created_at`.

Provider payload retention follows the approved privacy/retention policy.

---

# 15. Idempotency, Outbox, and Audit

## 15.1 `idempotency_records`

Required for critical commands.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK |
| `actor_type` | VARCHAR(24) | yes | |
| `actor_id` | UUID | yes | |
| `operation` | VARCHAR(96) | yes | Stable command name |
| `idempotency_key` | VARCHAR(128) | yes | Client/generated key |
| `request_hash` | CHAR(64) | yes | Canonical request payload |
| `status` | VARCHAR(24) | yes | `in_progress`, `completed`, `failed` |
| `resource_type` | VARCHAR(64) | no | Result entity |
| `resource_id` | UUID | no | |
| `response_code` | INTEGER | no | |
| `response_body` | JSONB | no | Sanitized replay response |
| `locked_until` | TIMESTAMPTZ | no | Recovery from abandoned execution |
| `expires_at` | TIMESTAMPTZ | yes | Retention depends on operation |
| `created_at` | TIMESTAMPTZ | yes | |
| `completed_at` | TIMESTAMPTZ | no | |

```sql
UNIQUE(actor_type, actor_id, operation, idempotency_key);
CREATE INDEX idx_idempotency_expiry ON idempotency_records(expires_at);
```

Same key + different request hash is a conflict. Same key + same hash returns the existing logical result.

Critical operations include request submission, batch creation, batch-version finalization, manager decision, final export generation, sent-to-bank marking, payment confirmation, evidence correction, and result publication.

## 15.2 `outbox_events`

Inserted in the same transaction as business changes and audit events.

Fields: `id`, `aggregate_type`, `aggregate_id`, `event_type`, `payload`, `headers`, `status`, `available_at`, `attempt_count`, `locked_at`, `locked_by`, `published_at`, `last_error`, `created_at`.

```sql
CREATE INDEX idx_outbox_dispatch
ON outbox_events(status, available_at, created_at)
WHERE status IN ('pending','retry');
```

Workers claim rows using `FOR UPDATE SKIP LOCKED`. Event handlers must be idempotent.

## 15.3 `audit_logs`

Append-only financial/security audit record.

| Column | Type | Required | Notes |
|---|---:|---:|---|
| `id` | UUID | yes | PK |
| `event_type` | VARCHAR(128) | yes | |
| `entity_type` | VARCHAR(64) | yes | |
| `entity_id` | UUID | yes | |
| `actor_type` | VARCHAR(24) | yes | |
| `actor_id` | UUID | no | |
| `actor_role_snapshot` | JSONB | yes | Default `[]` |
| `reason` | TEXT | no | |
| `previous_values` | JSONB | no | Redacted where necessary |
| `new_values` | JSONB | no | |
| `metadata` | JSONB | yes | Default `{}` |
| `request_id` | UUID | no | Correlation ID |
| `idempotency_record_id` | UUID | no | |
| `ip_address` | INET | no | |
| `user_agent` | TEXT | no | |
| `previous_event_hash` | CHAR(64) | no | Optional tamper-evident chain |
| `event_hash` | CHAR(64) | no | Optional |
| `created_at` | TIMESTAMPTZ | yes | |

```sql
CREATE INDEX idx_audit_entity_time
ON audit_logs(entity_type, entity_id, created_at DESC);
CREATE INDEX idx_audit_actor_time
ON audit_logs(actor_type, actor_id, created_at DESC);
CREATE INDEX idx_audit_event_time
ON audit_logs(event_type, created_at DESC);
```

Application roles receive no `UPDATE` or `DELETE` grants on `audit_logs`. Audit JSON must not contain passwords, raw tokens, secret keys, or unnecessary complete bank documents.

---

# 16. Settings, Retention, and Legal Holds

## 16.1 `system_settings`

For ordinary versioned application settings that are not secrets.

Fields: `id`, `key`, `value`, `value_type`, `category`, `status`, `record_version`, `updated_by_admin_user_id`, timestamps.

```sql
UNIQUE(key)
```

Secrets belong in deployment secret management, not this table.

## 16.2 `feature_flags`

Fields: `id`, `flag_key`, `is_enabled`, `rollout_config`, `record_version`, `updated_by_admin_user_id`, timestamps.

```sql
UNIQUE(flag_key)
```

Phase 1A defaults:

```text
manual_crop.enabled = true
auto_segmentation.enabled = false
ocr.enabled = false
ai_matching.enabled = false
bank_api.enabled = false
```

## 16.3 `retention_policies`

Approved policy metadata, not an automatic delete switch.

Fields: `id`, `policy_name`, `record_category`, `retention_days`, `status`, `effective_from`, `approved_by_admin_user_id`, `approved_at`, `legal_basis_note`, `record_version`, timestamps.

Reducing a duration creates a new version/policy and does not immediately delete historical records.

## 16.4 `legal_holds`

Fields: `id`, `scope_type`, `scope_id`, `reason`, `status`, `placed_by_admin_user_id`, `placed_at`, `released_by_admin_user_id`, `released_at`, `release_reason`, timestamps.

Any future physical-deletion job must prove no active applicable legal hold exists and must produce a dry-run report and audit trail.

---

# 17. Critical Cross-Table Invariants

The following are mandatory application-service transactions and, where practical, deferred constraints/triggers.

## 17.1 Trader eligibility

A trader may submit a financial request only when:

```text
trader.approval_status = approved
trader.operational_status = active
trader_user.status = active
```

## 17.2 Request revision ownership

`payment_requests.current_revision_id` must point to a revision whose `payment_request_id` equals the request ID. Implement with a composite unique/FK:

```sql
ALTER TABLE payment_request_revisions
ADD CONSTRAINT uq_request_revision_pair UNIQUE(id, payment_request_id);

ALTER TABLE payment_requests
ADD CONSTRAINT fk_request_current_revision
FOREIGN KEY (current_revision_id, id)
REFERENCES payment_request_revisions(id, payment_request_id)
DEFERRABLE INITIALLY DEFERRED;
```

The same composite-FK pattern is required for `payment_batches.current_version_id`:

```sql
ALTER TABLE payment_batch_versions
ADD CONSTRAINT uq_batch_version_pair UNIQUE(id, payment_batch_id);

ALTER TABLE payment_batches
ADD CONSTRAINT fk_batch_current_version
FOREIGN KEY (current_version_id, id)
REFERENCES payment_batch_versions(id, payment_batch_id)
DEFERRABLE INITIALLY DEFERRED;
```

## 17.3 Attempt/request revision consistency

An attempt's revision must belong to the same payment request. Use a composite FK to `payment_request_revisions(id, payment_request_id)`.

## 17.4 Batch version content

For one version:

```text
row_count = count(payment_batch_items)
total_amount_irr = sum(item attempt snapshot amount)
content_hash = canonical hash of ordered items + configuration context
```

The service calculates and locks these values in one transaction. A validation trigger may reject direct inconsistent writes.

## 17.5 Approval validity

A batch is operationally approved only if:

```text
current version status = approved
one batch_approval exists for that version
approval.decision = approved
approval.approved_content_hash = version.content_hash
payment_batch.current_version_id = approved version
```

A new current version changes the batch state to `approval_invalidated` or `ready_for_approval`; old approvals remain historical.

## 17.6 Export integrity

A final export is sendable only if its version, approval, bank profile version, mapping, source account, row count, total, and hash all match the approved snapshot.

## 17.7 Attempt allocation and payment aggregate

The service locks the request and relevant attempts before creating split/retry attempts or confirming results.

- Active unsent/sent allocation must not double-allocate the same unpaid amount.
- Superseded/cancelled attempts do not count toward active allocation.
- Paid sum is based only on authoritative `paid` attempts.
- Exact paid sum equals request amount for `paid`.
- Greater-than-request paid sum creates a reconciliation task and blocks normal closure.

## 17.8 Evidence cardinality

Partial unique indexes enforce one active primary evidence link per attempt and one active primary attempt per segment. Supplementary evidence is allowed.

## 17.9 Immutable source records

The following are insert-only or only allow controlled status fields:

- used bank-profile versions and mappings;
- payment request revisions;
- batch versions and items after finalization;
- batch approvals;
- original file metadata/key/hash after availability;
- bank statement rows;
- confirmed/replaced evidence-link history;
- audit logs.

## 17.10 Atomic financial command pattern

A critical command commits together:

```text
business changes
aggregate/version updates
audit log
outbox event
idempotency result
```

A crash after commit is recovered from outbox/idempotency data; a crash before commit produces no partial financial state.

---

# 18. Index Strategy

## 18.1 Operational queues

Use partial indexes matching real queue predicates:

```sql
CREATE INDEX idx_payment_request_accountant_queue
ON payment_requests(status, submitted_at, created_at)
WHERE status IN ('submitted_to_center','under_accountant_review',
                 'needs_trader_correction','eligible_for_batching',
                 'retry_required','trader_disputed');

CREATE INDEX idx_batch_manager_queue
ON payment_batch_versions(created_at)
WHERE status = 'ready_for_approval';

CREATE INDEX idx_bundle_review_queue
ON bank_result_bundles(status, uploaded_at)
WHERE status IN ('ready_for_manual_review','partially_matched','failed');
```

## 18.2 Matching

```sql
CREATE INDEX idx_attempt_match_amount_iban
ON payment_attempts(amount_irr, beneficiary_iban_snapshot)
WHERE status IN ('sent_to_bank','bank_result_pending','failed','retry_required');

CREATE INDEX idx_segment_match_amount_iban
ON receipt_segments(extracted_amount_irr, extracted_destination_iban)
WHERE status IN ('unmatched','candidate_found','needs_review');
```

Use trigram indexes only after measuring query behavior and normalizing Persian/Arabic characters.

## 18.3 Time-series append-only tables

For very large `audit_logs`, `auth_events`, and `outbox_events`, consider BRIN indexes or partitioning only after measured growth. Do not partition Phase 1A prematurely.

## 18.4 Foreign-key indexes

PostgreSQL does not automatically index referencing columns. Every frequently joined or deleted-parent FK needs an explicit index.

## 18.5 Avoid redundant indexes

Each unique constraint already creates an index. Review `EXPLAIN (ANALYZE, BUFFERS)` before adding overlapping indexes.

---

# 19. Transaction and Locking Requirements

## 19.1 Isolation level

Use PostgreSQL `READ COMMITTED` by default with explicit row locks and optimistic versions. Use `SERIALIZABLE` only for isolated operations proven to need it, with retry handling.

## 19.2 Required row locks

Use `SELECT ... FOR UPDATE` when:

- finalizing a request revision;
- creating split/retry attempts;
- finalizing a batch version;
- approving/rejecting a batch version;
- generating a final bank export;
- marking an export/batch sent to bank;
- confirming a payment attempt;
- replacing a confirmed evidence link;
- publishing a result;
- changing a trader's approval/status during an active command.

Use deterministic lock ordering to reduce deadlocks.

## 19.3 Worker claims

Outbox/jobs use `FOR UPDATE SKIP LOCKED` with lease/heartbeat fields. A timed-out lease can be reclaimed. Workers must tolerate at-least-once delivery.

## 19.4 Derived counters

Bundle counts, dashboard counts, and request aggregate states may be cached but must be recomputable. They never replace underlying attempt/segment/task records.

---

# 20. Database-Level Security and Privacy

- Production connections require TLS where supported by topology.
- Secrets and encryption keys are not stored in normal settings tables.
- Full IBAN/national ID access is role-controlled in the application; logs use masked values.
- `technical_admin` does not automatically receive financial-file read rights.
- File downloads create audit/access events according to security policy.
- Database backups are encrypted and access-controlled.
- Staging/development use fake or anonymized data only.
- Row-level security may be evaluated as defense-in-depth after ADR approval, but Phase 1A trader isolation is mandatory in repository/service queries and authorization tests.
- Dynamic SQL must be parameterized; bank mapping values never become untrusted SQL identifiers without strict allowlists.

---

# 21. Migration and Deployment Strategy

## 21.1 Alembic only

All schema changes are version-controlled Alembic migrations. No manual production DDL is allowed except documented emergency actions followed by an equivalent migration and incident record.

## 21.2 Expand/contract migrations

For production-safe changes:

1. add nullable/new structures;
2. deploy code capable of reading both old/new forms;
3. backfill in bounded batches;
4. validate constraints using `NOT VALID` / `VALIDATE CONSTRAINT` where appropriate;
5. switch reads/writes;
6. remove old columns only in a later release.

## 21.3 Index creation

Large production indexes use `CREATE INDEX CONCURRENTLY` in a migration strategy that avoids wrapping the command in a transaction.

## 21.4 Constraint validation

Do not add a heavy `NOT NULL` or table-scan constraint without assessing locks and data volume. Backfill and validate safely.

## 21.5 Rollback philosophy

Database rollback is usually a forward-fix, not destructive downgrade. Every release includes:

- pre-deployment backup/restore confidence;
- migration review;
- compatibility window;
- rollback or roll-forward instructions;
- verification queries.

## 21.6 Seed data

Seed only:

- system roles and permissions;
- required feature flags;
- one center profile;
- safe application defaults.

Do not seed invented bank rules, fake transfer limits, or placeholder production profiles. Initial bank profiles, accounts, templates, mappings, and limits are imported from approved anonymized fixtures and reviewed before activation.

---

# 22. Phase 1A Table Boundary

## 22.1 Required

```text
center_profile
admin_users
trader_users
auth_sessions
auth_events
roles
permissions
role_permissions
admin_user_roles

traders
trader_bank_accounts
beneficiaries

bank_profiles
bank_profile_versions
bank_accounts
bank_mappings

file_objects
file_links
file_derivations

gold_sale_orders
gold_sale_pricing_versions
incoming_payment_receipts
bank_statement_files
bank_statement_import_runs
bank_statement_rows
incoming_payment_matches
gold_dispatches

payment_requests
payment_request_revisions
payment_attempts
payment_batches
payment_batch_versions
payment_batch_items
batch_approvals
bank_excel_exports
payment_result_publications

bank_result_bundles
bank_result_bundle_files
bank_result_bundle_batch_links
receipt_segments
matching_candidates
confirmed_evidence_links

manual_review_tasks
comments
notifications
processing_jobs

idempotency_records
outbox_events
audit_logs
system_settings
feature_flags
retention_policies
legal_holds
```

## 22.2 Optional/future-active

```text
ai_usage_logs
external_validation_results
bank_api_connection_records
accounting_integration_records
advanced risk/anomaly tables
multi-company/tenant tables
```

Future tables may exist behind migrations/flags, but they must not complicate or become dependencies of Phase 1A operations.

---

# 23. Implementation Prohibitions

Coding agents and developers must not:

1. add `center_id` to every table as partial SaaS preparation;
2. store a mutable balance without an authoritative ledger;
3. store money as floating point;
4. store manager approval on individual payment requests as the primary Phase 1A approval model;
5. store one mutable `payment_batch_id` on attempts as the only batch history;
6. generate a final export from a mutable or unapproved batch;
7. combine match candidates and confirmed evidence links in one ambiguous table;
8. keep a single mutable `receipt_segment_id` on `payment_attempts`;
9. store generic `matched_entity_type/id` on bank statement rows as match truth;
10. hard-delete or generically soft-delete financial records;
11. mutate used bank configurations, batch versions, approvals, or original files;
12. rely on JSONB instead of relational core entities;
13. allow workers or AI jobs to authorize/confirm payment;
14. treat visibility flags as authorization;
15. use real bank/customer data in development fixtures;
16. run destructive production migrations without backup, review, and an operational plan.

---

# 24. Acceptance Criteria

This database schema is approved for implementation only when migrations and automated tests prove that:

1. a trader and trader user can be created, approved, suspended, and isolated;
2. a beneficiary is reusable but historical requests preserve snapshots;
3. original amount value/unit and canonical IRR are preserved correctly;
4. a request amendment creates a new immutable revision;
5. split/retry attempts remain traceable to the request and revision;
6. attempt allocation cannot silently exceed the request amount;
7. a batch has immutable ordered versions and items;
8. manager approval references one exact version and content hash;
9. material change invalidates operational use of prior approval;
10. a final bank export cannot exist without a same-version approval;
11. final export totals/hash/version match the approved snapshot;
12. bank profile/mapping versions preserve historical interpretation;
13. every trader-visible publication is immutable/versioned and corrections preserve prior output;
14. original files are private and immutable after finalization;
15. image/PDF preview and minimal manual crop can produce a traceable segment;
16. match candidates cannot directly finalize a payment;
17. one active primary evidence link per attempt/segment is enforced;
18. replacing evidence preserves the previous link;
19. bank statement reparsing preserves prior import runs and raw rows;
20. unmatched results remain visible through tasks/queues;
21. critical commands are idempotent and stale writes conflict safely;
22. financial changes, audit, outbox, and idempotency result commit atomically;
23. append-only/immutable tables cannot be modified by normal application roles;
24. retention reduction does not trigger immediate deletion and legal holds block future deletion;
25. all required FKs have appropriate indexes and delete actions;
26. migrations run successfully on an empty database and through an upgrade test from the previous schema;
27. backup/restore testing confirms database/file referential integrity.

---

# 25. Next Document

The next document is:

```text
05_API_Specification.md
```

It must be revised against this schema and define:

- resource and command endpoints;
- immutable revision/version representations;
- batch approval and export integrity contracts;
- `Idempotency-Key` behavior;
- expected-version / `If-Match` concurrency behavior;
- secure upload/preview/crop flows;
- explicit candidate versus confirmation commands;
- authorization and trader ownership rules;
- consistent errors, pagination, filtering, and audit correlation.
