# M2 Implementation Plan — Persistence and Integrity Foundation

Status: Working implementation plan for hand-off to implementers. Not an approved M0 artifact.
Milestone authority: `Implementation Docs/00_Start_Here/15_Agent_Implementation_Plan.md:519-597`.
Precondition: M1 as merged (`app/db/{base,session,unit_of_work,migrations}.py`,
`app/core/{config,errors,logging,request_context,runtime,time}.py`, Alembic baseline
`services/backend/alembic/versions/20260720_0001_runtime_baseline.py`, and the compose `migrate`
one-shot that runs `alembic upgrade head` as `MIGRATION_DB_USER`).
Date of this revision: 2026-08-01.

Every claim traceable to a document is cited as `path:line`. Where this plan resolves a divergence
between authorities, the divergence is named and the resolution is recorded in section 2.3 so it can
be raised in the pull request rather than decided silently inside a migration.

---

# 1. What M2 delivers, and the Definition of Done

## 1.1 Scope, as the milestone authority states it

`15_Agent_Implementation_Plan.md:521-523` sets the goal: "Build the database and application
integrity mechanisms required by every later financial command."

`:525-541` requires the Alembic foundation for `center_profile`, admin and trader identity tables,
roles/permissions/assignments, auth sessions and auth events, the bank-profile and configuration
foundation, file metadata and relationships, idempotency records, outbox events, append-only audit
logs, durable processing jobs, and retention policies and legal holds where required by the approved
schema — and forbids an `organizations` or partial tenant model.

`:543-557` requires the application foundation: session factory, Unit of Work, repository
interfaces, the one-commit command pattern, transaction-safe audit writer, transaction-safe outbox
writer, idempotency resolver and result store, optimistic-concurrency helpers, lock helpers with
deterministic lock ordering, canonical money serializers, and canonical entity/version/hash
utilities.

`:559-565` requires five separate database roles (migration, API runtime, worker runtime, read-only,
backup) and states: "Runtime roles must not own the schema or update/delete append-only audit and
approval records."

`:571-582` fixes the migration gate: clean database to head; previous supported schema to head;
migration retry after a controlled failure; all constraints and indexes created; PostgreSQL
repository tests, not SQLite substitutes; audit-insert failure rolls back the business transaction;
outbox-insert failure rolls back the business transaction; idempotency replay returns the original
result.

## 1.2 Definition of Done (verbatim)

`15_Agent_Implementation_Plan.md:586`:

> M2 is complete when a sample command can atomically write business state, audit, outbox, and
> idempotency result through Unit of Work and all rollback tests pass.

The milestone evidence gate in `docs/governance/TRACEABILITY_MATRIX.md:24` restates this and adds
the second half that the DoD sentence does not: "Clean and supported-upgrade migrations pass on
PostgreSQL; sample command atomically writes business state, audit, outbox, and idempotency result;
audit/outbox failure rolls back; replay returns the same logical result; runtime roles cannot mutate
append-only records."

Two consequences follow, and both drive the slice order:

1. Slice 1 alone satisfies the DoD sentence. It is therefore deliberately the largest slice; every
   part of it is a precondition of that one piece of evidence.
2. "Runtime roles cannot mutate append-only records" is a GRANT-level claim proven only by a session
   connected as the runtime role. Slice 2 exists because that claim cannot be delegated to an ORM
   convention or a Python guard.

The same matrix row records M2's admissible status: "Provisional — integrity primitives may proceed;
disputed domain tables may not" (`TRACEABILITY_MATRIX.md:24`). That is the distinction every
"structure free, values blocked" decision in section 3 turns on.

---

# 2. Authority, precedence, and the naming decisions this plan makes

## 2.1 Precedence order

`15_Agent_Implementation_Plan.md` §2.2 fixes the order: approved decision/ADR → security and
financial invariants → domain/workflow rules → database integrity → API contract →
architecture/implementation guides → UI/UX → future-phase guidance. It also forbids silently
choosing an interpretation and requires the conflict to be recorded in the task and pull request.

Approved baselines that bind M2 directly:

| Baseline | What it settles for M2 |
|---|---|
| `docs/governance/FINANCIAL_INTEGRITY_BASELINE.md` §4 (`:73-93`) | Audit evidence uses first-class typed columns; JSON metadata requires `metadata_schema` + `metadata_version` and cannot replace a required column; rows are append-only and commit in the business transaction. Resolves DOC-CONFLICT-020 (`CONFLICT_REGISTER.md:42`). |
| `FINANCIAL_INTEGRITY_BASELINE.md` §3 (`:47-71`) | `recent_auth_contexts` bound to actor, session, action/purpose and resource, with expiry, revocation and consumption recorded in the command transaction. Factor and duration remain ADR-009. |
| `FINANCIAL_INTEGRITY_BASELINE.md` §5 (`:95-110`) | `finalizer != approver`, not configurable off; break-glass activation, permission grants, endpoints, **feature flags** and runtime bypasses are disabled for Phase 1A. |
| `FINANCIAL_INTEGRITY_BASELINE.md` §1 | Durable export job separate from the immutable artifact; the export **job** lifecycle `queued/running/succeeded/failed` is approved text. |
| `docs/governance/status_catalog.yaml` (approved 2026-08-01, `:4-11`) | Canonical status values. `outbox_event` = `pending/processing/published/failed/dead_lettered` (`:583-592`); `processing_job` = eight values (`:602-614`). `retry` is an unresolved alias with `canonical: null` (`:593-599`). |
| `docs/governance/permission_catalog.yaml` (approved 2026-08-01) | Canonical permission identifiers and baseline roles. Document 05 spellings are deprecated aliases (DOC-CONFLICT-013, `CONFLICT_REGISTER.md:35`). |
| `docs/governance/MONEY_TIME_CONTRACT.md` + ADR-006 (`docs/adr/ADR_INDEX.md:34`) | Integer IRR money, TIMESTAMPTZ/UTC persistence, `Asia/Tehran` business-day interpretation. |
| DOC-CONFLICT-022 (`CONFLICT_REGISTER.md:44`) | PostgreSQL 16 is required in local, CI, staging and production. |

Catalogues that remain **provisional pending M0 approval**: `audit_outbox_catalog.yaml`,
`api_error_catalog.yaml`, `command_catalog.yaml`. Their table structures and transaction rules are
required now; their **names** are not frozen, which is why slice 1 puts every audit action string and
outbox event type behind one indirection layer (section 4.1).

## 2.2 Naming decisions that are settled, not invented

**The audit table is named `audit_logs`.** Every authority uses that identifier:
`04_Database_Schema.md:278` (entity map), `:1436` (§15.3 table definition), `:1847` (§22.1 active
Phase 1A table inventory), `05_API_Specification.md:729` (aggregate inventory), and
`10_Backend_Implementation_Guide.md:570` declares the Unit of Work attribute
`audit_logs: "AuditRepository"` with `:666` using `uow.audit_logs.add(...)`. No document anywhere in
the repository contains the string `audit_events`. Doc 12 §20.3 (`12_Security_RBAC_Audit.md:1602-1633`)
supplies 24 field names and no table name; `FINANCIAL_INTEGRITY_BASELINE.md` §4 supplies columns and
no table name. There is therefore **no inter-document conflict for precedence to resolve**, and an
`audit_events` rename would be a unilateral deviation made permanent in a migration that can never be
edited. Implementers use `audit_logs`, and the Unit of Work exposes the writer as `uow.audit_logs`
so `10_Backend_Implementation_Guide.md:570`'s protocol is honoured.

**The security-event table is named `auth_events`** — doc 04's required table name
(`04_Database_Schema.md:438`, `:1795`) carrying doc 12's required column set and its twenty security
event types. The name/scope reconciliation is recorded (section 2.3, item d).

**Decision identifiers use the canonical namespace.** `ADR_INDEX.md:20-24` records the approved
DOC-CONFLICT-003 rule: `Open_ADR_Register` IDs are the only canonical namespace and every `ADR-01x`
identifier is an alias. File size/type limits are therefore **POL-006** (`ADR_INDEX.md:56`), never
`ADR-014`. `ADR_INDEX.md:56` additionally records that ADR-014 is broader than POL-006 because it
adds operational volume, and `ADR_INDEX.md:94` lists that remainder as an unrepresented composite
alias scope requiring explicit owner mapping — so tickets must cite POL-006 and must **not** assert
that the volume remainder is out of Phase 1A scope, because no owner has decided that. The same rule
applies to OPS-001/OPS-002, which per DOC-CONFLICT-012 (`CONFLICT_REGISTER.md:34`) must always be
qualified with their source document.

## 2.3 Divergences this plan resolves by precedence — all must be recorded in the PR

Each row is a permanent choice inside a migration. Each is implemented as a **named** (therefore
alterable) constraint or as a deliberately **omitted** constraint, and each must appear in the pull
request body with the reasoning below, plus a request for owner confirmation.

| # | Divergence | Sources | Resolution in M2 | Mechanism |
|---|---|---|---|---|
| a | Audit `actor_type` vocabulary | `04_Database_Schema.md:1444` gives `VARCHAR(24)` with doc-04 prose values; `12_Security_RBAC_Audit.md:1591-1597` gives `trader_user/admin_user/system_worker/system_maintenance`. Not in `CONFLICT_REGISTER.md`. | Doc 12 wins under §2.2 (security invariants above database integrity). | Named CHECK `ck_audit_logs_actor_type`, alterable. A missing constraint is the worse hole. |
| b | Audit column vocabulary vs doc 04 §15.3 | `04_Database_Schema.md:1440-1458` names `event_type`, `previous_values`, `new_values`, and a single `request_id` described as "Correlation ID". `FINANCIAL_INTEGRITY_BASELINE.md:77-82` requires action, outcome, schema version, session and recent-auth IDs, assurance, parent entity, entity version and hash, and **correlation ID, causation ID and request ID as separate fields**. | Baseline §4 vocabulary wins (approved decision beats database integrity). `action` replaces `event_type`; the three IDs are three columns; doc 04's `previous_values`/`new_values` are retained as names with write-time redaction; doc 04's `idempotency_record_id`, `previous_event_hash`, `event_hash` are retained nullable. | Superset table. Doc-04 index names `idx_audit_entity_time` and `idx_audit_actor_time` retained verbatim (`04:1461-1466`); `idx_audit_event_time` (`04:1467`) becomes `idx_audit_action_time` because the column is `action`. Recorded. |
| c | `file_objects.storage_status` | Seven values stated identically by `04_Database_Schema.md:637`, `12_Security_RBAC_Audit.md:1456-1468`, `14_Testing_QA_Acceptance.md:555-563`, `18_Production_Setup_and_Runbook.md:707-715`; `status_catalog.yaml:617-632` records `file_object` with `canonical: null` and states `deleted` vs `deleted_by_policy` "must not be canonicalized here". | Ship the named seven-value CHECK excluding `deleted_by_policy`, on a recorded reconciliation. If owner sign-off is unavailable at merge, ship **no** value CHECK and add it by expand/contract. | Named CHECK or deliberate omission; application-enforced fail-closed either way. |
| d | `file_objects.scan_status` | `04_Database_Schema.md:638` gives `not_scanned/pending/clean/suspicious/failed`; `12_Security_RBAC_Audit.md:1518-1526` gives `pending/clean/suspicious/failed/skipped_by_approved_policy` and states a skip "must not be implicit". DOC-CONFLICT-029 is **Open** (`CONFLICT_REGISTER.md:51`) and ADR-008 is **Open** (`ADR_INDEX.md:49`). | **No value CHECK in M2.** The value set is the subject of an Open conflict; enumerating it decides half of it. `skipped_by_approved_policy` is a reserved value no code path may set while ADR-008 is Open. Availability is gated in the database instead. | Named conditional constraint `ck_file_objects_available_requires_clean_scan`, deliberately stricter than any candidate enum, alterable by expand/contract when ADR-008 lands. |
| e | `identity_account` status | `04_Database_Schema.md:310-365` and `12_Security_RBAC_Audit.md` disagree in count and names; `status_catalog.yaml:646-651` records `canonical: null`. | No value CHECK in M2; application-enforced fail-closed; CHECK added in M3 with the owner decision. | Deliberate omission. |
| f | `auth_events` name vs doc 12's twenty security event types | `04_Database_Schema.md:438`; `12_Security_RBAC_Audit.md:1577-1633`. | Doc 04's table name, doc 12's column set and `event_class` discriminator. | Recorded reconciliation. |
| g | Outbox `retry` | `04_Database_Schema.md:1428-1433` writes the dispatch index as `WHERE status IN ('pending','retry')`; `status_catalog.yaml:593-599` records `retry` as an unresolved alias with `canonical: null` and names "failed-with-available_at" as one of the two permitted answers. | Model retry as `failed` + `available_at`. Do **not** copy doc 04's predicate: with the approved five-value set it would index rows no legal row can satisfy, and would omit claimed-but-stalled `processing` rows. | Dispatch partial index over the claimable set only. |
| h | Index duplication between doc 04 §11 and §18 | Near-duplicate indexes specified twice while `04` §18.5 forbids redundancy. | Deduplicate as a recorded decision; never create both. | Recorded decision + `DB-CONSTRAINT-001`. |
| i | Index naming convention | `services/backend/app/db/base.py:8-14` generates `ix_`/`uq_`/`ck_`/`fk_`/`pk_`; doc 04 DDL uses explicit `idx_*` names (`04:1461-1467`, `:1415`, `:1428`). | Indexes named in doc 04 are declared with their **explicit** doc-04 names (an explicit name bypasses the convention); new indexes use the convention. | Recorded; asserted by `DB-CONSTRAINT-001`. |

---

# 3. Confirmed blocked/unblocked position

`CONFLICT_REGISTER.md` records 33 conflicts, 21 Open and 12 Resolved/Approved, with **0 Critical
open** (summary table, `:77-79`). Its header line 3 still says "7 decisions Resolved/Approved; 26
conflicts Open" and its footer (`:96`) repeats "Twenty-six conflicts remain Open" — both stale; plan
from the rows, not the counts (see slice 10 and section 7).

## 3.1 Decisions that touch M2

