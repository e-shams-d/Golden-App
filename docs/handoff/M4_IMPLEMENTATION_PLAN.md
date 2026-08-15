# M4 Implementation Plan — Versioned Bank Configuration and Private-File Lifecycle

Status: Working implementation plan for hand-off to implementers. Not an approved M0 artifact.
Milestone authority: `Implementation Docs/00_Start_Here/15_Agent_Implementation_Plan.md:670-733`.
Precondition: M3 as merged — authentication, RBAC, ownership guards, recent-auth and the
router-enumeration gate exist; ADR-001 is Approved; the Unit of Work commits business state with
audit, outbox and idempotency in one transaction.
Date of this revision: 2026-08-15.

Every claim traceable to a document is cited as `path:line`. Where this plan resolves a divergence
between authorities, the divergence is named and the resolution is recorded in section 2 so it is
raised in the pull request rather than decided silently inside a migration.

---

# 1. What M4 delivers, and the Definition of Done

## 1.1 Scope, as the milestone authority states it

`15_Agent_Implementation_Plan.md:674` sets the goal: "Create the versioned configuration and secure
file foundation required before payment workflows rely on bank-specific behavior."

`:676-686` lists nine bank-configuration deliverables: profiles; immutable versions; source bank
accounts; immutable mappings/templates; splitting-rule configuration; effective-date/version
handling; test fixture bank profiles; configuration validation and audit; and **no fake production
bank configuration**.

`:688-701` lists thirteen file-lifecycle deliverables: pending upload initiation; streaming upload
without holding a long database transaction; size/extension/MIME/signature validation; checksum
calculation; scan and quarantine state; finalize-to-available; private authorized preview and
download; original/derived relationships; preview job dispatch through the outbox; stale-pending and
orphan reconciliation; a storage adapter interface; and a local pilot adapter with an
object-storage boundary.

`:703-715` fixes the file states. `:717-726` lists eight tests.

## 1.2 Definition of Done (verbatim)

`15_Agent_Implementation_Plan.md:730`:

> M4 is complete when every later module can reference a stable `FileObject` and a stable bank
> configuration version without directly handling storage paths or mutable bank settings.

Like M3's, this DoD names a **property**, not an artifact — and the property is about code that does
not exist yet. "Every later module" is M5 through M12. Nothing in M4 can test M5's behaviour.

What can be tested is the **boundary that makes the property true**, and it decomposes into three
mechanical claims:

1. A storage address never leaves the file service. No module outside the file and storage packages
   imports the storage backend or names `storage_key`, `storage_bucket` or `storage_provider`; and
   no response schema in the published OpenAPI document carries any of those three names.
2. A `FileObject` is referenceable by id alone. A later module attaches a file to its own resource
   and authorizes downloads of it **without writing an authorization branch of its own** — it
   registers an ownership resolver for its category, and the registry denies any category with no
   resolver.
3. Operational bank rules are readable only through a version. `bank_profiles` carries identity and
   nothing operational (verified: `code`, `name`, `status`, `current_version_id`, `record_version`,
   timestamps — `app/db/models/bank.py:105-124`, matching `04_Database_Schema.md:535`), so "without
   directly handling mutable bank settings" is already structurally true at the schema. M4's job is
   to keep it true at the service boundary and to prove there is no second way in.

Slice 11 is that gate. Every earlier slice is written to feed it.

`docs/governance/TRACEABILITY_MATRIX.md:26` restates the gate and adds what the DoD sentence omits:
"Versioned synthetic bank fixtures validate; FileObject hides raw storage keys; unauthorized/guessed
downloads fail; quarantine and checksum guards work; missing/orphan objects reconcile; retry creates
no duplicate record; later modules consume stable file/config IDs only."

The same row records M4's admissible status: "Provisional — production storage, bank fixtures,
scanning, and limits remain open."

## 1.3 The fact that determines this plan's shape

**M4's entire foundation already exists and has never been called.**

M2 shipped seven tables (`bank_profiles`, `bank_profile_versions`, `bank_accounts`, `bank_mappings`,
`file_objects`, `file_links`, `file_derivations`), a storage backend protocol
(`app/storage/interface.py`), a local filesystem adapter (`app/storage/local.py`), an opaque
server-generated key builder (`app/storage/keys.py`) and six reconciliation checks
(`app/storage/reconciliation.py`).

A search of `services/backend` for `LocalStorageBackend`, `StorageBackend`, `generate_storage_key`
and the reconciliation functions returns six files: the four that define them, plus
`app/core/runtime.py:52` which constructs the backend into the runtime container, and
`app/observability/health.py` which probes it for readiness.

So: **the platform checks at startup that it can reach a storage backend it never writes to.**
`generate_storage_key` has no production caller. Not one of the six reconciliation checks has a
caller of any kind — no route, no CLI, no scheduled job.

This is the defect that recurred five times in M3 — a complete, tested, imported-nowhere mechanism —
and here it is the shape of the whole milestone rather than one slice's oversight. It is not a
criticism of M2, which built the schema deliberately ahead of its consumers and said so. It is the
reason M4's slices are ordered by **caller** rather than by capability: the first slice that touches
files makes bytes travel end to end through the machinery that exists, and no slice in this plan is
allowed to add a mechanism whose acceptance test is the only thing that calls it.

Two obligations exist in this plan solely to make that rule enforceable rather than aspirational —
`TRACE-CALLER-001` in slice 2 and `TRACE-CALLER-002` in slice 7.

---

# 2. Authority, precedence, and the decisions this plan makes

## 2.1 Precedence order

`15_Agent_Implementation_Plan.md` §2.2 fixes the order: approved decision/ADR → security and
financial invariants → domain/workflow rules → database integrity → API contract →
architecture/implementation guides → UI/UX → future-phase guidance. It forbids silently choosing an
interpretation and requires the conflict to be recorded in the task and the pull request.

Baselines that bind M4 directly:

| Baseline | What it settles for M4 |
|---|---|
| **DOC-CONFLICT-036, Approved 2026-08-06** | `file_objects.storage_status` is a seven-value CHECK keeping `deleted` and refusing `deleted_by_policy`. M4 uses exactly those seven and adds none. Widening is a visible migration. |
| **DOC-CONFLICT-029, Open** | Unknown or skipped scans fail closed; no file becomes available evidence until ADR-008 and the lifecycle fields are synchronised. Owner: Security Lead + File Processing Lead + Database Lead. Blocking milestone named as M4. See §2.7. |
| **DOC-CONFLICT-042, Approved 2026-08-06** | Index naming by rule: an index doc 04 names keeps that name written explicitly; an index this codebase introduces takes the generated `ix_*` form. Blocking milestone recorded as "M4 onwards, every new index". |
| `docs/governance/permission_catalog.yaml` (approved 2026-08-01) | `file.upload`, `file.read_metadata`, `file.preview`, `file.download`, `file.download_bank_export`, `file.read_sensitive_bundle`, `file.quarantine_review` (`:607-638`); `bank_profile.read`, `bank_profile.create_version`, `bank_mapping.create_version`, `source_bank_account.manage` (`:687-706`). **There is no activation permission** — see §2.5. |
| `docs/governance/command_catalog.yaml` (provisional) | Global rules bind every command M4 writes: `backend_is_authority`, `deny_by_default`, `one_command_one_transaction`, `audit_same_transaction`, `idempotency_result_same_transaction`, and `raw_storage_keys_never_returned` (`:9-18`). Eleven M4-relevant commands carry a blocked status — see §2.4. |
| `docs/governance/status_catalog.yaml` (approved 2026-08-01) | `bank_profile_version` and `bank_mapping` are `canonical: null` with aliases `[draft, active, retired]` (`:634-640`). M4 uses those three and does not canonicalise the aggregate. |
| **ADR-001, Approved 2026-08-08** | Cookie-carried server-side sessions with CSRF on unsafe methods. Every file route in M4 is an authenticated route under that scheme; nothing in M4 introduces a second credential, and no signed URL is issued (§2.8). |

