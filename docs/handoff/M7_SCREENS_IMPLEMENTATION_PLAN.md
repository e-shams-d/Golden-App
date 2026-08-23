# M7 Screens — The Money Path, Made Visible

Status: in progress. **Five slices, twenty-three obligations**, five questions for the owner.

Slice 0 was added after this plan merged: building slice 1 found that neither screen can be
rendered from what the API returns today, which is the finding §1.3's rule exists to produce.

Authority: `21_UI_Design_System_and_Screen_Specification.md` §12–14, which specify these screens
field by field. This plan implements a specification; it does not invent one.

## Where every section cited below lives

The prose says `§13.3`; this table is what makes that checkable. Cited once here rather than at
every mention — a sixty-character filename repeated forty times is a document nobody reads, which
the first draft of this plan demonstrated.

| Section | Line | What it specifies |
|---|---|---|
| §12 | `21_UI_Design_System_and_Screen_Specification.md:1452` | batch builder screens — **not** in this plan, see S-4 |
| §13.1 | `21_UI_Design_System_and_Screen_Specification.md:1541` | manager dashboard — **not** in this plan, see S-3 |
| §13.2 | `21_UI_Design_System_and_Screen_Specification.md:1551` | approval queue, one row per exact version |
| §13.3 | `21_UI_Design_System_and_Screen_Specification.md:1568` | approval detail, nineteen mandatory fields |
| §13.4 | `21_UI_Design_System_and_Screen_Specification.md:1590` | stale approval protection, five behaviours |
| §13.5 | `21_UI_Design_System_and_Screen_Specification.md:1600` | the approve command's five preconditions |
| §13.6 | `21_UI_Design_System_and_Screen_Specification.md:1612` | the reject command |
| §14.1 | `21_UI_Design_System_and_Screen_Specification.md:1622` | preview banner, and three prohibitions |
| §14.2 | `21_UI_Design_System_and_Screen_Specification.md:1638` | final export generation |
| §14.3 | `21_UI_Design_System_and_Screen_Specification.md:1650` | export processing states |
| §14.4 | `21_UI_Design_System_and_Screen_Specification.md:1659` | final export detail, twelve fields |
| §14.5 | `21_UI_Design_System_and_Screen_Specification.md:1676` | integrity mismatch, and "no download anyway" |
| §14.6 | `21_UI_Design_System_and_Screen_Specification.md:1686` | the download sentence, verbatim |
| §14.7 | `21_UI_Design_System_and_Screen_Specification.md:1694` | mark sent, ten confirmation fields |
| §15 | `21_UI_Design_System_and_Screen_Specification.md:1713` | bundle upload — M8's, not this plan's |