| Decision | Status | Blocks in M2 | Leaves free in M2 |
|---|---|---|---|
| DOC-CONFLICT-004 — product/domain baseline approval | **Resolved — Approved 2026-08-01** (`CONFLICT_REGISTER.md:26`) | Nothing further. The sign-off is scoped: it establishes the baseline for schema and API work and does not pre-approve any individual financial contract. | Financial schema, enums, commands and generated clients against approved names. The M2 traceability note calling it a blocker (`TRACEABILITY_MATRIX.md:24`) is stale and is corrected in slice 10 — not obeyed. |
| DOC-CONFLICT-005 — PaymentRequestRevision contract | Open (`:27`) | `payment_request_revisions`, `payment_requests.current_revision_id`, `uq_request_revision_pair`, `fk_request_current_revision`, request/revision identity or ETag semantics. Migration Group C. | Every generic integrity primitive. The matrix wording is exact — it "blocks request-revision schema, not generic integrity primitives" (`TRACEABILITY_MATRIX.md:24`). The DEFERRABLE composite-FK capability is therefore proven in slice 3 on a harness-only parent/child pair. |
| DOC-CONFLICT-014 / 015 — bundle states; evidence-link revoked vs voided | Open (`:36`, `:37`) | Any DB CHECK or API enum for `bank_result_bundle` states and for the inactive-evidence-link term. 014's interim rule is literally "do not add DB checks or API enums until alias resolution is approved". | A catalogue-driven constraint generator, **provided** it excludes every aggregate carrying an unresolved alias or `canonical: null`. A naive generator over the approved catalogue silently decides both. |
| DOC-CONFLICT-016 — bank export status catalogue | Open (`:38`) | The export **artifact** status enum; `superseded` and `failed` vs `generation_failed`. A single column mixing preview/final type with lifecycle is wrong even after it unblocks. | The export **job** lifecycle `queued/running/succeeded/failed` on `processing_jobs` (approved in `FINANCIAL_INTEGRITY_BASELINE.md` §1), and the UoW capability to insert an immutable artifact, link it to a completed job and transition the job atomically. |
| DOC-CONFLICT-025 — If-Match target for exact mark-sent | Open (`:47`) | Choosing the export If-Match target. `bank_excel_exports` deliberately has no `record_version`. | A concurrency helper supporting **both** shapes: `record_version` compare-and-swap, and exact resource ID + expected content hash + row lock. A helper hardwired to `record_version` cannot express M7 mark-sent at all, so the dual shape is mandatory now. |
| DOC-CONFLICT-026 — `sent_to_bank` / `bank_result_pending` transition | Open (`:48`) | Deciding whether a derived state is entered transactionally or is a read projection. | A recomputable-derived-value convention plus recomputation functions, so neither answer is pre-empted. |
| DOC-CONFLICT-029 — file scan and lifecycle metadata | Open (`:51`) | The `scan_status` value set (see 2.3 d) and any claim that lifecycle/retention/legal-hold metadata is synchronized. Interim rule: "Unknown/skipped scans fail closed; no file becomes available evidence until ADR-008 and lifecycle fields/statuses are synchronized." | The columns themselves, and the conditional availability constraint, which is strictly fail-closed. |
| DOC-CONFLICT-030 — readiness during Redis/worker/storage outage | Open (`:52`) | Any readiness or degradation policy treating Redis or storage as universally required; any financial command whose commit depends on Redis. | The transactional outbox with post-commit dispatch, PostgreSQL-only durable idempotency and job state, and a typed `BACKGROUND_PROCESSING_UNAVAILABLE` (503) response. The outbox is what keeps both halves of the interim rule true. |
| DOC-CONFLICT-032 — pilot worker topology and queue ownership | Open (`:54`) | Concrete worker containers, health ownership, resource limits. | The `queue_name` column and the six logical prefixes already frozen in `app/core/config.py:100-103` and `app/workers/celery_app.py:15-20`. Collapsing to one queue would force a data migration when topology lands. |
| DOC-CONFLICT-012 / 007 / 010 | Open (`:34`, `:29`, `:32`) | Bare OPS-001/OPS-002 references; any documentation path rename or copy; package release. | Citing exact reviewed `Implementation Docs/` paths with every OPS identifier qualified by source document. |
| ADR-001 — session transport and CSRF | Open (`ADR_INDEX.md:42`) | Shaping `auth_sessions` around a cookie or JWT choice; any transport-specific column. | The server-side session record storing only `secret_hash`, with the XOR actor check, INET IP, security-stamp version and revocation columns. |
| ADR-003 — storage adapter | Open (`:44`) | Embedding a local-filesystem-only key format. | The `(storage_provider, storage_bucket, storage_key)` triple and its unique constraint; the storage protocol extension for hashing and size. |
| ADR-004 — RPO/RTO, backup schedule, restore authority | Open (`:45`) | Every backup/restore claim and the schedule. Per the safe default, "backup claims are invalid until a clean full restore drill succeeds", so the release-evidence restore item cannot be filled at M2. | Creating the backup role and testing that its privileges suffice for a consistent dump of business plus audit/security data and no more. |
| ADR-005 — retention, deletion, legal hold, approval governance | Open (`:46`) | Any deletion executor, purge job, retention-reduction path, expiry sweeper or deletion trigger; any behaviour acting on `expires_at`, `retention_class`, `retention_policy_id`, `legal_hold_state`, `physically_deleted_at`. Because the governed procedures `FINANCIAL_INTEGRITY_BASELINE.md:87-89` references do not exist, **no append-only UPDATE/DELETE may be granted at all**. | `retention_policies` and `legal_holds` with separate propose/approve/activate actor columns, and the retention-shaped columns. |
| ADR-007 — initial bank profiles, templates, mappings, limits | Open (`:48`) | Every seeded bank rule, transfer limit, cutoff time and named production bank profile. Safe default: "Synthetic fixtures only; no real final export UAT or production bank output." | Bank profile/version/account/mapping structures with all uniques and hashes, plus named versioned synthetic fixtures. |
| ADR-008 — malware scanning and quarantine policy | Open (`:49`) | Any approved-skip path. Safe default: "never treat an unchecked file as available evidence." | The `scan_status` column, the reserved value, and the fail-closed availability constraint. |
| ADR-009 — manager strong/recent-auth factor and validity | Open (`:50`) | The assurance-factor enum values and any validity-duration default. A CHECK enumerating factors, or a `NOT NULL DEFAULT interval`, silently decides an Open ADR. No MFA coverage may be claimed for non-approval sign-in. | The `recent_auth_contexts` structure and the audit `authentication_assurance` column, both approved by `FINANCIAL_INTEGRITY_BASELINE.md` §3. |
| POL-003 — IBAN masking by role | Open (`ADR_INDEX.md:55`) | The per-role masking policy and the set of request-context fields approved for audit retention. | A parameterised write-time redaction mechanism plus the settled absolute prohibitions (`04_Database_Schema.md:1470`). |
| POL-005 — break-glass | **Approved for Phase 1A** (`ADR_INDEX.md:36`, `FINANCIAL_INTEGRITY_BASELINE.md:101-102`) | "no route, grant, flag, runtime activation, universal financial super-admin, or SoD bypass" — the **flag itself**, not merely its enablement. | Seeding `break_glass.activate` / `break_glass.review` permission identifiers with zero grants, which the approved catalogue already records (`permission_catalog.yaml:289-296`). |
| POL-006 — production file size/type limits | Open (`ADR_INDEX.md:56`) | Encoding size or type limits as CHECK constraints. | Configuration-driven limits in `system_settings`, plus `size_bytes >= 0` and the MIME/scan columns. |
| OPS-002 (ADR register sense) — monitoring, alert routing, scrubbing | Open (`ADR_INDEX.md:59`) | Alert destinations, alert owners, any production-readiness claim. | Structured redacted metrics: outbox lag, oldest pending age, dead-letter counts, failed-job surfaces. |
| OPS-005 — log/security-event/audit-view retention and export authority | Open | Any shortening, purge or export-authority design for audit and security history. Not listed in the M2 traceability row, yet it bears directly on the audit table M2 creates. | Least-access audit read paths with no default grant; `audit.read` and `audit.export` stay separate and `audit.export` keeps zero default roles. |
| Status catalogue `canonical: null` entries (`status_catalog.yaml:616-653`) | Approved catalogue, unresolved values | The status CHECK **value sets** for `file_object`, `bank_profile_version`, `bank_mapping`, `idempotency_record`, `identity_account`. `idempotency_records` is an M2 table whose three doc-04 states (`04:1398`) are not catalogue-approved: the table is allowed, the enum is not. | The tables and their status columns, application-enforced fail-closed, with named CHECKs added by expand/contract. `processing_job` by contrast **is** approved with eight canonical values (`status_catalog.yaml:602-614`), so its CHECK is permitted now — an easy place to be inconsistent in either direction. |
| Provisional audit/outbox, error and command catalogues | `provisional_pending_m0_approval` | Freezing audit action strings, PascalCase outbox event names, error codes and command envelopes as contracts. The response envelope is not frozen. | Table structures and transaction rules. All names live behind one indirection layer; the dotted-lowercase audit and PascalCase outbox conventions are never normalised by a shared helper. |
| OpenAPI breaking-change waiver | unresolved `TODO(governance)` in the workflow | Any intentional breaking response-schema change — notably adding a migration-freshness or outbox-lag check to `ReadinessResponse.checks`, which would trip the oasdiff gate (`.github/workflows/m1-verify.yml:96-134`) with no approved escape. | Additive new `/api/v1` paths, including a new restricted operations path for outbox and job observability. |
| Alembic naming/forward-fix policy; OpenAPI generation strategy | Pending owner approval | Claiming either policy is approved. | Implementing the mechanics, while recording that the policy is an unapproved M0 artifact. |

---

# 4. Sequenced slices

Ordering logic. Slice 1 is the DoD; splitting it would produce a first PR delivering tables with no
proof, and no slice is complete on a green migration alone (`15_Agent_Implementation_Plan.md:588-597`
and `14_Testing_QA_Acceptance.md:219-288`). Slices 2-5 harden and generalise what slice 1 proves
once. Slice 5 lands money/time/hash **before** any table with a monetary or hash column exists, so no
wrong precedent is set. Slices 6-9 land the remaining §10.2 table groups in dependency order as
structure-with-blocked-values. Slice 10 converts the accumulated tests into milestone evidence and
corrects the governance record.

`04_Database_Schema.md` §28.2 Group A (platform integrity) is `center_profile`, identity/RBAC/auth
sessions and events, idempotency, outbox, audit, processing jobs, retention/legal hold. Group B
(bank + files) is required by `15_Agent_Implementation_Plan.md:525-537` as a **foundation** while the
milestone table gives M4 bank configuration and private-file lifecycle as **behaviour**. M2 creates
the schema foundation for all of it; M4 adds versioned behaviour and lifecycle commands.
Identity/RBAC/session is **schema only**; authentication behaviour is M3
(`15_Agent_Implementation_Plan.md:598-669`).

---

## Slice 1 — Integrity spine: migration harness, `audit_logs` / `outbox_events` / `idempotency_records`, savepoint-capable Unit of Work, and the atomic exemplar command

This slice **is** the Definition of Done.

### Delivers

**Alembic harness conventions, decided once.** `file_template` plus a documented `--rev-id`
date-sequence rule so `alembic revision` cannot mint random hex. `services/backend/alembic/script.py.mako`
rewritten so a generated stub is ruff-clean under the repo's own gate: the current template emits
unused `op`/`sa` imports (F401) and `from typing import Sequence, Union` (UP035), while per-file
ignores waive only UP007. An `include_object` / `include_schemas` filter that excludes the
verifier's real `m1_verification.persistence_probe` schema — created by
`infra/scripts/verify-docker.sh` — so autogenerate never proposes dropping it.
`transaction_per_migration` enabled so a non-transactional revision (`CREATE INDEX CONCURRENTLY`) is
expressible. An explicit downgrade policy: forward-fix by default, no destructive downgrade of
append-only tables, `downgrade()` never autogenerated as if supported.

**Revision 1 (extensions only).** `CREATE EXTENSION IF NOT EXISTS pgcrypto` and `citext`, isolated
so `gen_random_uuid()` and CITEXT exist before any table, with a documented fallback for managed
environments where the migrator role cannot create extensions.

**Shared declarative conventions in `app/db/base.py`.** UUID PK defaulting to `gen_random_uuid()`;
`created_at`/`updated_at` TIMESTAMPTZ NOT NULL routed through `app.core.time.ensure_utc`, which
already raises on a naive datetime; `record_version BIGINT NOT NULL DEFAULT 1 CHECK (record_version > 0)`
for **mutable aggregates only**, never on immutable snapshots; every `CheckConstraint` explicitly
named, because the `ck` convention at `app/db/base.py:11` contains `%(constraint_name)s` and an
unnamed constraint raises `InvalidRequestError` at DDL time; a generated-identifier length guard
keeping `ix`/`uq`/`fk` names under 63 bytes; explicit `idx_*` names where doc 04 states them
(section 2.3 i). **No** soft-delete mixin, **no** `deleted_at`, **no** `organization_id`/`tenant_id`,
**no** `center_id` propagated to child tables.

