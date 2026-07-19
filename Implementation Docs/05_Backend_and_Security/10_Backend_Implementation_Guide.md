# 10 — Backend Implementation Guide

## Gold Trade Settlement Platform

**Document ID:** `10_Backend_Implementation_Guide`  
**Version:** `1.1`  
**Status:** Revised authoritative backend implementation baseline  
**Language:** English  
**Primary audience:** Backend engineers, technical leads, DevOps engineers, QA engineers, security reviewers, and coding agents  
**Primary stack:** Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, PostgreSQL, Redis, Celery, private file storage

### Document control

| Field | Value |
|---|---|
| Product phase | Phase 1A manual operational core, with later-phase extension points |
| Architecture | Single-tenant modular monolith |
| Database model | Relational, versioned, auditable, transaction-centered |
| Worker framework | Celery with Redis broker |
| Financial authority | Authorized human commands only |
| Approval authority | Manager approval of one immutable `PaymentBatchVersion` |
| Implementation readiness | Approved as backend coding baseline; production security/hosting ADRs remain |

### Change log

| Version | Summary |
|---|---|
| `1.0` | Initial backend implementation draft. |
| `1.1` | Aligned implementation with documents `00`–`09` v1.1; selected Celery; added request revisions, immutable batch versions, exact-version approval, Unit of Work, mandatory idempotency, optimistic concurrency, transactional outbox, export integrity, Phase 1A manual crop, explicit evidence/publication models, file lifecycle, retention governance, production health contracts, and stronger test/release rules. |

### Related authoritative documents

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

When documents conflict, the domain, schema, API, and workflow specifications above take precedence over examples in this guide. A conflict must be resolved by updating the documentation before merging contradictory code.

---

# 1. Purpose

This guide defines how to implement the backend of the Gold Trade Settlement Platform as a reliable financial-operations system rather than as a digital copy of messages, spreadsheets, or paper forms.

The backend must provide:

1. Trader PWA and internal Admin Web APIs.
2. A complete manual-first Phase 1A workflow.
3. Strong server-side authorization and trader isolation.
4. Payment-request revisions and bank-execution attempts.
5. Immutable batch versions and manager approval of an exact snapshot.
6. Deterministic bank-export generation and integrity verification.
7. Incoming bank-statement imports with immutable import runs.
8. Bank-result bundle review, preview, rotation, and minimal manual crop.
9. Matching candidates separated from confirmed evidence links.
10. Human-controlled payment-result confirmation and publication.
11. Gold-sale, incoming-payment, dispatch, and settlement workflows.
12. Audit, outbox, idempotency, concurrency, and recovery controls.
13. Optional AI/OCR that can be disabled without affecting operations.

The implementation goal is not merely to recreate the current manual tools. It is to preserve valid business outcomes and controls while standardizing and improving process execution.

---

# 2. Fixed Backend Decisions

The following decisions are no longer open implementation choices for Phase 1A.

| Topic | Decision |
|---|---|
| Backend style | Modular monolith |
| Tenant model | Single center / single tenant |
| API framework | FastAPI |
| Validation | Pydantic v2 |
| ORM | SQLAlchemy 2.x |
| Migration tool | Alembic |
| Database | PostgreSQL |
| Worker framework | Celery |
| Broker | Redis |
| Frontends served | Separate Trader PWA and Admin Web App |
| Money storage | Integer IRR only |
| Manager approval | Exact immutable `PaymentBatchVersion` and content hash |
| Manual crop | Required Phase 1A backend capability |
| Auto-segmentation | Phase 2 |
| AI authority | Suggestions only; no financial finality |
| Financial deletion | No generic hard-delete/soft-delete workflow |
| Notification delivery | Transactional outbox; in-app Phase 1A |
| Concurrency | Optimistic version checks plus targeted row locks/constraints |
| Idempotency | Mandatory for critical commands |
| File access | Private, authorized, never raw public paths |

Authentication transport, production storage adapter, hosting topology, retention duration, and recent-auth policy remain controlled ADR decisions. The backend must expose stable requirements without prematurely coupling domain code to one authentication mechanism.

---

# 3. Non-Negotiable Backend Invariants

## 3.1 Human financial authority

A background worker, parser, matching engine, OCR provider, AI provider, or scheduled task must never directly:

- approve a batch version;
- mark an outgoing payment attempt as paid or failed;
- confirm incoming money before dispatch;
- publish a financial result to a trader;
- register gold dispatch or settlement;
- reverse a published paid result;
- shorten retention and delete financial records.

Only named command handlers invoked by an authorized human actor may perform these actions.

## 3.2 Exact-version approval

Manager approval is not attached to a mutable batch container. It is attached to:

```text
PaymentBatchVersion ID
Version number
Ordered item snapshot
Row count
Total amount IRR
Bank Profile Version
Bank Mapping Version
Source Bank Account
Content hash
Manager identity
Approval timestamp
Recent-auth context
```

Any material change requires a replacement version and new approval.

## 3.3 Request intent versus execution

Keep these boundaries explicit:

```text
PaymentRequest
  └── PaymentRequestRevision
        └── PaymentAttempt

PaymentBatch
  └── PaymentBatchVersion
        └── PaymentBatchItem
              └── PaymentAttempt
```

A `PaymentRequest` expresses business intent. A `PaymentAttempt` represents one bank execution row. Never collapse them into one table or one lifecycle.

## 3.4 Evidence versus decision

Keep these boundaries explicit:

```text
FileObject
ReceiptSegment
MatchingCandidate
ConfirmedEvidenceLink
PaymentAttemptResult decision
PaymentResultPublication
```

An uploaded file is not a match. A candidate is not confirmed evidence. Confirmed evidence alone does not automatically mark a payment paid. A paid result is not automatically trader-visible until publication.

## 3.5 History preservation

Financial records must use states such as:

```text
cancelled
voided
superseded
replaced
revoked
archived
```

Do not expose generic delete endpoints for financial aggregates, approvals, exports, evidence links, publications, audit events, or bank imports.

## 3.6 Canonical money handling

- Persist amounts as integer IRR.
- Use Python `int` and PostgreSQL `BIGINT` or `NUMERIC(20,0)` according to the schema.
- Never use binary floating point for money.
- Preserve the original entered value and unit when required by the domain.
- Never infer rial versus toman from the magnitude of a number.
- Treat `paid_sum > request_amount` as reconciliation error, not success.

---

# 4. Runtime and Dependency Strategy

## 4.1 Core runtime

Recommended baseline:

```text
Python 3.12+
FastAPI
Pydantic v2
SQLAlchemy 2.x
Alembic
PostgreSQL 15+
Redis 7+
Celery 5+
ASGI server
Docker
```

All production dependencies must be locked. Container tags must be pinned; `latest` is forbidden.

## 4.2 Synchronous database model

Use synchronous SQLAlchemy sessions for Phase 1A unless an ADR explicitly changes this.

Reasons:

- simpler transaction reasoning;
- fewer mixed async/sync failure modes;
- straightforward `SELECT ... FOR UPDATE` behavior;
- easier integration with Alembic and Celery;
- financial commands are database-bound rather than high-fanout streaming workloads.

FastAPI route functions may be synchronous. Heavy file, export, report, and AI work belongs in Celery tasks.

Do not mix sync and async database engines inside the same bounded context.

## 4.3 Dependency boundaries

Business modules must depend on internal interfaces, not directly on:

- Celery task objects;
- Redis clients;
- storage SDKs;
- provider SDKs;
- SMS vendors;
- AI providers;
- framework request objects.

Adapters implement interfaces at the infrastructure boundary.

---

# 5. Monorepo and Backend Structure

Recommended repository structure:

```text
gold-trade-platform/
  apps/
    trader-pwa/
    admin-web/
  backend/
    app/
      main.py
      api/
        dependencies.py
        middleware.py
        router.py
        v1/
      core/
        config.py
        errors.py
        identifiers.py
        money.py
        normalization.py
        request_context.py
        time.py
        hashing.py
      db/
        base.py
        session.py
        unit_of_work.py
        naming.py
      common/
        commands.py
        queries.py
        idempotency.py
        concurrency.py
        audit.py
        outbox.py
        pagination.py
        files.py
      modules/
        auth/
        users/
        traders/
        beneficiaries/
        gold_sales/
        incoming_payments/
        bank_profiles/
        bank_statements/
        payment_requests/
        payment_attempts/
        payment_batches/
        bank_exports/
        bank_results/
        receipt_segments/
        matching/
        evidence_links/
        publications/
        manual_reviews/
        notifications/
        reports/
        settings/
        retention/
        ai_ocr/
      storage/
        interface.py
        local.py
        s3_compatible.py
      integrations/
        bank_formats/
        ai_providers/
        notification_channels/
      workers/
        celery_app.py
        routing.py
        tasks/
      observability/
        logging.py
        metrics.py
        tracing.py
        health.py
    alembic/
    tests/
      unit/
      integration/
      contract/
      workflow/
      security/
      migration/
      fixtures/
    pyproject.toml
    Dockerfile
  infra/
  docs/
```

## 5.1 Module-local structure

A module may use this layout:

```text
modules/payment_batches/
  api.py
  schemas.py
  models.py
  repository.py
  service.py
  policies.py
  transitions.py
  events.py
  queries.py
  exceptions.py
```

Do not force every small module to have every file. Preserve a consistent dependency direction:

```text
API -> application/service -> policies/domain helpers -> repositories/interfaces
                                                 -> Unit of Work
Infrastructure adapters -> repository/storage/provider interfaces
```

## 5.2 Shared-code limits

`common/` must not become an unbounded dumping ground. Shared code is appropriate only for cross-cutting infrastructure such as:

- command context;
- Unit of Work;
- idempotency;
- concurrency helpers;
- audit/outbox writing;
- pagination;
- normalized error responses.

Domain-specific policy belongs in its module.

---

# 6. Layering and Dependency Rules

## 6.1 API layer

API routers are responsible for:

- HTTP method and path;
- authentication/session dependency;
- permission dependency;
- parsing headers such as `Idempotency-Key`, `If-Match`, and `X-Recent-Auth`;
- request/response DTO validation;
- invoking one query or command service;
- mapping domain errors to the standard API error shape;
- setting `ETag` and correlation headers.

Routers must not:

- change ORM objects directly;
- call `session.commit()`;
- calculate batch totals;
- determine status transitions;
- generate audit logs manually;
- publish Celery tasks before transaction commit;
- expose ORM models.

## 6.2 Application/service layer

A named application service or command handler owns one business use case.

Examples:

```text
SubmitPaymentRequest
CreatePaymentRequestRevision
MarkPaymentRequestEligibleForBatching
CreatePaymentBatch
CreatePaymentBatchVersion
FinalizePaymentBatchVersion
ApprovePaymentBatchVersion
GenerateFinalBankExport
MarkBankExportSent
ConfirmPaymentAttemptPaid
ConfirmPaymentAttemptFailed
CreateReceiptSegmentFromCrop
CreateConfirmedEvidenceLink
ReplaceConfirmedEvidenceLink
PublishPaymentResult
```

A command handler must:

1. verify command context and permission assumptions;
2. open a Unit of Work;
3. resolve idempotency;
4. load and lock/check required aggregates;
5. validate expected version or immutable hash;
6. apply domain policies and transition rules;
7. persist business changes;
8. persist audit and outbox records;
9. persist the idempotency result;
10. commit exactly once through the Unit of Work.

## 6.3 Domain policies

Pure or mostly pure policy classes should implement rules such as:

```text
AmountInputPolicy
PaymentRequestRevisionPolicy
PaymentRequestEligibilityPolicy
PaymentSplittingPolicy
PaymentBatchVersionPolicy
BatchApprovalPolicy
BankExportIntegrityPolicy
PaymentAttemptResultPolicy
EvidenceCardinalityPolicy
PublicationPrivacyPolicy
IncomingPaymentMatchPolicy
GoldDispatchGuardPolicy
RetentionGovernancePolicy
```

Policy functions should receive explicit data and return decisions/errors rather than perform hidden database writes.

## 6.4 Repository layer

Repositories:

- encapsulate SQLAlchemy queries;
- return domain-safe model objects or query DTOs;
- provide explicit lock methods;
- provide queue/query methods;
- never commit or rollback;
- never decide whether a financial transition is allowed;
- never create audit/outbox records implicitly.

Avoid an over-general generic repository that hides important query behavior. Financial queries should have named methods.

Examples:

```text
get_request_with_current_revision()
lock_request_for_command()
find_active_batch_membership()
get_current_batch_version()
lock_attempt_and_parent_request()
list_unresolved_segments()
get_active_primary_evidence_link()
```

## 6.5 ORM models

ORM models define persistence structure and simple invariants only. Do not place multi-aggregate workflows or network calls on ORM models.

Safe model behavior includes:

- normalized property helpers;
- lightweight local validation;
- immutable snapshot properties;
- version field mapping.

Unsafe model behavior includes:

- committing sessions;
- sending notifications;
- invoking providers;
- approving financial commands;
- generating files.

---

# 7. Request, Actor, and Command Context

Every request and worker execution must carry an explicit context.

```python
from dataclasses import dataclass
from uuid import UUID

@dataclass(frozen=True)
class ActorContext:
    actor_type: str
    actor_id: UUID | None
    role_codes: tuple[str, ...]
    permission_codes: frozenset[str]
    trader_id: UUID | None
    session_id: UUID | None
    recent_auth_id: UUID | None
    ip_address: str | None
    user_agent: str | None

@dataclass(frozen=True)
class CommandContext:
    actor: ActorContext
    request_id: str
    idempotency_key: str | None
    expected_record_version: int | None
```

Rules:

- Never derive a trader resource scope from a client-supplied `trader_id` alone.
- System/worker actors must be explicit and cannot inherit human permissions.
- Recent-auth references must be validated server-side and bound to session, actor, action class, and expiry.
- Sensitive values must be masked before entering logs or generic exception metadata.

---

# 8. Unit of Work and Transaction Ownership

## 8.1 Rule

The Unit of Work owns the SQLAlchemy session and the final commit/rollback. Repositories do not commit.

```python
from typing import Protocol

class UnitOfWork(Protocol):
    payment_requests: "PaymentRequestRepository"
    payment_attempts: "PaymentAttemptRepository"
    payment_batches: "PaymentBatchRepository"
    audit_logs: "AuditRepository"
    outbox: "OutboxRepository"
    idempotency: "IdempotencyRepository"

    def __enter__(self) -> "UnitOfWork": ...
    def __exit__(self, exc_type, exc, tb) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
```

A concrete SQLAlchemy Unit of Work may create repositories using one shared session.

## 8.2 One command, one transaction

For normal state-changing commands, one database transaction must include:

```text
Business entity changes
Revision/version/history records
Status changes
Aggregate recalculation
Audit event
Outbox event
Idempotency result
```

Do not commit an entity change and then attempt to add its audit record in a second transaction.

## 8.3 External side effects

Never keep a database transaction open while:

- streaming an upload;
- rendering a PDF page;
- generating a large Excel file;
- calling an AI provider;
- sending a notification;
- uploading a large derived file;
- waiting for another service.

Use staged file records, jobs, and outbox events.

## 8.4 Read-only queries

Read-only query services may use short-lived sessions without a Unit of Work commit. They must still enforce authorization and trader isolation.

## 8.5 Nested transactions

Avoid implicit nested commits. If savepoints are used for row-level import error isolation, they must be explicit and tested. A savepoint must not allow a partially valid financial command to commit when the command contract is atomic.

---

# 9. Critical Command Execution Template

Use a consistent template for critical commands.

```python
class ApprovePaymentBatchVersionHandler:
    def __init__(self, uow_factory, clock, hasher):
        self._uow_factory = uow_factory
        self._clock = clock
        self._hasher = hasher

    def handle(self, command, context: CommandContext):
        require_permission(context.actor, "payment_batch.approve")
        require_recent_auth(context.actor, action="payment_batch.approve")

        request_hash = canonical_request_hash(command)

        with self._uow_factory() as uow:
            idem = uow.idempotency.begin_or_get(
                actor_id=context.actor.actor_id,
                operation="approve_payment_batch_version",
                key=context.idempotency_key,
                request_hash=request_hash,
            )
            if idem.is_completed:
                return idem.response_payload

            batch = uow.payment_batches.lock_batch(command.batch_id)
            version = uow.payment_batches.get_version(command.version_id)

            assert_version_belongs_to_batch(version, batch)
            assert_current_version(batch, version)
            assert_version_ready_for_approval(version)
            assert_hash_equal(version.content_hash, command.expected_content_hash)
            assert_no_existing_decision(version)

            approval = create_batch_approval(
                version=version,
                actor=context.actor,
                approved_at=self._clock.now_utc(),
            )
            uow.payment_batches.add_approval(approval)
            batch.mark_approved(version.id)

            uow.audit_logs.add(build_approval_audit(...))
            uow.outbox.add(build_batch_approved_event(...))

            response = build_approval_response(batch, version, approval)
            uow.idempotency.complete(idem, response)
            uow.commit()
            return response
```

The exact class names may differ, but the transaction semantics must remain.

---

# 10. Idempotency Implementation

## 10.1 Mandatory operations

Require `Idempotency-Key` for:

- payment-request submission;
- structured bulk draft creation, when enabled;
- batch creation;
- batch-version creation and finalization;
- manager approval and rejection;
- final export generation;
- sent-to-bank marking;
- payment-result confirmation;
- evidence-link creation and replacement;
- payment-result publication;
- dispatch/settlement registration;
- critical configuration activation;
- governed retention actions.

## 10.2 Idempotency identity

An idempotency record is scoped by at least:

```text
actor or client identity
operation/route identity
idempotency key
canonical request hash
```

Do not scope only by key globally, because two independent actors may coincidentally use the same UUID.

## 10.3 Canonical request hash

Canonicalization must be deterministic:

- sort JSON object keys;
- normalize UUID and enum representations;
- exclude volatile transport metadata;
- include all fields that alter the logical command;
- use a versioned canonicalization algorithm;
- hash with SHA-256 or stronger supported algorithm.

## 10.4 Required behavior

| Scenario | Behavior |
|---|---|
| New key | Execute command and store logical response. |
| Same key, same hash, completed | Return the original logical result. |
| Same key, different hash | `409 IDEMPOTENCY_KEY_REUSED`. |
| Concurrent same key | One execution wins; others return stored result or safe in-progress conflict. |
| Previous transport timeout after commit | Retry returns original result. |
| Failed validation before business mutation | May persist a safe failure according to operation policy. |

## 10.5 Storage

Use the `idempotency_records` table from the database specification. Store:

- key scope;
- request hash;
- status;
- resource/result reference;
- safe serialized response body and HTTP status where practical;
- expiry/retention metadata;
- created/completed timestamps.

Do not store secrets or full file payloads in idempotency responses.

## 10.6 Worker idempotency

Celery retries are at-least-once. Every task must have a stable logical job ID and verify whether the requested artifact or state already exists before producing side effects.

---

# 11. Optimistic Concurrency and Locking

## 11.1 Mutable aggregate version

Mutable aggregates contain `record_version`.

API responses emit:

```http
ETag: "rv-7"
```

Mutating requests send:

```http
If-Match: "rv-7"
```

Missing precondition returns `428 PRECONDITION_REQUIRED`. A stale version returns `412 VERSION_CONFLICT`.

## 11.2 Update pattern

Use an update or ORM version check equivalent to:

```sql
UPDATE payment_requests
SET status = :new_status,
    record_version = record_version + 1,
    updated_at = :now
WHERE id = :id
  AND record_version = :expected_version;
```

Zero affected rows means stale data or missing record; resolve safely without overwriting.

## 11.3 Immutable snapshots

Immutable entities such as finalized `PaymentBatchVersion` use IDs and content hashes, not mutable `record_version` semantics. Approval handlers verify:

- version belongs to batch;
- version is current;
- version remains ready for approval;
- expected content hash matches;
- no conflicting approval exists.

## 11.4 Targeted row locks

Use `SELECT ... FOR UPDATE` where aggregate-wide atomicity requires it, including:

- assigning requests/attempts to an active batch;
- finalizing a batch version;
- approving a batch version;
- confirming an attempt result and recalculating its parent;
- replacing a primary evidence link;
- creating a publication version;
- governed correction of a published paid result.

Use `FOR UPDATE SKIP LOCKED` for worker/outbox claiming, not for interactive financial decisions.

## 11.5 Database constraints remain mandatory

Application checks do not replace:

- unique active batch membership constraints;
- unique active primary evidence constraints;
- approval uniqueness;
- export/version composite foreign keys;
- idempotency uniqueness;
- non-negative amount checks;
- valid status checks where represented in schema.

---

# 12. Transactional Audit and Outbox

## 12.1 Audit

Financial actions must not succeed without their audit record. The audit record is inserted in the same transaction as the domain change.

Audit metadata should include, when relevant:

```text
actor/session/recent-auth reference
request/correlation ID
entity and version IDs
previous and new state
amount IRR
row count and total
content hash or file checksum
reason
related files/evidence/publication IDs
IP and user-agent metadata
```

Mask sensitive values in generic metadata. Detailed before/after snapshots must follow the security policy.

## 12.2 Outbox

Notification and asynchronous side effects are represented by `outbox_events` inserted in the same transaction.

Examples:

```text
PaymentRequestSubmitted
PaymentRequestCorrectionRequested
PaymentBatchVersionReadyForApproval
PaymentBatchVersionApproved
BankExportSent
PaymentAttemptPaid
PaymentAttemptFailed
EvidenceLinkReplaced
PaymentResultPublicationCreated
TraderResultCorrected
GoldOrderReadyForDispatch
```

## 12.3 Outbox dispatcher

A Celery task or controlled worker:

1. claims pending rows using `FOR UPDATE SKIP LOCKED`;
2. assigns a lease/attempt;
3. invokes an idempotent handler;
4. marks the event delivered;
5. retries transient failures;
6. sends exhausted events to operational review/dead-letter state.

