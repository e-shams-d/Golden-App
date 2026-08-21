# M6 Implementation Plan — Attempts, Splitting, and the Immutable Batch Version

Status: Working implementation plan for hand-off to implementers. Not an approved M0 artifact.
Milestone authority: `Implementation Docs/00_Start_Here/15_Agent_Implementation_Plan.md:822-899`.
Precondition: M5 as merged — a payment request reaches `eligible_for_batching` through an
immutable revision chain, and `tests/backend/test_m5_definition_of_done.py` holds the property
that no request-level route requires a manager-only permission.
Date of this revision: 2026-08-20.

Every claim traceable to a document is cited as `path:line` and was read back from the file
rather than quoted from a summary. Eight off-by-one citations were found that way during M5,
by reading rather than by any gate.

Where this plan resolves a divergence between authorities, the divergence is named in section 2
so it is raised in the pull request rather than decided silently inside a migration.

---

# 1. What M6 delivers, and the Definition of Done

## 1.1 Scope, as the milestone authority states it

`15_Agent_Implementation_Plan.md:826` sets the goal: "Translate eligible business requests into
exact bank-execution attempts and an immutable versioned batch snapshot."

`:828-838` requires a **server-side preview** that computes the split without mutating records.
`:839-848` names the entities. `:849-859` is titled "Attempt lineage" and requires that retry
and correction lineage be *supportable*, not that retry commands exist. `:861-872` gives the
batch-version lifecycle. `:874-882` gives the concurrency controls. `:883-893` lists the tests.

## 1.2 Definition of Done (verbatim)

`15_Agent_Implementation_Plan.md:897`:

> M6 is complete when an accountant can produce an exact immutable batch version ready for
> manager review and all row-level bank data is frozen in relational snapshots.

**"Ready for manager review" is where M6 stops.** `:901` opens M7 as "Exact Manager Approval,
Final Export, and Mark Sent". This plan's first draft assumed manager approval was M6 work and
was wrong: M6 builds the **object** approval binds to — the exact version, its content hash, and
the persisted finalizer identity M7's separation-of-duties guard will compare against — and M7
builds the decision.

That matters for a gate M5 already installed. `tests/backend/test_m5_definition_of_done.py`
pins the manager-only permission set to exactly `payment_batch_version.approve`, `.reject` and
`.invalidate_approval`, and asserts no **request-level** route declares one. M6 does not weaken
that gate; M6 is what the gate was written in anticipation of. Two ways M6 could break it are
obligations below: a batch route that declares a `payment_request.*` permission would widen the
gate's request-scope classification (`TRACE-BATCH-001`), and a manager-only permission declared
on anything request-side would fail it outright (`SEC-BATCH-004`).

The DoD's second clause — "all row-level bank data is frozen in relational snapshots" — is the
one most easily satisfied in appearance. A snapshot column that is written once and never read
is frozen and worthless. `DB-ATTEMPT-002` therefore requires that every snapshot the export
will need is read back from the frozen row and not from the live profile.

## 1.3 What M6 starts with, and what it must build

**Nothing M6 needs exists.** `services/backend/app/db/models/` has no attempt, batch, version,
item or allocation model, and the migration head is `20260817_0016_payment_request_and_revision`.
All five tables and the allocation relation are new.

What M5 and M4 leave ready:

- A request at `eligible_for_batching` with a current immutable revision carrying
  `amount_irr`, the beneficiary snapshots and `content_hash`.
- The splitting **inputs**, from M4's versioned bank configuration: `bank_profile_versions`
  carries the per-transfer limit, the after-cutoff limit, the cutoff time and
  `splitting_enabled` (`services/backend/app/db/models/bank.py:185-195`).
- `app/db/locking.py`'s ordered lock scopes, `compare_and_swap`, the Unit of Work,
  `IdempotencyResolver`, and audit-and-outbox in one transaction.
- The money contract, and `app/core/money.py` with a caller.

---

# 2. Authority, precedence, and the decisions this plan makes

## 2.1 Baselines that bind M6

