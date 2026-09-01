# M9 — Matching Candidates, Confirmed Evidence, Payment Results, and Publication

Turn bank-returned evidence into a financial result, and that result into an immutable
trader-visible publication — through **separated human decisions**, none of which is allowed to
imply the next. `15_Agent_Implementation_Plan.md:1085`.

## Where every section cited below lives

The prose says `§17 :1120`; this table is what makes that checkable. Each source is cited once
here rather than at every mention.

**Short forms: `§17` is document 15's M9 section, `doc 04` the schema, `doc 05` the API
specification, `doc 06` the workflows document, `doc 08` the bank-file document.**

| Cited as | Full citation | What it specifies |
|---|---|---|
| §17 `:1089` | `15_Agent_Implementation_Plan.md:1089` | the milestone's goal |
| §17 `:1093` | `15_Agent_Implementation_Plan.md:1093` | the four candidate actions |
| §17 `:1102` | `15_Agent_Implementation_Plan.md:1102` | acceptance does not change financial status |
| §17 `:1106` | `15_Agent_Implementation_Plan.md:1106` | `ConfirmedEvidenceLink`'s six requirements |
| §17 `:1115` | `15_Agent_Implementation_Plan.md:1115` | default cardinality, all three rules |
| §17 `:1121` | `15_Agent_Implementation_Plan.md:1121` | the five payment-result commands |
| §17 `:1131` | `15_Agent_Implementation_Plan.md:1131` | the seven paid-confirmation validations |
| §17 `:1141` | `15_Agent_Implementation_Plan.md:1141` | request aggregate recalculation |
| §17 `:1153` | `15_Agent_Implementation_Plan.md:1153` | publication contents, all ten fields |
| §17 `:1165` | `15_Agent_Implementation_Plan.md:1165` | the four trader actions |
| §17 `:1172` | `15_Agent_Implementation_Plan.md:1172` | the eight steps of a correction |
| §17 `:1185` | `15_Agent_Implementation_Plan.md:1185` | the ten tests and the gate |
| §17 `:1200` | `15_Agent_Implementation_Plan.md:1200` | the Definition of Done |
| doc 04 `:915` | `04_Database_Schema.md:915` | `payment_attempts` columns, including every result column |
| doc 04 `:961` | `04_Database_Schema.md:961` | the cross-row invariant, in four lines |
| doc 04 `:1133` | `04_Database_Schema.md:1133` | `payment_result_publications` |
| doc 04 `:1154` | `04_Database_Schema.md:1154` | its three uniques, one of them partial |
| doc 04 `:1162` | `04_Database_Schema.md:1162` | what a correction does, in one sentence |
| doc 04 `:1261` | `04_Database_Schema.md:1261` | `matching_candidates` |
| doc 04 `:1274` | `04_Database_Schema.md:1274` | acceptance is not confirmation |
| doc 04 `:1276` | `04_Database_Schema.md:1276` | `confirmed_evidence_links`, column by column |
| doc 04 `:1297` | `04_Database_Schema.md:1297` | the two partial unique indexes |
| doc 04 `:1306` | `04_Database_Schema.md:1306` | replacement never deletes |
| doc 04 `:1334` | `04_Database_Schema.md:1334` | `notifications` |
| doc 04 `:1606` | `04_Database_Schema.md:1606` | overpayment creates a reconciliation task |
| doc 05 `:1564` | `05_API_Specification.md:1564` | confirm-paid, request and eight rules |
| doc 05 `:1594` | `05_API_Specification.md:1594` | confirm-failed |
| doc 05 `:1800` | `05_API_Specification.md:1800` | the three candidate endpoints |
| doc 05 `:1824` | `05_API_Specification.md:1824` | create evidence link |
| doc 05 `:1844` | `05_API_Specification.md:1844` | replace |
| doc 05 `:1860` | `05_API_Specification.md:1860` | void |
| doc 05 `:1869` | `05_API_Specification.md:1869` | a segment is not independently published |
| doc 05 `:1874` | `05_API_Specification.md:1874` | publication preview and publish |
| doc 05 `:1905` | `05_API_Specification.md:1905` | the publication reads |
| doc 05 `:1921` | `05_API_Specification.md:1921` | acknowledge |
| doc 05 `:1942` | `05_API_Specification.md:1942` | dispute, and what it does *not* do |
| doc 06 `:600` | `06_Workflows_and_State_Machines.md:600` | the only arrow into publication |
| doc 06 `:1066` | `06_Workflows_and_State_Machines.md:1066` | a segment becomes `published` |
| doc 08 `:1307` | `08_Bank_File_and_Result_Processing.md:1307` | §19.3, the eight publication guards |

---

# 1. What is different about this milestone

**Governance is complete before the code, for the first time in this project.** Every previous
milestone opened with a survey of what the catalogues did not yet say, and M8 shipped **seven**
audit actions marked `catalogued=False` with a written reason apiece —
`LINK_BANK_RESULT_BUNDLE_TO_BATCH`, `ATTACH_EXTERNAL_EVIDENCE`, and all five review-task names.
M9 opens with none of that:

| Governance artifact | M9 coverage |
|---|---|
| `permission_catalog.yaml` | all sixteen M9 permissions approved and seeded by `20260801_0008` |
| `status_catalog.yaml` | `matching_candidate`, `confirmed_evidence_link`, `payment_result_publication` — every state, with sources |
| `audit_outbox_catalog.yaml` | eleven M9 audit actions named, and five outbox events |
| `command_catalog.yaml` | rows for confirm-paid, confirm-failed, candidate acceptance, all three evidence-link commands, and publish |

**This changes how the slices should be judged.** For M8 the recurring question was "which
identifier may an implementer invent"; here the answer is *none*, and any name this milestone
needs that the catalogues do not already carry is a signal that the slice has drifted, not a
licence to add one. The first gate of every M9 slice is that its audit action, its status value
and its permission all come from a catalogue file unchanged.

**The one exception is recorded below as G-1**, and it is a conflict the catalogue already knows
about rather than an omission.

---

# 2. What already exists, and what that removes from this milestone

A survey, because three of M9's dependencies were built by earlier milestones and one of them was
built *for* M9 specifically.

- **`payment_attempts` already carries every result column.** `bank_tracking_number`,
  `bank_result_at`, `failure_code`, `failure_reason`, `confirmed_by_admin_user_id` and
  `confirmed_at` were created by M6 against doc 04 `:915` and have sat unwritten since. So the
  attempt half of M9 is a **grant** and a command, not a schema change — the migration adds
  column-level UPDATE and nothing else. This is worth stating because the natural first move is to
  add columns that are already there.
