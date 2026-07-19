# Gold Trade Settlement Platform

## Bank File and Result Processing Specification

**Document ID:** `08_Bank_File_and_Result_Processing`  
**Version:** `1.1`  
**Status:** Authoritative bank-processing baseline  
**Language:** English  
**Primary audience:** Product owner, technical lead, backend engineer, frontend engineer, QA engineer, DevOps engineer, security engineer, and coding agents  
**Supersedes:** Version 1.0 of this document

**Authoritative dependencies:**

- `00_Master_Implementation_Blueprint.md`
- `01_Product_Requirements_PRD.md`
- `02_Domain_Model_and_Business_Rules.md`
- `03_System_Architecture.md`
- `04_Database_Schema.md`
- `05_API_Specification.md`
- `06_Workflows_and_State_Machines.md`
- `07_UI_UX_Specification.md`

---

## 1. Purpose and Authority

This document defines the authoritative processing rules for all bank-related files and bank-result evidence in the **Gold Trade Settlement Platform**.

It covers two distinct financial domains:

1. **Incoming-payment verification**  
   Money is paid by a trader to the center. The center verifies the incoming payment using trader evidence and imported bank-statement rows before gold dispatch or settlement.

2. **Outgoing-payment execution and result processing**  
   The center prepares an approved set of payments to beneficiaries, generates a bank-compatible export file, submits the exact file manually to the bank in Phase 1A, receives one or more result files, confirms actual bank outcomes, and publishes safe result snapshots to the relevant trader.

This document is an implementation authority for:

- bank-profile and bank-mapping behavior;
- incoming-statement imports;
- outgoing bank-export generation;
- payment splitting;
- result-bundle ingestion;
- PDF/image preview and manual crop;
- matching candidates and confirmed evidence;
- manual result confirmation;
- publication and correction;
- file security, audit, recovery, and retention.

Existing spreadsheets, bank receipts, screenshots, messenger messages, and paper workflows are **discovery evidence**, not UI or data-model templates. The system must preserve business controls while replacing fragmented execution with structured, versioned, auditable processing.

---

## 2. Scope and Non-Goals

### 2.1 In scope for Phase 1A

Phase 1A must provide a complete manual operational path for:

- versioned bank profiles and mappings;
- incoming statement upload, parsing, preview, and confirmed import;
- outgoing batch preparation and deterministic payment splitting;
- immutable batch-version finalization;
- manager approval of the exact batch version and content hash;
- preview and final bank-export generation;
- manual submission of the exact final export to the bank;
- mixed bank-result-bundle upload;
- internal image/PDF preview;
- simple rectangular manual crop inside the admin application;
- manual extraction and entry of bank-result fields;
- manual success/failure confirmation by authorized accountants;
- traceable retry and correction flows;
- immutable trader-result publication snapshots;
- secure download/share of trader-safe outputs;
- audit, idempotency, concurrency, outbox, monitoring, and recovery.

### 2.2 Explicitly not required for Phase 1A

- automatic OCR;
- automatic segmentation;
- AI-finalized matching;
- bank API execution or result ingestion;
- open-banking integration;
- automatic ownership validation for IBAN or national ID;
- anomaly models;
- multi-company or SaaS behavior;
- beneficiary login;
- generic workflow builders.

### 2.3 Phase boundaries

```text
Phase 1A — Manual operational core, including simple internal crop
Phase 1B — Assisted extraction and deterministic matching helpers
Phase 2  — Advanced OCR, automatic segmentation, duplicate/risk intelligence
Phase 3  — Bank/accounting integrations and operational scale
Phase 4  — Multi-company, SaaS, billing, and productization
```

---

## 3. Mandatory Processing Invariants

The following invariants are non-negotiable.

### 3.1 Human financial finality

AI, OCR, parsers, rules, or workers may produce technical outputs and suggestions. They must not:

- approve outgoing money;
- mark a payment attempt as paid or failed with financial finality;
- publish a result to a trader;
- authorize gold dispatch;
- override an accountant or manager decision.

### 3.2 Exact-version approval

A manager approves one exact `PaymentBatchVersion`, including:

- ordered rows;
- total amount;
- row count;
- request and attempt snapshots;
- bank-profile version;
- bank-mapping version;
- source bank account;
- canonical content hash.

Approval of a mutable batch container is invalid.

### 3.3 Exact-export submission

The system records the exact `BankExcelExport` sent to the bank. Downloading a file is not equivalent to sending it.

### 3.4 Original files are immutable

Original uploaded or generated files must never be overwritten. Normalized pages, previews, crops, and publication files are separate derived objects.

### 3.5 Evidence is not a decision

The system must keep separate:

```text
File object
Parsed/imported data
Receipt segment
Matching candidate
Confirmed evidence link
Financial result confirmation
Trader publication
```

### 3.6 Bank configuration is versioned

A bank rule or mapping already used by a finalized batch, export, statement import, or result process must not be edited in place.

### 3.7 Amount integrity

- Canonical money is positive integer IRR.
- Floating-point money is prohibited.
- User-entered value and unit may be preserved separately.
- A request is fully paid only when authoritative paid attempts equal the request amount.
- `paid_sum > request_amount` is a reconciliation error, not success.

### 3.8 Privacy isolation

A trader must never receive:

- a mixed result bundle;
- another trader's transaction;
- unrelated beneficiary data;
- internal bank/accounting notes;
- manager or audit notes;
- OCR/debug payloads.

### 3.9 No silent overwrite or deletion

