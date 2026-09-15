# M12 — Security, QA, and Operational Hardening

**Written 2026-09-14, after the frontend completion plan's six slices.** §20 opens at
`15_Agent_Implementation_Plan.md:1337` and lists roughly forty items across three areas;
`15_Agent_Implementation_Plan.md:1376` is operational hardening and
`15_Agent_Implementation_Plan.md:1391` is the exit gate. This is not a restatement of that list: it
is what a survey of the repository found already true, what is genuinely missing, and the order to
close the gaps in.

**The survey is evidence, not estimate, for every claim marked "verified".** Items matched by
keyword and not read are not counted as done — slice 0 settled the ones the exit gate names, and
found the survey wrong about three of them.

---

## What the survey found

### §20.2 Security — mostly built, three real holes

The behavioural security surface is well covered. RBAC and ownership, session revocation, CSRF,
recent-auth, separation of duty, rate limits, runtime database grants and audit immutability all
have tests, most of them integration tests against a real PostgreSQL.

**This section first claimed three headers were missing. All three exist, and the claim was wrong.**
It was made by grepping `infra/nginx/` and `services/backend/app/` — the two places headers *could*
have lived — and not `packages/config/`, where they do.
`packages/config/src/security-headers.mjs:87` applies them to `/:path*` of both applications:

- a full `Content-Security-Policy`, `packages/config/src/security-headers.mjs:2` onward:
  `default-src 'self'`, `base-uri 'self'`, `object-src 'none'`,
  `frame-ancestors 'none'` (`packages/config/src/security-headers.mjs:5`), `form-action 'self'`,
  `connect-src 'self'`, and `style-src 'self' 'unsafe-inline'`
  (`packages/config/src/security-headers.mjs:9`) because Next emits inline bootstrap scripts —
  which the file records at `packages/config/src/security-headers.mjs:10`, deferring the nonce work
  behind the auth/proxy ADR rather than omitting it silently;
- `X-Frame-Options: DENY` at `packages/config/src/security-headers.mjs:21`, with `Referrer-Policy`,
  `X-Content-Type-Options`, `X-DNS-Prefetch-Control`, `Cross-Origin-Opener-Policy: same-origin` and
  `Permissions-Policy` beside it;
- `Strict-Transport-Security` at `packages/config/src/security-headers.mjs:63`, behind
  `SECURITY_HSTS_ENABLED`, together with `upgrade-insecure-requests`.

**The correction is left in place rather than deleted**, because the mistake is the point: a survey
that greps where a thing *ought* to be and concludes it is absent is the same error as a gate that
asserts nothing — it produces a confident answer from an incomplete input. Slice 0 exists for this,
and it caught it one step later than it should have.

### The real finding: most authenticated pages are cacheable

`buildNextHeaderRules` takes `protectedPagePatterns` and applies `no-store` to them
(`packages/config/src/security-headers.mjs:82`); `packages/config/src/security-headers.mjs:92-95`
covers `/api/`, `/files/`, `/downloads/` and `/sw.js`, and nothing else.

**Both applications' lists are stale, and nginx does not cover the gap.**
`infra/nginx/conf.d/local.conf:63` and `infra/nginx/conf.d/local.conf:77` set
`Cache-Control: no-store, private` on `/api/` and `/files/`; `infra/nginx/conf.d/local.conf:83` is
`location /`, the page routes, and sets none. The admin server block repeats the same shape at
`infra/nginx/conf.d/local.conf:117`, `infra/nginx/conf.d/local.conf:131` and
`infra/nginx/conf.d/local.conf:137`.

The lists themselves are `apps/admin-web/next.config.ts:35` and
`apps/trader-pwa/next.config.ts:31`.

| app | listed but no such page | real page, not listed |
|---|---|---|
| admin | `/dashboard`, `/work-queues`, `/payment-requests`, `/payment-batches`, `/audit`, `/settings` | `/requests`, `/batches`, `/queues`, `/admin-users`, `/roles`, `/payment-attempts`, `/incoming-payments`, `/review-tasks`, `/gold-orders`, `/notifications`, `/password`, `/bank-configuration`, `/bank-statements` |
| trader | `/results`, `/publications` | `/beneficiaries`, `/evidence`, `/gold-orders`, `/password` |

Four of the admin app's nine patterns point at pages that were renamed during M5–M7 (`/requests`
and `/batches` were once `/payment-requests` and `/payment-batches`); two never existed. The trader
list omits `/beneficiaries` and `/evidence` — a trader's bank details and their uploaded receipts.

