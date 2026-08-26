# M8 — Bank-Result Bundles, Manual Crop, and the Review Workspace

Bring bank-returned evidence into the system, and let an accountant cut a reproducible rectangle
out of it without AI. `15_Agent_Implementation_Plan.md:1012`.

## Where every section cited below lives

The prose says `§16 :1044`; this table is what makes that checkable. Each line is cited once here
rather than at every mention, because a sixty-character path repeated forty times is a document
nobody reads — the screens plan learned that the hard way and this follows its shape.

**Short forms used throughout: `§16` is document 15's milestone section, `doc 04` the schema, `doc
05` the API specification, `doc 08` the bank-file document.**

| Cited as | Full citation | What it specifies |
|---|---|---|
| §16 `:1012` | `15_Agent_Implementation_Plan.md:1012` | the milestone's goal |
| §16 `:1016` | `15_Agent_Implementation_Plan.md:1016` | the nine required entities and services |
| §16 `:1028` | `15_Agent_Implementation_Plan.md:1028` | the review workspace's eleven items |
| §16 `:1039` | `15_Agent_Implementation_Plan.md:1039` | keyboard-accessible controls |
| §16 `:1044` | `15_Agent_Implementation_Plan.md:1044` | the ten things crop creation must do |
| §16 `:1057` | `15_Agent_Implementation_Plan.md:1057` | the three things it must **not** do |
| §16 `:1065` | `15_Agent_Implementation_Plan.md:1065` | the privacy review |
| §16 `:1069` | `15_Agent_Implementation_Plan.md:1069` | the nine tests and the gate |
| §16 `:1081` | `15_Agent_Implementation_Plan.md:1081` | the Definition of Done |
| doc 04 `:1170` | `04_Database_Schema.md:1170` | `bank_result_bundles` fields and CHECKs |
| doc 04 `:1179` | `04_Database_Schema.md:1179` | the counts are cached, not financial truth |
| doc 04 `:1181` | `04_Database_Schema.md:1181` | `bank_result_bundle_files` |
| doc 04 `:1191` | `04_Database_Schema.md:1191` | `file_role`'s four values |
| doc 04 `:1193` | `04_Database_Schema.md:1193` | `bank_result_bundle_batch_links` |
| doc 04 `:1199` | `04_Database_Schema.md:1199` | a link does not prove payment |
| doc 04 `:1201` | `04_Database_Schema.md:1201` | `receipt_segments`, column by column |
| doc 04 `:1240` | `04_Database_Schema.md:1240` | the bbox CHECK, all-null or in bounds |
| doc 04 `:1249` | `04_Database_Schema.md:1249` | the five creation methods |
| doc 04 `:1259` | `04_Database_Schema.md:1259` | manual crop is Phase 1A; AI is flagged off |
| doc 04 `:1312` | `04_Database_Schema.md:1312` | `manual_review_tasks` — M7's G-10 answered |
| doc 04 `:1317` | `04_Database_Schema.md:1317` | its two indexes |
| doc 04 `:1324` | `04_Database_Schema.md:1324` | entity refs are queue navigation only |
| doc 05 `:1676` | `05_API_Specification.md:1676` | the two bundle reads |
| doc 05 `:1685` | `05_API_Specification.md:1685` | batch links |
| doc 05 `:1693` | `05_API_Specification.md:1693` | start review |
| doc 05 `:1700` | `05_API_Specification.md:1700` | close |
| doc 05 `:1721` | `05_API_Specification.md:1721` | AI extraction — **not** in this plan |
| doc 05 `:1733` | `05_API_Specification.md:1733` | external evidence, the crop-free method |
| doc 05 `:1756` | `05_API_Specification.md:1756` | the crop request, which omits rotation |
| doc 05 `:1786` | `05_API_Specification.md:1786` | `202` with a job; the source stays immutable |
| doc 05 `:1791` | `05_API_Specification.md:1791` | get and patch a segment |
| doc 05 `:1795` | `05_API_Specification.md:1795` | patch only before finalization, with `If-Match` |
| doc 05 `:2058` | `05_API_Specification.md:2058` | the six manual-review routes |
| doc 08 `:137` | `08_Bank_File_and_Result_Processing.md:137` | an original is never overwritten |
| doc 08 `:395` | `08_Bank_File_and_Result_Processing.md:395` | the derivation kinds |
| doc 08 `:431` | `08_Bank_File_and_Result_Processing.md:431` | what a derivation stores |
| doc 08 `:975` | `08_Bank_File_and_Result_Processing.md:975` | Phase 1A includes a minimal crop tool |
| doc 08 `:979` | `08_Bank_File_and_Result_Processing.md:979` | the seven preview capabilities |
| doc 08 `:985` | `08_Bank_File_and_Result_Processing.md:985` | rotation is a preview control |
| doc 08 `:989` | `08_Bank_File_and_Result_Processing.md:989` | the crop input, **with** rotation |
| doc 08 `:1011` | `08_Bank_File_and_Result_Processing.md:1011` | crop provenance, **with** rotation |
| doc 08 `:1031` | `08_Bank_File_and_Result_Processing.md:1031` | the crop workflow, request before file |
| doc 08 `:1044` | `08_Bank_File_and_Result_Processing.md:1044` | crop failure |

Also leaned on: `FINANCIAL_INTEGRITY_BASELINE.md:1` (§1's no-placeholder rule),
`docs/governance/status_catalog.yaml:384` (the `bank_result_bundle` aggregate), and
`CONFLICT_REGISTER.md:83` (DOC-CONFLICT-057, which §2.1 files).

---

# 1. What exists, and what does not

## 1.1 The tables are specified and none are built

doc 04 §12 and §13 define six: `bank_result_bundles` (`:1170`), `bank_result_bundle_files`
(`:1181`), `bank_result_bundle_batch_links` (`:1193`), `receipt_segments` (`:1201`),
`matching_candidates` and `confirmed_evidence_links` — plus `manual_review_tasks` (`:1312`).

**M8 builds four of them.** `matching_candidates` and `confirmed_evidence_links` are M9: §17 makes
candidates and confirmation the *separated human decisions*, and building a suggestion table with
no decision to feed would be a mechanism with no caller — the defect this repository has produced
in every milestone.

## 1.2 M7's G-10 was wrong, and this plan corrects it

M7 recorded G-10 as "there is no task table in Phase 1A", and used it to justify not building
§14.5's "create/link urgent review task" for a quarantined export. **doc 04 `:1312` specifies
`manual_review_tasks`**, with two indexes and no later-phase marker, and doc 05 `:2058` gives it six
routes. The table was never a design gap; it was unbuilt work, and M8 is where it is scheduled.

So slice 3 owes a debt: once the queue exists, M7's quarantine path should create a task, and the
record of it has to go — which turned out to be a docstring rather than a `RECORDED_GAPS` entry, and
slice 3 records the correction. A recorded gap whose reason has expired is worse
than no gap at all — it reads as considered.

## 1.3 The worker has never run a real job

`app/workers/tasks/files.py` is thirteen lines and empty by design: the module exists so that the
first task defined in it routes to the `files` queue instead of landing silently on `maintenance`.
M8's crop render is that first task.

`processing_jobs` — an M2 table — has the catalogue's richest lifecycle (`queued`, `running`,
`succeeded`, `failed`, `retry_scheduled`, `cancelled`, `dead_lettered`, `fallback_to_manual`) and
no application caller. **Slice 4 is its first**, which is the same shape as M6 slice 3 becoming
`lock_rows()`'s first caller two milestones after it was written.

## 1.4 What this plan does not build

- **Matching and confirmation** (§17). M9.
- **Publication to a trader** (§17). M9, and §16 `:1057` forbids crop creation from doing any of
  it: it must not confirm evidence, mark an attempt paid, or publish.
- **AI segmentation.** doc 04 `:1259`: `manual_in_panel_crop` is Phase 1A and
  `ai_auto_segmentation` stays feature-flagged. doc 05 `:1721` defines an `ai-extraction` route
  and this plan does not add it.
- **Excel row preview.** doc 08 `:979` asks for it "where a deterministic parser exists" and none
  does; `BANK-VER-005` already records that absence.

---

# 2. Decisions this plan makes

## 2.1 Rotation is a hole in three documents, and it breaks reproduction (Q-1)

This is the finding that matters most, and it was found by reading the three documents against each
other rather than in turn:

| Document | Says about rotation |
|---|---|
| doc 08 `:989` | the crop input carries `"rotation_degrees": 90` |
| doc 08 `:1011` | provenance stores `rotation_degrees: integer` |
| §16 `:1044` | crop creation must "validate normalized rectangle **and rotation**" |
| doc 05 `:1756` | the request body has **no rotation field** |
| doc 04 `:1201` | `receipt_segments` has **no rotation column** |

**Why it is not cosmetic.** §16 `:1069` requires that "normalized coordinates reproduce the same
crop within approved tolerance". If an operator rotates a scanned page 90° and *then* draws a
rectangle, the normalized coordinates are relative to the rotated page. Store the rectangle without
the rotation and the same four numbers describe a different region of the same file — so the stored
crop is not reproducible from its own provenance, which is the one property the whole table exists
to have.

**This plan follows doc 08 and doc 04 gains the column**, because doc 08 is the only document that
states the requirement rather than omitting it, and because §16 `:1044` independently requires
rotation to be validated — which is impossible if it is never sent. Recorded as **Q-1** and as a
new conflict-register row; the migration adds `rotation_degrees` with a CHECK constraining it to
the four right angles doc 08's preview supports.

**Slice 4 found the governance answer, and it was there all along.** `command_catalog.yaml:277` — the
approved command row for `receipt_segment.create_crop` — lists its preconditions as:

    "preconditions": ["normalized_rectangle", "page", "rotation", "renderer_version",
                      "derived_checksum"]
    "status": "blocked_by_coordinate_rotation_contract"

So M0 **requires the rotation** and names its absence from doc 05's request schema as the reason the
command is blocked. Q-1 was decided correctly on the documents' own merits, but it did not have to be
a judgement call: a sixth source settles it, and the row this milestone unblocks is the row that says
so. Two lessons worth carrying: the command catalogue is a source of truth about *contracts* and not
only about permissions, and a `status` field on a catalogue row can record a blocker that no
conflict register mentions.

**Demonstrated, not argued.** `tests/integration/test_segment_intake.py` re-renders a stored crop
from the row alone and gets the byte-identical file back, then renders the same rectangle at 0° and
gets a *different* image. The second assertion is the one that makes the first mean anything: if
forgetting the angle produced the same picture, there would be no conflict to file.

## 2.2 A segment pending render rests in `created`, not in a new state (Q-2)

doc 08 `:1031` has the segment created before its file exists: *save segment request → worker
renders → verify checksum → available*. The catalogue's `receipt_segment` states are `created`,
`unmatched`, `candidate_found`, `confirmed_linked`, `published`, `superseded`, `voided` — and
`processing`, the obvious name for that window, is an **unresolved alias**, not canonical.

This plan does not invent a state. The segment stays `created` and the *job* carries the render's
progress, which is what `processing_jobs` is for. §16 `:1069`'s "failed render leaves no active
evidence" then has a precise meaning: `segment_file_id IS NULL` and the job is `failed`, so nothing
downstream can treat it as evidence — M9's matching reads segments that have a file.

The cost is that `created` means two things, and a screen must say which. Recorded as **Q-2**; it
does not block, because the alternative is an M0 catalogue change and this reading needs none.

## 2.3 "Approved tolerance" has no value anywhere (Q-3)

§16 `:1069` requires reproduction "within approved tolerance" and no document approves one. A crop
is a rectangle of pixels; the sources of drift are rounding normalized coordinates to integer
pixels and the renderer's own rasterisation at a given DPI.

This plan asserts **exact byte equality of the derived file** for a re-render at the same renderer
version, DPI and rotation, which needs no tolerance and is the stronger claim. Tolerance only
becomes necessary across renderer versions, and that comparison is what `renderer_version` exists
to make possible rather than to paper over. Recorded as **Q-3**.

## 2.4 The renderer is a new production dependency and a licence decision (Q-4)

Nothing in the dependency list can open a PDF. `openpyxl` was M7's G-1 and the owner answered it;
this is the same question with a sharper edge, because the leading library is licensed in a way that
matters.

| Candidate | Licence | Shape |
|---|---|---|
| **pypdfium2** | Apache-2.0 / BSD-3 | wraps Google's PDFium; manylinux wheels ship the native library, so no compiler on the target |
| PyMuPDF | **AGPL-3.0** or paid commercial | fastest and most capable, and AGPL is a legal decision for a closed product |
| pdf2image | MIT wrapper | shells out to `poppler-utils`; adds a system package to the image, not a wheel |

**Recommendation: `pypdfium2` for PDF pages and `Pillow` for raster crop and rotation.** Apache-2.0
and HPND respectively, both vendorable as wheels for a network that cannot reach a registry — which
`wsl-environment-gotchas` and the Iran-only constraint make a hard requirement rather than a
preference.

This is weaker than M7's openpyxl precedent in one stated way and the plan says so: openpyxl was
chosen partly because `find .venv/lib -name '*.so'` found nothing for it. Neither of these is pure
Python. What is preserved is the property that mattered — no build step on the target — and what is
lost is the audit simplicity of a dependency with no native code at all.

**Q-4 blocks slices 4, 5 and 6 and blocks none of 1, 2 or 3.** Slice order follows from that, the
way M7's did.

## 2.5 Privacy review records a verification; it cannot gate publication yet

§16 `:1065`: before evidence is included in publication, the operator must verify the crop reveals
no unrelated names, IBANs, amounts, tracking references or transactions.

Publication is M9. So M8 records the verification — who, when, and against which segment — and M9's
publication path reads it. This plan does **not** write a publication guard, because a guard on a
path that does not exist is untestable and would be the eighth mechanism with no caller.

What M8 *can* assert is the absence of a way round it: no route this milestone adds may mark a
segment publishable, and slice 7 asserts that over the whole surface.

## 2.6 Counts are cached, and a cached count is a thing that drifts

doc 04 `:1179` is explicit: `segment_count`, `resolved_segment_count` and `unresolved_segment_count`
are cached read values, "recomputed/validated transactionally from segments/tasks", and "not
independent financial truth".

They are therefore recomputed in the same transaction that changes a segment, never incremented.
An increment is correct until the first retry, and this repository already has the pattern for
this: M7's approval view computes its three counts from the version's own items rather than reading
a live table.

---

# 3. Slices

Each slice is one pull request. `### What proves it` is the section the traceability gate parses.
Slices 1–3 need no answer to Q-4.