| Baseline | What it settles |
|---|---|
| **`FINANCIAL_INTEGRITY_BASELINE.md:34-49`** | Active allocation is **database-enforced**. A dedicated relation keyed on `payment_attempt_id`; allocation and item insertion in one transaction; "service-layer checks alone are insufficient"; release is an explicit guarded transition; historical evidence stays immutable and queryable; the constraint applies **across all active versions**, not within one. Required evidence is enumerated: unique-constraint, two-transaction race, rollback/retry, replacement/release, and a double-payment negative test. |
| **`FINANCIAL_INTEGRITY_BASELINE.md` §5** | `finalizer != approver` at **batch** level. M6 persists the finalizer; M7 enforces the comparison. |
| `MONEY_TIME_CONTRACT.md:17-18` | Rule 8: API monetary values are base-10 integer **strings**. Rule 9: JavaScript `Number` is forbidden for financial amounts. |
| `04_Database_Schema.md:171` | "Outgoing-payment allocation has no hidden tolerance. **Exact equality is required** unless a future explicitly modeled fee/rounding component is introduced." |
| `docs/governance/status_catalog.yaml` | The canonical state vocabularies. M6 uses them and adds none. |
| `docs/governance/permission_catalog.yaml:458-486` | Every permission M6 needs already exists, is approved, and is seeded. M6 creates none. |

## 2.2 `batched` is derived, and a command must not write it

`status_catalog.yaml:266-267` marks `batched` `derived: true` and records the reason: "current
active attempt allocation is the authoritative condition."

The natural inference — that the create command moves the request to `batched` — is exactly the
defect M5 slice 7 removed from `create_revision`, which set `submitted_to_center` on every
correction because a plausible sentence justified it and no document asked for it. So M6 writes
no `batched` status. The request's membership of a batch **is** its active allocation, and
`CON-BATCH-003` asserts that the projection and the allocation cannot disagree.

Owner confirmation is cheap here and worth having: see G-5.

**The same thing is true of the batch container, and document 04 stores it anyway.** Found while
writing slice 2. `status_catalog.yaml:359-370` marks **nine of the batch's eleven states**
`derived: true` — `draft`, `ready_for_approval`, `approved`, `approval_invalidated`, `exported`,
`sent_to_bank`, `result_received`, `partially_resolved`, `resolved` — with only `rejected` and
`cancelled` stored facts. `04_Database_Schema.md:971` nonetheless gives `payment_batches` a
`status` column and calls it "operational status".

Both are right, and the resolution is that the column is a **materialised projection**, not an
independent fact. The status drift gate settles the vocabulary without being asked: a
`status IN (...)` CHECK must equal its catalogue aggregate exactly, and the catalogue records a
canonical set here, so the CHECK carries all eleven or the gate fails. What it cannot settle is
whether the stored value and the derivation agree, so `CON-BATCH-004` asserts that they cannot
disagree — `draft` stored exactly when the current version is `draft` — rather than asserting
that the command wrote `draft`. A test that asserts the write would pass on a projection that
had drifted from the thing it projects, which is the whole failure mode.

## 2.3 The allocation relation is approved in design and unspecified in shape

`FINANCIAL_INTEGRITY_BASELINE.md:34-49` is a resolved, approved decision. But no document gives
the relation a name, a column list, or a shape for the release evidence it requires.
`04_Database_Schema.md:1598-1606` still describes allocation as a service concern — "The
service locks the request…" — which `:39-40` of the baseline explicitly calls insufficient.

And `docs/governance/command_catalog.yaml:115` still records `payment_batch.create` with
`"status": "blocked_by_active_membership_constraint_design"`, a status that has been stale since
the design was approved. That is the same class of defect as the `settings.manage` promise M5
slice 9 found in `UNGUARDED_ROUTES`: a note that reads as current and describes a world that
moved on.

**This plan proposes the shape rather than inventing it silently** (G-1). Slice 2 is blocked on
the owner ratifying or amending it, and the migration is where it becomes irreversible, which is
why it is named here.

## 2.4 The batch-version diagram and §29.2 disagree about cancelling an approved batch

`06_Workflows_and_State_Machines.md:801-803` draws `draft --> cancelled`,
`ready_for_approval --> cancelled` and `rejected --> cancelled`. It draws **no**
`approved --> cancelled` and no `approval_invalidated --> cancelled`. §29.2 says: "Approved batch
may be replaced/cancelled only before valid final export is sent; approval remains historical."

