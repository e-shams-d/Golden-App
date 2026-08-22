# M7 — Exact Manager Approval, Final Export, and Mark Sent

Status: proposed. Six slices, thirty-five obligations, eleven questions for the owner.

Authority: `15_Agent_Implementation_Plan.md:901-1000` (§15). Every obligation below cites the
document that requires it; where the documents disagree, §2 records which one wins and why.

---

# 1. Scope

## 1.1 Goal, as the milestone authority states it

`15_Agent_Implementation_Plan.md:905`: "Implement the complete controlled path from immutable batch version to the exact file
manually sent to the bank."

M6 built the object. M7 builds the decision, the artifact, and the proof that ties them together.

## 1.2 Definition of Done (verbatim)

`15_Agent_Implementation_Plan.md:999`:

> M7 is complete when the system can prove exactly which approved immutable version produced the
> exact checksummed file that an authorized accountant marked as sent to the bank.

**Read the verbs.** The sentence does not ask that the system *do* those things — M6 already
produces versions and M7 will produce files. It asks that the system can **prove** the chain:
version → approval → file → checksum → sent. That is a statement about queryable evidence, and it
is what §5's integrity checks are for. A milestone that generated correct files and could not
reconstruct which approval authorised which one would satisfy every intermediate obligation and
fail this sentence.

## 1.3 What M7 starts with

**Present, and with real callers:**

- The exact immutable version, its `content_hash`, its ordered items with their `row_hash`, and
  the frozen bank fields — M6 slices 2 and 3. `tests/integration/test_m6_journey.py` proves the
  snapshot answers with the live profile deactivated.
- `payment_batch_versions.finalized_by_admin_user_id`, added by `20260821_0018` on
  `FINANCIAL_INTEGRITY_BASELINE.md` §5's authority. **This is the column M7's separation-of-duties
  guard compares against**, and it exists only because M6 slice 3 found no document provided one
  (DOC-CONFLICT-055).
- `recent_auth_contexts` and `app/security/step_up.py`, with a working caller in
  `app/commands/role_permissions.py`. M7's "valid recent-auth context" requirement has a
  mechanism; it does not have to build one.
- `app/db/locking.py`, whose first caller is M6's `finalize_version`.
  `LockScope.BATCH_VERSION_APPROVAL = 350` and `EXPORT_GENERATE_FINAL = 400` and
  `EXPORT_MARK_SENT = 450` are reserved, in that order, and the order is the point.
- M4's file storage, `file_objects`, and the availability gate that refuses a `pending` or
  `quarantined` file (`05_API_Specification.md:1014`).
- `app/core/hashing.py`'s canonical serialiser, and `app/audit/registry.py` — whose entries M7
  must extend rather than write literals into, per
  `tests/backend/test_audit_names_come_from_the_registry.py`.

**Missing, and M7 builds:**

- `batch_approvals` (`04_Database_Schema.md` §11.7) and `bank_excel_exports` (§11.8).
- **An Excel writer. Nothing is pinned** — see G-1, which is the largest open question in this
  plan because it is a dependency decision on an air-gapped deployment.
- Every command in §15: approve, reject, generate preview, generate final, download, mark sent.

---

# 2. Authority, precedence, and the decisions this plan makes

## 2.1 Baselines that bind M7

| Baseline | What it settles |
|---|---|
| **`FINANCIAL_INTEGRITY_BASELINE.md` §1** | A final artifact record is inserted **only after the file exists** and its size, media type, SHA-256, row count, total and provenance are verified. `file_id`, artifact SHA-256 and `generated_at` are non-null. **No placeholder file, hash or timestamp is permitted.** Creating the artifact, linking it to the job and marking the job succeeded are **atomic**: a failed job has no final artifact. Preview output cannot be promoted by mutating it into a final artifact. |
| **`FINANCIAL_INTEGRITY_BASELINE.md` §5** | `finalizer != approver`, not configurable off, enforced **at the command layer and by a database-enforceable guard whose race behaviour is tested**. Replacement versions require a new approval under the same rule. Break-glass is disabled for Phase 1A: no activation, grants, endpoints, flags or runtime bypasses. |
| **`FINANCIAL_INTEGRITY_BASELINE.md` §3** | Recent-auth is a persisted context bound to actor, session, action, resource, assurance, expiry and revocation, with a non-replayable identifier, and **consumption recorded in the command transaction**. |
| `MONEY_TIME_CONTRACT.md:17-18` | API monetary values are base-10 integer strings. §15.6 says the same thing about the file: "never use floating-point values for amounts." |
| `docs/governance/status_catalog.yaml` | `bank_export`'s eight canonical states. M7 adds none — see §2.3. |
| `permission_catalog.yaml:475-507` | All eleven permissions M7 needs exist, are approved and are seeded. M7 creates none. |

