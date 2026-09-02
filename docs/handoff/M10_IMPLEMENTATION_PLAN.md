# M10 — Gold Sale, Incoming Payment, Statement Import, and Dispatch

The other direction of the business. M1–M9 built the outgoing path — a trader's money leaving the
centre for a beneficiary. This one is the trader **buying gold**: money coming in, verified against
a bank statement the centre imports itself, and gold leaving. `15_Agent_Implementation_Plan.md:1206`.

## Where every section cited below lives

The prose says `§18 :1225`; this table is what makes that checkable. Each source is cited once here
rather than at every mention.

**Short forms: `§18` is document 15's M10 section, `doc 04` the schema, `doc 05` the API
specification, `doc 06` the workflows document, `doc 12` the security document.**

| Cited as | Full citation | What it specifies |
|---|---|---|
| §18 `:1208` | `15_Agent_Implementation_Plan.md:1208` | the milestone's goal |
| §18 `:1212` | `15_Agent_Implementation_Plan.md:1212` | the twelve required capabilities |
| §18 `:1227` | `15_Agent_Implementation_Plan.md:1227` | the six statement-import rules |
| §18 `:1236` | `15_Agent_Implementation_Plan.md:1236` | the dispatch guard, in one sentence |
| §18 `:1240` | `15_Agent_Implementation_Plan.md:1240` | the seven tests and the gate |
| §18 `:1250` | `15_Agent_Implementation_Plan.md:1250` | the Definition of Done |
| doc 04 `:686` | `04_Database_Schema.md:686` | `gold_sale_orders`, and its nineteen statuses |
| doc 04 `:720` | `04_Database_Schema.md:720` | `gold_sale_pricing_versions`, immutable |
| doc 04 `:733` | `04_Database_Schema.md:733` | `incoming_payment_receipts` |
| doc 04 `:758` | `04_Database_Schema.md:758` | `bank_statement_files` |
| doc 04 `:764` | `04_Database_Schema.md:764` | `bank_statement_import_runs`, one per parse |
| doc 04 `:776` | `04_Database_Schema.md:776` | `bank_statement_rows`, immutable within a run |
| doc 04 `:793` | `04_Database_Schema.md:793` | **no polymorphic match fields**, in two sentences |
| doc 04 `:798` | `04_Database_Schema.md:798` | `incoming_payment_matches` |
| doc 04 `:812` | `04_Database_Schema.md:812` | `gold_dispatches` and its four types |
| doc 04 `:818` | `04_Database_Schema.md:818` | no completion without the guard or an audited override |
| doc 05 `:1948` | `05_API_Specification.md:1948` | the eight gold-sale endpoints |
| doc 05 `:1971` | `05_API_Specification.md:1971` | create a pricing version |
| doc 05 `:1981` | `05_API_Specification.md:1981` | upload an incoming payment receipt |
| doc 05 `:1990` | `05_API_Specification.md:1990` | statement upload and import runs |
| doc 05 `:2002` | `05_API_Specification.md:2002` | match a receipt to a statement row |
| doc 05 `:2011` | `05_API_Specification.md:2011` | confirm an incoming payment |
| doc 05 `:2025` | `05_API_Specification.md:2025` | partial and excess are never silently full |
| doc 05 `:2029` | `05_API_Specification.md:2029` | dispatch or settlement |
| doc 06 `:451` | `06_Workflows_and_State_Machines.md:451` | the statement-import workflow: file states, run states, five rules |
| doc 08 `:435` | `08_Bank_File_and_Result_Processing.md:435` | **§8, incoming bank statement processing** — the detailed specification |
| doc 08 `:1601` | `08_Bank_File_and_Result_Processing.md:1601` | §26.2's ten statement-import test cases |

**Documents 06 and 08 were added on 2026-09-02, at the start of slice 3, and the omission is
recorded rather than quietly repaired.** The plan as merged cited neither, and document 08 §8 is
the detailed specification for slices 3, 4 and 5 — twelve sections of it. Section 6 below says
what that changed. This is the third time in two milestones that reading a citation before
writing against it found the specification the plan had missed; it is cheap and it keeps working.

---

# 1. What is different about this milestone