- **`manual_review_tasks` exists, and M8 built it for this.** Doc 04 `:1606`: "Greater-than-request
  paid sum creates a reconciliation task and blocks normal closure." Overpayment is therefore
  **not** a request status — the request statuses in `status_catalog.yaml` contain no
  `reconciliation_required` — it is a queue item, and the queue is M7's G-10 debt that M8 paid.
  The first time in this project that a milestone's dependency was ready before the milestone.
- **The outbox exists**, with `PaymentAttemptPaid`, `PaymentAttemptFailed`, `EvidenceLinkReplaced`,
  `PaymentResultPublicationCreated` and `TraderResultCorrected` already named. §17 `:1185`'s test
  "notification failure does not roll back committed financial state" is a claim about the pattern
  M2 built, applied to five new event types.
- **The renderer exists.** `app/exports/crop.py` and the `files` queue render a rectangle to an
  image deterministically; the publication's `share_file_id` is the same shape of problem, and
  M8's `renderer_version` precedent applies to it directly.
- **`notifications` (doc 04 `:1334`) does not exist.** It is the only table M9 needs that no
  earlier milestone built and that this plan does not open with. See G-2.

---

# 3. The slices

Seven, ordered so that each one is demonstrable on its own and none depends on a later one. The
ordering follows the causal chain in the Definition of Done — publication → confirmed result →
confirmed evidence → bank-result source — built in the opposite direction, from the source
outwards.

Each slice is one pull request. `### What proves it` is the section the traceability gate parses,
so an obligation that is not listed there is one nothing can be traced to.

## Slice 1 — `matching_candidates`, and the wall between suggestion and truth

### Goal

A suggestion can be recorded, accepted and rejected, and none of those touches money.

### What it changes

- `matching_candidates` (doc 04 `:1261`), with `UNIQUE(receipt_segment_id, payment_attempt_id,
  method)` and the score CHECK. Statuses from the catalogue: `proposed`,
  `accepted_for_confirmation`, `rejected`, `superseded`, `expired`.
- The three endpoints at doc 05 `:1800`: create, accept-for-confirmation, reject.
- UPDATE granted on `status` and `resolved_at` only. A candidate's segment, attempt, method and
  score are what it *is*; one that could be re-pointed would let a rejected suggestion quietly
  become a different accepted one.
- **No grant of any kind on `payment_attempts`.** That absence is what makes the negative below
  structural rather than behavioural — slice 3 adds the grant, and until then "acceptance cannot
  mark paid" is enforced by PostgreSQL rather than by a code path nobody has deleted yet.

### What proves it

- `DB-CANDIDATE-001` — the table matches doc 04 `:1261`'s field list, its unique and its score
  CHECK, asserted against the migrated database rather than against the model.
- `SVC-CANDIDATE-001` — **accepting a candidate does not mark paid**, the first of §17 `:1185`'s
  ten tests. Doc 04 `:1274` and §17 `:1102` both say it, which is worth taking seriously: two
  documents guarding one shortcut. The test is not "acceptance returns 200" — it reads the
  attempt's whole row through `row_to_json` before and after and asserts byte equality, the M5
  pattern, because `status`, `confirmed_at` and `confirmed_by_admin_user_id` are three separate
  ways for this to go wrong.
- `SVC-CANDIDATE-002` — rejection records its reason. Doc 05 `:1800`'s section requires one "when
  rejecting a high-confidence candidate or overriding a previously accepted candidate"; both
  cases are provoked separately, because a single test of one leaves the other unwritten.
- `SEC-CANDIDATE-001` — the runtime role holds no privilege on `payment_attempts` after this
  migration, read from `information_schema` as the runtime role rather than asserted about the
  migration text.
- `AUD-CANDIDATE-001` — acceptance writes `matching_candidate.accepted_for_confirmation`, the
  catalogued action, and rejection writes nothing the catalogue does not name.

## Slice 2 — `confirmed_evidence_links`: two partial uniques and an atomic replacement

### Goal

The authoritative segment-to-attempt relationship exists, is unique where §17 says it must be, and
is replaced without ever being lost.

### What it changes

- `confirmed_evidence_links` (doc 04 `:1276`) and the two partial unique indexes (doc 04 `:1297`).
- The three endpoints at doc 05 `:1824`, `:1844` and `:1860`.
- The status column stores `revoked`, not `voided` — see G-1.

### What proves it

- `DB-EVIDENCE-001` — both partial indexes exist with doc 04 `:1297`'s exact predicates. One
  active primary per attempt, one active primary target per segment; supplementary is deliberately
  unconstrained, which is §17 `:1115`'s third rule expressed as an absence.
- `CON-EVIDENCE-001` — **concurrent primary evidence creation is constrained** (§17 `:1185`). Two
  connections against a real PostgreSQL, both racing to create the primary link for one attempt,
  and exactly one commits. A single-threaded test proves the index exists, not that it constrains,
  which is the distinction `tests/integration/test_concurrency_primitives.py` was written around.
- `SVC-EVIDENCE-001` — **replacement is atomic** (§17 `:1185`), written as a failure injection:
  force the insert to fail and assert the old row is still `active`. A replacement that marks the
  old row first and then fails leaves an attempt with no primary evidence at all, and a
  happy-path test cannot see that ordering.
- `SVC-EVIDENCE-002` — a revoked link stores the canonical `revoked` while the route path stays
  `/void`, and the alias is refused at the boundary rather than translated.
- `AUD-EVIDENCE-001` — `evidence_link.confirmed`, `.replaced` and `.revoked`, and
  `EvidenceLinkReplaced` published by replacement **only**. Confirming and revoking publish
  nothing; that is the catalogue's answer rather than this plan's, and the test asserts the
  absence rather than trusting it.

## Slice 3 — confirm paid, confirm failed, and the seven validations

### Goal

The first slice that writes a financial fact, and the one where every guard has to be reachable.

### What it changes

- `confirm-paid` and `confirm-failed` (doc 05 `:1564`, `:1594`).
- **A grant, not a table.** Column-level UPDATE on `payment_attempts` for `status`,
  `bank_tracking_number`, `bank_result_at`, `failure_code`, `failure_reason`,
  `confirmed_by_admin_user_id`, `confirmed_at` and `record_version` — and nothing else. The
  snapshots stay unwritable, so a confirmation cannot restate what was sent.

