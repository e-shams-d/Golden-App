# M11 Screens — The Business Made Visible

Status: not started. **Eight slices, one Definition of Done gate, three questions for the owner.**

Authority: `21_UI_Design_System_and_Screen_Specification.md`, which specifies every screen below
field by field. **This plan implements a specification; it does not invent one.**

## 1. Why this plan exists

### 1.1 The finding

The backend publishes **147 operations across 130 paths**. The two applications have **24 screens**
between them — thirteen admin, eleven trader — and the newest of them was written for M9.

Everything M10 built has no screen at all. A search for the routes it published returns nothing in
either application:

```
grep -rl "gold-sale-orders|bank-statements|incoming-payment|/dispatches|notifications" apps/
→ no matches
```

That is a whole second business line — gold ordered, paid for, matched against a bank statement,
confirmed, dispatched and closed — reachable only through the API. M9's publication screens are
missing too: nothing renders a published payment result to the trader it is about, and nothing
lets them acknowledge or dispute it.

### 1.2 What is *not* the problem

**The specification is complete.** Document 21 §17 gives the gold-sale, incoming-payment and
dispatch screens (`21_UI_Design_System_and_Screen_Specification.md:1929`); §16 gives the candidate,
evidence, result and publication screens (`:1818`); §22 gives notifications and task indicators
(`:2196`); §10.3 gives the global work queue (`:1348`). Each is written to the field.

**The order is decided too.** §26 (`:2320`) lists fifteen implementation steps. Steps 1–11 are
substantially done — tokens, RTL primitives, the typed client, both shells, authentication,
beneficiaries, request flows, batching, approval, exports, and the bundle workspace. **Steps 12
through 15 are what remains**, and they are what this plan is.

So this is not a design gap and not a sequencing question. It is unbuilt work that no milestone
was ever assigned.

### 1.3 Why it was never assigned

The roadmap has fourteen milestones. M12 is security, QA and operational hardening; M13 is UAT,
pilot and production release. **Neither is a UI milestone**, and none of M8 through M11 carried
one. M7's screens were built under their own plan
(`docs/handoff/M7_SCREENS_IMPLEMENTATION_PLAN.md`), which worked — and was never repeated.

The consequence, if this is not fixed before M13: user acceptance testing puts a real person in
front of a system where half the business is invisible.

### 1.4 The rule this plan inherits from M7's

> A screen that needs a field the API does not return is a **finding**, not a frontend fix.

M7's screens plan gained two slices mid-flight from exactly that: the approval view returned 11 of
§13.3's 19 fields, and the export detail returned 15 where §14 needed 22. Slice 0 below exists to
find that class of problem **before** eight slices are estimated against it.

---

## 2. Where every section cited below lives

The prose says `§17.3`; this table is what makes that checkable. Cited once here rather than at
every mention.