This is the same shape as M5's cancellation finding, where the request diagram declared
`cancelled` and drew no arrow into it while §29.1 held the real rule. **M6 does not need to
resolve it**: M6 cannot reach `approved`, because approval is M7. M6 implements draft-only
cancellation, `SVC-BATCH-006` enumerates the permitted origins from §29.2 restricted to the
states M6 reaches, and G-3 records the conflict for M7, which cannot avoid it.

## 2.5 Two approved permissions have no catalogued command

`payment_batch.cancel_draft` (`permission_catalog.yaml:466`) and
`payment_batch_version.invalidate_approval` (`:486`) are both approved and both seeded, and
neither appears in `command_catalog.yaml` at all. That is DOC-CONFLICT-045/046's shape exactly —
a permission with nothing to grant access to. `cancel_draft` blocks slice 4; `invalidate_approval`
is M7's. See G-4.

## 2.6 Money on the batch surface

`05_API_Specification.md:1300` and `:1307` show batch amounts as unquoted JSON numbers.
`MONEY_TIME_CONTRACT.md:17-18` requires base-10 integer strings and forbids `Number`. The
contract wins, as it did in M5 slice 4, and the editorial fix is owed to document 05 (G-6, the
same DOC-CONFLICT-050 on a new surface).

`API-BATCH-002` asserts this on the **raw response text**, not on a parsed dictionary. A parsed
assertion cannot tell `"2000000000"` from `2000000000`, which is the whole of the claim.

## 2.7 What M6 does not build

- **No manager approval, no reject, no invalidate.** `:901` gives all three to M7.
- **No exports of any kind.** `:934-947` is M7.
- **No mark-sent, no attempt outcome confirmation, no retry command.** `:849-859` requires the
  lineage *columns* so a retry can be attributed later; the commands are M7 and M8.
- **No `batch_approvals` table.** It records a decision M6 cannot make.
- **No screens.** The milestone names none — see G-7, which is the one open question that would
  add a sixth slice.

---

# 3. Slices

Each slice is one pull request. `### What proves it` is the section the traceability gate parses;
every obligation named there must be discharged by a test in the same pull request.

## Slice 1 — The splitting engine, and the preview that is its only caller

### Goal

An accountant can ask what a batch *would* be. Nothing in the database changes.

### What it changes

- `app/batching/splitting.py`: a pure function from a revision amount and a bank-profile
  version's four splitting inputs to an ordered list of proposed attempts.
- `app/api/v1/payment_batches.py`: `POST /api/v1/payment-batches/preview`
  (`05_API_Specification.md:1270`).
- **No migration.** The preview reads only tables M4 and M5 already built.

The engine and its caller ship together, and that is the boundary's whole justification. Five
times in M3 and once in M5 a complete, tested mechanism shipped with nothing calling it; the
preview is the splitting engine's consumer, so neither can exist alone.

### What proves it

- `SVC-SPLIT-001` — splitting is a pure function of the amount, the four inputs read from
  `bank_profile_versions` (`app/db/models/bank.py:185-195`), and the evaluation instant. The
  version id is an argument rather than a lookup, because `:833` makes the rules versioned: a
  preview computed against "the current profile" is a preview nobody can reproduce.
- `SVC-SPLIT-002` — the proposed rows sum to the request amount **exactly**.
  `04_Database_Schema.md:171` forbids a tolerance, so this is a property test over amounts that
  do not divide evenly, and the residual row carries the remainder.
- `SVC-SPLIT-003` — both limits are nullable, so a null limit yields one row; the after-cutoff
  limit applies strictly after `cutoff_time` in the business timezone. Asserted at
  cutoff minus one second, at the cutoff, and after it.
- `SVC-SPLIT-004` — `splitting_enabled = false` yields exactly one row whatever the limits say,
  and the limits are not consulted at all.
- `API-BATCH-001` — the preview returns the shape `05_API_Specification.md:1293-1312` specifies,
  and is advisory: `:1315`.
- `API-BATCH-002` — every monetary field is a base-10 integer string, asserted against the raw
  response body. `MONEY_TIME_CONTRACT.md:17-18`.
- `CON-BATCH-001` — the caller names the revision and the record version it computed against
  (`:1280-1281`), and a stale value is refused rather than previewed. A preview of a superseded
  revision is worse than an error, because it looks like an answer.
- `SEC-BATCH-001` — guarded by `payment_batch.read` (`permission_catalog.yaml:458`), not
  `payment_batch.create` (`:463`). A route that writes nothing must not require the grant that
  authorises writing. Blocked on G-2.