§17 `:1131` lists seven validations. They are not interchangeable, and each needs its own
provocation:

| Validation | The failure it prevents |
|---|---|
| attempt was sent | marking paid something the bank never received |
| not cancelled/superseded | reviving an attempt a replacement retired |
| amount is exact | a partial payment recorded as full |
| evidence or approved exception exists | a paid result no one can trace to a source |
| no duplicate conflict remains | two attempts claiming one bank transaction |
| paid sum does not exceed requested | doc 04 `:961`'s reconciliation error |
| permission, version, idempotency | a retry that pays twice |

### What proves it

- `SVC-CONFIRM-001` — an attempt that was never sent is refused, and the refusal names the status.
- `SVC-CONFIRM-002` — a cancelled attempt and a superseded attempt are each refused, provoked
  separately: one status standing in for the other is how a two-case check passes with one branch.
- `SVC-CONFIRM-003` — an amount that differs from the attempt's `amount_irr` by one rial is
  refused. Exactness is `MONEY_TIME_CONTRACT.md`'s rule and a tolerance would be a decision nobody
  made.
- `SVC-CONFIRM-004` — with no `primary_evidence_link_id`, a reason is required and stored; with
  one, it must be `active` and point at **this** attempt. See G-3 for what is deliberately not
  built.
- `SVC-CONFIRM-005` — a second attempt claiming a bank tracking number already confirmed against
  another attempt is refused.
- `SVC-CONFIRM-006` — **duplicate paid confirmation is idempotent** (§17 `:1185`). The replay
  asserts the attempt's `record_version` did not move, not merely that the second call returned
  200 — an idempotent-looking route that re-applies its effect passes the weaker assertion.
- `SEC-CONFIRM-001` — the runtime role cannot UPDATE `amount_irr`, `beneficiary_iban_snapshot` or
  `bank_profile_version_id`, read as the runtime role.
- `AUD-CONFIRM-001` — `payment_attempt.paid_confirmed` and `.failed_confirmed`, with
  `PaymentAttemptPaid` and `PaymentAttemptFailed` on the outbox, in the same transaction as the
  status change.

**Every one of these seven must be shown reachable through the real routes before it is believed.**
G-5 built a guard that could not fire because an earlier status transition already forbade its
case, and a unit test would have passed it by constructing a state production cannot reach.

## Slice 3B — retry, which this plan first forgot

### Goal

An attempt that failed can be marked as needing a retry, and a retry attempt can be created from
it — the two of §17 `:1121`'s five payment-result commands this plan omitted.

**Recorded as a correction rather than folded into slice 3.** §17 `:1121` lists five commands; the
plan assigned two to slice 3 and one to slice 7 and never mentioned these. The word "retry"
appeared once in the whole document, in an unrelated table cell. Meanwhile
`permission_catalog.yaml` approves and seeds `payment_attempt.create_retry`,
`audit_outbox_catalog.yaml:45` names `payment_attempt.retry_created`, and doc 05 defines both
routes — an approved permission and a catalogued action with no slice that builds them, which is
this repository's most-repeated shape appearing one level up, in a plan rather than in code.

**Its own slice rather than slice 3's tail**, following M7's rule that a slice splits when its
parts have different dependencies. Marking retry-required is a status transition on a row that
already exists. Creating a retry *attempt* inserts a new `payment_attempts` row with
`retry_of_attempt_id`, a fresh `attempt_number`, and a relationship to batching that slice 3 needs
none of.

### What it changes

- `POST /payment-attempts/{attempt_id}/mark-retry-required` (doc 05 §17.4). "Reason required. This
  does not itself create or send a retry" — the same shape as slice 1's acceptance: the human
  action that looks as though it should move money must not.
- `POST /payment-attempts/{attempt_id}/retry` (doc 05 §17.5), which creates the new attempt.
- No new table and no new grant: `20260830_0030` already grants `status`, and `retry_of_attempt_id`
  is written at insert on the new row rather than updated on the old one.

### What proves it

- `SVC-RETRY-001` — marking retry-required moves the attempt's status and creates **no** new
  attempt, asserted by counting the request's attempts before and after. Doc 05 §17.4 says so in
  its own words, and it is the third time in this milestone that the interesting property is what
  a command does not do.
- `SVC-RETRY-002` — a retry attempt carries `retry_of_attempt_id` and the next `attempt_number`,
  and the original row is byte-identical afterwards except for its status. `uq_attempt_number_per_request`
  is what makes the numbering checkable rather than assumed.
- `AUD-RETRY-001` — `payment_attempt.retry_created`, the catalogued action, with no outbox event —
  which is what `audit_outbox_catalog.yaml` lists.

---

## Slice 4 — the request aggregate, recalculated under lock

### Goal

The request's paid state is a function of its attempts, computed exactly and without a race.

### What it changes

- Recalculation inside the confirm commands, under `lock_rows` in M2's global order.
- Overpayment opens a `manual_review_tasks` row and refuses the confirmation.

§17 `:1141` and doc 04 `:961`:

```text
paid_sum == request amount → paid
0 < paid_sum < request amount → partially_paid
paid_sum > request amount → reconciliation required and normal confirmation blocked
```

**The third line is not a status.** `status_catalog.yaml`'s `payment_request` aggregate has no
reconciliation state at all. Doc 04 `:1606` says what happens instead: a reconciliation **task**,
and normal closure blocked. The request keeps whatever status it had.

### What proves it

- `SVC-AGGREGATE-001` — exact equality gives `paid`, a short sum gives `partially_paid`, and the
  boundary is tested at one rial either side rather than with a comfortable margin.
- `SVC-AGGREGATE-002` — **overpayment is blocked** (§17 `:1185`) **and** a task is opened. Both
  halves in one test, because a block with no task is a silent refusal and a task with no block is
  worse. Its negative control removes the task creation and must fail.
- `CON-AGGREGATE-001` — two concurrent confirmations against one request do not both read a
  pre-payment sum. Doc 04 `:961` calls this "a cross-row invariant enforced in a locked service
  transaction", so the test is two connections, not two sequential calls.

## Slice 5 — `payment_result_publications`: immutable, hashed, one active

### Goal

A trader-visible snapshot that cannot be edited, cannot be duplicated, and contains only what §17
allows.

### What it changes