## Slice 1 — The bundle, its files, and the batches it may point at

### Goal

An accountant uploads what the bank returned, and the system knows what it is without claiming
anything was paid.

### What it changes

- `bank_result_bundles`, `bank_result_bundle_files` and `bank_result_bundle_batch_links` (doc 04
  `:1170`, `:1181`, `:1193`), with `bundle_number` unique and the three count CHECKs.
- `POST /bank-result-bundles` and its file attachment, reusing M4's `file_objects` — doc 08 `:137`
  forbids overwriting an original, so a bundle file is a link to an existing uploaded file, never a
  copy.
- `POST /bank-result-bundles/{id}/batch-links` (doc 05 `:1685`), `start-review` (`:1693`) and
  `close` (`:1700`).
- The two reads doc 05 `:1676` defines.

### What proves it

- `DB-BUNDLE-001` — the three tables match doc 04's field lists and every constraint it states,
  asserted against the migrated database rather than the model.
- `SVC-BUNDLE-001` — a bundle links to a batch and the link **proves nothing about payment**. doc
  04 `:1199` says so in its own words; the test asserts no attempt or batch status changes when a
  link is created, which is the only way that sentence can be checked.
- `SVC-BUNDLE-002` — `file_role` accepts exactly doc 04 `:1191`'s four values and the two
  uniqueness constraints hold, including the one on `(bundle, sequence_number, file_role)` that
  allows a source and a preview to share a sequence number.