| Section | Line | What it specifies |
|---|---|---|
| §9.9 `:1256` | `21_UI_Design_System_and_Screen_Specification.md:1256` | trader payment result / publication screen |
| §9.10 `:1273` | `21_UI_Design_System_and_Screen_Specification.md:1273` | publication history |
| §9.11 `:1277` | `21_UI_Design_System_and_Screen_Specification.md:1277` | trader dispute screen |
| §9.12 `:1287` | `21_UI_Design_System_and_Screen_Specification.md:1287` | trader gold order screens |
| §10.3 `:1348` | `21_UI_Design_System_and_Screen_Specification.md:1348` | global work queue |
| §10.5 `:1379` | `21_UI_Design_System_and_Screen_Specification.md:1379` | audit and security event views |
| §16.1 `:1820` | `21_UI_Design_System_and_Screen_Specification.md:1820` | matching candidate review |
| §16.4 `:1859` | `21_UI_Design_System_and_Screen_Specification.md:1859` | confirm attempt paid |
| §16.5 `:1870` | `21_UI_Design_System_and_Screen_Specification.md:1870` | confirm attempt failed |
| §16.6 `:1880` | `21_UI_Design_System_and_Screen_Specification.md:1880` | retry creation |
| §16.7 `:1894` | `21_UI_Design_System_and_Screen_Specification.md:1894` | publication preview |
| §16.8 `:1900` | `21_UI_Design_System_and_Screen_Specification.md:1900` | publish result |
| §16.9 `:1911` | `21_UI_Design_System_and_Screen_Specification.md:1911` | published result correction |
| §17.1 `:1931` | `21_UI_Design_System_and_Screen_Specification.md:1931` | gold order queue |
| §17.2 `:1944` | `21_UI_Design_System_and_Screen_Specification.md:1944` | pricing workspace |
| §17.3 `:1958` | `21_UI_Design_System_and_Screen_Specification.md:1958` | incoming receipt upload/review |
| §17.4 `:1969` | `21_UI_Design_System_and_Screen_Specification.md:1969` | statement import preview |
| §17.5 `:1982` | `21_UI_Design_System_and_Screen_Specification.md:1982` | incoming match review |
| §17.6 `:1986` | `21_UI_Design_System_and_Screen_Specification.md:1986` | dispatch guard panel |
| §17.7 `:2000` | `21_UI_Design_System_and_Screen_Specification.md:2000` | dispatch registration |
| §18.4 `:2047` | `21_UI_Design_System_and_Screen_Specification.md:2047` | retention and legal hold |
| §18.5 `:2060` | `21_UI_Design_System_and_Screen_Specification.md:2060` | job and storage operations |
| §20.1 `:2114` | `21_UI_Design_System_and_Screen_Specification.md:2114` | frontend visibility is not authorization |
| §20.4 `:2131` | `21_UI_Design_System_and_Screen_Specification.md:2131` | technical admin presentation |
| §22 `:2196` | `21_UI_Design_System_and_Screen_Specification.md:2196` | notifications and task indicators |
| §24.1 `:2244` | `21_UI_Design_System_and_Screen_Specification.md:2244` | Phase 1A required UI scope |
| §26 `:2320` | `21_UI_Design_System_and_Screen_Specification.md:2320` | suggested implementation order |
| §27 `:2340` | `21_UI_Design_System_and_Screen_Specification.md:2340` | open decisions needing approval |

The backend surfaces these screens consume:
`15_Agent_Implementation_Plan.md:1256` (§19 work queues),
`15_Agent_Implementation_Plan.md:1298` (§19.3 query rules),
`05_API_Specification.md:2077` (§22.3 notification routes).

---

## 3. What this plan is not

- **Not a redesign.** Tokens, typography, RTL rules and component contracts are built and in use.
- **Not new backend work**, except where slice 0 finds a screen the API cannot feed. That is the
  point of putting slice 0 first.
- **Not §24.2's list** (`:2273`): no OCR, no automatic segmentation, no AI overlays, no bank API.

### 4.1 A note on the identifiers above

The first draft of this plan named its obligations `SCREENS-*`. **`tests/backend/test_traceability.py`
recognises no such prefix**, so every one of them would have been refused by the gate that exists
to catch exactly that — and until they were registered, nothing would have refused them either,
because an unregistered obligation is invisible rather than wrong.

They are `UI-*` now, which is what M7's screens plan used and what the gate knows. `TRACE-SCREENS-002`
keeps its shape because `TRACE-SCREENS-001` already has it.

The lesson is the one this project keeps relearning in a new place: **a plan is not checked until
something checks it.** These nine are registered in `PENDING` by slice 0, before any of them is
built, for the reason M11's plan gives — an obligation nothing tracks is one a milestone can finish
without meeting.

---

## 4. Slices

### Slice 0 — the reads these screens need, which may not exist

### Goal

Walk every screen §16, §17 and §22 specify, field by field, against what the API returns
today. Produce a list of missing fields *before* anything is built on top of them.

### Why first

M7's screens plan found two whole slices' worth of missing reads by discovering
them mid-build. The cost of finding them early is one pass over a document; the cost of finding
them late is a slice that stops halfway.

### What proves it

- `UI-READ-001` — for each specified screen, a test that names the fields
the specification requires and asserts the operation returns them. A field the API does not return
is a recorded finding with the slice that will add it, not a silent omission.

### Slice 1 — notifications, both applications

### Goal

§22 (`:2196`). M11 slice 1 built `GET /api/v1/notifications`, mark-read and
mark-all-read; nothing renders them.

### What it changes

A bell in both shells with an unread count, a list, mark-read, and
mark-all-read. The count comes from the `unread_count` the API already returns.

### What proves it