## 2.2 What M2 already shipped, and therefore what M4 must not rebuild

Present, migrated and tested:

- **Seven tables**, with the constraints that matter already enforced at the database:
  - `uq_file_objects_storage_address` — two rows may not claim the same object, which is how a
    duplicate write after a retry becomes two competing metadata records;
  - `available_requires_hash` (FILE-META-002) — a file cannot be `available` without a checksum;
  - `available_requires_clean_scan` (FILE-META-003) — a **whitelist of the single value `clean`**,
    so an unrecognised scan outcome fails closed rather than through;
  - `ck_file_objects_physical_deletion_implies_deleted_status` — a row cannot claim its bytes are
    gone while still offering them.
- **`bank_profiles.current_version_id` as a composite deferrable foreign key**
  `(current_version_id, id) REFERENCES bank_profile_versions (id, bank_profile_id)`, so a profile
  cannot point at another bank's configuration, and a profile with its first version is insertable
  in one transaction without a window where the pointer is null.
- **Column-level UPDATE grants** on `bank_profile_versions` and `bank_mappings`: the runtime may
  update `status` and nothing else. "Immutable except for a controlled status transition" is not
  expressible as a table-level privilege, and a comment saying so does not stop an UPDATE. M4's
  activation command is written against this grant and must not widen it (§2.6).
- **Uniques scoped deliberately**: `(bank_profile_id, config_hash)` stops an operator recreating an
  identical configuration as a "new" version, which would break the audit link between a batch and
  the configuration that produced it. Both mapping uniques include `file_type`.
- **Nothing seeded, in any value.** `tests/integration/` asserts the bank migrations insert nothing
  at all. ADR-007's safe default is synthetic fixtures only, and the reason recorded in
  `app/db/models/bank.py:3-8` is specific: a seeded transfer limit would silently drive real
  splitting decisions the first time a batch was built.
- **`app/storage/keys.py`** — `<category>/<YYYY>/<MM>/<DD>/<32 hex>`, 128 bits from `secrets`,
  nothing client-derived in the path, no extension. The category is constrained to
  `^[a-z][a-z0-9_]{0,39}$` and the module says why: "categories come from our own code today, and
  the point of a guard is the caller who does not exist yet." **M4 is that caller** (slice 1).
- **`app/storage/reconciliation.py`** — six checks returning `Finding` objects:
  `storage_objects_without_a_record`, `records_without_a_storage_object`, `stale_pending_uploads`,
  `derivatives_without_a_derivation`, `checksum_mismatches`, `stuck_processing_jobs`. M4 gives them
  an operator entry point (slice 7); it does not rewrite them.

M4 therefore writes **no new table** except where §2.6 records a migration and its reason, and
**no new storage primitive**. It writes commands, routes, screens and callers.

## 2.3 Four open decisions sit on top of M4, and each blocks a different thing

| Decision | Safe default (`docs/adr/ADR_INDEX.md`) | What it actually blocks in M4 |
|---|---|---|
| **ADR-003** — production private-file storage adapter and location | "Use the storage abstraction; local pilot storage is non-production unless backup and restore evidence passes." | Nothing structural. The abstraction exists and M4 uses it. Blocks calling the local adapter production-ready. |
| **ADR-007** — initial bank profiles, verified templates, mappings, limits, source accounts | "Synthetic fixtures only; no real final export UAT or production bank output." | The **content** of bank configuration, not the mechanism. See §2.4. |
| **ADR-008** — malware scanning and quarantine policy | "Quarantine or deny production use when scan status cannot satisfy the approved policy; never treat an unchecked file as available evidence." | Whether a file can become `available` in production. See §2.7. |
| **POL-006** — production file size/type limits | "No guessed production values; use conservative development-only limits and block production acceptance/load sign-off." | The **numbers**, not the enforcement. M4 enforces limits; the values are development-only and labelled as such. |
| **ADR-005** — retention, deletion, legal hold, approval governance | "No automated purge or retention reduction; preserve legal-hold capability and historical financial evidence." | The entire retention/legal-hold API surface. M4 builds none of it (§2.8). |

The pattern across all five is the same and it is worth stating once: **each open decision blocks a
value, a policy or a production claim — none of them blocks a boundary.** A plan that read them as
blocking the boundary would defer M4 entirely and leave M5 to invent a file service under deadline.
A plan that ignored them would ship guessed limits and a bank profile somebody would later mistake
for a real one. This plan builds every boundary, enforces every rule that does not require an
undecided value, and refuses at startup where a production claim would be false.

## 2.4 The blocked commands, and what "blocked" is allowed to mean

`command_catalog.yaml` marks eleven M4-relevant commands with a non-provisional status:

| Command | Status in the catalogue |
|---|---|
| `bank_profile.create_version` | `blocked_by_initial_bank_profile_adr` |
| `bank_profile.activate_version` | `blocked_by_permission_gap_and_ADR_007` |
| `bank_mapping.create_version` | `blocked_by_initial_bank_profile_adr` |
| `bank_mapping.activate` | `blocked_by_permission_gap_and_ADR_007` |
| `source_bank_account.create` | `blocked_by_initial_bank_profile_adr` |
| `retention.propose` / `.approve` / `.activate` | `blocked_by_retention_adr` |
| `legal_hold.create` | `blocked_by_retention_adr` |
| `legal_hold.release` | `blocked_by_release_authority_and_retention_adr` |
| `file.quarantine_review` | `blocked_by_missing_api_contract_and_ADR_008` |

**Decision.** `blocked_by_initial_bank_profile_adr` blocks the *data*, not the *route*. ADR-007's
title is "Initial bank profiles, verified templates, mappings, limits, and source accounts" and its
safe default is "synthetic fixtures only" — a sentence that presumes fixtures can be created, which
presumes a creation path. `15_Agent_Implementation_Plan.md:684` lists "test fixture bank profiles"
as an M4 deliverable in the same list as `:685`, "configuration validation and audit". A milestone
cannot validate configuration it has no way to create.

So slices 8 and 9 build `bank_profile.create_version`, `bank_mapping.create_version` and
`source_bank_account.create` as routes with full guards, and the ADR-007 constraint is enforced as a
**refusal at the boundary**, tested: no bank profile may be created outside a non-production
environment, and the fixture set is explicitly synthetic (§ slice 8, `BANK-FIXTURE-002`).

`blocked_by_retention_adr` blocks both the data and the route, because ADR-005's safe default is "no
automated purge or retention reduction" and every one of those five commands *is* the reduction
machinery. M4 builds none of them, and `test_no_deletion_machinery.py` — which already forbids every
`delete(...)` while ADR-005 is open — remains the enforcement.

`file.quarantine_review` is blocked on a **missing API contract**, which is a different thing from a
missing decision: doc 05 §14 defines no quarantine-review endpoint at all, and the catalogue records
its method and path as `TBD`. M4 does not invent one. Quarantined files are visible through
`GET /api/v1/files/{id}` metadata and through the reconciliation report (slice 7); releasing one
from quarantine is not implemented, and slice 4 records that a quarantined file has no exit.