Outbox delivery is at-least-once. Consumers must deduplicate by event ID.

## 12.4 Domain events versus external events

Domain-event names are internal contracts. Do not expose raw internal events directly to external consumers without an adapter and versioned external contract.

---

# 13. Status and Transition Implementation

## 13.1 Explicit commands

Do not implement generic financial status updates.

Forbidden:

```python
request.status = body.status
```

Required:

```text
submit_request(...)
request_correction(...)
mark_eligible_for_batching(...)
finalize_batch_version(...)
approve_batch_version(...)
mark_export_sent(...)
confirm_attempt_paid(...)
replace_evidence_link(...)
publish_payment_result(...)
```

## 13.2 Transition guards

Transition modules must enforce:

- allowed source states;
- required actor permission;
- ownership/isolation;
- expected version/hash;
- required reason;
- open task/conflict checks;
- amount/evidence guards;
- approval and export integrity;
- terminal-state correction rules.

## 13.3 Derived statuses

Derived status calculations must be centralized and deterministic.

For a payment request:

```text
authoritative_paid_sum = sum(
    attempt.amount_irr
    for authoritative non-superseded attempts
    where attempt.status == paid
)
```

Rules:

- equal to request amount → `paid`;
- greater than zero but less than request amount → `partially_paid`;
- greater than request amount → `RECONCILIATION_REQUIRED`;
- all relevant attempts failed and no retry → `failed`;
- retry is planned/required → `retry_required`;
- unresolved sent attempts → `bank_result_pending`.

Do not overwrite explicit dispute, cancellation, closure, or correction states through a blind recalculation.

## 13.4 Status history

Where the database schema provides history or revision tables, create history in the same transaction. Audit logs do not replace domain revision/version records.

---

# 14. Authentication, Sessions, and Authorization

## 14.1 Stable requirements

Until `ADR-001` is approved, backend code must support these stable requirements:

- secure credential verification;
- Argon2id or approved password hash;
- session/revocation records;
- short-lived authentication context;
- logout and server-side revocation;
- login rate limiting and lock protection;
- password/reset lifecycle;
- CSRF protection for cookie-authenticated unsafe methods;
- no long-lived browser token stored in local storage;
- authentication and permission audit events;
- stronger recent authentication for critical actions.

Do not spread JWT-specific code throughout domain modules.

## 14.2 Authorization

Every command and query must enforce permissions server-side. Use permission constants rather than role-name conditionals where possible.

```python
def require_permission(permission: str):
    def dependency(actor = Depends(get_actor_context)):
        if permission not in actor.permission_codes:
            raise ForbiddenError()
        return actor
    return dependency
```

The application service must still validate resource ownership and domain-specific authorization.

## 14.3 Trader isolation

Trader endpoints must derive `trader_id` from the authenticated actor.

Enforce isolation in:

- list queries;
- detail queries;
- file downloads;
- publication downloads;
- notifications;
- generated share output;
- dispute endpoints.

Prefer returning `404 NOT_FOUND` rather than revealing existence of another trader's object.

## 14.4 Technical admin limits

Technical administrators do not receive implicit financial permissions or unrestricted evidence access. Configuration access and operational data access are separate permissions.

## 14.5 Recent authentication

Manager approval and configured sensitive corrections require a recent-auth record validated for:

- current actor;
- current session;
- intended action class;
- creation/expiry time;
- revocation state.

The timeout is a security ADR, not a hard-coded domain constant.

---

# 15. Core Module Implementation Requirements

## 15.1 Traders and users

Implement:

- pending approval, active, suspended, rejected, inactive states;
- approval/suspension/reactivation commands;
- server-side prevention of new financial requests for non-active traders;
- historical access according to policy;
- role and permission management;
- append-only audit for permission changes.

Do not partially implement multi-company tenant switching in Phase 1A.

## 15.2 Beneficiaries

A beneficiary is reusable master data, not a payment amount container.

Implement:

- normalized name and IBAN;
- active/inactive/blocked/superseded states;
- duplicate warnings without automatic destructive merge;
- request/attempt snapshots so later edits do not rewrite history;
- blocked-beneficiary guards and controlled override policy.

## 15.3 Payment requests and revisions

`PaymentRequest` is a stable aggregate. Financial content is captured in immutable `PaymentRequestRevision` rows.

Commands:

```text
create_draft_request
create_request_revision
submit_request
start_accountant_review
request_trader_correction
mark_eligible_for_batching
cancel_request
open_dispute
resolve_dispute
close_request
```

A revision contains:

- beneficiary snapshot;
- destination IBAN snapshot;
- amount IRR;
- original entered value/unit;
- description;
- attachment references;
- revision reason;
- content hash.

Material changes after batch allocation must not mutate historical attempts or versions.

## 15.4 Payment attempts

Attempts:

- reference one exact request revision;
- carry amount and beneficiary snapshots;
- represent original, split, retry, or correction units;
- use `retry_of_attempt_id` when applicable;
- never change submitted bank row data after sent-to-bank;
- connect to batch versions through `PaymentBatchItem`;
- connect to evidence through `ConfirmedEvidenceLink`.

Do not store one mutable `payment_batch_id` or one mutable `receipt_segment_id` as the authoritative relationship.

## 15.5 Payment batches and versions

`PaymentBatch` is a logical container. `PaymentBatchVersion` is an immutable ordered financial snapshot.

Backend responsibilities:

1. preview candidate selection;
2. validate active eligibility;
3. generate/snapshot attempts according to bank rules;
4. create a draft version;
5. validate totals and row content;
6. finalize the version and calculate content hash;
7. create manager approval task;
8. process exact-version approval/rejection;
9. invalidate operational approval when a replacement version becomes current;
10. expose immutable approval view data.

Never edit finalized version items.

## 15.6 Batch approval

Approval commands must verify:

- manager permission;
- recent-auth context;
- exact version and hash;
- version is current;
- no blocking validations;
- no previous conflicting decision;
- configured separation-of-duty rules;
- total and row count consistency.

Approval records are append-only. Rejection creates its own decision record or immutable decision state according to the schema.

## 15.7 Bank profiles, versions, mappings, and accounts

Implement distinct concepts:

```text
BankProfile
BankProfileVersion
BankMapping
BankAccount
```

Bank configuration used by an import, batch version, or export must be snapshotted/version-referenced. Activation of a new version is a critical configuration command with audit, idempotency, and optimistic concurrency.

Do not hard-code a bank name or column position inside domain services. Bank-specific logic belongs in versioned configuration or isolated adapter modules.

## 15.8 Bank statement imports

Use:

```text
BankStatementFile
BankStatementImportRun
BankStatementRow
```

Reprocessing creates a new import run. It does not overwrite previous rows.

Parsing flow:

1. finalize original file as available;
2. create import run and job;
3. parse using exact mapping version;
4. retain raw row representation and normalized fields;
5. record row-level validation errors;
6. show preview;
7. accountant confirms import;
8. confirmed rows become eligible for matching.

Partial import requires explicit policy and user confirmation.

## 15.9 Bank-result bundles

A bundle may contain multiple files, batches, traders, and unknown transactions.

Implement:

- original private files;
- optional relations to multiple batches;
- preview/normalization jobs;
- unresolved-item counts;
- manual review lifecycle;
- close-with-reason support when unresolved items are intentionally left;
- no assumption that one bundle equals one batch.

## 15.10 Receipt segments and manual crop

Minimal manual crop is required in Phase 1A.