Corrections create replacement/superseding records. Financial files, evidence links, results, and publications are not normally deleted.

### 3.10 Transactional command integrity

Each sensitive command must atomically or recoverably record:

```text
Business changes
Version/history changes
Audit event
Outbox event
Idempotency result
Aggregate recalculation
```

---

## 4. Canonical Terminology and Entities

| Term | Canonical meaning |
|---|---|
| `BankProfile` | Stable identity of a supported bank/integration family. |
| `BankProfileVersion` | Immutable operational rules for a period of use. |
| `BankMapping` | Versioned import/export layout definition. |
| `BankAccount` | Center-owned source or destination bank account used by a flow. |
| `BankStatementFile` | Original statement file uploaded for incoming-payment verification. |
| `BankStatementImportRun` | One immutable parsing/import attempt for a statement file. |
| `BankStatementRow` | Canonical row produced by one import run. |
| `PaymentRequest` | Business intent submitted for a beneficiary payment. |
| `PaymentRequestRevision` | Immutable request-content snapshot. |
| `PaymentAttempt` | Executable or retryable bank-level payment unit. |
| `PaymentBatch` | Logical container for one or more batch versions. |
| `PaymentBatchVersion` | Immutable ordered collection of exact payment attempts and bank settings. |
| `BatchApproval` | Append-only manager decision for one batch version and hash. |
| `BankExcelExport` | Preview or final generated bank file for one batch version. |
| `BankResultBundle` | Raw container for one or more result files returned by a bank. |
| `ReceiptSegment` | Transaction-level evidence derived from a bundle file/page or external evidence. |
| `MatchingCandidate` | Non-final suggested relationship between evidence and a target entity. |
| `ConfirmedEvidenceLink` | Human-confirmed primary or supplementary evidence relationship. |
| `PaymentResultPublication` | Immutable trader-visible result snapshot. |
| `FileObject` | Private stored original or derived file with checksum and lifecycle state. |

---

## 5. File Categories and Separation

The platform must not implement a single ambiguous `bank_file` object.

### 5.1 Incoming bank statement

Used to verify money received by the center.

Typical content:

- dates and times;
- document or tracking numbers;
- descriptions;
- incoming and outgoing amounts;
- account balance;
- sender information where provided.

### 5.2 Outgoing bank export

Generated by the platform from an approved batch version.

A real bank profile may use columns equivalent to:

```text
Row number
Beneficiary/creditor name
Account or source field
Destination IBAN
Amount in IRR
Deposit/payment identifier
```

The exact headers, order, blank columns, formats, formulas, validation, and required fields are defined by the versioned bank mapping, not hard-coded globally.

### 5.3 Bank result bundle

Returned after outgoing-payment processing. It may contain:

- images or screenshots;
- photographed paper pages;
- multi-page PDF;
- scanned PDF;
- Excel result files;
- multiple files;
- overlapping images;
- results from multiple batches or traders;
- unidentified or unrelated transactions.

### 5.4 Trader-submitted incoming evidence

Evidence submitted by a trader for money paid to the center. It is a claim that must be reconciled against center bank data where required.

---

## 6. Versioned Bank Configuration

### 6.1 BankProfile

A stable bank identity contains only long-lived identity and availability information:

```yaml
id: uuid
code: string
name: string
status: active | inactive | retired
created_at: timestamp
```

### 6.2 BankProfileVersion

An immutable version contains operational rules:

```yaml
id: uuid
bank_profile_id: uuid
version_number: integer
status: draft | active | retired
valid_from: timestamp
valid_to: timestamp nullable
default_amount_unit: IRR
statement_import_capabilities: json
payment_export_capabilities: json
result_processing_capabilities: json
transfer_rule_config: json
validation_config: json
created_by: uuid
activated_by: uuid nullable
created_at: timestamp
activated_at: timestamp nullable
```

### 6.3 BankMapping

Mappings are independently versioned and typed:

```text
statement_import
payment_export
payment_result_import
```

Suggested fields:

```yaml
id: uuid
bank_profile_version_id: uuid
mapping_type: string
version_number: integer
status: draft | active | retired
file_type: xlsx | csv | fixed_width | json
sheet_selector: json
header_selector: json
column_definitions: json
row_validation_rules: json
formatting_rules: json
mapping_hash: sha256
```

### 6.4 Activation and immutability rules

- Draft configurations may be edited.
- Activation requires validation against representative anonymized fixtures.
- An active version used by a finalized operation becomes immutable.
- Changes create a new version.
- Historical operations retain exact configuration references and snapshots.
- Only authorized business/configuration roles may activate a version.
- Activation and retirement are audited.

### 6.5 Bank adapter boundary

Application services use interfaces such as:

```text
BankStatementParser.parse(file, mapping_version)
BankExportRenderer.render(batch_version, mapping_version)
BankResultParser.parse(file, mapping_version)
```

Bank-specific behavior must remain inside configuration or isolated adapters.

---

## 7. Private File Lifecycle

### 7.1 File states

```text
pending
quarantined
available
processing_failed
archived
retention_pending
deleted_by_policy
```

### 7.2 Upload sequence

```text
Client uploads
→ private pending storage
→ MIME/extension/size validation
→ checksum calculation
→ malware scan according to policy
→ FileObject created/finalized
→ state becomes available or quarantined
→ preview/processing jobs may start
```

### 7.3 Mandatory metadata