## 2.5 DOC-CONFLICT-045 — activation is a critical audited command with no permission

`05_API_Specification.md:2110-2111` and `:2122` define `POST /bank-profile-versions/{id}/activate`,
`POST /bank-profile-versions/{id}/retire` and `POST /bank-mappings/{id}/activate`.
`05_API_Specification.md:2125` states "Activation is a critical audited command."
`08_Bank_File_and_Result_Processing.md:347-348` states "Only authorized business/configuration roles
may activate a version" and "Activation and retirement are audited."

`permission_catalog.yaml:687-706` defines `bank_profile.read`, `bank_profile.create_version`,
`bank_mapping.create_version` and `source_bank_account.manage`. **There is no
`bank_profile.activate_version` and no `bank_mapping.activate`.** `command_catalog.yaml` records the
consequence itself, as `permission: []` with `status: blocked_by_permission_gap_and_ADR_007`.

Why it matters: a command with an empty permission list under `deny_by_default` is unreachable, and
a command with a *borrowed* permission is worse. Reusing `bank_profile.create_version` would mean the
role that drafts a configuration is the role that puts it into production — which is exactly the
preparer/approver split `FINANCIAL_INTEGRITY_BASELINE.md` §5 makes non-configurable elsewhere. The
permission catalogue's own `conditional_roles` for `create_version` say `manager:
approval_or_review_only`, which describes an approval authority that has no permission to exercise.

**Resolution this plan proposes, for owner approval:** two new canonical permissions,
`bank_profile.activate_version` and `bank_mapping.activate`, defaulting to `manager` and
`business_admin` — the roles the catalogue already marks as approval authorities — and explicitly
**not** to `technical_admin`, whose conditional role on both create permissions is
`technical_validation_only` and which holds no financial authority anywhere in M3's baseline.
Constraint set `[authenticated_active, bank_configuration_change, state_guarded_command]`, matching
the neighbouring entries.

Until that approval lands, slice 9 implements activation **behind the new permission identifiers**
and the routes return `403` for every role, because no role holds a permission that does not exist
yet. That is deliberate: the route, its guards, its audit record and its negative tests are all
reviewable, and the day the permission is granted nothing else has to change. Owner: Security Lead +
Product Owner. Blocking: M4 activation; M7 export, which is the first consumer of an active mapping.

## 2.6 DOC-CONFLICT-046 — the generic upload endpoint has no command-catalogue entry

`05_API_Specification.md:976-997` defines `POST /api/v1/files` with seven Phase 1A purposes.
`command_catalog.yaml` has **no entry for it**. The catalogue's scope is "Critical financial,
evidence, publication, and dispatch mutations" (`:5`) — an evidence upload is squarely inside that —
and it does contain `bank_result_bundle.upload` at `:250-257` with
`concurrency: file_checksum_and_upload_lifecycle` and `permission: ["bank_result_bundle.upload",
"file.upload"]`. So `file.upload` exists as a permission consumed by a specific command, while the
generic endpoint that the permission is named after is uncatalogued.

The consequence is not cosmetic. Catalogued commands inherit `idempotency_result_same_transaction`
and `audit_same_transaction` from the global rules, and the catalogue is where a command's
idempotency requirement is *stated*. `15_Agent_Implementation_Plan.md:725` requires "retry does not
create duplicate file records" — an idempotency obligation with no approved idempotency contract.

**Resolution this plan proposes, for owner approval:** add `file.upload` to the catalogue with
`method: POST`, `path: /api/v1/files`, `permission: ["file.upload"]`, `idempotency: required`,
`concurrency: not_applicable_new_aggregate`, `audit_action: file.uploaded`, `outbox_event: null`,
`source: 05_API_Specification.md:976`, `status: provisional`.

Slice 2 implements it that way. The idempotency key is the caller's `Idempotency-Key` header
resolved through the existing `IdempotencyResolver`, **not** the file's checksum: two people
legitimately uploading the same document are two pieces of evidence with two owners, and
deduplicating on content would silently attach one trader's file to another's request. The checksum
is recorded, indexed and reported as a duplicate *indicator* (`12_Security_RBAC_Audit.md:1506`
requires "checksum and duplicate indicators"), and it never merges rows. Owner: API Lead + File
Processing Lead. Blocking: M4 upload; M8 bundle upload, which reuses the same path.

## 2.7 DOC-CONFLICT-047 — `bank_mappings.file_type` means two different things

`04_Database_Schema.md:596` defines `bank_mappings.file_type` as `VARCHAR(48)`, "Statement import,
outgoing export, result import" — the **mapping type**.

`08_Bank_File_and_Result_Processing.md:331` defines `BankMapping.file_type` as
`xlsx | csv | fixed_width | json` — the **file format** — and puts the mapping type in a separate
field, `mapping_type` (`:328`), whose three values are listed at `:318-320`.

The same column name carries the two meanings, and both are plausible on sight. M2 implemented doc
04's meaning, visibly: `app/db/models/bank.py:37-41` explains that both mapping uniques include
`file_type` "so an import mapping and an export mapping can both exist at `template_version` 1".
That is only coherent under the mapping-type reading. An implementer arriving from doc 08 would
write `xlsx` into that column and the unique constraints would then permit two statement-import
mappings at the same template version — the failure would surface during the first export, in M7.

The two documents also diverge on `bank_profile_versions` more broadly. Doc 08 `:289-310` lists
`valid_from`/`valid_to`, `default_amount_unit`, four `*_capabilities` blobs, `transfer_rule_config`,
`validation_config`, `activated_by` and `activated_at`. Doc 04 `:549-564` lists
`effective_from`/`effective_to`, typed columns (`default_transfer_limit_irr`,
`after_cutoff_transfer_limit_irr`, `cutoff_time`, `splitting_enabled`,
`supports_description_field`), `required_fields`, `rules`, and **no activation columns at all**.

**Resolution this plan proposes, for owner approval:** doc 04's column set is authoritative, because
database integrity outranks an implementation guide in the precedence order and because it is what
exists and is migrated. Doc 08's field list is recorded as a superset in different names, and the
mapping between them is written into the model docstring so the next reader resolves it in one
place. Two specific consequences:

- **`file_type` keeps doc 04's meaning** and slice 8 constrains it to the three mapping types with a
  value CHECK, so the doc-08 reading fails at the database rather than at M7. The file *format*
  lives inside the `mapping` JSONB, where doc 08's `sheet_selector`, `header_selector`,
  `column_definitions`, `row_validation_rules` and `formatting_rules` also land.
- **No `activated_by`/`activated_at` columns are added.** They would require widening the
  column-level UPDATE grant from one column to three, trading a real immutability guarantee for a
  denormalised copy of a fact `audit_logs` already records — and DOC-CONFLICT-040's approved
  resolution makes `audit_logs` the record of authorised change. Activation writes an audit row in
  the same transaction as the status update, and "who activated this version" is answered there.

Owner: Database Lead + File Processing Lead. Blocking: M4 mapping schema; M7 export; M8 statement
import.

## 2.8 Scanning: how a file becomes available while ADR-008 is open

The tension is real and has to be resolved explicitly rather than discovered in slice 4.

`available_requires_clean_scan` is a database CHECK admitting exactly one value, `clean`. ADR-008 is
open, so no approved scanning policy exists. DOC-CONFLICT-029's holding position is that unknown and
skipped scans fail closed. Read literally and applied everywhere, that means **no file can ever
become `available`**, and M4 delivers an upload path that produces nothing usable — which would make
the milestone's own test list unsatisfiable (`:722` requires a checksum mismatch to *block use*,
which presumes a file that was in use).

The resolution turns on what ADR-008's safe default actually says: "Quarantine or deny **production
use** when scan status cannot satisfy the approved policy." It denies a production claim, not a
development one.

**Decision.** M4 introduces a `ScanPolicy` port with exactly two adapters and no third:

- `NoScannerConfigured` — the production default. It returns a non-`clean` outcome for every file,
  so every upload in a deployment with no scanner lands in `quarantined`. It is not a stub; it is
  the honest answer to "has this been scanned", and the database CHECK turns that answer into a
  refusal without any application code needing to remember.
- `DevelopmentScanBypass` — returns `clean`, and **refuses to construct when `APP_ENV` is
  `production`**, by the same pattern `app/cli/seed_demo.py` already uses. Selecting it is an
  explicit configuration act, it is logged at startup as a security-relevant configuration, and the
  readiness payload reports which adapter is live so an operator cannot be wrong about it by
  accident.

There is deliberately no `skipped_by_approved_policy` adapter: `12_Security_RBAC_Audit.md:1526`
states that a skipped decision "must not be implicit. It must reflect an approved deployment policy
with compensating controls" — and no such policy exists to reflect. Writing that value now would be
the implicitness the sentence forbids. The value is also absent from the M2 CHECK, so the database
would refuse it anyway; slice 4 asserts both facts together so the day ADR-008 lands, the widening
is one migration and one adapter rather than an archaeology exercise.

## 2.9 Purposes, categories, and who may see a file

`05_API_Specification.md:991-997` enumerates seven Phase 1A upload purposes.
`12_Security_RBAC_Audit.md:1476` requires a `category` in the mandatory metadata. `file_objects` has
a `category` column with no value CHECK, and a `visibility_scope` column with no value CHECK — M2
left both open because "no approved catalogue enumerates them, and inventing a set here would decide
questions this slice is not allowed to decide" (`app/db/models/file_object.py:170-173`).

Doc 05's `purpose` and doc 12's `category` are the same field under two names; nothing distinguishes
them in any authority, and treating them as two would create a second uncatalogued dimension. Slice
1 records them as one: the API field is `purpose` because that is the contract's name, the column is
`category` because that is the schema's name, and the mapping is identity.

All seven purposes satisfy `^[a-z][a-z0-9_]{0,39}$`, so the purpose becomes the first path segment
of the storage key. That is why slice 1 whitelists it in application code rather than trusting it:
an unconstrained purpose is a path-injection surface *and* an unbounded key namespace.

`visibility_scope` is where trader access is decided, and M4 fixes exactly two values:
`internal_only` and `trader_visible_after_publication`. Publication is M9. So within M4 the second
value grants nothing — a trader's access to a file is decided solely by ownership of the resource it
is linked to, which for M4 means files the trader uploaded themselves. Slice 5 states that as a
refusal rather than an absence: a `trader_visible_after_publication` file with no publication is
denied to the trader, with a test, so that M9 turns a refusal into an allowance rather than
discovering there was never a check.

---

# 3. Slices

Each slice is one pull request. `### What proves it` is the section the traceability gate parses;
every obligation named there must be discharged by a test in the same pull request, or the pull
request is not the slice.