The consequence is bounded but real: a browser may keep an authenticated page in its back/forward
cache and on disk. On a shared machine, pressing Back after sign-out can render a payment queue.

**Nothing would have noticed.** The list went stale silently across three milestones of renames,
which is why the fix is a gate and not an edit.

**"Origin controls" is recorded as considered rather than missing.** §20.2 lists it beside CSRF.
The CSRF design is an HMAC token bound to the session secret, delivered in a `__Host-` cookie with
`SameSite=strict` (`services/backend/app/security/cookies.py:103`), presented in a custom header and
compared in constant time (`services/backend/app/security/cookies.py:134`) — a cross-site form
cannot set the header and a cross-site script cannot read the cookie. An `Origin` check adds defence
in depth and closes nothing this leaves open. **It should still be added**, because
`services/backend/app/security/cookies.py:54` records that `SameSite` does not separate `admin.`
from `trader.` on one site — but it is a second lock, not a missing one, and it is scheduled
accordingly.

**XSS and log-injection tests are absent, and that is a genuine test gap rather than a missing
control.** React escapes by default and `core/logging.py` emits structured JSON; neither has a test
saying so, which means neither would notice the day somebody adds `dangerouslySetInnerHTML` or an
f-string log line.

### §20.3 QA — largely covered, one real absence

Integration, contract, component, concurrency, idempotency, crop, export-integrity,
publication-version and accessibility suites all exist and run in `verify-native.sh`.

**Performance checks are absent.** One keyword match, in the traceability matrix — i.e. the
*requirement* is recorded and nothing implements it. §20.3 asks for "performance checks with
realistic fixtures", and the exit gate does not name them, so this is scheduled after the blocking
work rather than before it.

### §20.4 Operational — **nothing exists**

This is the bulk of M12 and none of it is built:

| item | state |
|---|---|
| production-like Compose stack | only `infra/compose/compose.local.yml:1` |
| pinned immutable images | digests are pinned in CI's trivy gates; the stack uses tags — `infra/compose/compose.local.yml:282`, `infra/compose/compose.local.yml:392` |
| Nginx HTTPS configuration | `infra/nginx/conf.d/local.conf:41` listens on 8080; no TLS block, so nothing to attach HSTS to |
| backup automation | **no script, anywhere** |
| off-server encrypted backup | not started |
| consistency manifest | not started |
| full restore drill | **not started, and it is an exit-gate item** |
| runbook testing | no `docs/runbooks/` |
| monitoring and alert ownership | blocked on OPS-002 |
| release and rollback procedure | no `docs/RELEASE.md` |

---

## The exit gate, and what actually blocks it

§20.5 lists nine conditions. Seven are already met or are met by existing suites. **Two are not,
and one is not ours:**

1. **"backup and full restore drill pass"** — nothing to run. This is the single largest piece of
   M12 and the one with no partial credit: a backup nobody has restored is a belief, not a backup.
2. **"restored files, approvals, publications, and audit records reconcile"** — follows from 1, and
   needs a reconciliation script that does not exist.
3. **"open production-blocking ADRs are resolved"** — **the owner's**, not the implementer's.
   OPS-001 (production secret management and rotation) and OPS-004 (admin network restriction) are
   both open, and both are named in §20.4. No amount of implementation closes them.

---

## Order

Blocking work first, and the ordering is by what the exit gate names rather than by §20's own
sequence.

### Slice 0 — settle the survey — **done 2026-09-14**

The counts above were keyword matches, and a milestone plan built on a keyword count is the same
defect as a gate that reads another gate's artefact: it reports coverage it has not looked at. So
the four suites §20.5 names **by hand** were opened rather than counted:

| suite | tests | covers |
|---|---|---|
| `tests/backend/test_export_integrity.py:1` | 6 | `SVC-INTEGRITY-001` |
| `tests/integration/test_trader_isolation.py:1` | 9 | `SEC-IDOR-001/2/3/5`, `API-PROFILE-001` |
| `tests/integration/test_concurrency_primitives.py:1` | 11 | — no `Covers:` line |
| `tests/integration/test_idempotency_and_command.py:1` | 16 | `CON-IDEM-001`, `CON-VERSION-001` |

All four are substantive. **The exit gate's four test conditions are met today**, which moves the
whole of M12's remaining weight onto §20.4.

