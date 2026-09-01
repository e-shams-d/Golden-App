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

---

# 1. What is different about this milestone

**M10's governance is thin, and the M9 plan's opening standard must not be carried over.** M9 began
by saying every name it needed was already approved, and therefore "a slice that finds itself
wanting to invent a name has drifted". That was true of M9 and is false here. Surveyed before this
plan was written:

| Governance artifact | M10 coverage |
|---|---|
| `permission_catalog.yaml` | seventeen mentions — the best-covered of the four |
| `status_catalog.yaml` | three aggregates: `gold_sale_order`, `incoming_payment_receipt`, `gold_dispatch`. **None** for import runs, statement rows or matches |
| `audit_outbox_catalog.yaml` | **two** actions — `gold_sale.dispatched`, `incoming_payment.confirmed` — against §18 `:1212`'s twelve capabilities |
| `command_catalog.yaml` | six mentions, against eight endpoints in doc 05 `:1948` alone |

So M10 is shaped like **M8**, which shipped seven `catalogued=False` names with a written reason
apiece, rather than like M9, which shipped one. The rule this plan sets for itself is therefore the
M8 rule and not the M9 one:

> An M10 slice that needs a name no catalogue carries must **declare it**, against the nearest
> approved identifier, with the reason recorded in `app/audit/registry.py` and a DOC-CONFLICT-052
> instance in the register. It must not quietly invent one, and it must not stop.

**Three tables have no status aggregate at all**, which matters more than it sounds:
`test_status_catalogue_drift.py` holds every enforced CHECK to its catalogued aggregate exactly,
and for a column with no aggregate it can hold it to nothing. Each of those three needs a
`LOCAL_LIFECYCLES` entry with its reasoning — the shape M8's `bank_result_bundle_batch_links` and
M9's `payment_result_publications` both used.

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
  milestone now. **M10 is the milestone that closes it**, and the plan should say so rather than
  leaving the register to be read hopefully.
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

### Goal

The centre's own copy of what the bank says happened, imported as a versioned run.

### What it changes

- Both tables (doc 04 `:758`, `:764`) with `UNIQUE(bank_statement_file_id, run_number)`.
- Upload and start-import (doc 05 `:1990`), the second as a `processing_jobs` job — M8's crop is
  the precedent for a long parse that must not run inside a request.

### What proves it

- `DB-IMPORT-001` — the unique per file, and a second run getting `run_number` 2.
- `SVC-IMPORT-001` — **a reparse creates a new run and does not touch the old one** (§18 `:1227`,
  doc 04 `:774`). Run 1's rows are read back byte-for-byte after run 2 completes. This is §18
  `:1240`'s "reparse does not overwrite prior rows" and it is the slice's whole point.
- `TRACE-IMPORT-001` — the run records `parser_version` and `source_hash`, so a row can be told
  apart from one produced by a later parser against the same file. M8's `renderer_version`
  precedent, and the same argument.

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

**Not fully taken.** What "the mappings fit a file" means operationally — how a mapping mismatch is
reported, and whether a run may partially succeed — is a product decision doc 04 `:764` leaves to
`status` and `error_summary` without enumerating either. The plan's position is that a run either
completes or fails with a summary, and a partial run is not a state; if the owner wants partial
runs, that is a status value and a set of tests.

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
