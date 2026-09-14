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

### Slice 2 — backup, and the restore drill that proves it

The exit gate's hardest item. In order: a backup script, an off-server encrypted copy, a
consistency manifest, then a **restore into a clean database followed by reconciliation** —
counts and checksums for files, approvals, publications and audit rows, compared against the
source. The drill is the deliverable; the script is what it needs.

### Slice 3 — the production-like stack and HTTPS

Pinned digests rather than tags, TLS in nginx, private network validation. This is also what
slice 2's drill should run against, so it may merge into slice 2 if the drill needs it first.

### Slice 4 — runbooks, release and rollback

Written against the stack slice 3 produces, and **tested** — §20.4 says "runbook testing", and a
runbook nobody has followed is prose.

### Slice 5 — the remaining test gaps

XSS, log injection, origin checks, performance checks with realistic fixtures. Last because each
is defence in depth over a control that already holds, and none is named by the exit gate.

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