Two corrections to the survey above:

- **Performance is not merely absent — it is recorded as deferred.** The single keyword match is
  `tests/backend/test_traceability.py:1240` asserting that `performance_p95` sits in
  `UNFILLABLE_AT_M2`, beside `tests/backend/test_traceability.py:1241` for `PERF-QUEUE-001` in
  `RECORDED_GAPS`; the reason is at `tests/backend/test_traceability.py:89`. That record was written
  to expire, and M12 is where it expires. Scheduled in slice 5 rather than promoted, because the
  exit gate does not name it.
- **Break-glass is genuinely covered** — seven files including
  `tests/backend/test_high_risk_grants.py:1` and `tests/integration/test_role_permissions.py:1`, not
  adjacent matches.

One small finding left open: `tests/integration/test_concurrency_primitives.py:1` carries no
`Covers:` line where every neighbouring suite does. Not chased here; recorded so it is not
discovered twice.

### Slice 1 — every authenticated page is `no-store`, and a gate that keeps it true — **done**

Correct both `protectedPagePatterns` lists, and add a gate comparing them against the pages that
actually exist. The edit is minutes; the gate is the deliverable, because the lists went stale
across three milestones of renames and nothing said so.

The gate needs a notion of "public", and it must be an **explicit allowlist with a reason each** —
`/login`, `/register`, `/offline`, `/states`. A gate that inferred publicness from a path would
quietly excuse the next page somebody forgets. (`health/` turned out to be a `route.ts` in both
applications and therefore not a page at all; the gate refused it as a public *page*, which was
right — an exemption from a rule that never applied is its own kind of untruth.)

### What proves it

- `CI-CACHE-001` — `tests/backend/test_authenticated_pages_are_not_cacheable.py:1` compares each
  application's `protectedPagePatterns` against the directories under `app/` that contain a
  `page.tsx`, **in both directions**: a page nothing marks `no-store`, and a pattern with no page
  behind it. The second is what let the first hide — nine entries of which four were dead looked
  longer than their coverage. Five negative controls in `scripts/sabotage-m12-slice-1.sh:1`, one per
  way the two lists drifted apart, and the gate failed five times against its author's own data
  before it went green.

### Slice 2 — backup, and the restore drill that proves it — **done 2026-09-14**

The exit gate's hardest item, and the one with no partial credit.

`infra/scripts/backup.sh:1` dumps the database from inside the container, copies the storage tree,
writes a manifest and encrypts the bundle with `gpg --symmetric` — no external key service, which
is the same constraint the owner's 2026-09-13 secrets decision answers.
`infra/scripts/restore.sh:1` puts it back, and **refuses a database that already has rows** unless
`--force` is given. `infra/scripts/backup_manifest.py:1` decides what "reconcile" means.
`tests/integration/test_backup_restore_drill.py:1` is the drill: seed, back up, restore into a
second clean database and an empty storage tree, compare.

**Three of six negative controls were NOT CAUGHT on the first run, and all three were defects in the
tests rather than in the scripts.** Each is recorded where it was found:

- **The content digests were unreachable.** Every provoking test deleted rows, which a count alone
  catches, so replacing every digest with a constant changed nothing.
  `test_a_row_changed_without_changing_the_count_is_reported` now provokes the case a count cannot
  see — same rows, different money.
- **The database refusal was masked by the storage refusal.** After one restore both the database
  and the storage directory are non-empty, so removing the database check entirely still produced a
  refusal and the test still passed. It asserted "something refused", which is not the claim in its
  name.
- **The storage digest was indistinguishable from a size comparison**, because the provoking test
  emptied a file. The bytes are now replaced with the same number of different bytes.

That is the third and fourth time in this milestone that a negative control has found one of my own
assertions weaker than its name. No green test run showed any of it.

### What proves it

- `OPS-BACKUP-001` — a backup restores into a **clean** database and reconciles: every table §20.5
  names, every other table carrying state, and the bytes of every stored file.
  `test_a_backup_restores_into_a_clean_database_and_reconciles` asserts the reconciliation rather
  than the exit code, because `pg_restore` exits zero having skipped objects it could not create.
- `OPS-BACKUP-002` — the restore **refuses a populated target**. Restoring over rows that are
  already there reconciles with any manifest, which is how a drill passes while proving nothing —
  and how one run against production destroys it. Six controls in
  `scripts/sabotage-m12-slice-2.sh:1`, each producing a backup that runs and a restore that
  succeeds.