## Slice 1 — What M4 is allowed to accept, before anything accepts it

### Goal

Fix the three value sets M4 needs and M2 deliberately left open — purpose, visibility scope, and
size/type limits — so that no later slice decides them incidentally while writing a route. Nothing
here has a route; this is the vocabulary every following slice is written against.

### What it changes

- `docs/governance/file_purpose_catalog.yaml` — the seven purposes from
  `05_API_Specification.md:991-997` verbatim, each with: its `visibility_scope`; the MIME types and
  extensions it accepts; a **development-only** maximum size; and a `limits_status` field whose
  value is `blocked_by_POL_006` on every entry. The catalogue is the single place a reviewer reads
  to answer "what can be uploaded", and the POL-006 marker is per-entry rather than a header note so
  that no entry can quietly acquire a production-looking limit.
- `app/files/purposes.py` — loads the catalogue at import and exposes `PURPOSES`,
  `accepts(purpose, mime)`, `size_limit(purpose)`. The catalogue is data; this is the only reader.
- `app/config/settings.py` — `file_upload_limits_are_production_approved: bool = False`, and a
  startup refusal when `APP_ENV=production` and it is still `False`. The limits are development
  values; a deployment that wants to call them production has to say so, and POL-006 is what would
  make that true.
- Governance: DOC-CONFLICT-045, 046 and 047 added to `CONFLICT_REGISTER.md` with the resolutions
  proposed in §2.5–2.7; `permission_catalog.yaml` gains `bank_profile.activate_version` and
  `bank_mapping.activate` as **proposed, unassigned** entries (no `default_roles`), so that the
  identifiers exist to be denied against; `command_catalog.yaml` gains the `file.upload` entry;
  `M0_MANIFEST.json` hashes regenerated.

### What proves it

- `FILE-PURPOSE-001` — every purpose in the catalogue matches the seven in
  `05_API_Specification.md:991-997`, parsed from the document rather than restated. A purpose the
  document does not list, or a listed purpose the catalogue omits, fails. This is the floor derived
  from a gated artifact: the source is the specification, not a number in a test.
- `FILE-PURPOSE-002` — every catalogue purpose satisfies the storage-key category pattern in
  `app/storage/keys.py`, compiled from that module rather than restated. Guard-the-guard: the test
  asserts the pattern it imported actually rejects a known-bad category, so a pattern that had been
  loosened to `.*` could not pass this vacuously.
- `FILE-PURPOSE-003` — `visibility_scope` is one of exactly two values for every purpose, and the
  set is closed: adding a third to the catalogue fails the test.
- `OPS-LIMIT-001` — every catalogue entry carries `limits_status: blocked_by_POL_006`, and the
  application refuses to start with `APP_ENV=production` unless the limits have been explicitly
  approved. A guessed production limit cannot reach production silently.
- `SEC-PURPOSE-001` — a purpose absent from the catalogue is rejected by `accepts()`, and the
  rejection is the default branch rather than an enumerated deny-list.

### Negative controls

Replace the catalogue's parsed source with a hard-coded list of seven strings: `FILE-PURPOSE-001`
must fail. Loosen the key-category pattern to `.*`: `FILE-PURPOSE-002`'s guard must fail. Byte-compare
each file before and after so a sabotage that did not apply reports `NOT APPLIED` rather than a
false "caught".

## Slice 2 — The storage backend gets its first byte

### Goal

`POST /api/v1/files`, end to end, through the machinery M2 built. This is the slice that turns a
health-checked-but-unused storage adapter into a used one.

### What it changes