The backend must:

- authorize access to the source file/page;
- accept normalized decimal coordinates from zero to one;
- validate page, bounds, dimensions, and rotation;
- create a pending segment/job idempotently;
- render a derived crop;
- store source file, page, source dimensions, rotation, renderer/version, crop parameters, and checksum;
- preserve the original file;
- allow external prepared evidence as fallback.

Auto-segmentation remains a later-phase feature.

## 15.11 Matching candidates

`MatchingCandidate` is non-authoritative.

Candidate generation may use deterministic rules or AI extraction, but must store:

- source segment;
- target attempt;
- score;
- reasons/features;
- warnings;
- scoring/config version;
- creation source;
- superseded/expired state.

Accepting a candidate for confirmation does not mark a payment paid.

## 15.12 Confirmed evidence links

`ConfirmedEvidenceLink` is a separate authoritative relationship.

Default rules:

- one active primary evidence link per attempt;
- one active primary attempt link per transaction segment;
- supplementary evidence may be multiple;
- wrong links are replaced/revoked, never deleted;
- database partial unique constraints enforce cardinality;
- replacement occurs atomically with audit/outbox.

## 15.13 Payment-result confirmation

`ConfirmPaymentAttemptPaid` must verify:

- attempt was sent to bank or is in a specifically allowed correction flow;
- attempt is not cancelled/superseded;
- amount is exact;
- duplicate/tracking/evidence conflicts are resolved;
- expected record version is current;
- idempotency key is valid;
- paid aggregate will not exceed request amount;
- actor has permission;
- exception/text-only policy is satisfied.

Confirmation writes result/history, recalculates parent aggregates, creates audit/outbox, and commits atomically.

A direct `paid -> failed` status edit is forbidden. Use a governed correction command and preserve previous decisions.

## 15.14 Payment-result publications

Trader visibility is controlled through immutable `PaymentResultPublication` versions.

Publication creation must:

- load authoritative current request/attempt result data;
- select only safe evidence;
- apply IBAN masking policy;
- verify ownership/privacy;
- build a deterministic snapshot and content hash;
- create generated share file through a job when needed;
- create outbox notification;
- never expose a full mixed bundle.

Correction creates publication `N+1` and supersedes/revokes the previous version. Do not edit an active publication in place.

## 15.15 Gold sales, incoming payments, and dispatch

Keep incoming money separate from outgoing results.

Implement:

- order pricing/version data;
- multiple incoming receipts/payments;
- manual statement-row matching;
- partial/overpayment review;
- dispatch/settlement guard;
- physical dispatch and non-physical settlement types;
- delivery confirmation and dispute/closure history.

Gold dispatch must not occur before the required incoming-payment confirmation unless an authorized override workflow exists.

## 15.16 Manual-review tasks

Tasks represent actionable operational work, not financial truth.

Resolving a task must invoke the relevant domain command; changing task status alone must not mutate a payment result.

Use task types and priorities from the workflow/API documents. Tasks related to cancelled/superseded records should be cancelled or redirected automatically through outbox handlers.

## 15.17 Notifications

Phase 1A uses in-app notifications. Notification creation occurs from outbox handlers, not directly from controllers.

Notification failure must not roll back a committed financial command. Delivery retries and operational visibility are mandatory.

## 15.18 Settings and retention

Separate:

- deployment/secret configuration;
- versioned bank business configuration;
- feature flags;
- governed retention policies;
- technical operational settings.

A technical admin cannot simply lower `retention_years` and trigger immediate deletion. Retention changes require proposal, approval, legal-hold checks, dry run, and separately audited execution.

## 15.19 AI/OCR

AI/OCR remains optional and isolated.

Backend integration uses:

- immutable AI runs;
- job attempts;
- provider adapters;
- versioned prompts/schemas/configuration;
- privacy policy checks;
- evaluation/release gates;
- matching candidates only.

AI workers cannot invoke financial command handlers with human authority.

---

# 16. File Storage and Lifecycle

## 16.1 Storage abstraction

Use an interface such as:

```python
class FileStorage:
    def put_stream(self, *, key: str, stream, content_type: str) -> "StoredObject": ...
    def open_stream(self, *, key: str): ...
    def stat(self, *, key: str) -> "ObjectMetadata": ...
    def delete(self, *, key: str) -> None: ...
    def create_download_reference(self, *, key: str, ttl_seconds: int): ...
```

Local bind-mounted storage is acceptable for a pilot only when backup paths are explicit. Production object storage is selected by ADR.

## 16.2 File lifecycle

Canonical storage states:

```text
pending
quarantined
available
processing_failed
archived
retention_pending
deleted
```

A file is not usable for financial operations until `available`.

## 16.3 Two-phase upload/finalization

Recommended flow:

1. authenticate and authorize upload purpose;
2. stream to a private temporary/pending key while calculating checksum and size;
3. validate MIME signature, extension, size, and purpose;
4. run malware/quarantine policy as configured;
5. create/finalize file metadata in a short transaction;
6. create outbox/preview job;
7. transition to `available` only after required validation;
8. run orphan reconciliation for storage/database mismatches.

Do not hold a database transaction open during upload streaming.

## 16.4 Derivatives

Preview, normalized page, crop, thumbnail, and share-card files are derivatives. Store derivation relationships and renderer/version metadata. Never overwrite the original.

## 16.5 Download authorization

The file API resolves permission from the owning domain resource and actor. A generic `visibility` flag is insufficient by itself.

Authorization checks include:

- actor role/permission;
- trader ownership;
- file purpose;
- publication state;
- evidence privacy;
- legal/retention state.

Never expose raw storage keys or permanent public URLs.

## 16.6 Reconciliation jobs

Scheduled maintenance must detect:

- storage objects without DB records;
- DB records with missing objects;
- pending uploads past timeout;
- derivatives whose source is missing;
- checksum mismatches;
- files stuck in processing states.

Reconciliation creates operational tasks/alerts and does not silently delete financial evidence.

---

# 17. Deterministic Bank Export Generation

## 17.1 Preview and final modes

Provide separate generation paths:

```text
preview export: non-sendable, may exist before approval
final export: generated only for an approved exact version
```

Preview artifacts must be visibly marked and cannot be marked sent.

## 17.2 Input contract

Final generation receives:

- immutable batch version ID;
- batch approval ID;
- bank profile version ID;
- bank mapping version ID;
- source bank account ID;
- approved content hash;
- ordered immutable batch items.

It must not re-query mutable beneficiary master data to build historical rows.

## 17.3 Determinism

Given the same approved snapshot and generator version, row values must be reproducible. Store:

- generator version;
- template/mapping version;
- input snapshot hash;
- row count;
- total amount;
- generated file checksum;
- generation timestamp and actor/job.

Time-dependent metadata must not alter row-content integrity unless included explicitly in the approved/export contract.

## 17.4 Integrity checks

Before download and before marking sent, verify:

```text
Export version == approved version
Export content hash == batch version hash
Approval content hash == batch version hash
Export total == version total
Export row count == version row count
Mapping version == approved mapping version
Source account == approved source account
Actual file checksum == stored file checksum
```

On mismatch:

- set export `quarantined`;
- block download/sent command;
- create high-priority operational task;
- log audit/system event;
- require regeneration or correction workflow.

## 17.5 Excel adapter

Use an isolated bank-export adapter. An `.xlsx` implementation may use `openpyxl`, but domain code must not depend on workbook APIs.