```yaml
id: uuid
kind: original | preview | normalized_page | crop | generated_export | publication
original_filename: string
content_type: string
size_bytes: integer
sha256_checksum: string
storage_key: private
state: string
created_by_actor: string
created_at: timestamp
```

### 7.4 Security rules

- Never return raw storage paths.
- Downloads require resource-level authorization every time.
- Signed URLs, when used, are short-lived and scoped.
- Frontend applications do not receive storage credentials.
- Executable content is prohibited.
- File-type acceptance must use content inspection, not extension alone.
- Sensitive downloads should be auditable according to policy.

### 7.5 Derivation graph

Derived files must identify their source:

```text
Original PDF
 ├── Preview page 1
 ├── Preview page 2
 └── Manual crop segment

Approved batch version
 ├── Preview bank export
 └── Final bank export
```

A derivation stores source file, operation type, parameters, renderer version, and checksums.

---

## 8. Incoming Bank Statement Processing

### 8.1 Supported Phase 1A input

At minimum:

- `.xlsx` for approved bank mappings;
- a selected bank-profile version;
- a selected destination center account;
- optional operator-supplied statement range;
- original file preservation.

CSV may be enabled per bank mapping when validated. PDF statement extraction is later-phase unless implemented as a bank-specific deterministic parser.

### 8.2 Versioned workflow

```text
Upload original statement file
→ validate and make file available
→ create BankStatementFile
→ create BankStatementImportRun
→ parse with exact BankProfileVersion and BankMapping
→ preserve raw cells and row errors
→ show import preview
→ accountant confirms or rejects the import run
→ confirmed rows become available for matching
```

Reprocessing never overwrites earlier rows. It creates a new import run.

### 8.3 Import-run states

```text
draft
queued
parsing
preview_ready
partial_preview
parse_failed
confirmed
rejected
superseded
```

### 8.4 Canonical statement row

```json
{
  "import_run_id": "uuid",
  "source_row_number": 42,
  "transaction_timestamp": "2026-07-18T09:15:23+03:30",
  "transaction_date_raw": "1405/04/27",
  "transaction_time_raw": "09:15:23",
  "document_number": "optional",
  "tracking_number": "optional",
  "description": "optional",
  "deposit_amount_irr": 2000000000,
  "withdrawal_amount_irr": 0,
  "balance_amount_irr": 12300000000,
  "counterparty_name": "optional",
  "counterparty_iban": "optional",
  "normalized_fingerprint": "sha256",
  "raw_row_data": {},
  "parse_status": "valid"
}
```

Missing fields remain null. They must not be guessed.

### 8.5 Normalization rules

- Preserve every raw source value.
- Parse amount with bank-mapping rules.
- Reject or flag decimal/fractional IRR unless explicitly supported.
- Store timestamps in a timezone-aware canonical form.
- Preserve raw Jalali/Gregorian strings.
- Normalize IBAN and tracking values without losing originals.
- Do not silently convert debit to credit or vice versa.

### 8.6 Row validation

Each row receives a state such as:

```text
valid
warning
invalid
ignored_empty
possible_duplicate
```

Validation checks include:

- required source columns;
- numeric amount validity;
- mutually coherent deposit/withdrawal values;
- date parsing;
- empty-row handling;
- duplicate detection;
- mapping consistency;
- impossible amount or balance values.

Invalid rows are visible in preview. Partial import requires explicit confirmation and an audit note.

### 8.7 Duplicate detection

Signals may include:

- same original file checksum;
- same bank account and statement period;
- same normalized row fingerprint;
- same tracking/document number;
- same timestamp, amount, and description.

A warning does not automatically delete or merge data.

### 8.8 Incoming-payment matching

Matching sources:

- trader-submitted receipt/evidence;
- structured payment data;
- bank statement rows.

Phase 1A allows manual search and confirmation. Candidate rules may help but remain non-final.

A confirmed incoming match must:

- reference the exact import run and row;
- reference the exact trader evidence/payment record;
- record actor, time, reason, and warnings;
- prevent silent reuse of an already-authoritative row;
- recalculate the gold-sale order in the same transaction;
- create audit and outbox events.

### 8.9 Incoming edge cases

The workflow must support:

- evidence before statement availability;
- statement row without trader evidence;
- several incoming transfers for one order;
- one transfer allocated across approved business records only through explicit policy;
- underpayment and overpayment;
- duplicate or fake receipt suspicion;
- correction of a wrong confirmed match;
- a new import run after mapping correction.

---

## 9. Outgoing Payment Preparation

### 9.1 Eligibility

A request revision is eligible for batch preparation when:

- trader is active;
- request is `eligible_for_batching`;
- current request revision is valid;
- amount is positive integer IRR;
- beneficiary snapshot is complete;
- beneficiary is not blocked;
- no unresolved critical warning exists;
- the allocatable amount is not already allocated to an active/sent attempt;
- the request is not cancelled or closed.

### 9.2 Preview before persistence

A selection preview should show:

- selected request revisions;
- bank-profile and mapping versions;
- source bank account;
- deterministic split results;
- row-level validation;
- total amount and row count;
- duplicate-allocation warnings;
- expected export layout.

Preview is not approval and does not reserve or send money.

### 9.3 Batch and version creation

```text
Create PaymentBatch container
→ create draft PaymentBatchVersion
→ create exact PaymentAttempts and PaymentBatchItems
→ validate totals and allocation
→ accountant reviews
→ finalize immutable version
→ manager reviews exact version
```

### 9.4 Finalized version contents

A finalized version stores:

```yaml
version_number: integer
bank_profile_version_id: uuid
bank_mapping_id: uuid
source_bank_account_id: uuid
ordered_items: immutable
row_count: integer
total_amount_irr: integer
validation_summary: json
content_hash: sha256
finalized_by: uuid
finalized_at: timestamp
```

### 9.5 Canonical content hash

The hash must be deterministic. Canonical input should include, at minimum, ordered rows containing:

```text
row order
payment attempt ID
payment request revision ID
beneficiary snapshot
normalized destination IBAN
amount IRR
deposit/payment identifier
bank-profile version
bank-mapping version
source account
```

Whitespace, locale formatting, or presentation-only values must not alter the canonical hash unless they affect the bank file.

---

## 10. Payment Splitting

### 10.1 Configuration

Splitting belongs to the selected `BankProfileVersion` and is snapshotted into the batch version.

Example:

```json
{
  "enabled": true,
  "default_max_amount_irr": 5000000000,
  "time_zone": "Asia/Tehran",
  "time_rules": [
    {
      "from_local_time": "14:00:00",
      "max_amount_irr": 2000000000
    }
  ],
  "strategy": "max_chunks_then_remainder",
  "minimum_row_amount_irr": 1
}
```

These values are examples, not hard-coded business rules.

### 10.2 Determinism

Given the same:

- request revision;
- amount;
- bank-profile version;
- source account;
- effective business timestamp;

the splitting engine must produce the same ordered attempts.

### 10.3 Allocation invariant

```text
sum(active split attempt amounts for the revision allocation)
= allocated request amount
```

### 10.4 Failed split attempts

- Successful attempts remain authoritative.
- Failed attempts remain historical.
- Retry creates a new attempt.
- Retry references the exact current request revision.
- A new batch version and manager approval are required before retry submission.
- Already paid amount is not recreated or re-exported.

---

## 11. Manager Approval

### 11.1 Approval target

The manager approves one exact batch version and `content_hash`.

### 11.2 Approval guards

- version is finalized and current;
- all validations pass;
- no unresolved blocking warning exists;
- actor has approval permission;
- recent authentication is valid;
- separation-of-duty policy is satisfied;
- expected hash matches current hash;
- no existing final decision exists for the same version;
- idempotency key is valid.

### 11.3 Approval result

An append-only `BatchApproval` records:

```yaml
payment_batch_version_id: uuid
content_hash: sha256
decision: approved | rejected
actor_id: uuid
note: string nullable
authentication_context: json
created_at: timestamp
```

### 11.4 Change after approval

Material change never edits the approved version. It creates a replacement version. The previous approval remains historical but cannot authorize the replacement.

---

## 12. Bank Export Generation

### 12.1 Export types

```text
preview
final
```

### 12.2 Preview export

A preview may be generated before approval for human review.

It must:

- be visibly marked non-sendable;
- have a distinct export type and filename;
- not be eligible for `mark-sent-to-bank`;
- not be used as evidence that approval occurred.

### 12.3 Final export prerequisites

- approved exact batch version;
- matching approval and content hash;
- active/allowed mapping version;
- available source account;
- no attempt previously sent in another authoritative export;
- all required values available;
- idempotency key supplied.

### 12.4 Typical export mapping

```json
{
  "file_type": "xlsx",
  "sheet_name": "Sheet1",
  "start_row": 2,
  "columns": [
    {"header": "ردیف", "source": "row.sequence", "type": "integer"},
    {"header": "بستانکار", "source": "attempt.beneficiary_name", "type": "text"},
    {"header": "حساب", "source": "source_account.export_value", "type": "text"},
    {"header": "شبای مقصد", "source": "attempt.destination_iban", "type": "text"},
    {"header": "مبلغ به ریال", "source": "attempt.amount_irr", "type": "integer"},
    {"header": "شناسه واریز", "source": "attempt.deposit_identifier", "type": "text", "required": false}
  ]
}
```

This is an example fixture based on observed workflow needs. Each production mapping must be verified against an anonymized bank template.

### 12.5 Export record

Store:

- export type;
- batch-version and approval IDs;
- bank-profile/mapping versions;
- source account;
- file object;
- file checksum;
- canonical batch content hash;
- row count;
- total amount;
- renderer version;
- mapping snapshot;
- generated by/at;
- validation result;
- download history where required.

### 12.6 Export integrity validation

Before final download and before marking sent:

```text
Export batch version == approved batch version
Export content hash == version content hash
Approval content hash == version content hash
Export row count == version row count
Export total == version total
Export mapping == approved mapping
Export source account == approved source account
Stored file checksum == current file checksum
```

Any mismatch:

- blocks download/submission action;
- sets export to `quarantined`;
- creates a high-priority review task;
- emits audit and alert events.

### 12.7 Export states

```text
generating
generated
validated
downloaded
sent_to_bank_marked
voided
quarantined
generation_failed
```

### 12.8 Filename

Recommended:

```text
bank-export-{bank-code}-{batch-number}-v{batch-version}-{jalali-date}-{export-short-id}.xlsx
```

Preview files include `PREVIEW-NOT-SENDABLE` in the filename or visible document content.

---

## 13. Marking the Exact Export as Sent

### 13.1 Command target

The command targets a `BankExcelExport`, not only a batch.

### 13.2 Required information

- exact export ID;
- sent timestamp;
- submission channel;
- optional operator note;
- expected record version/ETag;
- idempotency key.

### 13.3 Guards