- `app/files/upload.py` — the command, in **three short transactions and never one long one**, per
  `15_Agent_Implementation_Plan.md:691` ("streaming upload without holding a long database
  transaction"):
  1. **Initiate.** Claim the idempotency key; generate the storage key from the purpose and the
     command's instant; insert `file_objects` as `pending` with `sha256_hash` NULL. Commit.
  2. **Stream.** Outside any transaction, write the request body to the backend through
     `StorageBackend.write`, computing SHA-256 incrementally as the bytes pass and counting them.
     No buffering of the whole file; the size limit is enforced *during* the stream, not after, so
     an oversized upload is abandoned rather than absorbed.
  3. **Finalize.** One short transaction: set `sha256_hash`, `size_bytes`, `mime_type_detected`, and
     the resulting state, with the audit row in the same transaction; complete the idempotency
     record.
- Ordering is row-first, bytes-second on purpose. A crash between 1 and 2 leaves a `pending` row
  with no object — which `stale_pending_uploads` already detects. Bytes-first would leave an orphan
  object, which `storage_objects_without_a_record` also detects, but the pending row is the one that
  carries who was uploading and why, and an orphan blob carries nothing.
- `app/api/v1/files.py` — the route; multipart, `file` + `purpose` + optional `client_filename`.
  Response per `05_API_Specification.md:1000-1012`: `id`, `status`, `original_filename`,
  `mime_type`, `size_bytes`, `sha256`, `processing_job_id`. **No storage field of any kind.**
- `original_filename` is stored sanitised and used for display only. It never reaches a path — the
  key is already generated and does not consult it.
- `app/audit/registry.py` — `file.uploaded`.

### What proves it

- `FILE-UP-001` — a file uploaded through the route exists in storage under a key that contains
  none of: the original filename, its extension, or the client-supplied identifier; and the row's
  `storage_key` matches the generated pattern.
- `FILE-UP-002` — the upload holds no database transaction while bytes are being written. Asserted
  by instrumenting the session: the streaming step runs with no open transaction, and a regression
  that wrapped all three steps in one `with uow:` fails.
- `FILE-UP-003` — retrying with the same `Idempotency-Key` returns the first result and creates
  **one** `file_objects` row and **one** stored object. `15_Agent_Implementation_Plan.md:725`.
- `FILE-UP-004` — two different callers uploading byte-identical content produce two rows with two
  keys and the same `sha256_hash`. Deduplication on content is not idempotency (§2.6).
- `FILE-UP-005` — an upload exceeding the purpose's size limit is refused mid-stream: the response
  is the catalogued error, and the storage backend holds no complete object afterwards.
- `API-FILE-001` — the response body contains no `storage_key`, `storage_bucket` or
  `storage_provider`, checked against the response model's fields rather than against one example
  payload.
- `TRACE-CALLER-001` — `StorageBackend.write` and `generate_storage_key` each have at least one
  caller in `app/` that is not a test and not the health probe. The guard for §1.3's defect, written
  as a rule over the import graph rather than a grep for a name.
- `AUD-FILE-001` — a successful upload writes exactly one `file.uploaded` audit row in the finalize
  transaction, and a failed finalize leaves neither an audit row nor an `available` file.

### Negative controls

Wrap all three steps in one Unit of Work: `FILE-UP-002` must fail. Return the existing row when a
checksum matches: `FILE-UP-004` must fail. Add `storage_key` to the response model: `API-FILE-001`
must fail. Delete the route and keep the command: `TRACE-CALLER-001` must fail.

## Slice 3 — Content inspection, and what happens to a file that fails it

### Goal

`12_Security_RBAC_Audit.md:1497-1510`'s validation list, with the rule that
`08_Bank_File_and_Result_Processing.md:413` states plainly: "File-type acceptance must use content
inspection, not extension alone."

### What it changes

- `app/files/inspection.py` — signature/magic-byte detection producing `mime_type_detected`,
  compared against `mime_type_declared`. The two columns are never reconciled into one; M2's model
  says why at `app/db/models/file_object.py:158-160`: "the comparison is the signal."
- Rejection versus quarantine, decided by which rule failed:
  - **Rejected before any row exists** — purpose not in the catalogue, size over the limit,
    declared MIME not accepted for the purpose. Nothing was stored; nothing needs a record.
  - **Quarantined, with the row and the bytes kept** — declared and detected MIME disagree; the
    detected type is executable or unknown-binary; the content is structurally unreadable as its
    claimed type. A file that lied about what it is, is evidence about the uploader, and deleting it
    destroys that. `12_Security_RBAC_Audit.md:1571` states reconciliation "does not automatically
    delete financial evidence"; the same principle applies at the front door.
- Executable content is refused outright per `12_Security_RBAC_Audit.md:1510` and `08_Bank_File_and_Result_Processing.md:412`, by detected type, not
  by extension.

### What proves it

- `FILE-VAL-001` — a PNG renamed `.pdf` and declared `application/pdf` is quarantined, not accepted,
  and the row records both the declared and the detected type.
- `FILE-VAL-002` — a file whose *content* is an ELF or PE executable is refused even when its
  extension and declared MIME are an accepted image type.
  `15_Agent_Implementation_Plan.md:719` — "malicious or unsupported file is rejected/quarantined".
- `FILE-VAL-003` — a structurally corrupt PDF/XLSX that passes signature detection is quarantined at
  the structural-readability check, not accepted as available evidence.
- `FILE-VAL-004` — a quarantined file keeps its bytes and its row. Nothing in the validation path
  calls a delete.
- `FILE-VAL-005` — validation decides on detected content: a test that changes only the extension
  and only the declared MIME, holding the bytes constant, gets the same outcome both times.
- `SEC-FILEUP-001` — an upload declaring a purpose the actor's permission does not cover is refused
  before a byte is written.

### Negative controls

Make the decision read `original_filename`'s extension: `FILE-VAL-005` must fail. Change quarantine
to delete the object: `FILE-VAL-004` must fail. Accept when declared and detected disagree:
`FILE-VAL-001` must fail.

## Slice 4 — `available` requires a scan, and there is no scanner

### Goal

Implement §2.8's decision. Make the absence of a scanner a visible, configured, fail-closed fact
rather than an unwritten assumption.

### What it changes

- `app/files/scanning.py` — the `ScanPolicy` port and its two adapters, `NoScannerConfigured` and
  `DevelopmentScanBypass`, the second refusing to construct under `APP_ENV=production`.
- `app/core/runtime.py` — selects the adapter from configuration, defaulting to
  `NoScannerConfigured`, and records the choice in the readiness payload so an operator reads which
  one is live instead of assuming.
- Finalize (slice 2, step 3) consults the policy: `clean` → `available`; anything else →
  `quarantined`. The application never writes `available` with a non-clean scan, and the database
  refuses it independently — two layers, deliberately, because the CHECK is what holds when a future
  code path forgets.
- `app/files/states.py` — the seven states from DOC-CONFLICT-036's approved CHECK as the single
  Python source, imported by everything that names a state.

### What proves it

- `FILE-SCAN-001` — with `NoScannerConfigured` live, an otherwise perfect upload lands in
  `quarantined` and never in `available`.
- `FILE-SCAN-002` — `DevelopmentScanBypass` raises at construction when `APP_ENV=production`, and
  the application fails to start rather than starting with scanning silently off.
- `FILE-SCAN-003` — writing `available` with a non-clean `scan_status` is refused **by the
  database**, asserted through a direct SQL insert that bypasses the application entirely. The
  application-layer guard and the constraint are proved separately, because a test that only
  exercises the command cannot tell which of the two is holding.
- `FILE-SCAN-004` — `skipped_by_approved_policy` is not writable: no adapter produces it and the
  CHECK refuses it. Both asserted together, with the reason, so the ADR-008 widening is one place.
- `FILE-LIFE-001` — the Python state tuple equals the database CHECK's value set, read from
  `information_schema` rather than restated. A state added to one and not the other fails.
- `FILE-LIFE-002` — a quarantined file has no transition to `available` anywhere in the command
  layer; §2.4's consequence of `file.quarantine_review` being uncatalogued, asserted rather than
  left as an absence.

### Negative controls

Make `NoScannerConfigured` return `clean`: `FILE-SCAN-001` must fail. Remove the `APP_ENV` guard:
`FILE-SCAN-002` must fail. Add an eighth state to the Python tuple only: `FILE-LIFE-001` must fail.

## Slice 5 — Every download is authorized again, and a category with no owner is denied

### Goal

`12_Security_RBAC_Audit.md:1530-1539`: every download and preview re-evaluates session, permission,
ownership, category, lifecycle state, publication state and restriction. And the DoD's second
claim — that a later module gets authorization by registering, not by writing a branch.

### What it changes

- `app/files/ownership.py` — an ownership-resolver registry keyed on `category`. A resolver answers
  "may this actor reach this file". **A category with no registered resolver denies**, and the
  registry has no default-allow branch. This is the extension point M5–M8 fill: a later module
  registers a resolver for its own category and inherits every guard below it.
  - M4 registers exactly one resolver, for files whose uploader is the requesting trader. It does
    **not** route ownership through `file_links`: M2 scoped that table to non-critical attachments
    and forbade its promotion into a general link primitive
    (`app/db/models/file_object.py:262-268`), and the critical owning resources — payment requests,
    batches, bundles — do not exist until M5–M8 and will carry their own explicit foreign keys.
- `app/api/v1/files.py` — `GET /files/{id}`, `GET /files/{id}/download`, `GET /files/{id}/preview`,
  per `05_API_Specification.md:1018-1046`. Preview is authorized **separately** from download
  (`:1045`), not as a weaker download.
- Response headers on every file body: `Cache-Control: no-store`, `Content-Disposition: attachment`
  with a sanitised filename, `X-Content-Type-Options: nosniff`. `12_Security_RBAC_Audit.md:1555-1558`
  forbids sensitive files in browser or service-worker caches.
- `GET /files/{id}/integrity` per `05_API_Specification.md:1050` — internal only, behind
  `file.read_sensitive_bundle`.

### What proves it

- `SEC-FILEDL-001` — a valid, authenticated actor requesting a file id they do not own gets the same
  response as for an id that does not exist: no distinction in status, body or timing branch.
  `15_Agent_Implementation_Plan.md:720` — "a user cannot download by guessing a file ID".
- `SEC-FILEDL-002` — a trader cannot download or preview a file whose category is an internal bank
  bundle. `15_Agent_Implementation_Plan.md:721`.
- `SEC-FILEDL-003` — a category with **no registered resolver** is denied for every actor including
  a business administrator. The negative control for the registry: this is the test that fails if a
  default-allow branch is ever added.
- `SEC-FILEDL-004` — a `pending` or `quarantined` file is not downloadable even by its owner.
  `12_Security_RBAC_Audit.md:1468` — only `available` files may be used by normal business commands.
- `SEC-FILEDL-005` — a `trader_visible_after_publication` file with no publication is denied to the
  trader. The M9 hook, asserted as a refusal now (§2.9).
- `SEC-FILEDL-006` — revoking the session between two identical download requests changes the second
  to a denial. "Re-evaluates every time" proved by changing the state, not by reading the code.
- `API-FILE-002` — every file-serving response carries `Cache-Control: no-store` and
  `Content-Disposition: attachment`, asserted on all three routes rather than one.
- `API-FILE-003` — `GET /files/{id}` returns metadata and allowed actions and no storage address,
  checked against the response model's fields.
- `SEC-FILEDL-007` — preview authorization is not inherited from download: an actor permitted to
  preview is refused the original when only `file.preview` is held.
- `SEC-FILEDL-008` — signed access expires or is re-authorized correctly.
  `15_Agent_Implementation_Plan.md:726`. **Recorded in `RECORDED_GAPS`, not discharged**: M4 issues
  no signed URLs (§4), so there is no expiry to test. It is stated here rather than omitted because
  the milestone's authority lists it, and an obligation dropped from the plan is invisible while an
  obligation recorded as a gap is read by whoever accepts the milestone. Its authorized half is a
  different obligation and is discharged by `SEC-FILEDL-006`.

### Negative controls

Add a default-allow branch to the registry: `SEC-FILEDL-003` must fail. Return `404` for unknown and
`403` for unowned: `SEC-FILEDL-001` must fail. Drop the state check: `SEC-FILEDL-004` must fail. Let
`file.download` imply `file.preview`: `SEC-FILEDL-007` must fail.

## Slice 6 — Derived files know their source, and preview work is dispatched rather than done

### Goal

`15_Agent_Implementation_Plan.md:697-698`: original/derived relationships and preview job dispatch
through the outbox. Dispatch only — no worker consumes it in M4.

### What it changes

- `app/files/derivation.py` — creating a derived `FileObject` and its `file_derivations` row in one
  transaction, recording `source_file_id`, `derivation_type`, `parameters_hash`, `renderer_version`
  and the derived checksum, per `08_Bank_File_and_Result_Processing.md:431`.
- A derived file that cannot name its source cannot be created: the two rows are written together or
  neither is.
- Preview dispatch: an available file of a previewable purpose emits an outbox event in the finalize
  transaction. No worker in M4 consumes it; `processing_jobs` records the pending work and
  `stuck_processing_jobs` (already written, given a caller in slice 7) is what notices it never ran.
  This is stated as a known incompleteness rather than left to be discovered: the preview endpoint
  returns the catalogued "not yet generated" state, and the frontend renders it (slice 10).

### What proves it

- `FILE-DERIV-001` — a derived file and its derivation row commit in one transaction; a failure
  after the file insert leaves neither.
- `FILE-DERIV-002` — `derivatives_without_a_derivation` finds nothing after a successful derivation
  and finds the orphan after a deliberately partial one. The reconciliation check and the writer
  proved against each other.
- `FILE-DERIV-003` — two renderers agreeing on parameters and differing on `renderer_version`
  produce two derivations, not a conflict. `app/db/models/file_object.py:356-358`.
- `JOB-PREVIEW-001` — finalizing a previewable file enqueues exactly one outbox event in the same
  transaction as the state change, and a rolled-back finalize enqueues none.
- `JOB-PREVIEW-002` — the preview route returns the "processing" state rather than a 500 or an empty
  body when no derivation exists yet.

### Negative controls

Commit the derived file before its derivation row: `FILE-DERIV-001` must fail. Emit the outbox event
outside the transaction: `JOB-PREVIEW-001` must fail.

## Slice 7 — The six reconciliation checks get an operator

### Goal

Give `app/storage/reconciliation.py` the caller it has never had, and make its output something a
person acts on.

### What it changes

- `app/cli/reconcile_storage.py` — runs all six checks, prints findings grouped by kind with counts
  and identifiers, exits non-zero when any finding exists. Read-only: it repairs nothing and deletes
  nothing, per `12_Security_RBAC_Audit.md:1571` — "Reconciliation does not automatically delete
  financial evidence. It creates controlled repair/quarantine work."
- `infra/scripts/` entry so it is runnable against the compose stack, and a line in the operations
  section of the demo script.
- The six checks are enumerated from the module rather than listed in the CLI, so a seventh check
  added later is run without editing the caller.

### What proves it

- `OPS-RECON-001` — the CLI runs all six checks against a database with one seeded instance of each
  defect and reports six findings; the count comes from enumerating the module's checks, not from a
  literal `6`.
- `OPS-RECON-002` — the CLI exits non-zero on any finding and zero on none. An operator's script can
  branch on it.
- `OPS-RECON-003` — the CLI performs no write: asserted by running it against a read-only database
  role and requiring success.
- `TRACE-CALLER-002` — every public function in `app/storage/reconciliation.py` has a caller in
  `app/` that is not a test. The rule from §1.3, applied to the module where the defect was widest.
- `OPS-RECON-004` — a check added to the module and not to any test is reported by the enumeration
  as uncovered, rather than silently skipped. Guard-the-guard.

### Negative controls

Add a seventh check to the module: `OPS-RECON-001` must still run it and `OPS-RECON-004` must report
it. Give the CLI a `--repair` flag that deletes: `OPS-RECON-003` must fail.

## Slice 8 — Bank configuration: structure without content

### Goal

Profiles, versions, mappings and source accounts, created and validated — with ADR-007 enforced as a
refusal rather than as a note.

### What it changes

- `app/commands/bank_configuration.py` — `create_profile`, `create_version`, `create_mapping`,
  `create_source_account`, `deactivate_source_account`. Every one is a catalogued command with its
  permission, `If-Match` where the catalogue requires it, audit in the same transaction.
- `app/api/v1/bank_config.py` — the routes from `05_API_Specification.md:2096-2136`.
- Migration: a value CHECK on `bank_mappings.file_type` admitting exactly the three mapping types,
  per §2.7's resolution, and a value CHECK on `bank_profile_versions.status` and
  `bank_mappings.status` admitting `draft`/`active`/`retired` — the three the status catalogue lists
  as aliases without canonicalising the aggregate. Index names follow DOC-CONFLICT-042's rule.
- `config_hash` computed canonically through `app/core/hashing.parameters_hash`, so the
  `(bank_profile_id, config_hash)` unique actually catches a recreated-identical configuration
  rather than being defeated by key ordering or whitespace.
- **ADR-007 enforcement**: creating a bank profile refuses when `APP_ENV=production`. The fixture
  set lives in `tests/fixtures/bank/` and is explicitly synthetic — no real Iranian bank code, no
  real IBAN, no real transfer limit. A test asserts the fixture bank codes are outside the real
  allocated range and that no migration inserts a bank row.
- Account numbers and IBANs are masked in responses according to permission
  (`05_API_Specification.md:2136`).

### What proves it

- `BANK-CFG-001` — a profile and its first version are created in one transaction with
  `current_version_id` set, and the deferrable composite foreign key is what permits it: a version
  belonging to another profile is refused.
- `BANK-CFG-002` — an operator cannot recreate an identical configuration as a new version; the
  `config_hash` unique refuses it, and the hash is canonical across key reordering and whitespace.
- `BANK-CFG-003` — `bank_mappings.file_type` accepts the three mapping types and refuses `xlsx`.
  §2.7's resolution, enforced at the database so the doc-08 reading fails immediately rather than in
  M7.
- `BANK-CFG-004` — an import mapping and an export mapping coexist at `template_version` 1; a second
  import mapping at the same version is refused. The unique's scope, asserted as behaviour.
- `BANK-FIXTURE-002` — the fixture bank profiles are synthetic: codes outside the real allocated
  range, IBANs failing a real-checksum test, and no migration inserting a bank row.
  `15_Agent_Implementation_Plan.md:686` — "no fake production bank configuration".
- `BANK-ACCT-001` — an account number and IBAN are masked for an actor without the permission to see
  them, and the unmasked value never appears in the response body for that actor.
- `SEC-BANKCFG-001` — every bank-configuration route denies an actor lacking the catalogued
  permission, and denies a trader session outright.
- `AUD-BANKCFG-001` — each creation writes its catalogued `audit_action` in the same transaction as
  the row.
- `OPS-BANKCFG-001` — creating a bank profile refuses under `APP_ENV=production` while ADR-007 is
  open.

### Negative controls

Compute `config_hash` with `json.dumps` unsorted: `BANK-CFG-002` must fail. Drop the `file_type`
CHECK: `BANK-CFG-003` must fail. Put a real bank code in a fixture: `BANK-FIXTURE-002` must fail.

## Slice 9 — A version is resolved by date, and a used version cannot change

### Goal

`15_Agent_Implementation_Plan.md:683` — effective-date/version handling — and
`08_Bank_File_and_Result_Processing.md:342-350`'s activation and immutability rules. This is the
half of the DoD that says "a stable bank configuration version".

### What it changes

- `app/bankconfig/resolution.py` — `resolve_active_version(profile_id, at)`: the single public way
  to read operational bank rules. Returns a version id and its snapshot; there is no function
  returning "the bank's current transfer limit", because a caller holding a limit without the
  version it came from cannot reproduce a decision later.
- Activation: `draft → active`, retiring the previously active version and repointing
  `current_version_id`, in one transaction, under the **new permission identifiers from §2.5** which
  no role holds yet. Retirement likewise. The status update is the only column written, so M2's
  column-level grant is not widened.
- Effective-date semantics settled explicitly: `effective_from` is inclusive, `effective_to`
  exclusive, both UTC per ADR-006, and the business-day interpretation for `cutoff_time` is
  `Asia/Tehran` per the same approved decision. Overlapping active windows for one profile are
  refused.
- Validation before activation, per `08_Bank_File_and_Result_Processing.md:343`: a version activates
  only if its mappings parse the synthetic fixtures from slice 8. An activation that cannot
  demonstrate this is refused.

### What proves it

- `BANK-VER-001` — `resolve_active_version` returns the version whose window contains the instant,
  and two versions with overlapping active windows cannot both exist for one profile.
- `BANK-VER-002` — boundary behaviour is asserted at both edges: an instant equal to
  `effective_from` resolves to that version; an instant equal to `effective_to` does not.
- `BANK-VER-003` — activation is refused for every role, because no role holds
  `bank_profile.activate_version`. §2.5's deliberate state, asserted rather than assumed — and the
  test that must be rewritten, not deleted, when the permission is approved.
- `BANK-VER-004` — a version referenced by a finalized operation cannot be edited: an UPDATE of any
  column other than `status` is refused **by the database grant**, asserted through direct SQL.
- `BANK-VER-005` — activation of a version whose mappings fail to parse the synthetic fixtures is
  refused. `08_Bank_File_and_Result_Processing.md:343`.
- `BANK-VER-006` — activation writes an audit row naming the actor, in the same transaction as the
  status change; "who activated this" is answerable without an `activated_by` column (§2.7).
- `BANK-VER-007` — `app/bankconfig/` exports no function returning an operational value without its
  version id. Asserted over the module's public surface, so a convenience helper added later fails
  the DoD gate rather than quietly defeating it.

### Negative controls

Make `effective_to` inclusive: `BANK-VER-002` must fail. Widen the column grant to permit
`effective_to`: `BANK-VER-004` must fail. Add `get_transfer_limit(profile_id)`: `BANK-VER-007` must
fail.

## Slice 10 — Upload and view it in a browser

### Goal

`21_UI_Design_System_and_Screen_Specification.md:954-980` — `FileUploadPanel` and
`SecureFileViewer` — wired into a real screen. M3's lesson applies directly: routes with no screen is
the same defect as a mechanism with no caller, and M4 has shipped nine slices of backend.

### What it changes

- `packages/ui/src/file-upload-panel.tsx` — staged upload, progress, cancel before finalization,
  allowed type and size guidance read from the API rather than hard-coded, checksum/processing state,
  quarantined state, retry. No storage path anywhere in the component's props or state.
- `packages/ui/src/secure-file-viewer.tsx` — authorized fetch, image and PDF page view, processing
  state, expired-access recovery. Object URLs revoked after use
  (`12_Security_RBAC_Audit.md:1557`); nothing written to `localStorage`, IndexedDB or the
  service-worker cache (`:1555`).
- An admin screen and a trader screen that use both, so each component has a production caller
  before this slice is claimed done.
- `packages/api-client` — the file endpoints, and the new application states from the file lifecycle
  mapped into `STATE_FOR_CODE` so a quarantined upload renders as a stated outcome rather than a
  generic failure.

### What proves it

- `UI-FILE-001` — the upload panel renders the quarantined outcome distinctly from the failed one; a
  user whose file was quarantined is told what happened rather than shown a retry that will do the
  same thing.
- `UI-FILE-002` — cancelling before finalization aborts the request and leaves no available file.
- `UI-FILE-003` — the viewer revokes every object URL it creates; a test that mounts and unmounts
  asserts no leaked URL remains.
- `UI-FILE-004` — neither component writes file content to `localStorage`, IndexedDB or a cache; a
  test stubs all three and asserts they are never called.
- `UI-FILE-005` — allowed types and the size limit are read from the API response, not restated in
  the component. A limit changed on the server changes the guidance without a frontend release.
- `UI-FILE-006` — both components have an importer that is a screen, not a test. The same
  caller rule slices 2 and 7 apply to the backend, applied here to the frontend, which is where it
  was last violated.

### Negative controls

Hard-code the size limit in the component: `UI-FILE-005` must fail. Remove the `revokeObjectURL`
call: `UI-FILE-003` must fail. Delete the screen and keep the component: `UI-FILE-006` must fail.

## Slice 11 — The Definition of Done gate

### Goal

The three mechanical claims from §1.2, as a gate that fails when a later milestone breaks them —
because M4's DoD is a promise made to M5 through M12, and a promise with no gate is a comment.

### What it changes

- `tests/backend/test_m4_definition_of_done.py` — the gate, in the shape of M3's
  router-enumeration gate: it enumerates rather than lists, so it covers code written after it.
- `tests/backend/test_traceability.py` — M4's obligations move out of `PENDING` as their slices land;
  this slice removes the last of them and asserts the dictionary holds no M4 entry.

### What proves it

- `TRACE-DOD-003` — no module outside `app/storage/` and `app/files/` imports the storage backend or
  names `storage_key`, `storage_bucket` or `storage_provider`. The allowlist is asserted to be
  **exactly** the recorded set — `app/core/runtime.py` and `app/observability/health.py` — so it
  cannot grow silently. Guard-the-guard: the test fails if the allowlist is empty, which is how an
  over-broad exclusion would otherwise pass vacuously.
- `TRACE-DOD-004` — no schema in the published `openapi/v1.json` has a property named for a storage
  address. Derived from the generated contract, which the existing OpenAPI contract test already
  gates, so the floor is a rule over an artifact rather than a number.
- `TRACE-DOD-005` — every category reachable through the file routes has a registered ownership
  resolver, enumerated from the purpose catalogue rather than listed. A purpose added without a
  resolver fails here rather than denying silently in production.
- `TRACE-DOD-006` — `app/bankconfig/`'s public surface offers no path to an operational bank value
  that does not carry its version id. §1.2's third claim.
- `TRACE-M4-001` — `PENDING` contains no M4 obligation. The milestone is complete when nothing is
  owed, and the ledger is what says so.

### Negative controls

Import `LocalStorageBackend` into `app/commands/`: `TRACE-DOD-003` must fail. Add `storage_key` to
any response model: `TRACE-DOD-004` must fail. Add a purpose to the catalogue without a resolver:
`TRACE-DOD-005` must fail. Empty the allowlist: `TRACE-DOD-003`'s guard must fail.

---

# 4. What M4 deliberately does not build

Stated so that the absences are reviewable rather than discovered:

- **No retention, deletion or legal-hold API.** ADR-005 is open and its safe default is no automated
  purge; the five catalogued commands are `blocked_by_retention_adr`; `test_no_deletion_machinery.py`
  remains the enforcement. `file_objects.retention_policy_id`, `legal_hold_state`, `archived_at` and
  `physically_deleted_at` stay structure with no writer.
- **No signed URLs.** `05_API_Specification.md:1035` permits streaming *or* a short-lived signed URL,
  and `12_Security_RBAC_Audit.md:1545-1551` sets seven conditions on the second. The local pilot
  adapter cannot sign, ADR-003 has not chosen the production adapter, and issuing a URL that is a
  credential is not something to build against an undecided backend. M4 streams. The eighth M4 test
  — `15_Agent_Implementation_Plan.md:726`, "signed/authorized access expires or is re-authorized
  correctly" — is discharged in its *authorized* half by `SEC-FILEDL-006`; its *signed* half is
  stated as `SEC-FILEDL-008` and recorded in `RECORDED_GAPS`, with ADR-003 named.
- **No quarantine-release path.** §2.4: the command is blocked on a missing API contract, not on a
  decision, and inventing the contract is not M4's to do.
- **No worker consuming preview jobs.** Slice 6 dispatches; consumption is M8's, where the renderer
  and the crop workspace live. `stuck_processing_jobs` is what makes the gap visible meanwhile.
- **No `ManualCropWorkspace`.** `21_UI_Design_System_and_Screen_Specification.md:981-1006` places it
  with `ReceiptSegment`, which is M8, and DOC-CONFLICT-027 blocks the crop reproducibility contract.
- **No object-storage adapter.** The boundary exists; the second implementation waits on ADR-003.

# 5. Landing mechanics

The traceability gate parses every `### What proves it` section in every plan under
`docs/handoff/` and requires each obligation to be cited by a test, recorded in `RECORDED_GAPS`, or
listed in `PENDING` with the slice that owes it. This plan states roughly sixty obligations and its
first pull request contains no tests, so **the plan's own pull request must add every one of them to
`PENDING`**, each annotated with its owning slice, and each slice's pull request removes its own.
That is not bookkeeping around the gate; it is the gate working — an obligation with no owner and no
test is what M3 twice discovered had been carried for two milestones as a name.

Two mechanical constraints on the identifiers, both learned the expensive way in M3:

- Every prefix must already be in `PREFIXES` in `tests/backend/test_traceability.py`. This plan uses
  `FILE`, `BANK`, `SEC`, `API`, `AUD`, `OPS`, `JOB`, `UI` and `TRACE`, all of which are. The
  POL-006 limits obligation is `OPS-LIMIT-001` and **not** `POL-LIMIT-001`, which is worth recording
  because the first draft wrote the latter: `POL` is the namespace of approved policies — `POL-002`,
  `POL-005`, `POL-006` — cited in prose throughout both earlier plans and several tests. Adding it
  to `PREFIXES` to accommodate one obligation would reclassify every one of those citations as an
  obligation id, so the gate would report policy references as uncovered obligations and a test
  merely *mentioning* `POL-005` would count as discharging it. The prefix list is not a formality;
  a namespace shared with something else is the one way to make this gate produce confident nonsense.
- No identifier may collide with one an earlier plan states. `BANK-001` through `BANK-006`,
  `FILE-001`, `FILE-META-001` through `-005` and `FILE-RECON-001` through `-007` are M2's; every
  identifier here is deliberately outside those ranges. `test_no_obligation_id_means_two_different_things`
  is what catches a collision, and in M3 it caught one where an M2 test was discharging an M3
  obligation.