- `SVC-BUNDLE-003` — the counts are recomputed, not incremented, and a second call in the same
  transaction produces the same numbers.
- `API-BUNDLE-001` — the reads carry what a review workspace needs, parsed from §16 `:1028`'s list
  rather than transcribed. The same parse slice 6 uses.
- `SEC-BUNDLE-001` — a trader cannot reach any bundle route. §16 `:1069`'s seventh test.

### Negative controls

Increment a count instead of recomputing: `SVC-BUNDLE-003` must fail after a retry. Let a batch
link set the batch's status: `SVC-BUNDLE-001` must fail. Grant a trader `bank_result_bundle.read`:
`SEC-BUNDLE-001` must fail.

## Slice 2 — Segments that are records, before any of them are pictures

### Goal

The evidence table exists and the creation method that needs no renderer works end to end.

### What it changes

- `receipt_segments` (doc 04 `:1201`), including the bbox CHECK at `:1240` verbatim and — per §2.1
  — a `rotation_degrees` column doc 04 does not yet list.
- `POST /bank-result-bundles/{id}/receipt-segments/external` (doc 05 `:1733`): the
  `manual_external_attachment` method, which attaches a whole file as evidence and crops nothing.
- `GET /receipt-segments/{id}` (doc 05 `:1791`). **Not `PATCH`** — see the amendment below.

### Amended while building: the `PATCH` is forbidden, not merely unbuilt

This section originally planned a guarded `PATCH /receipt-segments/{id}` with the finalization rule
doc 05 `:1795` states. `permission_catalog.yaml` settles it the other way and says so in terms:
`receipt_segment.update` carries `status: unresolved_no_exact_canonical_target`,
`canonical_targets: []` and `resolution: deny until an explicitly scoped pre-finalization update
permission is approved` — and its `m0_open_items` carries `receipt_segment_update_permission` with
`conservative_effect: deny_update_until_action-specific_permission_is_approved`, citing the same doc
05 lines this plan read.

**That is an approved decision, not a silence.** It is unlike Q-6 and Q-7, which were gaps slice 1
discovered and worked around on precedent: here M0 has already ruled, and shipping the route would
have broken the ruling. A `correct_fields` command was written and deleted rather than left
unexposed, because a command whose route is forbidden by governance is the most misleading form of
the mechanism-with-no-caller defect — reviewed, tested, green, unreachable by design. Q-9.

So two obligations become **absences**, and one is added for what the slice does instead.

### What proves it

- `DB-SEGMENT-001` — doc 04 `:1240`'s CHECK at each of its edges, and this found a defect in the
  specified constraint: **three coordinates with a NULL fourth satisfies it.** The all-null branch is
  false, the in-bounds branch is NULL because a comparison against NULL is NULL, and a CHECK rejects
  only on false — so a row claiming three quarters of a rectangle is accepted and can never be
  reproduced. Closed with `num_nonnulls(...) IN (0, 4)`; **Q-11** owes doc 04 the correction. Eight
  refusals and one positive control, because eight refusals with a malformed insert would be eight
  false confirmations.
- `DB-SEGMENT-002` — `creation_method` admits doc 04 `:1249`'s five names, parsed from the document,
  and the automatic-segmentation method is unreachable through every route this milestone adds. An
  enum value with no writer is how a feature flag gets bypassed.
- `SVC-SEGMENT-001` — **no route mutates a segment**, asserted over the live route table for every
  method, with a companion test that fails when the catalogue stops refusing. An absence whose reason
  can expire needs the expiry to be a failure rather than a silence.
- `SVC-SEGMENT-002` — provenance is unwritable **at every status**, which is stronger than the
  original wording, in two independent ways: no request model accepts those fields, and the migration
  grants UPDATE on none of them. Two reasons is the right number for a rule whose failure is silent.
- `SVC-SEGMENT-003` — attaching evidence recomputes the bundle's cached counts in the same
  transaction (doc 04 `:1179`), and a bundle with unresolved segments cannot be closed. Added because
  slice 1 wrote both against a count that was always zero: this is the first slice in which either
  claim can be distinguished from a hard-coded constant.
- `SEC-SEGMENT-001` — a trader reads no internal segment, and a manager may read but not create.
  §16 `:1069`.

### Negative controls

Allow `bbox_x + bbox_width` to reach 1.000001: `DB-SEGMENT-001` must fail. Drop the all-or-nothing
constraint: `DB-SEGMENT-001` must fail on the partial rectangle §12.4 admits. Add a `PATCH` route:
`SVC-SEGMENT-001` must fail. Accept a bbox field in the creation request: `SVC-SEGMENT-002` must
fail. Reach the automatic-segmentation method through the external route: `DB-SEGMENT-002` must fail.
Increment the count instead of recomputing: `SVC-SEGMENT-003` must fail.

## Slice 3 — The review queue, and M7's expired excuse

### Goal

Work that needs a person has somewhere to be, and the gap M7 recorded closes.

### What it changes

- `manual_review_tasks` (doc 04 `:1312`) with both indexes at `:1317`.
- The six routes doc 05 `:2058` defines: list, read, assign, start, resolve, cancel.
- **M7's quarantine path creates a task.** §14.5's fifth requirement, unbuildable in M7 and
  buildable now.

### What proves it

- `DB-TASK-001` — the table matches doc 04 `:1314`, and the partial index covers exactly `open` and
  `in_progress`, asserted from the catalogue's `manual_review_task` states rather than a literal.
- `SVC-TASK-001` — the four transitions, and no other. `resolve` requires a resolution code.
- `SVC-TASK-002` — `entity_type`/`entity_id` are **queue navigation only** (doc 04 `:1324`): no
  financial read joins through them, asserted by walking the query surface for a join on those two
  columns.