- export is final and validated;
- export has not been voided or quarantined;
- approval remains valid for the same version/hash;
- export has not already been sent, except idempotent replay;
- actor has permission;
- file is available and checksum-valid.

### 13.4 Atomic side effects

```text
Mark exact export sent
→ mark batch sent_to_bank
→ mark included attempts sent_to_bank / bank_result_pending
→ update affected request aggregates
→ write audit event
→ write outbox events
→ save idempotency response
```

---

## 14. Bank Result Bundle Ingestion

### 14.1 Bundle model

A bundle is a raw evidence container. It is not a batch and must not be assumed to map one-to-one to a batch.

### 14.2 Upload workflow

```text
Upload one or more original files
→ private pending/quarantine validation
→ create bundle and file links
→ mark available files
→ create previews/pages where supported
→ enter manual-review queue
→ optionally relate candidate batches/exports
```

### 14.3 Bundle states

```text
uploaded
preparing_preview
ready_for_manual_review
under_manual_review
partially_resolved
resolved
needs_attention
processing_failed
closed
archived
```

### 14.4 Relationships

A bundle may relate to:

- zero, one, or many payment batches;
- zero, one, or many exact bank exports;
- multiple traders;
- unknown or unrelated transactions.

Relationships are advisory until individual result evidence is confirmed.

### 14.5 Closing a bundle

A bundle can be closed with unresolved content only when:

- all known actionable items are resolved or have review tasks;
- unresolved items are explicitly classified;
- a closure reason is recorded;
- authorization policy permits closure;
- closure does not delete or hide evidence.

---

## 15. Preview, Normalized Pages, and Manual Crop

### 15.1 Phase 1A requirement

Phase 1A includes a minimal internal manual crop tool. It is not AI and does not make financial decisions.

### 15.2 Preview support

At minimum:

- images;
- image-based and text PDFs;
- PDF page navigation;
- zoom and pan;
- clockwise/counter-clockwise rotation;
- safe download for authorized internal users;
- Excel metadata/row preview where a deterministic parser exists.

### 15.3 Crop input

```json
{
  "source_file_id": "uuid",
  "page_number": 1,
  "bbox_normalized": {
    "x": "0.105000",
    "y": "0.220000",
    "width": "0.790000",
    "height": "0.160000"
  },
  "rotation_degrees": 90,
  "client_source_dimensions": {
    "width": 1600,
    "height": 2200
  }
}
```

Normalized coordinates are decimal strings between `0` and `1`.

### 15.4 Crop provenance

A manual crop stores:

```yaml
source_file_id: uuid
source_page_number: integer
bbox_normalized: json
source_width_px: integer
source_height_px: integer
rotation_degrees: integer
renderer_name: string
renderer_version: string
render_parameters: json
crop_file_id: uuid
crop_checksum: sha256
created_by: uuid
created_at: timestamp
```

### 15.5 Crop workflow

```text
Open authorized preview
→ select page/rotation
→ draw rectangle
→ preview selected region
→ save segment request
→ worker renders derived crop
→ verify derived checksum and dimensions
→ segment becomes available for structured entry/matching
```

### 15.6 Crop failure

A failed crop:

- does not alter the original file;
- records technical error;
- may be retried idempotently;
- remains visible as processing failed;
- does not block use of external evidence attachment.

### 15.7 Privacy review

Before a crop can be included in a trader publication, an accountant confirms that:

- it contains only the relevant transaction;
- unrelated names, IBANs, amounts, and tracking values are absent;
- it matches the selected attempt;
- it is readable enough for its intended purpose.

---

## 16. Receipt Segments

### 16.1 Segment sources

```text
manual_in_panel_crop
manual_external_attachment
manual_structured_result
excel_result_row
ai_auto_segmented
```

`ai_auto_segmented` is later-phase.

### 16.2 Segment fields

A segment records:

- source bundle/file/page;
- optional crop derivation;
- structured bank fields;
- source values and normalized values;
- creation method;
- processing confidence when applicable;
- status and history;
- actor and timestamps.

### 16.3 Segment lifecycle

```text
draft
available
unmatched
candidate_exists
confirmed_evidence
irrelevant
superseded
archived
```

A segment itself never proves payment until an authorized human creates a confirmed evidence link and confirms the financial outcome.

---

## 17. Matching Candidate and Confirmed Evidence

### 17.1 MatchingCandidate

A candidate is non-final and may be created by:

- manual search;
- deterministic rules;
- bank-specific parser;
- OCR/AI in later phases.

Candidate states:

```text
proposed
accepted_for_confirmation
rejected
expired
superseded
```

Accepting a candidate does not mark an attempt paid.

### 17.2 Matching signals

Potential signals:

- exact amount;
- destination IBAN;
- beneficiary name;
- tracking/document number;
- result date/time;
- exact sent export context;
- bank-profile version;
- split sequence and amount pattern;
- internal description/reference where returned.

### 17.3 Ambiguity handling

The system must not auto-finalize when:

- several attempts share amount and beneficiary;
- split attempts are identical;
- IBAN is missing or partly unreadable;
- tracking number appears multiple times;
- result bundle mixes exports;
- an existing active evidence link conflicts.

### 17.4 ConfirmedEvidenceLink

A confirmed link is created by an authorized human and is classified as:

```text
primary
supplementary
```

Default cardinality:

- one active primary link per payment attempt;
- one active primary attempt per transaction segment;
- multiple supplementary files may be attached;
- old links are `replaced` or `revoked`, not deleted.