## 2.2 The separation guard needs an answer M6 could not give (G-2)

§5 requires the guard to be **database-enforceable**, and M6 gave it the column it had been
missing. What is still undecided is *how many comparisons it is*.

`12_Security_RBAC_Audit.md:1111` lists among the approval guards: "actor is not the version
finalizer/**preparer**". Two readings:

- **One comparison** — the approver must differ from `finalized_by_admin_user_id`.
- **Two** — the approver must also differ from `created_by_admin_user_id`, the preparer.

They differ in a case that is not hypothetical: `payment_batch_version.create` and `.finalize` are
separate permissions, both defaulting to `accountant`, so accountant A can prepare a version and
accountant B finalize it. Under the one-comparison reading, A may approve — having chosen every row
in the file. DOC-CONFLICT-055 records the question; **slice 1 implements the stricter reading and
records it**, because a guard that is too strict refuses a legitimate approval and says so, while
one that is too loose permits a self-approval nobody notices.

## 2.3 Document 05 and the catalogue disagree about export statuses (DOC-CONFLICT-016)

`status_catalog.yaml`'s `bank_export` aggregate holds eight canonical states: `generating`,
`generated`, `validated`, `downloaded`, `sent_to_bank_marked`, `voided`, `quarantined`,
`generation_failed`.

`05_API_Specification.md:536` lists exactly: `sent_to_bank_marked, quarantined, superseded, voided,
failed`. So document 05 has **`superseded`**, which the catalogue does not, and **`failed`** where
the catalogue says `generation_failed`.

This is DOC-CONFLICT-016, already Open. The status drift gate settles it without being asked: a
`status IN (...)` CHECK must equal its catalogue aggregate exactly, so the column carries the
catalogue's eight. Document 05 is owed an editorial fix, and G-3 records the one substantive part —
whether an export can be `superseded` at all, or whether replacement always produces a `voided`
one.

## 2.4 A mismatch quarantines: that is a consequence, not a command

`05_API_Specification.md:1514` — "Before every final download, the server revalidates export integrity. A mismatch
quarantines the export and returns `409 EXPORT_INTEGRITY_MISMATCH`" — and §15.5 says a mismatch
"quarantines the export and creates a high-priority task/security event".

So quarantine happens **inside the download path**, on a failed check. `permission_catalog.yaml:507`
also grants `bank_export.quarantine`, and `command_catalog.yaml` has **no row for it** — the same
shape as M6's `payment_batch.cancel_draft` (G-4 there, DOC-CONFLICT-056). Either the permission is
for a *manual* quarantine no document specifies, or it authorises nothing.

**M7 implements the automatic quarantine** and does not invent a manual one. G-4 records it.

## 2.5 Downloading is not sending, and the schema says so twice

`15_Agent_Implementation_Plan.md:989`: "Downloading does not mean sent." `bank_excel_exports` carries `downloaded_at` and
`sent_to_bank_marked_at` as separate nullable columns, and `status` distinguishes `downloaded`
from `sent_to_bank_marked`.

This is the milestone's central human-factors risk: an accountant who downloads a file and emails
it to the bank without marking it sent leaves the system believing the payment has not been made,
and the next reconciliation cycle will chase it. M7 cannot prevent that — the sending is manual by
design — but `SVC-SENT-002` requires that a downloaded, unsent export is *visibly* unsent in the
read model rather than merely lacking a timestamp.

## 2.6 Approved-batch cancellation: M7 cannot defer it (DOC-CONFLICT-053)

`06_Workflows_and_State_Machines.md:1381` (§29.2): "Approved batch may be replaced/cancelled only before valid final export is sent; approval
remains historical." The batch-version diagram at `06_Workflows_and_State_Machines.md:801-803`
draws three cancellation arrows and **not** `approved --> cancelled`.

M6 recorded this and did not need it — M6 cannot reach `approved`. M7 reaches it in slice 1, and
M6's own slice 4 finding compounds it: `permission_catalog.yaml` has exactly one batch cancellation
permission, `payment_batch.cancel_draft`, so **the state M7 creates has no exit** unless the owner
settles both DOC-CONFLICT-053 and DOC-CONFLICT-056. G-5 states the pair together, because
answering one without the other leaves an approved batch that cannot be withdrawn.

## 2.7 Excel safety is a security obligation, not a formatting one

`15_Agent_Implementation_Plan.md:971`: "escape or reject formula-like untrusted text according to policy". The untrusted text
reaching a bank file is the **beneficiary name and the description**, both of which a trader types.
A cell beginning `=`, `+`, `-` or `@` is executed by Excel when the file is opened — on the
machine of whoever at the bank opens it.

`SEC-EXPORT-001` therefore asserts a fixture whose beneficiary name is
`=HYPERLINK("http://…","click")` renders inert. **The policy is the open question** (G-6): escape
by prefixing, or refuse the row. Escaping ships a file the bank can process and changes what a
payee name looks like; refusing blocks a legitimate payment because of a character. This plan
implements escaping and records the choice, because the alternative refuses to pay somebody whose
name the trader entered in good faith.

## 2.8 What M7 does not build

- **No result publication.** `payment_result_publications` (§11.9) is M9's.
- **No bank-result bundles, no matching, no crops.** M8's.
- **No automated bank submission.** §15.7 makes sending manual; there is no channel to automate.
- **No screens** unless the owner says otherwise (G-7). §15 names none, and M6 asked the same
  question and shipped none.

---

# 3. Slices

Each slice is one pull request. `### What proves it` is the section the traceability gate parses;
every obligation named there must be discharged by a test in the same pull request.

## Slice 1 — The approval decision, and the guard that makes it mean something

### Goal

A manager approves an exact version, or rejects it, and cannot approve one they prepared or
finalized.

### What it changes

- One migration creating `batch_approvals` (§11.7), with `UNIQUE(payment_batch_version_id)` — one
  decision per version, enforced by the database — and the CHECK tying `approved_content_hash` to
  the decision.
- `app/commands/payment_batch_approval.py`: `approve_version`, `reject_version`.
- Routes at `05_API_Specification.md:1398` (approval view), `:1415` (approve), `:1449` (reject).

### What proves it

- `DB-APPROVAL-001` — the table matches §11.7 column for column, compared by **parsing** the
  document. `tests/backend/test_batch_schema.py` is the pattern, including its
  `APPROVED_ADDITIONS` mechanism for a column the document does not list.
- `SEC-APPROVAL-001` — the approver cannot be the finalizer, **enforced at the command layer and
  at the database**, with a concurrent test. `FINANCIAL_INTEGRITY_BASELINE.md` §5 requires both,
  and requires the race behaviour to be tested; a service check alone is what §2 of that document
  calls insufficient for the allocation and the same reasoning applies here.
- `SEC-APPROVAL-002` — the approver cannot be the **preparer** either, per §2.2's stricter
  reading, and the test names G-2 so the assertion can be relaxed deliberately if the owner
  decides otherwise.
- `SEC-APPROVAL-003` — approval requires a valid recent-auth context bound to *this* action and
  *this* version, and consumption is recorded in the command transaction.
  `FINANCIAL_INTEGRITY_BASELINE.md` §3.
- `CON-APPROVAL-001` — two concurrent approvals of one version produce **one** decision, and the
  loser learns which. `UNIQUE(payment_batch_version_id)` decides, not a prior read.
- `SVC-APPROVAL-001` — approval requires the expected content hash and refuses a stale one; a
  replacement version makes an open approval screen stale and the old version unapprovable
  (§15.3). No decision transfers automatically.
- `AUD-APPROVAL-001` — `payment_batch_version.approved` and `.rejected`, with the outbox event
  `PaymentBatchVersionApproved` the catalogue defines for approval and **none** for rejection,
  because the catalogue defines none.
- `TRACE-APPROVAL-001` — the approval names the exact hash it approved, so "what did the manager
  see" is answerable from one row. This is the first half of the DoD's chain.

### Negative controls

Let the finalizer approve: `SEC-APPROVAL-001` must fail. Drop the database guard and keep the
service check: its concurrent case must fail. Approve with the previous version's hash:
`SVC-APPROVAL-001` must fail. Reuse a consumed recent-auth context: `SEC-APPROVAL-003` must fail.

## Slice 2 — The export record, and the preview that cannot be sent

### Goal

An Excel file exists, is stored, is hashed, and a preview is permanently marked non-sendable.

### What it changes

- One migration creating `bank_excel_exports` (§11.8) with the `export_type`/`batch_approval_id`
  CHECK the document states.
- The Excel writer, and the dependency G-1 names.
- `app/exports/`: the renderer, taking the version and its items as **data** — no session — for
  the reason `app/batching/splitting.py` takes its rules as data.
- `bank_export.generate_preview` and its route at `05_API_Specification.md:1466`.

### What proves it

- `DB-EXPORT-001` — the table matches §11.8, parsed; and the CHECK refuses a `final` row with no
  approval and a `preview` row with one.
- `SVC-EXPORT-001` — the file is written, its SHA-256 stored, and the record inserted **only
  after** the file exists and verifies. `FINANCIAL_INTEGRITY_BASELINE.md` §1. A failure after the
  file is written and before the record commits leaves no record and no orphan claim.
- `SVC-EXPORT-002` — a preview is permanently identifiable as non-sendable
  (`15_Agent_Implementation_Plan.md:936`), and cannot be
  promoted by mutation into a final artifact (§1 of the baseline). The grant, not a rule.
- `SEC-EXPORT-001` — formula-like untrusted text is inert. The fixture's beneficiary name begins
  `=`, and the assertion is on the **written file's cell**, not on the value passed in.
- `SVC-EXPORT-003` — amounts are written as integers, never floats
  (`15_Agent_Implementation_Plan.md:975`), asserted by reading
  the cell's type back out of the file.
- `SVC-EXPORT-004` — Persian and English text round-trips, and the row order is exactly the version's
  `row_order` (`15_Agent_Implementation_Plan.md:972-974`).
- `AUD-EXPORT-001` — `bank_export.preview_generated`, from the registry rather than a literal.

### Negative controls

Insert the record before the file exists: `SVC-EXPORT-001` must fail. Write an amount as a float:
`SVC-EXPORT-003` must fail. Pass the formula fixture through unescaped: `SEC-EXPORT-001` must fail.

## Slice 3 — The final export, and the eight integrity checks

### Goal

A final file exists only for an approved version, and every check §15.5 lists is run before it can
be downloaded.

### What it changes

- `bank_export.generate_final` and its route at `05_API_Specification.md:1475`.
- `app/exports/integrity.py`: the eight comparisons, as one pure function over stored values.

### What proves it

- `SVC-EXPORT-005` — a final export requires an active approval for the **exact** version,
  and is generated from the immutable version and items, "not current mutable beneficiary data"
  (§15.4). Asserted with the live beneficiary changed first, so a read that reached for it fails.
- `SVC-INTEGRITY-001` — all eight comparisons of `15_Agent_Implementation_Plan.md:952-963`, each with its own failing case. Eight
  assertions, not one: a single "integrity holds" test passes while seven comparisons are absent.
- `SVC-INTEGRITY-002` — a mismatch **quarantines** the export and creates the security event
  `15_Agent_Implementation_Plan.md:965` requires, and the quarantined export cannot be downloaded for bank submission.
- `CON-EXPORT-001` — two concurrent final-export commands produce one logical result
  (`15_Agent_Implementation_Plan.md:987`), and a timeout after commit returns the stored result rather than generating a second
  file.
- `AUD-EXPORT-002` — `bank_export.final_generated` and `bank_export.integrity_failed`, both
  catalogued.

### Negative controls

Generate a final export with no approval: `SVC-EXPORT-005` must fail. Remove one of the
eight comparisons: `SVC-INTEGRITY-001` must fail, and it must fail on **that** comparison's case.
Read the beneficiary name from `beneficiaries` instead of the item: `SVC-EXPORT-005` must
fail.

## Slice 4 — Authorized download, and mark sent

### Goal

The file reaches a human, and the human records that they sent it.

### What it changes

- The download route, with the integrity revalidation `:1514` requires *before every* download.
- `bank_export.mark_sent` and its route at `05_API_Specification.md:1516`.

### What proves it

- `SEC-DOWNLOAD-001` — download requires `bank_export.download`, is refused for a quarantined
  export, and is refused to a trader. The file is a list of every payment the centre is making.
- `SVC-INTEGRITY-003` — integrity is revalidated **before every** download, not once at
  generation. Asserted by corrupting the stored file between two downloads.
- `SVC-SENT-001` — mark-sent acts on an exact export id, not a batch (`15_Agent_Implementation_Plan.md:978`), and records all seven fields
  `15_Agent_Implementation_Plan.md:980-987` lists. A preview cannot be marked sent.
- `SVC-SENT-002` — a downloaded, unsent export is visibly unsent in the read model (§2.5), so an
  accountant who forgot can be shown that they forgot.
- `CON-SENT-001` — mark-sent is idempotent under its catalogued key, and a second call does not
  move the timestamp or write a second audit row.
- `AUD-SENT-001` — `bank_export.sent_marked`, with `BankExportSent` — the outbox event the
  catalogue defines for exactly this.

### Negative controls

Mark a preview sent: `SVC-SENT-001` must fail. Skip revalidation on the second download:
`SVC-INTEGRITY-003` must fail. Mark sent twice and move the timestamp: `CON-SENT-001` must fail.

## Slice 5 — Invalidation, and what a replacement does to an approval

**Split into 5A and 5B after slice 1 shipped, and corrected on one point. Read this before the
obligations.**

**The split.** Three of the five obligations below are about the approval and two are about the
export. G-1 blocks the export and nothing else, so slice 5A discharges `SVC-INVALIDATE-001`,
`SVC-INVALIDATE-002` and `AUD-INVALIDATE-001`, and slice 5B discharges `SVC-INVALIDATE-003` and
`TRACE-INVALIDATE-001` once slices 2 to 4 exist. The precedent is M3's slice 8, split into five
when its parts turned out to have different dependencies. Splitting is not deferral: the two
export obligations stay in `PENDING` under 5B's name, which is the same commitment they had
before.

**The correction, which matters more.** §5 of this plan said slice 5 would build
`payment_batch_version.invalidate_approval` as "a command with a recorded catalogue gap", in
contrast to quarantine as a consequence. **That was wrong**, and checking the authority before
implementing is what found it:

- `05_API_Specification.md` defines **no invalidation endpoint**. The word appears five times and
  never as a route.
- `:1366` says the *replacement* command "never edits an approved/finalized version. Previous
  operational approval becomes historical and the batch status becomes `approval_invalidated` or
  `draft` as applicable."
- `06_Workflows_and_State_Machines.md:793` draws `approved --> approval_invalidated:
  replacement/material change`, and `:901` says the batch becomes `approval_invalidated`/`draft`
  "as a replacement version is prepared".

So invalidation is a **consequence**, exactly as quarantine is — and building it as a command
would have created an endpoint no document defines, for a permission that authorises nothing.
That is the mechanism-with-no-caller failure §5 warns about, written into the plan that warns
about it. `payment_batch_version.invalidate_approval` therefore joins `bank_export.quarantine`
under G-4, and G-12 records the state this leaves unreachable.

### What it changes

- M6's `create_replacement_version` extended: replacing an **approved** version makes its approval
  historical and records that it did. The approval row itself is never touched — §11.7 says
  approved/rejected rows are never updated, and there is no grant that would permit it, so
  "historical" is a property of the version's state rather than a flag on the decision.
- No migration. `approval_invalidated` is already in `payment_batch`'s CHECK, `payment_batches`
  already grants `status`, and the audit action is already catalogued.

### What proves it

- `SVC-INVALIDATE-001` — a replacement version makes a prior approval historical and
  non-operational (`15_Agent_Implementation_Plan.md:927-933`, `04_Database_Schema.md:1580-1592`), and the
  container reaches `approval_invalidated`. M6's
  container-projection obligation still holds — the stored status cannot disagree with the current
  version's — and its id is deliberately not repeated here: the traceability scanner counts any
  occurrence in a "What proves it" section as *this* plan stating that obligation, so naming M6's
  would make a citation of either discharge both.
- `SVC-INVALIDATE-002` — a replacement requires a **new** approval under the same separation rule
  (`FINANCIAL_INTEGRITY_BASELINE.md` §5), so the original approver may not approve the replacement
  either if they finalized it.
- `SVC-INVALIDATE-003` — an approval whose version was superseded cannot produce a final export,
  and an existing final export for it is voided rather than deleted. §29.2's "approval remains
  historical".
- `AUD-INVALIDATE-001` — `payment_batch_approval.invalidated`, catalogued.
- `TRACE-INVALIDATE-001` — after a replacement and a second approval, the chain from the *sent*
  file back to *its* approval is unambiguous. Two approvals exist and only one produced the file.

### Negative controls

Let a superseded version's approval authorise a final export: `SVC-INVALIDATE-003` must fail.
Transfer the decision to the replacement automatically: `SVC-INVALIDATE-001` must fail, because
`15_Agent_Implementation_Plan.md:931` says no decision transfers.

## Slice 6 — The M7 Definition of Done gate

### Goal

The DoD's verb is "prove". This slice is the proof.

### What proves it

- `TRACE-DOD-013` — the chain, in one test: an eligible request becomes a version, an approval, a
  final file, a checksum and a sent marking, and from the **sent export alone** every earlier link
  is recoverable. The DoD sentence is parsed from this plan and its clauses asserted, as M5's and
  M6's gates do.
- `TRACE-DOD-014` — break-glass is absent. `FINANCIAL_INTEGRITY_BASELINE.md` §5 disables
  activation, grants, endpoints, feature flags and runtime bypasses for Phase 1A, and
  `15_Agent_Implementation_Plan.md:983` requires the absence to be tested. Structural, in `tests/backend`, because in
  `tests/integration` a missing PostgreSQL turns it into a skip.
- `TRACE-DOD-015` — no route or command lets the same actor finalize and approve, asserted over
  the whole route table rather than the two routes involved.
- `TRACE-M7-001` — `PENDING` holds no M7 obligation, matched by id against this plan and not by
  prefix.

### Negative controls

Add a feature flag that bypasses the separation check: `TRACE-DOD-014` must fail. Break one link
of the chain — a final export whose `batch_approval_id` names an approval of a different version:
`TRACE-DOD-013` must fail.

---

# 4. What the owner must settle

| ID | Question | Blocks |
|---|---|---|
| **G-1** | **Which Excel writer, and is it acceptable on an air-gapped deployment?** Nothing is pinned. §15.6 requires formula escaping, column/type validation, exact row order, Persian/English encoding and integer amounts — all of which a pure-Python writer can do offline. `openpyxl` is the proposal: MIT, no native build, no network at runtime. It is a new production dependency on a system that cannot reach a registry from the deployment network, so the wheel must be vendored and the choice is the owner's, not an implementer's. | **Slice 2**, and everything after it |
| **G-2** | **Does the preparer also disqualify an approver?** `12_Security_RBAC_Audit.md:1111` says "finalizer/preparer" and the two are separately permissioned, so accountant A can prepare what accountant B finalizes. Slice 1 implements the stricter reading — the approver differs from **both** — and `SEC-APPROVAL-002` names this question so it can be relaxed deliberately. DOC-CONFLICT-055. | Slice 1's guard; relaxing it later is one assertion |
| **G-3** | **Can a `bank_export` be `superseded`?** `05_API_Specification.md:536` lists it and `status_catalog.yaml` does not, which is DOC-CONFLICT-016. The catalogue wins on the CHECK; what is undecided is whether replacement voids an export or supersedes it, and those differ in whether the old file stays downloadable as history. | Slice 5's void path |
| **G-4** | **`bank_export.quarantine` has a permission and no command.** M7 implements the *automatic* quarantine §15.5 requires. Whether a manual one is intended — and who may do it — is unanswered, and the permission currently authorises nothing. Same shape as M6's DOC-CONFLICT-056. | Nothing in M7; the permission stays unreachable |
| **G-5** | **An approved batch will have no exit** (DOC-CONFLICT-053 **and** DOC-CONFLICT-056 together). §29.2 permits cancelling an approved batch before a final export is sent; the diagram draws no such arrow; and the only batch cancellation permission is `cancel_draft`. M7 *creates* the `approved` state, so this stops being deferrable. Answering one conflict without the other still leaves an approved batch that cannot be withdrawn. | **Slice 1 creates the state; slice 5 cannot give it an exit** |
| **G-6** | **Escape or refuse formula-like text?** `15_Agent_Implementation_Plan.md:971` says "according to policy" and no document states the policy. Escaping ships a processable file and alters how a payee name reads; refusing blocks a legitimate payment over one character. Slice 2 escapes and records it. | Slice 2's `SEC-EXPORT-001` |
| **G-7** | **Does M7 owe screens?** `15_Agent_Implementation_Plan.md:901-1000` names none. M6 asked this and shipped none; the manager's approval view is the first surface where a *human decision* happens with no screen specified. If the answer is yes, that is a seventh slice. | Would add a slice |
| **G-8** | **What is `export_number`'s format?** `07_UI_UX_Specification.md:630-640` gives `EXP-14050427-000041`, and DOC-CONFLICT-054 already establishes that the Jalali date in that family cannot go into a stored, transported identifier under ADR-006. Slice 2 follows M6's resolution — `EXP-YYYYMMDD-NNNNNN`, Gregorian — and the same conflict row covers it. | Nothing; the resolution is already recorded |
| **G-9** | **How long is a recent-auth context valid for an approval?** `FINANCIAL_INTEGRITY_BASELINE.md` §3's closing line says the *factor and duration* remain governed by open `ADR-009`. Slice 1 must pick a number to write a test. It will use the existing step-up configuration and record that ADR-009 owns the value. | Slice 1's expiry test |
| **G-10** | **Where does the "high-priority task" for a failed integrity check go?** §15.5 requires a task *and* a security event. The event has a home — `auth_events` and the audit log. There is no task table in Phase 1A. Slice 3 writes the security event and records this gap rather than inventing a queue. | Slice 3's `SVC-INTEGRITY-002` |
| **G-11** | **Is a rejection's outbox event genuinely absent?** `audit_outbox_catalog.yaml` defines `PaymentBatchVersionApproved` and no rejection event, while `command_catalog.yaml:158-170` carries `outbox_event: null` for reject — so the two agree. Recorded because M5's `AUD-REQ-002` overclaimed in exactly this shape, and confirming the agreement is cheaper than rediscovering it. | Nothing; slice 1 follows both |

| **G-12** | **`approval_invalidated` is a canonical container state that nothing can rest in.** `06_Workflows_and_State_Machines.md:793` gives it one entry arrow — `approved --> approval_invalidated: replacement/material change` — and `:794` takes it straight out again to `draft` "current replacement version editable". Since `create_replacement_version` produces an editable draft in the same transaction, a replacement passes through the state without ever being in it. The other cause, a **material change** to an already-approved batch (`:901`, `:1208`), has no command, no route and no watcher: nothing in M6 or M7 re-examines an approved batch when a request is corrected or a bank profile version is superseded. So the state is reachable in principle and unreachable in practice, and `payment_batch_version.invalidate_approval` — the manager-only permission that would express it — authorises nothing. Two possible answers: the state is a documentation artifact of the `approval_invalidated`/`draft` pair and should be recorded as unreachable, or a material-change watcher is real work that belongs to a milestone. Slice 5A implements the replacement consequence and records this rather than inventing either. | Nothing in M7; the state stays unreachable and the permission unused |

None of G-2 through G-12 blocks starting. **G-1 blocks slices 2, 3, 4 and 5B**; slices 1 and 5A are
independent of it — neither touches a file — so the milestone can proceed while the dependency
question is settled.

---

# 5. What this plan learned from M6

Recorded because the same failures are available here:

- **A gate whose input is incomplete passes.** M6 found five registry entries outside the tuple its
  own gate reads, hiding a false `catalogued=True` for two milestones. Every gate this plan adds
  must assert its own corpus is complete.
- **"Where is its route?" kills a mechanism-with-no-caller before it ships.** M6 wrote a full
  `release_allocation` command for an operation with no endpoint and no permission. M7 has two
  permissions in that position — `bank_export.quarantine` and
  `payment_batch_version.invalidate_approval` — and **both** are implemented as consequences.

  This bullet originally said they were handled differently, with invalidation built as a command
  carrying a recorded catalogue gap. Asking its own question of its own sentence is what corrected
  it: document 05 defines no invalidation route, so a command would have been the exact failure
  this bullet describes. The lesson survived the plan; the plan did not. Slice 5A's revision note
  has the evidence.
- **A disjunctive assertion can be insensitive to the removal of either guard.** M6's hash test
  said `"content hash" in text or "sum to" in text` and passed with either check deleted.
  `SVC-INTEGRITY-001`'s eight comparisons are therefore eight assertions with eight provocations,
  not one.
- **An unmandated refusal is as much a deviation as an unmandated side effect.** M5 required a
  cancellation reason §29.1 does not ask for; M6 nearly treated a validation warning as blocking.
  G-6 is the live instance here: refusing a row over a leading `=` is stricter than any document
  requires, which is why the choice is named rather than made silently.