### Negative controls

Run the preview against a fully populated fixture with the session instrumented to fail on any
`INSERT`, `UPDATE` or `DELETE`, and snapshot every row and `record_version` in
`payment_requests` and `payment_request_revisions` before and after. Then assert the three
governance tables are **also** untouched — no `audit_logs` row, no `outbox_events` row, no
`idempotency_records` row. `:893` says the preview "does not mutate records"; this says it is not
a command, which is the stronger and more useful claim.

Remove the cutoff comparison: `SVC-SPLIT-003` must fail. Return a JSON number for one amount:
`API-BATCH-002` must fail.

## Slice 2 — The five tables, the create command, and the read that uses them

### Goal

The first write: one batch, one draft version, its attempts, its ordered items, and a
database-enforced allocation — or nothing at all.

### What it changes

- One migration creating `payment_attempts`, `payment_batches`, `payment_batch_versions`,
  `payment_batch_items` and the active-allocation relation of §2.3.
- `app/commands/payment_batch.py`: `create_batch`.
- `GET /api/v1/payment-batches/{batch_id}` and its list, because a container nothing can read is
  a container nobody can act on.

**Corrected before the migration was written.** This section said
`payment_batch_version_items`; `04_Database_Schema.md` §11.6 calls the table
`payment_batch_items`, and `:262` and `:1036` say the same. The document wins, and the
correction had to happen here rather than in review: a migration is where a name stops being
cheap, and the plan is what the traceability gate reads. Written from memory once already this
milestone — see the `request_number` finding, fixed in the same session for the same reason.

The tables cannot be split across pull requests, and there are **three** composite deferrable
foreign keys rather than the one this section originally named:

1. `payment_batches.current_version_id` → `payment_batch_versions(id, payment_batch_id)`, which
   `:1551-1562` specifies in the same shape `20260817_0016` used for the request and its current
   revision. Deferrable because the batch and its first version are inserted in one transaction
   and each points at the other.
2. `payment_attempts.payment_request_revision_id` → `payment_request_revisions(id,
   payment_request_id)`, which `:1564-1566` requires in as many words: "An attempt's revision
   must belong to the same payment request." A plain single-column key would let an attempt cite
   a revision of somebody else's request, and every snapshot on it would then be evidence for
   the wrong trader.
3. The allocation relation's target, so an allocation cannot name an item from a version of a
   different batch — the same argument one level down.

### What proves it

- `DB-BATCH-001` — the four tables match `04_Database_Schema.md` column for column, compared by
  **parsing** the document's tables rather than transcribing them. Slice 1 of M5 transcribed one
  type wrong and the test passed; `tests/backend/test_payment_request_schema.py` is the pattern.
- `DB-ATTEMPT-001` — an attempt carries the lineage columns `:849-859` requires: what it retries,
  what it corrects, and which revision it was derived from. Nothing writes the retry columns in
  M6, and the test asserts they are nullable and unwritten rather than pretending otherwise.
- `DB-ATTEMPT-002` — every bank field the export will need is frozen on the attempt or the item,
  and is read back from the frozen row. A snapshot nothing reads is not evidence.
- `DB-ALLOC-001` — the allocation relation refuses a second active allocation for one attempt
  **at the database boundary**, across versions. `FINANCIAL_INTEGRITY_BASELINE.md:39-40`.
- `CON-BATCH-002` — two concurrent transactions allocating the same attempt: one commits, one
  fails, and the failure is the database's. The baseline's required two-transaction race test.
- `CON-BATCH-003` — the derived `batched` projection and the allocation cannot disagree: a
  request is reported batched exactly when it owns an active allocation. §2.2.
- `CON-BATCH-004` — the container's stored `status` and the derivation from its current version
  cannot disagree. Nine of the batch's eleven catalogue states are `derived: true` and document
  04 stores the column anyway, so what needs asserting is the agreement, not the write. §2.2.
- `SVC-BATCH-003` — `create_batch` is idempotent under a repeated `Idempotency-Key`, because
  `command_catalog.yaml:111` says `"idempotency": "required"` and a create that runs twice on a
  network retry allocates the same attempts to two batches. The second call returns the first
  batch rather than a second one, and the audit row is written once.