- `SVC-QUARANTINE-001` — quarantining a bank export creates an open task naming that export, and a
  second revalidation of the same export finds that task rather than raising a duplicate.

  **This section originally claimed M7's `RECORDED_GAPS` entry would be removed here. There is no
  such entry.** M7 recorded the missing task in the plan's prose and in `_quarantine`'s docstring as
  G-10, and never added one to `RECORDED_GAPS` — so the cleanup this plan promised had no target.
  What was actually stale was the docstring, which said "G-10 already records the missing task
  table"; it now says the task half is built and the security-event half is not. Written down
  because a plan that claims a cleanup nobody can find is the same defect as a gap entry nobody
  removes, pointing the other way.

### Negative controls

Make `open_task` raise instead of returning the existing row: `SVC-QUARANTINE-001` must fail on the
second revalidation. Resolve without a code: `SVC-TASK-001` must fail. Join a financial read through
`entity_id`: `SVC-TASK-002` must fail. Permit `resolved → in_progress`: `SVC-TASK-001` must fail.

## Slice 4 — The renderer, the crop, and the job that does it

**Done.** Q-4 answered (`pypdfium2` + `pillow`, §2.4), Q-1 settled by `command_catalog.yaml:277`
rather than by judgement (§2.1), Q-3 answered by measurement: reproduction is byte equality, so
§16.6's "approved tolerance" needs no value.

### Goal

A rectangle drawn on a page becomes a derived file whose provenance can rebuild it.

### What it changes

- The renderer dependency, pinned with the same evidence M7 demanded of `openpyxl`: properties
  verified against a written-and-reread file before the version is fixed, not asserted in a comment.
- `POST /bank-result-bundles/{id}/receipt-segments/crop` (doc 05 `:1756`), answering `202` with a
  processing job per `:1786`.
- The `files` queue's first task, and `processing_jobs`' first caller.
- `file_derivations` rows recording operation, parameters, renderer version and checksums (doc 08
  `:431`).

### What proves it

- `SVC-CROP-001` — every one of §16 `:1044`'s ten requirements, one assertion each. Ten, because a
  single "crop works" test passes with authorization, lifecycle validation and idempotency all
  removed.
- `SVC-CROP-002` — §16 `:1057`'s three prohibitions, as absences: crop creation confirms no
  evidence, marks no attempt paid, publishes nothing. Asserted by reading the attempt and its
  publication state before and after.
- `SVC-CROP-003` — **the source file is byte-identical afterwards**, doc 08 `:137`. Measured, not
  assumed: the file is hashed before and after **through the storage service**, because M4's
  boundary obligation — the one forbidding any module outside `app/storage/` and `app/files/` from
  touching a storage key — applies here too. Its id is deliberately not written: the traceability
  scanner counts an id in a plan as that plan *stating* the obligation, so naming M4's would make a
  citation of either discharge both.
- `SVC-CROP-004` — reproduction. Re-rendering from stored provenance alone produces a
  byte-identical derived file, per §2.3. Includes a rotated page, which is the case §2.1 exists for.
- `SVC-CROP-005` — a retry does not duplicate a segment (§16 `:1069`), and a failed render leaves
  `segment_file_id` null with the job `failed`, per §2.2.
- `SVC-CROP-006` — a quarantined or unavailable source cannot be cropped (§16 `:1069`), reusing
  M4's file lifecycle rather than a second opinion about it.
- `AUD-CROP-001` — the audit and outbox records §16 `:1055` requires.

### Negative controls

Store the bbox without the rotation: `SVC-CROP-004` must fail on the rotated page — this is the
control that would have caught §2.1's gap had the documents been consistent. Write the crop over
the source: `SVC-CROP-003` must fail. Let the render succeed twice: `SVC-CROP-005` must fail.

`scripts/sabotage-m8-slice4.sh` runs those three and five more the code turned out to need: drop the
client-raster check, accept any scan status, let the renderer version drift, change the render scale,
and import `PaymentAttempt` into the crop command. **Eight of eight caught, each on its own named
assertion** — but two of them only after the control turned out to be right and the test wrong:

- **"Let the render succeed twice" reported NOT CAUGHT through the worker**, and the reason is that
  the worker's idempotency does not come from the guard being sabotaged. After a success the job is
  `succeeded`, so a second pass claims nothing and never reaches `render_pending_crop`'s
  already-rendered return. Two independent protections, and the queue-level one was hiding the
  command-level one. Fixed by calling the command directly, which is how slice 6 and any repair path
  will call it.
- **"Let the renderer version drift" could not be created by editing the source at all.**
  `RENDERER_VERSION` is read both when the request stores the provenance and when the worker renders,
  so changing the constant changes both and they still agree. Only a deploy between two moments
  produces drift, which the test now simulates from the owner connection — the only writer that
  *can*, since the runtime has no UPDATE grant on that column.

Both are the third meaning of NOT CAUGHT: the sabotage did not break the property. Neither was a weak
test and neither was a broken control; in both cases the control had found a guard whose reachable
caller was somewhere other than where the test was looking.

**The full suite found a defect the module could not.** Three of these tests passed run individually
and failed in the full run: `render_crops` claims the oldest due job on the queue, and an earlier
test requests a crop it never drains — so every later test was draining somebody else's work. Fixed
with an autouse fixture that leaves nothing claimable on the `files` queue, which makes the
precondition explicit instead of an accident of test order. This is the fourth time in this project
that verifying with a narrower command than the gate has hidden something.

### What slice 4 found

**Two mechanisms with no caller, and this slice is the first for both.** `app/files/derivation.py`
was written in M4 with `CROP` already in its `DERIVATION_TYPES`, and its own test says a preview "is
rendered in M8, and when the renderer arrives it will record its output through `record_derivation`".
Nothing outside tests had ever called it. `file_derivations.created_by_job_id` has existed since
M4's migration with **no writer at all**. That is the twelfth and thirteenth instance of this
repository's recurring shape — complete machinery nothing calls — and the useful thing is that both
were found by looking for the helper before writing one, not afterwards.

**The catalogue asymmetry is the sharp version of Q-12.** The crop is the **only** M8 command whose
permission, command row *and* audit action all exist in the approved catalogues
(`permission_catalog.yaml:537`, `command_catalog.yaml:277`, `audit_outbox_catalog.yaml:38`). Slices
1, 2 and 3 implemented eight commands under DOC-CONFLICT-052 with provisional names. So
`command_catalog.yaml` is not vaguely incomplete for the evidence path: it describes in full the one
command that needs a PDF renderer and omits `link_batch`, `create_external` and the entire review
queue. Q-12 should ask for the missing rows by name rather than for a general review.

**Requirement 8 is a check here, not a write, and slice 2 is why.** `20260824_0024` grants the
runtime no UPDATE on `renderer_version`, `source_pixel_width` or `source_pixel_height`. So
`request_crop` records the provenance and the worker *confirms* it — and a deploy between the two
makes the render refuse rather than produce a file whose row names software that did not make it.
The first draft wrote those three columns and PostgreSQL would have refused it; the constraint found
the design question.

**A float cannot be hashed, and the render scale is recorded.** `app/core/hashing.py` refuses a
float outright, so `parameters_hash` rejected `{"render_scale": 2.0}` on this slice's first
integration run. `RENDER_SCALE_TEXT = "2.0"` exists for anything that records or hashes the scale,
while the renderer keeps the float it needs. The rule generalises: `MONEY_TIME_CONTRACT.md`'s
no-float rule is not only about money — it is about any value whose exact digits are load-bearing,
and a crop's coordinates and scale are exactly that.