**`audit_logs`** (name per `04_Database_Schema.md:1436`; columns per
`FINANCIAL_INTEGRITY_BASELINE.md:73-93` ∪ `12_Security_RBAC_Audit.md:1602-1633` ∪ doc 04 §15.3):
`id`, `occurred_at` TIMESTAMPTZ, `action`, `outcome`, `audit_schema_version`, `actor_type`,
`actor_id` (nullable, no FK — polymorphic across two identity domains plus two non-human types),
`actor_role_snapshot` JSONB NOT NULL DEFAULT `'[]'` (array literal, distinct from metadata's `'{}'`),
`session_id`, `recent_auth_context_id` (nullable, FK deferred to slice 6),
`authentication_assurance`, `entity_type`, `entity_id`, `parent_entity_type`, `parent_entity_id`,
`entity_record_version`, `immutable_snapshot_hash`, `previous_values`, `new_values`, `reason`,
`reason_code`, `request_id` **and** `correlation_id` **and** `causation_id` as three distinct columns,
`idempotency_record_id` (doc 04), `idempotency_key_hash` (never the raw key), `ip_address` INET,
`user_agent`, `previous_event_hash` / `event_hash` nullable (doc 04's optional chain; **no chain
computation in M2**), `metadata` JSONB with mandatory `metadata_schema` + `metadata_version`, and a
monotonic indexed BIGINT ordering key for the stable cursor pagination M11 needs — a UUIDv4 PK with
only a timestamp cannot cursor under concurrent same-timestamp inserts. Indexes for all seven
documented access paths: entity, actor, action, date range, `request_id`, `correlation_id`, and the
security-event class; doc-04 names retained per section 2.3 b.

**`outbox_events`** (`04_Database_Schema.md:1422-1434`): `aggregate_type`, `aggregate_id`,
`aggregate_version` captured inside the transaction, `event_type`, `payload`, `payload_version`,
`headers`, `correlation_id`, `causation_id`, `status` CHECK over exactly the five approved canonical
values, `available_at`, `attempt_count`, `locked_at`, `locked_by`, `published_at`, `last_error`
(redacted), `created_at`; a dispatch partial index over the claimable set. `retry` is absent
(section 2.3 g).

**`idempotency_records`** (`04_Database_Schema.md:1391-1420`): `actor_type`, `actor_id` NOT NULL,
`operation`, `idempotency_key`, `request_hash` CHAR(64) over a canonically serialised payload,
`status` NOT NULL **with no value CHECK**, `resource_type`, `resource_id`, `response_code`,
`response_body` JSONB (sanitised), `locked_until`, `expires_at`, `created_at`, `completed_at`;
`UNIQUE(actor_type, actor_id, operation, idempotency_key)` — four columns, not a global key — and
`idx_idempotency_expiry` per `04:1415`.

**`center_profile`** as the non-financial exemplar mutable aggregate (`04_Database_Schema.md:286-308`):
`name`, `legal_name`, `default_currency` `IRR`, `timezone` default `Asia/Tehran`, `status`,
`record_version`, timestamps, plus `uq_center_profile_one_active ... WHERE status = 'active'`. A
deployment singleton, not a soft tenant table.

**Unit of Work extended** (`app/db/unit_of_work.py`): SAVEPOINT / nested-transaction support —
PostgreSQL aborts the whole transaction on `IntegrityError`, so catching a unique violation, mapping
it to a typed conflict and still writing audit is impossible without one; an after-commit hook
registry that runs strictly post-commit in a separate session and whose failure can never roll back
committed state; the single-commit invariant preserved (repositories never commit, never open their
own transaction); explicit `flush()` discipline documented because `autoflush=False`
(`app/db/session.py:26`) means a read-then-insert check sees neither its own pending rows nor a
deferred unique violation. Repository slots per `10_Backend_Implementation_Guide.md:564-572`, with
the audit writer exposed as `uow.audit_logs`.

**Transaction-safe `AuditWriter` and `OutboxWriter`** on the same session — no second session, no
`after_commit` hook, no logging handler, no trigger on another connection — and an
`IdempotencyResolver` implementing all three branches: same key + same hash returns the stored
response without re-execution; same key + different hash → 409 `IDEMPOTENCY_KEY_REUSED`; concurrent
same key → exactly one logical execution via insert-first-and-catch-conflict **inside a savepoint**,
never SELECT-then-INSERT. Completion is written inside the business transaction, not committed
beforehand.

**Write-time redaction in the audit writer.** Rows can never be UPDATEd, so read-time masking
creates a permanent unfixable exposure. Absolute prohibitions enforced now per
`04_Database_Schema.md:1470`: no passwords, session secrets, raw tokens, raw idempotency keys,
storage credentials or raw file content. Per-role IBAN masking is **parameterised**, not chosen
(POL-003).

**An action/event-name indirection layer.** One registry mapping command → audit action string and
outbox event type, asserted against `docs/governance/audit_outbox_catalog.yaml`, so provisional
names can be renamed at the M0 freeze without a migration or a call-site sweep. The two conventions
stay deliberately distinct (dotted lowercase audit, PascalCase outbox); no shared normaliser.

**Typed `AppError` subclasses and `_http_error` entries** for `IDEMPOTENCY_KEY_REUSED` (409),
`VERSION_CONFLICT` (412), `PRECONDITION_REQUIRED` (428), `INVALID_STATE_TRANSITION` (400),
`BUSINESS_RULE_VIOLATION` (400). Today `app/core/errors.py` defines three subclasses
(`:48`, `:53`, `:62`) and every one of those statuses is reachable only via a raw
`StarletteHTTPException` mapped at `:138-141`.

**One explicit named command over `/api/v1`** — not a generic `PATCH {status}`, not generic CRUD —
accepting `Idempotency-Key` and an expected-version precondition, writing `center_profile` + audit +
outbox + idempotency completion in one commit, with `record_version` compare-and-swap
(`... WHERE id = :id AND record_version = :expected` plus an affected-row-count check), never
read-then-compare in Python under READ COMMITTED.

**PostgreSQL-backed test spine.** `tests/integration/` gains its own `conftest.py` repeating the
`sys.path.insert(BACKEND_ROOT)` pattern (the package is not installed for tests); pytest markers
registered in `[tool.pytest.ini_options]` **before first use**, because addopts carries
`--strict-config --strict-markers`; `testpaths` extended beyond `tests/backend`; **three distinct
connection identities** (migrator/owner, app runtime, worker runtime); cleanup via DELETE or a
migrator connection, because the app role holds no TRUNCATE privilege; multi-connection support for
two-session race tests; `tests/integration` added to `infra/scripts/validate_repository.py`
`required_paths` (currently `:53-74`, listing `tests/contract`, `tests/e2e`, `tests/security` but not
`tests/integration`) so it cannot be deleted.

**CI and verifier wiring in lockstep, including the exact environment block.** A
`postgres:16.14-alpine3.24` service container in the `native` job of
`.github/workflows/m1-verify.yml:49-94`, which today has none — only `docker-acceptance` starts
PostgreSQL, via compose. Identical stages in all four verifier scripts
(`infra/scripts/verify-native.sh`, `verify-native.ps1`, `verify-docker.sh`, `verify-docker.ps1`).
Ruff and mypy target lists extended to cover `tests/integration` (`verify-native.sh` currently lists
`services/backend/app`, `services/backend/alembic`, `services/backend/scripts`, `tests/backend` and
the two infra scripts).

The environment block is a deliverable, not an implementation detail. `alembic/env.py:19-21` resolves
the URL through `load_settings()`, so **every** migration stage constructs the whole `Settings`
object: `DATABASE_URL`, `REDIS_URL` and an absolute `LOCAL_STORAGE_ROOT` are all required with no
defaults (`app/core/config.py:77-84`, validator `:153-158`), and `alembic.ini` has an empty
`sqlalchemy.url`, so there is no escape hatch. Two specific traps must be closed:

- `model_config` sets `env_file=".env"` (`app/core/config.py:31-38`) with `extra="forbid"`. The
  dotenv source passes every key it reads, and a `.env` generated from `.env.example` contains
  `COMPOSE_PROJECT_NAME`, `POSTGRES_DB`, `APP_DB_USER`, `LOCAL_DATA_ROOT`,
  `NEXT_PUBLIC_API_BASE_URL` — none of which are Settings fields. Any stage running `load_settings()`
  with such a file in its working directory hard-fails. Pin the invocation directory, and never
  generate a `.env` in the native job's working directory.
- `tests/backend/conftest.py:82` constructs `Settings(_env_file=None, **values)` and therefore never
  exercises the environment at all. The integration conftest must not copy that shortcut, or the
  harness will prove nothing about deployability.

`tests/integration/README.md` states the contract: "Use real disposable PostgreSQL and Redis
containers. Redis-loss tests must prove that no authoritative business or job fact is lost." Redis is
required from slice 4 onward: either add a pinned `redis:7.4.9-alpine3.21` service container to the
native job, or place `OPS-REDIS-001` in the Docker gate and say so in the handoff. Silence is not an
option.

**`EXPECTED_MIGRATION_HEADS` updated in the same commit as the new revisions**
(`app/db/migrations.py:7`, currently `frozenset({"20260720_0001"})`), and
`tests/backend/test_runtime_foundation.py:9-11`'s empty-metadata tripwire
(`assert list(Base.metadata.tables) == []`) **replaced** by a metadata↔migration-head consistency
assertion rather than deleted.

**Regenerated `services/backend/openapi/v1.json`** with the exact operationId-set assertion updated,
no `HTTPValidationError`/`ValidationError` in components
(`tests/backend/test_openapi_contract.py:44`), and no literal `postgresql` substring anywhere in
descriptions (`:105` asserts its absence).

**`FakeRuntime` extended in the same commit.** `RuntimeServices` already carries `uow_factory`
(`app/core/runtime.py:35`, `:75`); the test double at `tests/backend/conftest.py:45` does not, so the
first UoW-dependent route breaks every existing `app_factory` test unless the fake is extended
alongside.

### Migration IDs

`20260720_0001` (existing baseline, immutable) → `20260801_0002_extensions` →
`20260801_0003_center_profile` → `20260801_0004_integrity_tables` (`audit_logs`, `outbox_events`,
`idempotency_records`) → `20260801_0005_controlled_failure_fixture` (retry/restartability proof,
gated to the test harness).

### What proves it

| Test ID | Assertion |
|---|---|
| DB-MIG-001 | Clean database to Alembic head on PostgreSQL 16.14 — an empty database, not a developer's local schema. |
| DB-MIG-002 | Previous supported schema (pinned baseline `20260720_0001`) to head. |
| DB-MIG-003 | Migration retry after a controlled failure; every revision individually restartable. |
| DB-MIG-004 | The application boots against the migrated database and critical queries/constraints re-verify — items 4-5 of the eight-item gate at `15_Agent_Implementation_Plan.md:571-582`, not just `alembic upgrade head`. |
| DB-CONSTRAINT-001 | `pg_catalog` introspection: every declared named constraint and index exists **under the identifier the authority states** (section 2.3 b, i); every FK has an index on its referencing columns and a reviewed delete action (RESTRICT/no-action for audit and financial paths, CASCADE only on RBAC junctions). |
| DB-CASCADE-001 | Parent deletes attempted; preservation or rejection asserted **by behaviour**, not by reading DDL. |
| UT-UOW-001..005 | Savepoint rollback leaves the outer transaction usable; after-commit hook runs only post-commit and its failure never rolls back; a second commit raises; re-entry raises; repository code cannot commit. |
| SVC-ATOMIC-001 | The exemplar command writes business state + audit + outbox + idempotency completion in exactly one commit (assert one commit, five artifact classes). |
| AUD-ROLLBACK-001 / 002 | Injected audit-insert / outbox-insert failure rolls back the business command — proves a shared transaction, not a second session. |
| SVC-PARTIAL-001 | Failure injected at **each** write boundary in turn; no partial commit in any case. Requires deterministic patchable seams; the current `FakeSession`-driven `tests/backend/test_unit_of_work.py` cannot demonstrate this and is replaced. |
| CON-IDEM-001..004 | Replay with same key and same canonical payload returns the original stored response without re-executing; same key + different payload → 409 rejected at the **database** boundary; two genuinely concurrent sessions → exactly one logical execution and the loser observes the committed record; simulated post-commit HTTP response loss replays with no duplicate effect. |
| CON-VERSION-001 | Stale expected-version → 412; missing precondition → 428; the winning writer's data survives intact — rejection alone is insufficient. |
| AUD-REDACT-001 | No password, session secret, raw token, raw idempotency key, storage credential or raw file content in any audit row or log line; `idempotency_key_hash` is a hash. |
| AUD-META-001 | Metadata JSON rejected without `metadata_schema` + `metadata_version`; a command omitting a required first-class column fails rather than falling back to JSON. |
| API-CONTRACT-001 | Canonical error envelope; correlation/request ID propagation; no ORM or internal fields in responses; no raw storage keys; deterministic byte-identical OpenAPI export. |

### Depends on

M1 as merged. No Open decision blocks this slice: the audit column set is approved
(`FINANCIAL_INTEGRITY_BASELINE.md` §4), the outbox status set is approved
(`status_catalog.yaml:583-592`), and the two places where values are not approved are handled by
**omission** (no `idempotency_records.status` CHECK; no `retry`) rather than by guessing.

### Risk of doing it badly

This is the reference implementation every later financial command is copied from; a defect is
replicated eleven times. Specifically: an idempotency record committed before the work (the
reservation-vs-completion trap) breaks the five-artifact single-commit rule, while writing it only at
the end permits two concurrent winners — both are silent duplicate-financial-command paths. A UoW
without savepoints forces later code to choose between mapping a unique violation to a conflict and
writing audit, so integrity violations surface as 500s. Audit written on a second session or in an
after-commit hook passes a naive atomicity test and leaves committed financial state with no
evidence. Missing audit columns are permanently un-backfillable because rows can never be UPDATEd,
and unredacted payloads are permanently unredactable. Omitting the monotonic ordering key makes M11
cursor pagination impossible. Omitting the upgrade harness now means no later migration group is ever
upgrade-tested and the production-release gate becomes unsatisfiable. A migration merged without
updating `EXPECTED_MIGRATION_HEADS` makes readiness return 503 for every deployment and reds the
Docker verifier for a reason that looks unrelated.

---

## Slice 2 — Five least-privilege database roles bound to the **configured** identities, append-only enforcement proven as the runtime role, and transaction safety limits

### The identity problem this slice must solve first

`04_Database_Schema.md:90-99` §3.2 lists *recommended* role names. Those names appear nowhere else in
the repository. The identities the application actually connects as are operator-chosen environment
values: `infra/postgres/init/010-create-runtime-roles.sh:15-17` binds `app_role`/`migration_role` to
`$APP_DB_USER`/`$MIGRATION_DB_USER`; `.env.example:13` and `:15` set them to `gold_app` and
`gold_migrator`; `infra/compose/compose.local.yml:117` builds the backend `DATABASE_URL` from
`${APP_DB_USER}` and `:159` the migrate one-shot from `${MIGRATION_DB_USER}`; the worker and
scheduler services reuse the backend environment anchor, so **today only two runtime identities
exist and the worker connects as the app role**.

A migration that issues `REVOKE UPDATE, DELETE ON audit_logs FROM platform_app`, and a test that
connects `AS platform_app`, would constrain a role nothing connects as. Meanwhile
`010-create-runtime-roles.sh:41-42` has already registered
`ALTER DEFAULT PRIVILEGES FOR ROLE :"migration_role" IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_role"`,
so `audit_logs` — which does not exist yet — will receive UPDATE and DELETE for the real app role at
creation time. The M2 evidence gate would pass while being false.

**Decision for M2: role names are configuration, not literals.** No rename to `platform_*` (that
would require editing `.env.example`, compose, the init script and `validate_repository.py` together,
and would take effect on no existing volume). Instead:

- `Settings` gains `APP_DB_ROLE`, `WORKER_DB_ROLE`, `READONLY_DB_ROLE`, `BACKUP_DB_ROLE`,
  `MIGRATION_DB_ROLE`, defaulting to the existing `APP_DB_USER`/`MIGRATION_DB_USER` values, and the
  migration reads role names from settings via `alembic/env.py`'s existing `load_settings()` path.
- The doc 04 §3.2 names are recorded in the handoff as **labels** mapped to the configured
  identities, so the recommendation is honoured without hard-coding it.
- A migration-time guard fails the revision when a configured role does not exist, so a mismatch is
  an immediate loud failure rather than silent theatre.
- A test asserts the role under grant/revoke is **byte-identical** to the username parsed from the
  runtime `DATABASE_URL` the backend and worker services use, and fails otherwise.

### Delivers

The five roles as **idempotent Alembic migrations**, not by editing
`infra/postgres/init/010-create-runtime-roles.sh`. That directory only executes on an empty data
directory, and `infra/scripts/verify-docker.sh` deliberately recreates the stack **without** deleting
volumes, so an edited init script is invisible on every developer and CI volume that matters. Roles:
migrator (DDL/Alembic only, schema owner), app runtime, worker runtime (no migration rights),
read-only, backup. Password/credential provisioning stays outside the migration, through a documented
provisioning step run under the migrator identity that reads passwords from the environment.

**Correction of the inherited default privilege, plus repair of what it already granted.** The
`ALTER DEFAULT PRIVILEGES` at `010-create-runtime-roles.sh:41-42` is replaced by a narrowed default
plus an explicit per-table grant convention, so later append-only tables (`auth_events` in slice 6,
approval tables in M7) cannot silently inherit UPDATE/DELETE. Corrected default privileges do **not**
undo grants already materialised, so the migration additionally issues explicit `REVOKE` statements
for the real migrator→app pair on every existing table, covering volumes where init already ran.

**Explicit REVOKE of UPDATE and DELETE** from the app and worker roles on `audit_logs`
(`04_Database_Schema.md:1470`), with the same convention pre-registered for
`auth_events`/security-event tables and future approval tables, and INSERT/SELECT retained — the
worker role **must** keep audit INSERT because `system_worker`/`system_maintenance` are audit actors
and blocking it would break worker-side atomicity.

**A deliberately scoped revocation.** Not a blanket `REVOKE DELETE` from every role, and not an
unconditional `BEFORE DELETE` trigger that always raises, because governed retention and
legal-hold-released deletion must remain addable later under a distinct maintenance path
(`FINANCIAL_INTEGRITY_BASELINE.md:87-89`). In M2 the effective rule is **zero UPDATE/DELETE for
runtime roles**, because the governed procedures ADR-005/OPS-005 would authorise do not exist.

**Schema ownership separation asserted.** The app role owns nothing, cannot CREATE/ALTER/DROP, holds
USAGE only on `public` (the bootstrap already does `REVOKE CREATE ON SCHEMA public FROM PUBLIC` at
`010-create-runtime-roles.sh:19`), and cannot bypass, drop or alter a database-enforceable guard —
the precondition that makes the M7 finalizer≠approver constraint non-bypassable.

**Per-transaction safety limits.** `statement_timeout`, `lock_timeout`,
`idle_in_transaction_session_timeout` set per connection/role. None exist today, so a
`SELECT ... FOR UPDATE` on a contended row blocks a worker indefinitely while Celery's
`task_acks_late` plus a long visibility timeout redelivers the task on top of still-held locks.

**Connection-pool correction.** `app/db/session.py:20` binds `pool_timeout` to
`settings.dependency_timeout_seconds` (`app/core/config.py:86-88`, default 1.5s, ceiling 10s). A
pool-checkout deadline is thereby bound to a health-probe deadline: adding an outbox poller alongside
request traffic produces spurious 500s at low concurrency, and raising the value simultaneously
loosens every health probe. Decouple them and size `pool_size`/`max_overflow` deliberately.

**READ COMMITTED confirmed as the application baseline** — not raised to SERIALIZABLE globally — with
explicit row locks and atomic conditional updates as the coordination mechanism.

**Backup role** created with privileges sufficient for a consistent dump of business plus
audit/security data and no more. Role only, with **no** backup or restore claim (ADR-004).

### What proves it

| Test ID | Assertion |
|---|---|
| SEC-ROLE-000 | The role named in the grant/revoke statements is byte-identical to the username in the runtime `DATABASE_URL` for both the backend and worker services. Without this, every test below can pass vacuously. |
| SEC-ROLE-001 / 002 | A session connected **as the app runtime role** attempts UPDATE, then DELETE, on `audit_logs` → privilege error. Same pair as the worker role. Run through the ordinary owner-identity fixture these pass trivially and prove nothing. |
| SEC-ROLE-003 | The worker role **can** INSERT into `audit_logs`; least privilege must not break worker-side atomicity. |
| SEC-ROLE-004 | The app role cannot CREATE/ALTER/DROP a table, cannot create or drop a constraint or trigger, and is not the schema owner. |
| SEC-ROLE-005 | The read-only role cannot write; the backup role can read audit/security tables and cannot write. |
| SEC-ROLE-006 | Default privileges: a newly created table does not grant UPDATE/DELETE on an append-only table to app or worker. Asserted **after** creating a table through the migrator role, so the `pg_default_acl` path is genuinely exercised. |
| DB-TIMEOUT-001 | `lock_timeout` aborts a contended `FOR UPDATE` within the configured bound instead of blocking forever; `statement_timeout` and `idle_in_transaction_session_timeout` are in effect for app and worker roles. |
| OPS-POOL-001 | Pool exhaustion under simulated poller + request load produces a bounded typed 503, not an unexplained 500, and health-probe timeouts are unaffected. |

### Depends on

Slice 1 (`audit_logs` and the migration harness must exist to be granted against).

### Risk of doing it badly

Append-only is a GRANT-level control; an ORM convention, an event hook or a Python guard satisfies
neither `15_Agent_Implementation_Plan.md:565` nor the M2 evidence gate. If the proving test runs on
the owner connection, or against a role no connection string uses, the milestone is signed off with
an audit table the API can rewrite. If the revocation is applied bluntly, governed retention becomes
impossible to add later without dropping the guard — i.e. the control gets removed under delivery
pressure. If role changes ship as an edit to the init script they take effect on nobody's machine.
If the timeouts are skipped, the first contended lock in M6 is an indefinite production hang
compounded by Celery redelivery on top of held locks.

---

## Slice 3 — Concurrency, precondition and locking primitives with one global lock ordering

### Delivers

A shared optimistic-concurrency helper supporting **both** precondition shapes, because
DOC-CONFLICT-025 (`CONFLICT_REGISTER.md:47`) records that `bank_excel_exports` deliberately has no
`record_version` while the surrounding batch has mutable versioning: (a) `record_version`
compare-and-swap with the predicate in the SQL and an affected-row-count check, and (b) exact
resource ID + expected content hash + row lock. A helper hardwired to `record_version` cannot express
the M7 mark-sent command at all.

HTTP transport binding: ETag emission from `record_version` on mutable aggregates; `If-Match`
parsing; 428 when a required precondition is absent; 412 when stale. Immutable snapshots are
explicitly excluded from ETag semantics and use exact IDs plus content hashes — no blanket ETag
middleware. `xmin`, `updated_at` and row hashes are prohibited as the concurrency token.

A lock helper restricted to the enumerated coordination points (`04_Database_Schema.md:1691-1723`):
finalise a request revision; create split/retry attempts; finalise a batch version; approve/reject a
version; generate a final export; mark export/batch sent; confirm a payment attempt; replace a
confirmed evidence link; publish a result; change a trader's approval/status during an active
command; recalculate a request paid total. A closed list, not a general-purpose lock-anything helper.

**One documented global lock ordering rule for the whole system** — a deterministic sort key applied
before locking, plus a reserved advisory-lock key namespace — published as a reviewable document
rather than discovered per command. M6 allocation locking and M9 evidence replacement will otherwise
deadlock against each other with two independently sensible orderings.

A structural guarantee that no lock is held across file or network I/O: the UoW makes it hard to open
the transaction at request start and hold it through a storage put or preview render, and file
generation plus notification delivery are placed strictly after commit.

`DEFERRABLE INITIALLY DEFERRED` composite-FK capability proven as a **harness capability** on a
test-only parent/child pair with `UNIQUE(id, parent_id)` — the exact pattern M5's current-revision
pointer and M6's current-version pointer require, with the exact column order
(`FOREIGN KEY (current_child_id, id) REFERENCES child(id, parent_id)`; reversed it still creates and
enforces nothing). This is permitted while DOC-CONFLICT-005 is Open because the matrix wording blocks
"request-revision schema, not generic integrity primitives" (`TRACEABILITY_MATRIX.md:24`). The
apparently redundant `UNIQUE(id, parent_id)` is documented as load-bearing, with a review note so a
linter or reviewer does not remove it as duplicative.

A serialization-failure (40001) retry wrapper for any future proven-necessary SERIALIZABLE operation.
A two-session race-test harness generalised from slice 1 (threads or separate engines, real locks,
ordering assertions) as the reusable primitive for the CON-001..CON-010 suite M6/M7/M9 populate.

Server-side list conventions for the audit and queue read paths: cursor or stable page-based
pagination, deterministic sort, allowlisted filter and sort fields, permission-scoped counts,
mandatory limits. Queries never mutate domain state.

### What proves it

CON-001-shape (two concurrent sessions on one mutable aggregate: one succeeds, the stale one gets a
conflict, the winner's data survives and `record_version` increments by exactly one);
CON-PRECOND-001 (valid If-Match succeeds, missing → 428, stale → 412, immutable resource rejects ETag
semantics); CON-HASHTARGET-001 (exact-ID-plus-content-hash path holds under concurrency with a row
lock); DB-DEFERRED-001 (parent and first child created in one transaction under the deferrable
composite FK; a cross-parent child pointer rejected at commit; the reversed column order shown not to
enforce the invariant); CON-LOCKORDER-001 (deadlock regression: opposing orders deadlock, both routed
through the helper serialise); CON-NOIO-001 (no lock or open write transaction held across a storage
write or outbound call, asserted structurally); UT-RETRY-001 (bounded 40001 retry, typed conflict on
exhaustion); API-LIST-001 (every list endpoint paginated with deterministic sort and allowlisted
filters; unbounded or unsorted rejected).

### Depends on

Slice 1 (`record_version` convention, exemplar command, typed 412/428, PostgreSQL harness) and
slice 2 (`lock_timeout`, so a lock-ordering regression fails fast instead of hanging CI).

### Blocked values

DOC-CONFLICT-025 blocks choosing the export If-Match **target**, so the helper must support both
shapes and must not pick one for exports. DOC-CONFLICT-026 blocks stored-versus-projection semantics,
so the derived-value convention must make every derived state recomputable. The ten `FOR UPDATE` call
sites belong to M5-M9; M2 owns only the primitives and the ordering rule.

### Risk of doing it badly

Read-then-compare in Python loses the race under READ COMMITTED, so a version guard that looks
correct silently permits lost updates on financial aggregates. If the ordering rule is not published
as one global rule in M2, the first two commands that lock overlapping rows deadlock in production
rather than in tests, and the fix then requires reworking both. If the helper is hardwired to
`record_version`, someone will add a `record_version` to an immutable export table, contradicting the
immutable-snapshot rule. If the deferred composite-FK capability is not proven now, M5/M6 will
weaken the pointer invariant to a plain single-column FK, which allows a parent to point at another
parent's child. A UoW that holds the transaction across a file write turns an availability defect
into an inherited property of every later command.

---

## Slice 4 — Durable processing jobs, transactional-outbox dispatcher, and the worker protocol

### Delivers

**`processing_jobs`** (`04_Database_Schema.md:1350-1378`): `id`, `job_type`, `queue_name`, `status`,
`input_entity_type`, `input_entity_id`, `provider`, `provider_version`, `input_payload`,
`output_payload`, `idempotency_key`, `attempt_count`, `max_attempts`, `available_at`, `started_at`,
`heartbeat_at`, `finished_at`, `locked_by`, `last_error_code`, `last_error_message` (redacted),
timestamps. Status CHECK over the **eight approved canonical values**
`queued/running/succeeded/failed/retry_scheduled/cancelled/dead_lettered/fallback_to_manual` —
`processing_job` **is** an approved aggregate (`status_catalog.yaml:602-614`), unlike
`idempotency_record`, so this CHECK is permitted. `UNIQUE(job_type, idempotency_key)` implemented as
a **partial** unique index where the key is not null, exactly as `04:1373-1376` instructs.

The **claim and reclaim indexes** doc 04 never writes down but the specified worker pattern requires:
a claim index over `(queue_name, status, available_at)` and a lease-reclaim predicate index over
`heartbeat_at`. Adding a lease column later means migrating a live queue.

**The outbox dispatcher as a post-commit reader in its own session and transaction.** Write side
(in-transaction) and dispatch side (post-commit) are two different transactional regimes and must not
share a session. Atomic claim via `FOR UPDATE SKIP LOCKED` (`04:1434`) plus a lease/visibility
timeout for crashed claimants; a SELECT-then-UPDATE poller double-delivers, and the
single-scheduler-instance rule is a documented assumption, not a substitute for atomic claiming.

Bounded exponential backoff with jitter and a maximum attempt count; on exhaustion mark
failed/dead_lettered, retain the original input, raise an operational review item, permit authorised
manual retry as a **new** execution attempt, and never mark financial success merely because a task
was retried. Per-handler retry-safety declaration so a globally applied retry decorator cannot
silently retry a non-retry-safe operation; at-least-once delivery with `outbox_event_id` as the
mandated consumer dedup key.

**Worker runtime plumbing that does not exist today**: engine/session-factory construction in the
worker process (`RuntimeServices.from_settings` at `app/core/runtime.py:43` is currently called only
from the FastAPI lifespan), a task base class owning per-task transaction boundaries, and task
modules under the already-frozen dotted paths `app.workers.tasks.{files,exports,notifications,reports,maintenance,ai}`
— the routing globs at `app/workers/celery_app.py:15-20` and the default queue
`task_default_queue="maintenance"` (`:36`) mean anything landing elsewhere silently falls through to
maintenance. The `ai` queue has no Phase 1A producer.

Scheduler-driven maintenance: outbox polling and stale-job/expired-lease recovery. Explicitly **not**
delivered: expired-idempotency cleanup or any purge. `expires_at` exists with an index
(`04:1415`) and nothing acts on it.

**Post-commit dispatch discipline.** `celery_task_always_eager` is a real setting
(`app/core/config.py:104-106`) and tests use it, so an eager task fired before commit executes inline
inside the caller's transaction and, if it opens its own session, cannot see the uncommitted rows.
Dispatch is registered as an after-commit hook (slice 1) and never called next to a commit.

**Observability**: outbox-lag and oldest-pending-age metrics, a stale-outbox and dead-letter surface,
a failed-jobs surface, redacted structured diagnostics carrying correlation/causation/request IDs.
Exposed as a **new restricted path**, deliberately **not** by adding a check to
`ReadinessResponse.checks` — that changes the response schema and trips the oasdiff gate
(`.github/workflows/m1-verify.yml:96-134`), whose waiver process is an unresolved
`TODO(governance)`.

### What proves it

AUD-OUTBOX-001/002 (event written in the same transaction; no event if the command rolls back);
AUD-OUTBOX-003 (two concurrent dispatchers claim safely, no double delivery — proves atomic claim);
AUD-OUTBOX-004..007 (retry does not duplicate the user-visible effect; a poison event reaches
dead-letter handling; old pending age raises an alertable signal; notification/dispatch failure does
**not** roll back committed financial state); JOB-LEASE-001; JOB-CRASH-001..005 (crash before the
side effect, after a file write but before the DB update, after the job-state update, after the
outbox claim, and during notification send — convergence in every case); JOB-RETRY-001;
JOB-EAGER-001 (an eager-dispatched task cannot observe uncommitted rows); DB-PLAN-001 (EXPLAIN at
representative seeded volume for the outbox dispatch queue and the job retry queue — plan assertions,
not `pg_indexes` existence checks; this is the volume-seeding harness the other seven queues reuse);
OPS-REDIS-001 (with Redis unavailable, safe reads continue, background work is unavailable, no job is
falsely completed, no business truth is lost — placed in whichever gate actually has a Redis
container, per slice 1).

### Depends on

Slice 1 (outbox table, after-commit hook, UoW, harness), slice 2 (worker role grants, `lock_timeout`,
pool sizing), slice 3 (SKIP LOCKED claim ordering, race harness).

### Blocked values

DOC-CONFLICT-032: `queue_name` and the six prefixes are free; concrete worker containers, health
ownership and resource limits are blocked. DOC-CONFLICT-030: a financial command's commit must not
depend on Redis and no policy may treat Redis/storage as universally required. DOC-CONFLICT-016: the
export **job** lifecycle is approved and implementable here; the export **artifact** status enum is
blocked, and preview/final **type** stays a separate field from lifecycle. OPS-002 (ADR register
sense): metrics and redacted diagnostics free; alert destinations, owners and production-readiness
claims blocked. ADR-005/OPS-005: no expiry, purge or retention-execution job.

### Risk of doing it badly

`15_Agent_Implementation_Plan.md:543-557` lists only the audit and outbox **writers**, so reading it
alone under-scopes M2 by the dispatcher and the worker protocol, while the Phase 1A acceptance
checklist requires jobs to be operational. Teams routinely ship UoW/audit/outbox/idempotency and
defer durable jobs — after which the outbox poller has no authoritative place to record its own
attempts, error codes and heartbeat. A non-atomic claim double-delivers every event, which under
at-least-once semantics means duplicate trader notifications and duplicate derived artifacts. A
missing lease column means retrofitting one onto a live financial queue. A dispatcher sharing the
command session makes the two required behaviours mutually exclusive: either audit-failure rollback
or notification-failure non-rollback will fail. Adding an outbox-lag check to the existing readiness
response blocks the PR on an OpenAPI waiver that does not exist.

---

## Slice 5 — Money, time and canonical-hash utilities with pinned determinism

Delivered **before** any table with a monetary or hash column exists, so no wrong precedent is set.

### Delivers

Money as a triple, not a scalar: canonical `amount_irr BIGINT` (NUMERIC only under a recorded
approved schema exception, of which none exists; FLOAT/REAL/DOUBLE PRECISION forbidden in columns,
ORM types, Pydantic fields, serialisers and fixtures) plus retained `entered_amount_value BIGINT` and
`entered_amount_unit VARCHAR(8) CHECK IN ('IRR','TOMAN')` as provenance that is never the canonical
value.

Exact TOMAN→IRR conversion as integer multiplication by ten, in exactly one place, with no tolerance
and no rounding; no unit ever inferred from magnitude, formatting, actor or page context.

API boundary serialisation as base-10 integer strings — the canonical wire shape
`{"amount_irr":"1250000000","entered_amount":"125000000","entered_unit":"TOMAN"}` — with three-way
agreement validated and rejected as `AMOUNT_UNIT_MISMATCH` (400) when the parts do not agree exactly.
The serialiser therefore has two distinct sides, storage and wire, and must accept an entered value
plus explicit unit, not only a canonical integer, or M5 will add its own conversion path.

Correct asymmetries preserved rather than harmonised by accident: `amount_irr > 0` strictly positive;
`credit_limit_irr >= 0`; `file_objects.size_bytes >= 0` (`04_Database_Schema.md:654`);
statement-row directional amounts exempt from the positive convention; `confirmed_amount_irr` `>= 0`
on receipts and `> 0` on matches. Aggregate/derived sums are legitimately zero and must not inherit
the strict-positive CHECK.

Exact paid aggregation with overpayment producing reconciliation work (`RECONCILIATION_REQUIRED`,
409) and blocked normal closure — never clamped or normalised into success. Helper only; no financial
table.

Time: TIMESTAMPTZ-only enforcement (a lint/model guard rejecting naive `TIMESTAMP` and
`datetime.now()`), the raw-plus-normalized external date/time convention with the parser/rule version
retained, ambiguous or unparseable external dates routed to manual review rather than guessed, and
business-day/cutoff computation from the IANA identifier `Asia/Tehran` via the installed tz database —
never server-local time and never a hard-coded +03:30, which would pass today's tests and fail on any
future rule change. tzdata presence verified as a runtime image requirement; `BUSINESS_TIMEZONE` is
already pinned and validated in `app/core/config.py:70-72`.

A canonical serialiser and versioned content-hash utility backing every hash column in the system:
pinned field order, encoding, integer-only numeric representation, timestamp normalisation, and
Persian/Arabic Unicode normalisation, with an explicit algorithm version identifier so a library or
interpreter upgrade cannot silently change a stored hash. Python dict ordering, `json.dumps`
defaults, `repr()` and `hash()` are prohibited inputs. A `parameters_hash` variant is provided for
derivation reproducibility in preference to uniqueness over raw JSONB.

The hash utility is designed for stored-hash comparison years after creation (M7 compares export hash
== batch-version hash == approval hash) and for the exhaustive normative input list of a
batch-version hash: ordered rows, attempt IDs and snapshots, amounts, beneficiary/IBAN snapshots,
bank profile version, mapping version, source account, transfer-channel configuration. Omitting any
element lets an approved hash match a materially different export.

A field-aware golden-comparison helper separating meaningful business content, stable row ordering,
exact integer values and expected metadata from acceptable renderer metadata variation — byte-for-byte
golden assertions are both flaky and explicitly not what is required.

A frozen-money contract test binding the generated client: money maps to BigInt or an integer-safe
decimal, never JavaScript `number`. IRR amounts exceed 2^53 quickly, so an OpenAPI-generated `number`
is silent precision loss at the boundary. The OpenAPI generation strategy is Pending, so this slice
constrains the type without freezing the generator.

### What proves it

UT-MONEY-001..010 (IDs pre-assigned by the test authority): integer IRR preserved exactly; Toman
converts by exact ×10; entered value and unit retained; unit never inferred from magnitude;
decimal/floating input rejected; overflow bounds enforced; Persian/Latin digit normalisation without
value change; `paid_sum == requested` → paid; `<` → partial/failed by attempts; `>` →
reconciliation-required, never paid. Plus UT-MONEY-011 (three-way agreement rejects a mismatched
payload as `AMOUNT_UNIT_MISMATCH`) and UT-MONEY-012 (no float anywhere on the money path, asserted by
type introspection over models and schemas). UT-HASH-001..005 (stability across process restarts and
dict insertion orders; material change changes the hash; pinned golden vectors; version identifier
stored and compared; Persian/Arabic normalisation and integer formatting deterministic).
UT-TIME-001..005 (naive datetime rejected at model and serialisation boundaries; business-day and
cutoff evaluation uses the tz database with a boundary/DST regression case even though `Asia/Tehran`
currently has no seasonal change; ambiguous external date routes to manual review; raw external text
plus parser/rule version retained; API timestamps ISO 8601 UTC and Jalali never reaching transport or
persistence). API-MONEY-001 (generated TypeScript type is BigInt/integer-safe decimal, not `number`).
DB-TYPE-001 (introspection: every monetary column BIGINT, every timestamp column TIMESTAMPTZ).

### Depends on

Slice 1 (base conventions, typed errors, `app.core.time` UTC helpers) and slice 3 (canonical request
hashing shares the serialiser with the idempotency `request_hash`).

### Blocked values

None for the approved contracts — `MONEY_TIME_CONTRACT.md` and ADR-006 are Approved. Deliberately out
of scope because their governing decisions are Open: screen-by-screen Jalali input controls, bank
cutoff date conventions and holiday/calendar ownership, per-role display timezone, date-only
end-of-day interpretation. The OpenAPI generation strategy is Pending.

### Risk of doing it badly

A single float column, a NUMERIC money column without a recorded exception, or one Python float
round-trip silently breaks the exact-equality integrity comparisons M6 finalisation and M7 export
validation depend on — and those failures appear intermittently, months later, as quarantined real
exports. A serialiser accepting only a canonical integer forces M5 to build its own conversion path,
which is where a magnitude heuristic and a 10× error enter. Reusing the strict-positive CHECK on
aggregate or provenance columns produces false constraint violations on legitimate data. A
non-deterministic hash turns a library upgrade into a fleet-wide false-positive integrity incident;
because M7 compares three independently stored hashes, an unversioned algorithm is unrecoverable. A
hard-coded UTC offset passes every test today and silently shifts every cutoff decision the first
time the tz rules change.

---

## Slice 6 — Identity, RBAC, session and recent-auth schema plus the approved catalogue seed (schema only, no authentication behaviour)

### Delivers

**Two separate identity tables**, not one polymorphic user table with a type flag
(`04_Database_Schema.md:310-365`; `12_Security_RBAC_Audit.md:296-559`): `admin_users` (username
CITEXT globally unique; email/phone with **partial** unique indexes `WHERE ... IS NOT NULL`;
`password_hash` sized for Argon2id; `full_name`, `status`, `failed_login_count`, `locked_until`,
`password_changed_at`, `last_login_at`, `record_version`, timestamps) and `trader_users`
(`phone_number` unique login identity; `is_primary` with the **two-condition** partial unique
`WHERE is_primary = TRUE AND status <> 'inactive'`; `failed_login_count`, `locked_until`,
`last_login_at`, `record_version`). M3 must prove admin sessions are rejected on trader surfaces and
vice versa; a shared table with a role flag makes that test unfalsifiable.

An **authentication/security stamp version** column on both identity tables **and** the same version
stored on the session record — doc 12's requirement, absent from doc 04. Without the pair, step 2 of
the command check order cannot detect a stamp change, so a password change or role revocation leaves
authority live in existing sessions.

**RBAC core**: `roles` (unique code, `is_system`), `permissions` (unique code), `role_permissions`
with `PRIMARY KEY(role_id, permission_id)` and the one sanctioned `ON DELETE CASCADE`, and
`admin_user_roles` with a **surrogate UUID PK** plus `UNIQUE(admin_user_id, role_id) WHERE revoked_at IS NULL`
— doc 04 specifies no PK for this table, and a composite PK would make revoke-then-regrant impossible.

**`auth_sessions`**: session ID PK; conditional admin/trader FKs with the exactly-one-actor XOR check
`((admin_user_id IS NOT NULL)::int + (trader_user_id IS NOT NULL)::int = 1)`; `secret_hash` only,
never a raw session/refresh secret; `auth_level`, `authenticated_at`, `step_up_expires_at`,
`expires_at`, `revoked_at`, `revocation_reason`, `ip_address` INET (not VARCHAR), `user_agent`,
credential/security-stamp version, optional parent/replaced session reference, `last_seen_at`, and
the two symmetric partial active indexes.

**`auth_events`** as the append-only security-event store: doc 04's required table name
(`04:438`) carrying doc 12's required column set — `actor_type`, `actor_id`, `event_type`,
`event_class`, `outcome`, `ip_address` INET, `user_agent`, `request_id`, `correlation_id`, `metadata`
with schema/version, `created_at` — and an `event_class` discriminator wide enough for all twenty doc-12
security event types. Conceptually distinguishable from business audit (audit explains **authorised**
changes; security events record **denied and failed** behaviour) while sharing infrastructure, and
receiving slice 2's append-only grant treatment.

**Durable PostgreSQL storage for failed-login counters and lock metadata.** Rate-limit counters may
be cached, but the durable account/security record is not Redis-only: `infra/redis/redis.conf` has
`appendonly no` and `save ""`, i.e. zero persistence.

**`recent_auth_contexts`** per `FINANCIAL_INTEGRITY_BASELINE.md:47-71`: bound to actor ID,
authentication-session ID, action/purpose, resource type, resource ID, assurance/factor, issuance
time, expiry, revocation state, a non-replayable identifier or token hash, and explicit
**consumption** columns recorded inside the command transaction so timeout/retry and idempotency
cannot reuse assurance for a different effect. The `audit_logs.recent_auth_context_id` FK from
slice 1 is attached here via expand/contract.

**Seed of only canonical identifiers.** Permissions from `permission_catalog.yaml`; the nine baseline
roles `trader_owner`, `accountant`, `manager`, `warehouse_operator`, `business_admin`,
`technical_admin`, `read_only_auditor`, `support_operator` (disabled by default), `system_worker`. No
`super_admin`. Document-05 API spellings are deprecated aliases and are **not** grantable rows
(DOC-CONFLICT-013, `CONFLICT_REGISTER.md:35`); `unresolved_no_exact_canonical_target` entries deny.
`audit.read` and `audit.export` stay separate with `audit.export` at zero default grants.
`break_glass.activate` / `break_glass.review` may be seeded for catalogue completeness with zero
grants and no activation path, exactly as `permission_catalog.yaml:289-296` already records them.

System/worker actor identities able to author audit and job rows without holding human financial
authority, and `technical_admin` seeded with **no** grant to approve batches, confirm payments,
publish results, mark exports sent, approve incoming payments, dispatch gold, or read every financial
file.

**Fail-closed authorization primitives**: unknown permission, role or alias resolves to deny; aliases
never accepted at runtime and never broaden a grant; a role name alone is never sufficient for
sensitive service authorization; a frontend check is never authorization. Identity → role assignments
→ permissions, combined with ownership/business scope, current state/version/hash and
command-specific policy.

**Catalogue contract tests** binding code constants to `status_catalog.yaml` and
`permission_catalog.yaml`, with `pyyaml` promoted to an explicitly pinned dev dependency plus a
reviewed `uv.lock` diff — it currently reaches the tree only as a transitive dependency of
`uvicorn[standard]`, and `infra/scripts/validate_repository.py` does not inspect `docs/`, so nothing
today can detect drift between an approved catalogue value and a persisted one.

**Twelve user fixtures** expressible by the schema and seed: Trader A, Trader B, Pending Trader,
Suspended Trader, Accountant A, Accountant B, Manager A, Warehouse Operator, Business Admin,
Technical Admin, Read-only Auditor, and a break-glass identity disabled by default. Synthetic only;
no default passwords, no seeded credentials in migrations or images.

### What proves it

DB-IDENTITY-001 (XOR check rejects a session with both or neither actor); DB-IDENTITY-002 (partial
unique indexes behave with their **full** predicates: a second non-null email rejected while multiple
NULLs allowed; a deactivated primary trader user can be replaced, proving the `status <> 'inactive'`
half is present; a revoked role can be re-granted, proving the surrogate PK and
`WHERE revoked_at IS NULL`); SEC-RBAC-001 (catalogue-driven positive **and** negative matrix over
every seeded permission, executed against the API, not against hidden buttons; role-name-only checks
fail the matrix); SEC-RBAC-002 (unknown permission, role and alias each deny; a deprecated doc-05
alias is not a grantable row and does not broaden a grant); SEC-SOD-001..004; SEC-BREAKGLASS-001
(**scope: no break-glass route, no grant, no feature flag, no runtime activation path** — route-level
absence plus a repository-level check. It must **not** be phrased as "no break-glass string
anywhere", or it fails on the approved permission catalogue's own zero-grant rows);
SEC-RECENTAUTH-001 (wrong actor, wrong session, wrong action/purpose and wrong resource each
rejected; expiry and revocation invalidate; replay after consumption rejected while the legitimate
same-idempotency-key retry after step-up still succeeds); SEC-STAMP-001 (a stamp bump invalidates a
live session's authority on the next protected request); SEC-DURABLE-001 (failed-login and lock state
survive a Redis flush); CONTRACT-CAT-001 (every persisted permission code and status value exists in
the approved catalogue; an injected mismatch fails); SEC-SECRET-001 (no plaintext password, OTP,
token or secret reference in `auth_events`, `auth_sessions`, audit metadata or any settings row;
password hashes never returned by an API).

### Depends on

Slice 1 (base conventions; `audit_logs.recent_auth_context_id` awaiting its FK), slice 2 (append-only
grant convention and corrected default privileges so `auth_events` does not inherit UPDATE/DELETE),
slice 3 (precondition helper for mutable identity aggregates), slice 5 (canonical hash for token/key
hashing).

### Blocked values — structure free in four places

1. **ADR-001** (session transport/CSRF): the server-side record with `secret_hash` is free; the table
   must not be shaped around a cookie or JWT choice.
2. **ADR-009**: the recent-auth structure and the audit `authentication_assurance` column are
   explicitly approved; the factor enum values and any TTL default are blocked. A CHECK enumerating
   factors, or a `NOT NULL DEFAULT interval`, silently decides an Open ADR.
3. **`identity_account` status**: `status_catalog.yaml:646-651` records `canonical: null` **and** docs
   04 and 12 genuinely disagree, so the status columns ship with **no** value CHECK,
   application-enforced fail-closed, with the conflict recorded and the named CHECK added in M3.
4. **`trader_users.trader_id` has no FK target**: `traders` is migration Group C, not Group A. The
   column ships NOT NULL **without** its FK, and the FK is attached by expand/contract when `traders`
   lands — the same sanctioned pattern used for `recent_auth_context_id`. Recorded as an explicit
   gap, not a clean answer.

POL-003: the redaction mechanism is parameterised; the per-role policy is not chosen.

### Risk of doing it badly

A merged identity table with a type flag makes M3's cross-domain session rejection test structurally
unfalsifiable and weakens M4/M5 trader ownership scoping — and it cannot be split later without
migrating live credentials. Omitting the security-stamp pair means role revocation and password
change are audited but ineffective, leaving revoked authority live in in-flight sessions. Seeding a
convenience superset for `technical_admin`, or any `super_admin`, permanently defeats separation of
duty and matches a named abuse case. Seeding an invented permission string or a doc-05 alias
re-creates exactly the Critical conflict that closed on 2026-08-01, and because `payment_batch.approve`
names the mutable container rather than the reviewed version, it would let an approval outlive its
content (`CONFLICT_REGISTER.md:35`). A `recent_auth_contexts` table without consumption columns
forces a choice between burning the context on the first attempt (breaking the legitimate
post-timeout retry) and never burning it (permitting replay). Reducing any two-condition partial
unique predicate to one condition either blocks legitimate replacement or permits two active rows.

---

## Slice 7 — Configuration surface and inert retention/legal-hold structures

### Delivers

**`system_settings`** (`04_Database_Schema.md:1476-1488`): `id`, `key` with UNIQUE, `value`,
`value_type` (so typed settings do not depend on parsing heuristics), `category`, `status`,
`record_version`, `updated_by_admin_user_id`, timestamps. Secrets, tokens and encryption keys are
prohibited in this table and belong to deployment secret management (`04:1486`).

**`feature_flags`** (`04:1490-1507`): `id`, `flag_key` UNIQUE, `is_enabled`, `rollout_config`,
`record_version`, `updated_by_admin_user_id`, timestamps, seeded with **exactly the five** Phase 1A
dotted rows stated at `04:1502-1506`:

```text
manual_crop.enabled      = true
auto_segmentation.enabled = false
ocr.enabled              = false
ai_matching.enabled      = false
bank_api.enabled         = false
```

**`break_glass_enabled` is not seeded, in any value.** POL-005 is Approved and
`FINANCIAL_INTEGRITY_BASELINE.md:101-102` disables "Break-glass activation, permission grants,
endpoints, **feature flags**, and runtime bypasses"; `ADR_INDEX.md:36` repeats "no route, grant, flag,
runtime activation". The flag itself is prohibited, not merely its enablement — and a seeded row would
be writable by `feature_flag.update`, whose default grant is `technical_admin`, the one role that
must hold no financial authority. The wider "recommended initial flags" list in
`18_Production_Setup_and_Runbook.md:411` (`break_glass_enabled`, plus `feature.`-prefixed
`_enabled`-suffixed spellings) is a non-normative recommendation in a different naming convention,
and doc 18 carries no owner sign-off in `docs/governance/DOCUMENT_APPROVAL_REGISTER.md`; the approved
policy overrides it. Any naming divergence against that list is **recorded**, not silently
normalised, and the runbook's contradiction with POL-005 is raised as a new conflict entry (slice 10).

A **write path for both tables that is audited by construction** and structurally incapable of
bypassing migration, authorization or integrity checks; security and audit are never
flag-disableable, and no flag can bypass authorization or an integrity check.

**`retention_policies`** (`04:1509-1517`) and **`legal_holds`** (`04:1519-1521`) — **structure only**,
with separate propose/approve/activate actor columns so the approved workflow (proposal → review →
approval → legal-hold check → dry-run impact report → backup coordination → activation → separate
deletion execution → deletion evidence) is expressible later.

**Explicit non-delivery, enforced by test**: no deletion executor, no purge job, no
retention-reduction execution path, no expiry sweeper, no deletion trigger anywhere, and no route
that could invoke one. `idempotency_records.expires_at` exists with an index and nothing acts on it;
reducing a retention duration creates a new policy version and deletes nothing (`04:1517`). Because
the governed retention and legal-hold procedures that would authorise an audit UPDATE/DELETE do not
exist, the effective M2 rule remains zero UPDATE/DELETE on append-only tables.

The **deletion model documented as a governed, table-specific state machine** plus policy records
(`cancelled`, `voided`, `superseded`, `replaced`, `archived`) rather than a soft-delete column
pattern, so no base-class mixin can add `deleted_at` across every future financial table at once.

### What proves it

OPS-RETENTION-001 (reducing a retention duration triggers no deletion, asserted by row counts before
and after); OPS-RETENTION-002 (no deletion executor, purge job, retention-execution route or deletion
trigger exists — asserted structurally, not by inspection); CON-010-shape (a legal hold wins against
any hypothetical retention path and data is preserved; demonstrable at M2 because both tables exist
here); OPS-FLAG-001 (**exactly** the five seeded rows with the exact dotted keys and values, AI/OCR/
auto-segmentation/matching/bank-api all false, **and** no flag key matching `break_glass*` exists);
OPS-FLAG-002 (a flag change writes an audit row); OPS-FLAG-003 (no flag can disable security or audit
or bypass an authorization/integrity check); SEC-SETTINGS-001 (no secret, token or encryption key can
be written to `system_settings`); DB-DELETE-001 (no table carries a mechanically added `deleted_at`,
and no base class exposes a generic `delete()` for a financial aggregate).

### Depends on

Slice 1 (audit writer, base conventions), slice 2 (append-only grants and the scoped rather than
blanket revocation), slice 6 (admin identity for the `updated_by`/`approved_by`/`placed_by` columns
and the configuration permissions).

### Blocked values

ADR-005 is the definitive structure-allowed / behaviour-blocked case in M2: the tables and columns may
exist and absolutely nothing may act on them. OPS-005 additionally blocks any shortening, purge or
export-authority design for audit and security history — least-access read only, and `audit.export`
keeps zero default grants. POL-006 means file limits live in configuration, never as a CHECK
constraint. POL-005 is Approved and break-glass is disabled, which is why no break-glass flag row
exists at all.

### Risk of doing it badly

A retention or feature-flag table whose write path is not audited and integrity-guarded from the first
commit becomes the mechanism by which an unaudited configuration change alters financial behaviour,
and retrofitting the audit obligation onto an existing write path is exactly the change that gets
skipped. Shipping any expiry or purge job — even a well-intentioned idempotency-record TTL sweep —
destroys precisely the records that prove no duplicate financial command occurred, and does so
silently. A `deleted_at` added to the base model violates the deletion prohibition across every
future financial table simultaneously. Seeding a flag key that diverges from the approved dotted
names silently enables an AI or OCR path Phase 1A forbids; seeding `break_glass_enabled` violates an
Approved policy and fails slice 6's own SEC-BREAKGLASS-001.

---

## Slice 8 — File metadata and relationship foundation (structure and integrity columns; two value sets withheld)

### Delivers

**`file_objects`** (`04_Database_Schema.md:619-655`): `storage_provider`, `storage_bucket`,
`storage_key` server-generated and never a client contract, `original_filename` sanitised for
display, `mime_type_declared` and `mime_type_detected` as **separate** columns,
`size_bytes BIGINT CHECK (size_bytes >= 0)` (empty files allowed — not the money convention),
`sha256_hash`, `category`, `visibility_scope`, `storage_status`, `scan_status`,
`uploaded_by_actor_type`/`_id`, `retention_class`, `retention_policy_id`, `legal_hold_state`,
`original_or_derived_relation`, `metadata` JSONB, `created_at`/`updated_at`, `archived_at`,
`physically_deleted_at` (retention process only, and no process exists).
`UNIQUE(storage_provider, storage_bucket, storage_key)`; `idx_file_objects_hash` and
`idx_file_objects_status_category` with doc-04 names (`04:650-653`).

**A conditional constraint making the prose rule real**:
`CHECK (storage_status <> 'available' OR sha256_hash IS NOT NULL)`. Doc 04 states "Required before
`available`" (`04:626`) with no constraint given, so without this the rule exists only in application
code.

**A second conditional constraint gating availability on scan state**:
`ck_file_objects_available_requires_clean_scan`. This replaces the value-set enum that
DOC-CONFLICT-029 blocks (section 2.3 d) and is deliberately stricter than any candidate enum, in the
direction ADR-008's safe default requires: "never treat an unchecked file as available evidence"
(`ADR_INDEX.md:49`). `skipped_by_approved_policy` is a **reserved** value no code path may set while
ADR-008 is Open, so a skip can never be implicit (`12_Security_RBAC_Audit.md:1526`).

**`file_links`** for non-critical polymorphic attachments only (`04:657-667`), with supersession
modelled as `replaced_at`/`replaced_by_file_link_id` rather than deletion, and a partial index over
active links only. Critical financial relationships use explicit FKs; this polymorphic pattern is
scoped and must not be promoted into a reusable generic financial link primitive.

**`file_derivations`** (`04:669-683`): `source_file_id`, `derived_file_id`, `derivation_type`,
`parameters_hash` (the sanctioned canonical alternative to raw-JSONB uniqueness, which is fragile
against key order and Unicode differences), `renderer_version`, `source_hash`, `created_by_job_id`,
with `UNIQUE(source_file_id, derived_file_id)` and the reproducibility unique
`UNIQUE(source_file_id, derivation_type, parameters_hash, renderer_version)`.

**`StorageBackend` protocol extended** with hashing and size reporting while keeping
`check_available()` and `close()` intact, because the storage probe binds directly to
`check_available` and `infra/scripts/validate_repository.py:57` hard-requires
`services/backend/app/storage/local.py`. No binary content in PostgreSQL — metadata only, streaming
upload/download at the storage layer.

**Storage-reconciliation DETECTION queries** for the seven required conditions (storage object without
a DB record; DB record without an object; stale pending upload; derivative without a source; checksum
mismatch; stuck processing job; duplicate object write after retry), with an explicit guarantee that
reconciliation never automatically deletes financial evidence.

**Seventeen file fixtures** as versioned synthetic artifacts, including extension/MIME mismatch,
corrupt PDF, corrupt Excel, formula-injection text, duplicate checksum, and a simulated suspicious
scanner result — the last two dictate that the checksum and quarantine columns exist in **this**
migration rather than later.

### What proves it

FILE-META-001 (a raw storage key or path never appears in any API response or client contract);
FILE-META-002 (the hash constraint rejects `available` with a null `sha256_hash`); FILE-META-003 (a
file that is not `available` cannot become evidence; a quarantined file is refused by the business
path; a file whose scan is not clean cannot reach `available` at the **database** boundary);
FILE-META-004 (derivation reproducibility unique holds; identical source + `parameters_hash` +
`renderer_version` rejected; a differing `renderer_version` accepted); FILE-META-005 (the
duplicate-checksum fixture is representable and detected, not rejected as invalid data);
FILE-RECON-001..007 (each condition simulated and detected; no run deletes financial evidence);
DB-FILE-001 (introspection confirms `size_bytes >= 0` not `> 0`, the provider/bucket/key unique, the
partial active-links index, the doc-04 index names, and no `deleted_at`); OPS-STORAGE-001
(`check_available` and the existing storage probe behave identically after the protocol extension).

### Depends on

Slice 1 (base conventions, harness), slice 2 (grants), slice 4 (`created_by_job_id` needs
`processing_jobs`), slice 5 (canonical serialiser for `parameters_hash`), slice 6 (uploaded-by actor
identities), slice 7 (`retention_policy_id` needs `retention_policies`).

### Blocked values — **two** genuine value conflicts, not one

- **`storage_status`** — section 2.3 c. Four authorities state the same seven values; the approved
  catalogue records `file_object` with `canonical: null` and forbids canonicalising `deleted` vs
  `deleted_by_policy`. Named seven-value CHECK excluding `deleted_by_policy` on a recorded
  reconciliation, or no value CHECK if sign-off is unavailable at merge.
- **`scan_status`** — DOC-CONFLICT-029 **Open** (`CONFLICT_REGISTER.md:51`) and ADR-008 **Open**
  (`ADR_INDEX.md:49`). No value CHECK; reserved value; availability gated by constraint. Both
  decisions must be cited in the slice's blocking list, and DOC-CONFLICT-029's interim rule quoted in
  the PR.

ADR-003: the provider/bucket/key triple is free; a local-filesystem-only key format must not be
embedded. POL-006: limits are configuration, never a CHECK. ADR-005/OPS-005:
`physically_deleted_at`, `retention_class`, `retention_policy_id` and `legal_hold_state` may exist and
nothing may act on them.

### Risk of doing it badly

A boolean `is_available` or a generic `deleted_at` cannot express quarantine or `retention_pending`,
which are hard gates for evidence, export and publication — and file lifecycle is the one M2 table the
dependency graph feeds directly, so M4, M8 and M9 all reference a stable `FileObject`. Omitting
checksum or quarantine columns now makes the required duplicate-checksum and scanner fixtures
unrepresentable and the reconciliation queries unwritable. A convenient trader-visible boolean used as
the access gate is a designed-in IDOR: the security tests require denial when a visibility flag says
yes but the publication relationship is absent (`04:655`). Implementing derivation uniqueness over
raw JSONB rather than a canonical `parameters_hash` makes crop and preview reproducibility silently
depend on dict ordering. Promoting `file_links`' polymorphic pattern into a reusable financial link
primitive violates the prohibition that a mutable direct FK must never be the sole source of history.

---

## Slice 9 — Bank profile and configuration foundation (structure and integrity constraints; status enums blocked)

### Delivers

**`bank_profiles`**: unique code, name, status, `current_version_id` assigned after the version row
exists via a DEFERRABLE FK or a documented two-step, `record_version`, timestamps — one of the four
circular-reference pairs where a non-deferrable FK makes creating a profile and its first version in
one transaction impossible.

**`bank_profile_versions`** (`04_Database_Schema.md:543-573`) as an immutable operational
configuration snapshot: `bank_profile_id`, `version_number` monotonic per bank, `status`,
`effective_from`/`effective_to`, `default_transfer_limit_irr` and `after_cutoff_transfer_limit_irr`
(each BIGINT with a null-tolerant positive check), `cutoff_time TIME` evaluated in the configured
timezone rather than UTC, `splitting_enabled`, `supports_description_field`, `required_fields` JSONB,
`rules` JSONB, `config_hash` CHAR(64), `created_by_admin_user_id`, `created_at`.
`UNIQUE(bank_profile_id, version_number)` **and** `UNIQUE(bank_profile_id, config_hash)` — the second
prevents an operator recreating an identical config as a "new" version and losing the audit link.
**No** `record_version`: it is an immutable snapshot superseded by inserting a new row.

**`bank_accounts`** (centre-owned source/destination): `bank_profile_id`, `display_name`,
`account_number`, `deposit_number`, `iban`, `normalized_iban` nullable with a **null-tolerant**
`CHECK (normalized_iban IS NULL OR normalized_iban ~ '^IR[0-9]{24}$')`, `account_role`
(`outgoing_source`/`incoming_destination`/`both`), `status`, `record_version`.
`UNIQUE(normalized_iban)`.

**`bank_mappings`** (`04:588-613`) as an immutable mapping/template version:
`bank_profile_version_id`, `file_type`, `template_version`, `status`, `mapping` JSONB,
`required_fields` JSONB, `normalization_rules` JSONB DEFAULT `'{}'`, `sample_header_hash`,
`config_hash`, `created_by_admin_user_id`, `approved_by_admin_user_id`, `created_at`, with **both**
uniques scoped to `(bank_profile_version_id, file_type, ...)` so an import mapping and an export
mapping can both exist at `template_version` 1.

Explicit resolution of the source's IBAN-constraint asymmetry (beneficiaries NOT NULL with a regex;
`bank_accounts` nullable with a null-tolerant regex; `trader_bank_accounts` with none specified) as a
**recorded decision** rather than an accidental harmonisation — with a note that no unique
beneficiary-per-IBAN/name constraint may ever be added, because duplicates may be legitimate and the
service warns rather than auto-merging.

Versioned synthetic bank fixtures with the named identifiers the evidence set requires:
`BANK_A_PROFILE_V1`, `BANK_A_MAPPING_V1`, `BANK_A_MAPPING_V2` (two mapping versions coexisting inside
one profile), `BANK_B_PROFILE_V1`, source account A and B, one invalid mapping, one inactive profile,
one profile with split limits, one profile with time/cutoff rules — with the fixture version strings
emitted into the run report. No real bank hard-coded as a universal default.

Mapping-driven SQL safety: bank mapping values may never become untrusted SQL identifiers without a
strict allowlist, and all dynamic SQL is parameterised — a named attack surface for the later
import/export code.

### What proves it

DB-BANK-001 (duplicate `(bank_profile_id, version_number)` rejected); DB-BANK-002 (duplicate mapping
version within `(bank_profile_version_id, file_type)` rejected, while an import mapping and an export
mapping at `template_version` 1 both succeed); DB-BANK-003 (a second version with an identical
`config_hash` for the same profile rejected); DB-BANK-004 (a profile and its first version created
inside **one** transaction under the deferrable FK); DB-BANK-005 (the null-tolerant IBAN regex accepts
NULL and a valid IR IBAN and rejects a malformed one; no unique beneficiary-per-IBAN constraint
exists); DB-BANK-006 (a used bank-profile version and a used mapping cannot be updated, while a
controlled status field may still change); BANK-FIXTURE-001 (the ten named synthetic fixtures load,
their version strings appear in the run report, and no real bank, IBAN, phone number or payment
evidence is present in source control); SEED-001 (no bank rule, transfer limit, cutoff time or named
production bank profile is seeded).

### Depends on

Slice 1 (harness, base conventions), slice 3 (DEFERRABLE composite-FK capability proven), slice 5
(canonical serialiser for `config_hash` and `sample_header_hash`), slice 6 (created-by/approved-by
admin identity), slice 8 (file categories referenced by mapping `file_type` semantics).

### Blocked values

`status_catalog.yaml:633-645` records `bank_profile_version` and `bank_mapping` with
`canonical: null`, so their `status` value sets (`draft/active/retired`) are **not** written; the
columns ship application-enforced with the conflict recorded, and the CHECKs are added by
expand/contract at M4. ADR-007 (safe default "Synthetic fixtures only; no real final export UAT or
production bank output", `ADR_INDEX.md:48`) blocks all seeded bank configuration — a seeded transfer
limit would silently drive real splitting decisions. ADR-006 is Approved, so `cutoff_time TIME` plus
configured-timezone evaluation is settled, but bank cutoff date conventions and holiday/calendar
ownership remain Open and must not be encoded. Doc 12's separation-of-duties requirement means the
finalizer/preparer actor must be persistable on the immutable batch version in M6; nothing here may
make that impossible.

### Risk of doing it badly

`15_Agent_Implementation_Plan.md:525-537` requires the bank-profile and configuration foundation in M2
while migration Group B and M4 also own bank configuration, so this line is routinely skipped as
"M4's job", leaving one of M2's required outputs undelivered. Getting the uniqueness **scope** wrong
is the specific trap: a globally scoped mapping unique blocks having both an import and an export
mapping at `template_version` 1, while dropping `UNIQUE(bank_profile_id, config_hash)` lets an
operator recreate an identical configuration as a new version and lose the audit link. A
non-deferrable `current_version_id` FK makes atomic creation impossible, forcing a two-step write and
a window where the pointer is null. Copying the beneficiaries' NOT NULL IBAN regex onto
`bank_accounts` breaks legitimate null normalized IBANs; adding the "obvious" unique
beneficiary-per-IBAN index breaks legitimate duplicate data entry. A seeded transfer limit or a
hard-coded named bank profile becomes production truth that silently drives real financial splitting.

---

## Slice 10 — Evidence emitter, catalogue-drift CI gates, manifest regeneration, and traceability reconciliation

### Delivers

**A run-metadata evidence emitter** producing the fields M2 can supply from the fifteen-item release
evidence set: test-run identifier; application commit and image digests; the Alembic revision read
programmatically **from the running application**, not from the repository; environment identifier;
feature-flag snapshot showing AI disabled; bank-profile/mapping fixture versions; test data-set
version. Emitted as a durable publishable artifact so the evidence set is not a manual transcription.

**New CI gates** in the four-job workflow (`.github/workflows/m1-verify.yml`): PostgreSQL migration
failure (clean **and** upgrade) as a hard gate; a catalogue-versus-code **drift** gate that fails on
an unhandled status mapping or a documentation/state-machine mismatch — a human review step does not
satisfy a CI gate, and now that the status and permission catalogues are approved rather than
provisional this must be automated; a security/concurrency stage; and a signed-test-artifact
publication step, which is the mechanism by which the evidence set becomes durable.

**A manifest integrity gate, and regeneration of the manifest itself.**
`docs/governance/M0_MANIFEST.json:5` records `generated_on: 2026-07-20`, two approved decisions and
`open_conflicts: 26`; recomputing SHA-256 over its seventeen listed paths today gives **10 drift, 7
match** (`ADR-006_Business_Timezone_and_Calendar_Rules.md`, `ADR_INDEX.md`, `api_error_catalog.yaml`,
`CONFLICT_REGISTER.md`, `DOCUMENT_APPROVAL_REGISTER.md`, `FINANCIAL_INTEGRITY_BASELINE.md`,
`M0_READINESS.md`, `permission_catalog.yaml`, `status_catalog.yaml`, `TRACEABILITY_MATRIX.md`). Five
of those files have not been modified since the commit that introduced the manifest, and the
repository normalises line endings, so those hashes were **wrong at generation time**: the checksum
chain has never been valid. `ADR-006_Business_Timezone_and_Calendar_Rules.md:111` anchors its approval
evidence to that manifest. Slice 10 therefore regenerates `M0_MANIFEST.json` (hashes, byte/line
counts, `decision_state`, `generated_on`) **in the same commit** as the governance corrections below,
and adds a CI check that fails on any manifest-listed hash drift — same gate class as the catalogue
drift gate. Regeneration must not certify stale prose, so the count corrections below are part of the
same change.

**Pipeline ordering aligned to the recommended sequence**: static analysis → unit → PostgreSQL
integration → API contract → frontend component → security/concurrency → clean and upgrade migration
→ immutable image build → container/dependency/secret scans → ephemeral deploy → E2E smoke → signed
test artifacts. The four verifier scripts stay in lockstep so a stage added to only
`verify-native.sh` does not make Windows developers and the shell gate disagree about what green
means.

**Test-ID scheme applied across every M2 test** using the fixed catalogue (`UT-`, `DB-`, `SVC-`,
`API-`, `SEC-`, `CON-`, `FILE-`, `AUD-`, `OPS-`, `PERF-`), with the traceability mapping completed. No
test in the repository currently carries any catalogue ID, and this is the last point at which they
can be added without renaming the whole suite.

**Governance-record corrections, written as documentation rather than silent code choices.** Enumerate
rows; never trust a count.

| Record | Stale value | Correct value, by row enumeration |
|---|---|---|
| `docs/governance/TRACEABILITY_MATRIX.md:24` | "DOC-CONFLICT-004 blocks irreversible financial schema approval", citing `CONFLICT_REGISTER.md:21-22` | DOC-CONFLICT-004 is Resolved — Approved 2026-08-01. The cited line range is also stale: the 004 and 005 rows are now `CONFLICT_REGISTER.md:26-27`. |
| `CONFLICT_REGISTER.md:3` and `:96` | "7 decisions Resolved/Approved; 26 conflicts Open"; "Twenty-six conflicts remain Open. Seven decisions are Resolved" | Summary table `:77-79`: 21 Open, 12 Resolved, 0 Critical. The evidence heading at `:59` ("All seven approvals below") must also become twelve. |
| `docs/governance/README.md:4`, `:16`, `:36` | "Last validated: 2026-07-20"; "33 conflicts: 7 Resolved/Approved and 26 Open"; "All machine-readable catalogues remain `provisional_pending_m0_approval`" | Counts per the register's summary table; the provisional claim is false for status and permission (approved 2026-08-01) and true for error, command and audit/outbox. |
| `docs/adr/ADR_INDEX.md:86-87` | Count control row `Approved 2 \| Open 31` | **The count table is the stale row, not the header.** Enumerating rows `:42-74` gives 33 canonical entries minus three Approved (ADR-006, POL-005, POL-002) = 30 Open, matching header `:4` and `M0_READINESS.md:35`. Correct the table to Approved 3 / Open 30 — do **not** "correct" the header to 31. |
| `docs/governance/README.md:15`, `TRACEABILITY_MATRIX.md:22` | "ADR-006 and POL-005 Approved; 31 Open" | Same 2026-08-01 drift; fold into the same commit. |

**New conflict records raised by M2**, each requiring an owner decision: (a) audit `actor_type`
vocabulary divergence, absent from the register, resolved here by §2.2 precedence in favour of doc 12;
(b) `file_objects.storage_status` — four authorities agree on seven values while the approved
catalogue records `canonical: null`; (c) `identity_account` status — docs 04 and 12 disagree in count
and names; (d) the `auth_events` name/scope reconciliation; (e) the outbox `retry` resolution as
failed-plus-`available_at`; (f) index deduplication between doc-04 §11 and §18; (g) the audit
**column** vocabulary reconciliation of section 2.3 b, including the `idx_audit_event_time` →
`idx_audit_action_time` index rename and the `uow.audit_logs` attribute binding to
`10_Backend_Implementation_Guide.md:570`; (h) `18_Production_Setup_and_Runbook.md:411`'s recommended
`break_glass_enabled` flag contradicting Approved POL-005, together with the doc-18 flag naming
convention divergence; (i) the doc-04 `idx_*` index-naming convention versus
`app/db/base.py:8-14`'s `ix_*` convention.

**Published deliverable documents M2 owes as artifacts rather than code**: the global lock-ordering
rule and advisory-lock key namespace; per-migration rollback/forward-fix notes; the revision-granularity
convention for non-transactional operations; the append-only grant convention for future tables
(including the configured-role-name mapping from slice 2); the canonical-hash algorithm version
register; and the per-release verification queries.

**Performance evidence** recorded against the initial targets (normal API p95 under 500 ms where
practical; admin operational queue under 3 seconds with pagination) **with** the test data volume and
environment recorded. Performance evidence without recorded volume and environment is not acceptable
evidence, and unknown expected volumes must not be hidden behind arbitrary hard-coded limits.

### What proves it

OPS-EVIDENCE-001 (the emitter output contains every M2-supplyable evidence field, with the Alembic
revision read from the running application and matching the migration head); CI-DRIFT-001 (an
injected status-value mismatch and an injected permission-code mismatch each fail the drift gate);
CI-DRIFT-002 (an injected documentation/state-machine mismatch fails); CI-MANIFEST-001 (an injected
byte change to a manifest-listed file fails the hash gate; the regenerated manifest matches the tree
at HEAD); CI-MIGRATE-001 (clean and upgrade migration stages are hard gates and a deliberately broken
revision reds the pipeline); CI-PARITY-001 (the four verifier scripts run the same stage set; a stage
present in only one is detected); PERF-QUEUE-001 (recorded p95 and queue timings with volume and
environment captured alongside); TRACE-001 (every mandatory M2 requirement maps to at least one test
ID, and every critical integrity primitive maps across the unit, DB/service and API layers).

### Depends on

All prior slices. Slice 1 already pinned the baseline revision and built the upgrade job, so this
slice gates them rather than inventing them.

### Blocked values

OPS-002 (ADR register sense): metrics and redacted diagnostics free; alert destinations, owners and
production-readiness claims blocked. ADR-004: no backup or restore claim, so the restore-drill
evidence item stays unfilled at M2 and the gap is stated rather than left blank. The OpenAPI
breaking-change waiver process is an unresolved `TODO(governance)`, so no intentional breaking
response-schema change may be attempted; additive new paths only. DOC-CONFLICT-012: every ticket or
traceability entry citing OPS-001 or OPS-002 must qualify the identifier with its source document —
and the roadmap's OPS-002 (durable jobs and outbox monitoring) is precisely M2's territory.
DOC-CONFLICT-007/010: documentation paths must not be renamed or copied. The Alembic
naming/forward-fix policy and the OpenAPI generation strategy remain Pending, so M2 implements the
mechanics while recording that the policies are unapproved M0 artifacts.

### Risk of doing it badly

Without an automated drift gate, an approved status name or permission code silently diverges from
what the code persists, and nothing detects it. Without the evidence emitter, four of the fifteen
required evidence fields can only be transcribed by hand, and a release candidate is accepted on
evidence that cannot be reproduced. Without test IDs applied now, the traceability duty cannot be
satisfied without renaming the entire suite. Leaving the stale governance counts uncorrected means
the next planner reads "26 Open including 5 Critical" and blocks work that is actually unblocked, or
reads DOC-CONFLICT-004 as a blocker when it closed on 2026-08-01. Not raising the actor_type and
file-status conflicts means M2 silently decides material questions inside migrations that can never
be edited. Leaving `M0_MANIFEST.json` unregenerated means every M2 citation rests on a checksum chain
that does not hold, while the change protocol at `docs/governance/README.md:64` is violated again.

---

# 5. Cross-cutting rules, including every prohibited shortcut

The five explicit prohibitions are `15_Agent_Implementation_Plan.md:588-597`. Each is expanded below
with the enforcement mechanism, because a prohibition without a failing test is advice.

1. **PROHIBITED — repository-level `commit()`.** The Unit of Work solely owns commit and rollback.
   Repositories receive the ambient session, never open a transaction, never commit, never
   flush-and-commit independently. A sensitive command commits exactly once; audit writer, outbox
   writer and idempotency resolver share that one transaction. Enforced by a test that fails if any
   repository or writer calls `commit`.
2. **PROHIBITED — audit written after the business commit.** No SQLAlchemy `after_commit` hook, no
   second session, no autonomous transaction, no logging handler, no message-queue emit, no database
   trigger on a different connection. Audit is an ordinary INSERT on the same session, and an audit
   insert failure rolls the business command back (AUD-ROLLBACK-001).
3. **PROHIBITED — Redis as the durable source of truth for idempotency or job state.**
   `infra/redis/redis.conf` has `appendonly no` and `save ""`: zero persistence. No Redis SETNX
   idempotency, no Redis distributed lock as the concurrency guard, no Celery result backend as the
   job record. PostgreSQL is authoritative and Redis loss must never lose financial truth.
4. **PROHIBITED — a generic `deleted_at` added to every financial table.** No soft-delete mixin on
   the base class. Retirement is a governed, table-specific state machine (`cancelled`, `voided`,
   `superseded`, `replaced`, `archived`) plus policy records. No base repository exposes a generic
   `delete()` or `update(**fields)` for a financial aggregate.
5. **PROHIBITED — SQLite used as proof that PostgreSQL constraints work.** Every repository, locking,
   index, partial-unique, JSONB, transaction, constraint, concurrency and migration test runs on
   PostgreSQL 16.14. Partial unique indexes, composite FKs, row locks, SKIP LOCKED and privilege
   behaviour either do not exist or differ in SQLite.

Additional cross-cutting rules, each binding on every slice:

6. No `organizations` table, no `organization_id`, no `tenant_id`, no `center_id` propagated to child
   tables, no tenant-switching logic (`15_Agent_Implementation_Plan.md:539`). `center_profile` is a
   single-row deployment singleton, not a soft tenant table.
7. No floating-point or JSON `number` for money anywhere — columns, ORM types, Pydantic fields,
   serialisers, fixtures or generated TypeScript. Canonical money is integer IRR in BIGINT; API
   financial fields are base-10 integer strings; frontends use BigInt or an integer-safe decimal.
8. No monetary unit inferred from magnitude, formatting, actor or page context. TOMAN→IRR is exact
   multiplication by ten. No hidden tolerance or epsilon in any allocation or equality comparison.
   Overpayment creates reconciliation work and is never normalised into success.
9. No generic `PATCH {status}` financial endpoint, no generic CRUD over sensitive records, no mass
   assignment. Commands are explicit and intention-revealing; routers stay thin and never commit.
10. Never send a Celery task or publish a notification before commit. The transactional outbox is the
    only legal pre-commit emission mechanism, and no external network call happens inside a financial
    database transaction.
11. Applied Alembic migrations are never edited. `20260720_0001_runtime_baseline.py` is the recorded
    M1 head and is immutable. Alembic is the only normal schema-change mechanism; no `create_all()`,
    no manual production DDL outside a documented emergency with a follow-up migration and an
    incident record. `EXPECTED_MIGRATION_HEADS` is updated in the same commit as every new revision.
12. Runtime roles must not own the schema and must not UPDATE or DELETE append-only audit,
    security-event or approval records. Enforced by GRANT, not by application convention or an ORM
    hook, and proven by a test that connects **as the runtime role** whose name is byte-identical to
    the username in the runtime `DATABASE_URL`.
13. Raw storage paths and raw storage keys are never client contracts and never returned to clients.
    A file visibility flag is never sufficient authorization by itself; access is decided by the
    ownership relationship chain (`04_Database_Schema.md:655`).
14. No invention: no new financial statuses, approval authorities, deletion behaviour, bank rules,
    tenant boundaries, AI authority, hidden fallback behaviour, alternate money units or conversion
    assumptions, and no direct mutable relationship replacing an approved version/history entity. A
    necessary assumption is written explicitly and never weakens an approved invariant.
15. Every status CHECK value comes from the approved canonical catalogue. Aliases are never
    implemented as database or API values and never broaden a grant. No unresolved alias
    (`canonical: null`) is implemented as an automatic mapping (`status_catalog.yaml:39`). The legacy
    PRD spellings `included_in_batch`, `needs_retry`, `confirmed_by_trader`, `disputed_by_trader` and
    `payment_request.bank_result_pending` never reach schema, API or UI. VARCHAR plus named CHECK,
    never a native PostgreSQL ENUM, and an unknown status string is never accepted for forward
    compatibility.
16. Only canonical permission identifiers are seeded. Document-05 API spellings are deprecated
    aliases and are not grantable rows. Unknown permission, role or alias resolves to deny; a role
    name alone is never authorization; a frontend check is never authorization; the backend is
    authoritative.
17. No permanently omnipotent `super_admin`, and no break-glass route, permission grant, **feature
    flag**, runtime activation path, table or column. `technical_admin` receives no implicit financial
    authority. Workers and system actors never approve, confirm payment, publish, dispatch or override
    a control.
18. No governed deletion, purge, retention execution, retention reduction or expiry sweeper of any
    kind. ADR-005 and OPS-005 are Open and the procedures that would authorise an append-only
    UPDATE/DELETE do not exist, so the effective M2 rule is zero UPDATE/DELETE on append-only tables.
    `expires_at` may exist; nothing may act on it.
19. Every `CheckConstraint` is explicitly named. `app/db/base.py:11` contains `%(constraint_name)s`,
    so an unnamed one raises `InvalidRequestError` at DDL time — and an unnamed constraint cannot be
    asserted on or altered later. Generated `ix`/`uq`/`fk` identifiers stay under PostgreSQL's 63-byte
    limit, or two different constraints silently collide into one name.
20. All timestamps are timezone-aware TIMESTAMPTZ normalised to UTC. `ensure_utc` already raises on a
    naive datetime; no model, default or migration may bypass it. Business-day and cutoff evaluation
    uses the IANA tz database for `Asia/Tehran`, never server-local time and never a hard-coded
    offset. Jalali is presentation only.
21. Never trust actor ID, trader ID, role, approval state, totals or file visibility from the request
    payload. Actor identity, roles, permissions, session assurance, IP and user agent come from the
    authenticated request context only.
22. Audit and log output never contains passwords, password hashes, session secrets, CSRF tokens, API
    keys, raw session tokens, raw idempotency keys, storage credentials, AI keys, raw file contents,
    unnecessarily full IBANs, national IDs, signed URLs, raw bank rows or unbounded provider
    payloads (`04_Database_Schema.md:1470`). Redaction happens at **write** time because audit rows
    can never be UPDATEd. JSON metadata never substitutes for a required first-class audit column and
    never exists without `metadata_schema` and `metadata_version`.
23. No lock is held across user interaction, file upload, storage I/O, preview rendering or any
    network call. File generation and notification delivery happen strictly after commit.
    `SELECT ... FOR UPDATE` is restricted to the enumerated coordination points, always through the
    shared helper, always in the one documented global ordering.
24. Last-write-wins is prohibited for financial and configuration aggregates. Optimistic concurrency
    uses an explicit `record_version` column mapped to ETag/If-Match with the predicate in the SQL and
    an affected-row-count check — never `xmin`, `updated_at` or a row hash, and never a
    read-then-compare in Python under READ COMMITTED. Zero updated rows is a conflict, never a silent
    overwrite.
25. No binary file content in PostgreSQL. The database holds file metadata only; streaming
    upload/download belongs to the storage layer.
26. No partitioning and no BRIN indexes on `audit_logs`, `auth_events` or `outbox_events` in
    Phase 1A — only after measured growth (`04_Database_Schema.md:1679`). Every FK on a frequently
    joined or deleted-parent path gets an explicit index; near-duplicate indexes across doc-04 §11
    and §18 are deduplicated as a recorded decision rather than created twice.
27. No real trader, bank, payment, personal or production credential data anywhere — not in fixtures,
    tests, seeds, staging or source control. All fixtures are synthetic, versioned and named. No
    default passwords or seeded credentials in migrations or images. No real bank hard-coded as a
    universal default, and no seeded bank rule, transfer limit, cutoff or named production bank
    profile.
28. No AI tables and no enabled AI/OCR job type. The `ai` queue prefix may exist in the naming
    convention with no Phase 1A producer, and file jobs are never labelled AI jobs
    (`04_Database_Schema.md:1352`). All AI providers stay disabled and no production data is
    transmitted.
29. On any conflict, apply the §2.2 precedence order, never silently choose an interpretation, and
    record the conflict in the task and the PR.
30. No coding begins until the 16-point preflight is written into the task or implementation note,
    and every task uses the canonical task contract structure verbatim.
31. No milestone or slice is complete on the basis of a UI demo, a green migration, or a passing happy
    path alone. A critical invariant is not covered because one E2E test passes, and the implementing
    developer is never the sole approver of a high-risk feature's production acceptance.

---

# 6. Evidence obligations, mapped to the repository's verification scripts and CI gates

## 6.1 Existing verification surface

| Mechanism | Location | What M2 must add |
|---|---|---|
| Native verifier (shell) | `infra/scripts/verify-native.sh` | PostgreSQL-backed integration stage; migration clean + upgrade stages; ruff/mypy targets extended to `tests/integration`; the explicit environment block (`DATABASE_URL` per identity, `REDIS_URL`, absolute `LOCAL_STORAGE_ROOT`), with a pinned invocation directory so no stray `.env` reaches `Settings`. |
| Native verifier (PowerShell) | `infra/scripts/verify-native.ps1` | Identical stages, same order. CI-PARITY-001 fails if it drifts. |
| Docker verifier | `infra/scripts/verify-docker.sh` / `.ps1` | Migration/upgrade assertions on the compose `migrate` one-shot; role-privilege assertions executed as the app and worker identities; `OPS-REDIS-001` if the native job has no Redis container. The verifier recreates the stack **without** deleting volumes, which is exactly why slice 2 forbids fixing roles by editing the init script. |
| Repository validator | `infra/scripts/validate_repository.py:53-74` | `tests/integration` added to `required_paths`; role-name/URL identity assertion; no-`deleted_at` structural check; break-glass absence check. |
| Secret scanner | `infra/scripts/scan_secrets.py` | Must stay green with the new fixtures; no seeded credentials. |
| CI: `native` job | `.github/workflows/m1-verify.yml:49-94` | `postgres:16.14-alpine3.24` service container (there is none today); optional pinned Redis; the environment block; markers registered before use. |
| CI: `openapi-compat` job | `:96-134` | Additive paths only. A new field on `ReadinessResponse` would trip the gate with no waiver process. |
| CI: `docker-acceptance` job | `:135-260` | Already starts PostgreSQL via compose; extended with the migration and role-privilege gates. |
| CI: `secret-scan` job | `:30-47` | Unchanged. |
| Migration head constant | `services/backend/app/db/migrations.py:7` | Updated in the same commit as each revision; the M1 tripwire at `tests/backend/test_runtime_foundation.py:9-11` replaced by a metadata↔head consistency assertion. |
| Committed OpenAPI | `services/backend/openapi/v1.json` | Regenerated deterministically; operationId set, absent `HTTPValidationError` (`tests/backend/test_openapi_contract.py:44`) and absent `postgresql` substring (`:105`) all still asserted. |
| M0 manifest | `docs/governance/M0_MANIFEST.json` | Regenerated with the governance corrections, plus a new hash-drift CI gate (slice 10). |

## 6.2 Per-slice obligations

- **The 16-point preflight** written into the task or implementation note **before any coding** on
  every slice: task ID and milestone; authoritative document sections; affected aggregates and
  immutable records; command versus query; permissions and ownership scope; status transition and
  guards; idempotency requirement; concurrency or lock requirement; audit action and outbox event;
  file lifecycle implications; migration requirements; tests and acceptance evidence; observability
  requirements; rollback/forward-fix implications; explicit out-of-scope items; blocking ADRs. This
  is an absolute gate.
- **Canonical task contract structure used verbatim**, because its fields — idempotency requirement,
  concurrency/locking requirement, audit actions, outbox events, database migration and constraints —
  are precisely the M2 surface an unstructured task omits.
- **A handoff per slice** containing: implementation summary; files changed; migration IDs and upgrade
  behaviour (the only record operators have at deploy time); API/contract changes; permissions and
  security implications; audit and outbox events; idempotency and concurrency behaviour; tests added
  and results; manual verification; observability and runbook changes; assumptions and remaining
  ADRs; and confirmation that no prohibited Phase 1A scope was added.
- **Sensitive-task evidence** for slices 2, 6 and 7: test IDs; database state before and after; audit
  event evidence; idempotency replay evidence; stale and concurrent request evidence;
  permission-denial evidence; failure/rollback behaviour.
- **The PR checklist** satisfied on every slice: docs referenced; schema/API/status changes
  described; migration reviewed; permissions reviewed; audit/outbox/idempotency reviewed; negative
  tests included; sensitive logging reviewed; generated artifacts updated; docs synchronized; feature
  flags safe; no deleted history; no raw storage paths; no floating-point money; no generic financial
  status mutation. Migrations require **both** a database reviewer and a backend reviewer.
- **Recorded conflict entries** for every divergence in section 2.3, in the task **and** the PR.
- **Proof executed as the runtime role**, not the owner (section 4, slice 2), which is why the
  harness needs three distinct connection identities.
- **Named owners exercised**: the QA lead owns the plan and release recommendation; the security
  reviewer owns append-only audit, database role separation and the permission-matrix baseline; the
  DevOps/operations owner owns migration, backup role and restore evidence
  (`14_Testing_QA_Acceptance.md:219-288`). The implementing developer may contribute test evidence but
  is never the sole approver of a high-risk feature's production acceptance, and a High defect may
  only be accepted by a formal time-bounded joint decision of business, technical and security
  owners — never for unauthorized money movement or data exposure.
- **A business-owner validation record for every bank mapping fixture version**, as a reviewable
  document rather than a code-only factory, alongside the field-mapping, required-column, row-order,
  amount-format, encoding, formula-injection, maximum-length and source-account tests.
- **A stable catalogue test ID on every test M2 creates**, with the traceability mapping completed.
- **Environment parity recorded**: PostgreSQL 16.14 fixed and stated for the constraint, locking and
  concurrency acceptance evidence, so CI and staging cannot drift to a version with different index
  or lock semantics (DOC-CONFLICT-022, `CONFLICT_REGISTER.md:44`).
- **Performance evidence recorded with volume and environment**; numbers without both are not
  acceptable evidence.
- **Confirmation on every slice** that no real trader, bank, payment, personal or production
  credential data was used and that all fixtures are synthetic and versioned.

## 6.3 The fifteen-item release evidence set for the M2 release candidate

Test-run identifier; application commit and image digests; Alembic revision read from the running
application; environment identifier; feature-flag snapshot showing AI disabled; bank-profile and
mapping fixture versions; test data-set version; automated test reports; failed-test details; manual
QA evidence; UAT sign-off; security review result; **backup/restore drill result — unfillable at M2
because ADR-004 is Open, and that gap must be stated rather than left blank**; known-risk acceptance
records.

---

# 7. Known gaps and residual risk

## 7.1 Resolved by this plan (previously unincorporated)

| # | Gap | Resolution in this plan |
|---|---|---|
| 1, 2 | The draft renamed the audit table to `audit_events` with no recorded conflict, against `04_Database_Schema.md:1436`, `:278`, `:1847`, `05_API_Specification.md:729` and `10_Backend_Implementation_Guide.md:570`, while recording six lesser divergences — and applied migrations can never be edited. | Table is `audit_logs`; UoW attribute is `uow.audit_logs`; doc-04 index names retained; only the **column** vocabulary diverges, recorded as new conflict (g) in slice 10 with the `idx_audit_action_time` rename stated. Sections 2.2, 2.3 b, 4.1. |
| 3 | Slice 7 seeded `break_glass_enabled = false`, which Approved POL-005 / `FINANCIAL_INTEGRITY_BASELINE.md:101-102` forbid as a **flag**, contradicting the plan's own cross-cutting rule and failing SEC-BREAKGLASS-001. | The flag is not seeded in any value; OPS-FLAG-001 asserts exactly five rows and no `break_glass*` key; SEC-BREAKGLASS-001 re-scoped to "no route, no grant, no flag, no activation path" so it does not fail on the approved catalogue's zero-grant permission rows; the runbook contradiction is raised as new conflict (h). Sections 4.7, 4.6, 4.10. |
| 4, 9 | Slice 2 fixed five `platform_*` role literals while the app and migrator connect as `${APP_DB_USER}`/`${MIGRATION_DB_USER}`, so the REVOKE and SEC-ROLE tests would target roles nothing uses while the real app role inherits UPDATE/DELETE on the new audit table via `010-create-runtime-roles.sh:41-42`. | Role names are configuration resolved from `Settings`; doc 04 §3.2 names recorded as labels; SEC-ROLE-000 asserts byte-identity with the runtime `DATABASE_URL` username; the migration also explicitly revokes already-materialised privileges and fails loudly when a configured role is absent. Section 4.2. |
| 5 | `ADR-014` cited as a canonical blocking decision, violating Approved DOC-CONFLICT-003's namespace rule. | Every citation is **POL-006** (`ADR_INDEX.md:56`), with the operational-volume remainder noted as an unrepresented composite alias scope per `ADR_INDEX.md:94` — **not** asserted as out of Phase 1A scope, because no owner has decided that. Section 2.2. |
| 6 | Slice 8 declared "one genuine value conflict" and shipped a five-value `scan_status` including `skipped_by_approved_policy`, silently deciding part of Open DOC-CONFLICT-029 with no approved skip policy and ADR-008 Open. | Two value conflicts declared; both decisions cited; `scan_status` ships with **no** value CHECK; `skipped_by_approved_policy` is reserved and unsettable; availability is gated by a named conditional constraint in the fail-closed direction ADR-008's safe default requires. Sections 2.3 d, 4.8. |
| 7 | Slice 10 assumed the `M0_MANIFEST.json` checksum chain was intact. Recomputation gives 10 of 17 hashes drifted, five of which were wrong at generation time; `decision_state` still records 2 approvals and 26 open conflicts; commit `ae93d79` modified five manifest-covered files without touching the manifest, against `docs/governance/README.md:64`. | Slice 10 regenerates the manifest in the same commit as the governance corrections, adds a CI hash-drift gate (CI-MANIFEST-001), and states plainly that no M2 citation currently has manifest backing. Section 4.10. |
| 8 | The draft's ADR_INDEX correction was inverted, treating the header's "30 Open" as stale and the count table's 31 as the reference; enumerating rows gives 30 Open, so applying it would have injected an error into an approved-decision register. | The Count control row `ADR_INDEX.md:86-87` is the stale record and becomes Approved 3 / Open 30; the header stands; `docs/governance/README.md:15` and `TRACEABILITY_MATRIX.md:22` carry the same drift and are corrected in the same commit. Section 4.10. |
| 10 | No environment block or Redis container was specified for the integration and migration stages, although `alembic/env.py:19-21` builds the whole `Settings` object and `tests/integration/README.md` demands real PostgreSQL **and** Redis containers. | The environment block is an explicit slice 1 deliverable, including the `env_file=".env"` + `extra="forbid"` trap and a pinned invocation directory; Redis is either a pinned service container in the native job or `OPS-REDIS-001` moves to the Docker gate, stated in the handoff. Sections 4.1, 4.4, 6.1. |

## 7.2 Residual risk that M2 cannot close

| Item | Why it cannot be closed in M2 | Containment | What would close it |
|---|---|---|---|
| Audit `actor_type` vocabulary | Docs 04 and 12 disagree; the conflict is absent from `CONFLICT_REGISTER.md`; §2.2 gives an answer but applied migrations can never be edited, so this is a permanent bet made in a migration. | Named (alterable) CHECK; conflict recorded; owner sign-off requested before merge. A missing constraint would be the worse hole. | Owner confirmation of doc 12's four values, or an explicit decision to use doc 04's. |
| `file_objects.storage_status` | Four authorities state the same seven values; the approved catalogue records `canonical: null` and forbids canonicalising `deleted` vs `deleted_by_policy`. There is no way to be simultaneously complete and fully compliant. | Named seven-value CHECK excluding `deleted_by_policy` on a recorded reconciliation, or no value CHECK with expand/contract later. | An owner decision on the `file_object` status set, closing DOC-CONFLICT-029's lifecycle half. |
| `file_objects.scan_status` | DOC-CONFLICT-029 and ADR-008 both Open. | No value CHECK; reserved value; fail-closed availability constraint. | ADR-008 (scanning/quarantine policy) plus the DOC-CONFLICT-029 lifecycle synchronization. |
| `identity_account` status | Docs 04 and 12 disagree in count and names; the catalogue approves neither. | No CHECK in M2; application-enforced fail-closed; CHECK lands in M3. | An owner decision on the identity-account lifecycle, separate from trader business state. |
| `trader_users.trader_id` has no FK target | `traders` is migration Group C; Group A does not include it. Neither creating a Group C table in M2 nor omitting the trader identity table `15_Agent_Implementation_Plan.md:527` requires is acceptable. | Column NOT NULL without its FK; FK attached by expand/contract when `traders` lands — the pattern already sanctioned for `recent_auth_context_id`. An accepted, recorded gap, not a clean answer. | DOC-CONFLICT-005 closing and Group C landing in M5. |
| The audit UPDATE/DELETE escape hatch | `FINANCIAL_INTEGRITY_BASELINE.md:87-89` permits mutation only through governed retention or legal-hold procedures, and ADR-005/OPS-005 mean those procedures do not exist. | M2 delivers no escape hatch; the effective rule is zero UPDATE/DELETE. The revocation stays **scoped** to runtime roles and no unconditional `BEFORE DELETE` trigger is installed, or governed retention becomes unaddable later without dropping the guard. | ADR-005 and OPS-005 approval. |
| Backup/restore evidence | ADR-004 is Open and backup claims are invalid until a clean full restore drill succeeds. | The evidence item is explicitly stated as unfillable rather than left blank. | ADR-004 plus a passing restore drill. |
| OpenAPI breaking-change waiver | The waiver process is an unresolved `TODO(governance)`. | Avoided rather than blocking: observability ships as a new restricted path instead of new fields on `ReadinessResponse`. The underlying governance gap is recorded. | An approved waiver process for the oasdiff gate. |
| `M0_MANIFEST.json` provenance | Five recorded hashes were wrong at generation time, so the chain never held; regeneration establishes provenance from now on, not retroactively. | Regeneration + CI hash gate; the historical invalidity is stated rather than papered over. | Owner re-approval of the regenerated manifest as the M0 checksum baseline. |
| `CONFLICT_REGISTER` / README / ADR_INDEX / TRACEABILITY counts | Four registers disagree with their own rows after the 2026-08-01 decision session. | Corrected in slice 10 by row enumeration, in the same commit as the manifest regeneration. | The corrections merging and the manifest hashes matching. |
| Provisional audit/outbox, error and command catalogues | `provisional_pending_m0_approval`; the response envelope is not frozen. | One indirection layer for every audit action and outbox event name; the two naming conventions never normalised. | M0 freeze of the three remaining catalogues. |
| DOC-CONFLICT-032 worker topology | Open; concrete containers, health ownership and resource limits blocked. | Six logical queue prefixes preserved even under one pilot process; collapsing to one queue would force a data migration. | An operations decision on the pilot topology. |

---

# 8. Owner decisions required before slice 1 starts

Slice 1 is not blocked by any Open decision, but three items must be settled or explicitly accepted
before its pull request can merge, and two more before slice 2.

1. **Audit `actor_type` vocabulary** (before slice 1 merges). Confirm doc 12's four values
   `trader_user/admin_user/system_worker/system_maintenance` as the named CHECK, or direct doc 04's
   set. Applied migrations are never edited; a named CHECK is alterable but the column values already
   written are not.
2. **Audit column vocabulary and index rename** (before slice 1 merges). Confirm that baseline §4
   wording (`action`, three separate correlation/causation/request columns, `outcome`,
   `audit_schema_version`) supersedes doc 04 §15.3's `event_type` and single `request_id`, and that
   `idx_audit_event_time` becomes `idx_audit_action_time` while `idx_audit_entity_time` and
   `idx_audit_actor_time` keep their doc-04 names.
3. **Redis in CI** (before slice 1 merges, because it shapes the workflow file). Either approve a
   pinned `redis:7.4.9-alpine3.21` service container in the `native` job, or accept that
   `OPS-REDIS-001` and all Redis-loss evidence live only in the Docker gate.
4. **Database role identity strategy** (before slice 2 starts). Approve "role names are
   configuration, resolved from `Settings`, doc 04 §3.2 names recorded as labels", or direct a rename
   of the deployment identities to `platform_*` — which requires editing `.env.example`,
   `infra/compose/compose.local.yml`, `infra/postgres/init/010-create-runtime-roles.sh` and
   `infra/scripts/validate_repository.py` together and coordinating with every existing volume.
5. **Credential provisioning for the three new roles** (before slice 2 starts). Confirm the
   out-of-band provisioning step (migrator-identity script reading passwords from the environment) as
   the mechanism, since the worker, read-only and backup roles must be connectable for SEC-ROLE-003
   and SEC-ROLE-005 while no password may enter a migration file.

Deferred but worth requesting in the same session, because slices 8 and 9 stall without them:
`file_objects.storage_status` sign-off (section 7.2), ADR-008, and the `identity_account` status
decision.
