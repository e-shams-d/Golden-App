# M11 — Operational Queues, Notifications, Reports, and Maintenance

Ten milestones built the money paths. This one makes them **workable**: each role can find its own
outstanding work, and every operational failure is visible to somebody who can act on it.
`15_Agent_Implementation_Plan.md:1254`.

## Where every section cited below lives

The prose says `§19 :1260`; this table is what makes that checkable. Each source is cited once here
rather than at every mention.

**Short forms: `§19` is document 15's M11 section, `doc 04` the schema, `doc 05` the API
specification, `doc 06` the workflows document, `doc 10` the backend implementation guide, `doc 12`
the security document.**

| Cited as | Full citation | What it specifies |
|---|---|---|
| §19 `:1256` | `15_Agent_Implementation_Plan.md:1256` | the milestone's goal, in one sentence |
| §19 `:1260` | `15_Agent_Implementation_Plan.md:1260` | the required queues, by role |
| §19 `:1262` | `15_Agent_Implementation_Plan.md:1262` | the accountant's eleven |
| §19 `:1276` | `15_Agent_Implementation_Plan.md:1276` | the manager's four |
| §19 `:1283` | `15_Agent_Implementation_Plan.md:1283` | the warehouse's three |
| §19 `:1289` | `15_Agent_Implementation_Plan.md:1289` | technical operations' six |
| §19 `:1298` | `15_Agent_Implementation_Plan.md:1298` | the six query rules |
| §19 `:1307` | `15_Agent_Implementation_Plan.md:1307` | notifications, and the four failure rules |
| §19 `:1318` | `15_Agent_Implementation_Plan.md:1318` | the eight maintenance jobs |
| §19 `:1331` | `15_Agent_Implementation_Plan.md:1331` | the Definition of Done |
| doc 05 `:2055` | `05_API_Specification.md:2055` | manual review tasks, six routes |
| doc 05 `:2068` | `05_API_Specification.md:2068` | structured comments, and their two scopes |
| doc 05 `:2077` | `05_API_Specification.md:2077` | **notifications, three routes** — none built |
| doc 04 `:1312` | `04_Database_Schema.md:1312` | `manual_review_tasks`, which four queues read |
| doc 04 `:1334` | `04_Database_Schema.md:1334` | `notifications`, the table with no API |
| doc 06 `:348` | `06_Workflows_and_State_Machines.md:348` | the gold-order state machine G-2 turns on |
| doc 10 `:382` | `10_Backend_Implementation_Guide.md:382` | pagination, named in the API layer |
| doc 10 `:1888` | `10_Backend_Implementation_Guide.md:1888` | "queue filters and pagination" as a tested concern |
| doc 12 `:616` | `12_Security_RBAC_Audit.md:616` | `technical_admin` has "no implicit financial authority" |
| doc 12 `:664` | `12_Security_RBAC_Audit.md:664` | what a technical admin does **not** automatically receive |
| doc 12 `:1942` | `12_Security_RBAC_Audit.md:1942` | least privilege |

---

# 1. What is different about this milestone

**M11 builds almost no new financial state.** Every earlier milestone added tables that record what
money did; this one adds *reads* over tables that already exist, plus the jobs that keep them
honest. That changes what can go wrong, and the plan should say so before the first slice:

- A queue that returns the wrong rows is a **silent** defect. Nothing fails, nobody is refused, and
  the work simply does not appear — which is the same shape as M10's missing outbox event and the
  reason that slice needed a gate rather than a fix.
- A queue is a **permission-aware read of somebody else's money**. §19 `:1298` says so twice:
  "permission-aware counts" and "technical admin does not receive full financial detail by
  default". A count is a disclosure; getting it wrong leaks the shape of the business to a role
  that may not see it.
- **The queues are specified as role lists, not as endpoints.** §19 `:1260` names twenty-four
  queues across four roles and document 05 defines a route for none of them. That is the largest
  gap between "what the milestone requires" and "what an approved contract describes" in the
  project so far, and §4 records it as the milestone's central open question.

## The governance survey, done first and stated in full

M10's plan opened with a survey that was **wrong** — it counted three status aggregates where there
were seven, because it searched for table names and the catalogues name business objects. Slice 3
found it. So this survey names what was searched for as well as what was found.