- `payment_result_publications` (doc 04 `:1133`) with all three uniques (doc 04 `:1154`), and
  **no `UPDATE` grant at all** — §11.9's word "immutable", made a privilege the runtime does not
  hold rather than a description of intent. Slice 7 brings `GRANT UPDATE (status)` with the
  correction that needs it.
- Preview and publish (doc 05 `:1874`).
- ~~The share file, rendered by the `files` queue with a recorded renderer version.~~ **Moved to
  slice 5B** — see below.

`UNIQUE(payment_request_id, content_hash)` is worth pausing on: it makes republishing an identical
snapshot impossible, which is what stops a correction that changed nothing from producing a
version N+1 that says the same thing.

**And that constraint decides the shape of the whole slice.** It can only ever refuse anything if
the digest covers content alone: put `published_at` into the hashed payload and every republication
is unique by its clock; put `publication_version` in and it is unique by its counter. Either way
the constraint stays in the schema, stays in every report, and never fires again. So §17 `:1153`'s
ten items are split — nine hashed in `summary_payload`, and the version, the actor and the time as
columns beside it. A trader still sees all ten because the API composes both halves.

**The preview is not a read.** `06_Workflows_and_State_Machines.md:600-601` draws exactly two
arrows into publication — `paid -> result_ready_for_trader: publication preview validated` and
`result_ready_for_trader -> result_published` — so the preview is the validation step, and
publishing without it is a transition the workflow document does not have. Not implementing it
would have left `result_ready_for_trader` a status nothing could reach.

### What proves it

- `DB-PUBLICATION-001` — the two uniques and the partial `uq_active_publication_per_request`, with
  a second `active` row for one request refused by the database.
- `SVC-PUBLICATION-001` — `content_hash` is canonical and stable across a re-render, computed with
  M6's `unversioned_digest`. Any numeric in the payload is an integer or a string, because
  `parameters_hash` refuses floats — the rule M8 slice 4 found the hard way.
- `SVC-PUBLICATION-002` — the hashed payload contains **no** key that changes on every publication,
  asserted as an AST scan over `_snapshot`'s returned dictionary. Paired with a live test that
  publishes an unchanged result twice and requires a 409: publishing once would pass against a
  hash that included the clock.
- `SVC-PUBLICATION-003` — neither request body carries a financial value, asserted over the models.
  Doc 05 §20.2: "The client cannot submit arbitrary financial summary values." Third use of
  enforcement-by-absence in this milestone, after the amount and the beneficiary.
- `SVC-PUBLICATION-004` — a publication is unreachable from `partially_paid` or `failed`, and
  unreachable without a preview. Both are transitions 13.2 does not draw.
- `SVC-PUBLICATION-005` — the two §19.3 guards that were nearly missed: the financial result is
  **human-confirmed**, checked against `confirmed_by_admin_user_id` rather than against the
  request's derived status, and the caller's **expected version** is valid, as `If-Match` against
  the request through a compare-and-swap.
- `SEC-PUBLICATION-002` — **no unresolved privacy warning exists** (doc 08 `:1314`, §16.5). The
  check is a version comparison, so a crop re-rendered after its review is unverified again with
  nothing to reset.
- `SEC-PUBLICATION-001` — **the full bundle never reaches trader APIs or files** (§17 `:1185`).
  Asserted as a scan over the whole trader surface, not over the publication endpoint alone,
  because the thing somebody adds under pressure gets added wherever it is convenient. §17
  `:1153`'s ten fields are the allowed set and the IBAN is masked **at write time**, so the full
  account number never enters a column retained for years. A segment with no crop is refused
  rather than degraded — the fallback is how a bundle would reach a trader.
- `AUD-PUBLICATION-002` — `payment_publication.created` and `PaymentResultPublicationCreated`, both
  catalogued. The audit row carries the hash and not the payload.

**The plan cited the wrong document for the guard list, and a gate found it.**
`08_Bank_File_and_Result_Processing.md` §19.3 is headed "Publication guards" and gives **eight**;
this plan cited §17 and doc 05 and none of them. Three had no implementation until M8's
`TestNothingCanPublish` failed — it had asserted "nothing publishes" because publication did not
exist, and slice 5 is the milestone that makes that assertion false. Following it to its source
produced the privacy guard, the human-confirmation guard and `If-Match`.

The privacy one is the sharpest: `privacy_verification` has existed since M8 with **no caller**,
its own docstring recording why — "publication is M9's, and a guard on a path that does not exist
would be untestable". Sixteenth instance of the mechanism-with-no-caller shape, and the first one
this project planned in advance and then nearly walked past.

**What this slice found that no gate had:** `receipt_segments.status = 'published'` was a value the
catalogue approved, the CHECK admitted, `RESOLVED_SEGMENT_STATUSES` counted, and **nothing wrote**.
`06_Workflows_and_State_Machines.md:1066` gives the arrow — `confirmed_linked --> published:
included in active publication` — and slice 2's own comment promised M9 would write it. A status
with no writer is the mechanism-with-no-caller defect in another costume; it is written here, and
asserted.

## Slice 5B — the share file

### Goal

The downloadable artifact §20.2's `include_share_file` asks for, and §17 `:1153` calls the "safe
evidence/share file".

**Split out of slice 5 because its inputs were not settled. Two of the three since have been —
by measurement, not by assumption**, and the correction is worth recording because the original
list overstated the blocker.

| Input | First assessment | What checking it found |
|---|---|---|
| RTL text shaping in the backend | missing | **Dissolved.** Pillow 12.3.0 in the frozen graph reports `raqm: True`, so `ImageDraw.text(..., direction="rtl", language="fa")` shapes Persian and applies bidi natively. **No new dependency.** |
| Which font, and vendored or fetched | undecided | **Decided by precedent.** `infra/scripts/refresh-webfont.sh` settled it for the two frontend apps and argues it at length: Vazirmatn, SIL OFL 1.1, **committed rather than installed**, because Iran cannot reach the font hosts and the image build has no registry. |
| A FreeType-readable copy of that font | looked like the one real blocker | **Resolved, from the asset the repo already vendors.** `Vazirmatn-Variable.woff2` was converted to `services/backend/app/exports/fonts/Vazirmatn-Regular.ttf` with a throwaway `uv run --with fonttools` — the tool is fetched for the run and is **not** a project dependency, which is the same shape as `refresh-webfont.sh`: a once-a-year human operation whose *output* is committed. Nothing was downloaded from a geo-blocked host; the font is the one already approved. |
| `file_purpose_catalog.yaml` has no publication share file | inventing one is drift | **Still blocked, and for a sharper reason than first recorded.** It is *not* the M0 checksum chain: that manifest hashes seventeen files and this catalogue is not among them. It is that the catalogue's seven purposes are `05_API_Specification.md:991-997` **verbatim**, and `FILE-PURPOSE-001` parses the specification and compares. Adding an eighth row was tried and the gate failed exactly as designed; the row was reverted. Amending the list means amending an approved API contract. |

