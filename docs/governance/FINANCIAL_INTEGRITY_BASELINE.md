# Approved Phase 1A Financial Integrity Baseline

Status: APPROVED FOR THE DECISIONS IN THIS FILE
Decision date: 2026-07-20
Approval evidence: workspace owner approval via conversation; legal name/organizational role not supplied

## Scope and precedence

This baseline resolves `DOC-CONFLICT-017` through `DOC-CONFLICT-021`. It is the
implementation authority for these five decisions until the conflicting passages in the
source documents receive their next editorial revision. It does not approve unrelated
statuses, permissions, workflows, production settings, or open ADRs.

## 1. Export job and final artifact are separate records

- A durable export request/job record is created before generation begins. It owns the
  lifecycle (`queued`, `running`, `succeeded`, `failed`), idempotency identity, requester,
  exact batch-version ID/hash, bank-profile/mapping/source-account versions, timestamps,
  error code, and retry lineage.
- A final bank-export artifact record is inserted only after the file exists and its size,
  media type, SHA-256, row count, total, and generation provenance have been verified.
- `file_id`, artifact SHA-256, and `generated_at` are non-null on the final artifact. No
  placeholder file, hash, or timestamp is permitted.
- Creating the immutable artifact, linking it to the completed job, and transitioning the
  job to `succeeded` occur atomically. A failed job has no final artifact.
- Preview output is non-authoritative and cannot be promoted by mutating it into a final
  artifact. Retry is idempotent for the same command or creates explicit retry lineage; it
  never creates two active final artifacts for one logical export command.

Implementation evidence required: migration constraints, transaction tests, failure-before-
file and failure-after-file compensation tests, concurrent generation tests, checksum tests,
and exact download/mark-sent tests.

## 2. Active payment-attempt allocation is database-enforced

- Introduce a dedicated active-allocation relation whose unique/primary key is
  `payment_attempt_id` and whose target is the exact active batch version/item.
- Allocation and batch-item insertion occur in one database transaction. A competing
  allocation for the same attempt must fail at the database boundary; service-layer checks
  alone are insufficient.
- Release is an explicit guarded transition for cancellation, supersession, or another
  approved lifecycle exit. Historical batch items and allocation/release evidence remain
  immutable and queryable.
- Finalization and replacement lock the relevant attempt/allocation rows. A version cannot
  finalize unless each item owns the matching active allocation.
- The constraint applies across all active batch versions, not merely within one version.

Implementation evidence required: unique-constraint tests, two-transaction race tests,
rollback/retry tests, replacement/release tests, and a double-payment negative test.

## 3. Recent-auth uses an explicit bound context

- Persist a dedicated recent-auth context rather than treating `auth_level` and
  `step_up_expires_at` on a session as sufficient proof.
- The context is bound to actor ID, authentication-session ID, action/purpose, resource type,
  resource ID, assurance/factor, issuance time, expiry, and a revocation state. It also has a
  non-replayable identifier or token hash and explicit consumption data where the command is
  single-use.
- Validation requires the same active actor and session, exact action/purpose and resource,
  sufficient assurance, unexpired time, and non-revoked/non-replayed state. Client-supplied
  identity or purpose cannot widen the binding.
- Consumption for a protected financial command is recorded in the command transaction so
  timeout/retry and idempotency behavior cannot reuse assurance for a different effect.
- Session revocation, actor suspension, password/security reset, or explicit security action
  invalidates related contexts.

This persistence decision does not select the strong-auth factor or validity duration;
those values remain governed by open `ADR-009`.

Implementation evidence required: wrong actor/session/action/resource tests, expiry and
revocation tests, replay/concurrent-consumption tests, and timeout-after-commit replay tests.

## 4. Audit evidence has first-class columns plus versioned metadata

Security- and finance-critical audit fields are first-class, typed, and indexed as needed:

- immutable event ID, occurred-at UTC timestamp, action, outcome, and schema version;
- actor type/ID, authentication-session ID, recent-auth-context ID, and assurance level;
- entity type/ID, parent entity type/ID, entity version, and entity/content hash;
- correlation ID, causation ID, request ID, and idempotency key when applicable;
- reason code and reason text/reference when a reason is required;
- source/request context fields approved for retention, with sensitive values minimized.

Extensible details live in a JSON metadata payload only when accompanied by an explicit
`metadata_schema` and `metadata_version`. Metadata cannot substitute for a required
first-class field. Audit rows are append-only and commit in the same transaction as the
business command; database roles and tests prevent update/delete outside governed retention
or legal-hold procedures.

Implementation evidence required: migration/schema tests, required-field tests per command,
transaction rollback tests, immutability tests, query/index tests, metadata-version contract
tests, and sensitive-data redaction tests.

## 5. Separation of duties is mandatory; break-glass is disabled

- For every Phase 1A outgoing batch, the recorded finalizer actor must differ from the
  approver actor for the exact immutable batch version.
- This rule is not configurable off. It is enforced by the command/domain layer and by a
  database-enforceable guard or transactional constraint/trigger whose race behavior is tested.
- Replacement versions require a new exact approval and preserve the same separation rule.
- Break-glass activation, permission grants, endpoints, feature flags, and runtime bypasses
  are disabled for Phase 1A. No exception path may bypass finalizer/approver separation.
- Any future break-glass capability requires a new explicit approval/ADR, threat review,
  narrowly scoped implementation, alerting, expiry, secondary review, and audit evidence.

Implementation evidence required: same-actor denial at service and database boundaries,
concurrent finalization/approval tests, replacement-version tests, absence/denial of
break-glass routes and grants, and UAT evidence.

## Conflict resolutions

| Conflict | Approved resolution | Evidence state |
|---|---|---|
| `DOC-CONFLICT-017` | Separate durable export job from immutable final artifact. | Resolved — Approved |
| `DOC-CONFLICT-018` | Dedicated database-enforced active-attempt allocation. | Resolved — Approved |
| `DOC-CONFLICT-019` | Explicit actor/session/action/resource-bound recent-auth context. | Resolved — Approved |
| `DOC-CONFLICT-020` | Required first-class audit columns plus typed versioned metadata. | Resolved — Approved |
| `DOC-CONFLICT-021` | Mandatory `finalizer != approver`; Phase 1A break-glass disabled. | Resolved — Approved |

## Approval boundary

The approval evidence identifies the approving party only as the workspace owner. No legal
name, employer title, product role, technical role, security role, or other organizational
authority is inferred. Topic-owner review and implementation/test evidence remain required
at the milestone gates even though these architecture/policy choices are approved.