**Only two of §16.5's three prohibitions can be broken at M8.** `PaymentAttempt` is importable
today; `evidence_links` is M9's and trader publication is an empty queue module. The prohibition test
asserts all three and a companion test records which are live, so three passing assertions are not
read as three enforced rules. Without that companion, `SVC-CROP-002` would have been a test that
cannot fail — the third meaning of NOT CAUGHT, arriving in a test rather than in a control.

## Slice 5 — Preview: pages, zoom, rotation, and a download that stays internal

**Done.**

### What it changes

doc 08 `:979`'s list, minus the Excel row preview §1.4 explains: page images for image and text
PDFs, page navigation, and the authorized internal download.

**Mostly a connection, not a construction.** M4 built the preview *request* path —
`PREVIEWABLE_MEDIA_TYPES`, the outbox dispatch on upload, and `GET /files/{id}/preview` — and left
that route serving the **original bytes** with a comment saying a later milestone would resolve it.
Slice 4 brought the renderer; this is the resolution. So the headline change is a removal: a preview
permission stopped acting as a download permission, which is the separation doc 05 `:1045` asks for
and the placeholder quietly broke for four milestones.

**Rendered on demand, cached as a derivation, not pre-rendered on upload.** A bundle can be forty
pages and an operator opens three. On demand is also the honest shape for the request — the operator
is waiting for *this page*, so a job would only add a poll. `file_derivations`' own reproducibility
unique turns the second view into an indexed lookup. The consequence is stated rather than hidden: a
`GET` writes. It is a cache fill, it is idempotent, and when two operators open one page at once the
loser of that race reads the winner's row.

**Zoom and pan are the client's**, and that is a decision rather than an omission: they change no
bytes. A viewer scales an image it already holds, so serving them would render the same page again at
every zoom level and store a derivation for each.

**An image is not a PDF and the difference needed measuring.** doc 08 `:983` lists images beside
PDFs, so `_raster` gained an image path — placed *below* both `render_crop` and `render_page` rather
than beside them, because a JPEG receipt must be croppable too and two render paths would eventually
disagree about what the operator saw. Rotation there uses `transpose`, which permutes pixels, never
`rotate`, which resamples; and `RENDER_SCALE` is deliberately not applied, because doubling a
photograph invents pixels the scanner never recorded and the operator would draw a rectangle on an
interpolation. Four properties were measured before the path was trusted: re-render equality, a
lossless four-quarter round trip, the direction of a clockwise turn, and no upscaling.

### What proves it