**M10's governance is thin, and the M9 plan's opening standard must not be carried over.** M9 began
by saying every name it needed was already approved, and therefore "a slice that finds itself
wanting to invent a name has drifted". That was true of M9 and is false here. Surveyed before this
plan was written:

| Governance artifact | M10 coverage, **as re-surveyed 2026-09-02** |
|---|---|
| `permission_catalog.yaml` | seventeen mentions — the best-covered of the four |
| `status_catalog.yaml` | **seven** aggregates: `gold_sale_order`, `incoming_payment_receipt`, `gold_dispatch`, `bank_statement_file`, `bank_statement_import_run`, `incoming_match_candidate`, `incoming_confirmed_match`. Only `bank_statement_rows` has none |
| `audit_outbox_catalog.yaml` | **four** actions — `gold_sale.dispatched`, `incoming_payment.confirmed`, `bank_statement.import_run_created`, `bank_statement.import_run_confirmed` — against §18 `:1212`'s twelve capabilities |
| `command_catalog.yaml` | six mentions, against eight endpoints in doc 05 `:1948` alone |

**The first survey was wrong, and this is the corrected one.** It reported three status aggregates
and two audit actions; there are seven and four. What it missed is exactly the statement-import
half of the milestone — the two aggregates and the two actions that slices 3, 4 and 5 need. The
error had one cause: the survey searched for `bank_statement_row` and `incoming_payment_match`,
the *table* names, and the catalogues name aggregates after the business object rather than the
table (`bank_statement_import_run`, `incoming_confirmed_match`). A count of absences is worth no
more than the search that produced it, and this one set each slice's naming rule.

The consequence for slice 3 is not small: **it was expected to need declared names and it needs
almost none.** Its statuses, its permissions and its import-run audit action are all approved
already. Compare M9, where the same expectation was correct.

So M10 is still shaped like **M8** rather than M9 — the gold-sale half genuinely has nothing, and
slices 1 and 2 shipped four declared names between them. The rule stands:

> An M10 slice that needs a name no catalogue carries must **declare it**, against the nearest
> approved identifier, with the reason recorded in `app/audit/registry.py` and a DOC-CONFLICT-052
> instance in the register. It must not quietly invent one, and it must not stop.

**One table has no status aggregate at all** — `bank_statement_rows`, slice 4's — which matters
more than it sounds: `test_status_catalogue_drift.py` holds every enforced CHECK to its catalogued
aggregate exactly, and for a column with no aggregate it can hold it to nothing. It needs a
`LOCAL_LIFECYCLES` entry with its reasoning, the shape M8's `bank_result_bundle_batch_links` and
M9's `payment_result_publications` both used. The other two the first survey named do not: they
are catalogued, and a `LOCAL_LIFECYCLES` entry for a catalogued aggregate would be a local copy
that drifts from the thing it duplicates.

---

# 2. What already exists, and what that removes from this milestone

Four of M10's dependencies were built by earlier milestones, and one of them was built badly enough
that this milestone has to notice.

- **The bank profile, its versions and its mappings exist** (M2). `bank_statement_import_runs`
  takes a `bank_mapping_id`, and doc 04 `:764` makes the mapping the thing a parse is done
  *against* — so a statement import is the first real consumer of M2's mapping work, three
  milestones after it was written.