Searched: `report`, `queue`, `dashboard`, `notification` across all four catalogues; then every
model file for a reports table.

| Governance artifact | M11 coverage |
|---|---|
| `permission_catalog.yaml` | **`report.read`** (accountant, manager, business_admin, read_only_auditor) and **`report.export`** — `default_roles: []` with `assignment: explicit_report_export_grant`. No queue permission and no notification permission at all. |
| `status_catalog.yaml` | `notification` and `outbox_event` aggregates exist, both from M9. No report aggregate. |
| `audit_outbox_catalog.yaml` | Eleven outbox events, of which the projection consumes four. No report or queue action. |
| `command_catalog.yaml` | The six manual-review-task rows. Nothing for reports, queues or notifications — consistent with its own stated scope, "query endpoints are excluded". |

**`report.export` is granted to nobody by default, deliberately.** That is not an oversight to
correct: `assignment: explicit_report_export_grant` is the catalogue saying an administrator hands
it out per person. A route guarded by it therefore denies every role until somebody is granted it —
the same shape M4's activation permissions have, and the same test discipline applies.

---

# 2. What already exists, and what that removes from this milestone

Four dependencies are built. One of them is built and **unreachable**, which is where this
milestone starts.

- **`notifications` exists and has no API.** M9 slice 7 built the table doc 04 `:1334` specifies,
  along with the projection and the deduplication index; M10 slice 8 added the fourth event type and the first non-payment-request
  aggregate. Document 05 `:2077` gives it three routes — list, mark-read, mark-all-read — and
  **none of them exists**. A trader cannot read a single notification the system has written for
  them. This is the seventeenth mechanism with no caller in this project and the most consequential
  one, because M9's G-5 decided a failed payment reaches its trader *as a notification* rather than
  as a publication. That decision has been unhonoured since it was made.
- **`manual_review_tasks` exists with all six of document 05 `:2055`'s routes** (M8 slice 3), over
  the table doc 04 `:1312` specifies. Four of §19 `:1260`'s twenty-four queues are views over it, so
  those need filters rather than machinery.
- **The outbox dispatcher and the stale-lease sweep are built and scheduled** — the only two of §19
  `:1318`'s eight jobs that are. `app/workers/celery_app.py`'s beat schedule has exactly two
  entries.
- **`app/storage/reconciliation.py` is written, tested, and has no scheduled caller.** Its only
  entry point is `app/cli/reconcile_storage.py`. §19 `:1318` names storage reconciliation as a
  maintenance job; making it one is wiring, not building.
- **`app/db/pagination.py` is a complete cursor-pagination contract with one caller.** Cursors,
  a sort-field allowlist, `normalise_limit`, and two error types — written for the audit read
  (`app/audit/reading.py`) and used by nothing else. Doc 10 `:382` names pagination in the API
  layer and doc 10 `:1888` lists "queue filters and pagination" among the integration concerns, so
  the contract §19 `:1298` asks for **already exists and is approved by use**. This was found while
  looking for a citation, which is the argument for looking.

**So M11's shape is M8's**: the machinery mostly exists and nothing calls it. The habit that found
all of the above is the one M8 recorded — *look for the helper before writing one* — and it should
be the first act of every slice here.

---

# 3. The slices

Seven, ordered so that the unreachable thing becomes reachable first and the largest open question
is faced before anything is built on top of it.

**Slice 1 is the notification API and nothing else**, because it is the one piece of M11 that is
already decided: three routes in an approved document, a table that exists, and a projection
already writing rows into it. Everything else in this milestone needs a contract decision first.

## Slice 1 — the notifications a trader cannot read

### Goal

Document 05 `:2077`'s three routes, against the table M9 built.

### What it changes

- `GET /api/v1/notifications`, `POST /{id}/mark-read`, `POST /mark-all-read`.
- Scoped by recipient, not by permission: `notifications.recipient_actor_id` is the row's owner and
  `app/security/ownership.py` is what constrains the query. There is no notification permission in
  the catalogue, and inventing one would be a governance act.

### What proves it

- `SEC-NOTIFY-001` — a second trader's notifications are invisible, asserted through `scoped()`
  rather than through a filter a later refactor can drop.
- `SVC-NOTIFY-001` — `mark-all-read` marks **only the caller's own**, and a test with two
  recipients is what makes that observable. The single-recipient version passes against an
  implementation that marks everything.