**What this slice does not prove**: that grants and ownership survive. `pg_restore --no-owner`
leaves every object owned by the restoring role, and handing ownership back is a step slice 4's
runbook owes. The drill reads the restored database as the role that restored it, and says so,
rather than connecting as whichever role happens to work.

### Slice 3 — the production-like stack and HTTPS — **done 2026-09-14**

`infra/compose/compose.prod.yml:1` is an **overlay**, not a second stack: everything already true of
`infra/compose/compose.local.yml:1` — `no-new-privileges`, `cap_drop: ALL`, `read_only`, log
rotation, healthchecks, three networks — stays true without being restated. A standalone production
file would be a copy, and copies drift; that is what `infra/verification/lint_targets.txt:1` exists
to record about two copies of one list.

It changes three things: images pinned **by digest**, TLS terminated in nginx on 443, and
`SECURITY_HSTS_ENABLED` set — which `packages/config/src/security-headers.mjs:61` reads, and which
must never be true on a stack without a certificate.

**OPS-004's answer is one file.** `infra/nginx/deployment/admin-access.conf:1` is the whole of it:
today `allow all;` with the consequence written beside it, and restricting the panel is editing that
file and reloading — no image rebuild, no restart, no session lost. **That does not close OPS-004**,
and §20.5 still requires it resolved.

### What `nginx -t` found that reading did not

The first draft parsed in my head and not in nginx. Three defects, each of which would have shipped:

- **`${TRADER_HOST}` is nine literal characters.** The official image substitutes `${VAR}` only in
  `/etc/nginx/templates/*.template`, through an entrypoint `infra/docker/nginx.Dockerfile:29`
  replaces with `ENTRYPOINT []` — and `read_only: true` means nothing could write the result anyway.
- **`admin-access.conf` in `conf.d/` would have restricted traders too.**
  `infra/nginx/nginx.conf:31` includes `conf.d/*.conf` at `http` level, so its `allow` rules would
  have applied to every server block. The file's own comment warned against exactly that while its
  placement caused it.
- **A production file beside `local.conf` gives nginx two of every upstream** and it refuses to
  start.

All three are fixed by `infra/nginx/deployment/`, a directory the wildcard include does not sweep
up, holding one decision per file.

### What proves it

- `OPS-STACK-001` — `tests/backend/test_production_stack.py:1` asserts every third-party image is
  pinned by digest **and** that the overlay pins every image the local stack pulls: an overlay that
  pinned one and dropped another would satisfy the first check while shipping from a moving tag.
- `OPS-STACK-002` — the production nginx serves every location the local one does, **counted per
  audience**, sets every header the local one sets plus HSTS, has no plaintext listener, and applies
  the admin access rule to the admin block alone.

Eight negative controls in `scripts/sabotage-m12-slice-3.sh:1`, and control 0 asserts both that the
suite is green and that the configuration **parses**. One was NOT CAUGHT: the location comparison
was set-based, so removing `/files/` from one of the two audiences left the path present and the
check silent — every trader would have got a 404 for every receipt. It counts now.

### Slice 4 — runbooks, release and rollback — **done 2026-09-15**

`15_Agent_Implementation_Plan.md:2110` names four — deployment, rollback/forward-fix, incident and
restore — and `infra/runbooks/secret-rotation.md:1` is the fifth, OPS-001's answer written where it
is used rather than in a decision register nobody opens during a rotation.

**"Runbook testing" is answered honestly rather than claimed.** Three of the five cannot be executed
without a server with a certificate and a domain, which is M13's, and each says so in its own words.
What `tests/backend/test_runbooks.py:1` asserts is the half that rots:

- every script a runbook names exists, and **accepts the flags it is told to pass**;
- every database column its diagnostic queries name exists in the models;
- every setting `secret-rotation.md` tells an operator to rotate is one `.env.example` declares;
- every runbook says how it is tested, including when the answer is "it is not".

`infra/runbooks/restore.md:1` is the exception: steps 1, 2 and 4 are executed on every verifier run
by slice 2's drill. Step 3 — re-applying `020-runtime-roles.sql` — is the step the drill
deliberately does not cover, and this runbook is now the only place it is recorded.

### What the gate caught while being written

**The runbooks named `--database-url` on scripts that still took `--container`.** This branch
carried slice 2's pre-CI interface, so every restore instruction would have failed on its first
argument. That is exactly the failure this gate exists for, found before it shipped rather than
during a recovery.