**The font is instanced at `wght=400`, and that is the reproducibility decision.** A variable font
is many typefaces in one file; asking FreeType for "Vazirmatn" without naming an instance means the
default instance today and whatever the default becomes after an upgrade. `FILE-PUBLICATION-001`
cannot rest on that, so the weight is pinned in the committed artifact rather than at render time
— the same argument `app/exports/crop.py` makes for `RENDER_SCALE` being a constant.

**Shaping was verified rather than assumed**, and the first two attempts to verify it were wrong,
which is worth recording because both failures were the shapes this milestone kept meeting:

1. The canvas was 400px and the text 193px wide, anchored at x=380 — most of it rendered off the
   edge, giving 76 dark pixels and the conclusion "the font has no coverage". A check whose canvas
   cannot hold its subject is insensitive by construction.
2. Comparing `direction="rtl"` against `"ltr"` produced identical bytes, and that is *correct*: for
   a pure-Persian string the Unicode bidi algorithm orders it the same either way, so the base
   direction hint changes nothing. The sabotage did not break the property.

What actually proves shaping is contextual joining: `getlength("پپ")` is **34.7px** against
**49.0px** for two isolated glyphs, and `"پرداخت"` is **83.0px** against **97.2px** naive. Persian
letters connect, which is the thing a renderer without Raqm cannot do.

**Two routes existed and Route B was taken**, at a cost of one value in a tuple this repository
owns.

*Route A — an eighth upload purpose.* Amend `05_API_Specification.md:991-997`, then the catalogue,
then the inlined copy. Three gates keep them aligned, so the change is safe once made — but the
first step is editing an approved API contract, which is the owner's. **Tried and reverted:** the
catalogue row alone failed `FILE-PURPOSE-001`, exactly as designed.

*Route B — a derivation, which is what the platform already does for files it produces itself.*
`record_derivation` gives a derived file its **source's** category and visibility rather than a
purpose of its own, and M4's catalogue already describes this exact shape: of
`bank_result_bundle_source` it says "what a trader eventually sees is a crop derived from it (M8),
which is a different file with its own row". A share card built from the primary evidence crop
inherits `incoming_payment_receipt` — already
`visibility_scope: trader_visible_after_publication`, already approved — and needs **no new upload
purpose at all**. What it does need is a fourth value in `DERIVATION_TYPES`, which is
implementation-owned: doc 08 `:431` lists what a derivation *records* and enumerates no types.

**Route B was chosen.** It reuses the mechanism M8 built, keeps the trader-visible file
provenance-linked to the evidence it shows, and touches no approved document. Route A's only real
advantage is that a share card is conceptually its own kind of thing — a naming preference, not a
control.

### What it changes

- `app/exports/share_card.py` — pure rendering, `crop.py`'s separation and its discipline.
- `services/backend/app/exports/fonts/Vazirmatn-Regular.ttf` and its licence, converted from the
  `.woff2` the repository already vendors and **instanced at `wght=400`**.
- `SHARE_CARD` in `DERIVATION_TYPES`, and the card recorded through `record_derivation` so it
  inherits the crop's category and visibility.
- The card is rendered **before** the publication row is inserted, so `share_file_id` is set at
  insert. `20260831_0031` grants no UPDATE on that table, and a card attached afterwards would need
  a grant whose first other use is rewriting a publication's status outside a correction.
- Doc 05 §20.4's second route, which slice 6 deliberately left out while every `share_file_id` was
  null.

### What proves it

- `FILE-PUBLICATION-001` — two renders of one publication are byte-identical, and the card carries
  no PNG timestamp. Paired with controls that add one, swap the font for Pillow's bundled default,
  and drop the font instance from the provenance string.
- `FILE-PUBLICATION-002` — the derivation row names its source and its renderer version, and the
  trader download resolves ownership through the publication's **request**: a file id is the wrong
  thing to authorise against, because `file_objects` has no trader column.
- The font covers Persian **and joins it**: `getlength("پپ")` is 34.7px against 49.0px for two
  isolated glyphs. Coverage and shaping are different claims and only the second proves Raqm works.

**Two more negative controls went NOT CAUGHT, and one of them found a missing gate again.** The
control that made the renderer carry on without evidence failed nothing — because *nothing tested
it*: the refusal existed with a comment explaining itself and no test.
`test_a_crop_with_no_stored_bytes_refuses_the_publication` exists because of that control. The
other was the third meaning: removing one of two guards on a missing card left the second still
answering 404, which is defence in depth rather than a hole, so the control now removes the pair.

**A text scan matched its own justification, for the ninth time in this project.** The test that
forbids a system-font lookup searched the source for the matcher's name and found it in the
module's docstring explaining why it does not use one. Rewritten as an AST walk over called
function names.

`FILE-PUBLICATION-001` asks for byte-for-byte reproduction, which is why the font is a *committed,
version-pinned* asset rather than whatever the base image happens to ship: `fc-match ":lang=fa"` on
this machine returns DejaVu Sans, which has no Arabic script at all. A renderer that fell back to
the system font would produce boxes, and would produce *different* boxes on a different image.

Slice 5 therefore offers **no way to ask for one**: `include_share_file` and `share_format` are
absent from the request model, the way the amount is absent from a confirmation. A flag a caller
may set that changes nothing reads as a working feature, which is worse than no flag.

### What proves it

- `FILE-PUBLICATION-001` — the share file reproduces byte-for-byte from the same publication, and
  its renderer version is recorded. `app/exports/crop.py`'s precedent governs it, including that a
  scale factor is never applied to pixels that are evidence.
- `FILE-PUBLICATION-002` — the file's `file_objects` row carries a catalogued purpose and a
  visibility scope of `trader_visible_after_publication`, and the derivation row names its source.

## Slice 6 — the trader surface: read, acknowledge, dispute

### Goal

The trader sees their own current result, can acknowledge it, and can dispute it without anything
financial moving.

### What it changes