- `API-NOTIFY-001` — the list is cursor-paginated and stably ordered, per §19 `:1298`. Asserted
  against a page boundary, because an unstable sort is invisible until two rows share a timestamp.

## Slice 2 — the queue contract, and one queue built against it

### Goal

Answer G-1 by building the smallest real queue, so the shape is decided by something that works
rather than by a document nobody has tried.

### What it changes

- One list endpoint per queue, or one endpoint with an allowlisted `queue` parameter — **G-1**.
- The accountant's "new requests" queue (§19 `:1262`'s first), which is a filter over
  `payment_requests` that M5 already reads.
- **`app/db/pagination.py`, reused rather than re-decided.** `ListSpec`, `SortField` and
  `apply_pagination` already express five of §19 `:1298`'s six rules; the sixth — permission-aware
  counts — is the only part this slice invents. Writing a second pagination helper would have been
  the easy path and the wrong one, on M8's rule: look for the helper before writing one.

### What proves it

- `API-QUEUE-001` — §19 `:1298`'s six rules, each asserted separately: cursor pagination, stable
  ordering, allowlisted filters, allowlisted sorting, permission-aware counts, and no unbounded
  read.
- `SEC-QUEUE-001` — the allowlist is an **allowlist**: a filter or sort key not on it is refused
  rather than ignored. Ignoring an unknown sort key returns the wrong page and says nothing.

## Slice 3 — the accountant's remaining ten

### Goal

§19 `:1262`'s eleven, against tables that already exist.

### What it changes

Filters and reads over `payment_requests`, `payment_batches`, `bank_excel_exports`,
`payment_attempts`, `bank_result_bundles`, `incoming_payment_receipts` and `manual_review_tasks`.
No new table and no new command: every row these queues return was written by an earlier milestone.

### What proves it

- `SVC-QUEUE-001` — each of the eleven returns rows in the state it names and **excludes the
  adjacent state**. That second half is the assertion that fails when a filter is one status wide,
  and the first half alone passes against a query returning everything.

## Slice 4 — the manager's four and the warehouse's three

### Goal

§19 `:1276` and `:1283`, and the first consequence of a deviation M10 recorded.

### What it changes

Seven queues. The warehouse's "orders ready for dispatch" is the one to watch: M10 records that no
order ever sits in `ready_for_dispatch`, because slice 7 evaluates the dispatch guard at dispatch
time rather than on confirmation. **That queue cannot be built as a status filter**, and G-2 is the
question it raises.

### What proves it

- `SVC-QUEUE-002` — the manager's four and the warehouse's three each return what their role may
  act on, and the dispatch queue returns orders whose guard **would** pass rather than orders in a
  state nothing writes.

## Slice 5 — technical operations, and what they may not see

### Goal

§19 `:1289`'s six, under §19 `:1298`'s last rule — which is the whole slice: "technical admin does
not receive full financial detail by default."

### What it changes

Failed jobs, stale outbox records, storage reconciliation findings, quarantined files and exports,
backup and health warnings. AI status is excluded: §19 `:1289` admits it "only when enabled", and
no AI path exists.

The redaction rule is not this plan's invention. Doc 12 `:616` describes `technical_admin` as
having "no implicit financial authority", doc 12 `:664` lists what the role does **not**
automatically receive, and doc 12 `:1942` states least privilege outright. §19 `:1298`'s last rule
is those three applied to a queue.

### What proves it

- `SEC-QUEUE-003` — a technical admin's queue rows carry no amount, no IBAN and no trader name,
  asserted over the **response body** rather than over the query. A redaction applied after
  serialisation is one a later serialiser change removes silently.

## Slice 6 — the six maintenance jobs that are not scheduled

### Goal

§19 `:1318` names eight jobs; two are built and scheduled.

### What it changes

Wires `app/storage/reconciliation.py`, which is written and called by nothing but a CLI, and adds
pending upload cleanup, file checksum verification, notification retry and the retention dry run.
Report generation is slice 7's.

**Every one is bounded.** §19 `:1318` says it once and means it for all of them: a job that reads
an unbounded set stops finishing as the database grows, and a maintenance job nobody can finish is
worse than none.

### What proves it

- `OPS-JOB-001` — each job is idempotent under redelivery and bounded by an explicit limit,
  asserted by running it twice against the same state and by planting more rows than the limit.