### 17.5 Link replacement

```text
Validate current link and target
→ mark old link replaced
→ create new active link
→ recalculate result/publication impact
→ create audit and outbox events
```

This occurs in one transaction.

---

## 18. Manual Result Confirmation

### 18.1 Manual-first requirement

An authorized accountant can confirm results without OCR or automatic matching.

### 18.2 Confirmation inputs

For paid confirmation:

- exact payment attempt;
- bank result date/time where available;
- tracking/document number where available;
- structured bank note;
- primary evidence link or approved exception reason;
- expected record version;
- idempotency key.

For failed confirmation:

- exact payment attempt;
- failure reason code;
- bank result note/evidence where available;
- expected record version;
- idempotency key.

### 18.3 Evidence policy

Production policy must choose one of:

```text
Evidence required for paid confirmation
Evidence required only before trader publication
Text-only confirmation allowed as controlled exception
```

When text-only confirmation is enabled, it requires:

- elevated permission;
- mandatory reason;
- prominent warning;
- audit classification;
- reviewability in reports.

### 18.4 Paid confirmation guards

- attempt was sent to bank or an authorized exceptional flow applies;
- attempt is not cancelled/superseded;
- result is not already final except idempotent replay;
- evidence cardinality is valid;
- amount equals the attempt amount;
- parent paid sum will not exceed request amount;
- actor has permission;
- no stale record version;
- no duplicate tracking/evidence conflict remains unresolved.

### 18.5 Atomic result side effects

```text
Confirm attempt result
→ persist result/history
→ update attempt state
→ recalculate payment request
→ recalculate batch
→ create/resolve review tasks
→ write audit
→ write outbox
→ store idempotency result
```

### 18.6 Retry

A retry:

- creates a new attempt;
- references the original failed attempt;
- references an exact request revision;
- cannot edit the previous attempt;
- is included in a new finalized and approved batch version;
- cannot exceed the unpaid authoritative remainder.

### 18.7 Overpayment

If a confirmation would produce:

```text
authoritative_paid_sum > request_amount_irr
```

confirmation is blocked and a reconciliation task is created.

---

## 19. Trader Result Publication

### 19.1 Publication is a snapshot

A trader-visible result is represented by an immutable `PaymentResultPublication`.

It contains the exact values shown at publication time:

- request and publication references;
- publication version;
- beneficiary snapshot;
- amount and unit displays;
- attempt results;
- bank and tracking information;
- selected safe evidence;
- generated share file;
- content hash;
- published by/at.

### 19.2 Publication states

```text
active
superseded
revoked
```

### 19.3 Publication guards

- financial result is human-confirmed;
- trader owns the request;
- evidence is safe for trader visibility;
- full mixed bundle is not included;
- required evidence policy is satisfied;
- no unresolved privacy warning exists;
- publication preview has been reviewed;
- idempotency key and expected version are valid.

### 19.4 Share output

Phase 1A may generate an image or PDF-like result card containing structured fields. It must not include unrelated data or raw mixed evidence.

### 19.5 Publication correction

A correction creates version `N+1`, supersedes the active version, preserves history, and notifies the trader when materially changed.

---

## 20. Correction and Reconciliation

### 20.1 Evidence-only correction

Replacing evidence without changing the financial result:

- uses evidence-link replacement;
- records reason;
- preserves old evidence;
- reevaluates publication privacy;
- creates a replacement publication when the active publication changes.

### 20.2 Material result correction

Changing a published paid/failed result is a sensitive correction.

Required flow:

```text
Create sensitive review task
→ record correction reason and new evidence
→ obtain required manager/dual-control approval
→ supersede incorrect result record
→ create corrected result/history
→ recalculate parent aggregates
→ create replacement publication
→ notify trader
→ audit all steps
```

### 20.3 Re-export

A previously sent attempt must never be re-exported as a normal selection.

A controlled re-export/retry requires:

- failure or correction rationale;
- new attempt when appropriate;
- new batch version;
- manager approval;
- new final export;
- preserved original export history.

---

## 21. Concurrency, Idempotency, and Transactions

### 21.1 Required idempotent commands

- statement upload finalization;
- import-run confirmation;
- batch creation and version finalization;
- manager approval/rejection;
- final-export generation;
- mark exact export sent;
- result confirmation;
- retry creation;
- evidence replacement;
- publication and publication correction;
- crop creation.

### 21.2 Optimistic concurrency

Mutable resources return `ETag` and require `If-Match` for sensitive changes.

Stale changes return:

```text
412 VERSION_CONFLICT
```

Missing precondition where required returns:

```text
428 PRECONDITION_REQUIRED
```

### 21.3 Database constraints and locks

Use appropriate transactions, partial unique indexes, and row/advisory locks to prevent:

- duplicate active allocation of an attempt;
- two manager decisions for one version;
- two final exports for one approved version when policy allows only one;
- two active primary evidence links;
- duplicate result confirmation;
- paid sum exceeding request amount;
- simultaneous conflicting publication updates.

### 21.4 Transactional outbox

Business commits must not depend on notification availability. Notifications, generated reports, and integrations are driven from outbox events after commit.

---

## 22. Error Handling and Recovery

### 22.1 Upload/storage mismatch

Possible states:

- object stored but database transaction failed;
- database file record exists but object upload failed;
- client timed out after successful commit.

Recovery:

- orphan-object reconciliation;
- missing-object reconciliation;
- idempotent upload finalization;
- clear operator-visible status;
- no duplicate business object creation.