- The reads at doc 05 `:1905`, acknowledge at doc 05 `:1921`, dispute at doc 05 `:1942`.
- A dispute writes a `manual_review_tasks` row and the exact `publication_version`.
- `20260901_0032`: one CHECK widened by one value, so `entity_type` may be
  `payment_result_publication`. Attaching the dispute to an *attempt* — which is what slice 3 does
  for an overpayment — would name a part of what the trader is complaining about, and would put the
  attempt's version where §17 requires the publication's.
- **§20.4's share-file download is not built.** `share_file_id` is null on every row until slice
  5B, and a route that can only ever 404 is a promise a client would write code against.

**The trader guard cannot be `requires(...)`.** `04_Database_Schema.md:405` gives a trader session
no permissions at all, so the route-level guard every internal route uses denies the only audience
these three have — measured, not assumed: the first version used it and every trader test failed
with `Permission denied`. The permission name is still carried in the guard closure, because
`test_permission_guards.py` finds a route's permissions by walking it. M5's `payment_requests.py`
established the shape and records the same reasoning.

### What proves it

- `API-PUBLICATION-001` — **a trader sees only their own active publication** (§17 `:1185`). A
  second trader receives **404, not 403**: an authorisation error tells them the publication
  exists, which is M5's isolation rule one aggregate further along.
- `SVC-DISPUTE-001` — **a dispute references the exact publication version** (§17 `:1185`) and
  "does not automatically reverse bank facts" (doc 05 `:1942`). The test asserts the attempt's and
  the request's rows are byte-identical after the dispute. This is slice 1's negative property at
  the other end of the milestone: the human action that looks like it should move the money is
  precisely the one that must not.
- `SVC-ACKNOWLEDGE-001` — **the same read-back for the safe-looking action.** The plan named the
  dispute's negative property and not the acknowledgement's, and a convenience write gets added to
  whichever action nobody is watching. Both compare whole rows.
- `AUD-PUBLICATION-001` — `payment_publication.acknowledged` and `.disputed`, and no outbox event
  for either, which is what the catalogue lists. The absence is asserted as well as the presence.

**A trap this slice found in M8's code.** `resolve_task` sets `entity_record_version` from the
subject *at resolution*, which is right for a privacy review — its comment explains that the
version somebody judged is the fact worth keeping. A dispute needs the other fact: the version the
trader was shown. Without teaching `_subject_version` about publications, resolving a dispute
would have set the column back to `NULL` and §17 `:1185`'s reference would have vanished at exactly
the moment somebody acted on it. The two readings agree here only because a publication is
immutable, which is what makes writing it at both ends consistent rather than contradictory.

**No dispute `reason_code` list exists.** Doc 05 shows one value and no catalogue names a set. The
field is required and bounded rather than enumerated: a closed list invented here would refuse a
trader whose complaint does not fit an option somebody guessed, and this is the only surface in the
system whose user is a customer rather than staff — the cost of guessing wrong is a phone call
instead of a record. The same reversible middle as G-3, and M0 owes the list.

## Slice 7 — `notifications`, and the consumer the outbox never had

### Goal

Outbox events become messages for people, so that G-2 and G-5 stop being promises.

**Split from the correction, which is now slice 7B.** §17.7's seventh step is "notify the trader",
so the correction depends on this and not the other way round — and the two have different
blockers. This one has none: `04_Database_Schema.md` §13.3 specifies the table, the index and the
rule that a notification is never workflow truth. 7B's are recorded there.

### What it changes

- `notifications` (doc 04 `:1334`) with §13.3's dedup index verbatim, and **no UPDATE grant** —
  nothing marks a notification read yet, and ADR-009 has not settled a delivery channel.
- `app/notifications/projection.py`, and `poll_outbox_task`'s `lambda _event: None` replaced.
  That no-op carried M2's own explanation since the outbox was built: "nothing consumes these
  events in Phase 1A, and a dispatcher that invented a destination would publish somewhere no
  consumer agreed to." The destination is document 04's, not a guess.
- Three of the eleven event types are read. The other eight are ignored rather than dead-lettered:
  most of them are about work the centre does to itself, and a person has no use for them.

### What proves it

- `OPS-NOTIFY-001` — **notification failure does not roll back committed financial state** (§17
  `:1185`). The projection is made to raise and the attempt's whole row is read back; the event is
  left `failed` and retryable rather than published, because the message genuinely was not sent.
- `OPS-NOTIFY-002` — a confirmed failure produces a trader notification. G-5's decision made
  concrete: `PaymentAttemptFailed` has been enqueued since slice 3 and read by nothing, and this is
  the test that says the failure path exists rather than being described.
- The dedup index is exercised by redelivering the same event, which is what at-least-once means in
  practice rather than in a docstring.
- A notification carries **no amount and no IBAN**: every channel ADR-009 might choose delivers
  outside the authenticated surface, so a figure in the body is a figure on somebody's lock screen.

**Four of the first seven negative controls went NOT CAUGHT, one for each of the four meanings.**
Worth recording in full, because the milestone opened by naming them:

| Control | Meaning | What it actually showed |
|---|---|---|
| an amount in the message | *test insensitive by construction* | the fixture's event payload carried no amount, so the assertion could not have failed however the message was written |
| the dedup key set to `None` | *sabotage does not break the property* | the projection's read matched the earlier row through `IS NULL`, so deduplication held for the wrong reason |
| a malformed payload returning `None` | *sabotage does not break the property* | the caller then hit `None.trader_id` and the event failed anyway |
| the migration granting `UPDATE` | *sabotage asks the wrong question* — **and the gate was missing** | the control defined an uncalled helper; fixing it revealed that **no test covered this table's privileges at all** |

The fourth is the one that mattered. `test_batching_table_privileges.py`'s matrix is M6's and stops
at the batching tables, so `notifications` could have shipped with any grant and nothing would have
said so. `test_the_runtime_role_cannot_change_a_notification` exists because a negative control went
uncaught, which is the whole reason for running them.

## Slice 7B — correction, publication N+1, and the Definition of Done

### Goal

A published result can be corrected without erasing what the trader was shown.

### What it changes

- The correction command behind `payment_publication.correct`, with M7's step-up binding.
- §17 `:1172`'s eight steps, and doc 04 `:1162` compressed into one sentence.

**What is settled and what is not.** ADR_INDEX's **POL-002 is approved for Phase 1A**: "manager
authority or dual control is required; the accountant-only default is rejected... The previous
publication and its evidence are preserved and `payment_publication.correct` keeps
`default_roles: []` with preparer and approver split." So the *control* is decided, and the empty
default roles are a deployment decision — an administrator assigns them — rather than a block.
POL-002 also sets this slice's headline obligation in its own words: **"M9 correction and UAT must
prove the control cannot be configured off."**