- **`RECORDED_GAPS` carries `BANK-VER-005`, and its text was corrected at M8's close** precisely
  because a statement *parser* had been confused with M8's evidence *renderer*. That entry names no
  milestone now. **M10 is the milestone that can close it**, and the plan should say so rather than
  leaving the register to be read hopefully.

  **Narrowed 2026-09-02, at slice 3, by the traceability gate.** Slice 3 named the id in a test
  docstring and `test_no_recorded_gap_is_actually_covered` failed — correctly. The gap is document
  08 §6.4's *activation* rule: "Activation requires validation against representative anonymized
  fixtures", meaning a bank version may not become active until its mappings are shown to parse
  real files. Slice 3 checks something adjacent and different — that a mapping and the statement it
  is asked to parse name the same bank version, at import time. Both matter and neither is the
  other.

  So closing `BANK-VER-005` needs three things, and this plan should stop implying one slice
  supplies them: a deterministic parser (slice 4), a set of approved anonymized fixtures (nobody's
  yet — the owner's, since they must come from a real bank file), and the parser wired into
  `bank_profile_version` activation (M2's surface, not M10's). **The honest statement is that M10
  builds the parser the gap has been waiting for and does not by itself discharge the gap.** The
  slice that changes that must remove the `RECORDED_GAPS` entry in the same commit, which is what
  the entry already says.
- **`file_purpose_catalog.yaml` already has `bank_statement` and `incoming_payment_receipt`**, both
  approved, and `gold_dispatch_evidence` besides. Unlike M9 slice 5B, M10 needs **no new file
  purpose** — the three it wants are in document 05's seven.
- **`manual_review_tasks` exists** (M8) and M9 taught it `entity_record_version` and a fifth entity
  type. §18 `:1227`'s "duplicate fingerprints create warnings/tasks" and doc 05 `:2025`'s review
  tasks both land in it. Expect to add entity types for the new aggregates, by the rule M9 slice 6
  used: the list is M8's own and its stated test is "a table that exists".
- **`notifications` exists** (M9 slice 7) with a projection reading three event types. A trader
  whose gold is dispatched should be told, and that is one entry in `HANDLED_EVENTS` rather than a
  new mechanism.

---

# 3. The slices

Eight, ordered so that each is demonstrable alone and none depends on a later one. The ordering
follows the money: an order exists, it acquires a price, a trader claims to have paid, the centre
imports the bank's own record, the two are matched, the payment is confirmed, and only then does
gold move.

**The dispatch guard is deliberately last**, and §18 `:1236` is why: "Gold cannot be dispatched
unless the approved payment/settlement condition is satisfied." A guard written before the thing it
guards is a guard whose input does not exist — which this repository has shipped sixteen times and
should not ship a seventeenth.

## Slice 1 — `gold_sale_orders` and `gold_sale_pricing_versions`

### Goal

An order a trader can place, and an immutable price snapshot the centre sets.

### What it changes

- Both tables (doc 04 `:686`, `:720`), with `UNIQUE(gold_sale_order_id, version_number)` and the
  `expected_amount_irr > 0` CHECKs.
- Create, submit and read (doc 05 `:1948`), and create-pricing-version (doc 05 `:1971`).

**The pricing table is M5's revision pattern again**, and the plan should reuse it rather than
rediscover it: an immutable snapshot with a `content_hash`, a monotonic `version_number`, and a
pointer on the mutable aggregate updated in the same transaction. `payment_request_revisions` is
the model, including that a revision carries no `record_version` because nothing may change it.

### What proves it

- `DB-GOLDSALE-001` — the unique per order, and a pricing row refused when its amount is not
  positive.
- `SVC-PRICING-001` — updating a price **creates a new row and repoints
  `current_pricing_version_id` in one transaction** (doc 04 `:731`). Asserted by reading the old row
  back unchanged, the M6 supersession pattern.
- `SVC-PRICING-002` — `content_hash` is canonical, computed with `unversioned_digest`, and every
  numeric in it is an integer or a string. `parameters_hash` refuses floats and a gold *weight* is
  the first quantity in this system that is not a whole number of rials — so the hash input must
  carry it as a string, and the column as `NUMERIC`.

**`gold_weight` is the first non-integer quantity this system stores.** Every amount so far has been
`BigInteger` rials. Weight is decimal, and `MONEY_TIME_CONTRACT.md` governs money rather than mass —
so the plan must decide the column type and the hashing spelling explicitly rather than letting a
float in through the side door. That is G-1 below.

## Slice 2 — `incoming_payment_receipts`

### Goal

A trader says they have paid, and attaches evidence.

### What it changes

- The table (doc 04 `:733`) and the upload route (doc 05 `:1981`).
- The receipt uses the approved `incoming_payment_receipt` file purpose — already
  `trader_visible_after_publication` and already in document 05's seven.

### What proves it

- `SEC-RECEIPT-001` — a trader may attach only their **own** file to their **own** order, and a
  second trader gets 404 rather than 403. M9 slice 6's rule, one aggregate along.
- `SVC-RECEIPT-001` — a claim is not a payment. Uploading a receipt moves the order to
  `payment_evidence_submitted` and **changes no confirmed amount**, which is the same negative
  property M9 asserted four times: the human action that looks like it should move money must not.

**As built**, three things are worth carrying to slice 6.

**The two amounts are two columns and the test reads both.** `amount_irr` is claimed,
`confirmed_amount_irr` is verified, and the three sharpest controls each collapse them in a way
that looks helpful — fill the confirmation from the claim, mark the order confirmed, or create the
receipt as `confirmed`. All three are the mistake somebody makes when the two facts look like one.

**An accountant cannot claim on a trader's behalf**, and it is a 403 rather than a convenience.
"The centre says the trader paid" is a different assertion from "the trader says so", and the audit
row is where that difference has to survive.

**Two owner checks, deliberately.** The route's `require_owned` and the command's own
`trader_id` comparison; a control removing only the first went NOT CAUGHT because the second
answered. Defence in depth rather than a hole — the command's comment says why it re-checks — and
the control now removes both.

## Slice 3 — `bank_statement_files` and the import run

**Rewritten 2026-09-02 against doc 06 `:451` and doc 08 `:435`, which the merged plan did not
cite.** What follows replaces a section written from doc 04 and §18 alone.

### Goal

The centre's own copy of what the bank says happened, imported as a versioned run.

### The statuses are catalogued, and they are document 06's, not document 08's

This is the finding that shapes the slice. Document 08 §8.3 lists **nine** import-run states
(`draft`, `queued`, `parsing`, `preview_ready`, `partial_preview`, `parse_failed`, `confirmed`,
`rejected`, `superseded`) and document 06 §10.2 lists **five** (`queued`, `running`, `succeeded`,
`failed`, `cancelled`). They are not the same lifecycle and neither is a superset.

`status_catalog.yaml` has already ruled on this, and the entry is worth quoting because it is the
slice's design:

> Document 06 models technical execution states. Document 08 defines a richer preview/confirmation
> lifecycle and is intentionally not silently collapsed.

The five document-06 states are canonical, `parsing` and `parse_failed` are recorded as *aliases*
of `running` and `failed`, and the remaining six document-08 states sit in `unresolved_aliases`
with `canonical: null` and this note: *"M0 must choose a two-axis model or extend the canonical
lifecycle."*

So the CHECK this slice writes carries the **five canonical states**, and the human confirmation
§18 `:1232` requires ("human confirmation is required") is **not a status value in this slice**.
Two reasons, and the second is the stronger:

- Using `preview_ready` or `confirmed` as a status would enforce a value M0 has explicitly not
  approved, and `test_status_catalogue_drift.py` would fail — correctly.
- A `review_status` column added here would be a column nothing writes. That is the defect this
  project has shipped five times and named: complete machinery with no caller. Confirmation
  belongs to the slice where rows exist to confirm, because "confirmed rows become available for
  matching" (doc 08 §8.2) is a statement about rows.

`bank_statement_file` is catalogued too — `uploaded`, `parsed`, `parse_failed`,
`ready_for_matching`, `archived` — and doc 06 `:451` draws the transitions, including
`parse_failed → parsed` when a later run succeeds. This slice writes `uploaded` and nothing else,
for the same reason: no parse exists yet to move it.

### What it changes

- Both tables (doc 04 `:758`, `:764`) with `UNIQUE(bank_statement_file_id, run_number)`.
- Upload and create-import-run (doc 05 `:1990`), plus the two reads §21.4 lists.
- `bank_statement.create_import_run` is **catalogued** (`command_catalog.yaml`, audit action
  `bank_statement.import_run_created`, `outbox_event: null`, `idempotency: required`). The upload
  is not, and is the one declared name this slice needs.

### The guards, which come from document 08 §8.1–8.2 and are new to this plan

A run is parsed "with exact BankProfileVersion and BankMapping" (§8.2), from ".xlsx for approved
bank mappings" (§8.1), against "a selected destination center account". That is four guards the
earlier section did not have:

1. the mapping must be **approved** — an unapproved draft mapping is not a parser;
2. the mapping must belong to **the file's own** bank-profile version — a mapping from another
   bank's version parsing this file is precisely the mismatch `BANK-VER-005` is about;
3. the destination account must be a **centre incoming account** (`account_role` in
   `incoming_destination`, `both` — M2's approved set);
4. the file must not be archived.

A fifth is the implementation's own and is recorded as such: **no second run may start while one
is `queued` or `running`.** Nothing in either document forbids it, but two concurrent parses of
one file produce two row sets and nothing in Phase 1A says which is authoritative. A reparse after
one finishes is the specified workflow and is unaffected.

### What proves it

- `DB-IMPORT-001` — the unique per file, and a second run getting `run_number` 2.
- `SVC-IMPORT-001` — **a reparse creates a new run and does not touch the old one** (§18 `:1227`,
  doc 04 `:774`, doc 06 `:471`, doc 08 `:463`). **Split, and the split is recorded:** at the *run*
  level here — run 1's `status`, `row_count`, `parser_version`, `source_hash` and `finished_at`
  read back unchanged after run 2 exists — and at the *row* level in slice 4, which is where rows
  exist. §18 `:1241`'s "reparse does not overwrite prior rows" is not fully closed until then, and
  the DoD slice must not record it as closed here. The plan anticipated this split at §5.
- `TRACE-IMPORT-001` — the run records `parser_version` and `source_hash`, so a row can be told
  apart from one produced by a later parser against the same file. M8's `renderer_version`
  precedent, and the same argument.
- `SEC-IMPORT-001` — **new.** The four guards above, each refused independently.

## Slice 4 — `bank_statement_rows`

### Goal

Immutable parsed rows, with both what the bank wrote and what the platform made of it.

### What it changes

- The table (doc 04 `:776`), both indexes, and `UNIQUE(bank_statement_import_run_id, row_number)`.
- **No `matched_entity_type`, no `matched_entity_id`, no `is_matched`.** Doc 04 `:793` refuses all
  three in two sentences: "Do not store generic `matched_entity_type/id` or a mutable `is_matched`
  flag as the source of truth. Match state is derived from dedicated match records."

### What proves it

- `DB-ROW-001` — the columns doc 04 names and, asserted as an **absence**, the three it forbids.
  A scan over the model, because the failure mode is somebody adding a convenient flag later and
  every behavioural test still passing.
- `SVC-ROW-001` — raw **and** normalized values are both retained (§18 `:1227`). A row whose raw
  date was discarded cannot be re-normalised when the mapping is corrected.
- `SVC-FINGERPRINT-001` — `row_fingerprint` is canonical, and a duplicate creates a **task**
  rather than a refusal (§18 `:1227`). A bank statement legitimately contains two identical
  transfers; the fingerprint says "look at this", not "this is wrong".

**Split at build time into 4 and 4B**, by §5's rule that a slice splits when its parts have
different blockers. Slice 4 computes, stores and indexes the fingerprint; slice 4B is what looks at
it, and it needed values on two M0-owned lists that slice 4 did not.

## Slice 4B — duplicate detection, and the task a warning becomes

### Goal

`SVC-FINGERPRINT-001`. Document 08 §8.7 in nine lines, the last of which governs the rest:
**"A warning does not automatically delete or merge data."**

### What it changes

- No new table. `20260908_0039` widens two CHECKs on `manual_review_tasks`.
- **Three of §8.7's five signals**, and the two omissions are recorded rather than left implicit:
  *same bank account and statement period* is skipped because the period is optional operator
  input and a signal that fires on `NULL = NULL` never fires; *same timestamp, amount and
  description* is already covered by the fingerprint wherever a timestamp exists.
- Two entity types added by the list's own stated rule — they are tables that exist, which is how
  M9 slice 6 added `payment_result_publication`.
- **One task type declared**, and it is the first value `TASK_TYPES` has ever gained. None of its
  four describes a statement row suspected of being a duplicate, and the nearest —
  `payment_result_discrepancy` — is about an *outgoing* payment's result. Reusing it would file an
  incoming-statement question in the queue an accountant filters for payment results, which breaks
  the one thing that list exists for. Recorded as a name M0 owes.

### The property the whole detector is shaped around

**A reparse is not a duplicate of itself.** Document 08 §8.2 makes reprocessing the *specified*
workflow, so run 2 of a file produces the same fingerprints as run 1 every single time. A detector
comparing against every earlier row would flag every reparse completely — the documented workflow
reporting itself as an error — and an accountant who sees that twice learns to ignore the warning,
which is worse than not having one. Rows of other runs of the **same statement file** are therefore
excluded, and the overlapping-period case across two different files is not.

### What proves it

Eight integration tests, and two of them are there to keep the other six honest: a clean statement
must produce no flag, no task and an empty signal list, and a repeated *unreadable* row must stay
`invalid` rather than becoming `possible_duplicate` — §22.2's "never partially hide invalid rows"
applied to the detector itself.

This closes two of §26.2's ten statement-import cases: **duplicate file checksum** and **duplicate
normalized rows**. Two more — *partial preview confirmation* and *rejected import run* — remain
blocked on the two-axis status decision G-4 records as M0's.

## Slice 5 — `incoming_payment_matches`

### Goal

The relationship between a trader's claim and the bank's record, as its own row.

### What it changes

- The table (doc 04 `:798`), `UNIQUE(incoming_payment_receipt_id, bank_statement_row_id)`, and the
  score CHECK.
- Propose and reject (doc 05 `:2002`).

**This is M9 slice 1 and 2 again, and the plan should say so.** A match is a *candidate*; confirming
it is a separate act with its own permission — the wall between suggestion and truth that
`matching_candidates` and `confirmed_evidence_links` already draw for the outgoing direction.

**Doc 04 `:809` leaves the cardinality open on purpose**: "Use partial unique rules only if the
business confirms strict one-row/one-receipt matching. The baseline supports traceable
partial/combined payment cases." So the baseline is **many-to-many**, and a partial unique index
would be a business decision this milestone must not take. G-2.

### What proves it

- `DB-MATCH-001` — the plain unique refuses the same pair twice, and **no** partial unique
  constrains the rest, asserted as an absence with the reason cited.
- `CON-MATCH-001` — two accountants proposing the same pair concurrently: one wins, on the unique
  rather than on a read-then-insert.

## Slice 6 — confirming an incoming payment

### Goal

A person decides the money arrived, and the order's state says exactly what arrived.

### What it changes

- Confirm (doc 05 `:2011`), with `Idempotency-Key` and `If-Match`.
- The order aggregate's recalculation across **multiple** receipts.

### What proves it

- `SVC-INCOMING-001` — **multiple receipts and partial incoming payments aggregate
  correctly** (§18 `:1240`). The paid sum is computed from confirmed matches, never cached on the
  order — `04_Database_Schema.md:469` forbids a second copy of a balance, and M9 slice 4 already
  refused a cached total for the outgoing direction.
- `SVC-INCOMING-002` — **partial and excess are never silently full** (doc 05 `:2025`).
  Under-payment moves the order to `incoming_payment_partially_confirmed`; over-payment opens a
  review task and refuses, which is M9's overpayment shape exactly — including that the task must
  commit even though the command refuses.
- `AUD-INCOMING-001` — `incoming_payment.confirmed`, one of only two M10 actions the catalogue
  carries.

## Slice 7 — dispatch, settlement, and the guard

### Goal

Gold moves, and only when it may.

### What it changes

- `gold_dispatches` (doc 04 `:812`) with its four `dispatch_type` values, and the route at doc 05
  `:2029`.
- The guard (§18 `:1236`, doc 04 `:818`).

### What proves it

- `SEC-DISPATCH-001` — **an unauthorized warehouse user cannot bypass the dispatch guard** (§18
  `:1240`). The sharp negative: somebody who may *record* a dispatch and may not *authorise an
  override*.
- `SVC-DISPATCH-001` — no dispatch completes unless the payment condition holds **or** an override
  is recorded with a reason and an audit row (doc 04 `:818`). Both branches tested, and the override
  asserted to be impossible without the reason.
- `SVC-SETTLEMENT-001` — **offset settlement is distinct from physical receipt** (§18 `:1240`).
  Four types exist and two of them move no metal; a test that treated them alike would pass against
  an implementation that dispatched gold for an offset.

## Slice 8 — correction, the trader surface, and the Definition of Done

### Goal

History survives a correction, the trader can see and acknowledge, and the chain is traceable.

### What it changes

- Correction paths that preserve prior pricing, payment and dispatch history (§18 `:1240`).
- The trader's read and acknowledgement, and one entry in M9's notification projection.

### What proves it

- `SVC-GOLDCORRECT-001` — **corrections preserve prior pricing/payment/dispatch history**. Every
  column of the superseded rows read back through `row_to_json`, the M9 slice 7B pattern.
- `TRACE-M10-001` — the Definition of Done (§18 `:1250`): an order can be **priced, paid or
  settled, verified, dispatched and closed**, walked in SQL for one order so that each hop resolves.

---

# 4. Decisions this plan takes, and questions it does not

## G-1 — gold weight is the first non-integer quantity in this system

Every amount M1–M9 stores is `BigInteger` rials, and `app/core/hashing.py` **refuses a float
outright** because "0.1 + 0.2 does not equal 0.3, so two amounts a human calls equal produce
different digests". `gold_weight` is decimal by nature, and doc 05 `:2035` shows it as the string
`"125.500000"`.

**Taken:** `NUMERIC` in the column, `Decimal` in Python, and **a string in every hash input** — the
spelling document 05 already uses. `MONEY_TIME_CONTRACT.md` governs rials and says nothing about
mass, so this is an implementer's decision made explicitly rather than a policy borrowed by
analogy. The owner owes nothing here; it is recorded because a float reaching `parameters_hash`
would be caught by a gate and this says why it never should.

## G-2 — match cardinality is the business's, and the baseline is many-to-many

Doc 04 `:809`: "Use partial unique rules only if the business confirms strict one-row/one-receipt
matching. The baseline supports traceable partial/combined payment cases."

**Not taken.** The plain `UNIQUE(receipt, row)` ships; no partial unique does. One bank transfer
legitimately settles two receipts, and one receipt is legitimately settled by two transfers — a
constraint forbidding either would make a real case unrecordable, and unrecordable cases are what
produce spreadsheets beside the system. **The owner owes the decision**, and if they confirm strict
matching, one partial unique index and one test change.

## G-3 — ten of twelve capabilities have no catalogued audit action

`audit_outbox_catalog.yaml` names `gold_sale.dispatched` and `incoming_payment.confirmed`, and
nothing for ordering, pricing, receipt upload, statement upload, import runs, matching, rejection,
settlement, correction or closure.

**Taken, as M8 took it:** each is declared `catalogued=False` in `app/audit/registry.py` with a
written reason and implemented against the nearest approved permission, and each is a
DOC-CONFLICT-052 instance. **This is expected to be the largest block of them in the project so
far**, and the plan says so in advance so that a reviewer reads them as recorded rather than as
drift. M0 owes the names.

## G-4 — `BANK-VER-005` is M10's to close, and its scope needs stating

The register's entry now names no milestone, having been corrected at M8's close when a statement
*parser* was confused with an evidence *renderer*. Slice 3 builds the parser.

**Superseded 2026-09-02 — the documents answer most of this, and the plan's position was wrong.**

What this said: that doc 04 `:764` leaves `status` unenumerated, that a run either completes or
fails, that "a partial run is not a state", and that partial runs would be the owner's call.

Three of the four are contradicted by documents the merged plan did not cite:

- **`status` is enumerated, twice.** Doc 06 §10.2 gives five states and doc 08 §8.3 gives nine;
  `status_catalog.yaml` already canonicalises the first set and records the second as unresolved.
  Nothing here was open.
- **A partial run is a state.** Doc 08 §8.3 names `partial_preview`, §8.6 says "Partial import
  requires explicit confirmation and an audit note", and §26.2 lists "partial blank template rows"
  and "partial preview confirmation" among its ten statement-import test cases. Whether the
  platform supports partial imports is not a question; only *where the state lives* is.
- **A mapping mismatch has a specified report.** §22.2: preserve the original file, preserve the
  import-run errors, allow a new import run after mapping correction, **never partially hide
  invalid rows**, keep the manual workflow available. That is `error_summary`'s contract.

**What remains genuinely open, and it is narrower and sharper.** `status_catalog.yaml`'s own note:
*"M0 must choose a two-axis model or extend the canonical lifecycle."* Document 06's five states
describe a parser running; document 08's six extra describe an accountant reviewing what it
produced. Both are needed and they are not one column. The decision is which:

- **a second column** — `status` stays document 06's, a review column carries document 08's six; or
- **one extended lifecycle** — M0 approves nine canonical states and document 06's five become a
  subset.

**Taken, for slice 3, on the narrowest possible reading:** the CHECK carries the five canonical
states and this slice adds no review column, because it has nothing to review — see the slice. The
choice above is still M0's, and it must be made before slice 4 confirms a run. Recording it as an
owner debt rather than choosing it in a migration is the point; a two-axis model invented in
`alembic/` is a schema decision wearing a governance decision's clothes.

---

# 5. What this plan carries forward

The M9 lessons that apply here specifically, rather than the whole list.

- **A gate whose input is incomplete passes.** Every list parsed from a document is checked
  non-empty first, and every fixture is checked to contain the thing its assertion looks for — M9
  slice 7 shipped a test whose event payload made it unable to fail.
- **NOT CAUGHT has four meanings, and one is "the gate does not exist".** Three times in M9 a
  failed sabotage found an absent test rather than a broken pattern. Record which meaning applied;
  a control quietly rewritten loses the finding.
- **A failing pre-existing gate is a finding.** Twice in M9 an old gate's citation led to the real
  specification — once to eight publication guards the plan had never cited. Read the citation
  before editing the assertion.
- **Prohibition scans over source are AST walks, never substring searches.** Nine times in this
  project a scan has matched the prose written to justify it.
- **Enforcement by absence beats enforcement by branch.** No grant, no field, no route — M9 used
  all three, and each is stronger than a check somebody can delete.
- **A slice splits when its parts have different blockers.** M9 grew from seven slices to ten that
  way. Expect the same here; slice 3 and slice 4 in particular may separate if the parser's
  dependencies are not settled when it is reached.

---

# 6. Documents 06 and 08, added at slice 3

The merged plan cited neither, and both specify the statement-import half of the milestone. What
they changed, so a reader of slices 4 through 8 does not rediscover it:

| Section | What it settles | Whose slice |
|---|---|---|
| doc 06 `:451` §10.1–10.3 | the canonical file and run state machines, and five import rules | 3 |
| doc 08 §8.1 | the supported input, and what an upload must select | 3 |
| doc 08 §8.2 | the workflow, ending "confirmed rows become available for matching" | 4, 5 |
| doc 08 §8.3 | the nine review states — unresolved against document 06's five | 3, and M0's |
| doc 08 §8.4 | the canonical parsed row, field by field, and "missing fields must not be guessed" | 4 |
| doc 08 §8.5 | six normalization rules, including "do not silently convert debit to credit" | 4 |
| doc 08 §8.6 | the five row states and "partial import requires explicit confirmation and an audit note" | 4 |
| doc 08 §8.7 | five duplicate-detection signals, and "a warning does not automatically delete or merge" | 4, 5 |
| doc 08 §8.8 | six requirements of a confirmed incoming match | 5, 6 |
| doc 08 §8.9 | eight incoming edge cases the workflow must support | 5, 6 |
| doc 08 §22.2 | what an import failure must preserve | 3, 4 |
| doc 08 §26.2 | ten statement-import test cases, by name | 3, 4 |

**Two of these change a later slice materially, and they are flagged here rather than left to be
found:**

- **Slice 5 gains a precondition it did not have.** Doc 08 §8.2: only rows from a *confirmed* run
  become available for matching. The plan's slice 5 lets a match name any statement row. That is a
  guard, and by this project's own count the sixteenth mechanism whose input would otherwise be
  ungoverned.
- **Slice 4's row states are catalogued nowhere and document 08 names five of them** (`valid`,
  `warning`, `invalid`, `ignored_empty`, `possible_duplicate`). That is the `LOCAL_LIFECYCLES`
  entry §1 now points at, and its reasoning is written: the states exist in an approved document
  and no catalogue aggregate carries them.

§26.2's ten cases are the closest thing this milestone has to an acceptance list for the parser,
and slices 3 and 4 should be able to name which of the ten each of their tests covers.