### 22.2 Import failure

- preserve original file;
- preserve import-run errors;
- allow new import run after mapping correction;
- never partially hide invalid rows;
- manual workflow remains available.

### 22.3 Export failure

- no partial file is available as final;
- store generation error and renderer logs;
- retry with same idempotency key returns prior state;
- changed input requires new batch version or command key;
- integrity mismatch quarantines the export.

### 22.4 Crop/preview failure

- preserve original;
- allow authorized original download;
- allow external evidence attachment;
- retry derived processing;
- alert when failure rate exceeds threshold.

### 22.5 Timeout after financial commit

The client reuses the same idempotency key and checks authoritative resource state before showing failure or repeating the command.

### 22.6 Result before recorded submission

A bank result may arrive before an operator marks the export sent. The system must:

- preserve the bundle;
- flag the sequence anomaly;
- allow authorized reconciliation to the exact export;
- never invent a sent event automatically.

---

## 23. Security and Privacy

### 23.1 Authorization

- Traders access only their own published snapshots.
- Accountants access operational files according to role and assignment policy.
- Managers access approval views and necessary financial context.
- Technical admins do not receive financial-file access by default.
- Read-only access cannot execute commands or download restricted evidence unless explicitly granted.

### 23.2 Sensitive fields

Sensitive data includes:

- full IBAN/account details;
- beneficiary and trader identities;
- national IDs;
- amounts;
- tracking/document numbers;
- bank evidence;
- raw import rows;
- audit before/after values.

### 23.3 Logs and analytics

Do not send banking data to third-party product analytics. Application logs must avoid raw sensitive payloads and storage URLs.

### 23.4 Test data

- Real uploaded banking samples must not be committed to source control.
- Automated tests use anonymized or synthetic fixtures.
- Screenshots used in tickets/documentation must be redacted.
- Staging must not casually reuse production banking files.

---

## 24. Retention and Legal Hold

### 24.1 Governed retention

Retention is not a normal technical setting. Policies require business/legal ownership.

Covered objects include:

- original statements and result bundles;
- import runs and rows;
- generated bank exports;
- previews and crops;
- evidence links;
- publications;
- audit and outbox history where required.

### 24.2 Reduction workflow

Reducing retention requires:

- policy proposal;
- legal/business approval;
- legal-hold evaluation;
- dry-run scope report;
- backup-policy coordination;
- separately authorized deletion job;
- audit evidence.

### 24.3 Legal hold

Objects under legal hold are excluded from normal deletion even when retention age is reached.

---

## 25. Observability and Alerts

### 25.1 Metrics

Collect, without exposing sensitive values:

- statement uploads/import runs by bank;
- parse success, partial, and failure counts;
- row-validation error categories;
- batch versions finalized and rejected;
- manager approval latency;
- export generation and integrity failures;
- exported amount totals by authorized reporting dimension;
- exact exports awaiting sent confirmation;
- result bundles awaiting review;
- crop/preview processing latency and failures;
- unmatched segments;
- result-confirmation latency;
- retries and correction counts;
- publication corrections;
- text-only confirmation exceptions;
- duplicate warnings;
- outbox backlog;
- orphan/missing file reconciliation counts.

### 25.2 Alerts

Alert on:

- export-integrity mismatch;
- repeated export-generation failure;
- unavailable storage;
- large outbox backlog;
- worker heartbeat loss;
- repeated statement-parser failure for an active mapping;
- abnormal duplicate-confirmation conflict;
- backup or restore-test failure;
- quarantined files requiring attention.

---

## 26. QA Test Matrix

### 26.1 Bank configuration

- activate valid mapping fixture;
- reject invalid required columns;
- preserve old mapping after new version activation;
- prevent editing a used active version;
- verify permission and audit for activation.

### 26.2 Statement import

- valid first-bank XLSX;
- partial blank template rows;
- missing column;
- invalid amount;
- duplicate file checksum;
- duplicate normalized rows;
- partial preview confirmation;
- rejected import run;
- reparse creates a new run;
- old confirmed rows remain unchanged.

### 26.3 Batch and splitting

- deterministic preview;
- no split below limit;
- exact multiple of limit;
- remainder split;
- time-zone boundary rule;
- duplicate allocation blocked;
- blocked beneficiary rejected;
- finalized version immutable;
- content hash stable for identical canonical input.

### 26.4 Approval and export

- stale version cannot be approved;
- stale hash cannot be approved;
- duplicate approval is idempotent;
- preview is visibly non-sendable;
- final export blocked without approval;
- final export matches real anonymized bank headers/order;
- file checksum validated;
- mismatched export quarantined;
- exact export marked sent once;
- download does not mark sent.

### 26.5 Result bundles and crop

- image bundle;
- multi-image bundle;
- ten-page PDF bundle;
- mixed-batch bundle;
- no selected batch;
- preview page navigation;
- normalized-coordinate crop;
- rotated-page crop;
- crop worker retry;
- external attachment fallback;
- privacy review blocks unsafe trader publication.

### 26.6 Matching and confirmation

- manual exact match;
- ambiguous same-amount attempts;
- candidate acceptance does not mark paid;
- primary evidence uniqueness;
- supplementary evidence allowed;
- paid confirmation with evidence;
- failed confirmation;
- controlled text-only exception;
- duplicate tracking warning;
- overpayment blocked;
- partial paid request and retry.

### 26.7 Correction and publication