- `DB-BATCH-002` — `batch_number` follows the human-readable family the documents specify —
  `05_API_Specification.md:304` for the prefix, `07_UI_UX_Specification.md:630-640` for the
  day precision and the six-digit width — with a Gregorian business-day date, because ADR-006
  forbids Jalali in stored and transported values. `DOC-CONFLICT-054`. Written as an obligation
  because M5 invented this format instead of reading it, and the only assertion it had was
  against its own choice.
- `SVC-BATCH-001` — `create_batch` allocates and inserts items in **one** transaction; a failure
  anywhere leaves no batch, no version, no attempt and no allocation.
- `SVC-BATCH-002` — only a request at `eligible_for_batching` may be allocated, and the
  permitted origin is enumerated from document 06 rather than listed.
- `SEC-BATCH-002` — `payment_batch.create` guards the command; the read is
  `payment_batch.read`. Neither route declares a `payment_request.*` permission.
- `AUD-BATCH-001` — creation writes `payment_batch.created`
  (`audit_outbox_catalog.yaml`) in the same transaction, and publishes no outbox event, because
  the catalogue defines none and "zero or more" is what it permits. M5's audit obligation for the
  request aggregate claimed more than the catalogue allowed and had to be corrected mid-slice;
  this one is written from the catalogue outward. Its id is deliberately not repeated here — the
  traceability scanner counts any occurrence of an id in this section as *this* plan stating that
  obligation, so naming M5's would make a citation of either discharge both.
- `TRACE-BATCH-001` — no batch route declares a `payment_request.*` permission. Not tidiness:
  M5's gate classifies a route as request-scoped partly by the permissions it declares, so a
  batch route declaring one would pull itself into that gate's scope and change what the
  milestone's prohibition is asserted over.

### Negative controls

Replace the unique constraint with a service-level check: `DB-ALLOC-001` and `CON-BATCH-002`
must both fail. Commit the batch before the allocation: `SVC-BATCH-001` must fail. Write
`status = 'batched'` on the request: `CON-BATCH-003` must fail — the projection would then agree
with itself and disagree with the allocation.

## Slice 3 — Finalization: the canonical hash, the validation summary, and immutability

### Goal

A draft version becomes the exact thing a manager will approve, and stops being editable.

### What it changes

- `app/commands/payment_batch.py`: `finalize_version`, guarded by
  `payment_batch_version.finalize` (`permission_catalog.yaml:472`).
- The content hash over the version's canonical serialisation, and the persisted finalizer
  identity M7's separation-of-duties rule will read.
- **A migration adding `payment_batch_versions.finalized_by_admin_user_id`**, because there is
  nowhere else to persist it. Found while writing this slice: the word "finalizer" appears in
  neither document 04 nor document 05, so the schema as documented can name the *preparer*
  (`created_by_admin_user_id`) and the *approver* (`batch_approvals.decided_by_admin_user_id`)
  and not the finalizer — while `FINANCIAL_INTEGRITY_BASELINE.md` §5, which is
  Resolved — Approved, requires the "recorded finalizer actor" to differ from the approver and
  requires the guard to be *database-enforceable*. A guard cannot reference a column that does
  not exist. Registered as `DOC-CONFLICT-055` with G-11; the precedent is slice 2's
  `payment_attempt_allocations`, an entire table document 04 never mentions, created because the
  same baseline approves it.
- **The first caller of `app/db/locking.py`.** `lock_rows()` — the function that issues
  `SELECT … FOR UPDATE` in the global scope order — has no caller in the application and no
  test, two milestones after M2 built it for "M5 through M9". `LockScope.BATCH_VERSION_FINALISE`
  exists for exactly this command. That makes it the seventh mechanism-with-no-caller this
  project has found, and `CON-FINAL-001` is what stops it being the eighth.

### What proves it

- `SVC-FINAL-001` — the hash is deterministic across processes and stable under row ordering,
  computed over a canonical form. Two finalizations of identical content produce the same hash;
  one changed digit produces a different one.
- `SVC-FINAL-002` — a version cannot finalize unless **every** item owns the matching active
  allocation. `FINANCIAL_INTEGRITY_BASELINE.md:44-45`.
- `SVC-FINAL-003` — the item sums equal the version total exactly, and the version total equals
  the sum of the requests it carries. `04_Database_Schema.md:171` again, at the level where a
  rounding error would first become money.