The other authorities this plan leans on:
`15_Agent_Implementation_Plan.md:936` (a preview stays non-sendable),
`15_Agent_Implementation_Plan.md:978` (mark-sent targets an exact export),
`15_Agent_Implementation_Plan.md:989` ("downloading does not mean sent"),
`05_API_Specification.md:1398` (the approval view),
`05_API_Specification.md:1443` (the content-hash precondition),
`05_API_Specification.md:1514` (revalidation and quarantine),
`04_Database_Schema.md:1038` (§11.8's export record), and
`MONEY_TIME_CONTRACT.md:17` (integer strings on the wire).

---

# 1. Why this exists now

## 1.1 G-7, answered

Every milestone plan since M6 asked whether the batch and approval surfaces owe screens, and none
got an answer. M7's G-7 recorded the consequence rather than guessing.

The consequence has now arrived in full. **M6 and M7 built the entire money path — batching,
splitting, immutable versions, manager approval, the bank file, download, mark-sent — and none of
it is reachable from a browser.** The admin app has eight screens and the trader eleven; none goes
past the payment-request level. A demonstration of this platform today shows a trader filing a
request and an accountant reviewing it, and stops.

**The work is specified, which is what makes it startable.** §13.3 lists nineteen mandatory fields for the approval detail. §14.1 gives the preview banner's
exact words. §14.5 says "no 'download anyway' option". This is not a design exercise.

## 1.2 What the backend already answers

Nothing here needs a new endpoint, and that is deliberate — the read models were built for these
screens:

| Screen needs | Already returned by |
|---|---|
| the exact version, its rows, warnings, hash | `GET /payment-batches/{id}/versions/{id}/approval-view` |
| the prior decision, if any | the same response's `prior_decision` |
| whether an export may be sent | `bank_export.sendable` |
| whether somebody downloaded and never confirmed | `bank_export.awaiting_send_confirmation` |
| which integrity comparisons failed | the `409` body from download and final generation |

`awaiting_send_confirmation` exists **only** for §14.6's warning. It was added in M7 slice 4 with
this plan's §2.3 in view.

## 1.3 What this plan does not build

- **No M8 surfaces.** §15's bundle upload and manual crop belong to that milestone.
- **No new API.** If a screen needs a field the API does not return, that is a finding to record,
  not a route to add in a frontend slice.
- **No trader-facing view of a batch.** A batch has no trader; §12–14 are entirely internal.

---

# 2. Decisions this plan makes

## 2.1 The prohibitions are obligations, and they are tested as absences

§14.1: a preview "must not offer: mark as sent; official checksum as final; send-ready status".
§14.5: "no 'download anyway' option".

These are the most valuable assertions in the milestone and the easiest to lose. A screen that
grew a "send anyway" button would pass every positive test — the fields would still render, the
happy path would still work — and the only thing that would notice is a test that asserts the
control is **not there**.

The pattern is M7 slice 6A's break-glass gate: name the prohibition, assert the absence, and add a
negative control that puts the forbidden thing back to prove the assertion can fail.

## 2.2 Stale protection is the screen's whole reason for existing (§13.4)

Five requirements: block the command, show a prominent banner, link to the current version, keep
the old page as read-only history, and **do not transfer the open dialog to the new version**.

The last is the one worth stating. A manager with an approval dialog open when somebody replaces
the version underneath them must not have that dialog quietly re-target — they would confirm a
decision about content they never saw. The backend already refuses it (`SVC-APPROVAL-001` compares
the hash), so this is defence in depth: the server would reject it, and the screen must not offer
it.

## 2.3 "Downloading is not sending" gets a sentence, not an inference (§14.6)

The specification gives the words. This plan renders them verbatim rather than paraphrasing,
because `15_Agent_Implementation_Plan.md:989` makes this the milestone's central human-factors
risk and the wording is the mitigation.

`awaiting_send_confirmation` drives a visible reminder wherever an export appears. A screen that
merely omitted a timestamp would satisfy nothing.

## 2.4 §14.5's "urgent review task" cannot be built (G-10 again)

The specification says a quarantined export must "create/link urgent review task". There is no
task table in Phase 1A — M7 recorded this as G-10 and it is unchanged. The screen shows each
failed check and blocks both download and mark-sent, which is four of §14.5's five requirements.
The fifth is recorded as an uncovered obligation with its reason, in `RECORDED_GAPS`, rather than
being satisfied by a link to nothing.

## 2.5 §14.3 lists export states the catalogue does not have

The specification names `requested` and `superseded`. `status_catalog.yaml`'s `bank_export`
aggregate has neither — this is DOC-CONFLICT-016, already Open, and M7's G-3 records the
substantive half.

The screens render the eight canonical states. `requested` has no row to render (an export exists
only once its file does, per §1 of the baseline), and `superseded` is G-3's question. Rendering a
state the API can never return would be a screen written against a document rather than against
the system.

---

# 3. Slices

Each slice is one pull request. `### What proves it` is the section the traceability gate parses.

## Slice 0 — The reads the screens need, which do not exist

**Added after the plan was merged, because building slice 1 found the gap the plan's own rule was
written to find.** §1.3 says: "If a screen needs a field the API does not return, that is a finding
to record, not a route to add in a frontend slice." This is that finding, and it is larger than a
field.

### What the survey showed

`BatchListEntry` returns four values. §13.2 requires **ten columns**, and its first sentence is the
one that matters: "Each row must identify the exact version, not only the logical batch." The
version is not among the four.

| §13.2 asks for | Returned today |
|---|---|
| batch reference, total, row count | yes |
| **version** | **no** |
| bank, source account, mapping version | no |
| warning count, prepared/finalized by, age | no |

`ApprovalView` is closer and still short: eleven of §13.3's nineteen mandatory fields. The two
absences that matter most are **finalizer identity** and **separation-of-duty status** — a screen
built to let a manager decide cannot show them who finalized the version, which is the exact actor
the guard compares them against.

### Why this is a backend slice and not three lines of frontend

A screen that rendered eleven of nineteen fields would fail `UI-APPROVAL-001`, which asserts the
list **parsed from the specification**. Softening that assertion to match what the API happens to
return would empty the obligation — the screen would then be checked against itself.

### What it changes

- `BatchListEntry` gains the current version's identity and the human-readable values §13.2 names.
  **Names, not ids**: a queue row showing a UUID for "prepared by" is a row nobody can read.
- `ApprovalView` gains the eight missing fields, including the counts §13.3 asks for and the
  finalizer's identity.
- A `status` filter on the list, so "the approval queue" is a queue and not the whole history.

### What proves it

- `API-APPROVALREAD-001` — every column §13.2 names is present in the list response, asserted by
  parsing the specification's list. The same parse `UI-APPROVAL-002` will use, so the screen and
  the API are held to one source.
- `API-APPROVALREAD-002` — every field §13.3 names is present in the approval view, parsed the
  same way. Where the field is a count, it is computed from the version's own items rather than
  read from a live table — a trader count taken from `traders` would drift from what the version
  froze.
- `API-APPROVALREAD-003` — the separation-of-duty status is **actor-dependent** and says which
  rule would refuse: this viewer prepared it, finalized it, or may decide. Asserted for all three
  actors, because a status that only ever said "may decide" would render on the screen of somebody
  who cannot.
- `API-APPROVALREAD-004` — the queue filter returns only versions awaiting a decision, and the
  unfiltered list still returns everything. A filter that silently became the only view would hide
  the history §13.4 requires to stay readable.

### Negative controls

Drop one column from the list: `API-APPROVALREAD-001` must fail, naming it. Report "may decide" for
the finalizer: `API-APPROVALREAD-003` must fail. Compute the trader count from `traders` rather
than the version's items: `API-APPROVALREAD-002` must fail once the version's rows and the live
table disagree.

## Slice 1 — The approval queue and detail

### Goal

A manager sees what is waiting, opens one, and reads every field §13.3 makes mandatory.

### What it changes

- `apps/admin-web/app/batches/page.tsx` — the approval queue (§13.2), one row per **version**.
- `apps/admin-web/app/batches/[batchId]/versions/[versionId]/page.tsx` — the detail (§13.3).
- The navigation entry, behind `payment_batch_version.read_approval_view`.

### What proves it

- `UI-APPROVAL-001` — every one of §13.3's mandatory fields is rendered, asserted by **parsing the
  specification's list** rather than by a hand-copied one. A transcription can omit the same field
  the screen omits.
- `UI-APPROVAL-002` — the queue identifies the exact **version**, not only the batch (§13.2's
  first sentence). A row that showed a batch reference alone would be the defect this sentence
  exists to prevent.
- `UI-APPROVAL-003` — the screen is reachable only with `read_approval_view`, and the navigation
  entry is absent without it. `tests/backend/test_m3_definition_of_done.py` proves the route;
  this proves the surface.
- `UI-APPROVAL-004` — against no backend the screen renders its failure state with a level-one
  heading and a live region, and is included in the a11y sweep's fixed path list.

### Negative controls

Drop one mandatory field: `UI-APPROVAL-001` must fail, naming that field. Show the batch reference
without the version: `UI-APPROVAL-002` must fail.

## Slice 2 — Approve, reject, and the stale banner

### Goal

The manager decides, and cannot decide about something they are no longer looking at.

### What it changes

- The approve and reject dialogs (§13.5, §13.6), both requiring explicit confirmation.
- The recent-auth step, which the approve command needs and reject also needs.
- The stale banner and its five behaviours (§13.4).

### What proves it

- `UI-APPROVE-001` — the dialog sends the exact version id and the expected content hash it was
  rendered with, never a value re-read at submit time. §13.5's "expected content hash" is
  meaningless if the page refreshes it.
- `UI-APPROVE-002` — the UI updates only after authoritative server success (§13.5's closing
  line). An optimistic update here would show an approval that did not happen.
- `UI-STALE-001` — when the version is no longer current, the command is blocked, the banner
  shows, the current version is linked, and the page stays readable. Four assertions, not one.
- `UI-STALE-002` — an open dialog is **not** transferred to the replacement version (§13.4's last
  clause), asserted by replacing the version while the dialog is open.
- `UI-REJECT-001` — rejection requires a reason and says the version is not edited (§13.6).

### Negative controls

Re-read the hash at submit time: `UI-APPROVE-001` must fail. Update the UI before the response:
`UI-APPROVE-002` must fail. Re-target the open dialog: `UI-STALE-002` must fail.

## Slice 2B — The export reads, which are short by the same amount

**Added after slice 2, by running §1.3's rule against §14 before writing a screen against it.**
Slice 0 was this finding for the approval view; this is the same finding for the export detail, and
it is worth saying that the rule caught it the second time without anybody having to remember.

### What the survey showed

`ExportDetail` returns fifteen fields. §14.4 requires twelve items and §14.7 requires ten, and the
overlap is not the point — five things are missing, and two of them are missing from the *system*
rather than from the response.

| §14.4 asks for | Returned today |
|---|---|
| checksum, generation time, row count, total | yes |
| exact version | id only — no batch number, no version number |
| file name, mapping, source account | on the row or one join away; not in the response |
| approval/hash match | both hashes are returned; the comparison is not |
| integrity state | the status, but not *which* checks failed |
| **generator version** | **nowhere in the system** |
| **download history** | one timestamp, not a history |

§14.5's "show each failed check" is the sharpest of these. `_quarantine` writes each failed
comparison to `audit_events.new_values.failed_checks` and nowhere else, and no endpoint returns
audit rows — so the screen §14.5 specifies cannot be rendered at all today, not merely rendered
short.

### Why this is a backend slice, again

The same reason as slice 0: `UI-EXPORT-001` asserts every field §14.4 lists, **parsed from the
specification**. An API that returns eight of twelve leaves two options — widen the API, or soften
the assertion until the screen is checked against itself. The second is how a green gate comes to
cover unwritten work.

### What it changes

- `ExportDetail` gains the file name, the batch and version numbers, the mapping and profile
  versions, the source account, and the approval/hash comparison as a decided boolean. **Names and
  numbers, not ids**, for slice 0's reason.
- A `failed_checks` field, populated for a quarantined export from the integrity re-evaluation
  rather than by parsing the audit row back out. The audit row is the record of *what happened*; a
  screen needs the current comparison, and re-running eight pure checks is cheaper than reading it.
- The mark-sent response echoes the `submission_channel` and `note` it just recorded. **Not new
  columns** — §11.8 has none and inventing them is the schema drift this milestone guards hardest
  against. The route has both values in hand at the moment §14.7's confirmation is shown.

### What proves it

- `API-EXPORTREAD-001` — every item §14.4 lists is present in the export detail, asserted by
  parsing the specification's list. The same parse `UI-EXPORT-001` will use.
- `API-EXPORTREAD-002` — a quarantined export returns each failed check, named, and a healthy one
  returns none. Both halves: a field that always returned every check would render a scary screen
  over a sound file.
- `API-EXPORTREAD-003` — the approval/hash match is **computed against the version**, not reported
  from the export's own copy of the hash. An export that carried the wrong hash would otherwise
  agree with itself.
- `API-EXPORTREAD-004` — every item §14.7 lists is present in the mark-sent response, including the
  channel and note, and the subsequent `GET` is asserted **not** to carry them. The asymmetry is
  real and a test that ignored it would let somebody build a screen that reads them later.

### Negative controls

Drop one item from the detail: `API-EXPORTREAD-001` must fail, naming it. Return the export's own
`content_hash` as the match: `API-EXPORTREAD-003` must fail once the export and the version
disagree. Return an empty `failed_checks` for a quarantined export: `API-EXPORTREAD-002` must fail.

### What it does not build

Generator version and download history. Both are S-6 and S-5 — questions, not fields — and a
response field invented for either would be a placeholder, which §1 of the baseline forbids by
name.

## Slice 3 — Export screens, and the things they must not offer

### Goal

A preview is visibly not sendable, a final export shows its provenance, and a quarantined one
offers no way out.

### What it changes

- The preview screen with §14.1's verbatim banner.
- The final export detail (§14.4) and its states (§14.3).
- The integrity-mismatch view (§14.5).

### What proves it

- `UI-PREVIEW-001` — the banner text is rendered **verbatim** from the specification, parsed from
  the document rather than transcribed.
- `UI-PREVIEW-002` — a preview offers no mark-as-sent control, presents no checksum as official,
  and shows no send-ready status. Three assertions of absence, one per §14.1 clause.
- `UI-EXPORT-001` — the final export detail renders every field §14.4 lists, parsed from the
  specification.
- `UI-INTEGRITY-001` — a quarantined export blocks download and mark-sent and **shows each failed
  check**, using the comparison names the `409` body carries.
- `UI-INTEGRITY-002` — there is no "download anyway" control, anywhere, asserted over the whole
  export surface rather than the one screen. §14.5.

### Negative controls

Paraphrase the banner: `UI-PREVIEW-001` must fail. Add a mark-sent button to the preview:
`UI-PREVIEW-002` must fail. Add a "download anyway" control: `UI-INTEGRITY-002` must fail.

## Slice 4 — Download, mark sent, and the sentence that prevents a lost payment

### Goal

The accountant takes the file and comes back to say they sent it — and is told, in words, that the
first is not the second.

### What it changes

- The download control with §14.6's verbatim sentence.
- The mark-sent confirmation with §14.7's ten fields.
- The reminder driven by `awaiting_send_confirmation`.

### What proves it

- `UI-DOWNLOAD-001` — §14.6's sentence is rendered verbatim next to the download control, parsed
  from the specification.
- `UI-SENT-001` — the confirmation shows all ten fields §14.7 lists before the command is sent.
- `UI-SENT-002` — an export that was downloaded and not confirmed is visibly awaiting
  confirmation, driven by the field the API returns rather than by a client-side inference.
- `UI-SENT-003` — the command targets the exact export id (§14.7's closing line), asserted by
  rendering two exports of the same batch and confirming one.
- `TRACE-SCREENS-001` — every screen this plan adds is in the a11y sweep's fixed path list, and
  the list is compared against the routes that exist. A screen outside that list is a screen
  nobody checks.

### Negative controls

Paraphrase the sentence: `UI-DOWNLOAD-001` must fail. Derive the reminder client-side from a null
timestamp: `UI-SENT-002` must fail. Target the batch instead of the export: `UI-SENT-003` must
fail.

---

# 4. What the owner must settle

| ID | Question | Blocks |
|---|---|---|
| **S-1** | **Is Toman shown, and at what rate?** §13.3 requires "total IRR and Toman equivalent". Toman is IRR ÷ 10 by definition, so no rate is involved — but `MONEY_TIME_CONTRACT.md` requires transported values to be base-10 integer strings in IRR, and a displayed Toman figure is a *rendering*. This plan divides by ten at render time and never stores or transmits Toman. Confirm that is the intended meaning of "equivalent". | Slice 1's field list |
| **S-2** | **What is a "content hash fingerprint"?** §13.3 asks for a fingerprint rather than the hash. A 64-character digest is unreadable on a screen; a truncation is a decision about how much collision resistance a human comparison needs. This plan shows the first twelve characters with the full value available, and records it. | Slice 1's rendering |
| **S-3** | **Does the approval queue need the manager dashboard (§13.1) too?** It lists five aggregate figures — value awaiting approval, warning count, age of the oldest item, sensitive corrections. Four of the five are computable from the existing list endpoint; "sensitive corrections awaiting review" is a concept no API returns and no document defines further. This plan builds the queue and **not** the dashboard, and records the absence. | Would add a slice |
| **S-4** | **Is a screen owed for batch creation (§12)?** §12 specifies the batch builder — the accountant's selection surface. It is M6's backend and this plan does not cover it, because the manager's approval is the part with no visible surface *at all*. An accountant can already reach the request queue; they cannot currently build a batch from it. | Would add two slices |
| **S-5** | **Who may see the download history (§14.4)?** "download history where permitted" names a permission that does not exist: `bank_exports` records `downloaded_at` only, not a history, and no catalogue entry governs who reads it. This plan shows the single timestamp and records the rest as absent. | Slice 3's field list |

| **S-7** | **One of §15.5's eight integrity checks cannot fail in production, and slice 2B is about to display it.** `source_account_matches_approved_account` compares `facts.version_bank_account_id` against `facts.export_bank_account_id` — and `_facts_for` fills the second from `version.bank_account_id`, because `bank_excel_exports` has no account column. Both sides are the same value, so the comparison always holds. `app/exports/integrity.py` takes flat values, so its unit tests *can* construct a failing case and do; the check is inert only for stored rows, which is where it matters. This is not a gap slice 2B creates, but it is one slice 2B makes visible: a screen listing "8 checks passed" over a comparison that cannot fail is a false assurance about which account the money leaves from. Either §11.8 gains `bank_account_id` on the export, or the check is recorded as structurally satisfied by the version link and removed from the eight. **This plan neither fixes nor hides it** — the field returns what the checks return, and this row is the record. | Nothing; it makes an existing check honest |
| **S-6** | **Where does §14.4's "generator version" come from?** It exists nowhere: §11.8 gives `bank_excel_exports` no column and `app/exports/` has no version constant. A constant read at request time would name the *current* writer, not the one that produced the file — the opposite of what the field is for, since its only use is explaining why an old export looks different from a new one. Either §11.8 gains a column, in the milestone where schema drift is most guarded against, or this is an uncovered obligation with its reason. This plan does the second and records it. | Slice 2B's field list; slice 3's screen |

None of S-1 through S-7 blocks starting. S-3 and S-4 would each *add* work rather than change what
is planned. S-5 and S-6 are the two items slice 2B deliberately leaves out of the response: both
are answerable only by a schema or permission decision, and a field invented to fill either would
be the placeholder `FINANCIAL_INTEGRITY_BASELINE.md` §1 forbids by name.

S-7 is the only one of the seven that is a **defect rather than a question**, and it was found by
reading the integrity module in order to display it. It is worth saying why it survived M7's gates:
`SVC-INTEGRITY-001` requires each of the eight comparisons to have its own failing case, and each
does — the facts are flat values, so a unit test can make any of them disagree. What no gate asked
was whether the *caller* can produce facts in which each comparison can disagree. That is the same
shape as "a gate whose input is incomplete passes", one level up: the gate checked the comparison
and not the assembly.

---

# 5. What this plan carries forward from M7

- **A gate whose input is incomplete passes.** Every list this plan parses from the specification
  is checked for being non-empty first. M7 was caught by this twice.
- **Assert absences with a negative control.** Three of the four slices assert that a control is
  *not* present, and each has a sabotage that puts it back.
- **Parse the document; do not transcribe it.** §13.3's nineteen fields and §14.4's twelve are
  read from the specification at test time. A hand-copied list omits the same field the screen
  omits, which is how M5 shipped a wrong type behind a green test.
- **Name an absent obligation, never its id.** §14.5's review task is recorded in `RECORDED_GAPS`
  by id; anything this plan cannot discharge is described in prose in the tests, because the
  traceability scanner counts any id in a test file as a citation. That has now cost eleven
  corrections.