```python
class BankExportRenderer(Protocol):
    def render(self, snapshot: "ApprovedBatchExportSnapshot") -> "RenderedExport": ...
```

Test with sanitized fixtures derived from actual bank templates. Never commit real customer data.

## 17.6 Mark sent

Mark sent against the exact `BankExcelExport`, not an ambiguous batch flag.

The command records:

- export ID;
- sent timestamp;
- submission channel;
- actor;
- note/reference;
- current integrity verification result.

It atomically updates export, batch, attempt, and request operational states and writes audit/outbox/idempotency records.

---

# 18. Celery and Background Jobs

## 18.1 Queue layout

Configure logical queues from the architecture document:

```text
files
exports
notifications
reports
maintenance
ai
```

One worker process may consume multiple Phase 1A queues, but routing names must exist so workloads can be isolated later.

## 18.2 Authoritative job record

Celery result backend data is not the authoritative operational record. Store job state in PostgreSQL for important jobs.

A job record includes:

- logical job ID;
- job type;
- target entity;
- input manifest/hash;
- status;
- attempt count;
- lease/heartbeat;
- output artifact references;
- safe error code/message;
- timing;
- queue/provider/version metadata.

## 18.3 Task rules

Every task must:

- be idempotent;
- accept stable IDs, not ORM objects;
- open its own session/Unit of Work;
- verify current target state;
- avoid granting itself human authority;
- record attempts/errors;
- update heartbeat for long jobs;
- use bounded retries;
- distinguish transient from permanent failures;
- create manual fallback tasks where required.

## 18.4 Example task pattern

```python
@celery_app.task(bind=True, autoretry_for=(), acks_late=True)
def render_receipt_crop(self, job_id: str) -> None:
    with uow_factory() as uow:
        job = uow.jobs.claim(job_id, worker_id=self.request.id)
        if job.is_terminal:
            return
        manifest = uow.receipt_segments.get_crop_manifest(job.target_id)
        uow.commit()

    try:
        rendered = crop_renderer.render(manifest)
        stored = storage.put_stream(...)
    except TransientStorageError as exc:
        record_retry_and_raise(job_id, exc)
        raise self.retry(exc=exc, countdown=retry_delay(self.request.retries))
    except PermanentRenderError as exc:
        mark_job_failed_and_create_review(job_id, exc)
        return

    with uow_factory() as uow:
        finalize_crop_artifact(uow, job_id, stored)
        uow.commit()
```

Ensure orphan cleanup when storage succeeds but final DB transaction fails.

## 18.5 Retry policy

Retry only transient failures. Do not blindly retry:

- invalid source coordinates;
- unsupported file types;
- failed domain guards;
- stale approval;
- conflicting financial state;
- invalid provider schema beyond a bounded policy.

Use exponential backoff with jitter and maximum attempts.

## 18.6 Scheduler

Celery Beat or a controlled scheduler may trigger:

- outbox dispatch;
- stale job recovery;
- file reconciliation;
- backup verification hooks;
- operational summaries;
- approved retention dry runs;
- expired session/idempotency maintenance.

Retention deletion execution must not be enabled merely because a schedule exists.

---

# 19. Error Handling and API Mapping

## 19.1 Domain errors

Define typed errors such as:

```text
UnauthenticatedError
ForbiddenError
NotFoundError
ValidationError
InvalidStateTransitionError
BusinessRuleViolationError
VersionConflictError
IdempotencyConflictError
ActiveBatchMembershipError
ActivePrimaryEvidenceError
ApprovalInvalidatedError
ExportIntegrityMismatchError
ReconciliationRequiredError
DependencyUnavailableError
```

## 19.2 Standard response