- `DB-FINAL-001` — a finalized version's rows cannot be updated. Enforced by the migration's
  grants rather than by a trigger, which is how `payment_request_revisions` does it: the runtime
  roles hold no `UPDATE` on the table, so an attempted edit fails at the privilege.
- `SEC-FINAL-001` — the finalizer's identity is persisted, and it is the identity from the
  session rather than anything the caller supplied.
- `AUD-BATCH-002` — finalization writes its catalogued audit action in the same transaction as
  the state change.
- `CON-FINAL-001` — finalization takes the lock scopes `app/db/locking.py` defines, in the
  order it defines them. The module's own comment explains why the order is not a preference.

### Negative controls

Finalize with one item's allocation released: `SVC-FINAL-002` must fail. Sort the items
differently before hashing: `SVC-FINAL-001` must fail. Grant `UPDATE` to the app role:
`DB-FINAL-001` must fail.

## Slice 4 — Replacement, release, and draft cancellation

### Goal

Every way a version can leave the lifecycle, and the evidence each leaves behind.

### What it changes

- `app/commands/payment_batch.py`: `create_replacement_version`, `release_allocation`,
  `cancel_draft_batch`.
- Blocked on G-4: `payment_batch.cancel_draft` has no catalogued command.

### What proves it

- `SVC-BATCH-005` — a replacement version supersedes a finalized one, and the superseded
  version's rows are unchanged afterwards. Every column, read before and after — the M5 pattern
  that caught what "the amount is unchanged" would have missed.
- `SVC-BATCH-006` — cancellation is permitted from exactly the states §29.2 lists, restricted to
  those M6 reaches, and enumerated from §29.2 rather than listed. §2.4 records why the diagram is
  not the authority here.
- `SVC-BATCH-007` — releasing an allocation leaves queryable evidence of the release, and the
  historical batch item remains. `FINANCIAL_INTEGRITY_BASELINE.md:41-43`.
- `SVC-BATCH-008` — the baseline's double-payment negative test: no sequence of replace, release
  and re-allocate produces two active allocations for one attempt.
- `AUD-BATCH-003` — supersession is audited. Blocked on G-8: the catalogue defines no
  supersession action, so either one is catalogued or the replacement's own creation action
  carries it, and the choice is the owner's.

### Negative controls

Release an allocation and delete its evidence row: `SVC-BATCH-007` must fail. Permit
cancellation from a finalized version: `SVC-BATCH-006` must fail. Allow re-allocation without
release: `SVC-BATCH-008` must fail.

## Slice 5 — The M6 Definition of Done gate

### Goal

The two halves of `:897`, gated.

### What proves it

- `TRACE-DOD-010` — the journey: an eligible request becomes an attempt, an item, a draft
  version and then an exact finalized version ready for review, in one test, through the API, as
  the accountant. The step-to-clause mapping is derived from the DoD sentence and asserted, not
  assumed — M5's gate found that its sentence named five clauses where the plan said six steps.
- `TRACE-DOD-011` — every bank field the export will need is frozen and readable from the
  finalized version alone, with no read of a live profile. The DoD's second clause, and the one a
  write-only snapshot column satisfies in appearance.
- `TRACE-DOD-012` — no manager-only permission is required to reach a finalized version.
  Structural, calls nothing, and lives in `tests/backend` for the reason M5's does: in
  `tests/integration` a missing PostgreSQL turns the milestone's prohibition into a skip.
- `SEC-BATCH-004` — and the converse, which is M6's own risk: no **request-level** route or
  command has gained a manager-only permission while M6 was adding batch-level authority.
  Discharged by asserting M5's gate still passes unchanged, which is a claim about this
  milestone rather than the last one.
- `TRACE-M6-001` — `PENDING` contains no M6 obligation.

### Negative controls

Read a bank field from the live profile in the export path: `TRACE-DOD-011` must fail. Declare
`payment_batch_version.approve` on a request route: `SEC-BATCH-004` must fail. Rewrite
`TRACE-M6-001` as a prefix filter: it must fail, because that is the M4 defect
`obligations_stated_by` exists to prevent.

---

# 4. What the owner must settle