- evidence replacement preserves old link;
- wrong paid result enters sensitive correction flow;
- publication version N+1 supersedes N;
- trader notified after material correction;
- trader cannot access superseded raw bundle;
- another trader receives 404/forbidden-safe response;
- audit history remains complete.

### 26.8 Reliability

- timeout after commit with same idempotency key;
- concurrent accountant confirmation;
- concurrent manager approval;
- storage success/database failure reconciliation;
- database success/storage failure reconciliation;
- Redis unavailable during manual operation;
- outbox delivery retry;
- worker restart during export/crop.

---

## 27. Phase 1A Acceptance Criteria

Phase 1A is acceptable only when all are true:

1. At least one real, anonymized bank profile/version/mapping is validated.
2. An incoming statement can be uploaded, previewed, confirmed, and searched.
3. Reprocessing creates a new import run without overwriting history.
4. Eligible request revisions can be split deterministically into attempts.
5. A batch version can be finalized and hashed.
6. A manager approves the exact version and hash.
7. A preview export cannot be sent as final.
8. A final export is generated only from the approved version.
9. Export row count, total, mapping, source account, and file checksum are validated.
10. The exact export can be marked sent once, idempotently.
11. A mixed bank-result bundle with multiple files can be uploaded.
12. Image and PDF previews are available for manual review.
13. A simple internal rectangular crop can create a receipt segment.
14. An accountant can manually confirm paid or failed without AI/OCR.
15. Candidate matches do not finalize results.
16. Confirmed primary evidence cardinality is enforced.
17. Partial payment and traceable retry are supported.
18. Overpayment confirmation is blocked for reconciliation.
19. Trader publication is an immutable safe snapshot.
20. Correction creates replacement history and a new publication when needed.
21. Traders cannot access mixed or unrelated evidence.
22. All sensitive commands are audited and idempotent.
23. File-storage inconsistencies can be detected and reconciled.
24. Core manual workflows remain usable when AI and Redis-assisted optional processing are unavailable.

---

## 28. Recommended Implementation Order

1. Private file abstraction, lifecycle, checksums, and authorization.
2. Bank profile, profile-version, mapping, and source-account models.
3. First anonymized incoming-statement parser and import-run preview.
4. Request eligibility and deterministic splitting engine.
5. Batch container/version/item finalization and canonical hashing.
6. Manager approval for exact version/hash.
7. Preview and final export renderer plus integrity validation.
8. Exact-export sent command.
9. Bank-result-bundle upload and secure preview.
10. Manual crop and receipt-segment provenance.
11. Manual attempt paid/failed confirmation.
12. Candidate and confirmed-evidence workflows.
13. Trader publication snapshot and safe share output.
14. Retry, correction, and reconciliation workflows.
15. Monitoring, reconciliation jobs, and operational alerts.
16. Optional OCR, segmentation, and matching assistance under feature flags.

---

## 29. Production Decisions Still Required

These decisions do not change the core model but must be resolved before production launch:

1. Exact first and second bank templates and anonymized validation fixtures.
2. Production source-bank accounts and authorized operators.
3. Maximum file sizes and accepted file types per category.
4. Malware-scanning approach.
5. Whether evidence is required at paid confirmation or only at publication.
6. Whether text-only paid confirmation is allowed and for which role.
7. Recent-authentication timeout for manager approval.
8. Separation-of-duty policy.
9. Full or masked IBAN policy for trader publications.
10. Image, PDF, or both for generated share output.
11. Closure authority for bundles with unresolved content.
12. Final retention, legal-hold, RPO, and RTO policies.
13. Expected daily/peak volumes for statements, attempts, bundle pages, and crops.
14. Required dual control for correcting a published paid result.

---

## 30. Coding-Agent Rules

1. Do not hard-code bank names, column positions, limits, or time rules outside versioned adapters/configuration.
2. Do not merge payment requests, revisions, attempts, batches, versions, exports, and result bundles.
3. Do not approve a batch container; approve an exact batch version/hash.
4. Do not generate a sendable final export from an unapproved version.
5. Do not treat file download as bank submission.
6. Do not update sent attempts in place.
7. Do not let candidate matching finalize payment.
8. Do not publish a receipt segment directly; create a publication snapshot.
9. Do not expose raw storage paths or mixed bundles to traders.
10. Do not overwrite original files, import rows, evidence, results, or publications.
11. Do not store money as float or infer Rial/Toman silently.
12. Do not allow paid sum to exceed request amount.
13. Do not implement manual crop without source/page/coordinate provenance.
14. Do not make OCR/AI a dependency of Phase 1A.
15. Do not omit idempotency, concurrency, audit, or outbox behavior from sensitive commands.
16. Do not commit real banking files or personal data to the repository.
17. Do not change retention through a simple settings toggle.
18. Do not mark a bundle fully resolved merely because some known attempts are matched.

---

## 31. Summary

The bank-processing subsystem is a versioned evidence-and-decision system, not a file-upload utility.

The critical implementation model is:

```text
Versioned bank configuration
→ versioned incoming imports
→ immutable outgoing batch version
→ manager approval of exact hash
→ validated final bank export
→ exact export sent record
→ mixed result-bundle ingestion
→ manual crop / structured evidence
→ candidate matching
→ human-confirmed financial result
→ immutable trader publication
→ traceable correction and retention
```

Phase 1A is manual-first but must already provide the operational controls needed for high-value financial work: exact snapshots, human approval, privacy-safe evidence, deterministic splitting, idempotency, concurrency protection, and complete auditability.