- `UI-NOTIFY-001` — the indicator reflects the server's count and never a
locally-derived one, and marking read updates it without a page reload. §2.3 (`:205`): server
truth over visual state.

### Slice 2 — the work queue surface

### Goal

§10.3 (`:1348`), against the sixteen queues M11 slices 2–5 built.

### What it changes

One queue shell driven by the queue registry, a per-role landing page, and
the filter/sort/cursor controls §19.3 (`15_Agent_Implementation_Plan.md:1298`) requires. Every
queue returns the same five-field row, so **one table component serves all sixteen** — which is
the payoff of that decision.

### What proves it

- `UI-QUEUE-001` — a role sees exactly the queues its grants allow, and the
paging control walks a cursor rather than an offset. §20.1 (`:2114`): frontend visibility is not
authorization, so the test asserts the *server* refuses, not that the link is hidden.

### Slice 3 — the trader's payment result

### Goal

§9.9 (`:1256`), §9.10 (`:1273`), §9.11 (`:1277`). M9 published results and built the
share file; no trader can see any of it.

### What it changes

The publication screen, its version history, acknowledge, and dispute.

### What proves it

- `UI-PUB-001` — a second trader receives 404 rather than 403 on somebody
else's publication, and the acknowledge and dispute buttons are absent rather than disabled when
the publication is superseded.

### Slice 4 — the centre's result confirmation and publication

### Goal

§16.4 (`:1859`), §16.5 (`:1870`), §16.6 (`:1880`), §16.7 (`:1894`), §16.8 (`:1900`),
§16.9 (`:1911`).

### What it changes

Confirm paid, confirm failed, mark a retry required, create a retry, preview a
publication and publish it. **The correction flow is not built**, and that is a correction to this
plan rather than a reduction of it — see below.

### What proves it

- `UI-RESULT-001` — every command this screen offers comes from the server's
`allowed_actions`, each carries the `If-Match` its read returned, and the publish control is absent
rather than disabled for a role holding `payment_publication.preview` without `.publish`. The
correction flow is recorded as blocked with the grant that blocks it, in the same shape the queue
registry's `BLOCKED` uses.

### Two things this slice found before writing any code

**This obligation named the wrong command for the step-up.** Its first wording said "the publish
button requires the recent-auth dialog §8.11 (`:887`) specifies". §8.11 describes the dialog
*component* — that reauthentication is a separate step and must not auto-submit the financial
command — and says nothing about which commands need one. `command_catalog.yaml` is the authority
and it is explicit: `payment_publication.publish` carries **no** `recent_auth` field, while
`payment_publication.correct_paid_result` carries `recent_auth:
"required_for_approving_second_human"` alongside `separation_of_duties:
"accountant_prepares_second_authorized_human_approves"`.

So the step-up belongs to the **correction**, not to the publish. A test written against the
original wording would have demanded a header the backend does not require, and passing it would
have meant adding a control nothing asked for.

**The correction flow cannot be built as specified.** `permission_catalog.yaml` gives
`payment_publication.correct` `default_roles: []` — no role holds it, by design: POL-002 requires
the preparer and approver permissions to be split and defers the split to **ADR-SEC-009**, which is
unresolved. `command_catalog.yaml` marks the command
`status: "blocked_by_business_policy_and_api_persistence_contract"` with `method: TBD, path: TBD`.

Building the screen anyway would produce a surface nobody can open — the `bank_profile.activate_
version` shape this project already carries once, and the "complete machinery nothing calls" defect
M3 hit five times. The original obligation's other clause is affected too: "cannot be reached by a
role that holds only the preparer half" is *trivially* true today, because it cannot be reached by
anybody. An assertion that passes for the wrong reason is worse than none.

Unblocked by ADR-SEC-009. Until then the backend route exists — M9 slice 7 built it and
`test_publication_correction.py` proves `_refuse_a_single_human` refuses even when one person holds
both grants — and no screen reaches it.

### Slice 5 — gold orders, trader and centre

### Goal

§9.12 (`:1287`), §17.1 (`:1931`), §17.2 (`:1944`). M10 slices 1–2.

### What it changes

The trader creates and submits an order; the centre reviews and prices it.

### What proves it

- `UI-GOLD-001` — the pricing workspace refuses to submit against a stale
pricing version, using the `If-Match` the API already requires.