## Slice 7 — reports, and the Definition of Done

### Goal

§19 `:1331`: **each role can identify and complete its work from controlled queues, and every
operational failure is visible to the responsible role.**

### What it changes

`report.read` and `report.export` exist in the catalogue and nothing uses them. This builds the
permission-gated surface and one report whose content needs no judgement — see G-4.

### What proves it

- `TRACE-M11-001` — the walk. For each of the four roles: sign in, list that role's queues, assert
  each returns only what the role may see, then take one item from one queue through to completion.
  A walk rather than a checklist, for M10's reason: a test that asserted the queues *exist* would
  prove they exist and not that anybody can work from them.

---

# 4. Decisions this plan takes, and questions it does not

## G-1 — the queues have no approved contract, and this is the milestone's central question

§19 `:1260` names twenty-four queues. **Document 05 defines a route for none of them**, and
`command_catalog.yaml` says query endpoints are outside its scope. So there is no approved shape:
not the paths, not whether a queue is an endpoint or a parameter, not the response envelope.

**Taken, on the narrowest reading:** one endpoint per queue under a `/queues/` prefix, named for
the queue §19 names, because a `?queue=` parameter makes the allowlist a runtime value and §19
`:1298` asks for allowlisted filters. Recorded as the implementer's decision, and slice 2 builds
exactly one so that reversing it costs one slice rather than seven.

**What would change if the owner decides otherwise:** the paths and the permission mapping. Nothing
about the filters, the pagination or the redaction.

## G-2 — a queue for a state nothing reaches

§19 `:1283` requires the warehouse's "orders ready for dispatch". M10 records that
`gold_sale_orders.status` never becomes `ready_for_dispatch`: doc 06 §8.2 draws the edge, and slice
7 evaluates the dispatch guard at dispatch time instead, so an order goes from
`incoming_payment_confirmed` straight to `dispatched`.

**Not taken.** Two honest options and they differ in what they claim: make the queue a *derived*
read — orders whose payment guard would pass — or move the order into `ready_for_dispatch` when
confirmation completes, which is what `GoldOrderReadyForDispatch` is already named after. The
second is more faithful to doc 06 `:348`, which draws
`incoming_payment_confirmed --> ready_for_dispatch: normal guard satisfied` as its own edge, and it
changes M10's tested behaviour. **The owner's, because it decides whether "ready for dispatch" is a
stored fact or a computed one.**

## G-3 — `report.export` authorises nobody

`assignment: explicit_report_export_grant` and `default_roles: []`. **Taken as written**: the route
is built and denies every role until an administrator grants it, exactly as M4's activation
permissions do. The test asserting that must be *rewritten, not deleted*, on the day somebody is
granted it.

## G-4 — no report is specified anywhere

§19 `:1318` names "report generation" as a job and §19 `:1260` names no report. `report.read`
exists; no document says what a report contains. **Not taken.** Slice 7 builds the permission-gated
surface and one report whose content is derivable from existing tables without judgement — a queue
count per role — and records that the report catalogue is M0's.

---

# 5. What this plan carries forward

The M10 lessons that apply here specifically.

- **A survey is only as good as its search.** M10's plan miscounted the catalogues because it
  searched for table names where the catalogues name business objects. §1 above states what was
  searched for, so the next reader can check the search rather than the conclusion.
- **A missing thing is silent in a way a wrong thing is not.** M10 shipped a slice with no outbox
  event and every test passed, because none was asked to observe an absence. Queues are made of
  absences: a row that should appear and does not is exactly this shape. **Every queue test asserts
  both what appears and what does not**, and the "does not" half must name a row that exists.
- **A control that goes NOT CAUGHT is usually a defect in the test.** Seven times in M10's last
  four slices: a fixture whose two columns were equal, a privilege query naming the wrong role, two
  guards masking each other, and a trader used to test an internal route when audiences are split
  by host. Diff the sabotage before concluding anything.
- **Look for the helper before writing one.** `app/storage/reconciliation.py` is written and
  scheduled by nothing; it would have been easy to write a second one.
- **A slice splits when its parts have different blockers.** M9 grew from seven to ten and M10 from
  eight to nine that way. Slices 3 and 4 here are the likely candidates, because G-2 blocks one
  queue of one role and nothing else.