Use the API specification's error shape:

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
    "request_id": "..."
  }
}
```

## 19.3 HTTP mapping

Follow the API specification exactly, including:

- `409` for idempotency reuse and domain conflicts;
- `412` for stale `If-Match`;
- `428` for missing required precondition/idempotency key;
- `503` for required background/dependency unavailability.

Do not expose database constraint names, stack traces, storage paths, provider payloads, or secrets.

## 19.4 Transaction rollback

Unhandled errors roll back the Unit of Work. Convert expected domain errors after rollback. Unexpected errors are logged with correlation ID and a safe response.

---

# 20. Configuration and Secrets

## 20.1 Typed configuration

Use Pydantic settings or an equivalent typed configuration layer.

Separate configuration by service. Do not give frontend or worker processes secrets they do not require.

Backend examples:

```text
APP_ENV
DATABASE_URL
REDIS_BROKER_URL
SESSION_SIGNING_SECRET / AUTH configuration per ADR
CSRF_SECRET if required
STORAGE_BACKEND
LOCAL_STORAGE_PATH or object-storage configuration
MAX_UPLOAD_* limits
LOG_LEVEL
OUTBOX_POLL_INTERVAL
```

Worker-only examples:

```text
CELERY_QUEUES
WORKER_CONCURRENCY
AI_PROVIDER_SECRETS when enabled
RENDERER_LIMITS
```

## 20.2 Business configuration

Runtime business configuration belongs in versioned database entities when it changes interpretation of financial work:

- bank profile versions;
- bank mappings/templates;
- transfer/split rules;
- source bank accounts;
- evidence requirement policy;
- approval/separation-of-duty policy;
- feature flags.

## 20.3 Retention configuration

Retention is governed data, not an ordinary key-value setting. Use retention-policy and legal-hold workflows.

## 20.4 Secret handling

- no secrets in source control;
- no secrets in frontend environment output;
- no secret values in logs or audit metadata;
- rotate secrets through an operational runbook;
- service-specific least privilege;
- production secret source selected by deployment ADR.

---

# 21. Database and Alembic Migrations

## 21.1 Migration rules

- Every schema change uses Alembic.
- Generated migrations require manual review.
- Migration order must be deterministic.
- Constraint and index names follow the schema naming convention.
- No manual production DDL outside the approved incident process.
- Destructive changes require backup, compatibility plan, and approval.
- Data migrations are separate, resumable where needed, and auditable.

## 21.2 Expand/contract strategy

For zero/low-downtime changes where required:

1. add compatible column/table/index;
2. deploy code that supports old and new shape;
3. backfill in bounded jobs;
4. validate data;
5. switch reads/writes;
6. remove old shape in a later release.

Do not combine a large blocking backfill with a schema lock in one migration.

## 21.3 Financial constraints

Migration tests must validate key constraints from document `04`, including:

- unique request revision numbering;
- immutable/current batch-version relations;
- one approval decision per version as specified;
- active batch membership uniqueness;
- primary evidence partial unique indexes;
- export-to-version/approval integrity foreign keys;
- idempotency uniqueness;
- outbox claim indexes;
- non-negative/canonical money constraints.

## 21.4 Migration CI

CI must test:

- upgrade from an empty database;
- upgrade from the previous released schema;
- downgrade where supported;
- schema drift detection;
- required extension availability;
- representative data migration cases.

---

# 22. Observability and Health

## 22.1 Structured logs

Use structured JSON logs with:

```text
timestamp
level
service/environment/version
request_id / correlation_id
actor_type and masked actor reference
module/action
entity type/reference when safe
job/event IDs
safe error code
latency
```

Never log full IBANs, receipts, financial notes, provider payloads, session tokens, or secrets in standard logs.

## 22.2 Metrics

Track at minimum:

- API latency/error rate by route class;
- authentication failures/rate limits;
- critical command success/conflict counts;
- idempotency replay/conflict counts;
- outbox backlog and oldest-event age;
- worker queue depth and job age;
- file upload/validation/failure counts;
- export generation and integrity failures;
- unresolved bank bundles/segments;
- payment request and attempt status counts;
- manual review backlog;
- publication corrections;
- AI cost/latency only when enabled.

Do not place trader names, IBANs, or transaction identifiers in high-cardinality metric labels.

## 22.3 Health endpoints

Implement the canonical contract:

```http
GET /api/v1/health/live
GET /api/v1/health/ready
GET /api/v1/health/dependencies
GET /api/v1/health/workers
```

Rules:

- `live`: process loop is alive; no expensive dependency checks.
- `ready`: service can accept normal traffic; checks required dependencies with strict timeouts.
- `dependencies`: authorized operational detail only.
- `workers`: authorized queue/heartbeat summary.

Do not expose secrets, internal URLs, credentials, or full exception traces.

## 22.4 Tracing

Correlation must flow through:

- inbound API request;
- Unit of Work/audit metadata;
- outbox event;
- Celery task headers/job record;
- notification/report/file jobs.

---

# 23. Testing Strategy

## 23.1 Unit tests

Test pure policies and helpers:

- amount and unit validation;
- canonical hashing;
- IBAN/name/digit normalization;
- request revision rules;
- status transition guards;
- split calculations;
- batch-version content hashing;
- approval policy;
- export row mapping;
- paid aggregate/reconciliation logic;
- evidence cardinality rules;
- publication privacy/masking;
- matching scoring;
- retention policy guards.

## 23.2 Repository tests

Use PostgreSQL, not SQLite, for repository/constraint tests. Test:

- partial unique indexes;
- row locks;
- `SKIP LOCKED` claiming;
- optimistic version updates;
- composite foreign keys;
- queue filters and pagination;
- trader isolation queries.

## 23.3 Integration tests

Test command handlers with real database transactions and fake adapters:

- command + audit + outbox atomicity;
- idempotency replay;
- same key/different payload conflict;
- stale `If-Match`;
- concurrent batch inclusion;
- concurrent manager approval;
- concurrent evidence-link creation;
- timeout/retry behavior;
- storage/database reconciliation;
- worker retry and job recovery.

## 23.4 API contract tests

Validate OpenAPI and response contracts for:

- headers;
- status codes;
- error codes;
- pagination;
- admin versus trader response filtering;
- ETag behavior;
- idempotency requirements;
- file download authorization;
- health endpoints.

## 23.5 Workflow tests

Required workflows include:

1. trader creates request and submits a revision;
2. accountant requests correction and trader creates a new revision;
3. accountant marks request eligible for batching;
4. accountant creates/finalizes batch version;
5. manager approves exact version/hash;
6. final export is generated and verified;
7. exact export is marked sent;
8. bank result bundle is uploaded;
9. accountant creates manual crop/segment;
10. evidence is linked and attempt is confirmed paid/failed;
11. parent request recalculates correctly;
12. publication is created for the correct trader;
13. trader acknowledges or disputes;
14. correction creates replacement evidence/publication without deleting history.

Also test:

- split payment with retry;
- overpayment block;
- mixed bundle across multiple batches;
- unknown segment;
- text-only confirmation policy disabled/enabled;
- published paid-result correction with required control;
- AI disabled/unavailable;
- gold incoming-payment and dispatch guard.

## 23.6 Security tests

Test:

- trader horizontal access attempts;
- file/publication ownership bypass;
- CSRF when cookie transport is selected;
- session revocation;
- recent-auth expiry/reuse;
- permission escalation attempts;
- technical-admin financial restrictions;
- upload content-type spoofing;
- path traversal/storage-key exposure;
- sensitive log masking;
- rate limiting and account lock behavior.

## 23.7 Export fixture tests

Use anonymized fixtures modeled on actual bank templates. Validate:

- exact column order and sheet behavior;
- Persian text handling;
- large integer preservation;
- row count/total;
- optional deposit identifiers;
- deterministic rendering where required;
- file checksum and integrity metadata;
- preview versus final distinction.

Do not commit raw production spreadsheets or bank-result documents.

## 23.8 Property and fuzz tests

Useful targets:

- split amounts always sum exactly to request amount;
- normalized crop coordinates remain within bounds;
- money parser never creates floats;
- arbitrary Unicode/RTL input does not break normalization;
- canonical request hashing is stable;
- invalid status transitions never succeed.

---

# 24. CI Quality Gates

The backend pipeline must run:

```text
format/lint
static type checking
unit tests
PostgreSQL integration tests
workflow tests
security-focused tests
migration upgrade tests
OpenAPI generation/compatibility check
container build
secret scan
dependency scan
container image scan
```

Release artifacts must be immutable. The same image digest tested in staging is promoted to production.

A merge is blocked when:

- schema and migration disagree;
- API status/error contract changes without docs/tests;
- financial command lacks audit/outbox/idempotency where required;
- a new endpoint bypasses authorization;
- export integrity tests fail;
- sensitive fixtures are detected.

---

# 25. Implementation Order

## 25.1 Foundation

1. Monorepo/backend skeleton.
2. Typed configuration and service-specific secrets.
3. PostgreSQL session and Unit of Work.
4. Alembic and naming conventions.
5. Standard errors and request context.
6. Structured logging and health endpoints.
7. Audit, outbox, idempotency infrastructure.
8. Celery/Redis worker and job records.
9. Storage abstraction and pending-file lifecycle.
10. Authentication/session baseline and RBAC.

Audit/outbox/idempotency must not be postponed until after financial workflows are built.

## 25.2 Core identity and configuration

1. Admin users, roles, permissions.
2. Traders and approval lifecycle.
3. Beneficiaries and snapshots.
4. Bank profiles, profile versions, mappings, and accounts.
5. Feature flags with controlled permissions.

## 25.3 Outgoing payment core

1. Payment requests and revisions.
2. Accountant review and eligibility.
3. Payment attempts and split policy.
4. Batch containers and draft versions.
5. Finalization/content hashing.
6. Manager exact-version approval.
7. Preview/final export renderer and integrity.
8. Exact-export sent command.

## 25.4 Result processing

1. Bank-result bundle upload.
2. Image/PDF preview jobs.
3. Minimal manual crop and external evidence fallback.
4. Matching candidate structures.
5. Confirmed evidence links.
6. Payment-result confirmation and aggregate recalculation.
7. Immutable trader publications and share output.
8. Correction/replacement workflows.

## 25.5 Gold sale and incoming payment

1. Gold-sale orders/pricing.
2. Incoming receipt/file upload.
3. Bank statement file/import runs.
4. Manual statement matching.
5. Incoming-payment confirmation.
6. Dispatch/settlement guard and records.

## 25.6 Operational completion

1. Work queues/tasks.
2. Notifications/outbox consumers.
3. Reports/dashboard queries.
4. Retention/legal-hold workflow.
5. Reconciliation and maintenance jobs.
6. Runbook hooks and production monitoring.

## 25.7 Later AI assistance

After manual Phase 1A is stable:

1. AI run/job-attempt infrastructure.
2. Mock provider and schema validation.
3. privacy policy gate;
4. shadow-mode OCR on manually selected inputs;
5. deterministic candidate scoring;
6. evaluation/cost/reliability dashboards;
7. auto-segmentation only in Phase 2 after approval.

---

# 26. Phase 1A Backend Acceptance Criteria

The backend is acceptable only when all conditions below are demonstrated in tests and staging.

## 26.1 Security and access

- Admin and trader authentication works under the approved ADR.
- Sessions can be revoked.
- Login protections are active.
- Backend permissions are enforced for every route.
- Traders cannot access another trader's records, files, publications, or notifications.
- Technical admin does not implicitly have financial decision permissions.
- Manager approval requires configured recent authentication.

## 26.2 Financial integrity

- Payment-request financial changes create immutable revisions.
- Amounts are integer IRR and original input provenance is retained.
- Eligible requests can be batched without duplicate active membership.
- Finalized batch versions are immutable.
- Manager approves one exact version/hash.
- Changes create replacement versions and require reapproval.
- Final export can be generated only from the approved snapshot.
- Preview files cannot be marked sent.
- Integrity mismatch quarantines the final export.
- Sent-to-bank marking references the exact export.

## 26.3 Results and evidence

- Mixed/multi-file bank-result bundles are supported.
- Accountant can preview images/PDFs and make a minimal manual crop.
- Original files and crop provenance are retained.
- Candidate matches do not finalize payments.
- Confirmed primary evidence cardinality is enforced.
- Paid/failed confirmation is idempotent, version-safe, and audited.
- Overpayment is blocked for reconciliation.
- Wrong evidence/result can be corrected without deleting history.
- Trader publication is immutable and privacy-safe.
- Full mixed bank bundles are never exposed to traders.

## 26.4 Reliability

- Audit and outbox are atomic with financial commands.
- Notification failure does not undo a committed payment decision.
- Worker retries are idempotent.
- Timeout after commit can be safely retried with the same idempotency key.
- File/storage orphan reconciliation exists.
- Backup/restore requirements can preserve database-file consistency.
- Canonical health endpoints work.
- AI/OCR can be completely disabled.

## 26.5 Gold and incoming payment

- Gold-sale order and pricing workflow works manually.
- Incoming payment evidence and statement import/matching work.
- Partial/overpayment enters review.
- Dispatch/settlement guard prevents unauthorized release.
- Closure/correction history is preserved.

---

# 27. Coding-Agent Rules

A coding agent implementing the backend must follow these rules:

1. Do not treat legacy spreadsheets or messages as the target architecture.
2. Do not implement AI/OCR as a Phase 1A dependency.
3. Do not allow AI or workers to finalize money or gold movement.
4. Do not merge Payment Request, Revision, Attempt, Batch, Version, Export, Evidence, or Publication concepts.
5. Do not approve a mutable batch container.
6. Do not generate a sendable export without exact-version approval.
7. Do not mark a batch sent without identifying the exact export file.
8. Do not store money as float or infer rial/toman.
9. Do not update financial status through generic PATCH/CRUD logic.
10. Do not commit inside repositories.
11. Do not perform external calls inside a financial database transaction.
12. Do not publish Celery tasks before commit; use outbox.
13. Do not omit idempotency on critical commands.
14. Do not ignore stale `If-Match` or content-hash checks.
15. Do not rely on application checks without database constraints.
16. Do not expose ORM models directly.
17. Do not expose storage paths or full mixed bank documents.
18. Do not hard-delete or generically soft-delete financial history.
19. Do not let technical settings bypass retention governance.
20. Do not include real banking/customer data in source control or test fixtures.
21. Do not log raw sensitive payloads.
22. Do not silently discard invalid/imported/unmatched rows or segments.
23. Do not duplicate derived-status logic across endpoints.
24. Do not automatically retry non-idempotent business commands.
25. Keep documentation, migrations, API contracts, and tests synchronized.

---

# 28. Recommended Interfaces

These examples are illustrative and must be aligned with the final codebase naming.

## 28.1 Payment request service

```python
class PaymentRequestService:
    def create_draft(self, command, context): ...
    def create_revision(self, command, context): ...
    def submit(self, command, context): ...
    def request_correction(self, command, context): ...
    def mark_eligible_for_batching(self, command, context): ...
    def cancel(self, command, context): ...
    def recalculate_from_attempts(self, request_id, uow): ...