### Slice 6 — incoming payment, claim to confirmation

### Goal

§17.3 (`:1958`), §17.4 (`:1969`), §17.5 (`:1982`). M10 slices 3–6.

### What it changes

The trader's payment claim on their own order; the accountant's review screen —
the claim, its candidates, proposing one, rejecting one, and confirming what arrived.

**The statement import screen is not built.** The owner has confirmed the bank returns no Excel,
so M10's statement parser has no input in practice and a screen for it would be a surface for a
flow that cannot start. The routes exist and are tested; nothing reaches them from a browser.
Unblocked by the bank question already recorded — whether an account statement can be exported in
any importable format.

**Duplicate review is not a separate screen either.** M10 builds duplicate detection into the
import run, and with no import there is nothing to review; the accountant's judgement about which
row proves a claim is the match surface, which *is* built.

### What slice 6 corrected in slice 5's record

Slice 5's precondition gate recorded both incoming-payment commands as needing the **receipt's**
version. Confirming does; **rejecting a match does not** — that route passes
`incoming_payment_match_id` and edits the match row. Reading the routes to build the screen is what
found it.

The distinction matters more than it looks: one read would have closed the recorded gap and left
the reject screen with nothing to echo, **and the gate would have gone green** — a recorded gap
that names the wrong aggregate is closed by a read that does not satisfy it. So slice 6 added two
reads, `GET /incoming-payment-receipts/{receipt_id}` and `GET .../matches/{match_id}`, and the
pairing is asserted rather than assumed.

### What proves it

- `UI-INCOMING-001` — an overpayment shows the reconciliation block §24.1
(`:2244`) requires rather than a generic error, because that path opens a task rather than
refusing.

### Slice 7 — dispatch and closure

### Goal

§17.6 (`:1986`), §17.7 (`:2000`). M10 slices 7–8.

### What it changes

The warehouse's dispatch guard panel and registration; the trader's
acknowledgement; the centre's closure.

### What proves it

- `UI-DISPATCH-001` — the guard panel shows *why* a dispatch is blocked and
offers the override only to the role that holds it, with the override reason mandatory.

### Slice 8 — Definition of Done

### Goal

A gate that fails when an operation ships without a screen or a recorded reason.

### What it changes

A test that walks the published OpenAPI operations and the route tables of
both applications, and asserts every operation is either reachable from a screen or listed with
the reason it is not — the same shape as the queue registry's `BLOCKED`.

### What proves it

- `TRACE-SCREENS-002` — the gate is written against *the operations that exist*
rather than the screens this plan adds, which is the only reason M7's equivalent caught `/login`
being unswept by the accessibility suite since M3.

---

## 5. Questions for the owner

### S-1 — the three §27 items that are still open

§27 (`:2340`) lists decisions the UI needs and nobody has made: the brand name and logo, the final
light-theme palette and whether dark mode exists, and the Persian font with its licensing.

**Not blocking slices 0–8.** Every screen here uses tokens that already have values. But the
answers change what the applications look like at UAT, and a font chosen late is a font that
reflows every screen.

### S-2 — does the technical-operations screen belong in this plan?

§18.5 (`:2060`) specifies job and storage operations screens, and §20.4 (`:2131`) constrains what a
technical administrator may see. M11 slice 5 found that four of those five queues have no session
permission or no table.

**Recommendation: out of scope here.** Building a screen over a surface guarded by an operations
token would mean putting a machine credential into a browser. Revisit when the owner answers
whether operational reads belong to a session grant.

### S-3 — reports

§24.1 (`:2244`) lists reports among Phase 1A's required UI. M11 slice 7 builds the report
generation backend. **Recommendation: leave reports to a slice added after M11 slice 7 lands**, so
the screen is built against a real response rather than a planned one.

---

## 6. Ordering, and why

Slice 0 first, because it is the one that can change the estimate for every slice after it.

Then 1 and 2, because they are the surfaces every other screen links *into* — a notification
points at an entity, and a queue row is how a person arrives at one. Building them last would mean
building navigation twice.

Then 3 → 4 → 5 → 6 → 7, which is the order money and metal actually move, and the order §26
(`:2320`) suggests at steps 12 and 13.

Slice 8 last, because a Definition-of-Done gate written before the work exists is a gate written
against intentions.