- `SVC-PREVIEW-001` — a multi-page PDF and a rotated image both render (§16 `:1069`'s first test),
  with page count matching `bank_result_bundle_files.page_count`.
- `SVC-PREVIEW-002` — preview files are derived objects, never the original, with a
  `file_derivations` row each.
- `SEC-PREVIEW-001` — the preview and its download are refused to a trader and to any admin without
  the bundle permission, and no preview URL is guessable from a segment id.
- `API-PREVIEW-001` — page dimensions are returned, because a client that must send
  `client_source_dimensions` (doc 05 `:1773`) cannot invent them.

### Negative controls

Serve the source file as the preview: `SVC-PREVIEW-002` must fail. Drop the permission check on the
page route: `SEC-PREVIEW-001` must fail.

`scripts/sabotage-m8-slice5.sh` runs those two and six more: trust the caller's page count again,
resample the image rotation, reverse its direction, upscale an image by the render scale, stop
swapping rotated dimensions, and never read the derivation cache. **Eight of eight caught.**

### What slice 5 found

**Three defects, none of them in the plan.**

`bank_result_bundle_files.page_count` was **whatever the caller sent**, and nothing could check it
until slice 4 shipped a renderer. `SVC-PREVIEW-001` asks that the rendered count match that column —
against a client-supplied value, that compares the renderer with a claim, and every later screen
saying "page 3 of 7" repeats it. Now counted from the document, with a disagreeing claim refused
rather than corrected: a caller describing four pages of a three-page file is referencing a file
other than the one they mean. For a document with no pages — an Excel result, a CSV — the column stays
`NULL` and a count sent for it is refused too, because it could never be verified.

**Every bundle fixture used a file category `app/files/ownership.py` has no resolver for**
(`bank_result_bundle` where the registered purpose is `bank_result_bundle_source`), so those files
were denied to *everybody*. It went unnoticed for three slices because no test had ever previewed or
downloaded a bundle file; the first test that did found it immediately.

**`a_clean_file` created a file row with no object in storage**, which is precisely the state M2's
`records_without_a_storage_object` reconciliation exists to *find*. Harmless while nothing opened the
bytes, and a hard failure the moment attach started counting pages.

**And one test of mine was insensitive by construction.** `SEC-PREVIEW-001` written with a trader
asserted the wrong status and, worse, tested nothing: a trader holds no `file.preview` at all, so the
route's permission gate refuses them before the ownership resolver runs. `sensitive_internal_bundle`
could have done nothing whatsoever and that test would have passed. It needs a `warehouse_operator` —
the only role holding `file.preview` without `file.read_sensitive_bundle` — who gets past the gate and
must be refused by the resolver, as a `404` rather than a `403`, because a `403` there confirms the id
is real. The plan's own wording asked for both actors; only one of them exercises the code.

**A control that missed taught something too.** Breaking the rotated-dimension swap was aimed at
`API-PREVIEW-001` and caught by the *crop* tests instead: the preview headers are read off the
rendered image, not computed from `page_size`, so no arithmetic error in that function can make them
lie. `page_size` has exactly one caller that can be wrong about it, and it is the crop request's
raster check.

## Slice 6 — The review workspace

**Done.**

### What it changes

§16 `:1028`'s eleven items, as a desktop-first admin screen — **seven of them built, four recorded
absent against the contract.**

Attempt search needs `GET /api/v1/payment-attempts`, which doc 05 `:1553` specifies and nobody has
built; the candidate, evidence and history drawers need matching, evidence links and segment
history, all M9's. Four panels with nothing behind them would be worse than four absences: an empty
drawer reads as "no candidates found" rather than "this does not work yet". So the record is a live
one — `workspace-screens.test.ts` reads the generated OpenAPI contract and fails the day one of
those routes appears, which is exactly when somebody needs to be told a panel became buildable. Slice
4 used the same shape for §16.5's prohibitions; a control on it asserts every one of the eleven items
is accounted for exactly once, present or absent, so an item cannot fall out of both lists unnoticed.

**A queue screen was not in the plan and the slice needed one.** `UI-REQ-004` found
`/bank-result-bundles/[bundleId]` reachable only by typing a URL. That is not tidiness: nobody
memorises a bundle id, so a workspace with no queue is a workspace nobody opens. It sorts by
outstanding work rather than arrival, because §16.3's first item is *unresolved* navigation and the
question an operator opens it with is "what still needs me".

### What proves it

- `UI-WORKSPACE-001` — every item §16 `:1028` lists, parsed from the document. The same parse slice
  1's `API-BUNDLE-001` uses, so the API and the screen answer to one list.
- `UI-CROP-001` — the rectangle is **keyboard-operable**: §16 `:1039` requires keyboard-accessible
  controls, and a drag-only crop excludes anybody who cannot use a mouse. Numeric entry for the four
  coordinates plus arrow-key nudging, asserted as controls rather than as a pointer gesture.
- `UI-CROP-002` — the coordinates the screen sends are normalized against the dimensions it
  reports, and rotation is sent with them.
- `UI-EVIDENCE-001` — the external-evidence fallback stays reachable (§16 `:1069`'s last test), so
  a bundle nothing can render is still workable.
- `TRACE-M8-001` — every screen in the a11y sweep's fixed list. Written as the screens plan
  wrote it: compared against the routes that exist, not against the ones this plan added.

### Negative controls

Make the crop pointer-only: `UI-CROP-001` must fail. Send pixel coordinates: `UI-CROP-002` must
fail. Remove the fallback: `UI-EVIDENCE-001` must fail.

`scripts/sabotage-m8-slice6.sh` runs those three and five more: hide the fallback behind a failed
preview, invent the raster instead of reading it, cycle rotation by arithmetic, let a nudge leave the
page, and drop the queue from navigation. **Eight of eight caught — after the first run caught six.**

### What slice 6 found

**The two controls that missed were the plan's own two, and both found a weak test rather than a
weak control.**

Making the crop pointer-only reported NOT CAUGHT because the tests asserted that `onKeyDown` and the
four labelled number inputs *existed in the source*. Deleting `onKeyDown={onKeyDown}` from the JSX
leaves the `useCallback` in place, and hiding the fieldset leaves every label string in the file —
so a keyboard handler that nothing attaches and controls nobody can see both passed. That is this
repository's recurring defect wearing a frontend costume: complete machinery with no caller. The
tests now assert the handler is *attached*, the element can hold focus, and the fieldset is not
hidden.

Sending pixel coordinates reported NOT CAUGHT because every normalisation assertion called
`normalizeRectangle` directly, so `buildCropRequest` could stop calling it and nothing noticed — and
`typeof "60" === "string"` is true of a pixel as well as a decimal. The test now asserts the
request's own bbox equals the helper's output, that every value is between 0 and 1, and that each
matches the column's scale.

**Two more defects, both caught by gates that already existed.** `UI-REQ-004` refused the workspace
for having nothing link to it, and the a11y sweep refused it for not being swept — which is how the
queue screen came to be built. Neither was in the plan.

**And the seventh instance of a scan defeated by its own explanation.** `UI-EVIDENCE-001` first
searched the fallback section for the words "failed" and "isPreviewable"; the comment above that
section explaining why neither belongs there broke it immediately. It now matches the guard itself —
`{selected ? (` immediately before the section — which is both prose-proof and the stronger claim,
since what the requirement says is that the fallback is conditioned on a file being selected and on
nothing else.

## Slice 7 — Privacy review and the Definition of Done

**Done. M8 is complete.**

### What it changes

The §16 `:1065` verification as a recorded fact, and the milestone gate.

**M0's own catalogue said where the verification goes, and it needed no new table.** §16.5 asks for a
verification and names nothing to hold it; `04_Database_Schema.md` has no review or verification
table at all. But `manual_review_tasks.task_type` already admits `segment_privacy_review` — one of
exactly four types slice 3 took from the approved list — so the review queue is where M0 expects the
work to live. A resolved task already recorded three of the four facts `SVC-PRIVACY-001` asks for:
the actor, the time and the subject.

The fourth was missing: **which version of the subject**. `record_version` on that table is the
task's own. So slice 7 is one nullable column, `entity_record_version`, copied from
`audit_logs.entity_record_version` which has held exactly this since M2 — a smaller change than a
table with a new permission, a new command row and a new audit action, and `manual_review.resolve` is
already seeded.

**Written at resolution, not at opening**, because that is when a person actually judges. The version
they were *asked* about is a different fact and the wrong one if the segment was re-rendered in
between. That needs an UPDATE grant, which this migration's first draft withheld on the grounds that
the value never moves; it moves once, and the protection against twice is `PERMITTED_TRANSITIONS`,
which draws no arrow out of `resolved`.

**`privacy_verified` is a comparison, never a stored flag.** A resolved task carries the version its
reviewer looked at, and the check applies only while the segment still has that version — so a crop
re-rendered afterwards is unverified again with nothing to remember to reset. That is the only form of
"per segment version" that cannot rot, and `SegmentDetail` returning it is what stops the record being
a mechanism with no caller. There is deliberately no setter: §2.5 explains why no publication guard is
written here.

**`request_crop` raises the task**, giving `open_task` its third caller. A crop is the moment §16.5's
obligation attaches, so the task exists then rather than depending on somebody remembering at
publication time — by which point the person who drew the rectangle has moved on.

### What proves it

- `SVC-PRIVACY-001` — the verification records actor, time and segment, and is **per segment
  version**: a segment edited after verification is unverified again, or the record would attest to
  something else.
- `SVC-PRIVACY-002` — no route this milestone adds can mark a segment publishable, asserted over the
  whole route table. §2.5.
- `TRACE-M8-002` — §16 `:1081`: an accountant can inspect a mixed bundle, create a reproducible
  crop, and continue without OCR or AI. One journey test through the API, because nine steps proved
  separately can all pass while the sequence is impossible — M5 slice 5 shipped exactly that.
- `TRACE-M8-003` — no AI path is reachable: `ai_auto_segmentation` unwritable, doc 05 `:1721`'s
  route absent, and `ai_usage_logs` empty after the journey.

### Negative controls

Add a publishable flag: `SVC-PRIVACY-002` must fail. Leave a verification attached across an edit:
`SVC-PRIVACY-001` must fail. Register the AI extraction route: `TRACE-M8-003` must fail.

`scripts/sabotage-m8-slice7.sh` runs those three and five more: stop recording the version, treat an
unresolved close as a pass, stop raising the task on a crop, write the AI creation method, and return
the privacy state as a constant. **Eight of eight caught.**

### What slice 7 found

**`ai_usage_logs` does not exist, which is stronger than empty.** `TRACE-M8-003` asked for the table
to be empty after the journey; `04_Database_Schema.md:1381` specifies it and no migration builds it,
because nothing in Phase 1A uses a model. The assertion is therefore its *absence*, and the
distinction has teeth: `SELECT count(*)` against a missing table raises, so a test that caught the
exception and called it success would pass equally well with a misspelled query against a table that
did exist.

**`BankExcelExport` has no `record_version`.** The first draft of `_subject_version` handled exports
too, arguing that an integrity task should say which version was signed off. M7 made an export
immutable — a new file is a new row, not a new version — so there was nothing to record, and the
draft would have failed on an attribute that does not exist.

**A control reported NOT CAUGHT because its sabotage had never applied.** Two source files held CRLF
in the working tree, so `perl -0pe 's/…\n…/'` matched nothing. The cause was mine: rewrapping helpers
run through the *Windows-side* Python, whose text mode translates `\n` to `\r\n`. Git normalises on
commit, so the repository looked clean and nothing pointed at it. The procedural lesson is the
valuable part — when a control reports NOT CAUGHT, confirm the sabotage applied before concluding
anything about the test. Patterns are now `\r?\n`.

**Two API facts the tests taught rather than the documents**: a task transition needs an
`Idempotency-Key` as well as `If-Match`, and `If-Match` takes the form `rv-<n>` rather than a bare
number — the platform gave the token a shape so a client cannot send something that merely happens to
parse.

**And an eighth registry.** `EXPECTED_MIGRATION_HEADS` in `app/db/migrations.py` pins the head the
readiness probe expects, and its failure message says to update it in the same commit as the revision
or the probe reports a correctly migrated database as unavailable. Eight registries touched across
M8 — the list is longer than anybody memorises, which is exactly why these tests exist rather than a
convention.

---

# 4. What the owner must settle

| ID | Question | Blocks |
|---|---|---|
| **Q-1** | **Is rotation stored?** doc 08 `:989` and `:1011` require it in the crop input and its provenance, and §16 `:1044` requires it validated. doc 05 `:1756` omits it from the request and doc 04 `:1201` gives `receipt_segments` no column. Without it a crop of a rotated page is **not reproducible from its own provenance**, which is the property §16 `:1069` tests. This plan follows doc 08, adds the column, and files a conflict-register row. Confirm, or say rotation is a view-only control and accept that §16 `:1069`'s reproduction test cannot cover rotated sources. | Slices 2 and 4 |
| **Q-2** | **What status does a segment hold while its crop renders?** doc 08 `:1031` creates it before the file exists; the catalogue's `processing` is an unresolved alias, not a canonical `receipt_segment` state. This plan leaves it `created` and puts the progress on `processing_jobs`. The cost is that `created` means both "render pending" and "rendered, awaiting matching". | Nothing; §2.2 needs no catalogue change |
| **Q-3** | **What is the "approved tolerance"** for reproduction (§16 `:1069`)? No document sets one. This plan asserts byte equality at a fixed renderer version, DPI and rotation, which needs no tolerance; a tolerance is only meaningful across renderer versions, and that is what `renderer_version` is stored for. | Nothing; a stricter reading ships |
| **Q-4** | **Which PDF renderer, and is its licence acceptable?** Nothing in the dependency list can open a PDF. Recommendation: `pypdfium2` (Apache-2.0) with `Pillow`, both vendorable as wheels so nothing compiles on the target. The alternative with the best capability is PyMuPDF, which is **AGPL-3.0 or paid** — a legal decision, not a technical one. Note both are unlike `openpyxl` in one respect the M7 decision leaned on: they carry native code. | **Slices 4, 5 and 6** |
| **Q-5** | **Does a bundle need a `bank_profile_id`?** doc 04 `:1170` makes it nullable and no document says when it is set. A bundle whose bank is unknown cannot be checked against the profile the export used, which is the one cross-check available at this stage. This plan sets it when a batch link supplies it and leaves it null otherwise. **Slice 1 built that**, and added one rule the question did not anticipate: a link fills the column only when it is empty, never overwrites it. A mistaken link must not be able to rewrite an established fact. | Slice 1's field list — **built** |
| **Q-6** | **`bank_result_bundle.link_batch` authorises a command no catalogue describes.** The permission is in `permission_catalog.yaml:528` and seeded to `accountant` by `20260801_0008_seed_rbac_catalogue.py:143,208`; `command_catalog.yaml` has no row and `audit_outbox_catalog.yaml` names no action — its only two bundle actions are `uploaded` and `closed`. This is **DOC-CONFLICT-052's shape for the third time**, after `payment_batch.cancel_draft` and `payment_batch_version.invalidate_approval`. **Slice 1 implements the route against the permission's own identifier** and declares the audit action `catalogued=False` with its reason, which is what M6 slice 4 did under that same conflict. The owner owes a command row and a catalogued action, and the action name must be renamed to whatever M0 approves. | Nothing; slice 1 shipped under the precedent — **built** |
| **Q-7** | **The route that moves a bundle into review has no permission at all.** doc 05 `:1693` defines `POST /{id}/start-review`; `permission_catalog.yaml` has no entry for it — not an ungranted permission but a missing one — so deny-by-default would answer `403` to every caller and a bundle left in `uploaded` could never leave it. Inventing a permission is not an implementer's decision, because a permission is a grant and grants are seeded and audited. **Slice 1's resolution: upload lands the bundle in `ready_for_manual_review` directly.** `06_Workflows_and_State_Machines.md:995` draws `uploaded --> ready_for_manual_review: direct manual mode`, and Phase 1A has no normalization job to take the `processing` branch — so upload *is* the direct manual mode, and this is the state machine's own label rather than a workaround. `uploaded` stays in the CHECK and stays meaningful for a future slice that adds the job. The owner decides whether `start-review` gains a permission or is dropped for Phase 1A. | Slice 6's workspace would have had nothing to review — **resolved in slice 1** |
| **Q-9** | **A guarded segment `PATCH` is forbidden, not merely unbuilt.** doc 05 `:1792` defines it and `permission_catalog.yaml` resolves `receipt_segment.update` as `unresolved_no_exact_canonical_target`, `canonical_targets: []`, `resolution: deny until an explicitly scoped pre-finalization update permission is approved` — with `m0_open_items` carrying `receipt_segment_update_permission` and `conservative_effect: deny_update_until_action-specific_permission_is_approved`, citing the same doc 05 lines this plan read. **Unlike Q-6 and Q-7 this is not a silence but a decision M0 has already taken**, and this plan had not consulted it: slice 2's original wording would have shipped a route that breaks an approved rule. The route is absent, a written `correct_fields` command was deleted rather than left unexposed, and `SVC-SEGMENT-001` became an assertion that no route mutates a segment — with a companion test that fails when the catalogue stops refusing, so the absence cannot outlive its reason. **The owner decides** whether to approve a scoped pre-finalization update permission (and its command row and audit action), or to rule that corrections always create a replacement segment, which is what doc 05 `:1795` already says happens after finalization. | Nothing; the absence is the conservative reading — **resolved in slice 2** |
| **Q-10** | **doc 04's index predicate names a segment status the catalogue does not have.** `:1672` writes `WHERE status IN ('unmatched','candidate_found','needs_review')` and `needs_review` is neither canonical nor an unresolved alias in `status_catalog.yaml`, so `ck_receipt_segments_status_value` makes that disjunct unreachable. Slice 2 **copies the predicate verbatim**: trimming it would make the index a differently-scoped object wearing the document's name, which `test_schema_matches_the_specification.py` refuses in those words. The divergence is therefore visible in the schema rather than hidden in a test exemption, and a test pins it so it cannot be tidied away. **The owner decides** whether the catalogue gains the state or doc 04 loses the word. | Nothing; recorded in the schema — **built** |
| **Q-11** | **§12.4's own bbox CHECK accepts a partial rectangle.** Set three coordinates and leave the fourth NULL: the all-null branch is false, the in-bounds branch contains `bbox_height > 0` which is NULL, and `false OR NULL` is NULL — **which a CHECK accepts, because SQL rejects only on false.** A row claiming three quarters of a rectangle satisfies the documented constraint exactly as written, sits in the table looking like a crop, and can never be reproduced. Found by testing the documented constraint at its edges rather than by reading it. Closed with `num_nonnulls(bbox_x, bbox_y, bbox_width, bbox_height) IN (0, 4)`, which cannot be NULL and is therefore decidable. **The owner owes doc 04 the correction**; the code is already safe. | Nothing; closed in slice 2 — **built** |
| **Q-8** | **The batch link's `status` is a lifecycle no catalogue governs.** `active` and `replaced`; doc 04 `:1197` gives the table a `status` and a `replaced_at` and names no aggregate, and `status_catalog.yaml` has none. `test_status_catalogue_drift.py` requires every enforced status CHECK to name an aggregate, so slice 1 added `LOCAL_LIFECYCLES` beside the existing `DELIBERATELY_UNCONSTRAINED` — the opposite case, a CHECK with no aggregate rather than an aggregate with no CHECK — with two tests that refuse a bare entry and refuse a column listed in both. The owner decides whether the catalogue gains a `bank_result_bundle_batch_link` aggregate. | Nothing; recorded with its reason — **built** |

**Q-4 is the only one that blocks starting.** Slices 1, 2 and 3 — the bundle, the segment table with
its non-rendering creation method, and the review queue — need none of the eight answered, and they
are three of the seven.

**Q-6, Q-7 and Q-8 were found by building slice 1, not by planning it**, and all three are the same
kind of thing: an approved permission with no command, a documented route with no permission, and an
enforced CHECK with no aggregate. Each was resolved by following a precedent this repository already
set rather than by inventing governance — and each still owes the owner a decision, which is why they
are here rather than only in a code comment. The pattern is worth naming: **the catalogues and the
specification disagree most often about the things neither of them thought were interesting.**

---

# 4.1 Decisions taken on the owner's instruction (2026-08-24)

The owner asked for the simplest defensible answer to each open question rather than a queue of
decisions. Each is recorded here as **taken, by whom, and reversible or not**, because a delegated
decision that leaves no trail is worse than an open one.

**Q-4's renderer was measured before it was pinned (2026-08-25), and here are the numbers.**
`pypdfium2==5.13.0` bundling pdfium `153.0.7999.0`, with `pillow==12.3.0`:

| Question | Result |
|---|---|
| opens a multi-page PDF | 2 pages from a hand-written document |
| reports page dimensions | `(300.0, 400.0)` points, so a client can normalise against them |
| applies rotation | upright raster `600×800`, rotated 90° `800×600` |
| **re-render is byte-identical** | **yes**, same rectangle twice → identical PNG; also identical when rotated |
| rotation changes the crop | yes — which is DOC-CONFLICT-057's whole point, now demonstrated |
| ships its native library | `pypdfium2_raw/libpdfium.so` in the wheel; nothing builds on the target |

The fourth row is what `SVC-CROP-004` rests on and what settles **Q-3**: byte equality holds at a
fixed version, DPI and rotation, so "approved tolerance" is unnecessary rather than merely
unspecified.

One correction worth keeping: the first native-library scan looked in the `pypdfium2` wrapper and
reported "none found", which would have contradicted the licence-and-portability claim on the
strength of a wrong glob. The library is in the sibling `pypdfium2_raw` package.

**Q-4 — renderer: `pypdfium2` with `Pillow`.** Taken. Apache-2.0 and HPND, both shipping manylinux
wheels with their native code bundled, so nothing compiles on the target and both can be vendored
for a network that cannot reach a registry. The alternative with better capability is PyMuPDF, and it
is **AGPL-3.0 or paid** — so choosing it would commit this product to either a copyleft obligation or
a purchase, and neither is a call an implementer should make quietly. Taking the permissive option is
the decision that *needs* no owner sign-off; if the owner later wants PyMuPDF's capability, that is a
licence purchase and slice 4's `renderer_name`/`renderer_version` columns are what make the swap
recordable rather than invisible.

Still not pinned in this slice. Slice 4 pins it with the evidence M7 demanded of `openpyxl` —
properties verified against a written-and-reread file before the version is fixed, not asserted in a
comment. A dependency added to a slice that cannot exercise it is how a library arrives with nothing
checking it does what the plan assumed.

**Q-9 — segment corrections create a replacement, and no update permission is requested.** Taken,
and it is the simplest reading of what already exists: doc 05 `:1795` says a replacement segment is
created after finalization, and the permission catalogue refuses a pre-finalization update until one
is approved. Making replacement the *only* path removes the distinction entirely — no window in which
evidence can be edited in place, one shape for every correction, and nothing new to authorise.
Replacement itself belongs to M9, which owns `superseded`. Slice 2 ships the absence and the test
that fails if the catalogue ever stops refusing.

**Q-10 — the index predicate keeps doc 04's wording.** Taken, already built. The unreachable
`needs_review` disjunct stays visible in the schema rather than hidden in a test exemption. Doc 04 or
the catalogue owes an editorial fix and neither blocks anything.

**Q-11 — the partial-rectangle hole is closed in code; doc 04 owes the correction.** Taken, already
built. `num_nonnulls(...) IN (0, 4)` is decidable where the documented CHECK is not.

**Q-1, Q-2, Q-3, Q-5, Q-6, Q-7, Q-8** were resolved in slices 1 and 2 as their rows describe.

**G-5 — an approved batch has no exit — was the one open item on this project about money rather
than documents, and the owner decided it on 2026-08-25.** Authority is split by state: cancellation
before a manager approves stays with the accountant under the existing `payment_batch.cancel_draft`,
and cancellation after approval requires a **new manager-only permission**, because undoing a
manager's decision is not an accountant's to make — the same separation-of-duties reasoning
`FINANCIAL_INTEGRITY_BASELINE.md` §5 applies to finalizing and approving. So the permission check
becomes a function of the batch's *state*, not of the route alone. DOC-CONFLICT-053 and -056 carry
the decision and what M0 still owes: the permission's catalogue row, its seed, a `command_catalog.yaml`
row for each of the two commands, and a catalogued cancellation action for the batch aggregate.

**M6 had already left the seam for it**, which is worth noting because it is the inverse of this
repository's recurring defect. `app/commands/payment_batch.py` carries two lists —
`CANCELLABLE_BATCH_STATUSES` and `CANCELLABLE_BUT_UNAUTHORISED` — and the second produces a distinct
refusal citing DOC-CONFLICT-056 by name. A mechanism that refuses and says why, rather than machinery
nothing calls. Implementing the decision moves `ready_for_approval` between those two lists and adds
`approved` behind the new permission; `_release_every_allocation_of` already returns the batch's
requests to the pool, so nothing about the requests needs deciding.

**Sequenced after M8's remaining slices**, because none of slices 5, 6 or 7 depends on it and a
milestone abandoned mid-flight costs more than an ordered queue.

---

# 5. What this plan carries forward

- **A gate whose input is incomplete passes.** Every list parsed from a document is checked for
  being non-empty first. This has caught real defects twice, both times as a list that quietly
  became empty rather than a comparison that failed.
- **NOT CAUGHT has four meanings**, and "the sabotage does not break the property" is one of them.
  M7's slice 2B had a control that was correctly not caught, because a foreign key made two
  formulations equivalent; the control was wrong, not the test.
- **Assert an absence over the whole surface, not the one screen.** §16 `:1057`'s three
  prohibitions and §2.5's publishable flag are bundle-wide greps, because the thing somebody adds
  under pressure gets added wherever it is convenient.
- **When an absence stops being literal, the claim becomes reachability.** The screens plan hit
  this: slice 3 asserted a control did not exist and slice 4 added it. One render site behind a
  server-derived flag, one importer, and the endpoint named exactly once.
- **Source-grep assertions collide with the prose explaining them** — three corrections in the
  screens plan. Narrow claims about code strip comments, with a guard against an over-eager
  stripper; blunt prohibition scans stay raw.
- **Name an absent obligation, never its id.** The traceability scanner counts any id in a test file
  as a citation, and that has now cost eleven corrections.
- **Run the gate's own invocation.** `ruff check app/` is not the lint gate; the verifier reads
  `infra/verification/lint_targets.txt`, and `scripts/lint-like-ci.sh` reads the same file.