Two negative controls were NOT CAUGHT and both were the gate reading too narrowly:

- the column check read only what lay between `SELECT` and `FROM`, so a rename inside a `WHERE`
  clause was invisible — and `incident.md`'s audit-chain query does all of its work in `WHERE`;
- the first fix then matched across markdown, from a `SELECT` in one block through the prose to a
  semicolon in the next, and reported that "money" and "should" are not columns. **A check whose
  first output is nonsense gets an exception added to it rather than being fixed**, so it is scoped
  to fenced blocks now.

### What proves it

- `OPS-RUNBOOK-001` — `tests/backend/test_runbooks.py:1`, with seven negative controls in
  `scripts/sabotage-m12-slice-4.sh:1`. Each leaves a runbook that reads perfectly and instructs
  somebody to do something that will not work: a renamed flag, a moved script, a renamed column, a
  setting nothing reads, the missing ownership step, a runbook that stops saying whether it is
  tested, and a required runbook deleted from a directory that still looks full.

### Slice 5 — the remaining test gaps — **done 2026-09-15**

XSS, log injection, origin checks, performance checks with realistic fixtures. Last because each
is defence in depth over a control that already holds, and none is named by the exit gate.

Three of the four were **protections that were already true and had no test**, which is the weakest
state a control can be in: it holds today and nothing notices the day it stops. React escapes
interpolated text by default; `JsonFormatter` emits one JSON object per line; and the CSRF token
was carrying the whole cross-origin burden alone.

#### A real defect, in the file an operator reads first

`U+2028` and `U+2029` passed through `app/core/logging.py` unescaped. To `json.dumps` they are
ordinary characters; to a JavaScript engine they are **line terminators**, so a browser-based log
viewer renders one record as two — the log-injection property itself, in the evidence
`infra/runbooks/incident.md` tells an operator to read before deciding whether money moved. Two
`str.replace` calls at the end of `format`, and a test that asserts on the output rather than on
the design.

#### The origin check, and why its permissive half is the assertion that matters

`app/security/cookies.py` already records that `SameSite` is a claim about *sites*, and that
`trader.` and `admin.` are the same site. `_refuse_a_foreign_origin` is the boundary `SameSite`
cannot draw. It closes nothing the CSRF token leaves open; it is a second lock, not a replacement.

**An absent `Origin` is allowed, and the test asserts that half too.** A test of the refusal alone
passes against a rule that refuses everything — which is what "tightening" looks like from the
inside, and which breaks every non-browser caller while closing nothing a browser could do.

#### The performance measurement, and what it found

`PERF-QUEUE-001` is **discharged, not deferred again.** Its reason named two things M2 could not
produce — a representative volume and a production-shaped environment — and slice 3 built the
second while `tests/integration/test_queue_performance.py` builds the first: 50,000 payment
requests with 5,000 unworked in the accountant's first queue, a month of intake with nobody
reviewing.

**No wall-clock threshold is asserted**, because a millisecond bound measured on a shared runner is
a flake generator and a flaky gate gets its threshold raised until it asserts nothing. What is
asserted is how many rows the database touches to return one page — a property of the plan, not of
the machine. The latency is *recorded*, with its volume and environment beside it, which is the
obligation's own wording: "recorded p95 and queue timings with volume and environment captured
alongside".

| queue | plan | rows touched | p95 |
|---|---|---|---|
| `new-requests` | bitmap index scan, then sort | 5,000 — the queue | 2.8 ms |
| `correction-responses` | bitmap index scan, then sort | 5,000 — the queue | 1.7 ms |
| `eligible-for-batching` | index scan | 0 — the queue was empty | 0.5 ms |
| `trader-disputes` | **sequential scan** | **50,000 — the table** | 11.1 ms |

**`trader-disputes` is the one read whose cost tracks all history rather than its own depth.**
`trader_disputed_at IS NOT NULL` is covered by no index, and `app/db/pagination.py:17-20` states
this exact failure mode as the reason sort and filter fields are allowlisted — here it is the
queue's own predicate rather than a caller's filter, so the allowlist cannot see it. Compounding
it, `app/queues/payment_requests.py:118` records that **no command resolves a dispute**, so the
queue never drains.

