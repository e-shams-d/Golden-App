# M5 Implementation Plan — Trader, Beneficiary, and the Immutable Payment Request

Status: Working implementation plan for hand-off to implementers. Not an approved M0 artifact.
Milestone authority: `Implementation Docs/00_Start_Here/15_Agent_Implementation_Plan.md:734-821`.
Precondition: M4 as merged — the private-file lifecycle, its ownership registry, versioned
bank configuration, and the M4 Definition-of-Done gate exist. Every M4 obligation is either
discharged or a recorded gap.
Date of this revision: 2026-08-16.

Every claim traceable to a document is cited as `path:line`. Where this plan resolves a
divergence between authorities, the divergence is named and the resolution is recorded in
section 2 so it is raised in the pull request rather than decided silently inside a
migration.

---

# 1. What M5 delivers, and the Definition of Done

## 1.1 Scope, as the milestone authority states it

`15_Agent_Implementation_Plan.md:738` sets the goal: "Implement trader onboarding and the
full business-intent lifecycle for outgoing payment requests."

`:740-751` lists eleven trader and beneficiary deliverables. `:753-768` lists the request
aggregate: `PaymentRequest`, immutable `PaymentRequestRevision` records, exact snapshots, a
current-revision pointer with same-request composite integrity, draft creation, correction,
submission, accountant review, return for correction, marking eligible for batching,
cancellation, and history.

`:770-794` fixes sixteen canonical statuses and adds the sentence that shapes the whole
milestone: **"A manager does not approve individual ordinary requests for batching."**

`:796-802` sets the money rules. `:804-814` lists nine tests.

## 1.2 Definition of Done (verbatim)

`15_Agent_Implementation_Plan.md:818`:

> M5 is complete when a trader can submit a request, receive a correction request, create a
> new immutable revision, resubmit, and reach `eligible_for_batching` without any manager
> approval at request level.

This is the first DoD in the programme that names a **journey** rather than a property or
an artifact. M2's named one artifact, M3's named a property of the test suite, M4's named a
boundary. This one names six steps a person takes, and it ends with a negative: *without
any manager approval*.

Both halves need gates, and they are different in kind:

1. **The journey runs end to end.** One integration test drives all six steps through the
   API as the two actors really would — a trader and an accountant — and asserts the
   request arrives at `eligible_for_batching`. Six steps proved separately can all pass
   while the sequence is impossible, which is the failure a journey DoD exists to catch.
2. **No manager approval exists at request level.** This cannot be proved by a test that
   does not call something. It is a gate over the route table and the permission
   catalogue: no request-level route may require a manager-only permission, and no
   request-scoped command may consult one. `12_Security_RBAC_Audit.md:876-904`'s role
   matrix is the authority for which permissions are manager-only, and it closes with the
   sentence the gate exists to keep true — `:904`, "Accountant eligibility is not manager
   approval."

The second is easy to lose. Batch-level approval **is** a manager's job from M6 onward
(`FINANCIAL_INTEGRITY_BASELINE.md` §5), so the temptation to add "just one" manager check
at request level will arrive with real motivation behind it. Slice 9 is that gate.

`docs/governance/TRACEABILITY_MATRIX.md:27` restates the row and adds what the DoD omits:
revision immutability, snapshot exactness, ownership and IDOR enforcement, money unit
handling, and `If-Match` behaviour.

## 1.3 What M5 starts with, and what it must build

Unlike M4 — which began with a complete foundation nothing called — **M5 begins with
almost nothing built.** `services/backend/app/db/models/` has `trader.py` (M3's `traders`
table) and no `beneficiaries`, no `payment_requests`, no `payment_request_revisions`.

So M5 is a schema milestone as well as a workflow one, and the ordering follows M2's
lesson rather than M4's: the tables come first, with their constraints, and the commands
are written against constraints that already refuse the wrong thing.

What M3 and M4 leave ready:

- `traders` with `operational_status` and `approval_status` as **two axes**
  (DOC-CONFLICT-024's approved structure), and the trader lifecycle commands.
- Ownership guards, `ActorContext.trader_id` as the single source of ownership scope, and
  the M3 DoD gate that will demand a negative ownership test for every new protected route.
- `IdempotencyResolver`, `compare_and_swap`, the Unit of Work, audit and outbox in one
  transaction.
- The file service: a request's attachment is a `file_object`, and M5 registers an
  ownership resolver for its category rather than inventing access rules
  (`app/files/ownership.py`).
- `app/core/money.py` and the `MONEY_TIME_CONTRACT`.

---

# 2. Authority, precedence, and the decisions this plan makes

## 2.1 Baselines that bind M5

| Baseline | What it settles |
|---|---|
| **DOC-CONFLICT-001, Approved 2026-08-01** | Document 06's status names are canonical; the PRD's spellings are legacy aliases that must never reach schema, API or UI. `payment_request.sent_to_bank` and `payment_attempt.bank_result_pending` stay separate because they describe different facts. |
| **DOC-CONFLICT-002, Approved 2026-08-01 (POL-002)** | Correcting a published paid result needs manager authority or dual control. That is M9; it is listed here because it is the one place manager authority *does* touch a request, and confusing it with request-level approval is the error slice 9 guards. |
| **DOC-CONFLICT-024, structure approved 2026-08-08** | Three axes, no stored projection. **The trader value sets are explicitly assigned to M5** — see §2.4. |
| `docs/governance/status_catalog.yaml` | `payment_request` canonical values. M5 uses those and adds none. |
| `docs/governance/permission_catalog.yaml` | `payment_request.*`, `beneficiary.*` and `trader.*` identifiers, and the role matrix that says which are manager-only. |
| `FINANCIAL_INTEGRITY_BASELINE.md` §5 | `finalizer != approver` at **batch** level. Nothing at request level. |

## 2.2 DOC-CONFLICT-005 — where the amount and the snapshots live

The register's interim rule is: "Preserve the concept of immutable revisions but **do not
choose its table/API representation** until documents 02, 04, 05, and 06 are aligned."

Read literally that blocks M5 entirely, because the revision is the aggregate. So it is
worth being precise about what is actually in dispute, and my first reading of it was
wrong. This is not one authority being silent. It is two different designs.

- `04_Database_Schema.md:873-906` defines `payment_request_revisions` **completely** —
  seventeen columns, the snapshots, `content_hash`, and the composite integrity that ties
  a current-revision pointer back to the same request.
- `05_API_Specification.md:1142` defines `POST /payment-requests/{request_id}/revisions`.
- `06_Workflows_and_State_Machines.md:553-655` defines the state machine the revisions move
  through.
- `02_Domain_Model_and_Business_Rules.md` **never uses the word "revision"** — not once in
  1,500 lines. Its section 6.14, Outgoing Payment Request
  (`02_Domain_Model_and_Business_Rules.md:850-907`), lists `amount_irr`,
  `entered_amount_value`, `entered_amount_unit`, `beneficiary_name_snapshot`,
  `beneficiary_iban_snapshot`, `beneficiary_national_id_snapshot`, `description` and
  `source_attachment_id` as **key fields of the request itself**.

Document 04's `payment_requests` (`04_Database_Schema.md:824-850`) carries none of those.
Its comment says it
plainly: "Stable logical request aggregate."

So the two documents disagree about something load-bearing. In document 02, a correction
edits the request's own amount and snapshots. In document 04, the request never holds them
and a correction writes a new immutable row. **Document 02's field list does not merely
omit the revision — it makes the revision unnecessary**, and building it would make the
milestone's central property, immutability, unreachable: there would be nothing immutable
to compare against.

**Resolution this plan proposes, for owner approval:** document 04's split is the
representation. The precedence order puts database integrity above the domain guide, and
here it also agrees with the milestone authority, the API specification, the workflow
document and the Definition of Done, all of which are written in terms of revisions.

What is owed is therefore larger than adding a missing entity to a catalogue: document
02's `6.14` must **move** eight key fields onto a new revision entity, keeping only the
aggregate's own columns. That is a substantive documentation correction and it should be
reviewed as one. Owner: Domain Lead + Documentation Owner. Blocking: M5 schema; M6, which
allocates attempts against revisions.

I am recording this as a proposed resolution rather than implementing it quietly because
the two readings produce different databases, and the difference is not visible in a
migration diff once it is written.

## 2.3 DOC-CONFLICT-011 — beneficiaries stay trader-owned

The PRD permits "a possible authorized center policy for controlled beneficiary sharing";
document 02 states a beneficiary may be reused only within the owning trader scope. The
register's interim rule already chooses: strict trader-owned isolation, and no cross-trader
reuse without a separate approved policy.

M5 implements the isolation and **does not build a sharing mechanism at all** — not even a
disabled one. A flag that would enable cross-trader beneficiary reuse is a flag somebody
turns on, and the failure mode is one trader paying money to another trader's beneficiary
because a screen offered it. `SEC-BEN-002` asserts the absence.

## 2.4 The trader value sets, owed since M3

DOC-CONFLICT-024's structure was approved in M3 and its **values** were assigned to M5:
`traders.operational_status` and `traders.approval_status` ship with no value CHECK today,
recorded in `test_status_catalogue_drift.py`'s `DELIBERATELY_UNCONSTRAINED` with the
reason — document 06 has one five-state machine, document 04 splits it across two columns
whose values do not partition that set, and `blocked` against `suspended` and `approved`
against `active` are unresolved aliases the catalogue says must not be collapsed without
policy approval.

**M5 owes that decision**, and slice 1 is where it is made — with the same discipline M4
learned the hard way in slice 8: constraining a column to a set nobody has approved is how
an alias set quietly becomes canonical. The proposal goes to the owner in the plan's pull
request, and the CHECK lands only in the slice that records an approved answer.

If the owner has not answered by the time slice 1 is implemented, the columns stay
unconstrained and slice 1 ships the rest. A milestone must not invent a status vocabulary
to unblock itself.

## 2.5 Money: the server computes, and the client is never authoritative

`15_Agent_Implementation_Plan.md:798-802`: the request accepts an entered value with an
explicit `IRR` or `TOMAN` unit, the server computes and validates canonical IRR, the API
uses string integers, and there is no frontend-authoritative conversion.

`entered_amount_value` and `entered_amount_unit` are stored **alongside** `amount_irr`
rather than instead of it. A trader who typed `۵۰۰` تومان and a trader who typed `۵۰۰۰`
ریال submitted the same money and different intents, and a dispute six months later is
about what they typed. The canonical value is what the platform acts on; the entered pair
is what the person meant.

## 2.6 What M5 does not build

- **No manager approval at request level.** The DoD says so and slice 9 gates it.
- **No batching.** `eligible_for_batching` is where M5 stops; M6 allocates.
- **No result, publication, acknowledgement or dispute.** Those statuses exist in the
  catalogue and are reached in M8 and M9. M5 implements the transitions up to
  `eligible_for_batching` and `cancelled`, and refuses the rest — a state machine that
  accepts a transition nothing implements is a state machine that lies.
- **No beneficiary sharing** (§2.3).
- **No bulk draft commands.** `05_API_Specification.md:1057-1251` includes them; they are
  an efficiency feature over a workflow that does not exist yet, and building them beside
  the first single-request path would double the surface every guard has to cover.

---

# 3. Slices

Each slice is one pull request. `### What proves it` is the section the traceability gate
parses; every obligation named there must be discharged by a test in the same pull request.

## Slice 1 — The trader status values, and the beneficiary table

### Goal

Pay M3's debt and lay the first table. Nothing in M5 can be built on a trader whose status
vocabulary is undecided.

### What it changes

- `docs/governance/status_catalog.yaml`: the `trader` aggregate's values, **if the owner
  has approved them**. The proposal recorded in this plan's pull request maps document 06's
  five states onto the two columns and records `blocked` and `approved` as the two aliases
  that need a decision rather than a mapping.
- Migration: `beneficiaries` per `04_Database_Schema.md:491-528` — trader-scoped, with
  `normalized_iban` NOT NULL and the `^IR[0-9]{24}$` CHECK that `app/db/models/bank.py`
  records as the beneficiary form, and **no unique on IBAN or name**.
- `app/db/models/beneficiary.py`.
- The trader status CHECKs, only if §2.4's decision landed.

### What proves it

- `DB-BEN-001` — `beneficiaries` matches doc 04 column for column, and carries a NOT NULL
  `normalized_iban` with the Iranian IBAN CHECK.
- `DB-BEN-002` — **no unique constraint exists on beneficiary IBAN or name, anywhere.**
  `app/db/models/bank.py` already exports `IBAN_UNIQUE_IS_PERMITTED_ONLY_ON` so a test can
  assert the prohibition rather than trusting a comment: duplicates are legitimate — the
  same person may hold two accounts and two people may share a name — and the approved
  behaviour is to warn, never to auto-merge. A unique index turns a warning into a refusal
  at data entry.
- `DB-BEN-003` — a beneficiary belongs to exactly one trader, enforced by the foreign key,
  and there is no column, table or flag through which one could belong to two.
- `DB-TRADER-002` — either the trader status columns carry the approved value CHECK, or
  they carry none and `DELIBERATELY_UNCONSTRAINED` still records why. **Both are passing
  states; inventing a value set is not.** Guard-the-guard: the test fails if the catalogue
  entry and the schema disagree in either direction.

### Negative controls

Add a unique index on `normalized_iban`: `DB-BEN-002` must fail. Add a value to the trader
CHECK that the catalogue does not list: `DB-TRADER-002` must fail.

## Slice 2 — Beneficiaries, and the duplicate warning that does not block

### Goal

Create, list, deactivate and supersede a beneficiary — and warn on a duplicate without
refusing it.

### What it changes

- `app/commands/beneficiary.py`: create, deactivate, supersede.
- `app/api/v1/beneficiaries.py` per `05_API_Specification.md:929-960`.
- Duplicate detection: a normalised-IBAN match within the trader's own set returns a
  **warning in the response**, and the beneficiary is created.

### What proves it

- `SEC-BEN-001` — a trader sees and may use only their own beneficiaries. A beneficiary id
  belonging to another trader answers exactly as a missing one, the pattern M4 slice 5
  established: a `403` confirms the id is real.
- `SEC-BEN-002` — there is no mechanism for cross-trader reuse. Asserted over the command
  and route surface, not by a runtime denial: DOC-CONFLICT-011's rule is that the
  mechanism does not exist, and a disabled one is a mechanism.
- `SVC-BEN-001` — creating a beneficiary whose IBAN matches an existing one **succeeds**
  and returns a warning naming the match. `15_Agent_Implementation_Plan.md:801`: the
  duplicate warning does not auto-block unless an approved policy says so, and no policy
  does.
- `SVC-BEN-002` — deactivation supersedes rather than deletes: the row stays, and requests
  that already reference it keep resolving. `test_no_deletion_machinery.py` is the standing
  gate; this is the behavioural half.
- `SVC-BEN-003` — a beneficiary carries no amount field of any kind
  (`15_Agent_Implementation_Plan.md:751`), asserted over the model's columns.
- `AUD-BEN-001` — each command writes its catalogued audit action in the same transaction.

### Negative controls

Make the duplicate check refuse: `SVC-BEN-001` must fail. Add an `amount_irr` column to the
model: `SVC-BEN-003` must fail. Add a `shared_with_trader_id` column: `SEC-BEN-002` must
fail.

## Slice 3 — The request and its first immutable revision

### Goal

The aggregate, its schema, and draft creation — the two tables together, because a request
without a revision has no content and a revision without a request has no owner.

### What it changes

- Migration: `payment_requests` and `payment_request_revisions` per
  `04_Database_Schema.md:822-906`, including the **composite integrity** at `:1536-1567`:
  `(current_revision_id, id) REFERENCES payment_request_revisions (id, payment_request_id)`,
  deferrable — the same pattern `bank_profiles` proved, and for the same reason. A
  single-column foreign key would let a request point at another request's revision.
- `app/db/models/payment_request.py`.
- `app/commands/payment_request.py`: `create_draft`.
- Column-level UPDATE grant on `payment_request_revisions`: **none at all.** A revision is
  immutable in every column, which is stricter than `bank_profile_versions`, where `status`
  moves. A revision has no status; the request does.

### What proves it

- `DB-REQ-001` — `payment_requests` matches doc 04 column for column.
- `DB-REV-001` — `payment_request_revisions` matches doc 04, and every snapshot column is
  NOT NULL where doc 04 says so: a revision that could omit the beneficiary name is a
  revision that cannot answer what was submitted.
- `DB-REV-002` — the composite deferrable foreign key rejects a `current_revision_id`
  belonging to another request, and permits a request and its first revision to be inserted
  in one transaction.
- `DB-REV-003` — **no column of a revision may be updated**, asserted through the runtime
  role with direct SQL, one parametrised case per column. The pattern M2 used for bank
  versions; stricter here because the exemption does not exist.
- `CON-REQ-001` — `payment_requests.record_version` supports `If-Match`, and a stale value
  returns `412` rather than overwriting. `15_Agent_Implementation_Plan.md:812`.
- `SEC-REQ-001` — a pending or suspended trader cannot create a draft
  (`15_Agent_Implementation_Plan.md:806`). Both statuses, because they are different axes.

### Negative controls

Use a single-column foreign key for the pointer: `DB-REV-002` must fail. Grant UPDATE on
one revision column: `DB-REV-003` must fail.

## Slice 4 — Money: what was typed, and what it is worth

### Goal

The entered value and unit, the server's canonical IRR, and the refusal of anything that
does not agree.

### What it changes

- `app/commands/payment_request.py`: amount handling on draft creation and revision.
- The API takes `entered_amount_value` as a **string integer** and
  `entered_amount_unit` as `IRR` or `TOMAN`; the server computes `amount_irr`.

### What proves it

- `SVC-REQ-001` — `500` TOMAN and `5000` IRR both store `amount_irr = 5000`, and both keep
  the pair the trader typed. What they meant and what it is worth are different facts, and
  a dispute is about the first.
- `SVC-REQ-002` — an invalid unit is refused, and a client-supplied `amount_irr` that
  disagrees with the entered pair is refused rather than trusted.
  `15_Agent_Implementation_Plan.md:799, 802`.
- `API-REQ-001` — every amount crosses the API as a string integer, asserted over the
  response model and the published contract. A JSON number loses precision above 2^53 and
  IRR amounts reach it.
- `SVC-REQ-003` — no conversion factor is accepted from the client in any field.

### Negative controls

Accept a client `amount_irr`: `SVC-REQ-002` must fail. Emit an amount as a JSON number:
`API-REQ-001` must fail.

## Slice 5 — Correction creates a revision, and the previous one does not move

### Goal

`15_Agent_Implementation_Plan.md:809-810`: a material correction creates a new revision
and the prior revision remains unchanged.

### What it changes

- `app/commands/payment_request.py`: `create_revision`, moving `current_revision_id`.
- `content_hash` over the canonical revision content, through
  `app.core.hashing.unversioned_digest` — the same function M4 slice 8 learned is the one
  that fits a `CHAR(64)`.
- **What counts as material** is decided and recorded: any change to beneficiary, IBAN,
  amount, unit or attachment. A description-only edit is still a new revision, because the
  description is submitted intent and a reviewer read it.

### What proves it

- `SVC-REV-001` — a correction creates revision *n+1*, moves the pointer, and leaves
  revision *n* byte-identical including its `content_hash`.
- `SVC-REV-002` — the history is readable in order and every revision is reachable, so
  "what did they submit the first time" is answerable after three corrections.
- `SVC-REV-003` — a correction whose content is byte-identical to the current revision is
  **refused**, and `content_hash` is what detects it.

  **This obligation is the reverse of what this plan first stated**, corrected in slice 3.
  The original text said identical content must be permitted, on the grounds that "a
  resubmission that changes nothing is a real thing a person does, and refusing it would be
  a uniqueness rule nobody asked for". Somebody did ask for it:
  `04_Database_Schema.md:901` states `UNIQUE(payment_request_id, content_hash)`. The plan
  cited the table's line range and did not read its constraints, which is the same failure
  as citing a line without reading it.

  And the document is right. A trader who was asked to correct something and resubmits it
  unchanged has not corrected it; storing a second identical revision would add a row that
  means nothing and put it in front of a reviewer as though it were new work. The correct
  answer is to refuse the correction and say why. Repeated *requests* are a different
  question, and `SVC-REV-004`'s idempotency key is what answers it.
- `CON-REQ-002` — creating a revision requires `If-Match` on the request, and a stale one
  returns `412`.
- `SVC-REV-004` — revision creation is idempotent under a repeated `Idempotency-Key`:
  one revision, not two. `15_Agent_Implementation_Plan.md:813`.

### Negative controls

Mutate the previous revision's `content_hash` on correction: `SVC-REV-001` must fail. Drop
the idempotency claim: `SVC-REV-004` must fail.

## Slice 6 — Submission, and the snapshots that make it evidence

### Goal

Submit a draft, and freeze what was submitted.

### What it changes

- `app/commands/payment_request.py`: `submit`, `draft → submitted_to_center`.
- The revision's snapshot columns are filled **when the revision is written**, not by
  reference and **not at submission**.

  **This sentence is corrected from the original, which said "at submission time".** That
  is not implementable and the reason is the milestone's own central property: a revision
  cannot be updated, so submission has nothing to fill. Filling it would mean submission
  creates a revision — and for a draft-then-submit with no edits in between, that second
  revision would be byte-identical to the first and
  `UNIQUE(payment_request_id, content_hash)` would refuse it. So the trader would be
  unable to submit an unmodified draft.

  The snapshot is therefore taken by `create_draft` and `create_revision`, which is where
  content is stated, and submission verifies it is complete rather than writing it. A
  trader who edits a beneficiary and wants the new details submitted files a correction,
  which re-snapshots — and that is the correct behaviour rather than a workaround: the
  reviewer must see the values the trader last stated, not values that changed underneath
  the request after they stated them.
- The attachment is a `file_object`. M4 **already registered** the resolver:
  `app/files/ownership.py:130` maps `payment_request_source` to `uploader_or_internal`,
  "staff, plus the trader who uploaded this exact file". So M5 adds nothing here — it
  becomes the first caller with a real request behind it, and the slice's job is to check
  that the rule M4 wrote is the rule a submitted request needs.
- One question that check must answer, because the answer is not obviously yes: the
  resolver grants on **uploader identity**, not on the request's `trader_id`. Those are the
  same person today. They stop being the same person the moment an admin uploads on a
  trader's behalf, which M5 does not build but the request table already anticipates with
  `created_by_admin_user_id`. If the resolver is to stay identity-based, that is a decision
  and it belongs in this slice's PR rather than in whichever later milestone trips over it.

### What proves it

- `SVC-SUB-001` — the submitted revision carries a **complete** snapshot: every column
  document 04 marks required is populated and matches the beneficiary as it stood when the
  revision was written. Submission verifies this rather than filling it, for the reason
  recorded above, and refuses to submit a revision whose snapshot is incomplete — a
  request that reaches a reviewer without a beneficiary name is one nobody can act on.
- `SVC-SUB-002` — **editing the beneficiary afterwards does not change the submitted
  revision.** `15_Agent_Implementation_Plan.md:808`: beneficiary history is not mutated by
  later edits. This is the test that makes a revision evidence rather than a view.
- `SEC-REQ-002` — a pending or suspended trader cannot submit, and a trader cannot submit
  another trader's request.
- `SVC-SUB-003` — an attachment that is not `available` cannot be submitted with a
  request. M4's file states carry the meaning; this is the first consumer to enforce it.
- `AUD-REQ-001` — submission writes its audit row and its outbox event in the command's
  transaction.

### Negative controls

Store a beneficiary reference instead of the snapshot: `SVC-SUB-002` must fail. Permit a
quarantined attachment: `SVC-SUB-003` must fail.

## Slice 7 — Accountant review, and the return for correction

### Goal

The centre's half of the journey: review, return, and mark eligible.

### What it changes

- `app/commands/payment_request.py`: `begin_review`, `return_for_correction`,
  `mark_eligible_for_batching`. The catalogued command ids are
  `payment_request.start_review`, `.request_correction` and `.mark_eligible`
  (`command_catalog.yaml`), and those are what the idempotency records and audit rows
  carry; the function names are internal.
- Transitions per `06_Workflows_and_State_Machines.md:579-607` and its transition table
  at `:635-652`, and **only** those:
  - `submitted_to_center → under_accountant_review` (start review)
  - `submitted_to_center → needs_trader_correction` **and**
    `under_accountant_review → needs_trader_correction` (request correction). The arrow
    from `submitted_to_center` was missing from this plan's first draft; `:586` and the
    table row at `:643` ("submitted/review") both state it, and `SVC-REVIEW-001`
    enumerates from the document, so omitting it here would have failed the gate rather
    than shipped quietly.
  - `under_accountant_review → eligible_for_batching` (mark eligible)
- Cancellation widens per `06_Workflows_and_State_Machines.md:1363-1375` (§29.1), which is
  the authority the §13.2 diagram is silent about — it declares `cancelled` as a state and
  draws no arrow into it. Within the states M5 reaches: `draft` (trader, no reason
  required), `submitted_to_center` and `needs_trader_correction` (trader or internal, reason
  required), `under_accountant_review` (**internal only**, reason required),
  `eligible_for_batching` (internal or trader, reason required). Slice 3 wrote
  `CANCELLABLE = (DRAFT,)` and said slice 7 owned the rest; it also cited the review
  workflow for that, which is wrong — §29.1 is where the rule lives.
- Request bodies per `05_API_Specification.md:1189-1226`: start review takes none;
  request correction takes `reason_code`, `message_to_trader`, `internal_note`, with the
  first two required; mark eligible takes `review_note` and `expected_revision_id`.

### What proves it

- `SVC-REVIEW-001` — each transition is permitted only from its stated predecessor, and
  every other pairing is refused. Enumerated from the state machine rather than listed, so
  a transition added to the document without an implementation is visible.
- `SVC-REVIEW-002` — a returned request goes back to the trader, who creates a new revision
  and resubmits; the request returns to `under_accountant_review` and the history holds
  both revisions.
- `SEC-REQ-003` — a trader cannot perform any accountant action, and an accountant cannot
  act on a request outside their scope.
- `AUD-REQ-002` — every accountant action writes its catalogued audit row in the same
  transaction as the state change, and the correction request also publishes
  `PaymentRequestCorrectionRequested` to the outbox in that transaction.
  `15_Agent_Implementation_Plan.md:814` reads "accountant action is audited and emitted
  through outbox", and this obligation first said *every* accountant action is emitted.
  That is more than the governance artifacts allow me to build.
  `audit_outbox_catalog.yaml` enumerates the outbox events, and the only accountant one is
  `PaymentRequestCorrectionRequested`; `command_catalog.yaml` accordingly carries
  `outbox_event: null` for start review and mark eligible. Those nulls are not an
  oversight: the same catalogue's `m0_open_items` says the mapping is "every catalogued
  critical command to exactly one audit action and **zero or more** outbox events", so a
  command with no event is anticipated, and a separate open item asks the owner to approve
  whether event names stay PascalCase or move to a versioned dotted convention. Inventing
  `PaymentRequestReviewStarted` and `PaymentRequestMarkedEligible` would decide that naming
  question on the owner's behalf and add two names to an enumeration whose approval is
  pending. So the narrow reading is implemented and the tension is recorded here rather
  than in `CONFLICT_REGISTER.md`: "zero or more" reconciles the two documents, which is
  what keeps this a note and not a conflict.
- `SVC-REVIEW-003` — cancellation is permitted from exactly the states
  `06_Workflows_and_State_Machines.md:1367-1375` (§29.1) lists, with its actor and reason
  rules, restricted to the states M5 reaches; every other state is refused, and a cancelled
  request accepts no further transition. Enumerated from §29.1 rather than listed, for the
  same reason as `SVC-REVIEW-001`. Not from the §13.2 diagram: it declares `cancelled` and
  draws no arrow into it, so a test built from the diagram would prove cancellation is
  never permitted at all.

### Recorded gap — command idempotency on the transition routes

`command_catalog.yaml` marks `payment_request.submit`, `.cancel`, `.start_review`,
`.request_correction` and `.mark_eligible` all `idempotency: required`, and none of the five
implements it. Only `POST /revisions` takes an `Idempotency-Key`. This is stated here
because I checked rather than assumed: there is no entry for it in `RECORDED_GAPS`, and
nothing in slice 6 recorded it when `submit` shipped the same way.

Why it is a gap and not a defect, and why it is nevertheless the owner's call: each of the
five is a state transition guarded by its origin, so a replay is already refused — a second
`submit` on a `submitted_to_center` request answers `400`, not a second submission. The
commands that genuinely need a key are the ones that *create* — a draft and a revision — and
both have one. So the catalogue's blanket "required" reads as over-broad for transitions
rather than as five missing implementations.

What a key would still buy is the *answer*: a client whose connection dropped mid-submit
cannot tell "my request went through" from "the request was already submitted by someone
else", because both are `400`. That is a real scenario on a mobile network and the reason
not to close this silently.

### Negative controls

Permit `submitted_to_center → eligible_for_batching` directly: `SVC-REVIEW-001` must fail.
Emit the outbox event outside the transaction: `AUD-REQ-002` must fail.

## Slice 8 — The screens both actors need

### Goal

`21_UI_Design_System_and_Screen_Specification.md:1162-1255` and `:1391-1451`. The trader
creates and corrects; the accountant reviews and returns.

### What it changes

**The two read endpoints, which this plan assumed existed and which nothing has built.**
The published contract carries eleven `payment-requests` operations and exactly one of them
reads: `GET /{request_id}/revisions`. Slices 3 to 7 built the writes. So a trader cannot
list their own requests, and an accountant has no review queue at all — no way to learn what
is waiting for them. Document 05 defines both:

- `GET /api/v1/payment-requests` (`05_API_Specification.md:1061-1075`) — eleven filters, and
  "Trader scope is always inferred". M5 implements `status` and the trader scope; the filters
  that name attempts, disputes or bank profiles have nothing to filter on yet.
- `GET /api/v1/payment-requests/{request_id}` (`:1125-1131`) — "current revision, aggregate
  state, attempts, current publication summary, warnings, record version, and allowed
  actions". Attempts arrive in M6 and publications in M8, so they are absent here rather
  than empty; `allowed_actions` is the interesting one, below.

They are built **in this slice rather than a slice of their own**, and that is the decision
rather than a convenience. An endpoint whose only consumer does not exist yet is this
repository's most repeated defect — five instances in M3, and `app/core/money.py` was the
fifth. The screens are the consumers. Building the two together with them is what makes
either provable.

- Trader: beneficiary list and form, request list, request draft, correction screen with the
  reviewer's note.
- Admin: review queue, request detail with revision history, return-for-correction and
  mark-eligible actions.
- Both wired into navigation, with pages that exist.

**`allowed_actions` comes from the server, computed from the same tables the commands
guard with.** Not a second list: `REVIEW_TRANSITIONS`, `CORRECTABLE` and `CANCELLABLE`
already declare every transition and who may make it, so the field is derived from them and
a screen that hides a button is showing what the server said rather than guessing. This is
`test_navigation_is_not_a_control.py`'s rule applied to buttons — the backend stays
authoritative, and the 403 remains the thing that actually refuses.

### What proves it

- `UI-REQ-001` — the correction screen shows the reviewer's note. A request returned
  without the reason visible is a request the trader resubmits unchanged.
- `UI-REQ-002` — the revision history shows every revision, and the current one is
  distinguishable from its predecessors.
- `UI-REQ-003` — the amount is entered with an explicit unit and no conversion happens in
  the browser. `15_Agent_Implementation_Plan.md:802`.
- `UI-REQ-004` — every navigation item added has a page, and every screen has an importer
  that is a route. The M3 and M4 lesson, applied again because it has been needed in every
  milestone so far. The first half is already gated by each app's `navigation.test.ts`; the
  second half is new, and it is the same defect from the other end — a screen nothing routes
  to is a screen nobody can reach.
- `API-REQ-002` — the list is scoped by the caller: a trader sees only their own requests,
  whatever they ask for, and an internal caller with `payment_request.read` sees the centre's
  queue. A trader who passes `trader_id` for somebody else gets their own rows, not a refusal
  and not the other trader's — "Trader scope is always inferred" (`:1075`) means inferred, not
  validated.
- `API-REQ-003` — the detail carries the current revision, the record version, and
  `allowed_actions` derived from the command tables rather than restated. An action the
  tables permit and the response omits, or the reverse, fails: the field is a projection of
  the guards, and a projection that disagrees with what it projects is worse than no field.

### Negative controls

Convert TOMAN to IRR in the component: `UI-REQ-003` must fail. Add a navigation item with
no page: `UI-REQ-004` must fail. Drop the trader scope from the list query: `API-REQ-002`
must fail. Add an action to `allowed_actions` that no table permits: `API-REQ-003` must fail.

## Slice 9 — The Definition of Done gate

### Goal

The journey, end to end, and the absence the DoD names.

### What it changes

- `tests/integration/test_m5_definition_of_done.py`.
- `tests/backend/test_m5_definition_of_done.py` for the structural half.

### What proves it

- `TRACE-DOD-007` — **the journey runs**: a trader submits, an accountant returns it for
  correction, the trader creates a new immutable revision and resubmits, and the request
  reaches `eligible_for_batching`. One test, six steps, through the API as both actors.
  Six steps proved separately can all pass while the sequence is impossible.
- `TRACE-DOD-008` — **no manager approval exists at request level.** No request-scoped
  route requires a manager-only permission and no request command consults one, derived
  from the route table and the role matrix rather than listed. Batch approval is a
  manager's job from M6, so this rule will be pressed against with real motivation.
- `TRACE-DOD-009` — every status the request aggregate can reach in M5 is one the approved
  catalogue lists, and every M5 transition is one document 06 states. A state machine that
  accepts a transition nothing implements is a state machine that lies.
- `TRACE-M5-001` — `PENDING` contains no M5 obligation.

### Negative controls

Add a manager permission to any request route: `TRACE-DOD-008` must fail. Remove a step
from the journey test: the derivation must report it rather than run one fewer case — the
mistake M4 slice 11 made and had to correct.

---

# 4. Landing mechanics

The traceability gate requires every obligation this plan states to be cited by a test,
recorded in `RECORDED_GAPS`, or listed in `PENDING` with the slice that owes it. This plan
states **43**, and its own pull request adds every one to `PENDING`. Each slice removes its
own. Nothing goes to `RECORDED_GAPS`: M5 builds its own tables, so no undecided ADR or
unwritten parser stands between any obligation and a test that could prove it.

Two rules learned in M4, restated because they cost time there:

- Every prefix must already be in `PREFIXES` in `tests/backend/test_traceability.py`. This
  plan uses `DB`, `SVC`, `API`, `SEC`, `AUD`, `CON`, `UI` and `TRACE`, all of which are.
- No identifier may collide with one an earlier plan states. `DB-REQ`, `DB-REV`, `DB-BEN`,
  `SVC-REQ`, `SVC-REV`, `SVC-SUB`, `SVC-REVIEW`, `SVC-BEN`, `API-REQ`, `SEC-REQ`,
  `SEC-BEN`, `AUD-REQ`, `AUD-BEN`, `CON-REQ`, `UI-REQ` and the `TRACE-DOD` numbers from 007
  onward are all free as of this revision.

Registering them found a defect in M4's own gate, fixed in this pull request.
`test_nothing_is_owed_for_m4` decided which obligations were M4's by matching a prefix
list that ended in `TRACE-` — so the moment this plan claimed the next `TRACE-DOD` numbers,
a merged milestone's completion gate reported them as its own outstanding work. It now asks
the M4 plan which obligations M4 states, via a new `obligations_stated_by(plan)` helper. A
prefix was standing in for a rule and stopped agreeing with it as soon as a second
milestone reached for the same family of names.

The correction had a second edge worth recording, because it is the failure this ledger
exists to catch and it happened while fixing the ledger. The first version of that comment
spelled one of the new identifiers out. The scanner treats any mention in a test file as a
citation, so an M4 test discharged an M5 obligation from inside a comment explaining the
bug — and `test_no_pending_obligation_is_already_covered` caught it. A mention is not a
proof, for the fifth time in this programme.

Three conflicts need an owner decision before or during M5: **DOC-CONFLICT-005** (§2.2,
needed before slice 3), **DOC-CONFLICT-024's values** (§2.4, needed before slice 1's CHECK
— slice 1 ships without it if the answer has not arrived), and **DOC-CONFLICT-011** (§2.3,
already has a workable interim rule and needs confirmation rather than a decision).