**What is not settled is the route.** `command_catalog.yaml`'s `payment_publication.correct_paid_
result` row carries `method: TBD, path: TBD`, and document 05 defines no correction endpoint. What
document 05 *does* define is where a correction comes from: `:1855`, on the evidence-link
replacement — "When a published result materially changes, a corrected publication and trader
notification are required." Slice 2 built that replacement before publications existed, so it
implements the first half of that sentence and none of the second. That is the seam 7B works along,
rather than inventing a path M0 owns.

### What proves it

- `SEC-CORRECTION-001` — **the control cannot be configured off**, which is POL-002's own wording
  and this slice's headline. One administrator grants one person both roles — two clicks, and
  exactly what a real deployment does by accident — and the correction is refused anyway, because
  the separation compares two identifiers rather than asking about grants. Its other half is that
  the named approver must actually hold `payment_publication.correct`, read from *their* roles: one
  alone would let two ungranted people correct, the other alone would let one granted person.
- `SVC-CORRECTION-001` — **the old publication is preserved** (§17 `:1185`). Every column of
  publication N read before and after through `row_to_json`, with only `status` permitted to move
  — the M6 supersession pattern. Backed by `20260903_0034` granting `UPDATE (status)` and nothing
  else, and by a second test that reads `information_schema` directly: a grant is a capability, and
  only a query about privileges can see one. That test exists because a negative control widening
  the grant went NOT CAUGHT — the command does not write those columns, so nothing observable
  changed.
- `SVC-CORRECTION-002` — N+1 is created, N becomes `superseded`, the aggregate is recalculated,
  and the whole thing is one transaction. A correction that commits the new publication and fails
  to supersede the old one leaves two `active` rows, which the partial unique index refuses — so
  this test asserts the failure path leaves exactly one.
- `OPS-NOTIFY-001` — **notification failure does not roll back committed financial state** (§17
  `:1185`). The handler is failed deliberately and the financial rows are read back.
  `audit_outbox_catalog.yaml` sets `notifications_are_workflow_truth: false`, so nothing reads the
  notification to decide anything, and the test asserts that too.
- `OPS-NOTIFY-002` — a confirmed failure produces a trader notification. G-5's decision made
  concrete: `PaymentAttemptFailed` is enqueued today and read by nothing, and this is the test that
  says the failure path exists rather than being described.

**Four of slice 7's first seven negative controls went NOT CAUGHT, and each was a different one of
the four meanings.** Worth recording in full, because the milestone opened by naming them:

| Control | Meaning | What it actually showed |
|---|---|---|
| an amount in the message | *test insensitive by construction* | the fixture's event payload carried no amount, so the assertion could not have failed however the message was written |
| the dedup key set to `None` | *sabotage does not break the property* | `_insert_once`'s read matched the earlier row through `IS NULL`, so deduplication held for the wrong reason |
| a malformed payload returning `None` | *sabotage does not break the property* | the caller then hit `None.trader_id` and the event failed anyway |
| the migration granting `UPDATE` | *sabotage asks the wrong question* — **and the gate was missing** | the control defined an uncalled helper; fixing it revealed that **no test covered this table's privileges at all** |

The fourth is the one that mattered. `test_batching_table_privileges.py`'s matrix is M6's and stops
at the batching tables, so `notifications` could have shipped with any grant and nothing would have
said so. `test_the_runtime_role_cannot_change_a_notification` exists because a negative control
went uncaught — which is the whole reason for running them.
- `TRACE-M9-001` — the Definition of Done (§17 `:1200`): every trader-visible result traces
  publication → confirmed result → confirmed evidence → exact bank-result source. One test that
  walks the chain in SQL for a published request and asserts each hop resolves — the shape of M7's
  approval-traceability obligation, **whose id is deliberately not written here**: the scanner
  counts any id inside a `### What proves it` section as one this plan states, so naming M7's
  would make two plans state one obligation and a citation of either would discharge both. The
  first draft did exactly that and the gate caught it.

**The hole this slice closed, which had been open since slice 2.** `replace_evidence_link` knew
nothing about publications — it was written before they existed — so an accountant holding
`evidence_link.replace` could swap the evidence under a *published* result: the old link became
`replaced`, the publication went on citing it, and the trader went on being shown evidence that had
been retired. No approval, no publication N+1, no notification. Doc 05 `:1855` requires all three;
slice 2 implemented the sentence's first clause and nothing after it. The ordinary route now
refuses the published case and names the correction, rather than quietly escalating to one — a
silent escalation would let POL-002's rejected accountant-only default back in through a path
nobody was looking at.

**One more gate found a second writer and was right to.** M8's `TestNothingCanPublish` refused
`publication_correction.py` until it was named among the modules allowed to write a publication
field. The exemption is not "this file is trusted": every module on that list must reach the §16.5
privacy guard, and a control asserts it — which is what keeps the list a condition rather than a
door.

---

# 4. Decisions this plan takes, and questions it does not

## G-1 — `revoked` or `voided`, and the catalogue already knows

`status_catalog.yaml`'s `confirmed_evidence_link` carries `revoked` as canonical with `voided` as
an alias, and marks it **"provisional pending schema/API reconciliation"**: documents 06 and 08 say
`revoked`, documents 04 and 05 say `voided`.

**Taken, by the precedent this repository already set.** DOC-CONFLICT-016 had the same shape for
`bank_export` and was settled by the status catalogue winning for the enforced CHECK, because the
status-drift gate holds every CHECK to its aggregate exactly. So: the column stores **`revoked`**,
the CHECK lists the canonical values only, and the alias is not accepted at the boundary — a
deprecated alias that never broadens authority and fails closed, the same rule
`permission_catalogue.py` records for document 05's permission spellings.

**The route path stays `/void`** (doc 05 `:1860`), because the path is the API contract and
renaming it would be a breaking change the oasdiff gate would refuse. The audit action stays
`evidence_link.revoked`, which is what the catalogue already names. A route whose path and whose
stored status differ in spelling is untidy, and untidy is cheaper than either an unapproved schema
value or a broken contract. Documents 04 and 05 are owed an editorial fix; this is recorded, not
decided for the owner.

## G-2 — `notifications` does not exist, and slice 7 builds it