```

## 28.2 Payment batch service

```python
class PaymentBatchService:
    def preview_selection(self, query, actor): ...
    def create_batch(self, command, context): ...
    def create_version(self, command, context): ...
    def finalize_version(self, command, context): ...
    def approve_version(self, command, context): ...
    def reject_version(self, command, context): ...
    def create_replacement_version(self, command, context): ...
```

## 28.3 Bank export service

```python
class BankExportService:
    def generate_preview(self, command, context): ...
    def request_final_generation(self, command, context): ...
    def verify_integrity(self, export_id, uow): ...
    def mark_sent(self, command, context): ...
    def quarantine(self, export_id, reason, uow): ...
```

## 28.4 Evidence service

```python
class EvidenceService:
    def create_manual_crop(self, command, context): ...
    def create_external_segment(self, command, context): ...
    def create_candidate(self, command, context): ...
    def create_confirmed_link(self, command, context): ...
    def replace_confirmed_link(self, command, context): ...
```

## 28.5 Payment result service

```python
class PaymentAttemptResultService:
    def confirm_paid(self, command, context): ...
    def confirm_failed(self, command, context): ...
    def create_retry(self, command, context): ...
    def request_sensitive_correction(self, command, context): ...
    def apply_approved_correction(self, command, context): ...
```

## 28.6 Publication service

```python
class PaymentResultPublicationService:
    def preview(self, query, actor): ...
    def publish(self, command, context): ...
    def supersede_and_publish_replacement(self, command, context): ...
    def revoke(self, command, context): ...
```

## 28.7 File service

```python
class FileService:
    def begin_upload(self, command, context): ...
    def finalize_upload(self, command, context): ...
    def authorize_download(self, file_id, actor): ...
    def schedule_preview(self, file_id, uow): ...
    def reconcile_storage(self, job_context): ...
```

---

# 29. Remaining ADRs and Production Decisions

The backend coding baseline is stable, but the following decisions must be approved before their production milestone:

| ADR/Decision | Required before |
|---|---|
| Authentication/session transport | Auth implementation completion |
| Recent-auth method and timeout | Manager approval production release |
| Separation-of-duty policy | Financial UAT |
| Production hosting topology | Deployment build |
| Production storage adapter/residency | Real file migration/use |
| Malware scanning policy | Production uploads |
| Exact upload size/volume limits | Load testing |
| Initial bank profiles/mappings/accounts | Bank export UAT |
| Text-only result confirmation policy | Result confirmation UAT |
| Evidence requirement for publication | Trader result UAT |
| IBAN masking policy | Publication UAT |
| Paid-result correction dual control | Financial UAT |
| Retention/legal hold authority and periods | Production data acceptance |
| RPO/RTO and restore owner | Production launch |
| AI provider/privacy/evaluation ADRs | Enabling any external AI |

Code must fail safely or keep the feature disabled until its required decision is approved.

---

# 30. Final Backend Position

The backend must be a transactionally consistent modular monolith with explicit command boundaries, immutable financial snapshots, server-side authorization, exact-version manager approval, deterministic bank exports, private evidence handling, manual Phase 1A crop/review, and recoverable asynchronous processing.

The first successful milestone is:

> The center can complete outgoing payments, bank-result review, trader publication, incoming-payment verification, and gold dispatch inside the platform with full auditability, while AI/OCR and bank APIs remain disabled.

Only after that baseline is stable and measured should assisted OCR, segmentation, provider integrations, and product-scale features be activated.