It is **recorded rather than fixed, and the measurement is the reason**: 11 ms at fifty thousand
rows projects to roughly 110 ms at half a million, which is a decade of this platform's traffic,
and an index is paid for on every insert and every status change of the busiest table in the
system. The one-line migration is written out in the test's docstring for whoever decides it is
time. Nothing blocks it — `test_schema_matches_the_specification.py` checks that document 04's
indexes exist, not that no others do — so this is a decision, not an obstacle.

**Two long-standing comments are answered.** `app/db/models/payment_request.py:211` and
`alembic/versions/20260820_0017_batching_tables.py:564` both record that
`idx_payment_request_accountant_queue` looks redundant and both decline to drop it for want of a
measurement. The planner chose it for `eligible-for-batching` and chose the other for
`new-requests`. Both are used; the question is closed.

#### What the work caught in itself

- **The count test measured a query nobody runs.** It rebuilt `read_queue_page`'s count the same
  way `read_queue_page` does, so the control that made the count scan the whole table went
  **NOT CAUGHT** — every number it produced was correct and none of them came from the code under
  test. Both statements are captured from the production call now, through the engine event that
  sees what is sent to the server. This is the same defect as a gate reading another gate's
  artefact, wearing different clothes.
- **`Actual Rows` is the wrong field to bound.** On a scan node it reports what *survived* the
  filter, so a sequential scan of fifty thousand rows returning none reads as zero, and a bound
  written against it would pass against the exact plan it exists to refuse. `Rows Removed by
  Filter` and `Rows Removed by Index Recheck` are added back in, and the `trader-disputes` finding
  is only visible because of it.
- **A suite that was green for a reason outside itself.** `tests/integration/` could import
  `scripts.emit_evidence` only because `tests/backend/conftest.py` had already put
  `services/backend` on `sys.path` — the editable install maps `app` and nothing else. The
  verifier always runs both directories, so the test would have passed there and failed when run
  alone. The integration conftest inserts it now.
- **`restore_drill`'s unfilled reason had gone stale.** It said "no restore drill has been
  performed", which slice 2 made false — while the field's conclusion stayed right, because
  ADR-004 is open for a different reason: the RPO and RTO targets, the restore authority, and who
  owns the off-server copy. A reader of the evidence artifact was being told something untrue about
  the exact thing they were checking. Corrected, and the new test checks the cited drill exists so
  it cannot go stale in the other direction either.

### What proves it

- `SEC-XSS-001`, `SEC-LOGINJ-001` — `tests/backend/test_injection_surfaces.py:1`, six tests, with
  six negative controls in `scripts/sabotage-m12-slice-5.sh:1`. Controls 1 and 2 add
  `dangerouslySetInnerHTML` and a bare `innerHTML =` to a component that already manipulates DOM
  geometry for legitimate reasons; control 3 restores the `U+2028` defect; control 5 makes the
  origin check refuse an absent header, which reads as stricter and is the one that breaks every
  non-browser caller.
- `PERF-QUEUE-001` — `tests/integration/test_queue_performance.py:1`, seven tests, with eight
  negative controls in `scripts/sabotage-m12-slice-5b.sh:1`. Each leaves a system that answers
  every request correctly and returns the same rows; only the cost changes, which is why no other
  suite in the repository would notice any of them. Control 2 replaces the row count with the naive
  `Actual Rows` reading, and control 8 records a measurement for the three fast queues while
  omitting the slow one — every number in it correct, and the omission the whole point.
- The evidence emitter's half — `tests/backend/test_evidence_emitter.py:1` asserts it reads the
  measurement whole, refuses a partial one, refuses an unreadable one, and says so rather than
  inventing a figure when a run took none. `tests/backend/test_traceability.py:1` asserts the gap
  is closed in both places a reader might look, **and that the field was filled rather than merely
  deleted** — an emitter that dropped it entirely would satisfy the first two checks while
  reporting nothing at all about performance.

---

## What this plan does not cover

**UAT dataset preparation is M13's**, though §20.3 lists it. The dataset's shape depends on what
the owner wants to exercise, and preparing one before that conversation would be building fixtures
to a guess.

**Monitoring and alert ownership is blocked on OPS-002**, which is open. §20.4 lists it; the safe
default is structured redacted diagnostics, which exists.

**Nothing here resolves an ADR.** OPS-001 and OPS-004 are the owner's decisions and they block the
exit gate. They should be asked early, because slice 3's stack and slice 4's runbooks both change
shape depending on the answers — a stack built for open admin access is not the one built for a
VPN-only panel.