Doc 04 `:1334` specifies the table; no milestone has built it. §17 `:1172` requires the trader be
notified on correction. **Taken:** slice 7 adds it as an outbox-handler projection, with the
deduplication key doc 04 `:1340` names, and never reads it to decide anything. If the owner later
wants a delivery channel — SMS, push — that is ADR-009 territory and the table is what it would
write into.

## G-3 — "a reason may be required by policy" is not a policy

Doc 05 `:1564` on confirming paid with no evidence: "when no evidence exists, a reason may be
required by policy". No approved document states the policy. §17 `:1131` lists "evidence or
approved exception exists" as a validation, which implies an approval this system has no command
for.

**Taken, as the reversible middle:** a reason is **required** whenever `primary_evidence_link_id`
is null, stored on the attempt, and audited. Not an approval workflow, because inventing one would
create a permission and a route that no catalogue describes — the exact thing section 1 says this
milestone must not do. **The owner owes a decision** on whether an evidence-free paid confirmation
needs a second person, and the field this slice stores is what a later approval flow would attach
to.

## G-4 — the reconciliation task's type is not named

`manual_review_tasks.task_type` is a value M8 seeded from M0's task-type list. Slice 4 needs a type
for the overpayment task, and the list must be checked before one is used. If it contains nothing
suitable, the precedent is M8's: implement against the identifier the catalogue does have, or
record the gap and open the task with the nearest approved type rather than inventing a value that
looks approved. **Not decided here** — it is a five-minute read at the top of slice 4, and deciding
it now from memory is how a wrong value gets written into a plan and then trusted.

## G-5 — how a failed payment reaches its trader

Found while building slice 5. `06_Workflows_and_State_Machines.md` 13.2 draws exactly one arrow
into the publication path — `paid --> result_ready_for_trader` — and none from `partially_paid`,
`failed` or `retry_required`. Read literally, **only a fully paid request can ever be published**,
which looks at first like a trader whose payment failed is never told anything.

**Taken: publication stays `paid`-only, and the failure path is `notifications`.** Four things
decided it, and none of them is the diagram.

**1. A publication is not a message.** `04_Database_Schema.md` §11.9 calls the row a "trader-visible
result/share output" and gives it a `share_file_id` and a `content_hash`. It is an immutable,
hashed, evidence-bearing artifact a trader can forward to their accountant. A failure has no
evidence to bear and nothing to share; publishing one would mean minting a permanent versioned
document whose content is "nothing happened".

**2. The event already exists and already fires.** Slice 3 enqueues `PaymentAttemptFailed` on every
confirmed failure — catalogued, dispatched by M2's outbox, and today **with no consumer**. G-2
already assigns `notifications` to slice 7. So the mechanism for telling a trader about a failure
is built and waiting for its reader; adding a publication path would be a second answer to a
question that already has one.

**3. `partially_paid` is not a final state in the first place.** The state machine's own next step
from it is `retry_required`, and Iranian per-transaction transfer limits make split payments
ordinary rather than exceptional — `bank_profile_versions.default_transfer_limit_irr` exists for
exactly that. An immutable publication saying "partly paid" while a retry is in flight would need
correcting almost immediately, which is the one thing §11.9 makes expensive.

**4. Publishing `failed` would have been a branch with no reachable input.** Checked rather than
assumed: **nothing in this system writes `payment_requests.status = 'failed'`.** Slice 4's
`_recalculate` returns early when the paid sum is zero, and §17.4's five payment-result commands
contain no command that would — though 13.2 draws `sent_to_bank --> failed: terminal failed outcome
chosen`. Adding the arrow to publication without adding the command would have shipped a status
branch nothing could reach, which is this repository's most-repeated defect.

**What this leaves for the owner, stated precisely rather than as an open question:**

- **Slice 7 must consume `PaymentAttemptFailed`, not only the correction event.** That is now a
  requirement of the slice rather than an implication, and it is what makes this decision honest —
  without it the failure path is a promise.
- **Doc 06 13.2 draws an arrow §17.4 gives no command for.** "Terminal failed outcome chosen" needs
  either a sixth payment-result command with a catalogue row, a permission and an audit action, or
  the arrow removed. M9 builds neither: inventing the command is exactly what section 1 says this
  milestone must not do. Recorded as an M0 debt; until it is settled, a request whose every attempt
  failed rests at `sent_to_bank`, and the trader learns of it from the notification rather than
  from the request's status.

## G-6 — the publication status aggregate is not in the catalogue

`status_catalog.yaml` has aggregates for `payment_request`, `payment_attempt`,
`confirmed_evidence_link`, `receipt_segment` and the rest, and **none for
`payment_result_publication`**. Document 04 §11.9 names its three values and is the only source.

`tests/backend/test_status_catalogue_drift.py` holds every CHECK to its catalogued aggregate
exactly; for this table it has nothing to compare against, so the CHECK is unguarded by that gate.
Recorded as an M0 debt rather than papered over: adding the aggregate is a catalogue change and
belongs to whoever owns the catalogue.

---

# 5. What this plan carries forward

The lessons from M6, M7 and M8 that apply here specifically, rather than the whole list.

- **A gate whose input is incomplete passes.** Every list parsed from a document is checked
  non-empty first.
- **NOT CAUGHT has four meanings**, and "the sabotage does not break the property" is one of them.
  M9 has more negative properties than any previous milestone — acceptance does not pay, dispute
  does not reverse, notification does not roll back — and a negative property is exactly where a
  control can be wrong rather than the gate.
- **Name an absent obligation, never its id.** The traceability scanner counts any id in a test
  file as a citation; G-5 nearly added a twelfth correction by inventing `SVC-CANCEL-*`.
- **A mechanism with no caller is this repository's most-repeated defect** — fifteen instances. M9's
  risk shape is specific: a validation that cannot fire because an earlier status transition already
  forbids the case, which is exactly how G-5's export guard died. **For each of slice 3's seven
  validations, construct the state that reaches it through the real routes before believing the
  check is live.**
- **Run the gate's own invocation**, and reproduce the environment as well as the command — the
  verifier keeps `.local/` between runs, so a local pass proves the stack works on an
  already-bootstrapped database.
- **A gate can fail on its own test data**, and its message will blame the code. Read what the gate
  measured before accepting what it concluded.
- **One governance row costs six edits.** M9 should cost none, and if a slice finds itself editing
  `permission_catalog.yaml`, that is the signal to stop and re-read section 1.