| ID | Question | Blocks |
|---|---|---|
| **G-1** | **The allocation relation's shape.** The design is approved (`FINANCIAL_INTEGRITY_BASELINE.md:34-49`) and its name, columns and release-evidence shape are specified nowhere. `04_Database_Schema.md:1598-1606` still models allocation as a service concern, which `:39-40` of the baseline calls insufficient. This plan proposes a relation keyed on `payment_attempt_id` with the active version and item as its target, plus a released-at and a reason for the evidence trail. Ratify or amend before the migration, because a migration is where a name stops being cheap. | **Slice 2**, and slice 4's release path |
| **G-2** | **What guards the preview.** `05_API_Specification.md:1267-1315` names no permission, and `command_catalog.yaml` excludes queries, so there is no catalogue row to read. Deny-by-default makes the route unreachable until somebody chooses. Proposal: `payment_batch.read`. | **Slice 1** |
| **G-3** | **`command_catalog.yaml:115` is stale.** `payment_batch.create` still carries `"status": "blocked_by_active_membership_constraint_design"`, and that design was approved. The status field should move to `provisional` like its neighbours. Same class as the `settings.manage` promise M5 slice 9 corrected. | Nothing, but it misleads slice 2's implementer |
| **G-4** | **Two approved permissions have no catalogued command.** `payment_batch.cancel_draft` (`permission_catalog.yaml:466`) and `payment_batch_version.invalidate_approval` (`:486`) are approved and seeded with nothing to grant access to — DOC-CONFLICT-045/046's shape. | **Slice 4** for cancel; invalidate is M7's |
| **G-5** | **Confirm `batched` stays derived.** `status_catalog.yaml:266-267` says so; §2.2 explains why the alternative reading reproduces a defect M5 removed. Cheap to confirm, expensive to discover. | Slice 2's behaviour |
| **G-6** | **Document 05 emits money as JSON numbers** on the batch surface (`:1300`, `:1307`) against `MONEY_TIME_CONTRACT.md:17-18`. DOC-CONFLICT-050 on a new surface; the contract wins and doc 05 is owed an editorial fix. | Nothing |
| **G-7** | **Does M6 owe accountant screens?** `:822-899` names no screen, yet `:897` says "an accountant can produce". M5 shipped screens as a slice of their own. This plan writes **no `UI-` obligation** rather than invent scope. If the answer is yes, that is a sixth slice. | Would add a slice |
| **G-8** | **No audit action exists for version supersession** (`audit_outbox_catalog.yaml`). Catalogue one, or accept the replacement's creation action as the record. | Slice 4's `AUD-BATCH-003` |
| **G-9** | **The approved-batch cancellation conflict** (§2.4): §29.2 permits it and the diagram draws no arrow. M6 does not reach `approved`, so this is recorded for M7 rather than resolved here. Registered as DOC-CONFLICT-053. | M7 |
| **G-10** | **What applies after the cutoff when the bank publishes no after-cutoff limit?** Found while writing slice 1, and named by neither document: `04_Database_Schema.md` and `05_API_Specification.md` are both silent on the combination of a `cutoff_time` with a null `after_cutoff_transfer_limit_irr`. The two readings differ in the direction that matters — continuing the ordinary limit produces more, smaller transfers, while reading the null as "no limit after the cutoff" would send one large transfer the bank had said it would refuse an hour earlier. Slice 1 implements the conservative reading, `applicable_limit` says so in its docstring, and `test_a_null_after_cutoff_limit_leaves_the_default_in_force` pins it. Recorded because it is an assumption and not a citation. | Nothing — slice 1 ships the conservative reading |

| **G-11** | **Where the finalizer is recorded, and whether the preparer disqualifies an approver.** `FINANCIAL_INTEGRITY_BASELINE.md` §5 is Approved and requires a *recorded* finalizer plus a **database-enforceable** separation guard; the word "finalizer" is in neither document 04 nor document 05, so no column exists to enforce against. Slice 3 adds `payment_batch_versions.finalized_by_admin_user_id` on the baseline's authority and records the deviation. Two things for the owner: confirm the column belongs in document 04 §11.5, and decide whether `12_Security_RBAC_Audit.md:1111`'s "finalizer/**preparer**" means the preparer also disqualifies an approver — which would make M7's guard two comparisons rather than one, and would change nothing in M6. `DOC-CONFLICT-055`. | **Slice 3** ships the column; M7's guard needs the second answer |

None of G-1 through G-9 is a reason to delay slice 1, which touches no schema and needs only
G-2 — and G-2's proposal is the narrower of the two candidates, so building on it and being
corrected costs one line.
